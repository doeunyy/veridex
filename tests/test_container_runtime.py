"""Bootstrap checks are offline and preserve canonical artifacts."""

import shutil

import pytest
from test_rag_artifacts import SPEC
from test_rag_artifacts import seed as seed  # noqa: PLC0414 — shared offline Chroma fixture

from veridex.deployment import runtime
from veridex.rag.artifacts import ArtifactError, records, tree


@pytest.fixture
def bundle(seed, tmp_path, monkeypatch):
    root = tmp_path / "canonical"
    shutil.copytree(seed[1], root)
    monkeypatch.setattr(runtime, "BUNDLE_SHA256", seed[3])
    monkeypatch.setattr(runtime, "SPEC", SPEC)
    return root, seed[2], seed[3]


def test_prepare_private_copy_preserves_canonical(bundle, tmp_path):
    root, lock, checksum = bundle
    before = records(root, tree(root))
    mtimes = {name: (root / name).stat().st_mtime_ns for name in tree(root)}
    target = runtime.prepare(root=root, checksum=checksum, lock=lock, temporary=tmp_path)
    assert target != root / "chroma"
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert target.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in target.rglob("*") if path.is_file())
    assert records(target, tree(target)) == records(root / "chroma", tree(root / "chroma"))
    (target / "chroma.sqlite3").write_bytes(b"private changes")
    assert records(root, tree(root)) == before
    assert mtimes == {name: (root / name).stat().st_mtime_ns for name in tree(root)}


def test_unapproved_digest_rejected_before_copy(bundle, tmp_path):
    with pytest.raises(ArtifactError, match="approved"):
        runtime.prepare(root=bundle[0], checksum="0" * 64, lock=bundle[1], temporary=tmp_path)
    assert not list(tmp_path.glob("veridex-instance-*"))


@pytest.mark.parametrize("missing", ["manifest.json", "bundle.json", "chroma/chroma.sqlite3"])
def test_missing_artifact_never_creates_collection(bundle, tmp_path, missing):
    (bundle[0] / missing).unlink()
    with pytest.raises((ArtifactError, FileNotFoundError)):
        runtime.prepare(root=bundle[0], checksum=bundle[2], lock=bundle[1], temporary=tmp_path)
    assert not list(tmp_path.glob("veridex-instance-*"))


def test_modified_artifact_rejected(bundle, tmp_path):
    path = bundle[0] / "chroma/chroma.sqlite3"
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ArtifactError, match="checksum"):
        runtime.prepare(root=bundle[0], checksum=bundle[2], lock=bundle[1], temporary=tmp_path)
    assert not list(tmp_path.glob("veridex-instance-*"))


def test_symlink_index_rejected(bundle, tmp_path):
    path = bundle[0] / "chroma/chroma.sqlite3"
    saved = tmp_path / "outside.sqlite3"
    path.rename(saved)
    path.symlink_to(saved)
    with pytest.raises(ArtifactError, match="Symlink"):
        runtime.prepare(root=bundle[0], checksum=bundle[2], lock=bundle[1], temporary=tmp_path)


def test_lock_mismatch_rejected(bundle, tmp_path):
    lock = tmp_path / "wrong.lock"
    lock.write_text("wrong")
    with pytest.raises(ArtifactError, match="lockfile"):
        runtime.prepare(root=bundle[0], checksum=bundle[2], lock=lock, temporary=tmp_path)


def test_container_check_honors_environment_digest(monkeypatch, capsys):
    from scripts import check_container

    monkeypatch.setattr(check_container.platform, "system", lambda: "Linux")
    monkeypatch.setattr(check_container.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(check_container.sys, "argv", ["check_container.py"])
    monkeypatch.setenv("RAG_BUNDLE_SHA256", "0" * 64)
    received = []

    def audit(*, checksum):
        received.append(checksum)
        raise ArtifactError("digest rejected")

    monkeypatch.setattr(runtime, "audit", audit)
    assert check_container.main() == 1
    assert received == ["0" * 64]
    assert "verification failed" in capsys.readouterr().err
