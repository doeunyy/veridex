"""Asynchronous LangGraph service scoped to the existing persistent MCP registry."""

import asyncio
import math
from collections import Counter
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from veridex.agent.graph import build_agent_graph
from veridex.agent.prompts import MCP_AGENT_SYSTEM_PROMPT
from veridex.config import settings
from veridex.mcp.client import MCPClientError, ToolRegistry, connect_servers

_REQUIRED_TOOLS = {"search_evidence", "search_web", "list_documents", "read_document"}


def _tool_error(exc: Exception) -> str:
    # Keep status=error without exposing provider exception payloads or connection secrets.
    return "MCP tool execution failed. No usable evidence was returned; do not cite this failure."


class MCPAgentService:
    """Async-only agent interface; construct through open_mcp_agent_service.

    A single InMemorySaver preserves thread_id memory. Per-session locks prevent
    overlapping turns in the same conversation; different sessions can run concurrently.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        model,
        checkpointer=None,
        recursion_limit: int = 12,
        turn_timeout: float = 120,
    ):
        if not registry.is_active:
            raise MCPClientError("MCP registry is not active.")
        if set(registry.entries) != _REQUIRED_TOOLS:
            raise MCPClientError("MCP agent requires exactly the four production tools.")
        if type(recursion_limit) is not int or not 2 <= recursion_limit <= 50:
            raise ValueError("recursion_limit must be an integer between 2 and 50.")
        if not math.isfinite(turn_timeout) or turn_timeout <= 0:
            raise ValueError("turn_timeout must be positive and finite.")
        self.registry = registry
        self.recursion_limit = recursion_limit
        self.turn_timeout = turn_timeout
        self._closed = False
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._origins = {
            name: {
                "server": entry.server,
                "server_identity": registry.servers[entry.server].serverInfo.name,
            }
            for name, entry in registry.entries.items()
        }
        self.checkpointer = InMemorySaver() if checkpointer is None else checkpointer
        self.graph = build_agent_graph(
            tools=registry.tools,
            model=model,
            checkpointer=self.checkpointer,
            async_mode=True,
            system_prompt=MCP_AGENT_SYSTEM_PROMPT
            + f"\nCurrent date: {datetime.now(UTC).date().isoformat()}.",
            handle_tool_errors=_tool_error,
        )

    def _ensure_open(self):
        if self._closed or not self.registry.is_active:
            raise MCPClientError("MCP agent service is closed.")

    def _lock(self, session_id: str) -> asyncio.Lock:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Session ID cannot be empty.")
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    async def achat(self, query: str, session_id: str) -> str:
        return (await self.achat_with_trace(query, session_id))["response"]

    async def aget_history(self, session_id: str):
        async with self._lock(session_id):
            self._ensure_open()
            state = await self.graph.aget_state({"configurable": {"thread_id": session_id}})
            return deepcopy(state.values.get("messages", []))

    async def _finish_interrupted_round(self, config, result):
        """Close unanswered ToolCalls with error markers, never fabricate tool execution."""
        messages = result.get("messages", [])
        answered = {message.tool_call_id for message in messages if message.type == "tool"}
        pending = [
            call
            for message in messages
            if message.type == "ai"
            for call in message.tool_calls
            if call["id"] not in answered
        ]
        if pending:
            failures = [
                ToolMessage(
                    content="Agent execution stopped before a verified tool result was available.",
                    name=call["name"],
                    tool_call_id=call["id"],
                    status="error",
                    additional_kwargs={"execution_interrupted": True},
                )
                for call in pending
            ]
            await self.graph.aupdate_state(config, {"messages": failures}, as_node="tools")
            return (await self.graph.aget_state(config)).values
        return result

    async def achat_with_trace(self, query: str, session_id: str) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")
        async with self._lock(session_id):
            self._ensure_open()
            config = {
                "configurable": {"thread_id": session_id},
                "recursion_limit": self.recursion_limit,
            }
            previous = await self.graph.aget_state(config)
            previous_ids = {message.id for message in previous.values.get("messages", [])}
            error = None
            try:
                async with asyncio.timeout(self.turn_timeout):
                    result = await self.graph.ainvoke(
                        {"messages": [HumanMessage(content=query)]},
                        config=config,
                    )
                response = result["messages"][-1].content
                if not isinstance(response, str):
                    raise TypeError("Expected a text-only agent response.")
            except (GraphRecursionError, TimeoutError) as exc:
                error = (
                    "recursion_limit" if isinstance(exc, GraphRecursionError) else "turn_timeout"
                )
                snapshot = await self.graph.aget_state(config)
                result = await self._finish_interrupted_round(config, snapshot.values)
                response = "I could not complete this request within the agent limits. No final answer is verified."
            messages = [
                message for message in result.get("messages", []) if message.id not in previous_ids
            ]
            calls = []
            results = []
            for message in messages:
                if message.type == "ai":
                    for call in message.tool_calls:
                        calls.append(
                            {
                                "id": call["id"],
                                "name": call["name"],
                                "args": deepcopy(call["args"]),
                                **self._origins.get(call["name"], {}),
                            }
                        )
                elif message.type == "tool":
                    artifact = deepcopy(message.artifact)
                    results.append(
                        {
                            "name": message.name,
                            "tool_call_id": message.tool_call_id,
                            "status": message.status,
                            "invocation_completed": message.name in self._origins
                            and not message.additional_kwargs.get("execution_interrupted", False),
                            **self._origins.get(message.name, {}),
                            "content": deepcopy(message.content),
                            "content_preview": str(message.content)[:300],
                            "artifact": artifact,
                            "structured_content": (
                                artifact.get("structured_content")
                                if isinstance(artifact, dict)
                                else None
                            ),
                        }
                    )
            return {
                "response": response,
                "status": "error" if error else "success",
                "error": error,
                "tool_calls": calls,
                "tool_results": results,
                "call_counts": dict(
                    Counter(item["name"] for item in results if item["invocation_completed"])
                ),
                "server_call_counts": dict(
                    Counter(
                        item["server"]
                        for item in results
                        if "server" in item and item["invocation_completed"]
                    )
                ),
            }

    async def aclose(self):
        """Reject new turns and drain current turns before the factory closes MCP sessions."""
        self._closed = True
        for lock in list(self._session_locks.values()):
            async with lock:
                pass


@asynccontextmanager
async def open_mcp_agent_service(
    connections=None,
    *,
    model=None,
    checkpointer=None,
    recursion_limit=12,
    turn_timeout=120,
    request_timeout=45,
):
    """Own the registry and AgentService together; enter/exit in the same async task."""
    if model is None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        # Leave temperature at the model's default (reasoning models may reject temperature=0).
        model = ChatOpenAI(
            model=settings.openai_model, api_key=settings.openai_api_key, timeout=45, max_retries=1
        )
    async with connect_servers(connections, timeout=request_timeout) as registry:
        service = MCPAgentService(
            registry,
            model=model,
            checkpointer=checkpointer,
            recursion_limit=recursion_limit,
            turn_timeout=turn_timeout,
        )
        try:
            yield service
        finally:
            await service.aclose()
