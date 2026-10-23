"""Planned chunks on disk, and the budget-guarded Chroma build that embeds exactly them."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from veridex.rag.v3 import COLLECTION, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

CHUNKS_FILE = "chunks.jsonl"
PLAN_FILE = "plan.json"
BUILD_FILE = "build.json"


def write_plan(chunks: list[Document], plan: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / CHUNKS_FILE).open("w", encoding="utf-8") as stream:
        for chunk in chunks:
            row = {"text": chunk.page_content, "metadata": chunk.metadata}
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    plan = {**plan, "chunks_sha256": _sha256(out_dir / CHUNKS_FILE)}
    (out_dir / PLAN_FILE).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")


def read_chunks(plan_dir: Path) -> tuple[list[Document], dict]:
    plan = json.loads((plan_dir / PLAN_FILE).read_text())
    if _sha256(plan_dir / CHUNKS_FILE) != plan["chunks_sha256"]:
        raise ValueError("chunks.jsonl changed after planning; plan again.")
    chunks = []
    with (plan_dir / CHUNKS_FILE).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            chunks.append(Document(page_content=row["text"], metadata=row["metadata"]))
    if len(chunks) != plan["chunks"]:
        raise ValueError("Chunk count differs from the plan.")
    return chunks, plan


def build_index(
    plan_dir: Path,
    index_dir: Path,
    embeddings: Embeddings,
    *,
    max_usd: float,
    batch_size: int | None = None,
) -> dict:
    """Embed every planned chunk into a new Chroma directory, or leave nothing behind.

    The estimate is checked against the caller's explicit budget before the first
    request, and an existing index is never modified.
    """
    chunks, plan = read_chunks(plan_dir)
    if plan["estimated_usd"] > max_usd:
        raise ValueError(f"Estimated ${plan['estimated_usd']:.4f} exceeds budget ${max_usd:.4f}.")
    if index_dir.exists():
        raise FileExistsError(f"{index_dir} exists; choose a new directory.")
    batch_size = batch_size or plan["batch_size"]
    staging = index_dir.with_name(index_dir.name + ".building")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        store = Chroma(
            collection_name=COLLECTION,
            embedding_function=embeddings,
            persist_directory=str(staging),
            collection_metadata={"hnsw:space": "cosine"},
        )
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            store.add_documents(batch, ids=[c.metadata["chunk_id"] for c in batch])
        stored = store._collection.count()
        if stored != len(chunks):
            raise RuntimeError(f"Indexed {stored} of {len(chunks)} chunks.")
        sample = store._collection.get(limit=1, include=["embeddings"])["embeddings"][0]
        if len(sample) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(f"Unexpected embedding dimension {len(sample)}.")
        del store
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    staging.rename(index_dir)
    build = {
        "built_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "collection": COLLECTION,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "distance": "cosine",
        "chunks": len(chunks),
        "documents": plan["documents"],
        "tokens": plan["tokens"],
        "estimated_usd": plan["estimated_usd"],
        "plan_sha256": _sha256(plan_dir / PLAN_FILE),
    }
    (index_dir / BUILD_FILE).write_text(json.dumps(build, indent=2, sort_keys=True) + "\n")
    return build


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
