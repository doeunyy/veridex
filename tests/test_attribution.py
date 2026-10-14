import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.prepare_notices import corpus_notice
from veridex.api.app import create_app
from veridex.config import Settings
from veridex.deployment.runtime import SPEC
from veridex.rag.artifacts import ArtifactError, FileRecord


@pytest.fixture
def metadata():
    papers = []
    files = {}
    for identifier in SPEC.document_ids:
        papers.append(
            {
                "id": identifier,
                "filename": identifier + ".pdf",
                "title": "Title " + identifier,
                "authors": ["Author A", "Author B"],
                "source_url": "https://example.test/" + identifier,
                "identified_local_version": "publisher version",
                "sha256": "a" * 64,
                "license_id": "CC-BY-NC-4.0" if identifier == "netmhcpan_2020" else "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "copyright_notice": "Copyright authors",
                "modifications": ["extracted and chunked"],
                "third_party_review": "External supplements excluded",
            }
        )
        files["papers/" + identifier + ".pdf"] = FileRecord(size=1, sha256="a" * 64)
    return SimpleNamespace(
        files=files,
        embedding_model_provenance=json.dumps(
            {"attribution": {"documents": papers}, "private": "PRIVATE-SENTINEL"}
        ),
    )


def test_notice_matches_source_and_excludes_internal_provenance(metadata):
    notice = corpus_notice(metadata)
    assert {d.id for d in notice.documents} == set(SPEC.document_ids)
    assert all(d.authors == ["Author A", "Author B"] for d in notice.documents)
    assert "PRIVATE-SENTINEL" not in notice.model_dump_json()
    assert any("noncommercial" in s for s in notice.limitations)


@pytest.mark.parametrize("change", ["hash", "id", "authors"])
def test_invalid_notice_rejected(metadata, change):
    data = json.loads(metadata.embedding_model_provenance)
    paper = data["attribution"]["documents"][0]
    if change == "hash":
        paper["sha256"] = "b" * 64
    elif change == "id":
        paper["id"] = "rag_2020"
    else:
        paper["authors"] = []
    metadata.embedding_model_provenance = json.dumps(data)
    with pytest.raises((ArtifactError, ValueError)):
        corpus_notice(metadata)


@pytest.mark.asyncio
async def test_readonly_notice_and_chat_link_do_not_change_contract(metadata, tmp_path):
    notice = corpus_notice(metadata)
    path = tmp_path / "notice.json"
    path.write_text(notice.model_dump_json())
    calls = []

    class Agent:
        async def achat(self, query, session_id):
            calls.append((query, session_id))
            return "answer"

    app = create_app(
        agent_service=Agent(), config=Settings(_env_file=None, corpus_attribution_path=path)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        app.state.shutting_down = True
        assert (await client.get("/attribution")).json() == notice.model_dump()
        assert calls == []
        assert (await client.post("/attribution", json={})).status_code == 405
        app.state.shutting_down = False
        response = await client.post("/chat", json={"query": "hello", "session_id": "one"})
        assert response.json() == {"response": "answer"}
        assert response.headers["link"] == '</attribution>; rel="describedby"'
        assert calls == [("hello", "one")]


@pytest.mark.asyncio
async def test_unconfigured_notice_is_safe():
    app = create_app(config=Settings(_env_file=None, corpus_attribution_path=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/attribution")
        assert response.status_code == 503
        assert response.json() == {"detail": "Corpus attribution is unavailable."}
