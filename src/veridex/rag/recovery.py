"""Offline, narrowly authorized recovery; source Chroma is never opened by Chroma.

The reviewed inspection digest pins every source file, including PDFs. Quiescence
is an operator-controlled maintenance window, not a lock supplied by this module.
Public Chroma API reconstruction runs in a child process to close native handles.
"""

import json
import math
import platform
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

from veridex.rag.artifacts import (
    DEPENDENCIES,
    ArtifactError,
    ArtifactSpec,
    BundleMetadata,
    _check_index,
    assert_idle,
    digest,
    read_file,
    records,
    relative_path,
    source_files,
    tree,
    validate_bundle,
)

REFERENCE_SHA256 = "7e033346ee4ff1c9dc6e408b0c3989e7ecbc7f4756a964519f13ae53afcc1f07"
TARGET = "rag_2020_p3_c00012"
RAW_SHA256 = "e0e1f6dad94e63be569dc1e25e4232c18761285ba538dcede2a27458191d0eef"
CLEAN_SHA256 = "2813cf233f4997a676c2211bf4f46f73ccca0b3bb0ae48fa7250debaf3222e98"
SPEC = ArtifactSpec(embedding_model="unverified-legacy-model")
NORMALIZATION = {
    "chunk_id": TARGET,
    "original_sha256": RAW_SHA256,
    "recovered_sha256": CLEAN_SHA256,
    "characters": 927,
    "replacements": [
        {"offset": 491, "from": "U+0000", "to": "("},
        {"offset": 502, "from": "U+0001", "to": ")"},
    ],
    "basis": "rag_2020.pdf page 3, section 2.2; reviewed CMEX10 parentheses",
}


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def normalize(identifier: str, text: str) -> str:
    """Change precisely two reviewed positions, never rechunk or normalize globally."""
    if identifier != TARGET:
        if "\0" in text:
            raise ArtifactError("Unexpected NUL outside the approved chunk.")
        return text
    if (
        digest(text.encode()) != RAW_SHA256
        or len(text) != 927
        or text.count("\0") != 1
        or text.count("\1") != 1
        or text[491] != "\0"
        or text[502] != "\1"
    ):
        raise ArtifactError("Approved chunk text or control-character pair does not match.")
    result = text[:491] + "(" + text[492:502] + ")" + text[503:]
    if len(result) != len(text) or digest(result.encode()) != CLEAN_SHA256:
        raise ArtifactError("Targeted normalization verification failed.")
    return result


def fingerprint(project: Path, inventory: dict) -> dict:
    """Check the pinned inventory and mtimes without opening a database connection."""
    expected_files = source_files(
        project / "data/samples/manifest.json",
        project / "data/papers",
        project / "data/index",
        SPEC,
    )
    paths = {path.relative_to(project).as_posix() for path in expected_files.values()}
    if paths != set(inventory):
        raise ArtifactError("Source inventory is incomplete or has unexpected index files.")
    result = {}
    for name in sorted(paths):
        relative_path(name)
        data = read_file(project, name)
        info = (project / name).stat()
        value = {"size": len(data), "sha256": digest(data), "mtime_ns": info.st_mtime_ns}
        if value != inventory[name]:
            raise ArtifactError("Source differs from the reviewed recovery fingerprints.")
        result[name] = {**value, "inode": info.st_ino}
    return result


def extract(index: Path) -> list[dict]:
    """Read a verified disposable copy; require complete, unambiguous FLOAT32 replay."""
    if sqlite3.sqlite_version_info < (3, 44, 0):
        raise ArtifactError("SQLite >=3.44 is required for FTS5 verification.")
    with closing(
        sqlite3.connect(
            (index / "chroma.sqlite3").resolve().as_uri() + "?mode=ro&immutable=1",
            uri=True,
        )
    ) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [
            ("malformed inverted index for FTS5 table main.embedding_fulltext_search",)
        ]:
            raise ArtifactError("Source failure differs from the reviewed FTS5-only failure.")
        for table in (
            "collections",
            "segments",
            "embeddings",
            "embedding_metadata",
            "embeddings_queue",
        ):
            if db.execute(f"PRAGMA integrity_check('{table}')").fetchall() != [("ok",)]:
                raise ArtifactError("Source has corruption outside FTS5.")
        collections = db.execute("SELECT id,name,dimension FROM collections").fetchall()
        if len(collections) != 1 or collections[0][1:] != (
            SPEC.collection,
            SPEC.embedding_dimension,
        ):
            raise ArtifactError("Unexpected source collection or dimension.")
        collection_id = collections[0][0]
        metadata = {}
        for row, key, string, integer, real, boolean in db.execute(
            "SELECT id,key,string_value,int_value,float_value,bool_value FROM embedding_metadata"
        ):
            values = [v for v in (string, integer, real, boolean) if v is not None]
            if len(values) != 1 or key in metadata.setdefault(row, {}):
                raise ArtifactError("Ambiguous stored metadata.")
            metadata[row][key] = bool(boolean) if boolean is not None else values[0]
        queue = db.execute(
            "SELECT id,vector,encoding,operation,topic,metadata FROM embeddings_queue"
        ).fetchall()
        vectors = {}
        for identifier, vector, encoding, operation, topic, raw_metadata in queue:
            if (
                identifier in vectors
                or encoding != "FLOAT32"
                or operation not in {0, 2}
                or topic != f"persistent://default/default/{collection_id}"
                or vector is None
                or len(vector) != 4 * SPEC.embedding_dimension
                or not all(
                    math.isfinite(v) for v in struct.unpack(f"<{SPEC.embedding_dimension}f", vector)
                )
            ):
                raise ArtifactError("Incomplete, ambiguous, or invalid embedding replay data.")
            vectors[identifier] = (vector, json.loads(raw_metadata))
        output = []
        for row, identifier in db.execute(
            "SELECT id,embedding_id FROM embeddings ORDER BY embedding_id"
        ):
            stored = metadata[row]
            if identifier not in vectors or vectors[identifier][1] != stored:
                raise ArtifactError("Stored document/metadata differs from vector replay metadata.")
            text = stored["chroma:document"]
            user_metadata = {k: v for k, v in stored.items() if k != "chroma:document"}
            if user_metadata.get("chunk_id") != identifier:
                raise ArtifactError("Chunk identity mismatch.")
            output.append(
                {
                    "id": identifier,
                    "metadata": user_metadata,
                    "document": normalize(identifier, text),
                    "vector_hex": vectors[identifier][0].hex(),
                    "original_text_sha256": digest(text.encode()),
                }
            )
    if (
        len(output) != SPEC.chunk_count
        or len(vectors) != SPEC.chunk_count
        or len({r["id"] for r in output}) != SPEC.chunk_count
        or TARGET not in {r["id"] for r in output}
        or {r["metadata"].get("document_id") for r in output} != set(SPEC.document_ids)
    ):
        raise ArtifactError("Unexpected chunk count, IDs, or paper IDs.")
    return output


# Explicit embeddings and embedding_function=None prevent provider/model loading.
NATIVE = r"""
import json,sys
from pathlib import Path
import numpy as np
import chromadb
from chromadb.config import Settings
root, payload, mode = sys.argv[1:]
data = json.loads(Path(payload).read_bytes())
def require(condition):
    if not condition:
        raise ValueError('Native recovery invariant failed')
client = chromadb.PersistentClient(path=root, settings=Settings(anonymized_telemetry=False))
collection = (client.create_collection('veridex_documents', embedding_function=None)
              if mode == 'build' else client.get_collection('veridex_documents', embedding_function=None))
if mode == 'build':
    for start in range(0,len(data),50):
        batch=data[start:start+50]
        collection.add(ids=[r['id'] for r in batch], documents=[r['document'] for r in batch],
            metadatas=[r['metadata'] for r in batch],
            embeddings=[np.frombuffer(bytes.fromhex(r['vector_hex']),dtype='<f4').tolist() for r in batch])
got=collection.get(include=['embeddings','metadatas','documents'])
actual={identifier:(np.asarray(vector,dtype='<f4').tobytes().hex(),metadata,document)
        for identifier,vector,metadata,document in zip(got['ids'],got['embeddings'],got['metadatas'],got['documents'])}
require(collection.count()==len(data) and set(actual)=={r['id'] for r in data})
require(all(actual[r['id']]==(r['vector_hex'],r['metadata'],r['document']) for r in data))
hits=0
for start in range(0,len(data),25):
    batch=data[start:start+25]
    result=collection.query(query_embeddings=[np.frombuffer(bytes.fromhex(r['vector_hex']),dtype='<f4').tolist() for r in batch],n_results=min(5,len(data)))
    for record,ids,distances in zip(batch,result['ids'],result['distances']):
        require(record['id'] in ids and distances[ids.index(record['id'])]<1e-6)
        hits+=1
for term in ['BERTd', 'd(z)', 'q(x)']:
    expected={r['id'] for r in data if term in r['document']}
    require(set(collection.get(where_document={'$contains':term},include=['documents'])['ids'])==expected)
print(json.dumps({'chunks':len(data),'vectors_preserved':len(data),'metadata_preserved':len(data),
                  'self_queries':hits,'text_filter_terms':['BERTd','d(z)','q(x)']}))
"""


def native(index: Path, payload: Path, *, build: bool) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", NATIVE, str(index), str(payload), "build" if build else "audit"],
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise ArtifactError(
            "Public Chroma reconstruction or native preservation/retrieval check failed."
        )
    return json.loads(result.stdout)


def verify(index: Path, payload: Path, temporary: Path, project: Path) -> dict:
    """Audit disposable copies; retain no validation bundle and do not repair tables."""
    _check_index(index, SPEC)
    probe = temporary / "probe"
    shutil.copytree(index, probe)
    for path in probe.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
    result = native(probe, payload, build=False)
    _check_index(probe, SPEC)
    with closing(sqlite3.connect(probe / "chroma.sqlite3")) as db:
        # FTS5's official diagnostic command is run only on the disposable copy.
        db.execute(
            "INSERT INTO embedding_fulltext_search(embedding_fulltext_search,rank) VALUES('integrity-check',1)"
        )
        db.rollback()
    bundle = temporary / "validation-only"
    bundle.mkdir()
    for name, source in source_files(
        project / "data/samples/manifest.json", project / "data/papers", index, SPEC
    ).items():
        target = bundle / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    metadata = BundleMetadata(
        snapshot_version="recovery-validation-only",
        spec=SPEC,
        embedding_model_provenance="UNRESOLVED: preserved legacy vectors; model identity not verified",
        dependencies={name: version(name) for name in DEPENDENCIES},
        lock_sha256=digest(read_file(project, "uv.lock")),
        exporter_platform=f"{platform.system()}/{platform.machine()}",
        files=records(bundle, tree(bundle)),
    )
    contents = canonical(metadata.model_dump())
    (bundle / "bundle.json").write_bytes(contents)
    validate_bundle(
        bundle,
        expected=SPEC,
        metadata_sha256=digest(contents),
        lock_file=project / "uv.lock",
        probe=True,
    )
    return {
        **result,
        "sqlite_integrity": "ok",
        "fts5_integrity": "ok",
        "artifact_validator": "passed on disposable bundle; model identity unresolved",
    }


def recover(
    *, project: Path, reference: Path, destination: Path, source_quiescent: bool = False
) -> dict:
    """Publish only the separate recovered index/provenance, never a deployment bundle."""
    if not source_quiescent:
        raise ArtifactError("Stop all readers/writers and explicitly attest source quiescence.")
    if version("chromadb") != "1.5.9":
        raise ArtifactError("Recovery requires the reviewed Chroma 1.5.9 version.")
    project = project.absolute()
    destination = destination.absolute()
    # All retained recovery outputs must live in the repository's ignored artifact root.
    allowed = project / ".artifacts/recovery"
    if (
        destination.is_symlink()
        or destination == allowed
        or not destination.is_relative_to(allowed)
        or destination.resolve() != destination
        or project.resolve() != project
    ):
        raise ArtifactError(
            "Recovery destination must be a separate safe directory under .artifacts/recovery."
        )
    relative_path(destination.relative_to(project).as_posix().removeprefix(".artifacts/"))
    reference_bytes = read_file(reference.parent, reference.name)
    if digest(reference_bytes) != REFERENCE_SHA256:
        raise ArtifactError("Inspection report does not match the reviewed trusted digest.")
    inventory = json.loads(reference_bytes)["source_inventory"]
    index = project / "data/index"
    assert_idle(index)
    before = fingerprint(project, inventory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".recovery-", dir=destination.parent) as scratch:
        temporary = Path(scratch)
        source = temporary / "source"
        source.mkdir()
        for name in tree(index):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(read_file(index, name))
            if digest(target.read_bytes()) != inventory[f"data/index/{name}"]["sha256"]:
                raise ArtifactError("Source changed during isolated snapshot copying.")
        assert_idle(index)
        if fingerprint(project, inventory) != before:
            raise ArtifactError("Source changed before extraction.")
        data = extract(source)
        payload = temporary / "records.json"
        payload.write_bytes(canonical(data))
        preserved = {
            r["id"]: {
                "float32_sha256": digest(bytes.fromhex(r["vector_hex"])),
                "metadata_sha256": digest(canonical(r["metadata"])),
                "original_text_sha256": r["original_text_sha256"],
                "recovered_text_sha256": digest(r["document"].encode()),
            }
            for r in data
        }
        identity = {
            "format_version": 1,
            "source_inspection_sha256": REFERENCE_SHA256,
            "source_files": inventory,
            "normalization": NORMALIZATION,
            "preserved_chunks": preserved,
            "spec": SPEC.model_dump(),
            "chroma_version": version("chromadb"),
            "embedding_model_identity": "UNRESOLVED; not inferred from dimension or runtime settings",
            "lock_sha256": digest(read_file(project, "uv.lock")),
        }
        reused = destination.exists()
        if reused:
            existing = json.loads(read_file(destination, "provenance.json"))
            if any(existing.get(k) != v for k, v in identity.items()):
                raise ArtifactError("Existing recovery provenance differs; never overwrite it.")
            expected_files = tree(destination / "chroma")
            actual_inventory = {
                k: v.model_dump()
                for k, v in records(destination / "chroma", expected_files).items()
            }
            if actual_inventory != existing.get("recovered_files") or tree(destination) != {
                "provenance.json"
            } | {f"chroma/{p}" for p in expected_files}:
                raise ArtifactError("Existing recovered files are modified or incomplete.")
            audit = verify(destination / "chroma", payload, temporary, project)
            report = {**existing, "validation": audit}
        else:
            staging = temporary / "candidate"
            staging.mkdir()
            candidate = staging / "chroma"
            native(candidate, payload, build=True)
            audit = verify(candidate, payload, temporary, project)
            report = {
                **identity,
                "validation": audit,
                "recovered_files": {
                    k: v.model_dump() for k, v in records(candidate, tree(candidate)).items()
                },
            }
            (staging / "provenance.json").write_bytes(canonical(report))
        assert_idle(index)
        if fingerprint(project, inventory) != before:
            raise ArtifactError("Source changed during recovery; candidate not retained.")
        if not reused:
            if destination.exists() or destination.is_symlink():
                raise ArtifactError(
                    "Recovery destination appeared during validation; never overwrite it."
                )
            staging.rename(destination)
    return report
