"""Validate immutable bundled evidence before preparing private instance-local storage."""

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from veridex.rag.artifacts import ArtifactError, _check_index, digest, validate_bundle
from veridex.rag.recovery import CLEAN_SHA256, SPEC, TARGET, canonical, native

BUNDLE_SHA256 = "6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8"
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
    validate(root, checksum=checksum, lock=lock)
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
    target = next(r for r in data if r["id"] == TARGET)
    if len(target["document"]) != 927 or digest(target["document"].encode()) != CLEAN_SHA256:
        raise ArtifactError("Approved recovered chunk does not match its reviewed text hash.")
    with tempfile.TemporaryDirectory(prefix="veridex-audit-") as scratch:
        temporary = Path(scratch)
        index = writable_copy(root / "chroma", temporary)
        payload = temporary / "records.json"
        payload.write_bytes(canonical(data))
        result = native(index, payload, build=False)
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
        "target_chunk": TARGET,
        "embedding_model_identity": "UNVERIFIED",
        "remote_publication": "BLOCKED",
    }


def bootstrap():
    index = prepare(checksum=os.environ.get("RAG_BUNDLE_SHA256", BUNDLE_SHA256))
    os.environ["CHROMA_PERSIST_DIR"] = str(index)
    os.environ["CHROMA_COLLECTION"] = SPEC.collection
    os.environ["DOCUMENTS_DIR"] = str(BUNDLE / "papers")
    os.environ["WORKSPACE_MANIFEST_PATH"] = str(BUNDLE / "manifest.json")
    # exec retains PID 1 signal delivery and the runner's 0.5 + 8 second drain policy.
    import sys

    os.execv(sys.executable, [sys.executable, "/app/scripts/serve_api.py"])
