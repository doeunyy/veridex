import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from veridex.api.app import create_app
from veridex.mcp.client import MCPClientError, ToolRegistry
from veridex.observability import correlation_id, execution, observed, turn_context


def events(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "uvicorn.error.veridex"]


@pytest.mark.asyncio
async def test_http_correlation_propagates_and_is_distinct(caplog):
    caplog.set_level("INFO")
    ids = []

    @observed("agent")
    async def call(**kwargs):
        ids.append(await asyncio.create_task(asyncio.to_thread(correlation_id)))
        return "SECRET-response"

    service = SimpleNamespace(achat=call)
    app = create_app(agent_service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(2):
            r = await c.post(
                "/chat", json={"query": "SECRET-query", "session_id": "SECRET-session"}
            )
            assert r.json() == {"response": "SECRET-response"}
    assert len(set(ids)) == 2
    assert all(len(i) == 32 for i in ids)
    assert correlation_id() is None
    assert "SECRET" not in caplog.text
    assert {e["event"] for e in events(caplog)} == {
        "chat_started",
        "chat_completed",
        "agent_started",
        "agent_completed",
    }
    for i in ids:
        assert len([e for e in events(caplog) if e["correlation_id"] == i]) == 4


@pytest.mark.asyncio
async def test_safe_http_failure_and_exception_normalization(caplog):
    caplog.set_level("INFO")
    error = type("SECRET-class", (Exception,), {})
    service = SimpleNamespace(achat=AsyncMock(side_effect=error("SECRET-message")))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(agent_service=service)), base_url="http://test"
    ) as c:
        r = await c.post("/chat", json={"query": "SECRET-query", "session_id": "SECRET-session"})
    assert r.status_code == 500 and r.json() == {"detail": "Agent request failed."}
    assert events(caplog)[-1]["exception_class"] == "Exception"
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_mcp_events_and_cancellation(caplog, failure):
    caplog.set_level("INFO")
    registry = ToolRegistry(SimpleNamespace(connections={"tavily": {}}), timeout=1)
    registry._active = True
    request = SimpleNamespace(server_name="tavily", name="tavily_search", args="SECRET-args")

    async def handler(request):
        assert correlation_id() is not None
        if failure:
            raise failure("SECRET-error")
        return "SECRET-result"

    with turn_context():
        if failure:
            expected = (
                asyncio.CancelledError if failure is asyncio.CancelledError else MCPClientError
            )
            with pytest.raises(expected):
                await registry._intercept(request, handler)
        else:
            assert await registry._intercept(request, handler) == "SECRET-result"
    emitted = events(caplog)
    assert [e["event"] for e in emitted] == [
        "mcp_tool_started",
        "mcp_tool_failed" if failure else "mcp_tool_completed",
    ]
    assert all(e["server"] == "tavily" and e["tool"] == "tavily_search" for e in emitted)
    assert "SECRET" not in caplog.text


def test_untrusted_names_never_logged(caplog):
    caplog.set_level("INFO")
    with execution("mcp_tool", server="SECRET-server", tool="SECRET-tool"):
        pass
    assert "SECRET" not in caplog.text
    assert "server" not in events(caplog)[0]


@pytest.mark.asyncio
async def test_protocol_failure_is_not_logged_as_completed(caplog):
    from mcp.types import CallToolResult, TextContent

    caplog.set_level("INFO")
    registry = ToolRegistry(SimpleNamespace(connections={"tavily": {}}), timeout=1)
    registry._active = True
    result = CallToolResult(isError=True, content=[TextContent(type="text", text="SECRET-payload")])
    handler = AsyncMock(return_value=result)
    request = SimpleNamespace(server_name="tavily", name="tavily_search")
    assert await registry._intercept(request, handler) is result
    assert events(caplog)[-1]["event"] == "mcp_tool_failed"
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_model_failure_is_attributed_without_payload(caplog):
    from langchain_core.messages import HumanMessage

    from veridex.config import Settings
    from veridex.llm.router import invoke_with_fallback, route

    caplog.set_level("INFO")
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError("SECRET-provider-body")))
    config = Settings(_env_file=None, google_api_key="g")
    with turn_context(), pytest.raises(TimeoutError):
        await invoke_with_fallback(
            route("supervisor", config=config),
            [HumanMessage(content="SECRET-prompt")],
            factory=lambda provider: model,
            config=config,
        )
    assert events(caplog)[-1]["event"] == "model_failed"
    assert events(caplog)[-1]["exception_class"] == "TimeoutError"
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
async def test_concurrent_contexts_do_not_cross(caplog):
    caplog.set_level("INFO")

    async def task():
        with turn_context():
            before = correlation_id()
            await asyncio.sleep(0)
            assert correlation_id() == before
            return before

    assert len(set(await asyncio.gather(task(), task()))) == 2
    assert correlation_id() is None


@pytest.mark.asyncio
async def test_handled_agent_limit_records_failure(caplog):
    caplog.set_level("INFO")

    @observed("agent")
    async def limited():
        return {"status": "error", "response": "SECRET-response"}

    assert (await limited())["status"] == "error"
    assert events(caplog)[-1]["event"] == "agent_failed"
    assert "SECRET" not in caplog.text
