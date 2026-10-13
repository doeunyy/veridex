import hashlib
import json

import pymupdf
import pytest

from veridex.rag.artifacts import ArtifactError
from veridex.rag.corpus_v2 import EXPECTED_IDS, escape_controls, prepare


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    (root / "papers").mkdir(parents=True)
    entries, notices = [], []
    for identifier in sorted(EXPECTED_IDS):
        entry = {
            "id": identifier,
            "filename": identifier + ".pdf",
            "title": identifier,
            "domain": "test",
            "year": 2024,
            "source_url": "https://example.com/paper",
        }
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "A synthetic paper for offline testing.")
        data = doc.tobytes()
        doc.close()
        (root / "papers" / entry["filename"]).write_bytes(data)
        entries.append(entry)
        notices.append(
            {
                **entry,
                "authors": ["Test Author"],
                "license_id": "CC-BY-4.0",
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    (root / "manifest.json").write_text(json.dumps({"documents": entries}))
    (root / "attribution.json").write_text(json.dumps({"documents": notices}))
    lock = tmp_path / "uv.lock"
    lock.write_text("test lock")
    return root, lock


def test_prepare_provenance_and_idempotence(corpus):
    root, lock = corpus
    first = prepare(root, lock)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert prepare(root, lock) == first
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert first["embedding_plan"]["model"] == "text-embedding-3-small"
    assert first["embedding_plan"]["dimensions"] == 1536
    assert first["embedding_plan"]["paid_requests_executed"] == 0
    assert first["embedding_plan"]["authorized_budget_usd"] is None
    assert first["embedding_plan"]["max_retries"] == 0
    assert first["chunk_count"] == 5
    assert set(first["chunks_per_document"]) == EXPECTED_IDS
    assert first["lock_sha256"] == hashlib.sha256(lock.read_bytes()).hexdigest()
    for name, fingerprint in first["generated_files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == fingerprint
    assert not (root / "chroma").exists()


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x0b", "\x7f", "\x85"])
def test_control_escape_is_explicit_and_auditable(control):
    result, changes = escape_controls("a" + control + "b\t\n\r")
    assert result == f"a⟦U+{ord(control):04X}⟧b\t\n\r"
    assert changes == [{"offset": 1, "codepoint": f"U+{ord(control):04X}"}]
    assert control not in result


def test_normal_text_unchanged_and_ambiguous_marker_rejected():
    assert escape_controls("ordinary (text)\t\n\r") == ("ordinary (text)\t\n\r", [])
    with pytest.raises(ArtifactError, match="ambiguous"):
        escape_controls("a⟦U+0000⟧")


@pytest.mark.parametrize("failure", ["missing", "corrupt", "extra", "symlink"])
def test_source_inventory_rejection(corpus, failure):
    root, lock = corpus
    pdf = next((root / "papers").iterdir())
    if failure == "missing":
        pdf.unlink()
    elif failure == "corrupt":
        pdf.write_bytes(b"changed")
    elif failure == "extra":
        (root / "papers" / "extra.pdf").write_bytes(b"pdf")
    else:
        data = pdf.read_bytes()
        pdf.unlink()
        target = root / "external.pdf"
        target.write_bytes(data)
        pdf.symlink_to(target)
    with pytest.raises((ArtifactError, OSError)):
        prepare(root, lock)
    assert not (root / "preparation.json").exists()


@pytest.mark.parametrize("failure", ["legacy_id", "duplicate_id", "license", "authors", "title"])
def test_manifest_and_license_consistency(corpus, failure):
    root, lock = corpus
    m = json.loads((root / "manifest.json").read_text())
    a = json.loads((root / "attribution.json").read_text())
    if failure == "legacy_id":
        m["documents"][0]["id"] = "rag_2020"
    elif failure == "duplicate_id":
        m["documents"][0]["id"] = m["documents"][1]["id"]
    elif failure == "license":
        a["documents"][0]["license_id"] = "UNVERIFIED"
    elif failure == "authors":
        a["documents"][0]["authors"] = []
    else:
        a["documents"][0]["title"] = "different"
    (root / "manifest.json").write_text(json.dumps(m))
    (root / "attribution.json").write_text(json.dumps(a))
    with pytest.raises(ArtifactError):
        prepare(root, lock)


def test_changed_output_not_overwritten(corpus):
    root, lock = corpus
    prepare(root, lock)
    (root / "chunks.json").write_bytes(b"corrupt")
    with pytest.raises(ArtifactError, match="differs"):
        prepare(root, lock)
    assert (root / "chunks.json").read_bytes() == b"corrupt"


@pytest.mark.integration
def test_local_v2_preparation_offline():
    from pathlib import Path

    root = Path(".artifacts/corpus/veridex-corpus-v2")
    if not root.exists():
        pytest.skip("Local Corpus v2 not prepared")
    plan = prepare(root, Path("uv.lock"))
    assert plan["chunk_count"] == 586
    assert plan["embedding_plan"]["tokens"] == 164002
    chunks = json.loads((root / "chunks.json").read_text())
    assert len(chunks) == plan["chunk_count"]
    assert {d["metadata"]["document_id"] for d in chunks} == EXPECTED_IDS
    assert all(d["metadata"]["page"] > 0 for d in chunks)
    assert len({d["metadata"]["chunk_id"] for d in chunks}) == len(chunks)
    assert all(escape_controls(d["text"])[1] == [] for d in chunks if "⟦U+" not in d["text"])
    for record in json.loads((root / "normalization.json").read_text()):
        text = next(d["text"] for d in chunks if d["metadata"]["chunk_id"] == record["chunk_id"])
        assert hashlib.sha256(text.encode()).hexdigest() == record["normalized_text_sha256"]
        # Reverse from original offsets; adjust for marker expansion on each substitution.
        shift = 0
        for change in record["changes"]:
            offset = change["offset"] + shift
            marker = "⟦" + change["codepoint"] + "⟧"
            assert text[offset : offset + len(marker)] == marker
            shift += len(marker) - 1
        for change in reversed(record["changes"]):
            marker = "⟦" + change["codepoint"] + "⟧"
            # Every marker has the same width for C0/C1 controls.
            offset = change["offset"] + (len(marker) - 1) * record["changes"].index(change)
            text = (
                text[:offset]
                + chr(int(change["codepoint"].replace("U+", "0x"), 0))
                + text[offset + len(marker) :]
            )
        assert hashlib.sha256(text.encode()).hexdigest() == record["raw_text_sha256"]


def test_source_change_during_extraction_is_rejected(corpus, monkeypatch):
    import veridex.rag.corpus_v2 as module

    root, lock = corpus
    original = module.load_corpus

    def changing_source(manifest, papers):
        pages = original(manifest, papers)
        next(papers.iterdir()).write_bytes(b"changed during extraction")
        return pages

    monkeypatch.setattr(module, "load_corpus", changing_source)
    with pytest.raises(ArtifactError, match="Source changed"):
        prepare(root, lock)
    assert not (root / "preparation.json").exists()
