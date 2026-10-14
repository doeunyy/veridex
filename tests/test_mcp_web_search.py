import asyncio
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tavily.errors import InvalidAPIKeyError, UsageLimitExceededError
from tavily.errors import TimeoutError as TavilyTimeoutError
from test_mcp_protocol import ROOT

from veridex.mcp.servers import web_search

SECRET = "tvly-test-secret-never-log"
PROVIDER_RESULT = {
    "title": "Title π",
    "url": "https://example.com/a%2Fb?x=1&y=2#fragment",
    "content": 'A "snippet"\nπ',
}
INVALID = [
    {},
    {"query": ""},
    {"query": " \n"},
    {"query": 123},
    *[{"query": "q", "max_results": value} for value in (0, 11, -1, 1.5, "5", True)],
]


@pytest.fixture
def tavily(monkeypatch):
    monkeypatch.setattr(web_search.settings, "tavily_api_key", SECRET)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.search.return_value = {"results": [PROVIDER_RESULT]}
    constructor = Mock(return_value=client)
    monkeypatch.setattr(web_search, "AsyncTavilyClient", constructor)
    return constructor, client


@pytest.mark.asyncio
async def test_results_schema_defaults_and_provider_metadata(tavily):
    constructor, provider = tavily
    provider.search.return_value = {
        "query": "provider rewrite",
        "request_id": SECRET,
        "results": [
            PROVIDER_RESULT,
            {
                **PROVIDER_RESULT,
                "published_date": "2026-10-01",
                "score": 0.9,
                "raw_content": SECRET,
            },
        ],
    }
    async with Client(web_search.create_server()) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["search_web"]
        schema = tools[0].inputSchema
        assert schema["required"] == ["query"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["query"] == {"type": "string", "minLength": 1}
        assert schema["properties"]["max_results"] == {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "default": 5,
        }
        item_schema = tools[0].outputSchema["properties"]["results"]["items"]
        assert item_schema["required"] == ["title", "url", "content"]
        assert item_schema["properties"]["published_date"]["type"] == "string"
        for limit in (None, 1, 10):
            args = {"query": "q"}
            if limit is not None:
                args["max_results"] = limit
            result = await client.call_tool("search_web", args)
            assert result.structured_content == {
                "query": "q",
                "results": [
                    PROVIDER_RESULT,
                    {**PROVIDER_RESULT, "published_date": "2026-10-01"},
                ],
            }
            provider.search.assert_awaited_with(
                query="q",
                max_results=limit or 5,
                search_depth="basic",
                include_answer=False,
                include_raw_content=False,
                timeout=web_search.SEARCH_TIMEOUT_SECONDS,
            )
    constructor.assert_called_with(api_key=SECRET)
    assert provider.__aexit__.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", INVALID)
async def test_invalid_input_does_not_call_provider(tavily, arguments):
    constructor, _ = tavily
    async with Client(web_search.create_server()) as client:
        result = await client.call_tool("search_web", arguments, raise_on_error=False)
        assert result.is_error
    constructor.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "", " \n"])
async def test_missing_credentials(tavily, monkeypatch, key):
    constructor, _ = tavily
    monkeypatch.setattr(web_search.settings, "tavily_api_key", key)
    async with Client(web_search.create_server()) as client:
        result = await client.call_tool("search_web", {"query": "q"}, raise_on_error=False)
        assert result.is_error
        assert "TAVILY_API_KEY is not configured" in result.content[0].text
    constructor.assert_not_called()


@pytest.mark.asyncio
async def test_empty_and_null_date(tavily):
    _, provider = tavily
    provider.search.side_effect = [
        {"results": []},
        {"results": [{**PROVIDER_RESULT, "published_date": None}]},
    ]
    async with Client(web_search.create_server()) as client:
        empty = await client.call_tool("search_web", {"query": "q"})
        assert empty.structured_content == {"query": "q", "results": []}
        result = await client.call_tool("search_web", {"query": "q"})
        assert result.structured_content["results"] == [PROVIDER_RESULT]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError(SECRET),
        InvalidAPIKeyError(SECRET),
        UsageLimitExceededError(SECRET),
        TimeoutError(SECRET),
        TavilyTimeoutError(20),
    ],
)
async def test_provider_errors_are_safe_and_recover(tavily, failure, caplog, capsys):
    _, provider = tavily
    provider.search.side_effect = [failure, {"results": [PROVIDER_RESULT]}]
    async with Client(web_search.create_server()) as client:
        failed = await client.call_tool("search_web", {"query": "q"}, raise_on_error=False)
        assert failed.is_error
        assert (
            "timed out"
            if isinstance(failure, (TimeoutError, TavilyTimeoutError))
            else "provider request failed"
        ) in failed.content[0].text
        assert SECRET not in str(failed)
        assert not (await client.call_tool("search_web", {"query": "q"})).is_error
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err + caplog.text
    assert provider.__aexit__.await_count == 2


@pytest.mark.asyncio
async def test_actual_deadline_cancels_provider_and_recovers(tavily, monkeypatch):
    _, provider = tavily
    monkeypatch.setattr(web_search, "SEARCH_TIMEOUT_SECONDS", 0.05)
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    provider.search.side_effect = slow
    async with Client(web_search.create_server()) as client:
        async with asyncio.timeout(2):
            failed = await client.call_tool("search_web", {"query": "q"}, raise_on_error=False)
        assert failed.is_error and "timed out" in failed.content[0].text
        assert cancelled.is_set()
        provider.search.side_effect = None
        assert not (await client.call_tool("search_web", {"query": "q"})).is_error
    assert provider.__aexit__.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"results": None},
        {"results": [{"url": SECRET}]},
        {"results": [{**PROVIDER_RESULT, "title": 123}]},
    ],
)
async def test_malformed_provider_response_is_safe(tavily, response, caplog):
    _, provider = tavily
    provider.search.return_value = response
    async with Client(web_search.create_server()) as client:
        failed = await client.call_tool("search_web", {"query": "q"}, raise_on_error=False)
        assert failed.is_error and "provider request failed" in failed.content[0].text
        assert SECRET not in str(failed) + caplog.text


@pytest.mark.asyncio
async def test_concurrent_calls_are_async(tavily):
    _, provider = tavily
    entered = 0
    ready = asyncio.Event()

    async def retrieve(**kwargs):
        nonlocal entered
        entered += 1
        if entered == 3:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=2)
        return {"results": [PROVIDER_RESULT]}

    provider.search.side_effect = retrieve
    async with Client(web_search.create_server()) as client:
        results = await asyncio.gather(
            *[client.call_tool("search_web", {"query": str(i)}) for i in range(3)]
        )
        assert all(result.structured_content["results"] == [PROVIDER_RESULT] for result in results)


@pytest.mark.asyncio
async def test_stdio_schema_calls_failures_and_recovery(tmp_path):
    # Only this test launcher replaces the SDK. No production mock flag or API credits.
    launcher = tmp_path / "web_fixture.py"
    launcher.write_text(
        "import asyncio\n"
        "from veridex.mcp.servers import web_search\n"
        "from tavily.errors import TimeoutError as TavilyTimeoutError\n"
        f"web_search.settings.tavily_api_key = {SECRET!r}\n"
        "web_search.SEARCH_TIMEOUT_SECONDS = 0.1\n"
        "class FakeTavily:\n"
        "    def __init__(self, api_key): pass\n"
        "    async def __aenter__(self): return self\n"
        "    async def __aexit__(self, *args): pass\n"
        "    async def search(self, query, **kwargs):\n"
        f"        if query == 'error': raise RuntimeError({SECRET!r})\n"
        "        if query == 'sdk-timeout': raise TavilyTimeoutError(20)\n"
        "        if query == 'timeout': await asyncio.Event().wait()\n"
        "        if query == 'empty': return {'results': []}\n"
        "        assert kwargs['max_results'] == 3\n"
        f"        return {{'results': [{PROVIDER_RESULT!r}, "
        f"{{**{PROVIDER_RESULT!r}, 'published_date': '2026-10-01'}}]}}\n"
        "web_search.AsyncTavilyClient = FakeTavily\n"
        "web_search.create_server().run(transport='stdio')\n"
    )
    diagnostics = tmp_path / "stderr.log"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(launcher)],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    with diagnostics.open("w", encoding="utf-8") as errlog:
        async with (
            asyncio.timeout(30),
            stdio_client(parameters, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "Veridex Web Search"
            tools = (await session.list_tools()).tools
            assert [tool.name for tool in tools] == ["search_web"]
            assert tools[0].inputSchema["required"] == ["query"]
            assert tools[0].inputSchema["properties"]["max_results"] == {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
            }
            assert tools[0].outputSchema["properties"]["results"]["items"]["required"] == [
                "title",
                "url",
                "content",
            ]
            arguments = {"query": "q", "max_results": 3}
            for _ in range(2):
                result = await session.call_tool("search_web", arguments)
                assert not result.isError
                assert result.structuredContent == {
                    "query": "q",
                    "results": [
                        PROVIDER_RESULT,
                        {**PROVIDER_RESULT, "published_date": "2026-10-01"},
                    ],
                }
            empty = await session.call_tool("search_web", {"query": "empty"})
            assert not empty.isError and empty.structuredContent == {
                "query": "empty",
                "results": [],
            }
            for args in INVALID:
                assert (await session.call_tool("search_web", args)).isError
            for query in ("error", "sdk-timeout", "timeout"):
                result = await session.call_tool("search_web", {"query": query})
                assert result.isError
                assert SECRET not in str(result)
                assert (
                    "provider request failed" if query == "error" else "timed out"
                ) in result.content[0].text
                assert not (await session.call_tool("search_web", arguments)).isError
    stderr = diagnostics.read_text(encoding="utf-8")
    assert "Starting MCP server" in stderr
    assert SECRET not in stderr


@pytest.mark.asyncio
async def test_default_stdio_missing_credentials(tmp_path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "veridex.mcp.servers.web_search"],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "TAVILY_API_KEY": ""},
    )
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as errlog:
        async with (
            asyncio.timeout(20),
            stdio_client(parameters, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            assert [tool.name for tool in (await session.list_tools()).tools] == ["search_web"]
            for _ in range(2):
                result = await session.call_tool("search_web", {"query": "q"})
                assert result.isError
                assert "TAVILY_API_KEY is not configured" in result.content[0].text
            assert [tool.name for tool in (await session.list_tools()).tools] == ["search_web"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_tavily_search():
    key = web_search.settings.tavily_api_key
    if not key or not key.strip() or key == "your_tavily_api_key":
        pytest.skip("Tavily credentials unavailable")
    async with Client(web_search.create_server()) as client:
        # Exactly one basic search request when explicitly opted into integration tests.
        result = await client.call_tool(
            "search_web",
            {
                "query": "retrieval augmented generation original paper",
                "max_results": 1,
            },
        )
        results = result.structured_content["results"]
        assert len(results) == 1
        assert results[0]["title"] and results[0]["url"] and results[0]["content"]
        assert results[0]["url"].startswith(("https://", "http://"))
