"""Verify the Corpus v3 bundle offline (no API calls): PDFs, Chroma index and catalog.

Run in the Docker build and locally before deploying:
    uv run python scripts/check_bundle.py
"""

import hashlib
import json
import sqlite3
import sys

import chromadb

from veridex.config import settings
from veridex.rag.v3 import COLLECTION, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from veridex.rag.v3.download import LOCK_FILE
from veridex.rag.v3.index import BUILD_FILE
from veridex.rag.v3.manifest import load_manifest


def check() -> dict:
    manifest = load_manifest(settings.corpus_manifest_path)
    papers = settings.documents_dir
    lock = json.loads((papers / LOCK_FILE).read_text())
    for paper in manifest.papers:
        data = (papers / paper.filename).read_bytes()
        if hashlib.sha256(data).hexdigest() != lock[paper.doc_id]["sha256"]:
            raise SystemExit(f"{paper.filename} does not match its recorded SHA-256.")

    build = json.loads((settings.chroma_persist_dir / BUILD_FILE).read_text())
    if (build["collection"], build["embedding_model"], build["embedding_dimensions"]) != (
        COLLECTION,
        EMBEDDING_MODEL,
        EMBEDDING_DIMENSIONS,
    ):
        raise SystemExit("Chroma build metadata does not match Corpus v3.")
    client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
    collection = client.get_collection(settings.chroma_collection)
    count = collection.count()
    if count != build["chunks"]:
        raise SystemExit(f"Index has {count} chunks; build recorded {build['chunks']}.")
    stored = {m["document_id"] for m in collection.get(include=["metadatas"])["metadatas"]}
    if stored != {p.doc_id for p in manifest.papers}:
        raise SystemExit("Index documents differ from the manifest.")

    with sqlite3.connect(f"file:{settings.catalog_path}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    if rows != len(manifest.papers):
        raise SystemExit(f"Catalog has {rows} papers; manifest has {len(manifest.papers)}.")
    return {"papers": len(manifest.papers), "chunks": count, "catalog_rows": rows}


if __name__ == "__main__":
    print(json.dumps(check()), file=sys.stderr)
