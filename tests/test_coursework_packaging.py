"""Synthetic in-memory archive plans; no ZIP is generated and no real corpus is required."""

import hashlib
import json
from pathlib import Path

import pytest

from veridex import submission as packaging
from veridex.rag.artifacts import ArtifactError


@pytest.fixture
def source():
    return {name: b"safe source" for name in packaging.REQUIRED} | {
        "CORPUS_LICENSE_NOTICE.md": b"noncommercial notice",
        "uv.lock": b"locked versions",
    }


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    files = {name: b"synthetic corpus" for name in packaging.BUNDLE_FILES - {"bundle.json"}}
    metadata = {
        "lock_sha256": hashlib.sha256(b"locked versions").hexdigest(),
        "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }
    files["bundle.json"] = json.dumps(metadata).encode()
    for name, data in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    monkeypatch.setattr(
        packaging, "BUNDLE_SHA256", hashlib.sha256(files["bundle.json"]).hexdigest()
    )
    calls = []

    def validate(path, **kwargs):
        calls.append((path, kwargs))

    monkeypatch.setattr(packaging, "validate_bundle", validate)
    return root, calls


def plan(source, root=None, mode="coursework"):
    return packaging.plan_archive(
        source, commit="approved", timestamp=1791936000, mode=mode, bundle=root
    )


def test_exact_twelve_file_coursework_plan_and_validator_boundary(source, bundle):
    root, calls = bundle
    result = plan(source, root)
    extras = set(result.files) - set(source)
    assert len(extras) == 12
    assert extras == {f"{packaging.PREFIX}/{name}" for name in packaging.BUNDLE_FILES}
    assert calls == [
        (
            root,
            {
                "expected": packaging.SPEC,
                "metadata_sha256": packaging.BUNDLE_SHA256,
                "probe": False,
            },
        )
    ]
    assert result.files["README.md"] == source["README.md"]
    assert all(
        result.files[f"{packaging.PREFIX}/{name}"] == (root / name).read_bytes()
        for name in packaging.BUNDLE_FILES
    )
    assert all(
        not Path(name).is_absolute() and ".." not in Path(name).parts for name in result.files
    )
    assert f"{packaging.PREFIX}/manifest.json" in result.files
    assert f"{packaging.PREFIX}/chroma/chroma.sqlite3" in result.files


def test_source_only_plan_never_reads_corpus(source, monkeypatch):
    monkeypatch.setattr(packaging, "validate_bundle", lambda *a, **kw: pytest.fail("Corpus read"))
    assert plan(source, mode="source-only").files == source
    with pytest.raises(ArtifactError):
        plan(source, Path("not-present"), "source-only")


@pytest.mark.parametrize("failure", ["missing", "changed", "extra", "fingerprint", "symlink"])
def test_bad_bundle_rejected_without_output(source, bundle, failure):
    root, _ = bundle
    p = root / "manifest.json"
    if failure == "missing":
        p.unlink()
    elif failure == "changed":
        p.write_bytes(b"altered")
    elif failure == "extra":
        (root / ".env").write_text("unapproved")
    elif failure == "fingerprint":
        (root / "bundle.json").write_text("{}")
    else:
        p.unlink()
        p.symlink_to(root / "bundle.json")
    with pytest.raises(ArtifactError):
        plan(source, root)
    assert not list(root.parent.rglob("*.zip"))


def test_existing_artifact_validator_failure_is_not_bypassed(source, bundle, monkeypatch):
    root, _ = bundle

    def reject(*args, **kwargs):
        raise ArtifactError("invalid index")

    monkeypatch.setattr(packaging, "validate_bundle", reject)
    with pytest.raises(ArtifactError):
        plan(source, root)


def test_source_drift_during_validation_rejected(source, bundle, monkeypatch):
    root, _ = bundle
    monkeypatch.setattr(
        packaging,
        "validate_bundle",
        lambda *a, **kw: (root / "manifest.json").write_bytes(b"changed during validation"),
    )
    with pytest.raises(ArtifactError):
        plan(source, root)


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".git/config",
        ".venv/bin/python",
        "data/papers/paper.pdf",
        "data/index/chroma.sqlite3",
        "../README.md",
        "submission_artifacts/other.pdf",
        ".artifacts/private.json",
        "docs/credentials.json",
    ],
)
def test_general_exclusions_still_reject_sensitive_paths(source, name):
    with pytest.raises(ArtifactError):
        plan(source | {name: b"unsafe"}, mode="source-only")


def test_credentials_missing_notice_and_wrong_lock_rejected(source, bundle):
    root, _ = bundle
    with pytest.raises(ArtifactError):
        plan(source | {"README.md": ("sk-" + "Z" * 40).encode()}, mode="source-only")
    with pytest.raises(ArtifactError):
        plan({k: v for k, v in source.items() if k != "CORPUS_LICENSE_NOTICE.md"}, root)
    with pytest.raises(ArtifactError):
        plan(source | {"uv.lock": b"different"}, root)


def test_notice_and_named_context_recipe_are_shipped():
    root = Path(__file__).resolve().parents[1]
    notice = (root / "CORPUS_LICENSE_NOTICE.md").read_text()
    for identifier in packaging.SPEC.document_ids:
        assert identifier in (root / "docs/rag_attribution_v2.json").read_text()
    assert notice.count("## ") == 6
    assert "CC-BY-NC" in notice and "unverified" in notice
    readme = (root / "README.md").read_text()
    assert 'RAG_BUNDLE_DIR="$PWD/submission_artifacts/veridex-rag-v2-local"' in readme
    assert '--build-context "rag=$RAG_BUNDLE_DIR"' in readme
    assert "--env-file .env" in readme
    assert "/submission_artifacts/" in (root / ".gitignore").read_text()
    assert "/submission_artifacts/" in (root / ".dockerignore").read_text()


def test_existing_output_is_never_overwritten(source, tmp_path):
    output = tmp_path / "existing.zip"
    output.write_bytes(b"existing archive sentinel")
    with pytest.raises(ArtifactError):
        packaging.write_archive(plan(source, mode="source-only"), output)
    assert output.read_bytes() == b"existing archive sentinel"


def test_mutated_plan_paths_are_rejected_before_writer(source, tmp_path):
    result = plan(source, mode="source-only")
    result.files["../unsafe"] = b"unsafe"
    with pytest.raises(ArtifactError):
        packaging.write_archive(result, tmp_path / "never-created.zip")
    assert not (tmp_path / "never-created.zip").exists()


def test_plan_can_be_materialized_at_an_unrelated_extraction_root(source, bundle, tmp_path):
    original, _ = bundle
    result = plan(source, original)
    extracted = tmp_path / "another-machine" / "assignment"
    for name, content in result.files.items():
        p = extracted / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    moved = extracted / packaging.PREFIX
    rebuilt = plan({name: (extracted / name).read_bytes() for name in source}, moved)
    assert rebuilt.files == result.files
    assert (moved / "manifest.json").is_file()
    assert (moved / "chroma/chroma.sqlite3").is_file()
    assert (extracted / "README.md").is_file()
    assert (extracted / "PROCESS_LOG.md").is_file()
    assert not list(extracted.rglob("*.zip"))


def test_source_only_original_tree_does_not_require_coursework_notice(source):
    original_source = {k: v for k, v in source.items() if k != "CORPUS_LICENSE_NOTICE.md"}
    assert plan(original_source, mode="source-only").files == original_source


@pytest.mark.parametrize(
    "name",
    [
        "src/node_modules/x.py",
        "scripts/__pycache__/x.py",
        "src/build/output.py",
        "tests/.venv/x.py",
    ],
)
def test_nested_generated_directories_remain_excluded(source, name):
    with pytest.raises(ArtifactError):
        plan(source | {name: b"generated"}, mode="source-only")


def test_unexpected_file_added_during_validation_is_rejected(source, bundle, monkeypatch):
    root, _ = bundle
    monkeypatch.setattr(
        packaging,
        "validate_bundle",
        lambda *a, **kw: (root / "unapproved.txt").write_text("unapproved"),
    )
    with pytest.raises(ArtifactError):
        plan(source, root)
