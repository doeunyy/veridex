"""Offline regression coverage; synthetic embeddings never load a provider."""

import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from veridex.rag import artifacts, recovery
from veridex.rag.artifacts import ArtifactError, ArtifactSpec

RAW = "a" * 491 + "\0" + "a" * 10 + "\1" + " BERTd d(z) q(x) " + "a" * 407
assert len(RAW) == 927
CLEAN = RAW[:491] + "(" + RAW[492:502] + ")" + RAW[503:]
SPEC = ArtifactSpec(
    document_ids=["paper_a", "paper_b"],
    chunk_count=2,
    embedding_dimension=3,
    embedding_model="unverified-legacy-model",
)


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("recovery-source")
    script = r"""
import json,sys
from pathlib import Path
import chromadb,pymupdf
from chromadb.config import Settings
root=Path(sys.argv[1]); raw=sys.argv[2]; target=sys.argv[3]
(root/'data/papers').mkdir(parents=True); (root/'data/samples').mkdir()
entries=[]
for identifier in ['paper_a','paper_b']:
    with pymupdf.open() as pdf:
        page=pdf.new_page(); page.insert_text((72,72),'Synthetic evidence')
        pdf.save(root/'data/papers'/f'{identifier}.pdf')
    entries.append({'id':identifier,'filename':f'{identifier}.pdf'})
(root/'data/samples/manifest.json').write_text(json.dumps({'documents':entries}))
client=chromadb.PersistentClient(path=str(root/'data/index'),settings=Settings(anonymized_telemetry=False))
c=client.create_collection('veridex_documents',embedding_function=None)
c.add(ids=[target,'chunk-b'],documents=[raw,'BERTd d(z) q(x) other'],
 embeddings=[[1,-0.0,0.25],[0,1,0]],metadatas=[
 {'chunk_id':target,'document_id':'paper_a','filename':'paper_a.pdf','page':3,'verified':False},
 {'chunk_id':'chunk-b','document_id':'paper_b','filename':'paper_b.pdf','page':1,'verified':True}])
"""
    # NUL cannot be passed in argv; serialize through a temporary JSON file instead.
    raw_file = root / "text.json"
    raw_file.write_text(json.dumps(RAW))
    script = script.replace("raw=sys.argv[2]", "raw=json.loads(Path(sys.argv[2]).read_text())")
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), str(raw_file), recovery.TARGET],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    (root / "uv.lock").write_text("synthetic lock")
    raw_file.unlink()
    return root


@pytest.fixture
def source(seed, tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(seed, project)
    monkeypatch.setattr(recovery, "SPEC", SPEC)
    monkeypatch.setattr(recovery, "RAW_SHA256", artifacts.digest(RAW.encode()))
    monkeypatch.setattr(recovery, "CLEAN_SHA256", artifacts.digest(CLEAN.encode()))
    files = artifacts.source_files(
        project / "data/samples/manifest.json",
        project / "data/papers",
        project / "data/index",
        SPEC,
    )
    inventory = {
        p.relative_to(project).as_posix(): {
            "size": p.stat().st_size,
            "sha256": artifacts.digest(p.read_bytes()),
            "mtime_ns": p.stat().st_mtime_ns,
        }
        for p in files.values()
    }
    reference = project / ".artifacts/source-inspection.json"
    reference.parent.mkdir()
    reference.write_bytes(recovery.canonical({"source_inventory": inventory}))
    monkeypatch.setattr(recovery, "REFERENCE_SHA256", artifacts.digest(reference.read_bytes()))
    monkeypatch.setattr(recovery, "assert_idle", lambda index: None)
    return project, reference, inventory


def run(source, *, quiescent=True, destination=None):
    project, reference, _ = source
    return recovery.recover(
        project=project,
        reference=reference,
        destination=destination or project / ".artifacts/recovery/v1",
        source_quiescent=quiescent,
    )


def test_corruption_recovery_vectors_filters_and_idempotence(source):
    project, _, inventory = source
    before = recovery.fingerprint(project, inventory)
    with closing(sqlite3.connect(project / "data/index/chroma.sqlite3")) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
    report = run(source)
    output = project / ".artifacts/recovery/v1"
    assert report["validation"]["vectors_preserved"] == 2
    assert report["validation"]["self_queries"] == 2
    assert report["validation"]["fts5_integrity"] == "ok"
    assert report["spec"]["embedding_model"] == "unverified-legacy-model"
    assert "UNRESOLVED" in report["embedding_model_identity"]
    assert set(report["preserved_chunks"]) == {recovery.TARGET, "chunk-b"}
    assert report["preserved_chunks"][recovery.TARGET]["recovered_text_sha256"] == artifacts.digest(
        CLEAN.encode()
    )
    with closing(
        sqlite3.connect(
            (output / "chroma/chroma.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True
        )
    ) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert (
            db.execute(
                "SELECT string_value FROM embedding_metadata WHERE key='chroma:document' AND instr(string_value,'aaaa')>0"
            ).fetchone()[0]
            == CLEAN
        )
    retained = artifacts.records(output, artifacts.tree(output))
    assert run(source) == report
    assert artifacts.records(output, artifacts.tree(output)) == retained
    assert recovery.fingerprint(project, inventory) == before
    assert list(output.parent.iterdir()) == [output]
    assert not list(output.rglob("bundle.json"))


@pytest.mark.parametrize("quiescent", [False])
def test_requires_explicit_quiescence(source, quiescent):
    with pytest.raises(ArtifactError, match="quiescence"):
        run(source, quiescent=quiescent)


@pytest.mark.parametrize(
    "path", ["data/index/new", ".artifacts/recovery", ".artifacts/other", "outside"]
)
def test_rejects_unsafe_destination(source, path):
    with pytest.raises(ArtifactError, match="destination"):
        run(source, destination=source[0] / path)


def test_symlink_destination_parent(source):
    project = source[0]
    (project / "target").mkdir()
    (project / ".artifacts/recovery").symlink_to(project / "target", target_is_directory=True)
    with pytest.raises(ArtifactError, match="destination"):
        run(source)


def test_rejects_changed_reference(source):
    source[1].write_bytes(source[1].read_bytes() + b" ")
    with pytest.raises(ArtifactError, match="trusted digest"):
        run(source)


@pytest.mark.parametrize("change", ["modified", "missing", "extra", "mtime", "symlink"])
def test_source_fingerprint_failures(source, change):
    project = source[0]
    path = project / "data/index/chroma.sqlite3"
    if change == "modified":
        path.write_bytes(path.read_bytes() + b"unexpected")
    elif change == "missing":
        path.unlink()
    elif change == "extra":
        (path.parent / "chroma.sqlite3-wal").write_bytes(b"pending")
    elif change == "mtime":
        path.touch()
    else:
        saved = project / "saved.sqlite3"
        path.rename(saved)
        path.symlink_to(saved)
    with pytest.raises(ArtifactError):
        run(source)
    assert not (project / ".artifacts/recovery/v1").exists()


def test_active_source_rejected(source, monkeypatch):
    def busy(index):
        raise ArtifactError("Index may be open")

    monkeypatch.setattr(recovery, "assert_idle", busy)
    with pytest.raises(ArtifactError, match="open"):
        run(source)


def test_source_change_after_reconstruction_rejected(source, monkeypatch):
    original = recovery.native

    def change(index, payload, *, build):
        result = original(index, payload, build=build)
        if build:
            (source[0] / "data/index/chroma.sqlite3").touch()
        return result

    monkeypatch.setattr(recovery, "native", change)
    with pytest.raises(ArtifactError, match="fingerprints"):
        run(source)
    assert not (source[0] / ".artifacts/recovery/v1").exists()


@pytest.mark.parametrize("change", ["vector", "metadata", "text", "files", "provenance"])
def test_existing_candidate_tampering_rejected(source, change):
    run(source)
    output = source[0] / ".artifacts/recovery/v1"
    if change == "provenance":
        path = output / "provenance.json"
        data = json.loads(path.read_bytes())
        data["embedding_model_identity"] = "verified"
        path.write_bytes(recovery.canonical(data))
    elif change == "files":
        (output / "chroma/chroma.sqlite3").unlink()
    else:
        with closing(sqlite3.connect(output / "chroma/chroma.sqlite3")) as db:
            if change == "vector":
                db.execute("UPDATE embeddings_queue SET vector=zeroblob(12)")
            elif change == "metadata":
                db.execute("UPDATE embedding_metadata SET int_value=99 WHERE key='page'")
            else:
                db.execute(
                    "UPDATE embedding_metadata SET string_value='other' WHERE key='chroma:document'"
                )
            db.commit()
    with pytest.raises(ArtifactError):
        run(source)


@pytest.mark.parametrize("mutation", ["nul", "pair", "offset", "length", "ordinary"])
def test_target_normalization_rejects_unreviewed_text(source, mutation):
    texts = {
        "nul": RAW[:100] + "\0" + RAW[101:],
        "pair": RAW[:100] + "\1" + RAW[101:],
        "offset": RAW.replace("\0", "x", 1)[:490] + "\0" + RAW[491:],
        "length": RAW + " ",
        "ordinary": "b" + RAW[1:],
    }
    with pytest.raises(ArtifactError, match="approved|Approved"):
        recovery.normalize(recovery.TARGET, texts[mutation])


def test_normalization_exact_positions_and_preserves_other_font_codes(source):
    assert recovery.normalize(recovery.TARGET, RAW) == CLEAN
    assert [i for i, (a, b) in enumerate(zip(RAW, CLEAN)) if a != b] == [491, 502]
    assert recovery.normalize("another", "known \1 \3 font codes") == "known \1 \3 font codes"
    with pytest.raises(ArtifactError, match="Unexpected NUL"):
        recovery.normalize("another", "unexpected \0")


def test_bad_native_vectors_are_rejected(source, tmp_path, monkeypatch):
    # Validation must remain active even when Python assertions are disabled.
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    data = recovery.extract(source[0] / "data/index")
    payload = tmp_path / "records.json"
    payload.write_bytes(recovery.canonical(data))
    index = tmp_path / "candidate"
    recovery.native(index, payload, build=True)
    data[0]["vector_hex"] = bytes(12).hex()
    payload.write_bytes(recovery.canonical(data))
    with pytest.raises(ArtifactError, match="native"):
        recovery.native(index, payload, build=False)


@pytest.mark.integration
def test_reviewed_real_source_extracts_without_mutation():
    project = Path(__file__).resolve().parents[1]
    reference = project / ".artifacts/source-inspection.json"
    assert artifacts.digest(reference.read_bytes()) == recovery.REFERENCE_SHA256
    inventory = json.loads(reference.read_bytes())["source_inventory"]
    recovery.assert_idle(project / "data/index")
    before = recovery.fingerprint(project, inventory)
    data = recovery.extract(project / "data/index")
    assert len(data) == 615
    assert (
        sum(r["original_text_sha256"] != artifacts.digest(r["document"].encode()) for r in data)
        == 1
    )
    assert recovery.fingerprint(project, inventory) == before


def test_local_export_preserves_unknown_model_and_readonly_sources(source, monkeypatch):
    from scripts import export_recovered_rag as exporter

    project = source[0]
    candidate = project / ".artifacts/recovery/veridex-rag-recovered-v1"
    run(source, destination=candidate)
    monkeypatch.setattr(
        exporter, "RECOVERY_SHA256", artifacts.digest((candidate / "provenance.json").read_bytes())
    )
    monkeypatch.setattr(exporter, "assert_idle", lambda index: None)
    before = artifacts.records(candidate, artifacts.tree(candidate))
    original = recovery.fingerprint(project, source[2])
    destination = project / ".artifacts/versions/local-v1"
    checksum = exporter.export(
        project=project, destination=destination, snapshot_version="local-v1", source_quiescent=True
    )
    metadata = artifacts.validate_bundle(
        destination,
        expected=SPEC,
        metadata_sha256=checksum,
        lock_file=project / "uv.lock",
        probe=True,
    )
    provenance = json.loads(metadata.embedding_model_provenance)
    assert metadata.spec.embedding_model == "unverified-legacy-model"
    assert "UNRESOLVED" in provenance["embedding_model_identity"]
    assert "BLOCKED" in provenance["distribution"]
    assert (
        provenance["recovered_files"]
        == json.loads((candidate / "provenance.json").read_bytes())["recovered_files"]
    )
    assert all(
        (destination / name).stat().st_mode & 0o222 == 0 for name in artifacts.tree(destination)
    )
    retained = artifacts.records(destination, artifacts.tree(destination))
    with pytest.raises(ArtifactError, match="already exists"):
        exporter.export(
            project=project,
            destination=destination,
            snapshot_version="local-v1",
            source_quiescent=True,
        )
    assert artifacts.records(destination, artifacts.tree(destination)) == retained
    assert artifacts.records(candidate, artifacts.tree(candidate)) == before
    assert recovery.fingerprint(project, source[2]) == original
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize(
    "failure", ["quiescence", "original-path", "missing-candidate", "modified-provenance"]
)
def test_local_export_rejects_unapproved_source_or_destination(source, monkeypatch, failure):
    from scripts import export_recovered_rag as exporter

    project = source[0]
    destination = project / ".artifacts/versions/local-v1"
    if failure == "original-path":
        destination = project / "data/index/export"
    if failure == "modified-provenance":
        candidate = project / ".artifacts/recovery/veridex-rag-recovered-v1"
        candidate.mkdir(parents=True)
        (candidate / "provenance.json").write_text("{}")

    def forbidden(**kwargs):
        pytest.fail("Rejected export must not invoke recovery/reconstruction")

    monkeypatch.setattr(recovery, "recover", forbidden)
    with pytest.raises((ArtifactError, FileNotFoundError)):
        exporter.export(
            project=project,
            destination=destination,
            snapshot_version="local-v1",
            source_quiescent=failure != "quiescence",
        )
    assert not destination.exists()
