"""Asynchronous LangGraph service scoped to the existing persistent MCP registry."""

import asyncio
import math
from collections import Counter
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime
from time import monotonic

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from veridex.agent.budgets import (
    AgentBudgetExceeded,
    SessionCapacityError,
    TurnBudget,
    compact_memory,
)
from veridex.agent.graph import build_agent_graph
from veridex.agent.prompts import MCP_AGENT_SYSTEM_PROMPT
from veridex.config import Settings, settings
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
        limits: Settings | None = None,
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
        self.limits = limits or settings
        self._session_users = {}
        self._session_used = {}
        self._session_admin = asyncio.Lock()
        self._budget = ContextVar(f"veridex-budget-{id(self)}")
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
            before_model=lambda messages: self._budget.get().before_model(messages),
            before_tools=lambda messages: self._budget.get().before_tools(messages),
        )

    @property
    def is_usable(self) -> bool:
        """Local lifecycle readiness; does not issue provider or MCP requests."""
        return not self._closed and self.registry.is_active

    def _ensure_open(self):
        if not self.is_usable:
            raise MCPClientError("MCP agent service is closed.")

    @asynccontextmanager
    async def _session(self, session_id: str):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Session ID cannot be empty.")
        self._ensure_open()
        async with self._session_admin:
            self._ensure_open()
            now = monotonic()
            expired = [
                key
                for key, used in self._session_used.items()
                if not self._session_users[key]
                and now - used >= self.limits.agent_session_ttl_seconds
            ]
            for key in expired:
                await self.checkpointer.adelete_thread(key)
                del self._session_locks[key], self._session_users[key], self._session_used[key]
            if session_id not in self._session_locks:
                if len(self._session_locks) >= self.limits.agent_max_sessions:
                    raise SessionCapacityError("Session capacity exhausted.")
                self._session_locks[session_id] = asyncio.Lock()
                self._session_users[session_id] = 0
                self._session_used[session_id] = now
            lock = self._session_locks[session_id]
            # Waiting turns also reserve the session; TTL cleanup cannot remove it.
            self._session_users[session_id] += 1
        try:
            async with lock:
                token = self._budget.set(
                    TurnBudget(
                        self.limits.agent_max_tool_calls,
                        self.limits.agent_max_model_calls,
                        self.limits.agent_max_context_characters,
                    )
                )
                try:
                    yield
                finally:
                    try:
                        if type(self.checkpointer) is InMemorySaver:
                            await compact_memory(
                                self.checkpointer, session_id, self.limits.agent_history_turns
                            )
                    finally:
                        self._budget.reset(token)
        finally:
            self._session_users[session_id] -= 1
            self._session_used[session_id] = monotonic()

    async def achat(self, query: str, session_id: str) -> str:
        return (await self.achat_with_trace(query, session_id))["response"]

    async def aget_history(self, session_id: str):
        async with self._session(session_id):
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
        async with self._session(session_id):
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
            except asyncio.CancelledError:
                # Preserve cancellation while leaving a valid tool-message history for follow-ups.
                snapshot = await self.graph.aget_state(config)
                await self._finish_interrupted_round(config, snapshot.values)
                raise
            except (GraphRecursionError, TimeoutError, AgentBudgetExceeded) as exc:
                error = (
                    str(exc)
                    if isinstance(exc, AgentBudgetExceeded)
                    else "recursion_limit"
                    if isinstance(exc, GraphRecursionError)
                    else "turn_timeout"
                )
                snapshot = await self.graph.aget_state(config)
                result = await self._finish_interrupted_round(config, snapshot.values)
                response = "I could not complete this request within the agent limits. No final answer is verified."
            except Exception:
                snapshot = await self.graph.aget_state(config)
                await self._finish_interrupted_round(config, snapshot.values)
                raise
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
        if type(self.checkpointer) is InMemorySaver:
            for key in self._session_locks:
                await self.checkpointer.adelete_thread(key)
        self._session_locks.clear()
        self._session_users.clear()
        self._session_used.clear()


@asynccontextmanager
async def open_mcp_agent_service(
    connections=None,
    *,
    model=None,
    checkpointer=None,
    recursion_limit=12,
    turn_timeout=120,
    request_timeout=45,
    limits: Settings | None = None,
):
    """Own the registry and AgentService together; enter/exit in the same async task."""
    limits = limits or settings
    if model is None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        # Leave temperature at the model's default (reasoning models may reject temperature=0).
        model = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            timeout=limits.provider_timeout_seconds,
            max_retries=limits.provider_max_retries,
            max_completion_tokens=limits.agent_max_completion_tokens,
        )
    async with connect_servers(connections, timeout=request_timeout) as registry:
        service = MCPAgentService(
            registry,
            model=model,
            checkpointer=checkpointer,
            recursion_limit=recursion_limit,
            turn_timeout=turn_timeout,
            limits=limits,
        )
        try:
            yield service
        finally:
            await service.aclose()
