import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import ToolException
from langchain_mcp_adapters.callbacks import Callbacks
from mcp.types import (
    CallToolResult,
    Implementation,
    InitializeResult,
    ListToolsResult,
    ServerCapabilities,
    TextContent,
    Tool,
)

from veridex.config import Settings
from veridex.mcp import client as mcp_client

TOOL = Tool(
    name="example", description="Example tool", inputSchema={"type": "object", "properties": {}}
)


class FakeSession:
    def __init__(self, tools):
        self.initialize = AsyncMock(
            return_value=InitializeResult(
                protocolVersion="2025-11-25",
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="Test Server", version="1"),
            )
        )
        self.list_tools = AsyncMock(return_value=ListToolsResult(tools=tools))
        self.call_tool = AsyncMock(
            return_value=CallToolResult(
                content=[TextContent(type="text", text='{"value": 7}')],
                structuredContent={"value": 7},
            )
        )


class FakeClient:
    def __init__(self, sessions):
        self.connections = dict.fromkeys(sessions)
        self.sessions = sessions
        self.callbacks = Callbacks()
        self.opened = []
        self.closed = []
        self.failed_server = None

    @asynccontextmanager
    async def session(self, server, *, auto_initialize):
        assert auto_initialize is False
        if server == self.failed_server:
            raise OSError("SECRET connection details")
        self.opened.append(server)
        try:
            yield self.sessions[server]
        finally:
            self.closed.append(server)


@pytest.fixture
def fake_client(monkeypatch):
    fake = FakeClient({"server": FakeSession([TOOL])})
    monkeypatch.setattr(mcp_client, "create_client", lambda connections: fake)
    return fake


def test_default_configuration_is_lazy_and_scoped(tmp_path):
    config = Settings(
        _env_file=None, openai_api_key="openai-secret", tavily_api_key="tavily-secret"
    )
    connections = mcp_client.default_connections(
        project_root=tmp_path, config=config, python_executable="python-test"
    )
    assert list(connections) == ["evidence", "web_search", "workspace"]
    for name, connection in connections.items():
        assert connection["transport"] == "stdio"
        assert connection["command"] == "python-test"
        assert connection["args"] == ["-m", f"veridex.mcp.servers.{name}"]
        assert "--protocol-smoke" not in connection["args"]
        assert connection["cwd"] == str(tmp_path)
    assert connections["evidence"]["env"]["OPENAI_API_KEY"] == "openai-secret"
    assert "TAVILY_API_KEY" not in connections["evidence"]["env"]
    assert connections["web_search"]["env"]["TAVILY_API_KEY"] == "tavily-secret"
    assert "OPENAI_API_KEY" not in connections["web_search"]["env"]
    assert connections["workspace"]["env"]["DOCUMENTS_DIR"] == str(tmp_path / "data/papers")
    assert "API_KEY" not in " ".join(connections["workspace"]["env"])
    client = mcp_client.create_client(connections)
    connections["evidence"]["args"].append("mutated")
    assert "mutated" not in client.connections["evidence"]["args"]
    assert client.handle_tool_errors is False


@pytest.mark.parametrize(
    "connections",
    [
        {},
        {"bad name": {}},
        {"x": "bad"},
        {"x": {}},
        {"x": {"transport": "stdio", "command": "python", "args": "not-list"}},
        {"x": {"transport": "stdio", "command": "", "args": []}},
        {"x": {"transport": "stdio", "command": "python", "args": [123]}},
        {"x": {"transport": "http"}},
    ],
)
def test_configuration_rejects_invalid_inputs(connections):
    with pytest.raises(mcp_client.MCPClientError):
        mcp_client.create_client(connections)


def test_http_connection_preserved_for_future_transport():
    connections = {
        "cloud": {
            "transport": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer secret"},
        }
    }
    client = mcp_client.create_client(connections)
    assert client.connections == connections


@pytest.mark.asyncio
async def test_discovery_refresh_artifacts_and_closed_tools(fake_client):
    async with mcp_client.connect_servers({}) as registry:
        assert [tool.name for tool in registry.tools] == ["example"]
        message = await registry.invoke("example", {}, call_id="call-1")
        assert message.status == "success"
        assert message.tool_call_id == "call-1"
        assert message.artifact == {"structured_content": {"value": 7}}
        old_tool = registry.tools[0]
        assert [tool.name for tool in await registry.refresh()] == ["example"]
        assert fake_client.opened == ["server"]
        report = registry.inspection()
        assert report["servers"][0]["identity"]["name"] == "Test Server"
        assert report["servers"][0]["tools"][0]["description"] == TOOL.description
        assert report["servers"][0]["tools"][0]["input_schema"] == TOOL.inputSchema
        with pytest.raises(mcp_client.MCPClientError, match="Unknown discovered"):
            await registry.invoke("missing", {})
    assert fake_client.closed == ["server"]
    with pytest.raises(mcp_client.MCPClientError, match="closed"):
        await registry.invoke("example", {})
    with pytest.raises(mcp_client.MCPClientError, match="closed"):
        await old_tool.ainvoke({})
    with pytest.raises(mcp_client.MCPClientError, match="closed"):
        await registry.refresh()


@pytest.mark.asyncio
async def test_protocol_echo_is_excluded(fake_client):
    fake_client.sessions["server"].list_tools.return_value = ListToolsResult(
        tools=[TOOL, TOOL.model_copy(update={"name": "protocol_echo"})]
    )
    async with mcp_client.connect_servers({}) as registry:
        assert list(registry.entries) == ["example"]


@pytest.mark.asyncio
async def test_duplicate_names_fail_and_close_all_sessions(fake_client):
    fake_client.sessions["other"] = FakeSession([TOOL])
    fake_client.connections["other"] = None
    with pytest.raises(mcp_client.MCPClientError, match="Duplicate.*example.*server.*other"):
        async with mcp_client.connect_servers({}):
            pytest.fail("Colliding registry must not be exposed")
    assert fake_client.closed == ["other", "server"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["connection", "discovery", "initialization"])
async def test_failure_paths_cleanup_and_redaction(fake_client, failure):
    fake_client.sessions["other"] = FakeSession([TOOL.model_copy(update={"name": "other_tool"})])
    fake_client.connections["other"] = None
    if failure == "connection":
        fake_client.failed_server = "other"
    elif failure == "discovery":
        fake_client.sessions["other"].list_tools.side_effect = RuntimeError("SECRET discovery")
    else:
        fake_client.sessions["other"].initialize.side_effect = RuntimeError("SECRET handshake")
    with pytest.raises(mcp_client.MCPClientError) as error:
        async with mcp_client.connect_servers({}):
            pytest.fail("Failed discovery must not yield a registry")
    assert "other" in str(error.value)
    assert "SECRET" not in str(error.value)
    assert sorted(fake_client.closed) == sorted(fake_client.opened)


@pytest.mark.asyncio
async def test_pagination_and_failed_refresh_is_transactional(fake_client):
    session = fake_client.sessions["server"]
    session.list_tools.side_effect = [
        ListToolsResult(tools=[TOOL], nextCursor="next"),
        ListToolsResult(tools=[TOOL.model_copy(update={"name": "second"})]),
    ]
    async with mcp_client.connect_servers({}) as registry:
        assert list(registry.entries) == ["example", "second"]
        session.list_tools.assert_awaited_with(cursor="next")
        session.list_tools.side_effect = RuntimeError("SECRET")
        with pytest.raises(mcp_client.MCPClientError, match="discovery failed"):
            await registry.refresh()
        assert list(registry.entries) == ["example", "second"]


@pytest.mark.asyncio
async def test_mcp_tool_error_is_not_success(fake_client):
    session = fake_client.sessions["server"]
    session.call_tool.return_value = CallToolResult(
        isError=True, content=[TextContent(type="text", text="Missing credentials")]
    )
    async with mcp_client.connect_servers({}) as registry:
        with pytest.raises(ToolException, match="Missing credentials"):
            await registry.invoke("example", {})
        session.call_tool.return_value = CallToolResult(content=[], structuredContent={"ok": True})
        assert (await registry.invoke("example", {})).artifact["structured_content"] == {"ok": True}


@pytest.mark.asyncio
async def test_same_session_calls_are_serialized(fake_client):
    active = 0
    maximum = 0

    async def call(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.01)
            return CallToolResult(content=[], structuredContent={"ok": True})
        finally:
            active -= 1

    fake_client.sessions["server"].call_tool.side_effect = call
    async with mcp_client.connect_servers({}) as registry:
        await asyncio.gather(*[registry.invoke("example", {}) for _ in range(3)])
    assert maximum == 1


@pytest.mark.asyncio
async def test_tool_deadline_and_recovery(fake_client):
    cancelled = asyncio.Event()

    async def stalled(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    session = fake_client.sessions["server"]
    session.call_tool.side_effect = stalled
    async with mcp_client.connect_servers({}, timeout=0.01) as registry:
        with pytest.raises(mcp_client.MCPClientError, match="timed out"):
            await registry.invoke("example", {})
        assert cancelled.is_set()
        session.call_tool.side_effect = None
        assert (await registry.invoke("example", {})).status == "success"


@pytest.mark.asyncio
async def test_transport_failure_and_consumer_error_cleanup(fake_client):
    fake_client.sessions["server"].call_tool.side_effect = RuntimeError("SECRET transport")
    with pytest.raises(ValueError, match="consumer failed"):
        async with mcp_client.connect_servers({}) as registry:
            with pytest.raises(mcp_client.MCPClientError, match="tool request failed") as error:
                await registry.invoke("example", {})
            assert "SECRET" not in str(error.value)
            raise ValueError("consumer failed")
    assert fake_client.closed == ["server"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["initialize", "list_tools"])
async def test_discovery_deadlines_cleanup(fake_client, stage):
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    getattr(fake_client.sessions["server"], stage).side_effect = stalled
    with pytest.raises(mcp_client.MCPClientError):
        async with mcp_client.connect_servers({}, timeout=0.01):
            pytest.fail("Discovery deadline must fail")
    assert fake_client.closed == ["server"]


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
async def test_invalid_deadlines(fake_client, timeout):
    with pytest.raises(mcp_client.MCPClientError, match="positive"):
        async with mcp_client.connect_servers({}, timeout=timeout):
            pytest.fail("Invalid deadline must fail before connecting")
    assert not fake_client.opened


@pytest.mark.asyncio
async def test_owner_cancellation_closes_sessions(fake_client):
    entered = asyncio.Event()

    async def run():
        async with mcp_client.connect_servers({}):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fake_client.closed == ["server"]


@pytest.mark.asyncio
async def test_sdk_teardown_exception_group_is_redacted(fake_client):
    original_session = fake_client.session

    @asynccontextmanager
    async def broken_session(*args, **kwargs):
        async with original_session(*args, **kwargs) as session:
            yield session
        raise ExceptionGroup("SECRET headers", [RuntimeError("SECRET payload")])

    fake_client.session = broken_session
    with pytest.raises(mcp_client.MCPClientError, match="lifecycle failed") as error:
        async with mcp_client.connect_servers({}):
            pass
    assert "SECRET" not in str(error.value)
    assert fake_client.closed == ["server"]


@pytest.mark.asyncio
async def test_distinct_server_calls_can_overlap(fake_client):
    fake_client.sessions["other"] = FakeSession([TOOL.model_copy(update={"name": "other_tool"})])
    fake_client.connections["other"] = None
    count = 0
    ready = asyncio.Event()

    async def call(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=1)
        return CallToolResult(content=[], structuredContent={"ok": True})

    for session in fake_client.sessions.values():
        session.call_tool.side_effect = call
    async with mcp_client.connect_servers({}) as registry:
        results = await asyncio.gather(
            registry.invoke("example", {}), registry.invoke("other_tool", {})
        )
        assert all(result.status == "success" for result in results)
