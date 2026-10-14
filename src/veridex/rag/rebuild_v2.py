"""Explicitly authorized embedding execution and offline Corpus v2 reconstruction."""

import json
import math
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from veridex.rag.artifacts import (
    ArtifactError,
    ArtifactSpec,
    _check_index,
    digest,
    package_bundle,
    read_file,
    records,
    tree,
    validate_bundle,
)
from veridex.rag.corpus_v2 import (
    BATCH_SIZE,
    DIMENSIONS,
    EXPECTED_IDS,
    MODEL,
    PRICE_PER_MILLION,
    canonical,
    prepare,
)
from veridex.rag.recovery import NATIVE

PREPARATION_SHA256 = "64575a59e33c4df5f43e65975cd3b624b9e2cde0daa0ea543402085b8ba8df10"
MAX_REQUESTS = 12
BUDGET_USD = 0.05
SPEC = ArtifactSpec(
    embedding_model=MODEL,
    embedding_dimension=DIMENSIONS,
    chunk_count=586,
    document_ids=sorted(EXPECTED_IDS),
)
FILTER_TERMS = ["RAG", "MixMHC2pred", "⟦U+0003⟧", "SELF"]


def frozen_inputs(root: Path, lock_file: Path) -> tuple[dict, list[dict]]:
    if digest(read_file(root, "preparation.json")) != PREPARATION_SHA256:
        raise ArtifactError("Preparation differs from the approved fingerprint.")
    plan = prepare(root, lock_file)
    workflow = json.loads(read_file(root, "workflow.json"))
    if workflow["preparation_sha256"] != PREPARATION_SHA256 or any(
        digest(Path(name).read_bytes()) != fingerprint
        for name, fingerprint in workflow["code_files"].items()
    ):
        raise ArtifactError("Frozen preparation workflow changed.")
    if plan["chunk_count"] != 586 or plan["embedding_plan"]["tokens"] != 164002:
        raise ArtifactError("Inputs differ from the authorized request plan.")
    return plan, json.loads(read_file(root, "chunks.json"))


def save_journal(directory: Path, journal: dict):
    temporary = directory / "journal.tmp"
    with temporary.open("xb") as stream:
        os.chmod(temporary, 0o600)
        stream.write(canonical(journal))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(directory / "journal.json")


def execute_batches(chunks: list[dict], directory: Path, client) -> list[dict]:
    """No retries/resume: existing journal or any failed attempt stops the run.

    The directory is created exclusively before any network request. Attempts are
    journaled before sending, so rerunning after a crash cannot repeat a paid call.
    """
    if not chunks or math.ceil(len(chunks) / BATCH_SIZE) > MAX_REQUESTS:
        raise ArtifactError("Embedding request count exceeds authorization.")
    estimate = sum(row["tokens"] for row in chunks) * PRICE_PER_MILLION / 1_000_000
    if estimate > BUDGET_USD:
        raise ArtifactError("Embedding estimate exceeds authorization.")
    directory.mkdir(mode=0o700)  # Existing output is a hard stop, even after failure.
    journal = {
        "status": "running",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "preparation_sha256": PREPARATION_SHA256,
        "executor_sha256": digest(Path(__file__).read_bytes()),
        "openai_sdk_version": version("openai"),
        "authorization": {
            "model": MODEL,
            "dimensions": DIMENSIONS,
            "maximum_requests": MAX_REQUESTS,
            "maximum_usd": BUDGET_USD,
            "timeout_seconds": 30,
            "max_retries": 0,
            "price_usd_per_million_tokens": PRICE_PER_MILLION,
        },
        "actual_tokens": 0,
        "usage_derived_usd": 0,
        "requests": [],
    }
    save_journal(directory, journal)
    output = []
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        tokens = sum(row["tokens"] for row in batch)
        if journal["usage_derived_usd"] + tokens * PRICE_PER_MILLION / 1_000_000 > BUDGET_USD:
            journal["status"] = "stopped-budget"
            save_journal(directory, journal)
            raise ArtifactError("Remaining embedding budget is insufficient.")
        record = {
            "attempt": len(journal["requests"]) + 1,
            "chunk_start": start,
            "chunk_count": len(batch),
            "estimated_tokens": tokens,
            "outcome": "attempted",
            "started_at_utc": datetime.now(UTC).isoformat(),
        }
        journal["requests"].append(record)
        save_journal(directory, journal)
        started = time.monotonic()
        try:
            response = client.embeddings.create(
                model=MODEL,
                dimensions=DIMENSIONS,
                input=[row["text"] for row in batch],
                encoding_format="float",
            )
            record["model"] = response.model
            record["request_id"] = getattr(response, "_request_id", None)
            record["actual_prompt_tokens"] = response.usage.prompt_tokens
            record["actual_total_tokens"] = response.usage.total_tokens
            journal["actual_tokens"] += response.usage.total_tokens
            journal["usage_derived_usd"] = journal["actual_tokens"] * PRICE_PER_MILLION / 1_000_000
            if (
                response.model != MODEL
                or response.usage.total_tokens < 0
                or journal["usage_derived_usd"] > BUDGET_USD
                or len(response.data) != len(batch)
                or sorted(item.index for item in response.data) != list(range(len(batch)))
            ):
                raise ArtifactError("Provider response differs from the approved plan.")
            rows = []
            for chunk, item in zip(batch, sorted(response.data, key=lambda item: item.index)):
                if len(item.embedding) != DIMENSIONS or not all(
                    math.isfinite(v) for v in item.embedding
                ):
                    raise ArtifactError("Invalid provider vector.")
                vector = struct.pack(f"<{DIMENSIONS}f", *item.embedding)
                if not all(math.isfinite(v) for v in struct.unpack(f"<{DIMENSIONS}f", vector)):
                    raise ArtifactError("Invalid FLOAT32 conversion.")
                rows.append(
                    {
                        "id": chunk["metadata"]["chunk_id"],
                        "document": chunk["text"],
                        "metadata": chunk["metadata"],
                        "vector_hex": vector.hex(),
                        "vector_sha256": digest(vector),
                    }
                )
            payload = canonical(rows)
            name = f"batch_{record['attempt']:02d}.json"
            with (directory / name).open("xb") as stream:
                stream.write(payload)
            record["batch_file"] = name
            record["batch_sha256"] = digest(payload)
            record["outcome"] = "success"
            output.extend(rows)
        except Exception as exc:  # noqa: BLE001 — journal safely and stop; never log bodies
            # Never log exception messages, response bodies, keys or provider traces.
            record["outcome"] = "failed"
            record["error_type"] = type(exc).__name__
            record["http_status"] = getattr(exc, "status_code", None)
            record["seconds"] = round(time.monotonic() - started, 3)
            journal["status"] = "failed-no-retry"
            save_journal(directory, journal)
            raise ArtifactError("Embedding request failed; run stopped without retry.") from None
        record["seconds"] = round(time.monotonic() - started, 3)
        save_journal(directory, journal)
        print(
            f"Embedding request {record['attempt']}: success, {record['actual_total_tokens']} tokens",
            flush=True,
        )
    journal["status"] = "complete"
    journal["completed_at_utc"] = datetime.now(UTC).isoformat()
    journal["vectors_float32_sha256"] = digest(
        b"".join(bytes.fromhex(row["vector_hex"]) for row in output)
    )
    save_journal(directory, journal)
    return output


def verified_vectors(root: Path) -> list[dict]:
    journal = json.loads(read_file(root / "embedding-run", "journal.json"))
    if (
        journal["status"] != "complete"
        or journal["preparation_sha256"] != PREPARATION_SHA256
        or len(journal["requests"]) != MAX_REQUESTS
        or journal["usage_derived_usd"] > BUDGET_USD
        or any(r["outcome"] != "success" or r["model"] != MODEL for r in journal["requests"])
    ):
        raise ArtifactError("Embedding run is incomplete or outside authorization.")
    chunks = json.loads(read_file(root, "chunks.json"))
    rows = []
    for request in journal["requests"]:
        payload = read_file(root / "embedding-run", request["batch_file"])
        if digest(payload) != request["batch_sha256"]:
            raise ArtifactError("Recorded embedding batch changed.")
        rows.extend(json.loads(payload))
    if len(rows) != len(chunks):
        raise ArtifactError("Embedding coverage differs from prepared chunks.")
    for row, chunk in zip(rows, chunks):
        vector = bytes.fromhex(row["vector_hex"])
        if (
            len(vector) != DIMENSIONS * 4
            or digest(vector) != row["vector_sha256"]
            or row["metadata"] != chunk["metadata"]
            or row["id"] != chunk["metadata"]["chunk_id"]
            or row["document"] != chunk["text"]
            or not all(math.isfinite(v) for v in struct.unpack(f"<{DIMENSIONS}f", vector))
        ):
            raise ArtifactError("Stored vector, text or metadata differs from provenance.")
    if (
        digest(b"".join(bytes.fromhex(row["vector_hex"]) for row in rows))
        != journal["vectors_float32_sha256"]
    ):
        raise ArtifactError("Aggregate vector fingerprint mismatch.")
    return rows


def native_check(index: Path, payload: Path, *, build: bool) -> dict:
    script = NATIVE.replace("['BERTd', 'd(z)', 'q(x)']", repr(FILTER_TERMS)).replace(
        "['BERTd','d(z)','q(x)']", repr(FILTER_TERMS)
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(index), str(payload), "build" if build else "audit"],
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise ArtifactError("Offline Chroma build or native retrieval verification failed.")
    return json.loads(result.stdout)


def build_and_export(root: Path, destination: Path, lock_file: Path, *, build: bool = True) -> dict:
    if destination.exists() or destination.is_symlink():
        raise ArtifactError("Bundle destination already exists; never overwrite.")
    frozen_inputs(root, lock_file)
    rows = verified_vectors(root)
    payload = root / "vectors.json"
    encoded = canonical(rows)
    if payload.exists():
        if read_file(root, payload.name) != encoded:
            raise ArtifactError("Existing vector payload differs; never overwrite.")
    else:
        with payload.open("xb") as stream:
            stream.write(encoded)
    index = root / "chroma"
    if build:
        if index.exists() or index.is_symlink():
            raise ArtifactError("V2 index already exists; never rebuild or overwrite.")
        native_check(index, payload, build=True)  # Worker exits before snapshot operations.
    elif index.is_symlink() or not index.is_dir():
        raise ArtifactError("Existing closed v2 index is required for offline export.")
    _check_index(index, SPEC)
    before = records(index, tree(index))
    with tempfile.TemporaryDirectory() as temporary:
        probe = Path(temporary) / "chroma"
        shutil.copytree(index, probe)
        checks = native_check(probe, payload, build=False)
        _check_index(probe, SPEC)
        with closing(sqlite3.connect(probe / "chroma.sqlite3")) as db:
            db.execute(
                "INSERT INTO embedding_fulltext_search(embedding_fulltext_search,rank) "
                "VALUES('integrity-check',1)"
            )
            db.rollback()
        checks["sqlite_integrity"] = "ok"
        checks["fts5_integrity"] = "ok"
    if records(index, tree(index)) != before:
        raise ArtifactError("Canonical v2 index changed during verification.")
    provenance = {
        "corpus_version": "veridex-corpus-v2",
        "preparation_sha256": PREPARATION_SHA256,
        "preparation": json.loads(read_file(root, "preparation.json")),
        "embedding_run": json.loads(read_file(root / "embedding-run", "journal.json")),
        "vectors_json_sha256": digest(encoded),
        "vector_hashes": {row["id"]: row["vector_sha256"] for row in rows},
        "attribution": json.loads(read_file(root, "attribution.json")),
        "license_links": {
            "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
            "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
        },
        "distribution": "local-only; no remote publication authorization; noncommercial coursework",
        "validation": checks,
    }
    checksum = package_bundle(
        manifest=root / "manifest.json",
        papers=root / "papers",
        index=index,
        destination=destination,
        snapshot_version="veridex-rag-v2-local",
        lock_file=lock_file,
        expected=SPEC,
        source_quiescent=True,
        embedding_model_provenance=canonical(provenance).decode(),
    )
    validate_bundle(
        destination, expected=SPEC, metadata_sha256=checksum, lock_file=lock_file, probe=True
    )
    if records(index, tree(index)) != before:
        raise ArtifactError("Canonical v2 index changed during export.")
    report = {**checks, "bundle_json_sha256": checksum, "bundle": str(destination)}
    with (root / "validation.json").open("xb") as stream:
        stream.write(canonical(report))
    return report
