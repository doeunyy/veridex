import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def evidence_session(errlog, *, smoke=True):
    args = ["-m", "veridex.mcp.servers.evidence"]
    if smoke:
        args.append("--protocol-smoke")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=args,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    async with (
        asyncio.timeout(20),
        stdio_client(parameters, errlog=errlog) as (read, write),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "Veridex Evidence"
        assert initialized.capabilities.tools is not None
        yield session


@pytest.mark.asyncio
async def test_stdio_schema_call_and_diagnostics(tmp_path):
    diagnostics = tmp_path / "stderr.log"
    with diagnostics.open("w", encoding="utf-8") as errlog:
        async with evidence_session(errlog) as session:
            tools = (await session.list_tools()).tools
            assert [tool.name for tool in tools] == ["protocol_echo"]
            schema = tools[0].inputSchema
            assert schema["type"] == "object"
            assert schema["required"] == ["text"]
            assert schema["properties"]["text"]["type"] == "string"
            assert schema["properties"]["text"]["minLength"] == 1

            # Unicode, quotes, and newlines must survive JSON-RPC serialization.
            text = 'Veridex "smoke"\nπ'
            for _ in range(2):
                result = await session.call_tool("protocol_echo", {"text": text})
                assert result.isError is False
                assert len(result.content) == 1
                assert isinstance(result.content[0], TextContent)
                assert result.content[0].text == f"echo: {text}"
            assert [tool.name for tool in (await session.list_tools()).tools] == ["protocol_echo"]

    stderr = diagnostics.read_text(encoding="utf-8")
    assert "Starting MCP server" in stderr
    assert stderr.count("Veridex protocol smoke: echo invoked") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{}, {"text": 123}, {"text": ""}])
async def test_stdio_invalid_arguments_return_tool_error(tmp_path, arguments):
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as errlog:
        async with evidence_session(errlog) as session:
            result = await session.call_tool("protocol_echo", arguments)
            assert result.isError is True
            assert result.content
            assert all(isinstance(content, TextContent) for content in result.content)
            assert "text" in " ".join(content.text for content in result.content)
            # A validation error must not terminate or desynchronize the session.
            recovered = await session.call_tool("protocol_echo", {"text": "after error"})
            assert recovered.isError is False
            assert recovered.content[0].text == "echo: after error"


@pytest.mark.asyncio
async def test_default_stdio_server_has_no_development_tools(tmp_path):
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as errlog:
        async with evidence_session(errlog, smoke=False) as session:
            assert (await session.list_tools()).tools == []
