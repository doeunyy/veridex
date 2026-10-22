import json
from types import SimpleNamespace

import httpx
import pytest
from agents_fakes import CONFIG, factory, make_tools, system, tool_call
from langchain_core.messages import AIMessage

from veridex.agents.prompts import RESEARCH_PROMPT
from veridex.agents.service import MultiAgentService
from veridex.api.app import create_app
from veridex.state.store import SqliteStore

pytestmark = pytest.mark.asyncio


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def research_script(provider, mode, messages):
    if mode == "structured":
        if any(m.type == "human" and "research (ok)" in m.content for m in messages):
            return {"next": "finish", "reason": "Answered."}
        return {"next": "research", "task": "Explain", "reason": "Needs evidence."}
    assert system(messages) == RESEARCH_PROMPT
    if messages[-1].type == "tool":
        prior = [m.content for m in messages if m.type == "human"]
        return AIMessage(content=f"Answer {len(prior)} [react_2022:p2:c012].")
    return tool_call("search_evidence", {"query": "ReAct"})


def service(store=None, script=research_script):
    make, _ = factory(script)
    registry = SimpleNamespace(
        is_active=True, tools=[t for group in make_tools().values() for t in group]
    )
    return MultiAgentService(registry, config=CONFIG, factory=make, store=store)


def client(application):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://t")


async def test_stream_emits_routing_trace_tokens_citations_and_done():
    application = create_app(agent_service=service(), config=CONFIG)
    async with client(application) as http:
        response = await http.post(
            "/api/chat/stream", json={"query": "What is ReAct?", "session_id": "s"}
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    kinds = [event for event, _ in events]
    assert kinds[-2:] == ["citations", "done"]
    assert kinds.index("route") < kinds.index("token") < kinds.index("done")
    routes = [data for event, data in events if event == "route"]
    assert [(r["agent"], r["provider"], r["rule"]) for r in routes][:2] == [
        ("supervisor", "gemini", "classify"),
        ("research", "gemini", "single_lookup"),
    ]
    assert all(r["reason"] for r in routes)
    trace = [data["node"] for event, data in events if event == "trace"]
    assert trace == ["supervisor", "research", "supervisor", "finalize"]
    tokens = "".join(d["text"] for e, d in events if e == "token" and d["node"] == "research")
    assert tokens.endswith("[react_2022:p2:c012].")
    done = events[-1][1]
    assert done["response"] == "Answer 1 [react_2022:p2:c012]."
    assert done["citations"][0]["url"] == "https://arxiv.org/abs/2210.03629"
    assert done["ttft_ms"] is not None and done["total_ms"] >= done["ttft_ms"]
    assert done["agents"][0]["tool_calls"][0]["tool"] == "search_evidence"


async def test_conversation_survives_a_new_instance_through_the_store(tmp_path):
    path = tmp_path / "conversations.db"
    first = service(SqliteStore(path))
    await first.achat("What is ReAct?", "session-1")
    replacement = service(SqliteStore(path))  # e.g. a different Cloud Run instance
    result = await replacement.achat_with_trace("And the follow-up?", "session-1")
    assert result["history_turns"] == 1
    assert result["response"].startswith("Answer 2")  # the earlier question was replayed
    other = await replacement.achat_with_trace("Unrelated", "session-2")
    assert other["history_turns"] == 0


async def test_stream_failure_is_reported_without_details():
    def broken(provider, mode, messages):
        raise RuntimeError("SECRET-provider-body")

    class Store:
        backend = "memory"

        async def load(self, session_id, turns):
            raise RuntimeError("SECRET-db")

    application = create_app(agent_service=service(Store(), broken), config=CONFIG)
    async with client(application) as http:
        response = await http.post("/api/chat/stream", json={"query": "q", "session_id": "s"})
    assert parse_sse(response.text) == [("error", {"message": "Agent request failed."})]
    assert "SECRET" not in response.text


async def test_stream_is_covered_by_request_limits():
    application = create_app(agent_service=service(), config=CONFIG)
    async with client(application) as http:
        too_big = await http.post(
            "/api/chat/stream", content=b"x" * (CONFIG.api_max_request_body_bytes + 1)
        )
        invalid = await http.post("/api/chat/stream", json={"query": "", "session_id": "s"})
    assert too_big.status_code == 413
    assert invalid.status_code == 422 and invalid.json() == {"detail": "Invalid request."}


async def test_ui_and_info_are_served():
    application = create_app(agent_service=service(), config=CONFIG)
    async with client(application) as http:
        page = await http.get("/")
        script = await http.get("/static/app.js")
        info = (await http.get("/api/info")).json()
    assert page.status_code == 200 and "<title>Veridex</title>" in page.text
    assert script.status_code == 200 and "/api/chat/stream" in script.text
    assert info["shared_tools"]["search_evidence"] == ["research", "summary"]
    assert info["models"] == {"openai": "gpt-6.1-sol", "gemini": "gemini-3.8-flash"}
    assert info["state_backend"] == "memory"
