"""Selective live QA: new Workspace/memory coverage without paid retrieval or web searches."""

import json

import pytest

from veridex.agent.mcp_service import open_mcp_agent_service
from veridex.config import Settings, settings
from veridex.mcp.client import default_connections


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_workspace_routing_memory_and_isolation(tmp_path):
    if not settings.openai_api_key:
        pytest.skip("OpenAI credentials unavailable")
    if not settings.documents_dir.is_dir() or not settings.workspace_manifest_path.is_file():
        pytest.skip("Local approved research corpus unavailable")
    # Real LLM in the parent; retrieval/web credentials disabled in children to bound paid calls.
    config = Settings(
        _env_file=None,
        openai_api_key=None,
        tavily_api_key=None,
        documents_dir=settings.documents_dir,
        workspace_manifest_path=settings.workspace_manifest_path,
    )
    connections = default_connections(config=config)
    reports = {}
    async with open_mcp_agent_service(connections, recursion_limit=8, turn_timeout=180) as service:
        reports["workspace-list"] = await service.achat_with_trace(
            "What papers are available in the local research corpus? List their titles and paper IDs. "
            "Use only the local Workspace; do not use indexed retrieval or external web searches.",
            "workspace-memory",
        )
        listing = reports["workspace-list"]
        assert listing["status"] == "success"
        assert any(item["name"] == "list_documents" for item in listing["tool_results"])
        documents = [
            doc
            for item in listing["tool_results"]
            if item["name"] == "list_documents" and item["status"] == "success"
            for doc in item["structured_content"]["documents"]
        ]
        paper = next(doc for doc in documents if doc["paper_id"] == "self_rag_2023")
        reports["workspace-read"] = await service.achat_with_trace(
            "Read PDF page 1 of the Self-RAG paper from that local list. Give a short summary with "
            "its indexed paper ID and PDF page. Use only local Workspace document access.",
            "workspace-memory",
        )
        reading = reports["workspace-read"]
        assert reading["status"] == "success"
        reads = [
            item
            for item in reading["tool_results"]
            if item["name"] == "read_document" and item["status"] == "success"
        ]
        assert (
            reads
            and reads[0]["structured_content"]["document"]["document_id"] == paper["document_id"]
        )
        assert reads[0]["structured_content"]["pages"][0]["page"] == 1
        assert reads[0]["structured_content"]["document"]["source_url"] == paper["source_url"]
        reports["memory"] = await service.achat_with_trace(
            "Which paper did we just read, and which PDF page? Return its indexed paper ID and "
            "page number from our conversation. Do not call tools again.",
            "workspace-memory",
        )
        memory = reports["memory"]
        assert memory["status"] == "success" and memory["call_counts"] == {}
        assert paper["paper_id"] in memory["response"] and "1" in memory["response"]
        reports["isolation"] = await service.achat_with_trace(
            "Which paper did we read earlier in this session? If this session has no reading "
            "history, say so. Do not call tools.",
            "new-isolated-session",
        )
        isolated = reports["isolation"]
        assert isolated["status"] == "success" and isolated["call_counts"] == {}
        assert paper["paper_id"] not in isolated["response"]
        assert len(await service.aget_history("new-isolated-session")) == 2
    (tmp_path / "live-workspace-memory-report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2)
    )
    results = [item for report in reports.values() for item in report["tool_results"]]
    assert all(
        item["server_identity"] == "Veridex Workspace" and item["status"] == "success"
        for item in results
    )
    assert {item["name"] for item in results} == {"list_documents", "read_document"}
