"""Async service around the supervisor graph: durable sessions, streaming turns, MCP lifecycle.

The graph itself is stateless between turns. Conversation history lives in a
ConversationStore (Firestore on Cloud Run) and is replayed into each turn, so any
instance can continue any session.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from time import monotonic

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from veridex.agents.graph import build_graph
from veridex.agents.state import WORKERS
from veridex.agents.tools import shared_tools, tools_by_agent
from veridex.config import Settings, settings
from veridex.llm import usage
from veridex.llm.providers import Provider, model_id
from veridex.mcp.client import MCPClientError, ToolRegistry, connect_servers, default_connections
from veridex.observability import observed
from veridex.state.store import ConversationStore, create_store, make_turn, to_messages

REQUIRED_SERVERS = {"evidence", "workspace", "catalog", "tavily"}
# Nodes whose model output can become (part of) the answer; supervisor JSON never streams.
ANSWER_NODES = {*WORKERS, "finalize"}


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
        store: ConversationStore | None = None,
        turn_timeout: float | None = None,
    ):
        if not registry.is_active:
            raise MCPClientError("MCP registry is not active.")
        self.registry = registry
        self.config = config or settings
        self.tools = tools_by_agent(registry.tools)
        self.store = store or create_store(self.config)
        self.graph = build_graph(self.tools, config=self.config, factory=factory)
        # Finish (and report) before the HTTP deadline, which cannot interrupt a started stream.
        self.turn_timeout = turn_timeout or max(1.0, self.config.api_request_timeout_seconds - 5)
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, float] = {}
        self._admin = asyncio.Lock()

    @property
    def is_usable(self) -> bool:
        return self.registry.is_active

    def describe(self) -> dict:
        """Agent/tool wiring and models for the UI and docs; contains no secrets."""
        return {
            "agents": {agent: sorted(t.name for t in self.tools[agent]) for agent in WORKERS},
            "shared_tools": shared_tools(),
            "models": {p: model_id(p, self.config) for p in ("openai", "gemini")},
            "state_backend": self.store.backend,
        }

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        """Per-instance turn lock; idle locks expire, conversation state does not."""
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
        done = None
        async for event, data in self.astream_turn(query, session_id):
            if event == "done":
                done = data
        return done

    async def astream_turn(
        self, query: str, session_id: str, *, include_contexts: bool = False
    ) -> AsyncIterator[tuple[str, dict]]:
        """Run one turn, yielding (event, data) as orchestration progresses.

        Events: route, trace, token, citations, done. The turn is saved to the
        conversation store before `done`, so a follow-up on any instance sees it.
        `include_contexts` adds the full text of every retrieved source (for RAGAS).
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")
        if not self.is_usable:
            raise MCPClientError("Agent service is closed.")
        lock = await self._lock_for(session_id)
        async with lock:
            started = monotonic()
            first_token = None
            routing, trace, agents = [], [], []
            sources: dict[str, dict] = {}
            final: dict = {}
            calls = usage.start_turn()
            async with asyncio.timeout(self.turn_timeout):
                history = await self.store.load(session_id, self.config.agent_history_turns)
                async for mode, chunk in self.graph.astream(
                    self.turn_input(query, history),
                    config={"recursion_limit": 2 * self.config.supervisor_max_hops + 4},
                    stream_mode=["updates", "messages", "custom"],
                ):
                    if mode == "custom":
                        # Routing decisions are announced as they are made, not when a node ends.
                        if chunk.get("kind") == "route":
                            yield "route", chunk["data"]
                        continue
                    if mode == "messages":
                        text = _token(*chunk)
                        if text:
                            first_token = first_token or monotonic()
                            yield "token", {"node": chunk[1]["langgraph_node"], "text": text}
                        continue
                    for node, update in chunk.items():
                        routing += (update or {}).get("routing") or []
                        for event in (update or {}).get("trace") or []:
                            trace.append(event)
                            yield "trace", event
                        for result in (update or {}).get("results") or []:
                            agents.append(_agent_summary(result))
                            sources |= result["sources"]
                        if node == "finalize":
                            final = update
                output = {
                    "response": final["answer"],
                    "citations": [_public(c) for c in final.get("citations", [])],
                    "routing": routing,
                    "trace": trace,
                    "agents": agents,
                    "usage": calls,
                    "cost_usd": usage.cost_usd(calls),
                    "timing": {
                        "retrieval_ms": sum(
                            c.get("duration_ms", 0) for a in agents for c in a["tool_calls"]
                        ),
                        "llm_ms": sum(c["duration_ms"] for c in calls),
                    },
                }
                if include_contexts:
                    output["contexts"] = [
                        {"id": key, "kind": s["kind"], "text": s["text"]}
                        for key, s in sources.items()
                    ]
                await self.store.append(session_id, make_turn(query, output))
            self._last_used[session_id] = monotonic()
        yield "citations", {"citations": output["citations"]}
        yield (
            "done",
            output
            | {
                "session_id": session_id,
                "history_turns": len(history),
                "ttft_ms": _ms(first_token, started),
                "total_ms": _ms(monotonic(), started),
            },
        )

    @staticmethod
    def turn_input(query: str, history: list[dict] | None = None) -> dict:
        return {
            "messages": [*to_messages(history or []), HumanMessage(content=query)],
            "question": query,
            "hops": 0,
            "results": None,
            "routing": None,
            "trace": None,
            "direct_answer": "",
        }


def _token(message, metadata: dict) -> str:
    if metadata.get("langgraph_node") not in ANSWER_NODES:
        return ""
    # Streaming models emit AIMessageChunks; non-streaming ones one complete AIMessage.
    if not isinstance(message, AIMessage) or message.tool_calls:
        return ""
    if isinstance(message, AIMessageChunk) and message.tool_call_chunks:
        return ""
    content = message.content
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def _public(citation: dict) -> dict:
    """Citations sent to clients carry a snippet, not the full retrieved text."""
    return {k: v for k, v in citation.items() if k != "text"}


def _agent_summary(result: dict) -> dict:
    return {
        "agent": result["agent"],
        "status": result["status"],
        "error": result["error"],
        "tool_calls": result["tool_calls"],
        "duration_ms": result["duration_ms"],
    }


def _ms(end: float | None, start: float) -> int | None:
    return None if end is None else round((end - start) * 1000)


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
