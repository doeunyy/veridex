import asyncio
import sys
import threading
from unittest.mock import Mock

import pytest
from fastmcp import Client
from langchain_core.documents import Document
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_mcp_protocol import ROOT

from veridex.mcp.servers import evidence

DOCUMENT = Document(
    page_content='Evidence "passage"\nπ',
    metadata={
        "document_id": "paper",
        "chunk_id": "paper_p2_c1",
        "title": "Paper π",
        "page": 2,
        "source_url": "https://example.com/paper.pdf",
    },
)
PASSAGE = {**DOCUMENT.metadata, "content": DOCUMENT.page_content, "distance": 0.42}
INVALID = [
    {},
    {"query": ""},
    {"query": " \n"},
    {"query": 123},
    *[{"query": "q", "top_k": value} for value in (0, 11, -1, 1.5, "5", True)],
    {"query": "q", "document_id": 123},
]


@pytest.mark.asyncio
async def test_mocked_retrieval_metadata_defaults_and_filter(monkeypatch):
    retrieve = Mock(return_value=[(DOCUMENT, 0.42)])
    monkeypatch.setattr(evidence, "search_documents", retrieve)
    async with Client(evidence.create_server()) as client:
        result = await client.call_tool("search_evidence", {"query": "q"})
        assert result.structured_content == {"query": "q", "passages": [PASSAGE]}
        retrieve.assert_called_once_with(query="q", top_k=5, document_id=None)
        await client.call_tool(
            "search_evidence", {"query": "q", "top_k": 10, "document_id": "paper"}
        )
        retrieve.assert_called_with(query="q", top_k=10, document_id="paper")


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", INVALID)
async def test_invalid_arguments_do_not_retrieve(monkeypatch, arguments):
    retrieve = Mock()
    monkeypatch.setattr(evidence, "search_documents", retrieve)
    async with Client(evidence.create_server()) as client:
        assert (await client.call_tool("search_evidence", arguments, raise_on_error=False)).is_error
    retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_empty_unknown_and_missing_distance(monkeypatch):
    retrieve = Mock(side_effect=[[], [], [(DOCUMENT, None)]])
    monkeypatch.setattr(evidence, "search_documents", retrieve)
    async with Client(evidence.create_server()) as client:
        for arguments in ({"query": "empty"}, {"query": "q", "document_id": "unknown"}):
            result = await client.call_tool("search_evidence", arguments)
            assert result.structured_content["passages"] == []
        result = await client.call_tool("search_evidence", {"query": "q"})
        assert result.structured_content["passages"][0]["distance"] is None


@pytest.mark.asyncio
async def test_concurrent_retrieval_runs_off_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    barrier = threading.Barrier(3)

    def retrieve(**kwargs):
        assert threading.get_ident() != loop_thread
        barrier.wait(timeout=5)
        return [(DOCUMENT, 0.42)]

    monkeypatch.setattr(evidence, "search_documents", retrieve)
    async with Client(evidence.create_server()) as client:
        results = await asyncio.gather(
            *[client.call_tool("search_evidence", {"query": str(i)}) for i in range(3)]
        )
        assert all(result.structured_content["passages"] == [PASSAGE] for result in results)


@pytest.mark.asyncio
async def test_retrieval_failure_is_tool_error_and_session_recovers(monkeypatch):
    monkeypatch.setattr(
        evidence,
        "search_documents",
        Mock(
            side_effect=[
                RuntimeError("Index was deleted or replaced; restart before accessing it again."),
                [],
            ]
        ),
    )
    async with Client(evidence.create_server()) as client:
        failed = await client.call_tool("search_evidence", {"query": "q"}, raise_on_error=False)
        assert failed.is_error
        assert "restart" in failed.content[0].text
        assert not (await client.call_tool("search_evidence", {"query": "q"})).is_error


@pytest.mark.asyncio
async def test_stdio_production_schema_and_mocked_calls(tmp_path):
    # Patch only the test subprocess; production has no mock retrieval switch.
    launcher = tmp_path / "evidence_fixture.py"
    launcher.write_text(
        "from langchain_core.documents import Document\n"
        "from veridex.mcp.servers import evidence\n"
        f"document = Document(page_content={DOCUMENT.page_content!r}, "
        f"metadata={DOCUMENT.metadata!r})\n"
        "def retrieve(query, top_k=5, document_id=None):\n"
        "    if query == 'empty' or document_id == 'unknown': return []\n"
        "    assert top_k == 3 and document_id == 'paper'\n"
        "    return [(document, 0.42)]\n"
        "evidence.search_documents = retrieve\n"
        "evidence.create_server().run(transport='stdio')\n"
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(launcher)],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    with (tmp_path / "stderr.log").open("w") as errlog:
        async with (
            asyncio.timeout(30),
            stdio_client(parameters, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert [tool.name for tool in tools] == ["search_evidence"]
            schema = tools[0].inputSchema
            assert schema["required"] == ["query"]
            assert schema["properties"]["query"]["minLength"] == 1
            assert schema["properties"]["top_k"] == {
                "default": 5,
                "minimum": 1,
                "maximum": 10,
                "type": "integer",
            }
            assert tools[0].outputSchema["properties"]["passages"]["type"] == "array"
            arguments = {"query": "q", "top_k": 3, "document_id": "paper"}
            for _ in range(2):
                result = await session.call_tool("search_evidence", arguments)
                assert not result.isError
                assert result.structuredContent == {"query": "q", "passages": [PASSAGE]}
            results = await asyncio.gather(
                *[session.call_tool("search_evidence", arguments) for _ in range(3)]
            )
            assert all(result.structuredContent["passages"] == [PASSAGE] for result in results)
            for args in ({"query": "empty"}, {"query": "q", "document_id": "unknown"}):
                result = await session.call_tool("search_evidence", args)
                assert not result.isError
                assert result.structuredContent["passages"] == []
            for args in INVALID:
                assert (await session.call_tool("search_evidence", args)).isError
            assert not (await session.call_tool("search_evidence", arguments)).isError


@pytest.mark.integration
@pytest.mark.asyncio
async def test_existing_index_evidence():
    from veridex.config import settings

    if not (settings.chroma_persist_dir / "chroma.sqlite3").is_file():
        pytest.skip("Existing local index unavailable")
    if not settings.openai_api_key:
        pytest.skip("OpenAI embedding credentials unavailable")
    async with Client(evidence.create_server()) as client:
        result = await client.call_tool(
            "search_evidence",
            {"query": "What is MixMHC2pred used for?", "document_id": "mixmhc2pred_2023"},
        )
        passages = result.structured_content["passages"]
        assert passages
        for passage in passages:
            assert passage["document_id"] == "mixmhc2pred_2023"
            assert passage["source_url"] and passage["chunk_id"] and passage["title"]
            assert passage["page"] >= 1 and passage["content"]
            assert isinstance(passage["distance"], float)
