import asyncio
import json
import os
import sqlite3
import sys

import pytest
from langchain_core.tools import ToolException
from test_mcp_protocol import ROOT
from test_mcp_workspace import make_pdf, write_catalog

from veridex.config import Settings
from veridex.data.catalog import SCHEMA
from veridex.mcp.client import (
    MCPClientError,
    connect_servers,
    default_connections,
    tavily_connection,
)

EXPECTED = {
    "search_evidence",
    "list_documents",
    "read_document",
    "describe_catalog",
    "query_catalog_sql",
    "tavily_search",
    "tavily_extract",
}
SERVERS = ["evidence", "workspace", "catalog", "tavily"]
SOURCE_URL = "https://example.com/paper%2Fone?x=1&y=2#section"


def make_catalog(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO papers VALUES "
            "('paper_2026','2601.00001','Approved research',2026,'rag_retrieval',"
            "'Ada Lovelace',1,'cs.CL','CC-BY-4.0','https://arxiv.org/abs/2601.00001',3,2,5,900)"
        )
    connection.close()


@pytest.fixture
def connections(tmp_path):
    corpus = tmp_path / "papers"
    corpus.mkdir()
    make_pdf(corpus / "paper_2026.pdf", ["Actual local research evidence."])
    manifest = tmp_path / "papers.json"
    write_catalog(manifest, ["paper_2026.pdf"])
    catalog = tmp_path / "catalog.db"
    make_catalog(catalog)
    config = Settings(
        _env_file=None,
        documents_dir=corpus,
        corpus_manifest_path=manifest,
        catalog_path=catalog,
        openai_api_key=None,
        tavily_api_key="fake-tavily-test-key",
    )
    connections = default_connections(project_root=ROOT, config=config, include_remote=False)
    # Tavily Remote MCP stands in as a local STDIO server with the same tool names.
    connections["tavily"] = {**connections["catalog"], "env": dict(connections["catalog"]["env"])}
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
        "            'document_id': 'paper_2026', 'chunk_id': 'paper_2026:p1:c000',\n"
        f"            'title': 'Paper', 'page': 1, 'source_url': {SOURCE_URL!r}}}), 0.37)]\n"
        "    retrieval.search_documents = retrieve\n"
        "if role == 'tavily':\n"
        "    from fastmcp import FastMCP\n"
        "    from fastmcp.exceptions import ToolError\n"
        "    server = FastMCP(name='Tavily Fake')\n"
        "    @server.tool\n"
        "    def tavily_search(query: str, max_results: int = 5) -> dict:\n"
        "        if query == 'error': raise ToolError('Provider failed')\n"
        f"        return {{'results': [{{'title': 'Web', 'url': {SOURCE_URL!r},\n"
        "            'content': 'Web evidence snippet'}]}\n"
        "    @server.tool\n"
        "    def tavily_extract(urls: list[str]) -> dict:\n"
        "        return {'results': [{'url': u, 'raw_content': 'page'} for u in urls]}\n"
        "    server.run(transport='stdio')\n"
        "    sys.exit(0)\n"
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


def test_tavily_remote_connection_passes_key_as_query_parameter():
    config = Settings(_env_file=None, tavily_api_key="tvly-abc+/=")
    connection = tavily_connection(config)
    assert connection == {
        "transport": "streamable_http",
        "url": "https://mcp.tavily.com/mcp/?tavilyApiKey=tvly-abc%2B%2F%3D",
    }
    assert set(default_connections(config=config)) == set(SERVERS)
    with pytest.raises(MCPClientError, match="TAVILY_API_KEY"):
        tavily_connection(Settings(_env_file=None))


@pytest.mark.asyncio
async def test_real_multi_server_discovery_invocation_refresh_and_cleanup(connections):
    configs, pid_log, _ = connections
    async with asyncio.timeout(45):
        async with connect_servers(configs, timeout=15) as registry:
            assert set(registry.entries) == EXPECTED
            assert list(registry.servers) == SERVERS
            assert [info.serverInfo.name for info in registry.servers.values()] == [
                "Veridex Evidence",
                "Veridex Workspace",
                "Veridex Catalog",
                "Tavily Fake",
            ]
            assert all(tool.response_format == "content_and_artifact" for tool in registry.tools)
            initial_pids = process_ids(pid_log)
            assert len(initial_pids) == 4 and all(is_alive(pid) for pid in initial_pids)

            evidence = await registry.invoke("search_evidence", {"query": "What is RAG?"})
            passage = evidence.artifact["structured_content"]["passages"][0]
            assert passage["chunk_id"] == "paper_2026:p1:c000"
            assert passage["source_url"] == SOURCE_URL

            web = await registry.invoke("tavily_search", {"query": "research"})
            assert web.artifact["structured_content"]["results"][0]["url"] == SOURCE_URL

            listed = await registry.invoke("list_documents", {})
            document = listed.artifact["structured_content"]["documents"][0]
            assert (document["document_id"], document["paper_id"]) == (
                "paper_2026.pdf",
                "paper_2026",
            )
            read = await registry.invoke("read_document", {"document_id": "paper_2026.pdf"})
            assert read.artifact["structured_content"]["pages"] == [
                {"page": 1, "text": "Actual local research evidence."}
            ]

            schema = await registry.invoke("describe_catalog", {})
            assert "CREATE TABLE papers" in schema.artifact["structured_content"]["schema_sql"]
            rows = await registry.invoke(
                "query_catalog_sql", {"sql": "SELECT doc_id, year FROM papers"}
            )
            assert rows.artifact["structured_content"]["rows"] == [["paper_2026", 2026]]

            for _ in range(2):
                assert {tool.name for tool in await registry.refresh()} == EXPECTED
            assert process_ids(pid_log) == initial_pids
            calls = await asyncio.gather(
                *[registry.invoke("search_evidence", {"query": "again"}) for _ in range(3)]
            )
            assert all(call.status == "success" for call in calls)
            for name, args in [
                ("search_evidence", {"query": "error"}),
                ("tavily_search", {"query": "error"}),
                ("read_document", {"document_id": "../outside.pdf"}),
                ("query_catalog_sql", {"sql": "DELETE FROM papers"}),
            ]:
                with pytest.raises(ToolException):
                    await registry.invoke(name, args)
            report = registry.inspection()
            assert "fake-tavily-test-key" not in json.dumps(report)
    assert all(not is_alive(pid) for pid in initial_pids)
    with pytest.raises(MCPClientError, match="closed"):
        await registry.invoke("list_documents", {})


@pytest.mark.asyncio
async def test_invalid_calls_through_actual_servers(connections):
    configs, _, _ = connections
    async with connect_servers(configs, timeout=15) as registry:
        with pytest.raises(ToolException, match="empty"):
            await registry.invoke("search_evidence", {"query": " "})
        with pytest.raises(ToolException, match="one SQL statement"):
            await registry.invoke("query_catalog_sql", {"sql": "SELECT 1; SELECT 2"})
        with pytest.raises(ToolException):
            await registry.invoke("query_catalog_sql", {"sql": "SELECT 1", "max_rows": 0})
        assert (await registry.invoke("list_documents", {})).status == "success"


@pytest.mark.asyncio
async def test_unavailable_server_cleans_up_already_started_processes(connections):
    configs, pid_log, _ = connections
    configs["catalog"]["command"] = "/nonexistent/veridex-mcp-test-command"
    with pytest.raises(MCPClientError, match="catalog"):
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
        assert len(pids) == 4 and all(is_alive(pid) for pid in pids)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all(not is_alive(pid) for pid in pids)
