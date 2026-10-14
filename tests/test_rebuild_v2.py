import json
from types import SimpleNamespace

import pytest

from veridex.rag.artifacts import ArtifactError
from veridex.rag.rebuild_v2 import DIMENSIONS, MODEL, execute_batches, frozen_inputs


def chunks(count=51, tokens=5):
    return [
        {
            "text": f"text {i}",
            "tokens": tokens,
            "metadata": {"chunk_id": f"paper_p1_c{i:05d}", "document_id": "paper", "page": 1},
        }
        for i in range(count)
    ]


class Client:
    def __init__(self, failure=None):
        self.embeddings = self
        self.calls = []
        self.failure = failure

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure == "exception":
            raise RuntimeError("secret credential/raw document/internal path")
        vectors = [
            SimpleNamespace(index=i, embedding=[0.25] * DIMENSIONS)
            for i in range(len(kwargs["input"]))
        ]
        if self.failure == "dimension":
            vectors[0].embedding.pop()
        elif self.failure == "nan":
            vectors[0].embedding[0] = float("nan")
        elif self.failure == "duplicate":
            vectors[-1].index = 0
        return SimpleNamespace(
            model="unexpected" if self.failure == "model" else MODEL,
            data=vectors,
            _request_id="test-request",
            usage=SimpleNamespace(prompt_tokens=250, total_tokens=250),
        )


def test_batches_record_usage_vectors_and_exact_request_contract(tmp_path):
    client = Client()
    directory = tmp_path / "run"
    rows = execute_batches(chunks(), directory, client)
    assert len(rows) == 51
    assert len(client.calls) == 2
    assert [len(c["input"]) for c in client.calls] == [50, 1]
    assert all(
        c["model"] == MODEL and c["dimensions"] == 1536 and c["encoding_format"] == "float"
        for c in client.calls
    )
    journal = json.loads((directory / "journal.json").read_text())
    assert journal["status"] == "complete"
    assert journal["actual_tokens"] == 500
    assert journal["usage_derived_usd"] == 0.00001
    assert journal["authorization"]["max_retries"] == 0
    assert journal["authorization"]["timeout_seconds"] == 30
    assert all(r["outcome"] == "success" for r in journal["requests"])
    assert all(len(bytes.fromhex(r["vector_hex"])) == 1536 * 4 for r in rows)
    with pytest.raises(FileExistsError):
        execute_batches(chunks(), directory, client)
    assert len(client.calls) == 2


@pytest.mark.parametrize("failure", ["exception", "dimension", "nan", "model", "duplicate"])
def test_failure_stops_no_retry_and_safe_journal(tmp_path, failure):
    client = Client(failure)
    directory = tmp_path / "run"
    with pytest.raises(ArtifactError, match="stopped without retry"):
        execute_batches(chunks(), directory, client)
    assert len(client.calls) == 1
    journal_bytes = (directory / "journal.json").read_bytes()
    assert b"secret credential" not in journal_bytes
    journal = json.loads(journal_bytes)
    assert journal["status"] == "failed-no-retry"
    assert len(journal["requests"]) == 1
    assert journal["requests"][0]["outcome"] == "failed"
    with pytest.raises(FileExistsError):
        execute_batches(chunks(), directory, client)
    assert len(client.calls) == 1


@pytest.mark.parametrize("records", [chunks(601), chunks(1, 3_000_000)])
def test_request_and_budget_bounds_before_api(tmp_path, records):
    client = Client()
    with pytest.raises(ArtifactError, match="authorization"):
        execute_batches(records, tmp_path / "run", client)
    assert client.calls == []
    assert not (tmp_path / "run").exists()


def test_preparation_fingerprint_required_before_paid_calls(tmp_path):
    (tmp_path / "preparation.json").write_text("{}")
    with pytest.raises(ArtifactError, match="fingerprint"):
        frozen_inputs(tmp_path, tmp_path / "lock")


def test_verified_vectors_complete_and_tampering_rejected(tmp_path):
    from veridex.rag.rebuild_v2 import verified_vectors

    records = chunks(586)
    (tmp_path / "chunks.json").write_text(json.dumps(records))
    rows = execute_batches(records, tmp_path / "embedding-run", Client())
    assert verified_vectors(tmp_path) == rows
    batch = tmp_path / "embedding-run/batch_01.json"
    batch.write_bytes(batch.read_bytes() + b" ")
    with pytest.raises(ArtifactError, match="batch changed"):
        verified_vectors(tmp_path)


@pytest.mark.parametrize("field", ["vector_hex", "vector_sha256", "document", "metadata", "id"])
def test_vector_and_metadata_integrity_beyond_file_checksum(tmp_path, field):
    from veridex.rag.artifacts import digest
    from veridex.rag.corpus_v2 import canonical
    from veridex.rag.rebuild_v2 import verified_vectors

    records = chunks(586)
    (tmp_path / "chunks.json").write_text(json.dumps(records))
    execute_batches(records, tmp_path / "embedding-run", Client())
    directory = tmp_path / "embedding-run"
    batch = json.loads((directory / "batch_01.json").read_bytes())
    if field == "metadata":
        batch[0][field]["page"] = 999
    else:
        batch[0][field] = "00" if field == "vector_hex" else "changed"
    payload = canonical(batch)
    (directory / "batch_01.json").write_bytes(payload)
    journal = json.loads((directory / "journal.json").read_bytes())
    journal["requests"][0]["batch_sha256"] = digest(payload)
    (directory / "journal.json").write_bytes(canonical(journal))
    with pytest.raises(ArtifactError, match="vector, text or metadata"):
        verified_vectors(tmp_path)


def test_native_filter_execution_and_report_use_same_terms(tmp_path, monkeypatch):
    import veridex.rag.rebuild_v2 as module

    def run(args, **kwargs):
        script = args[2]
        assert script.count(repr(module.FILTER_TERMS)) == 2
        assert "BERTd" not in script
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"text_filter_terms": module.FILTER_TERMS})
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    result = module.native_check(tmp_path, tmp_path / "vectors.json", build=False)
    assert result["text_filter_terms"] == module.FILTER_TERMS


def test_existing_bundle_not_overwritten(tmp_path):
    from veridex.rag.rebuild_v2 import build_and_export

    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "marker"
    marker.write_text("unchanged")
    with pytest.raises(ArtifactError, match="never overwrite"):
        build_and_export(tmp_path / "absent", destination, tmp_path / "uv.lock")
    assert marker.read_text() == "unchanged"


@pytest.mark.integration
def test_local_v2_bundle_native_integrity():
    from pathlib import Path

    from veridex.rag.artifacts import digest, validate_bundle
    from veridex.rag.rebuild_v2 import SPEC, verified_vectors

    root = Path(".artifacts/corpus/veridex-corpus-v2")
    bundle = Path(".artifacts/versions/veridex-rag-v2-local")
    if not (bundle / "bundle.json").is_file():
        pytest.skip("Completed local v2 bundle unavailable")
    metadata = validate_bundle(
        bundle,
        expected=SPEC,
        metadata_sha256=digest((bundle / "bundle.json").read_bytes()),
        lock_file=Path("uv.lock"),
        probe=True,
    )
    provenance = json.loads(metadata.embedding_model_provenance)
    rows = verified_vectors(root)
    assert len(rows) == 586
    assert provenance["embedding_run"]["actual_tokens"] == 164002
    assert provenance["embedding_run"]["authorization"]["dimensions"] == 1536
    assert all(r["model"] == MODEL for r in provenance["embedding_run"]["requests"])
    assert provenance["validation"]["self_queries"] == 586
    assert provenance["validation"]["text_filter_terms"] == [
        "RAG",
        "MixMHC2pred",
        "⟦U+0003⟧",
        "SELF",
    ]
    assert provenance["validation"]["fts5_integrity"] == "ok"
    assert set(provenance["vector_hashes"]) == {r["id"] for r in rows}
