import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage
from test_agent_mcp import ScriptedModel, call, request
from test_agent_mcp_reliability import assert_balanced_history, wait_for_file
from test_agent_mcp_reliability import (
    observed_connections as observed_connections,  # noqa: PLC0414 — pytest fixture
)
from test_mcp_multi_server import EXPECTED, is_alive, process_ids
from test_mcp_multi_server import connections as connections  # noqa: PLC0414 — pytest fixture

from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.api import lifecycle
from veridex.api.app import create_app
from veridex.config import Settings
from veridex.mcp.client import MCPClientError

pytestmark = pytest.mark.asyncio


class Lifespan:
    """Drive actual ASGI startup/shutdown messages in one persistent owner task."""

    def __init__(self, application):
        self.application = application
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def start(self):
        self.task = asyncio.create_task(
            self.application(
                {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}},
                self.incoming.get,
                self.outgoing.put,
            )
        )
        await self.incoming.put({"type": "lifespan.startup"})
        message = await asyncio.wait_for(self.outgoing.get(), 30)
        self.last_message = message
        if message["type"] == "lifespan.startup.failed":
            await self.task
        assert message["type"] == "lifespan.startup.complete"

    async def stop(self):
        await self.incoming.put({"type": "lifespan.shutdown"})
        message = await asyncio.wait_for(self.outgoing.get(), 12)
        await self.task
        assert message["type"] == "lifespan.shutdown.complete"


def build_app(configs, model):
    return create_app(
        service_factory=lambda: open_mcp_agent_service(configs, model=model, request_timeout=15)
    )


def http_client(application):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


async def test_startup_memory_isolation_persistent_children_and_shutdown(connections):
    configs, log, _ = connections
    model = ScriptedModel(
        [
            request(call("list_documents")),
            AIMessage(content="Corpus available."),
            AIMessage(content="Follow-up."),
            AIMessage(content="Other session."),
        ]
    )
    application = build_app(configs, model)
    owner = Lifespan(application)
    async with http_client(application) as client:
        assert (await client.get("/ready")).status_code == 503
        assert (await client.get("/health")).status_code == 200
        await owner.start()
        service = application.state.agent_service
        saver = service.checkpointer
        pids = process_ids(log)
        assert len(pids) == 3 and all(is_alive(pid) for pid in pids)
        assert set(service.registry.entries) == EXPECTED
        assert set(service.registry.servers) == lifecycle.PRODUCTION_SERVERS
        assert (await client.get("/ready")).json() == {"status": "ready"}
        try:
            for query, session, answer in [
                ("List papers", "a", "Corpus available."),
                ("Follow up", "a", "Follow-up."),
                ("Hello", "b", "Other session."),
            ]:
                response = await client.post("/chat", json={"query": query, "session_id": session})
                assert response.status_code == 200
                assert response.json() == {"response": answer}
            assert service.checkpointer is saver
            assert process_ids(log) == pids
            history_a = await service.aget_history("a")
            history_b = await service.aget_history("b")
            assert [m.content for m in history_a if m.type == "human"] == [
                "List papers",
                "Follow up",
            ]
            assert [m.content for m in history_b if m.type == "human"] == ["Hello"]
            assert any(m.content == "List papers" for m in model.messages[2])
            assert not any(m.content == "List papers" for m in model.messages[3])
        finally:
            await owner.stop()
        assert all(not is_alive(pid) for pid in pids)
        assert not service.is_usable
        assert (await client.get("/ready")).status_code == 503
        assert (await client.get("/health")).status_code == 200
        assert (
            await client.post("/chat", json={"query": "New", "session_id": "a"})
        ).status_code == 503


async def test_partial_startup_failure_is_unready_and_reaps_children(connections):
    configs, log, _ = connections
    configs["workspace"]["command"] = "/nonexistent/SECRET-command"
    application = build_app(configs, ScriptedModel([]))
    owner = Lifespan(application)
    with pytest.raises(MCPClientError, match="^Agent application lifecycle failed.$"):
        await owner.start()
    assert "SECRET-command" not in owner.last_message["message"]
    assert application.state.agent_service is None
    assert len(process_ids(log)) == 2
    assert all(not is_alive(pid) for pid in process_ids(log))
    async with http_client(application) as client:
        assert (await client.get("/ready")).status_code == 503


async def test_missing_production_server_fails_before_publication(connections):
    configs, log, _ = connections
    configs.pop("web_search")
    application = build_app(configs, ScriptedModel([]))
    with pytest.raises(MCPClientError):
        await Lifespan(application).start()
    assert application.state.agent_service is None
    assert all(not is_alive(pid) for pid in process_ids(log))


async def test_same_task_ownership_and_unready_during_initialization(connections):
    configs, log, _ = connections
    initializing, release = asyncio.Event(), asyncio.Event()
    owners = []

    @asynccontextmanager
    async def factory():
        owners.append(asyncio.current_task())
        initializing.set()
        await release.wait()
        async with open_mcp_agent_service(configs, model=ScriptedModel([])) as service:
            try:
                yield service
            finally:
                owners.append(asyncio.current_task())

    application = create_app(service_factory=factory)
    owner = Lifespan(application)
    startup = asyncio.create_task(owner.start())
    await initializing.wait()
    async with http_client(application) as client:
        assert (await client.get("/ready")).status_code == 503
        release.set()
        await startup
        await owner.stop()
    assert owners[0] is owners[1] is owner.task
    assert all(not is_alive(pid) for pid in process_ids(log))


async def test_http_concurrency_and_same_session_serialization(connections):
    configs, log, _ = connections
    entered, release, overlap = asyncio.Event(), asyncio.Event(), asyncio.Event()
    model = ScriptedModel([])
    seen = []

    async def answer(messages):
        query = messages[-1].content
        seen.append(query)
        if query == "first":
            entered.set()
            await release.wait()
        if query == "other":
            overlap.set()
        return AIMessage(content=query)

    model.ainvoke = answer
    application = create_app(
        service_factory=lambda: open_mcp_agent_service(configs, model=model, request_timeout=15),
        config=Settings(_env_file=None, api_max_active_requests=4, api_max_waiting_requests=8),
    )
    owner = Lifespan(application)
    await owner.start()
    try:
        async with http_client(application) as client:
            first = asyncio.create_task(
                client.post("/chat", json={"query": "first", "session_id": "a"})
            )
            await entered.wait()
            second = asyncio.create_task(
                client.post("/chat", json={"query": "second", "session_id": "a"})
            )
            other = asyncio.create_task(
                client.post("/chat", json={"query": "other", "session_id": "b"})
            )
            await asyncio.wait_for(overlap.wait(), 2)
            assert "second" not in seen
            release.set()
            responses = await asyncio.gather(first, second, other)
            assert [r.json() for r in responses] == [
                {"response": "first"},
                {"response": "second"},
                {"response": "other"},
            ]
    finally:
        release.set()
        await owner.stop()
    assert all(not is_alive(pid) for pid in process_ids(log))


@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancelled_http_tool_round_repairs_history_and_reaps_children(
    observed_connections, shutdown
):
    configs, log, control = observed_connections
    model = ScriptedModel(
        [
            request(call("search_evidence", {"query": "slow"}, call_id="interrupted")),
            AIMessage(content="Recovered."),
        ]
    )
    application = build_app(configs, model)
    owner = Lifespan(application)
    await owner.start()
    service = application.state.agent_service
    async with http_client(application) as client:
        turn = asyncio.create_task(client.post("/chat", json={"query": "Slow", "session_id": "a"}))
        await wait_for_file(control / "evidence.slow.started")
        if shutdown:
            closing = asyncio.create_task(owner.stop())
            while not application.state.shutting_down:
                await asyncio.sleep(0.005)
            assert (await client.get("/ready")).status_code == 503
            assert (
                await client.post("/chat", json={"query": "New", "session_id": "b"})
            ).status_code == 503
        else:
            turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        snapshot = await service.graph.aget_state({"configurable": {"thread_id": "a"}})
        assert_balanced_history(snapshot.values["messages"])
        marker = next(m for m in snapshot.values["messages"] if m.type == "tool")
        assert marker.status == "error"
        assert marker.additional_kwargs["execution_interrupted"]
        assert marker.artifact is None
        (control / "release").touch()
        if shutdown:
            await closing
        else:
            assert (
                await client.post("/chat", json={"query": "Continue", "session_id": "a"})
            ).json() == {"response": "Recovered."}
            await owner.stop()
    assert not application.state.chat_tasks
    assert all(not is_alive(pid) for pid in process_ids(log))


async def test_owner_cancellation_preserved_and_children_reaped(connections):
    configs, log, _ = connections
    application = build_app(configs, ScriptedModel([]))
    owner = Lifespan(application)
    await owner.start()
    owner.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner.task
    assert application.state.agent_service is None
    assert all(not is_alive(pid) for pid in process_ids(log))


async def test_total_deadline_for_stubborn_children(connections, monkeypatch):
    configs, log, _ = connections
    launcher = configs["evidence"]["args"][0]
    path = Path(launcher)
    path.write_text(
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        + path.read_text()
        + "\nwhile True: time.sleep(1)\n"
    )
    monkeypatch.setattr(lifecycle, "SHUTDOWN_TIMEOUT", 2.5)
    application = build_app(configs, ScriptedModel([]))
    owner = Lifespan(application)
    await owner.start()
    started = asyncio.get_running_loop().time()
    with pytest.raises(MCPClientError):
        await owner.stop()
    assert asyncio.get_running_loop().time() - started < 4
    assert all(not is_alive(pid) for pid in process_ids(log))


async def test_startup_cancellation_reaps_partially_initialized_children(connections):
    configs, log, _ = connections
    path = Path(configs["workspace"]["args"][0])
    path.write_text(
        path.read_text().replace(
            "sys.argv = ['server']",
            "if role == 'workspace':\n    import time\n    time.sleep(60)\nsys.argv = ['server']",
        )
    )
    application = build_app(configs, ScriptedModel([]))
    owner = Lifespan(application)
    startup = asyncio.create_task(owner.start())
    async with asyncio.timeout(20):
        while len(process_ids(log)) != 3:
            await asyncio.sleep(0.01)
    assert application.state.agent_service is None
    owner.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert all(not is_alive(pid) for pid in process_ids(log))
    assert application.state.agent_service is None


async def test_short_turn_drains_successfully_before_shutdown(connections):
    configs, log, _ = connections
    entered, release = asyncio.Event(), asyncio.Event()
    model = ScriptedModel([])

    async def answer(messages):
        entered.set()
        await release.wait()
        return AIMessage(content="Completed.")

    model.ainvoke = answer
    application = build_app(configs, model)
    owner = Lifespan(application)
    await owner.start()
    async with http_client(application) as client:
        turn = asyncio.create_task(client.post("/chat", json={"query": "Hello", "session_id": "a"}))
        await entered.wait()
        closing = asyncio.create_task(owner.stop())
        while not application.state.shutting_down:
            await asyncio.sleep(0.005)
        release.set()
        assert (await turn).json() == {"response": "Completed."}
        await closing
    assert all(not is_alive(pid) for pid in process_ids(log))


async def test_injected_service_lifespan_bypasses_mcp_and_runs_only_once(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    factory = Mock(side_effect=AssertionError("MCP must not start"))
    monkeypatch.setattr(lifecycle, "open_mcp_agent_service", factory)
    service = AsyncMock()
    application = create_app(agent_service=service)
    owner = Lifespan(application)
    await owner.start()
    assert application.state.agent_service is service
    await owner.stop()
    factory.assert_not_called()
    service.aclose.assert_not_called()  # The injected instance remains caller-owned.
    with pytest.raises(RuntimeError, match="already started"):
        await Lifespan(application).start()
