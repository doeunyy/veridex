"""Validate immutable bundled evidence before preparing private instance-local storage."""

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from veridex.rag.artifacts import ArtifactError, ArtifactSpec, _check_index, digest, validate_bundle
from veridex.rag.corpus_v2 import EXPECTED_IDS
from veridex.rag.rebuild_v2 import FILTER_TERMS, canonical, native_check

BUNDLE_SHA256 = "7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb"
SPEC = ArtifactSpec(
    embedding_model="text-embedding-3-small",
    embedding_dimension=1536,
    chunk_count=586,
    document_ids=sorted(EXPECTED_IDS),
)
BUNDLE = Path("/opt/veridex/rag")
LOCK = Path("/app/uv.lock")


def validate(root: Path, *, checksum: str, lock: Path):
    if checksum != BUNDLE_SHA256:
        raise ArtifactError("Bundle digest does not match the approved local/internal version.")
    return validate_bundle(root, expected=SPEC, metadata_sha256=checksum, lock_file=lock)


def writable_copy(source: Path, parent: Path) -> Path:
    """Only the fresh private copy receives writable permissions; no source writes."""
    root = Path(tempfile.mkdtemp(prefix="veridex-instance-", dir=parent))
    target = root / "chroma"
    shutil.copytree(source, target)
    for path in target.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    target.chmod(0o700)
    return target


def prepare(
    *,
    root: Path = BUNDLE,
    checksum: str = BUNDLE_SHA256,
    lock: Path = LOCK,
    temporary: Path = Path("/tmp"),
) -> Path:
    validate(root, checksum=checksum, lock=lock)
    index = writable_copy(root / "chroma", temporary)
    _check_index(index, SPEC)
    return index


def audit(*, root: Path = BUNDLE, checksum: str = BUNDLE_SHA256, lock: Path = LOCK) -> dict:
    """Offline full-vector and text-filter checks; Chroma sees only a writable copy."""
    bundle_metadata = validate(root, checksum=checksum, lock=lock)
    import json

    provenance = json.loads(bundle_metadata.embedding_model_provenance)
    with closing(
        sqlite3.connect(
            (root / "chroma/chroma.sqlite3").resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as db:
        metadata = {}
        for row, key, string, integer, real, boolean in db.execute(
            "SELECT id,key,string_value,int_value,float_value,bool_value FROM embedding_metadata"
        ):
            metadata.setdefault(row, {})[key] = (
                bool(boolean)
                if boolean is not None
                else next(v for v in (string, integer, real) if v is not None)
            )
        vectors = dict(db.execute("SELECT id,vector FROM embeddings_queue"))
        data = []
        for row, identifier in db.execute(
            "SELECT id,embedding_id FROM embeddings ORDER BY embedding_id"
        ):
            stored = metadata[row]
            data.append(
                {
                    "id": identifier,
                    "metadata": {k: v for k, v in stored.items() if k != "chroma:document"},
                    "document": stored["chroma:document"],
                    "vector_hex": vectors[identifier].hex(),
                }
            )
    expected_hashes = provenance["vector_hashes"]
    if set(expected_hashes) != {r["id"] for r in data} or any(
        digest(bytes.fromhex(r["vector_hex"])) != expected_hashes[r["id"]] for r in data
    ):
        raise ArtifactError("V2 vectors differ from recorded embedding provenance.")
    run = provenance["embedding_run"]
    if run["status"] != "complete" or any(
        r["model"] != SPEC.embedding_model or r["outcome"] != "success" for r in run["requests"]
    ):
        raise ArtifactError("V2 embedding model provenance is incomplete.")
    with tempfile.TemporaryDirectory(prefix="veridex-audit-") as scratch:
        temporary = Path(scratch)
        index = writable_copy(root / "chroma", temporary)
        payload = temporary / "records.json"
        payload.write_bytes(canonical(data))
        result = native_check(index, payload, build=False)
        _check_index(index, SPEC)
        with closing(sqlite3.connect(index / "chroma.sqlite3")) as db:
            db.execute(
                "INSERT INTO embedding_fulltext_search(embedding_fulltext_search,rank) VALUES('integrity-check',1)"
            )
            db.rollback()
    return {
        **result,
        "paper_ids": sorted({r["metadata"]["document_id"] for r in data}),
        "dimension": SPEC.embedding_dimension,
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_fts5_integrity": "ok",
        "text_filter_terms": FILTER_TERMS,
        "embedding_model_identity": SPEC.embedding_model,
        "remote_publication": "BLOCKED",
    }


def bootstrap():
    index = prepare(checksum=os.environ.get("RAG_BUNDLE_SHA256", BUNDLE_SHA256))
    os.environ["CHROMA_PERSIST_DIR"] = str(index)
    os.environ["CHROMA_COLLECTION"] = SPEC.collection
    os.environ["OPENAI_EMBEDDING_MODEL"] = SPEC.embedding_model
    os.environ["DOCUMENTS_DIR"] = str(BUNDLE / "papers")
    os.environ["WORKSPACE_MANIFEST_PATH"] = str(BUNDLE / "manifest.json")
    # exec retains PID 1 signal delivery and the runner's 0.5 + 8 second drain policy.
    import sys

    os.execv(sys.executable, [sys.executable, "/app/scripts/serve_api.py"])
