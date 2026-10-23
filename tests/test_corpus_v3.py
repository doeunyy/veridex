import json
from pathlib import Path

import pymupdf
import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from pydantic import ValidationError

from veridex.rag.v3 import COLLECTION, EMBEDDING_DIMENSIONS
from veridex.rag.v3.download import LOCK_FILE, download_papers, sha256
from veridex.rag.v3.index import build_index, read_chunks, write_plan
from veridex.rag.v3.manifest import DEFAULT_MANIFEST, Manifest, load_manifest
from veridex.rag.v3.pipeline import (
    CHUNK_TOKENS,
    build_ingestion_chain,
    embedding_plan,
    ingest,
    strip_back_matter,
)


def paper(index: int, **overrides) -> dict:
    arxiv_id = f"2401.{index:05d}"
    row = {
        "doc_id": f"paper_{index}_2024",
        "arxiv_id": arxiv_id,
        "title": f"Paper {index}",
        "authors": ["Ada Lovelace", "Alan Turing"],
        "year": 2024,
        "topic": "rag_retrieval",
        "categories": ["cs.CL"],
        "license": "CC-BY-4.0",
        "license_url": "http://creativecommons.org/licenses/by/4.0/",
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }
    return row | overrides


def manifest(count: int = 30, **overrides) -> Manifest:
    rows = [paper(i, **overrides) for i in range(count)]
    return Manifest.model_validate(
        {"corpus": "veridex-corpus-v3", "description": "t", "papers": rows}
    )


def write_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(36, 36, 576, 806), text, fontsize=9)
    document.save(path)


class FakeEmbeddings(Embeddings):
    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [[float(len(t) % 7 + 1)] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for t in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def test_tracked_manifest_is_valid_and_redistributable():
    loaded = load_manifest(DEFAULT_MANIFEST)
    assert 30 <= len(loaded.papers) <= 50
    assert {p.license for p in loaded.papers} <= {"CC-BY-4.0", "CC0-1.0"}
    assert {p.topic for p in loaded.papers} == {
        "rag_retrieval",
        "agent_reasoning_tools",
        "multi_agent_systems",
        "evaluation",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"license": "arXiv", "license_url": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"},
        {"license": "CC-BY-4.0", "license_url": "http://creativecommons.org/licenses/by-nc/4.0/"},
        {"abs_url": "https://example.com"},
        {"year": 2023},
    ],
)
def test_manifest_rejects_unusable_rows(overrides):
    with pytest.raises(ValidationError):
        manifest(**overrides)


def test_manifest_rejects_duplicates_and_bad_sizes():
    rows = [paper(i) for i in range(30)]
    rows[1] = paper(0)
    with pytest.raises(ValidationError, match="Duplicate"):
        Manifest.model_validate({"corpus": "veridex-corpus-v3", "description": "", "papers": rows})
    with pytest.raises(ValidationError):
        manifest(count=5)


def test_download_records_hashes_and_resumes(tmp_path):
    fetched, slept = [], []

    def fetch(url):
        fetched.append(url)
        return b"%PDF-1.7 " + url.encode()

    corpus = manifest()
    lock = download_papers(corpus, tmp_path, fetch=fetch, sleep=slept.append, log=lambda _: None)
    assert len(fetched) == 30 and len(slept) == 29
    assert json.loads((tmp_path / LOCK_FILE).read_text()) == lock
    first = corpus.papers[0]
    assert lock[first.doc_id]["sha256"] == sha256((tmp_path / first.filename).read_bytes())

    download_papers(corpus, tmp_path, fetch=fetch, sleep=slept.append, log=lambda _: None)
    assert len(fetched) == 30  # nothing refetched

    (tmp_path / first.filename).write_bytes(b"%PDF-tampered")
    with pytest.raises(ValueError, match="differs"):
        download_papers(corpus, tmp_path, fetch=fetch, sleep=slept.append, log=lambda _: None)


def test_download_rejects_non_pdf(tmp_path):
    with pytest.raises(ValueError, match="did not return a PDF"):
        download_papers(manifest(), tmp_path, fetch=lambda url: b"<html>", log=lambda _: None)


def test_strip_back_matter_keeps_body_only():
    pages = [
        Document(page_content="Contents\nReferences\n", metadata={"page": 1}),
        Document(page_content="Intro", metadata={"page": 2}),
        Document(page_content="Results\nReferences\n[1] Someone", metadata={"page": 3}),
        Document(page_content="Appendix A", metadata={"page": 4}),
    ]
    kept = strip_back_matter(pages)
    assert [p.page_content for p in kept] == ["Contents\nReferences\n", "Intro", "Results"]


def test_ingestion_chain_chunks_with_citation_metadata(tmp_path):
    corpus = manifest()
    body = "Retrieval augmented generation grounds answers in evidence. " * 120
    for item in corpus.papers:
        write_pdf(tmp_path / item.filename, ["Title page", body, "References\n[1] A citation"])
    chunks = ingest(corpus, tmp_path)

    assert {c.metadata["document_id"] for c in chunks} == {p.doc_id for p in corpus.papers}
    assert all(c.metadata["page"] in (1, 2) for c in chunks)
    assert all("A citation" not in c.page_content for c in chunks)
    first = [c for c in chunks if c.metadata["document_id"] == "paper_0_2024"]
    assert [c.metadata["chunk_id"] for c in first[:2]] == [
        "paper_0_2024:p1:c000",
        "paper_0_2024:p2:c001",
    ]
    assert first[0].metadata["source_url"] == "https://arxiv.org/abs/2401.00000"

    plan = embedding_plan(chunks, batch_size=100)
    assert plan["chunks"] == len(chunks) and plan["documents"] == 30
    assert 0 < plan["largest_chunk_tokens"] <= CHUNK_TOKENS
    assert plan["estimated_usd"] == pytest.approx(plan["tokens"] * 0.02 / 1_000_000, abs=1e-6)


def test_ingest_reports_missing_pdfs(tmp_path):
    with pytest.raises(FileNotFoundError, match="Missing PDFs"):
        ingest(manifest(), tmp_path, chain=build_ingestion_chain())


def planned(tmp_path, count=5):
    chunks = [
        Document(
            page_content=f"chunk {i}",
            metadata={
                "document_id": "paper_0_2024",
                "page": 1,
                "chunk_id": f"paper_0_2024:p1:c{i:03d}",
            },
        )
        for i in range(count)
    ]
    plan = {"documents": 1, "chunks": count, "tokens": 10, "estimated_usd": 0.01, "batch_size": 2}
    write_plan(chunks, plan, tmp_path / "plan")
    return tmp_path / "plan"


def test_build_index_embeds_every_planned_chunk(tmp_path):
    embeddings = FakeEmbeddings()
    result = build_index(planned(tmp_path), tmp_path / "chroma", embeddings, max_usd=0.05)
    assert result["chunks"] == 5 and result["collection"] == COLLECTION
    assert embeddings.calls == 3
    assert json.loads((tmp_path / "chroma" / "build.json").read_text()) == result
    assert not (tmp_path / "chroma.building").exists()


def test_build_index_refuses_over_budget_or_existing(tmp_path):
    plan_dir = planned(tmp_path)
    embeddings = FakeEmbeddings()
    with pytest.raises(ValueError, match="exceeds budget"):
        build_index(plan_dir, tmp_path / "chroma", embeddings, max_usd=0.001)
    (tmp_path / "chroma").mkdir()
    with pytest.raises(FileExistsError):
        build_index(plan_dir, tmp_path / "chroma", embeddings, max_usd=1)
    assert embeddings.calls == 0


def test_build_index_cleans_up_after_failure(tmp_path):
    class Failing(FakeEmbeddings):
        def embed_documents(self, texts):
            if self.calls:
                raise RuntimeError("provider down")
            return super().embed_documents(texts)

    with pytest.raises(RuntimeError, match="provider down"):
        build_index(planned(tmp_path), tmp_path / "chroma", Failing(), max_usd=1)
    assert not (tmp_path / "chroma").exists()
    assert not (tmp_path / "chroma.building").exists()


def test_read_chunks_detects_edits(tmp_path):
    plan_dir = planned(tmp_path)
    with (plan_dir / "chunks.jsonl").open("a") as stream:
        stream.write("{}\n")
    with pytest.raises(ValueError, match="changed after planning"):
        read_chunks(plan_dir)
