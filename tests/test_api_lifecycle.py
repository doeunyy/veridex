import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from agents_fakes import CONFIG, system, tool_call
from agents_fakes import factory as fake_models
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from test_mcp_multi_server import EXPECTED, is_alive, process_ids
from test_mcp_multi_server import connections as connections  # noqa: PLC0414 — pytest fixture

from veridex.agents.prompts import RESEARCH_PROMPT
from veridex.agents.service import REQUIRED_SERVERS, open_multi_agent_service
from veridex.api import lifecycle
from veridex.api.app import create_app
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


def greeter(provider, mode, messages):
    return {"next": "finish", "reason": "Greeting.", "direct_answer": "Hello."}


def build_app(configs, script=greeter):
    make, _ = fake_models(script)
    return create_app(
        service_factory=lambda: open_multi_agent_service(
            connections=configs, config=CONFIG, factory=make
        )
    )


def http_client(application):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


async def test_startup_real_mcp_turns_session_isolation_and_shutdown(connections):
    configs, log, _ = connections
    supervisor_inputs = []

    def script(provider, mode, messages):
        if mode == "structured":
            supervisor_inputs.append([m.content for m in messages[1:]])
            if any(m.type == "human" and "research (ok)" in m.content for m in messages):
                return {"next": "finish", "reason": "Answered."}
            return {"next": "research", "task": "Find evidence", "reason": "Needs evidence."}
        assert system(messages) == RESEARCH_PROMPT
        if messages[-1].type == "tool":
            return AIMessage(content="Evidence found [paper_2026:p1:c000].")
        return tool_call("search_evidence", {"query": "evidence"})

    application = build_app(configs, script)
    owner = Lifespan(application)
    async with http_client(application) as client:
        assert (await client.get("/ready")).status_code == 503
        assert (await client.get("/health")).status_code == 200
        await owner.start()
        service = application.state.agent_service
        pids = process_ids(log)
        assert len(pids) == 4 and all(is_alive(pid) for pid in pids)
        assert set(service.registry.entries) == EXPECTED
        assert set(service.registry.servers) == REQUIRED_SERVERS
        assert (await client.get("/ready")).json() == {"status": "ready"}
        try:
            for query, session in [("First", "a"), ("Follow up", "a"), ("Other", "b")]:
                response = await client.post("/chat", json={"query": query, "session_id": session})
                assert response.status_code == 200
                assert response.json() == {"response": "Evidence found [paper_2026:p1:c000]."}
            assert process_ids(log) == pids
            follow_up = supervisor_inputs[2]
            other_session = supervisor_inputs[4]
            assert "First" in follow_up and "First" not in other_session
        finally:
            await owner.stop()
        assert all(not is_alive(pid) for pid in pids)
        assert not service.is_usable
        assert (await client.get("/ready")).status_code == 503
        assert (
            await client.post("/chat", json={"query": "New", "session_id": "a"})
        ).status_code == 503


async def test_partial_startup_failure_is_unready_and_reaps_children(connections):
    configs, log, _ = connections
    configs["catalog"]["command"] = "/nonexistent/SECRET-command"
    application = build_app(configs)
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
    configs.pop("tavily")
    application = build_app(configs)
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
        make, _ = fake_models(greeter)
        async with open_multi_agent_service(
            connections=configs, config=CONFIG, factory=make
        ) as service:
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


async def test_owner_cancellation_preserved_and_children_reaped(connections):
    configs, log, _ = connections
    application = build_app(configs)
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
    application = build_app(configs)
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
    application = build_app(configs)
    owner = Lifespan(application)
    startup = asyncio.create_task(owner.start())
    async with asyncio.timeout(20):
        while len(process_ids(log)) != 2:
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

    async def decide(messages):
        entered.set()
        await release.wait()
        return {"next": "finish", "reason": "r", "direct_answer": "Completed."}

    class Slow:
        def with_structured_output(self, schema, **kwargs):
            return RunnableLambda(lambda m: None, afunc=decide) | schema.model_validate

    application = create_app(
        service_factory=lambda: open_multi_agent_service(
            connections=configs, config=CONFIG, factory=lambda provider: Slow()
        )
    )
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

    starter = Mock(side_effect=AssertionError("MCP must not start"))
    monkeypatch.setattr(lifecycle, "open_multi_agent_service", starter)
    service = AsyncMock()
    application = create_app(agent_service=service)
    owner = Lifespan(application)
    await owner.start()
    assert application.state.agent_service is service
    await owner.stop()
    starter.assert_not_called()
    service.aclose.assert_not_called()  # The injected instance remains caller-owned.
    with pytest.raises(RuntimeError, match="already started"):
        await Lifespan(application).start()
