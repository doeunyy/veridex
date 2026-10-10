import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from test_mcp_client import FakeClient, FakeSession

from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.agent.tools import search_evidence as local_search_evidence
from veridex.mcp import client as mcp_client


class ScriptedModel:
    """Exact tool sequences are model fixtures, never production routing rules."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.tools = None
        self.messages = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.messages.append(deepcopy(messages))
        response = next(self.responses)
        return response(messages) if callable(response) else response

    def invoke(self, messages):
        raise AssertionError("The MCP graph must use async model invocation")


def call(name, args=None, call_id=None):
    return {"name": name, "args": args or {}, "id": call_id or f"call-{name}", "type": "tool_call"}


def request(*calls):
    return AIMessage(content="", tool_calls=list(calls))


def assert_tool_then_answer(messages):
    tools = [message for message in messages if message.type == "tool"]
    assert tools
    sources = []
    for message in tools:
        data = message.artifact["structured_content"]
        sources.extend(
            f"[{passage['document_id']}, PDF p.{passage['page']}]"
            for passage in data.get("passages", [])
        )
        sources.extend(result["url"] for result in data.get("results", []))
        sources.extend(doc["document_id"] for doc in data.get("documents", []))
        sources.extend(
            f"[{data['document']['paper_id']}, PDF p.{page['page']}]"
            for page in data.get("pages", [])
        )
    return AIMessage(content="Tool results: " + ", ".join(sources))


SCENARIOS = {
    "no-tool": ("Hello!", [AIMessage(content="Hello!")], []),
    "evidence": (
        "Explain Self-RAG",
        [request(call("search_evidence", {"query": "Self-RAG"})), assert_tool_then_answer],
        ["search_evidence"],
    ),
    "web": (
        "Recent RAG developments",
        [request(call("search_web", {"query": "recent RAG"})), assert_tool_then_answer],
        ["search_web"],
    ),
    "workspace": (
        "What papers are available?",
        [request(call("list_documents")), assert_tool_then_answer],
        ["list_documents"],
    ),
    "evidence-web": (
        "Compare Self-RAG with recent RAG",
        [
            request(
                call("search_evidence", {"query": "Self-RAG"}),
                call("search_web", {"query": "recent RAG"}),
            ),
            assert_tool_then_answer,
        ],
        ["search_evidence", "search_web"],
    ),
    "workspace-evidence": (
        "List papers and explain one",
        [
            request(call("list_documents")),
            request(call("search_evidence", {"query": "paper", "document_id": "paper"})),
            assert_tool_then_answer,
        ],
        ["list_documents", "search_evidence"],
    ),
    "read-document": (
        "Read page one",
        [
            request(call("list_documents")),
            request(
                call("read_document", {"document_id": "paper.pdf", "start_page": 1, "end_page": 1})
            ),
            assert_tool_then_answer,
        ],
        ["list_documents", "read_document"],
    ),
    "insufficient": (
        "Find missing evidence",
        [
            request(call("search_evidence", {"query": "empty"})),
            AIMessage(
                content="There is insufficient evidence; I cannot provide verified citations."
            ),
        ],
        ["search_evidence"],
    ),
    "tool-failure": (
        "Search despite provider failure",
        [
            request(call("search_web", {"query": "error"})),
            AIMessage(
                content="The search failed. I cannot provide verified evidence or citations."
            ),
        ],
        ["search_web"],
    ),
}


@pytest.fixture
def fake_servers(monkeypatch):
    schemas = {
        "search_evidence": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "document_id": {"type": "string"}},
            "required": ["query"],
        },
        "search_web": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "list_documents": {"type": "object", "properties": {}},
        "read_document": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "start_page": {"type": "integer"},
                "end_page": {"type": "integer"},
            },
            "required": ["document_id"],
        },
    }
    roles = {
        "evidence": ["search_evidence"],
        "web_search": ["search_web"],
        "workspace": ["list_documents", "read_document"],
    }
    fake = FakeClient(
        {
            role: FakeSession(
                [Tool(name=name, description=name, inputSchema=schemas[name]) for name in names]
            )
            for role, names in roles.items()
        }
    )
    log = []

    async def execute(name, args, **kwargs):
        log.append((name, args))
        if args.get("query") == "error":
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text="SECRET provider failure")]
            )
        if name == "search_evidence":
            payload = {
                "query": args["query"],
                "passages": []
                if args["query"] == "empty"
                else [
                    {
                        "document_id": "paper",
                        "chunk_id": "paper_p1_c1",
                        "title": "Paper",
                        "page": 1,
                        "source_url": "https://example.com/paper",
                        "distance": 0.37,
                        "content": "Evidence",
                    }
                ],
            }
        elif name == "search_web":
            payload = {
                "query": args["query"],
                "results": [
                    {
                        "title": "Web paper",
                        "url": "https://example.com/web?x=1#section",
                        "content": "Web evidence",
                    }
                ],
            }
        elif name == "list_documents":
            payload = {"documents": [{"document_id": "paper.pdf", "paper_id": "paper"}]}
        else:
            payload = {
                "document": {"document_id": "paper.pdf", "paper_id": "paper"},
                "pages": [{"page": 1, "text": "PDF evidence"}],
                "truncated": False,
            }
        return CallToolResult(
            content=[TextContent(type="text", text=str(payload))], structuredContent=payload
        )

    for session in fake.sessions.values():
        session.call_tool.side_effect = execute
    monkeypatch.setattr(mcp_client, "create_client", lambda connections: fake)
    return fake, log


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_deterministic_agent_scenarios(fake_servers, scenario):
    fake, log = fake_servers
    query, responses, expected = SCENARIOS[scenario]
    model = ScriptedModel(responses)
    async with open_mcp_agent_service({}, model=model) as service:
        assert {tool.name for tool in model.tools} == {
            "search_evidence",
            "search_web",
            "list_documents",
            "read_document",
        }
        assert all(tool is not local_search_evidence for tool in model.tools)
        trace = await service.achat_with_trace(query, "test")
        assert [item["name"] for item in trace["tool_calls"]] == expected
        assert [name for name, args in log] == expected
        assert sum(trace["call_counts"].values()) == len(expected)
        assert all(result["server_identity"] == "Test Server" for result in trace["tool_results"])
        assert "untrusted" in model.messages[0][0].content
        assert "search_web" in model.messages[0][0].content
        if scenario == "insufficient":
            assert trace["tool_results"][0]["structured_content"]["passages"] == []
            assert "insufficient" in trace["response"]
        elif scenario == "tool-failure":
            result = trace["tool_results"][0]
            assert result["status"] == "error" and result["artifact"] is None
            assert "failed" in trace["response"]
            assert "SECRET" not in str(trace)
            assert model.messages[-1][-1].status == "error"
        elif scenario == "evidence":
            passage = trace["tool_results"][0]["structured_content"]["passages"][0]
            assert passage["page"] == 1 and passage["document_id"] == "paper"
            assert passage["distance"] == 0.37 and passage["source_url"]
        assert fake.closed == []
    assert set(fake.closed) == {"evidence", "web_search", "workspace"}
    with pytest.raises(mcp_client.MCPClientError, match="closed"):
        await service.achat("Hi", "test")


@pytest.mark.asyncio
async def test_memory_isolation_and_turn_local_traces(fake_servers):
    model = ScriptedModel(
        [
            request(call("search_evidence", {"query": "Self-RAG"})),
            AIMessage(content="Self-RAG answer."),
            AIMessage(content="Its benefits include evidence grounding."),
            AIMessage(content="Hello!"),
        ]
    )
    async with open_mcp_agent_service({}, model=model) as service:
        first = await service.achat_with_trace("Explain Self-RAG", "a")
        second = await service.achat_with_trace("What are its benefits?", "a")
        other = await service.achat_with_trace("Hello", "b")
        assert first["tool_calls"] and not second["tool_calls"] and not other["tool_calls"]
        assert any(message.content == "Explain Self-RAG" for message in model.messages[2])
        assert any(message.content == "Self-RAG answer." for message in model.messages[2])
        assert not any(message.content == "Explain Self-RAG" for message in model.messages[3])
        assert len(await service.aget_history("a")) == 6
        assert len(await service.aget_history("b")) == 2
        # Caller mutations of returned traces must not corrupt the shared checkpointer.
        first["tool_results"][0]["structured_content"]["passages"][0]["page"] = 999
        history = await service.aget_history("a")
        tools = [message for message in history if message.type == "tool"]
        assert tools[0].artifact["structured_content"]["passages"][0]["page"] == 1


@pytest.mark.asyncio
async def test_recursion_limit_returns_visible_failure(fake_servers):
    class LoopModel(ScriptedModel):
        async def ainvoke(self, messages):
            return request(call("list_documents", call_id=f"call-{len(messages)}"))

    async with open_mcp_agent_service({}, model=LoopModel([]), recursion_limit=4) as service:
        trace = await service.achat_with_trace("Loop", "loop")
        assert trace["status"] == "error" and trace["error"] == "recursion_limit"
        assert "No final answer is verified" in trace["response"]
        assert len(trace["tool_calls"]) <= 2
        assert trace["tool_results"]


@pytest.mark.asyncio
async def test_turn_timeout_is_visible(fake_servers):
    model = ScriptedModel([])
    model.ainvoke = AsyncMock(side_effect=lambda messages: asyncio.sleep(10))
    async with open_mcp_agent_service({}, model=model, turn_timeout=0.01) as service:
        # AsyncMock side effects must themselves await rather than return a coroutine.
        async def stalled(messages):
            await asyncio.Event().wait()

        model.ainvoke.side_effect = stalled
        trace = await service.achat_with_trace("Hello", "timeout")
        assert trace["error"] == "turn_timeout" and trace["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query, session", [("", "a"), (" ", "a"), (None, "a"), ("hi", ""), ("hi", None)]
)
async def test_invalid_requests(fake_servers, query, session):
    async with open_mcp_agent_service({}, model=ScriptedModel([])) as service:
        with pytest.raises(ValueError):
            await service.achat(query, session)


@pytest.mark.asyncio
async def test_session_turns_are_serialized_and_close_drains(fake_servers):
    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0
    model = ScriptedModel([])

    async def answer(messages):
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await release.wait()
        return AIMessage(content="Answer")

    model.ainvoke = answer
    async with open_mcp_agent_service({}, model=model) as service:
        first = asyncio.create_task(service.achat("first", "a"))
        await entered.wait()
        second = asyncio.create_task(service.achat("second", "a"))
        await asyncio.sleep(0)
        assert count == 1
        release.set()
        assert await first == await second == "Answer"
        assert len(await service.aget_history("a")) == 4
        closing = asyncio.create_task(service.aclose())
        await closing
        with pytest.raises(mcp_client.MCPClientError, match="closed"):
            await service.achat("third", "a")


@pytest.mark.asyncio
async def test_interrupted_tool_round_keeps_followup_history_valid(fake_servers):
    class LoopModel(ScriptedModel):
        async def ainvoke(self, messages):
            self.messages.append(deepcopy(messages))
            return request(call("list_documents", call_id=f"call-{len(messages)}"))

    model = LoopModel([])
    async with open_mcp_agent_service({}, model=model, recursion_limit=3) as service:
        trace = await service.achat_with_trace("Loop", "recover")
        assert trace["error"] == "recursion_limit"
        history = await service.aget_history("recover")
        requested = {
            item["id"] for message in history if message.type == "ai" for item in message.tool_calls
        }
        completed = {message.tool_call_id for message in history if message.type == "tool"}
        assert requested == completed

        async def answer(messages):
            return AIMessage(content="The previous request hit its execution limit.")

        model.ainvoke = answer
        assert "execution limit" in await service.achat("What happened?", "recover")


@pytest.mark.asyncio
async def test_service_close_waits_for_active_turn(fake_servers):
    fake, _ = fake_servers
    entered = asyncio.Event()
    release = asyncio.Event()
    model = ScriptedModel([])

    async def answer(messages):
        entered.set()
        await release.wait()
        return AIMessage(content="Completed before shutdown")

    model.ainvoke = answer
    async with open_mcp_agent_service({}, model=model) as service:
        turn = asyncio.create_task(service.achat("Hello", "active"))
        await entered.wait()
        close = asyncio.create_task(service.aclose())
        try:
            await asyncio.sleep(0)
            assert not close.done()
            assert fake.closed == []
            with pytest.raises(mcp_client.MCPClientError, match="closed"):
                await service.achat("New", "another")
        finally:
            release.set()
        assert await turn == "Completed before shutdown"
        await close
    assert len(fake.closed) == 3


@pytest.mark.asyncio
async def test_different_sessions_can_run_concurrently(fake_servers):
    count = 0
    ready = asyncio.Event()
    model = ScriptedModel([])

    async def answer(messages):
        nonlocal count
        count += 1
        if count == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 2)
        return AIMessage(content=messages[-1].content)

    model.ainvoke = answer
    async with open_mcp_agent_service({}, model=model) as service:
        assert await asyncio.gather(service.achat("Alice", "a"), service.achat("Bob", "b")) == [
            "Alice",
            "Bob",
        ]
        assert (await service.aget_history("a"))[0].content == "Alice"
        assert (await service.aget_history("b"))[0].content == "Bob"


@pytest.mark.asyncio
async def test_unknown_tool_never_counts_as_mcp_execution(fake_servers):
    model = ScriptedModel(
        [
            request(call("write_document", {"path": "outside"})),
            AIMessage(content="That operation is unavailable."),
        ]
    )
    async with open_mcp_agent_service({}, model=model) as service:
        trace = await service.achat_with_trace("Try writing", "invalid-tool")
        assert trace["tool_results"][0]["status"] == "error"
        assert not trace["tool_results"][0]["invocation_completed"]
        assert trace["call_counts"] == {} and trace["server_call_counts"] == {}
        assert not fake_servers[1]


@pytest.mark.asyncio
async def test_incomplete_registry_fails_before_model_binding(fake_servers):
    fake, _ = fake_servers
    session = fake.sessions["workspace"]
    session.list_tools.return_value = ListToolsResult(
        tools=[session.list_tools.return_value.tools[0]]
    )
    model = ScriptedModel([])
    with pytest.raises(mcp_client.MCPClientError, match="four production tools"):
        async with open_mcp_agent_service({}, model=model):
            pytest.fail("An incomplete agent registry must not be usable")
    assert model.tools is None
    assert len(fake.closed) == 3


@pytest.mark.asyncio
async def test_cancelled_agent_tool_round_repairs_history(fake_servers):
    fake, _ = fake_servers
    started = asyncio.Event()

    async def stalled(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    fake.sessions["evidence"].call_tool.side_effect = stalled
    model = ScriptedModel(
        [
            request(call("search_evidence", {"query": "Self-RAG"})),
            AIMessage(content="The previous tool request was cancelled."),
        ]
    )
    async with open_mcp_agent_service({}, model=model) as service:
        turn = asyncio.create_task(service.achat("Explain Self-RAG", "cancelled"))
        await asyncio.wait_for(started.wait(), 2)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        history = await service.aget_history("cancelled")
        requested = {
            item["id"] for message in history if message.type == "ai" for item in message.tool_calls
        }
        answered = {message.tool_call_id for message in history if message.type == "tool"}
        assert requested == answered
        errors = [message for message in history if message.type == "tool"]
        assert errors and all(
            message.status == "error" and message.artifact is None for message in errors
        )
        assert all(message.additional_kwargs["execution_interrupted"] for message in errors)
        followup = await service.achat_with_trace("What happened?", "cancelled")
        assert followup["call_counts"] == {} and "cancelled" in followup["response"]
