from types import SimpleNamespace

import httpx
import pytest

from veridex.api.app import create_app
from veridex.api.attribution import load_attribution
from veridex.config import Settings
from veridex.rag.v3.manifest import DEFAULT_MANIFEST, load_manifest


def test_notice_lists_every_corpus_paper_with_license_and_authors():
    notice = load_attribution(DEFAULT_MANIFEST)
    manifest = load_manifest(DEFAULT_MANIFEST)
    assert [p.doc_id for p in notice.papers] == [p.doc_id for p in manifest.papers]
    assert {p.license for p in notice.papers} <= {"CC-BY-4.0", "CC0-1.0"}
    assert all(
        p.authors and p.source_url.startswith("https://arxiv.org/abs/") for p in notice.papers
    )
    assert load_attribution(None) is None
    assert load_attribution(DEFAULT_MANIFEST.with_name("missing.json")) is None


@pytest.mark.asyncio
async def test_attribution_route_and_chat_link():
    class Service:
        async def achat(self, query, session_id):
            return "ok"

    application = create_app(
        agent_service=Service(),
        config=Settings(_env_file=None, corpus_manifest_path=DEFAULT_MANIFEST),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://t"
    ) as client:
        notice = (await client.get("/attribution")).json()
        chat = await client.post("/chat", json={"query": "q", "session_id": "s"})
    assert notice["corpus"] == "veridex-corpus-v3" and len(notice["papers"]) == 42
    assert chat.json() == {"response": "ok"}
    assert chat.headers["Link"] == '</attribution>; rel="describedby"'


@pytest.mark.asyncio
async def test_missing_manifest_is_safe(tmp_path):
    application = create_app(
        agent_service=SimpleNamespace(),
        config=Settings(_env_file=None, corpus_manifest_path=tmp_path / "none.json"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://t"
    ) as client:
        response = await client.get("/attribution")
    assert response.status_code == 503


def test_root_license_notice_is_current():
    from pathlib import Path

    from veridex.api.attribution import render_notice

    notice = Path(__file__).resolve().parents[1] / "CORPUS_LICENSE_NOTICE.md"
    assert notice.read_text() == render_notice(DEFAULT_MANIFEST)
