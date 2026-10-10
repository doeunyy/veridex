import asyncio
import json
import os
import sys

import pytest
from langchain_core.tools import ToolException
from test_mcp_protocol import ROOT
from test_mcp_workspace import catalog_entry, make_pdf

from veridex.config import Settings
from veridex.mcp.client import MCPClientError, connect_servers, default_connections

EXPECTED = {"search_evidence", "search_web", "list_documents", "read_document"}
SOURCE_URL = "https://example.com/paper%2Fone?x=1&y=2#section"


@pytest.fixture
def connections(tmp_path):
    corpus = tmp_path / "papers"
    corpus.mkdir()
    make_pdf(corpus / "paper.pdf", ["Actual local research evidence."])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [catalog_entry("paper.pdf")]}))
    config = Settings(
        _env_file=None,
        documents_dir=corpus,
        workspace_manifest_path=manifest,
        openai_api_key=None,
        tavily_api_key="fake-tavily-test-key",
    )
    connections = default_connections(project_root=ROOT, config=config)
    launcher = tmp_path / "bootstrap.py"
    launcher.write_text(
        "import os, sys, runpy\n"
        "from pathlib import Path\n"
        "role = sys.argv[1]\n"
        "with Path(os.environ['TEST_PID_LOG']).open('a') as log:\n"
        "    log.write(f'{role} {os.getpid()}\\n')\n"
        "if role == 'evidence':\n"
        "    from langchain_core.documents import Document\n"
        "    from veridex.rag import retrieval\n"
        "    def retrieve(query, top_k=5, document_id=None):\n"
        "        if not query.strip(): raise ValueError('Query cannot be empty.')\n"
        "        if query == 'empty': return []\n"
        "        if query == 'error': raise ValueError('Controlled retrieval failure')\n"
        "        return [(Document(page_content='Retrieved evidence π', metadata={\n"
        "            'document_id': 'paper', 'chunk_id': 'paper_p1_c1', 'title': 'Paper',\n"
        f"            'page': 1, 'source_url': {SOURCE_URL!r}}}), 0.37)]\n"
        "    retrieval.search_documents = retrieve\n"
        "if role == 'web_search':\n"
        "    import tavily\n"
        "    class FakeTavily:\n"
        "        def __init__(self, api_key): assert api_key == 'fake-tavily-test-key'\n"
        "        async def __aenter__(self): return self\n"
        "        async def __aexit__(self, *args): pass\n"
        "        async def search(self, query, **kwargs):\n"
        "            if query == 'error': raise RuntimeError('Provider failed')\n"
        "            if query == 'empty': return {'results': []}\n"
        f"            return {{'results': [{{'title': 'Web paper', 'url': {SOURCE_URL!r},\n"
        "                'content': 'Web evidence snippet', 'published_date': '2026-10-01'}]}\n"
        "    tavily.AsyncTavilyClient = FakeTavily\n"
        "sys.argv = ['server']\n"
        "runpy.run_module(f'veridex.mcp.servers.{role}', run_name='__main__')\n"
    )
    pid_log = tmp_path / "pids.txt"
    for name, connection in connections.items():
        connection["args"] = [str(launcher), name]
        connection["env"]["TEST_PID_LOG"] = str(pid_log)
    return connections, pid_log, config


def process_ids(log):
    if not log.exists():
        return []
    return [int(line.split()[1]) for line in log.read_text().splitlines()]


def is_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.asyncio
async def test_real_multi_server_discovery_invocation_refresh_and_cleanup(connections):
    configs, pid_log, _ = connections
    async with asyncio.timeout(45):
        async with connect_servers(configs, timeout=15) as registry:
            assert set(registry.entries) == EXPECTED
            assert set(registry.servers) == {"evidence", "web_search", "workspace"}
            assert [info.serverInfo.name for info in registry.servers.values()] == [
                "Veridex Evidence",
                "Veridex Web Search",
                "Veridex Workspace",
            ]
            assert all(tool.response_format == "content_and_artifact" for tool in registry.tools)
            initial_pids = process_ids(pid_log)
            assert len(initial_pids) == 3 and all(is_alive(pid) for pid in initial_pids)
            evidence = await registry.invoke("search_evidence", {"query": "What is RAG?"})
            passage = evidence.artifact["structured_content"]["passages"][0]
            assert passage == {
                "document_id": "paper",
                "chunk_id": "paper_p1_c1",
                "title": "Paper",
                "page": 1,
                "source_url": SOURCE_URL,
                "distance": 0.37,
                "content": "Retrieved evidence π",
            }
            web = await registry.invoke("search_web", {"query": "research"})
            assert web.artifact["structured_content"]["results"] == [
                {
                    "title": "Web paper",
                    "url": SOURCE_URL,
                    "content": "Web evidence snippet",
                    "published_date": "2026-10-01",
                }
            ]
            listed = await registry.invoke("list_documents", {})
            assert (
                listed.artifact["structured_content"]["documents"][0]["document_id"] == "paper.pdf"
            )
            read = await registry.invoke("read_document", {"document_id": "paper.pdf"})
            assert read.artifact["structured_content"]["pages"] == [
                {
                    "page": 1,
                    "text": "Actual local research evidence.",
                }
            ]
            for _ in range(2):
                assert {tool.name for tool in await registry.refresh()} == EXPECTED
                assert (
                    await registry.invoke("search_evidence", {"query": "again"})
                ).status == "success"
            assert process_ids(pid_log) == initial_pids
            # All adapters are usable as LangChain tools, including concurrent invocations.
            calls = await asyncio.gather(
                *[registry.invoke("read_document", {"document_id": "paper.pdf"}) for _ in range(3)]
            )
            assert all(call.status == "success" for call in calls)
            for name, args in [
                ("search_evidence", {"query": "error"}),
                ("search_web", {"query": "error"}),
                ("read_document", {"document_id": "../outside.pdf"}),
            ]:
                with pytest.raises(ToolException):
                    await registry.invoke(name, args)
            for name in ("search_evidence", "search_web"):
                result = await registry.invoke(name, {"query": "empty"})
                payload = result.artifact["structured_content"]
                assert payload.get("passages", payload.get("results")) == []
            report = registry.inspection()
            tools = {tool["name"]: tool for server in report["servers"] for tool in server["tools"]}
            assert set(tools) == EXPECTED
            assert tools["search_evidence"]["input_schema"]["properties"]["top_k"]["maximum"] == 10
            assert tools["search_web"]["input_schema"]["properties"]["max_results"]["default"] == 5
            assert tools["list_documents"]["input_schema"]["properties"] == {}
            assert tools["read_document"]["input_schema"]["required"] == ["document_id"]
            assert "fake-tavily-test-key" not in json.dumps(report)
    assert all(not is_alive(pid) for pid in initial_pids)
    with pytest.raises(MCPClientError, match="closed"):
        await registry.invoke("list_documents", {})


@pytest.mark.asyncio
async def test_missing_credentials_and_invalid_calls_through_actual_servers(connections):
    _, _, config = connections
    config.tavily_api_key = None
    configs = default_connections(project_root=ROOT, config=config)
    async with connect_servers(configs, timeout=15) as registry:
        assert set(registry.entries) == EXPECTED
        with pytest.raises(ToolException, match="TAVILY_API_KEY is not configured"):
            await registry.invoke("search_web", {"query": "research"})
        with pytest.raises(ToolException, match="empty"):
            await registry.invoke("search_evidence", {"query": " "})
        with pytest.raises(ToolException, match="OPENAI_API_KEY is not configured"):
            await registry.invoke("search_evidence", {"query": "research"})
        with pytest.raises(ToolException):
            await registry.invoke("search_web", {"query": "q", "max_results": True})
        assert (await registry.invoke("list_documents", {})).status == "success"


@pytest.mark.asyncio
async def test_unavailable_server_cleans_up_already_started_processes(connections):
    configs, pid_log, _ = connections
    configs["workspace"]["command"] = "/nonexistent/veridex-mcp-test-command"
    with pytest.raises(MCPClientError, match="workspace"):
        async with connect_servers(configs, timeout=15):
            pytest.fail("Unavailable server must not yield a partial registry")
    pids = process_ids(pid_log)
    assert len(pids) == 2
    assert all(not is_alive(pid) for pid in pids)


@pytest.mark.asyncio
async def test_inspection_cli_with_config_and_error_redaction(connections, tmp_path):
    configs, pid_log, _ = connections
    path = tmp_path / "connections.json"
    path.write_text(json.dumps(configs))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "scripts/inspect_mcp.py"),
        "--config",
        str(path),
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(45):
        stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    report = json.loads(stdout)
    assert {tool["name"] for server in report["servers"] for tool in server["tools"]} == EXPECTED
    assert b"fake-tavily-test-key" not in stdout + stderr
    assert all(not is_alive(pid) for pid in process_ids(pid_log))
    path.write_text(json.dumps({"bad": {"transport": "http", "url": "SECRET invalid URL"}}))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "scripts/inspect_mcp.py"),
        "--config",
        str(path),
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(10):
        stdout, stderr = await process.communicate()
    assert process.returncode == 1
    assert not stdout
    assert b"MCP inspection failed" in stderr
    assert b"SECRET" not in stderr


@pytest.mark.asyncio
async def test_owner_cancellation_shuts_down_actual_servers(connections):
    configs, pid_log, _ = connections
    entered = asyncio.Event()

    async def owner():
        async with connect_servers(configs, timeout=15):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    try:
        async with asyncio.timeout(30):
            await entered.wait()
        pids = process_ids(pid_log)
        assert len(pids) == 3 and all(is_alive(pid) for pid in pids)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all(not is_alive(pid) for pid in pids)
