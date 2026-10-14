import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

from veridex.rag import artifacts
from veridex.rag.artifacts import ArtifactError, ArtifactSpec, package_bundle, validate_bundle

SPEC = ArtifactSpec(document_ids=["paper_a", "paper_b"], chunk_count=2, embedding_dimension=3)


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("rag-artifact-seed")
    source = root / "source"
    source.mkdir()
    script = """
import json, sys
from pathlib import Path
import chromadb, pymupdf
from chromadb.config import Settings
root = Path(sys.argv[1])
(root/'papers').mkdir()
entries = []
for identifier in ['paper_a', 'paper_b']:
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72,72), 'Synthetic offline evidence.')
        pdf.save(root/'papers'/f'{identifier}.pdf')
    entries.append({'id':identifier,'filename':f'{identifier}.pdf'})
(root/'manifest.json').write_text(json.dumps({'documents':entries}))
client = chromadb.PersistentClient(path=str(root/'index'), settings=Settings(anonymized_telemetry=False))
collection = client.create_collection('veridex_documents', embedding_function=None)
collection.add(ids=['chunk-a','chunk-b'], embeddings=[[1,0,0],[0,1,0]],
    documents=['Synthetic offline evidence a.', 'Synthetic offline evidence b.'],
    metadatas=[{'document_id':'paper_a','filename':'paper_a.pdf','chunk_id':'chunk-a'},
               {'document_id':'paper_b','filename':'paper_b.pdf','chunk_id':'chunk-b'}])
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(source)], capture_output=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr.decode()
    lock = root / "uv.lock"
    lock.write_text("synthetic-test-lock\n")
    canonical = root / "bundles/v1"
    checksum = package_bundle(
        manifest=source / "manifest.json",
        papers=source / "papers",
        index=source / "index",
        destination=canonical,
        snapshot_version="v1",
        lock_file=lock,
        expected=SPEC,
        source_quiescent=True,
        audit_open_files=False,
    )
    return source, canonical, lock, checksum


@pytest.fixture
def bundle(seed, tmp_path):
    root = tmp_path / "bundle"
    shutil.copytree(seed[1], root)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
    return root


def reseal(root):
    """Construct a self-consistent but semantically invalid candidate for validation tests."""
    payload = json.loads((root / "bundle.json").read_text())
    payload["files"] = {
        name: record.model_dump()
        for name, record in artifacts.records(root, artifacts.tree(root) - {"bundle.json"}).items()
    }
    (root / "bundle.json").write_text(json.dumps(payload))


def sql(root, statement, parameters=()):
    with sqlite3.connect(root / "chroma/chroma.sqlite3") as connection:
        connection.execute(statement, parameters)
    reseal(root)


def index_fingerprints(root):
    return {
        name: (record, (root / name).stat().st_mtime_ns)
        for name, record in artifacts.records(root, artifacts.tree(root)).items()
    }


def test_valid_bundle_and_native_query_are_read_only(bundle, seed):
    before = index_fingerprints(bundle)
    metadata = validate_bundle(bundle, expected=SPEC, lock_file=seed[2], probe=True)
    assert len(metadata.files) == 8  # Manifest, two PDFs, SQLite, four HNSW files.
    assert metadata.spec.document_ids == ["paper_a", "paper_b"]
    assert metadata.spec.embedding_model == "text-embedding-3-small"
    assert before == index_fingerprints(bundle)


def test_reproducible_export_and_unchanged_source(seed, tmp_path):
    source, original, lock, checksum = seed
    before = index_fingerprints(source)
    destination = tmp_path / "version"
    assert (
        package_bundle(
            manifest=source / "manifest.json",
            papers=source / "papers",
            index=source / "index",
            destination=destination,
            snapshot_version="v1",
            lock_file=lock,
            expected=SPEC,
            source_quiescent=True,
            audit_open_files=False,
        )
        == checksum
    )
    assert artifacts.records(original, artifacts.tree(original)) == artifacts.records(
        destination, artifacts.tree(destination)
    )
    assert before == index_fingerprints(source)


@pytest.mark.parametrize("path", ["manifest.json", "papers/paper_a.pdf", "chroma/chroma.sqlite3"])
def test_missing_files_rejected(bundle, path):
    (bundle / path).unlink()
    with pytest.raises(ArtifactError):
        validate_bundle(bundle, expected=SPEC)


def test_modified_file_and_unlisted_file_rejected(bundle):
    (bundle / "papers/paper_a.pdf").write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="checksum"):
        validate_bundle(bundle, expected=SPEC)
    (bundle / "unexpected.txt").write_text("unapproved")
    with pytest.raises(ArtifactError, match="inventory"):
        validate_bundle(bundle, expected=SPEC)


@pytest.mark.parametrize(
    "mutation", ["id", "duplicate", "filename", "traversal", "root_extra", "entry_extra"]
)
def test_manifest_mismatch_and_unsafe_identifiers(bundle, mutation):
    manifest = json.loads((bundle / "manifest.json").read_text())
    entry = manifest["documents"][0]
    if mutation == "id":
        entry["id"] = "unknown"
    elif mutation == "duplicate":
        manifest["documents"].append(entry)
    elif mutation == "filename":
        entry["filename"] = "absent.pdf"
    elif mutation == "traversal":
        entry["filename"] = "../escape.pdf"
    elif mutation == "root_extra":
        manifest["credentials"] = "must not package unrelated fields"
    else:
        entry["credentials"] = "must not package unrelated fields"
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    reseal(bundle)
    with pytest.raises(ArtifactError):
        validate_bundle(bundle, expected=SPEC)


@pytest.mark.parametrize(
    "statement,parameters",
    [
        ("UPDATE collections SET name='wrong_collection'", ()),
        ("DELETE FROM collections", ()),
        ("DELETE FROM embeddings", ()),
        ("DELETE FROM embeddings WHERE embedding_id='chunk-b'", ()),
        ("UPDATE collections SET dimension=4", ()),
        ("UPDATE embedding_metadata SET string_value='unknown' WHERE key='document_id'", ()),
        ("UPDATE embedding_metadata SET string_value='paper_b.pdf' WHERE key='filename'", ()),
        ("DELETE FROM embedding_metadata WHERE key='chroma:document'", ()),
        ("DELETE FROM segments WHERE scope='VECTOR'", ()),
        ("DELETE FROM embeddings_queue", ()),
        ("UPDATE embeddings_queue SET vector=x'00000000'", ()),
        ("UPDATE embeddings_queue SET vector=x'0000807f0000000000000000'", ()),
        (
            "UPDATE embedding_fulltext_search_content SET c0='Deliberately inconsistent FTS contents'",
            (),
        ),
    ],
)
def test_semantically_invalid_database_rejected(bundle, statement, parameters):
    sql(bundle, statement, parameters)
    with pytest.raises(ArtifactError):
        validate_bundle(bundle, expected=SPEC)


@pytest.mark.parametrize(
    "path,data",
    [
        ("chroma/chroma.sqlite3", b"not sqlite"),
        ("papers/paper_a.pdf", b"not a pdf"),
    ],
)
def test_corrupt_payload_rejected_even_with_new_checksums(bundle, path, data):
    (bundle / path).write_bytes(data)
    reseal(bundle)
    with pytest.raises((ArtifactError, sqlite3.DatabaseError, RuntimeError)):
        validate_bundle(bundle, expected=SPEC)


@pytest.mark.parametrize("kind", ["missing", "header", "data", "sidecar", "unapproved"])
def test_incomplete_hnsw_or_unapproved_index_contents(bundle, kind):
    directory = next((bundle / "chroma").glob("*/header.bin")).parent
    if kind == "missing":
        (directory / "length.bin").unlink()
    elif kind == "header":
        (directory / "header.bin").write_bytes(b"bad")
    elif kind == "data":
        (directory / "data_level0.bin").write_bytes(b"short")
    elif kind == "sidecar":
        (bundle / "chroma/chroma.sqlite3-wal").write_bytes(b"")
    else:
        (directory / "secret.txt").write_bytes(b"unapproved")
    reseal(bundle)
    with pytest.raises(ArtifactError):
        validate_bundle(bundle, expected=SPEC)


@pytest.mark.parametrize("kind", ["model", "dependencies", "inventory", "version"])
def test_metadata_mismatches(bundle, kind):
    metadata = json.loads((bundle / "bundle.json").read_text())
    if kind == "model":
        metadata["spec"]["embedding_model"] = "wrong-model"
    elif kind == "dependencies":
        metadata["dependencies"]["chromadb"] = "different"
    elif kind == "inventory":
        metadata["files"].pop("manifest.json")
    else:
        metadata["format_version"] = 2
    (bundle / "bundle.json").write_text(json.dumps(metadata))
    with pytest.raises(ArtifactError):
        validate_bundle(bundle, expected=SPEC)


def test_independent_metadata_digest_and_lockfile_required_to_match(bundle, seed, tmp_path):
    validate_bundle(bundle, expected=SPEC, metadata_sha256=seed[3], lock_file=seed[2])
    with pytest.raises(ArtifactError, match="trusted digest"):
        validate_bundle(bundle, expected=SPEC, metadata_sha256="0" * 64)
    lock = tmp_path / "wrong.lock"
    lock.write_text("different")
    with pytest.raises(ArtifactError, match="lockfile"):
        validate_bundle(bundle, expected=SPEC, lock_file=lock)


@pytest.mark.parametrize("unsafe", ["../manifest.json", "/absolute", "a//b", "a/../b", "a\\b"])
def test_inventory_path_safety(bundle, unsafe):
    metadata = json.loads((bundle / "bundle.json").read_text())
    metadata["files"][unsafe] = metadata["files"].pop("manifest.json")
    (bundle / "bundle.json").write_text(json.dumps(metadata))
    with pytest.raises(ArtifactError):
        validate_bundle(bundle, expected=SPEC)


@pytest.mark.parametrize("kind", ["symlink", "directory_symlink", "hardlink"])
def test_links_rejected(bundle, tmp_path, kind):
    target = bundle / "papers/paper_a.pdf"
    outside = tmp_path / "outside.pdf"
    target.rename(outside)
    if kind == "symlink":
        target.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, target)
    else:
        shutil.rmtree(bundle / "papers")
        (bundle / "papers").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises((ArtifactError, OSError)):
        validate_bundle(bundle, expected=SPEC)


def test_source_quiescence_missing_index_and_destination_guards(seed, tmp_path):
    source, _, lock, _ = seed
    args = {
        "manifest": source / "manifest.json",
        "papers": source / "papers",
        "index": source / "index",
        "destination": tmp_path / "export",
        "snapshot_version": "v1",
        "lock_file": lock,
        "expected": SPEC,
        "audit_open_files": False,
    }
    with pytest.raises(ArtifactError, match="quiescence"):
        package_bundle(**args)
    args["source_quiescent"] = True
    args["index"] = tmp_path / "missing"
    with pytest.raises(ArtifactError):
        package_bundle(**args)
    assert not args["index"].exists() and not args["destination"].exists()
    args["index"] = source / "index"
    args["destination"] = source / "index/nested"
    with pytest.raises(ArtifactError, match="overlap"):
        package_bundle(**args)
    args["destination"] = seed[1]
    with pytest.raises(ArtifactError, match="already exists"):
        package_bundle(**args)


def test_open_files_and_source_changes_abort_export(seed, tmp_path, monkeypatch):
    source = tmp_path / "source"
    shutil.copytree(seed[0], source)
    args = {
        "manifest": source / "manifest.json",
        "papers": source / "papers",
        "index": source / "index",
        "destination": tmp_path / "export",
        "snapshot_version": "v1",
        "lock_file": seed[2],
        "expected": SPEC,
        "source_quiescent": True,
    }
    monkeypatch.setattr(
        artifacts,
        "assert_idle",
        lambda root: (_ for _ in ()).throw(ArtifactError("Index may be open")),
    )
    with pytest.raises(ArtifactError, match="open"):
        package_bundle(**args)
    monkeypatch.setattr(artifacts, "assert_idle", lambda root: None)
    original = artifacts.runtime_probe

    def change_source(root, spec):
        original(root, spec)
        (source / "papers/paper_a.pdf").write_bytes(b"changed")

    monkeypatch.setattr(artifacts, "runtime_probe", change_source)
    with pytest.raises(ArtifactError, match="Source changed"):
        package_bundle(**args)
    assert not args["destination"].exists()
    assert not list(tmp_path.glob(".rag-staging-*"))


@pytest.mark.skipif(shutil.which("lsof") is None, reason="Export host needs lsof")
def test_real_open_file_check_and_export_closes_its_sqlite_handles(seed, tmp_path):
    source, _, lock, _ = seed
    with (source / "index/chroma.sqlite3").open("rb"), pytest.raises(ArtifactError, match="open"):
        artifacts.assert_idle(source / "index")
    package_bundle(
        manifest=source / "manifest.json",
        papers=source / "papers",
        index=source / "index",
        destination=tmp_path / "export",
        snapshot_version="v1",
        lock_file=lock,
        expected=SPEC,
        source_quiescent=True,
    )
    artifacts.assert_idle(source / "index")


def test_corrupt_source_is_not_published_or_mutated(seed, tmp_path):
    source = tmp_path / "source"
    shutil.copytree(seed[0], source)
    with sqlite3.connect(source / "index/chroma.sqlite3") as connection:
        connection.execute("UPDATE embedding_fulltext_search_content SET c0='broken FTS data'")
    before = index_fingerprints(source)
    destination = tmp_path / "export"
    with pytest.raises(ArtifactError, match="SQLite integrity"):
        package_bundle(
            manifest=source / "manifest.json",
            papers=source / "papers",
            index=source / "index",
            destination=destination,
            snapshot_version="v1",
            lock_file=seed[2],
            expected=SPEC,
            source_quiescent=True,
            audit_open_files=False,
        )
    assert not destination.exists()
    assert before == index_fingerprints(source)


def test_old_sqlite_checker_cannot_certify_fts5(bundle, monkeypatch):
    monkeypatch.setattr(artifacts.sqlite3, "sqlite_version_info", (3, 43, 0))
    with pytest.raises(ArtifactError, match="SQLite >=3.44"):
        validate_bundle(bundle, expected=SPEC)
