"""Async service around the supervisor graph: sessions, turn limits and the MCP lifecycle."""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from time import monotonic

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from veridex.agents.graph import build_graph
from veridex.agents.state import WORKERS
from veridex.agents.tools import shared_tools, tools_by_agent
from veridex.config import Settings, settings
from veridex.llm.providers import Provider
from veridex.mcp.client import MCPClientError, ToolRegistry, connect_servers, default_connections
from veridex.observability import observed

REQUIRED_SERVERS = {"evidence", "workspace", "catalog", "tavily"}


class SessionCapacityError(RuntimeError):
    """All session slots are in use; no conversation was evicted."""


class MultiAgentService:
    """One compiled graph shared by all sessions; turns in one session never overlap."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        config: Settings | None = None,
        factory: Callable[[Provider], BaseChatModel] | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        turn_timeout: float | None = None,
    ):
        if not registry.is_active:
            raise MCPClientError("MCP registry is not active.")
        self.registry = registry
        self.config = config or settings
        self.tools = tools_by_agent(registry.tools)
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = build_graph(
            self.tools, config=self.config, factory=factory, checkpointer=self.checkpointer
        )
        self.turn_timeout = turn_timeout or self.config.api_request_timeout_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, float] = {}
        self._admin = asyncio.Lock()

    @property
    def is_usable(self) -> bool:
        return self.registry.is_active

    def describe(self) -> dict:
        """Agent/tool wiring for the UI and docs; contains no secrets."""
        return {
            "agents": {agent: sorted(t.name for t in self.tools[agent]) for agent in WORKERS},
            "shared_tools": shared_tools(),
        }

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Session ID cannot be empty.")
        async with self._admin:
            now = monotonic()
            for key in [
                key
                for key, used in self._last_used.items()
                if not self._locks[key].locked()
                and now - used >= self.config.agent_session_ttl_seconds
            ]:
                await self.checkpointer.adelete_thread(key)
                del self._locks[key], self._last_used[key]
            if session_id not in self._locks:
                if len(self._locks) >= self.config.agent_max_sessions:
                    raise SessionCapacityError("Session capacity exhausted.")
                self._locks[session_id] = asyncio.Lock()
            self._last_used[session_id] = now
            return self._locks[session_id]

    async def achat(self, query: str, session_id: str) -> str:
        return (await self.achat_with_trace(query, session_id))["response"]

    @observed("agent")
    async def achat_with_trace(self, query: str, session_id: str) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")
        if not self.is_usable:
            raise MCPClientError("Agent service is closed.")
        lock = await self._lock_for(session_id)
        async with lock:
            config = {
                "configurable": {"thread_id": session_id},
                "recursion_limit": 2 * self.config.supervisor_max_hops + 4,
            }
            async with asyncio.timeout(self.turn_timeout):
                state = await self.graph.ainvoke(self.turn_input(query), config=config)
            self._last_used[session_id] = monotonic()
        return self.turn_output(state)

    @staticmethod
    def turn_input(query: str) -> dict:
        # None resets every per-turn channel; messages keep the conversation.
        return {
            "messages": [HumanMessage(content=query)],
            "question": query,
            "hops": 0,
            "results": None,
            "routing": None,
            "trace": None,
            "direct_answer": "",
        }

    @staticmethod
    def turn_output(state: dict) -> dict:
        return {
            "response": state["answer"],
            "citations": state.get("citations", []),
            "routing": state.get("routing", []),
            "trace": state.get("trace", []),
            "agents": [
                {
                    "agent": r["agent"],
                    "status": r["status"],
                    "error": r["error"],
                    "tool_calls": r["tool_calls"],
                    "duration_ms": r["duration_ms"],
                }
                for r in state.get("results", [])
            ],
        }


@asynccontextmanager
async def open_multi_agent_service(*, config: Settings | None = None, connections=None, **kwargs):
    """Connect every MCP server in this task, then serve; everything closes on exit."""
    config = config or settings
    production = connections is None
    if production:
        connections = default_connections(config=config)
    async with connect_servers(connections) as registry:
        missing = REQUIRED_SERVERS - set(registry.servers)
        if production and missing:
            raise MCPClientError(f"Missing MCP servers: {sorted(missing)}")
        yield MultiAgentService(registry, config=config, **kwargs)
