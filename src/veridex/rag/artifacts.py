"""Versioned offline corpus bundles; never open the source through Chroma APIs.

V1 supports the observed Chroma 1.5.9 SQLite + little-endian HNSW layout. Export
requires an operator-controlled maintenance window: no readers/writers may start
until it finishes. lsof and before/after fingerprints detect mistakes; they are
not a distributed lock. SQLite backup alone cannot snapshot the HNSW files.
"""

import hashlib
import json
import math
import os
import platform
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
from contextlib import closing
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from uuid import UUID

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

DEPENDENCIES = ("chromadb", "langchain-chroma", "langchain-openai", "pymupdf")
INDEX_FILES = {"header.bin", "data_level0.bin", "length.bin", "link_lists.bin"}
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class ArtifactError(ValueError):
    """Invalid or unsafe snapshot; messages contain no document contents."""


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class ArtifactSpec(StrictModel):
    collection: str = "veridex_documents"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, gt=0)
    chunk_count: int = Field(default=615, gt=0)
    document_ids: list[str] = Field(
        default_factory=lambda: sorted(
            ["rag_2020", "react_2022", "self_rag_2023", "netmhcpan_2020", "mixmhc2pred_2023"]
        )
    )


class FileRecord(StrictModel):
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BundleMetadata(StrictModel):
    format_version: int = 1
    snapshot_version: str
    spec: ArtifactSpec
    embedding_model_provenance: str = "operator-attested; not encoded in legacy index"
    dependencies: dict[str, str]
    lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exporter_platform: str
    files: dict[str, FileRecord]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or str(path) != value
        or any(not SAFE_COMPONENT.fullmatch(p) or p in {".", ".."} for p in path.parts)
    ):
        raise ArtifactError("Unsafe artifact path.")
    return value


def read_file(root: Path, relative: str) -> bytes:
    """Descriptor-relative reads reject symlinks, hard links, and nonregular files."""
    parts = PurePosixPath(relative_path(relative)).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ArtifactError("Artifacts must be regular files without hard links.")
            return stream.read()
    finally:
        os.close(directory)


def tree(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("Artifact directory is missing or unsafe.")
    result = set()
    for path in root.rglob("*"):
        relative = relative_path(path.relative_to(root).as_posix())
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ArtifactError("Symlinks and special files are forbidden.")
        if path.is_file():
            result.add(relative)
    return result


def records(root: Path, paths: set[str]) -> dict[str, FileRecord]:
    return {
        path: FileRecord(size=len(data), sha256=digest(data))
        for path in sorted(paths)
        for data in [read_file(root, path)]
    }


def _manifest(data: bytes, spec: ArtifactSpec) -> dict[str, dict]:
    manifest = json.loads(data)
    if not isinstance(manifest, dict) or set(manifest) != {"documents"}:
        raise ArtifactError("Unexpected manifest fields.")
    entries = manifest["documents"]
    if not isinstance(entries, list):
        raise ArtifactError("Invalid manifest document list.")
    catalog = {}
    filenames = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {
            "id",
            "filename",
            "title",
            "domain",
            "year",
            "source_url",
        }:
            raise ArtifactError("Unexpected document catalog fields.")
        identifier, filename = entry["id"], relative_path(entry["filename"])
        if (
            identifier in catalog
            or filename in filenames
            or not filename.endswith(".pdf")
            or not SAFE_COMPONENT.fullmatch(identifier)
        ):
            raise ArtifactError("Manifest identifiers are invalid or duplicated.")
        catalog[identifier] = entry
        filenames.add(filename)
    if set(catalog) != set(spec.document_ids) or len(spec.document_ids) != len(
        set(spec.document_ids)
    ):
        raise ArtifactError("Manifest paper IDs do not match the expected corpus.")
    return catalog


def source_files(manifest: Path, papers: Path, index: Path, spec: ArtifactSpec) -> dict[str, Path]:
    catalog = _manifest(read_file(manifest.parent, manifest.name), spec)
    files = {"manifest.json": manifest}
    for entry in catalog.values():
        read_file(papers, entry["filename"])
        files[f"papers/{entry['filename']}"] = papers / entry["filename"]
    for path in tree(index):
        files[f"chroma/{path}"] = index / path
    if "chroma/chroma.sqlite3" not in files:
        raise ArtifactError("Existing Chroma database is required; never create a missing index.")
    return files


def assert_idle(index: Path):
    if shutil.which("lsof") is None:
        raise ArtifactError("lsof is required to check source use; use a controlled offline host.")
    result = subprocess.run(
        ["lsof", "-t", "+D", str(index)], capture_output=True, text=True, timeout=15, check=False
    )
    if result.stdout.strip() or result.stderr.strip() or result.returncode not in {0, 1}:
        raise ArtifactError("Index may be open or its process-use check failed.")


def _check_index(root: Path, spec: ArtifactSpec) -> bytes:
    if sqlite3.sqlite_version_info < (3, 44, 0):
        raise ArtifactError("SQLite >=3.44 is required to verify FTS5 integrity.")
    paths = tree(root)
    if any(p.endswith(("-wal", "-shm", "-journal")) for p in paths):
        raise ArtifactError(
            "SQLite sidecars require a clean offline source; do not checkpoint it here."
        )
    database = root / "chroma.sqlite3"
    if "chroma.sqlite3" not in paths:
        raise ArtifactError("Existing Chroma database is required.")
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    ) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ArtifactError("SQLite integrity check failed (including FTS5).")
        collections = connection.execute("SELECT id,name,dimension FROM collections").fetchall()
        if len(collections) != 1 or collections[0][1:] != (
            spec.collection,
            spec.embedding_dimension,
        ):
            raise ArtifactError("Collection name, count, or embedding dimension mismatch.")
        collection_id = collections[0][0]
        segments = connection.execute(
            "SELECT id,scope FROM segments WHERE collection=?", (collection_id,)
        ).fetchall()
        if sorted(scope for _, scope in segments) != ["METADATA", "VECTOR"]:
            raise ArtifactError("Incomplete collection segments.")
        vector_id = next(identifier for identifier, scope in segments if scope == "VECTOR")
        UUID(vector_id)
        expected_paths = {"chroma.sqlite3"} | {f"{vector_id}/{name}" for name in INDEX_FILES}
        if paths != expected_paths:
            raise ArtifactError("Incomplete or unexpected Chroma persistence files.")
        metadata_id = next(identifier for identifier, scope in segments if scope == "METADATA")
        rows = connection.execute(
            "SELECT id,embedding_id FROM embeddings WHERE segment_id=?", (metadata_id,)
        ).fetchall()
        if len(rows) != spec.chunk_count:
            raise ArtifactError("Empty collection or unexpected chunk count.")
        identifiers = set()
        for row_id, chunk_id in rows:
            metadata = dict(
                connection.execute(
                    "SELECT key,string_value FROM embedding_metadata WHERE id=?", (row_id,)
                ).fetchall()
            )
            if not metadata.get("chroma:document") or metadata.get("chunk_id") != chunk_id:
                raise ArtifactError("Incomplete chunk metadata or document contents.")
            identifiers.add(metadata.get("document_id"))
        if identifiers != set(spec.document_ids):
            raise ArtifactError("Unexpected paper IDs in the index.")
        # V1 deliberately requires a complete replay log, matching this small legacy corpus.
        # It cannot safely certify a purged log using SQLite metadata alone.
        queue = connection.execute(
            "SELECT id,vector,encoding,operation FROM embeddings_queue WHERE topic=?",
            (f"persistent://default/default/{collection_id}",),
        ).fetchall()
        if (
            len(queue) != len(rows)
            or {r[0] for r in queue} != {r[1] for r in rows}
            or any(
                r[2] != "FLOAT32"
                or r[3] not in {0, 2}
                or r[1] is None
                or len(r[1]) != 4 * spec.embedding_dimension
                for r in queue
            )
        ):
            raise ArtifactError("Incomplete vector replay log or incompatible vector dimensions.")
        sample = queue[0][1]
        if any(
            not math.isfinite(value)
            for row in queue
            for value in struct.unpack(f"<{spec.embedding_dimension}f", row[1])
        ):
            raise ArtifactError("Nonfinite stored embeddings.")
    header = read_file(root, f"{vector_id}/header.bin")
    if len(header) != 100:
        raise ArtifactError("Invalid HNSW header.")
    fields = struct.unpack("<i12Q", header)
    capacity, count, stride, label_offset, data_offset = fields[2:7]
    if (
        fields[0] != 1
        or not capacity
        or count > capacity
        or label_offset - data_offset != 4 * spec.embedding_dimension
        or stride != label_offset + 8
        or len(read_file(root, f"{vector_id}/data_level0.bin")) != capacity * stride
        or len(read_file(root, f"{vector_id}/length.bin")) != capacity * 4
    ):
        raise ArtifactError("Incomplete or incompatible HNSW contents.")
    return sample


def _check_payload(root: Path, spec: ArtifactSpec):
    if {p.name for p in root.iterdir()} - {"manifest.json", "papers", "chroma", "bundle.json"}:
        raise ArtifactError("Unexpected bundle entries.")
    catalog = _manifest(read_file(root, "manifest.json"), spec)
    if tree(root / "papers") != {entry["filename"] for entry in catalog.values()}:
        raise ArtifactError("Manifest/PDF inventory mismatch.")
    for entry in catalog.values():
        with pymupdf.open(
            stream=read_file(root, f"papers/{entry['filename']}"), filetype="pdf"
        ) as pdf:
            if pdf.needs_pass or pdf.is_repaired or not pdf.page_count:
                raise ArtifactError("PDF is encrypted, corrupt, or empty.")
            for page in pdf:
                page.get_text("text")  # Offline parser check; no text is included in errors.
    _check_index(root / "chroma", spec)
    # Check the mapping, not just the set: Evidence IDs differ from Workspace filenames.
    with closing(
        sqlite3.connect(
            (root / "chroma/chroma.sqlite3").resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as connection:
        mapping = connection.execute(
            "SELECT DISTINCT a.string_value,b.string_value FROM embedding_metadata a "
            "JOIN embedding_metadata b ON a.id=b.id WHERE a.key='document_id' AND b.key='filename'"
        ).fetchall()
        if set(mapping) != {
            (identifier, entry["filename"]) for identifier, entry in catalog.items()
        }:
            raise ArtifactError("Index paper ID/PDF filename mapping mismatch.")


def runtime_probe(root: Path, spec: ArtifactSpec):
    """Query existing vectors on a disposable writable copy in a fresh process.

    No ingestion, embedding model, or API requests. The canonical bundle is never
    passed to Chroma, whose initialization/replay can write to its directory.
    """
    sample = _check_index(root / "chroma", spec)
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "index"
        shutil.copytree(root / "chroma", target)
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        script = """
import json, sys, chromadb
from chromadb.config import Settings
client = chromadb.PersistentClient(path=sys.argv[1], settings=Settings(anonymized_telemetry=False))
collection = client.get_collection(sys.argv[2], embedding_function=None)
expected = int(sys.argv[3])
if collection.count() != expected:
    raise RuntimeError('Count mismatch')
query = json.loads(sys.argv[4])
records = collection.get(include=['embeddings'])
vectors = records['embeddings']
if len(records['ids']) != expected or vectors is None or len(vectors) != expected:
    raise RuntimeError('Incomplete vector contents')
if any(vector is None or len(vector) != len(query) for vector in vectors):
    raise RuntimeError('Vector dimension mismatch')
result = collection.query(query_embeddings=[query], n_results=1)
if not result['ids'][0]:
    raise RuntimeError('Empty query result')
"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(target),
                spec.collection,
                str(spec.chunk_count),
                json.dumps(struct.unpack(f"<{spec.embedding_dimension}f", sample)),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise ArtifactError("Chroma offline query probe failed on a disposable copy.")


def validate_bundle(
    root: Path,
    *,
    expected: ArtifactSpec | None = None,
    metadata_sha256: str | None = None,
    lock_file: Path | None = None,
    probe: bool = False,
) -> BundleMetadata:
    expected = expected or ArtifactSpec()
    paths = tree(root)
    metadata_bytes = read_file(root, "bundle.json")
    if metadata_sha256 is not None and digest(metadata_bytes) != metadata_sha256:
        raise ArtifactError("Bundle metadata does not match the trusted digest.")
    metadata = BundleMetadata.model_validate_json(metadata_bytes)
    relative_path(metadata.snapshot_version)
    if metadata.format_version != 1 or metadata.spec != expected:
        raise ArtifactError("Snapshot specification or embedding model mismatch.")
    if metadata.dependencies != {name: version(name) for name in DEPENDENCIES}:
        raise ArtifactError("Bundle dependency versions do not match the runtime.")
    if metadata.dependencies["chromadb"] != "1.5.9":
        raise ArtifactError("Unsupported Chroma persistence version.")
    if lock_file is not None and digest(lock_file.read_bytes()) != metadata.lock_sha256:
        raise ArtifactError("Bundle lockfile mismatch.")
    if set(metadata.files) != paths - {"bundle.json"}:
        raise ArtifactError("Bundle inventory is incomplete or contains unexpected files.")
    if records(root, set(metadata.files)) != metadata.files:
        raise ArtifactError("Bundle file checksum or size mismatch.")
    _check_payload(root, expected)
    if probe:
        runtime_probe(root, expected)
    return metadata


def package_bundle(
    *,
    manifest: Path,
    papers: Path,
    index: Path,
    destination: Path,
    snapshot_version: str,
    lock_file: Path,
    expected: ArtifactSpec | None = None,
    source_quiescent: bool = False,
    audit_open_files: bool = True,
    embedding_model_provenance: str = "operator-attested; not encoded in legacy index",
) -> str:
    """Atomically publish a new bundle only after offline and native query validation."""
    if not source_quiescent:
        raise ArtifactError("Stop all readers/writers and explicitly attest source quiescence.")
    relative_path(snapshot_version)
    if "/" in snapshot_version:
        raise ArtifactError("Snapshot version must be one safe path component.")
    expected = expected or ArtifactSpec()
    destination = destination.absolute()
    for source in (papers, index, manifest.parent):
        source = source.resolve()
        target = destination.resolve()
        if target.is_relative_to(source) or source.is_relative_to(target):
            raise ArtifactError("Snapshot destination must not overlap source paths.")
    if destination.exists() or destination.is_symlink():
        raise ArtifactError("Snapshot destination already exists; never overwrite it.")
    if audit_open_files:
        assert_idle(index)
    files = source_files(manifest, papers, index, expected)

    def read_source(name, path):
        if name.startswith("papers/"):
            return read_file(papers, name.removeprefix("papers/"))
        if name.startswith("chroma/"):
            return read_file(index, name.removeprefix("chroma/"))
        return read_file(path.parent, path.name)

    before = {
        name: (
            path.stat().st_mtime_ns,
            path.stat().st_ino,
            digest(read_source(name, path)),
        )
        for name, path in files.items()
    }
    # Refuse corrupt sources before creating a destination or staging directory.
    _check_index(index, expected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rag-staging-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for name, source in sorted(files.items()):
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_source(name, source))
            target.chmod(0o444)
            os.utime(target, (0, 0))
        _check_payload(staging, expected)
        metadata = BundleMetadata(
            snapshot_version=snapshot_version,
            spec=expected,
            embedding_model_provenance=embedding_model_provenance,
            dependencies={name: version(name) for name in DEPENDENCIES},
            lock_sha256=digest(lock_file.read_bytes()),
            exporter_platform=f"{platform.system()}/{platform.machine()}",
            files=records(staging, tree(staging)),
        )
        payload = (json.dumps(metadata.model_dump(), sort_keys=True, indent=2) + "\n").encode()
        (staging / "bundle.json").write_bytes(payload)
        (staging / "bundle.json").chmod(0o444)
        os.utime(staging / "bundle.json", (0, 0))
        validate_bundle(staging, expected=expected, lock_file=lock_file, probe=True)
        if audit_open_files:
            assert_idle(index)
        after_files = source_files(manifest, papers, index, expected)
        after = {
            name: (
                path.stat().st_mtime_ns,
                path.stat().st_ino,
                digest(read_source(name, path)),
            )
            for name, path in after_files.items()
        }
        if before != after:
            raise ArtifactError("Source changed during packaging; snapshot not published.")
        staging.rename(destination)
    return digest(payload)
