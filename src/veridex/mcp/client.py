"""Dynamic adapter tools backed by explicitly scoped multi-server MCP sessions."""

import asyncio
import math
import re
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import InitializeResult, Tool

from veridex.config import Settings, settings
from veridex.observability import execution

DEFAULT_TIMEOUT_SECONDS = 45
_SERVER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class MCPClientError(RuntimeError):
    """Connection, discovery, or lifecycle failure without raw connection details."""


def tavily_connection(config: Settings | None = None) -> Connection:
    """Tavily Remote MCP over Streamable HTTP; the key travels only as a query parameter."""
    config = config or settings
    key = (config.tavily_api_key or "").strip()
    if not key:
        raise MCPClientError("TAVILY_API_KEY is not configured.")
    return {
        "transport": "streamable_http",
        "url": f"{config.tavily_mcp_url}?{urlencode({'tavilyApiKey': key})}",
    }


def default_connections(
    *,
    project_root: Path | None = None,
    config: Settings | None = None,
    python_executable: str | None = None,
    include_remote: bool = True,
) -> dict[str, Connection]:
    """Local STDIO servers plus Tavily Remote MCP; construction starts no processes.

    Secrets are passed only to the relevant child environment or remote URL, never to
    CLI inspection output or error messages.
    """
    root = (project_root or Path(__file__).resolve().parents[3]).resolve()
    config = config or settings

    def path(value: Path) -> str:
        return str(value if value.is_absolute() else root / value)

    environments = {
        "evidence": {
            "OPENAI_API_KEY": config.openai_api_key or "",
            "OPENAI_EMBEDDING_MODEL": config.openai_embedding_model,
            "CHROMA_PERSIST_DIR": path(config.chroma_persist_dir),
            "CHROMA_COLLECTION": config.chroma_collection,
            "PROVIDER_TIMEOUT_SECONDS": str(config.provider_timeout_seconds),
            "PROVIDER_MAX_RETRIES": str(config.provider_max_retries),
        },
        "workspace": {
            "DOCUMENTS_DIR": path(config.documents_dir),
            "CORPUS_MANIFEST_PATH": path(config.corpus_manifest_path),
        },
        "catalog": {"CATALOG_PATH": path(config.catalog_path)},
    }
    connections: dict[str, Connection] = {
        name: {
            "transport": "stdio",
            "command": python_executable or sys.executable,
            "args": ["-m", f"veridex.mcp.servers.{name}"],
            "cwd": str(root),
            "env": {"PYTHONPATH": str(root / "src"), **environment},
        }
        for name, environment in environments.items()
    }
    if include_remote:
        connections["tavily"] = tavily_connection(config)
    return connections


def create_client(connections: dict[str, Connection] | None = None) -> MultiServerMCPClient:
    """Create a lazy SDK client with raw tool names and explicit execution errors."""
    connections = deepcopy(default_connections() if connections is None else connections)
    if not isinstance(connections, dict) or not connections:
        raise MCPClientError("At least one MCP server connection is required.")
    for name, connection in connections.items():
        if not isinstance(name, str) or not _SERVER_ID.fullmatch(name):
            raise MCPClientError("Invalid MCP server configuration identifier.")
        if not isinstance(connection, dict):
            raise MCPClientError(f"Invalid connection configuration for server '{name}'.")
        transport = connection.get("transport")
        if transport == "stdio":
            if (
                not isinstance(connection.get("command"), str)
                or not connection["command"]
                or not isinstance(connection.get("args"), list)
                or not all(isinstance(arg, str) for arg in connection["args"])
            ):
                raise MCPClientError(f"Invalid STDIO connection for server '{name}'.")
        elif transport in {"http", "streamable_http", "streamable-http", "sse", "websocket"}:
            if not isinstance(connection.get("url"), str) or not connection["url"]:
                raise MCPClientError(f"Missing MCP URL for server '{name}'.")
            address = urlsplit(connection["url"])
            schemes = {"ws", "wss"} if transport == "websocket" else {"http", "https"}
            if address.scheme not in schemes or not address.hostname:
                raise MCPClientError(f"Invalid MCP URL for server '{name}'.")
        else:
            raise MCPClientError(f"Unsupported MCP transport for server '{name}'.")
    # Errors must not become ordinary success-looking text when invoked without a ToolCall.
    return MultiServerMCPClient(connections, tool_name_prefix=False, handle_tool_errors=False)


@dataclass(frozen=True)
class DiscoveredTool:
    server: str
    protocol_tool: Tool
    langchain_tool: BaseTool


class ToolRegistry:
    """Session-bound tools. Use only within connect_servers' active async context."""

    def __init__(self, client: MultiServerMCPClient, timeout: float):
        self._client = client
        self._timeout = timeout
        self._sessions = {}
        self._locks = {name: asyncio.Lock() for name in client.connections}
        self._refresh_lock = asyncio.Lock()
        self._active = False
        self.servers: dict[str, InitializeResult] = {}
        self.entries: dict[str, DiscoveredTool] = {}

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def tools(self) -> list[BaseTool]:
        return [entry.langchain_tool for entry in self.entries.values()]

    async def _intercept(self, request, handler):
        server = request.server_name
        with execution("mcp_tool", server=server, tool=request.name) as fail_protocol:
            result = await self._intercept_observed(request, handler)
            if getattr(result, "isError", False) is True or (
                isinstance(result, ToolMessage) and result.status == "error"
            ):
                fail_protocol()
            return result

    async def _intercept_observed(self, request, handler):
        server = request.server_name
        async with self._locks[server]:
            if not self._active:
                raise MCPClientError("MCP tool registry is closed.")
            try:
                async with asyncio.timeout(self._timeout):
                    return await handler(request)
            except TimeoutError:
                raise MCPClientError(f"MCP server '{server}' tool request timed out.") from None
            except Exception:  # noqa: BLE001 — redact transport/session details
                raise MCPClientError(f"MCP server '{server}' tool request failed.") from None

    async def refresh(self) -> list[BaseTool]:
        """Rediscover on existing sessions, publishing a registry only after all succeed."""
        async with self._refresh_lock:
            discovered = {}
            for server, session in self._sessions.items():
                async with self._locks[server]:
                    if not self._active:
                        raise MCPClientError("MCP tool registry is closed.")
                    try:
                        async with asyncio.timeout(self._timeout):
                            cursor = None
                            seen = set()
                            tools = []
                            while True:
                                result = await session.list_tools(cursor=cursor)
                                tools.extend(result.tools)
                                cursor = result.nextCursor
                                if not cursor:
                                    break
                                if cursor in seen or len(seen) >= 100:
                                    raise MCPClientError("Invalid MCP tool-list pagination.")
                                seen.add(cursor)
                    except Exception:  # noqa: BLE001 — redact raw discovery details
                        raise MCPClientError(
                            f"Tool discovery failed for MCP server '{server}'."
                        ) from None
                for tool in tools:
                    if tool.name == "protocol_echo":
                        continue
                    if tool.name in discovered:
                        previous = discovered[tool.name].server
                        raise MCPClientError(
                            f"Duplicate MCP tool name '{tool.name}' on '{previous}' and '{server}'."
                        )
                    converted = convert_mcp_tool_to_langchain_tool(
                        session,
                        tool,
                        server_name=server,
                        callbacks=self._client.callbacks,
                        tool_interceptors=[self._intercept],
                        handle_tool_errors=False,
                    )
                    discovered[tool.name] = DiscoveredTool(server, tool, converted)
            self.entries = discovered
            return self.tools

    async def invoke(
        self, name: str, arguments: dict, *, call_id: str | None = None
    ) -> ToolMessage:
        """Invoke an adapter tool with a ToolCall envelope, preserving structured artifacts."""
        if not self._active:
            raise MCPClientError("MCP tool registry is closed.")
        if name not in self.entries:
            raise MCPClientError(f"Unknown discovered MCP tool '{name}'.")
        return await self.entries[name].langchain_tool.ainvoke(
            {
                "name": name,
                "args": arguments,
                "id": call_id or str(uuid4()),
                "type": "tool_call",
            }
        )

    def inspection(self) -> dict:
        """Report protocol identities and schemas, without commands, environments, or secrets."""
        return {
            "servers": [
                {
                    "id": server,
                    "identity": info.serverInfo.model_dump(mode="json"),
                    "tools": [
                        {
                            "name": entry.protocol_tool.name,
                            "description": entry.protocol_tool.description or "",
                            "input_schema": entry.protocol_tool.inputSchema,
                            "output_schema": entry.protocol_tool.outputSchema,
                        }
                        for entry in self.entries.values()
                        if entry.server == server
                    ],
                }
                for server, info in self.servers.items()
            ]
        }


@asynccontextmanager
async def connect_servers(
    connections: dict[str, Connection] | None = None, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
):
    """Retain one process/session per server; serialize calls and clean up on every exit.

    Enter and exit in the same async task (MCP SDK/AnyIO context-manager requirement).
    Tool calls from other tasks are supported and serialized per server. Do not use
    returned tools after exit. Closing drains active calls up to their request deadlines.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise MCPClientError("MCP request timeout must be positive.")
    client = create_client(connections)
    registry = ToolRegistry(client, timeout)
    failure = None
    try:
        async with AsyncExitStack() as stack:
            try:
                # Keep SDK context entry/exit in this task; do not gather context-manager entry.
                for server in client.connections:
                    try:
                        async with asyncio.timeout(timeout):
                            session = await stack.enter_async_context(
                                client.session(server, auto_initialize=False)
                            )
                            info = await session.initialize()
                    except Exception:  # noqa: BLE001 — redact raw connection/handshake details
                        raise MCPClientError(
                            f"Could not connect to MCP server '{server}'."
                        ) from None
                    registry._sessions[server] = session
                    registry.servers[server] = info
                registry._active = True
                await registry.refresh()
            except Exception as exc:  # noqa: BLE001 — preserve failure until SDK contexts are closed
                failure = exc
            if failure is None:
                try:
                    yield registry
                except BaseException as exc:  # noqa: BLE001 — preserve cancellation/body errors
                    failure = exc
            registry._active = False
            async with registry._refresh_lock:
                for lock in registry._locks.values():
                    async with lock:
                        pass
    except Exception:  # noqa: BLE001 — SDK task-group teardown can raise raw transport exceptions
        registry._active = False
        raise MCPClientError("MCP session lifecycle failed.") from None
    # Raise outside SDK contexts, which can otherwise suppress or group startup failures.
    if failure is not None:
        raise failure
