"""Mounted offline TCP fixture; never copied into the production image."""

import asyncio
import json
import os
import runpy
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from network_guard import install as install_network_guard

install_network_guard()

from veridex.deployment.runtime import BUNDLE, prepare

index = prepare()
os.environ["CHROMA_PERSIST_DIR"] = str(index)
os.environ["OPENAI_API_KEY"] = "offline-placeholder"
os.environ["TAVILY_API_KEY"] = "offline-placeholder"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from langchain_core.messages import AIMessage

from veridex.agent import mcp_service
from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.api import app as api
from veridex.config import settings
from veridex.mcp.client import default_connections

settings.chroma_persist_dir = index
settings.documents_dir = BUNDLE / "papers"
settings.workspace_manifest_path = BUNDLE / "manifest.json"
connections = default_connections()
for name, connection in connections.items():
    connection["args"] = ["/verification/server.py", name]
    connection["env"].update(
        FASTMCP_CHECK_FOR_UPDATES="off",
        FASTMCP_SHOW_SERVER_BANNER="false",
        ANONYMIZED_TELEMETRY="False",
    )

REPORT = Path("/verification-report") / os.environ.get("E2E_REPORT_NAME", "idle.json")
state = {
    "offline": True,
    "traces": [],
    "sessions": {},
    "events": [],
    "started": time.time(),
    "index_separate": index != BUNDLE / "chroma",
}
original_clock = mcp_service.monotonic
mcp_service.monotonic = lambda: original_clock() + state.get("clock_offset", 0)
service = None
application = None


def write():
    staging = REPORT.with_suffix(".tmp")
    staging.write_text(json.dumps(state, sort_keys=True))
    staging.replace(REPORT)


def history_summary(messages):
    calls = {call["id"] for m in messages if m.type == "ai" for call in m.tool_calls}
    answers = {m.tool_call_id for m in messages if m.type == "tool"}
    return {
        "balanced": calls == answers,
        "humans": [m.content for m in messages if m.type == "human"],
        "interrupted": sum(
            bool(m.additional_kwargs.get("execution_interrupted"))
            for m in messages
            if m.type == "tool"
        ),
    }


def trace_summary(trace, query, session):
    results = []
    for r in trace["tool_results"]:
        data = r["structured_content"] or {}
        results.append(
            {
                "name": r["name"],
                "server": r.get("server"),
                "status": r["status"],
                "completed": r["invocation_completed"],
                "passages": [
                    {
                        "chunk_id": p["chunk_id"],
                        "paper_id": p["document_id"],
                        "page": p["page"],
                        "distance": p["distance"],
                    }
                    for p in data.get("passages", [])
                ],
                "urls": [p["url"] for p in data.get("results", [])],
                "documents": [p["document_id"] for p in data.get("documents", [])],
                "pages": [p["page"] for p in data.get("pages", [])],
                "page_characters": [len(p["text"]) for p in data.get("pages", [])],
                "paper_id": data.get("document", {}).get("paper_id"),
            }
        )
    return {
        "query": query,
        "session": session,
        "calls": [
            {"name": c["name"], "server": c.get("server"), "args": c["args"]}
            for c in trace["tool_calls"]
        ],
        "results": results,
        "status": trace["status"],
        "error": trace["error"],
        "response": trace["response"],
    }


def calls(*tools):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"fixture-{uuid4().hex}-{name}", "type": "tool_call"}
            for name, args in tools
        ],
    )


class Model:
    def bind_tools(self, tools):
        if {t.name for t in tools} != {
            "search_evidence",
            "search_web",
            "list_documents",
            "read_document",
        }:
            raise RuntimeError("Unexpected tools")
        return self

    async def ainvoke(self, messages):
        last = max(i for i, m in enumerate(messages) if m.type == "human")
        query = messages[last].content
        current = messages[last + 1 :]
        rounds = sum(m.type == "ai" for m in current)
        evidence = ("search_evidence", {"query": "RAG", "document_id": "rag_2020", "top_k": 3})
        web = ("search_web", {"query": "offline-rag"})
        plans = {
            "tool-budget": [[("list_documents", {})] * 9],
            "model-budget": [[("list_documents", {})]] * 8,
            "evidence": [[evidence]],
            "web": [[web]],
            "workspace": [[("list_documents", {})]],
            "read": [
                [("list_documents", {})],
                [
                    (
                        "read_document",
                        {
                            "document_id": "rag_2020.pdf",
                            "start_page": 3,
                            "end_page": 3,
                            "max_chars": 1000,
                        },
                    )
                ],
            ],
            "evidence-web": [[evidence, web]],
            "workspace-evidence": [[("list_documents", {})], [evidence]],
            "insufficient": [[("search_evidence", {"query": "RAG", "document_id": "nonexistent"})]],
            "tool-error": [[("search_web", {"query": "web-error"})]],
            "pdf-error": [[("read_document", {"document_id": "not-approved.pdf"})]],
            "slow-tool": [[("search_web", {"query": "web-slow"})]],
        }
        if query == "model-error":
            raise RuntimeError("PRIVATE-SENTINEL credential /sensitive/path")
        if query == "slow-model":
            state["events"].append("slow-model-entered")
            write()
            await asyncio.sleep(120)
        if query == "brief-model":
            state["events"].append("brief-model-entered")
            write()
            await asyncio.sleep(1)
        if query in plans and rounds < len(plans[query]):
            return calls(*plans[query][rounds])
        if query == "recall":
            return AIMessage(
                content="History: "
                + json.dumps(
                    [m.content for m in messages if m.type == "human" and m.content != "recall"]
                )
            )
        results = [m for m in current if m.type == "tool"]
        if any(m.status == "error" for m in results):
            return AIMessage(content="Controlled tool error; no verified evidence.")
        if query == "insufficient":
            return AIMessage(content="Insufficient evidence; no verified answer.")
        return AIMessage(
            content="Hello offline." if query == "greeting" else "Verified offline: " + query
        )


@asynccontextmanager
async def factory():
    global service
    try:
        # Extra fixture imports on amd64 emulation need a startup-only allowance.
        async with open_mcp_agent_service(connections, model=Model(), request_timeout=90) as actual:
            actual.registry._timeout = 45
            service = actual
            state["servers"] = sorted(actual.registry.servers)
            state["tools"] = sorted(actual.registry.entries)
            state["ready_at"] = time.time()

            async def chat(query, session_id):
                try:
                    trace = await actual.achat_with_trace(query, session_id)
                    state["traces"].append(trace_summary(trace, query, session_id))
                    return trace["response"]
                except asyncio.CancelledError:
                    state["events"].append("cancelled:" + session_id)
                    raise
                finally:
                    snapshot = await actual.graph.aget_state(
                        {"configurable": {"thread_id": session_id}}
                    )
                    state["sessions"][session_id] = history_summary(
                        snapshot.values.get("messages", [])
                    )
                    write()

            actual.achat = chat
            write()
            yield actual
    finally:
        if service is not None:
            state["registry_closed"] = not service.registry.is_active
        state["shutdown_readiness_withdrawn"] = (
            application.state.shutting_down and application.state.agent_service is None
        )
        remaining = []
        for path in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                if b"/verification/server.py" in path.read_bytes():
                    remaining.append(int(path.parent.name))
            except FileNotFoundError:
                pass
        state["remaining_children"] = remaining
        state["shutdown_at"] = time.time()
        write()


application = api.create_app(service_factory=factory)
api.app = application


@application.get("/__verification")
async def snapshot():
    state["limits"] = {
        key: getattr(settings, key)
        for key in (
            "api_max_active_requests",
            "api_max_waiting_requests",
            "agent_max_tool_calls",
            "agent_max_model_calls",
            "agent_max_completion_tokens",
            "agent_history_turns",
            "agent_max_sessions",
            "agent_session_ttl_seconds",
            "provider_max_retries",
            "provider_timeout_seconds",
        )
    }
    if service is not None:
        state["retained_sessions"] = sorted(service._session_locks)
        state["checkpoint_counts"] = {
            key: len(list(service.checkpointer.list({"configurable": {"thread_id": key}})))
            for key in service._session_locks
        }
    state["active"] = application.state.admission.active
    state["waiting"] = application.state.admission.waiting
    current = Path("/sys/fs/cgroup/memory.current")
    peak = Path("/sys/fs/cgroup/memory.peak")
    if current.exists():
        state["memory_current_bytes"] = int(current.read_text())
        state["sampled_peak_bytes"] = max(
            state.get("sampled_peak_bytes", 0), state["memory_current_bytes"]
        )
    if peak.exists():
        state["kernel_peak_bytes"] = int(peak.read_text())
    events = Path("/verification-report/events.jsonl")
    state["provider_events"] = (
        [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
    )
    state["children"] = sorted(
        int(p.parent.name)
        for p in Path("/proc").glob("[0-9]*/cmdline")
        if b"/verification/server.py" in p.read_bytes()
    )
    return state


@application.post("/__verification/control")
async def control(body: dict):
    mapping = {
        "timeout": "api_request_timeout_seconds",
        "queue": "api_queue_timeout_seconds",
        "active": "api_max_active_requests",
        "waiting": "api_max_waiting_requests",
        "models": "agent_max_model_calls",
        "sessions": "agent_max_sessions",
    }
    for key, value in body.items():
        if key in mapping:
            setattr(settings, mapping[key], value)
            if key == "active":
                if application.state.admission.active or application.state.admission.waiting:
                    raise RuntimeError("Change fixture capacity only while idle")
                application.state.admission._semaphore = asyncio.Semaphore(value)
        if key == "unavailable":
            application.state.shutting_down = value
        if key == "advance_ttl":
            state["clock_offset"] = state.get("clock_offset", 0) + value
    return {"configured": True}


write()
runpy.run_path("/app/scripts/serve_api.py", run_name="__main__")
