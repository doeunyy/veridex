import asyncio
from unittest.mock import Mock

import httpx
import pytest
from langchain_core.messages import AIMessage
from test_agent_mcp import ScriptedModel, call, request
from test_agent_mcp import fake_servers as fake_servers  # noqa: PLC0414

from veridex.agent import mcp_service
from veridex.agent.budgets import SessionCapacityError
from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.api.app import create_app
from veridex.config import Settings
from veridex.rag import embeddings


def limits(**kwargs):
    return Settings(_env_file=None, **kwargs)


@pytest.mark.asyncio
async def test_tool_budget_rejects_entire_parallel_round_and_repairs(fake_servers):
    _, log = fake_servers
    model = ScriptedModel(
        [
            request(call("list_documents", call_id="one"), call("list_documents", call_id="two")),
            AIMessage(content="Recovered"),
        ]
    )
    async with open_mcp_agent_service({}, model=model, limits=limits(agent_max_tool_calls=1)) as s:
        trace = await s.achat_with_trace("Search", "a")
        assert trace["error"] == "tool_call_limit"
        assert log == []
        assert all(not r["invocation_completed"] for r in trace["tool_results"])
        history = await s.aget_history("a")
        assert {c["id"] for m in history if m.type == "ai" for c in m.tool_calls} == {
            m.tool_call_id for m in history if m.type == "tool"
        }
        assert await s.achat("Continue", "a") == "Recovered"


@pytest.mark.asyncio
async def test_tool_budget_counts_across_rounds_and_resets_per_turn(fake_servers):
    _, log = fake_servers
    model = ScriptedModel(
        [
            request(call("list_documents", call_id="one")),
            request(call("list_documents", call_id="two")),
            request(call("list_documents", call_id="three")),
            AIMessage(content="Done"),
        ]
    )
    async with open_mcp_agent_service({}, model=model, limits=limits(agent_max_tool_calls=1)) as s:
        assert (await s.achat_with_trace("First", "a"))["error"] == "tool_call_limit"
        assert len(log) == 1
        assert await s.achat("Second", "a") == "Done"
        assert len(log) == 2


@pytest.mark.asyncio
async def test_model_budget_and_context_guard_prevent_extra_provider_calls(fake_servers):
    model = ScriptedModel([request(call("list_documents"))])
    async with open_mcp_agent_service({}, model=model, limits=limits(agent_max_model_calls=1)) as s:
        assert (await s.achat_with_trace("Search", "a"))["error"] == "model_call_limit"
        assert len(model.messages) == 1
        assert (await s.achat_with_trace("x" * 70_000, "b"))["error"] == "context_limit"
        assert len(model.messages) == 1


@pytest.mark.asyncio
async def test_retention_compacts_checkpoints_keeps_two_turn_memory_and_isolation(fake_servers):
    model = ScriptedModel([AIMessage(content=f"answer-{i}") for i in range(5)])
    async with open_mcp_agent_service({}, model=model, limits=limits(agent_history_turns=2)) as s:
        saver = s.checkpointer
        for i in range(4):
            await s.achat(f"query-{i}", "a")
            assert len(list(saver.list({"configurable": {"thread_id": "a"}}))) == 1
        assert s.checkpointer is saver
        assert [m.content for m in await s.aget_history("a") if m.type == "human"] == [
            "query-2",
            "query-3",
        ]
        assert any(m.content == "query-2" for m in model.messages[3])
        await s.achat("isolated", "b")
        assert not any(m.content.startswith("query-") for m in model.messages[4])


@pytest.mark.asyncio
async def test_session_capacity_and_expiry_remove_checkpoint_and_lock(fake_servers, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(mcp_service, "monotonic", lambda: clock[0])
    model = ScriptedModel([AIMessage(content="First"), AIMessage(content="Second")])
    async with open_mcp_agent_service(
        {}, model=model, limits=limits(agent_max_sessions=1, agent_session_ttl_seconds=60)
    ) as s:
        await s.achat("first", "a")
        with pytest.raises(SessionCapacityError):
            await s.achat("second", "b")
        assert [m.content for m in await s.aget_history("a") if m.type == "human"] == ["first"]
        clock[0] = 61
        await s.achat("second", "b")
        assert "a" not in s._session_locks
        assert await s.checkpointer.aget_tuple({"configurable": {"thread_id": "a"}}) is None


@pytest.mark.asyncio
async def test_active_and_waiting_sessions_cannot_expire(fake_servers, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(mcp_service, "monotonic", lambda: clock[0])
    entered, release = asyncio.Event(), asyncio.Event()
    model = ScriptedModel([])

    async def answer(messages):
        entered.set()
        await release.wait()
        return AIMessage(content="Done")

    model.ainvoke = answer
    async with open_mcp_agent_service(
        {}, model=model, limits=limits(agent_max_sessions=1, agent_session_ttl_seconds=60)
    ) as s:
        first = asyncio.create_task(s.achat("first", "a"))
        await entered.wait()
        second = asyncio.create_task(s.achat("second", "a"))
        await asyncio.sleep(0)
        clock[0] = 100
        with pytest.raises(SessionCapacityError):
            await s.achat("other", "b")
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert s._session_users["a"] == 1
        release.set()
        assert await first == "Done"
        assert len(await s.aget_history("a")) == 2


@pytest.mark.asyncio
async def test_session_capacity_http_error_and_exact_memory_contract(fake_servers):
    model = ScriptedModel([AIMessage(content="First"), AIMessage(content="Second")])
    async with open_mcp_agent_service({}, model=model, limits=limits(agent_max_sessions=1)) as s:
        app = create_app(agent_service=s, config=limits())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            for query, response in [("first", "First"), ("second", "Second")]:
                r = await c.post("/chat", json={"query": query, "session_id": "a"})
                assert r.status_code == 200 and r.json() == {"response": response}
            assert any(m.content == "first" for m in model.messages[1])
            r = await c.post("/chat", json={"query": "other", "session_id": "b"})
            assert r.status_code == 429 and r.json() == {"detail": "Session capacity exhausted."}


@pytest.mark.asyncio
async def test_provider_construction_uses_supported_limits_without_calls(fake_servers, monkeypatch):
    model = ScriptedModel([AIMessage(content="Hello")])
    constructor = Mock(return_value=model)
    monkeypatch.setattr(mcp_service, "ChatOpenAI", constructor)
    monkeypatch.setattr(mcp_service.settings, "openai_api_key", "test-only")
    async with open_mcp_agent_service({}, limits=limits()) as s:
        assert await s.achat("Hi", "a") == "Hello"
    assert constructor.call_args.kwargs["max_completion_tokens"] == 4096
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert constructor.call_args.kwargs["timeout"] == 30
    embedding_constructor = Mock()
    monkeypatch.setattr(embeddings, "OpenAIEmbeddings", embedding_constructor)
    embeddings.get_embeddings()
    assert embedding_constructor.call_args.kwargs["max_retries"] == 0
    assert embedding_constructor.call_args.kwargs["request_timeout"] == 30


def test_public_demo_default_admission_and_validation():
    config = limits()
    assert (config.api_max_active_requests, config.api_max_waiting_requests) == (1, 0)
    for field, value in [
        ("agent_max_sessions", 0),
        ("agent_history_turns", 1),
        ("provider_max_retries", 2),
        ("agent_max_completion_tokens", 0),
        ("agent_session_ttl_seconds", float("inf")),
    ]:
        with pytest.raises(ValueError):
            limits(**{field: value})


@pytest.mark.asyncio
async def test_live_provider_regression_requires_explicit_opt_in(monkeypatch, tmp_path):
    from test_agent_mcp_protocol import test_live_llm_evidence_and_multiserver

    monkeypatch.delenv("VERIDEX_RUN_LIVE_PROVIDERS", raising=False)
    with pytest.raises(pytest.skip.Exception, match="explicit"):
        await test_live_llm_evidence_and_multiserver(tmp_path)


@pytest.mark.asyncio
async def test_concurrent_turn_budgets_are_independent_and_close_clears_memory(fake_servers):
    class ParallelModel(ScriptedModel):
        async def ainvoke(self, messages):
            await asyncio.sleep(0)
            if messages[-1].type == "human":
                return request(call("list_documents", call_id=messages[-1].content))
            return AIMessage(content="Done")

    async with open_mcp_agent_service(
        {}, model=ParallelModel([]), limits=limits(agent_max_tool_calls=1)
    ) as service:
        results = await asyncio.gather(
            service.achat_with_trace("a", "a"), service.achat_with_trace("b", "b")
        )
        assert all(result["status"] == "success" for result in results)
        assert all(result["call_counts"] == {"list_documents": 1} for result in results)
        saver = service.checkpointer
    assert service._session_locks == service._session_users == service._session_used == {}
    assert await saver.aget_tuple({"configurable": {"thread_id": "a"}}) is None
    assert await saver.aget_tuple({"configurable": {"thread_id": "b"}}) is None
