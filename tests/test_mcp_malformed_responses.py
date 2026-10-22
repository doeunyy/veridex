"""Real STDIO malformed-response regressions; no provider APIs or corpus files."""

import asyncio
import io
import json
import logging
import logging.config
import os
import sys

import pytest
from langchain_core.tools import ToolException

from veridex.framework_logging import SanitizedFrameworkErrors, uvicorn_log_config
from veridex.mcp.client import MCPClientError, connect_servers

SENTINEL = "PRIVATE_MALFORMED_RESPONSE_SENTINEL"


@pytest.fixture(autouse=True)
def production_logging():
    names = ["uvicorn", "uvicorn.error", "uvicorn.access", "mcp.client.stdio"]
    saved = {
        name: (log.handlers[:], log.filters[:], log.level, log.propagate, log.disabled)
        for name in names
        for log in [logging.getLogger(name)]
    }
    logging.config.dictConfig(uvicorn_log_config())
    yield
    for name, (handlers, filters, level, propagate, disabled) in saved.items():
        log = logging.getLogger(name)
        log.handlers[:] = handlers
        log.filters[:] = filters
        log.setLevel(level)
        log.propagate = propagate
        log.disabled = disabled


def test_sdk_origin_sanitizes_direct_and_propagated_handlers(caplog):
    logger = logging.getLogger("mcp.client.stdio")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SanitizedFrameworkErrors())  # A second boundary must preserve the event.
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        try:
            raise ValueError(SENTINEL)
        except ValueError:
            logger.exception("Failed to parse JSONRPC message from server", stack_info=True)
        logger.warning("Ordinary lifecycle warning")
    finally:
        logger.removeHandler(handler)
    for output in [stream.getvalue(), caplog.text]:
        assert SENTINEL not in output
        assert "Traceback" not in output
        assert "Stack (most recent call last)" not in output
        assert "Ordinary lifecycle warning" in output
    record = caplog.records[0]
    assert record.name == "mcp.client.stdio" and record.levelname == "ERROR"
    assert json.loads(record.getMessage()) == {
        "classification": "mcp_stdio_parse",
        "event": "framework_error",
        "exception_class": "ValueError",
    }


SERVER = r"""
import json, os, sys
from pathlib import Path
mode, role, pidfile = sys.argv[1:]
Path(pidfile).write_text(str(os.getpid()))
names = {"tavily": ["tavily_search"], "workspace": ["list_documents", "read_document"], "evidence": ["search_evidence"]}[role]
failed = False
for line in sys.stdin:
    req = json.loads(line)
    if "id" not in req:
        continue
    method = req["method"]
    if method == "initialize":
        result = {"protocolVersion": req["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": role, "version": "test"}}
    elif method == "tools/list":
        result = {"tools": [{"name": name, "description": "Offline test tool", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "additionalProperties": False}} for name in names]}
    elif method == "tools/call":
        if role == "tavily" and not failed:
            failed = True
            if mode == "invalid_json":
                print('{"PRIVATE_MALFORMED_RESPONSE_SENTINEL":', flush=True)
                continue
            if mode == "invalid_envelope":
                print(json.dumps({"jsonrpc": "PRIVATE_MALFORMED_RESPONSE_SENTINEL", "id": req["id"], "result": {}}), flush=True)
                continue
            if mode == "invalid_content":
                result = {"content": [{"type": "PRIVATE_MALFORMED_RESPONSE_SENTINEL", "text": "PRIVATE_MALFORMED_RESPONSE_SENTINEL"}]}
            else:
                result = {"content": "PRIVATE_MALFORMED_RESPONSE_SENTINEL", "isError": False}
        else:
            result = {"content": [{"type": "text", "text": "valid offline result"}], "isError": False}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}), flush=True)
"""


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["invalid_json", "invalid_envelope", "invalid_content", "invalid_field"]
)
async def test_malformed_wire_error_recovery_cleanup_and_log_safety(tmp_path, caplog, mode):
    caplog.set_level("INFO")
    server = tmp_path / "wire_server.py"
    server.write_text(SERVER)
    connections = {}
    for role in ["tavily", "workspace", "evidence"]:
        connections[role] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(server), mode, role, str(tmp_path / (role + ".pid"))],
        }
    async with asyncio.timeout(15):
        async with connect_servers(connections, timeout=5) as registry:
            registry._timeout = 0.3
            with pytest.raises((MCPClientError, ToolException)) as failure:
                await asyncio.wait_for(registry.invoke("tavily_search", {"query": "offline"}), 3)
            assert SENTINEL not in str(failure.value)
            recovered = await registry.invoke("tavily_search", {"query": "offline"})
            assert recovered.status == "success"
            healthy = await registry.invoke("list_documents", {})
            assert healthy.status == "success"
    assert all(not alive(int((tmp_path / (role + ".pid")).read_text())) for role in connections)
    # The production logger boundary must not permit SDK validation text or tracebacks.
    assert SENTINEL not in caplog.text
    assert "Traceback" not in caplog.text
    assert "validation error" not in caplog.text
    assert "input_value" not in caplog.text
    sdk_errors = [r for r in caplog.records if r.name == "mcp.client.stdio"]
    if mode in {"invalid_json", "invalid_envelope"}:
        assert len(sdk_errors) == 1
        assert json.loads(sdk_errors[0].getMessage()) == {
            "classification": "mcp_stdio_parse",
            "event": "framework_error",
            "exception_class": "Exception",  # ValidationError is intentionally not allowlisted.
        }
    else:
        assert not sdk_errors  # Valid wire envelope; result validation fails in ClientSession.
