"""Offline corpus preparation. This module never constructs a provider client."""

import json
import math
import unicodedata
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import tiktoken

from veridex.rag.artifacts import ArtifactError, digest, read_file, relative_path
from veridex.rag.chunking import chunk_documents
from veridex.rag.ingestion import load_corpus

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
BATCH_SIZE = 50
PRICE_PER_MILLION = 0.02
EXPECTED_IDS = {
    "rag_long_context_2024",
    "react_2022",
    "self_rag_2023",
    "netmhcpan_2020",
    "mixmhc2pred_2023",
}
DEPENDENCIES = (
    "pymupdf",
    "langchain-text-splitters",
    "langchain-core",
    "chromadb",
    "openai",
    "tiktoken",
)


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def escape_controls(text: str) -> tuple[str, list[dict]]:
    """Preserve unexpected controls as visible codepoint markers, never guess glyphs.

    Applied AFTER chunking: IDs and start_index still refer to unmodified extraction.
    Every changed codepoint/offset is retained for an auditable reverse transformation.
    Tabs/newlines/CR are accepted whitespace. Reject ambiguous pre-existing markers.
    """
    if "⟦U+" in text:
        raise ArtifactError("Text contains an ambiguous normalization marker.")
    changes = []
    result = []
    for offset, char in enumerate(text):
        if unicodedata.category(char) == "Cc" and char not in "\t\n\r":
            codepoint = f"U+{ord(char):04X}"
            changes.append({"offset": offset, "codepoint": codepoint})
            result.append(f"⟦{codepoint}⟧")
        else:
            result.append(char)
    return "".join(result), changes


def prepare(root: Path, lock_file: Path) -> dict:
    """Freeze validated source files, chunks and an exact offline token estimate.

    Existing output is verified byte-for-byte rather than overwritten. No index is
    created; a later approved run must pin preparation.json and all its file hashes.
    """
    manifest_bytes = read_file(root, "manifest.json")
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {"documents"}:
        raise ArtifactError("Unexpected manifest fields.")
    entries = manifest["documents"]
    ids = [entry["id"] for entry in entries]
    if len(ids) != 5 or set(ids) != EXPECTED_IDS:
        raise ArtifactError("Corpus v2 must have exactly the five approved IDs.")
    attribution_bytes = read_file(root, "attribution.json")
    attribution = json.loads(attribution_bytes)
    notices = attribution["documents"]
    if len(notices) != 5 or {entry["id"] for entry in notices} != EXPECTED_IDS:
        raise ArtifactError("Attribution IDs do not match Corpus v2.")
    by_id = {entry["id"]: entry for entry in notices}
    files = {"manifest.json": digest(manifest_bytes), "attribution.json": digest(attribution_bytes)}
    filenames = []
    for entry in entries:
        filename = relative_path(entry["filename"])
        if "/" in filename or not filename.endswith(".pdf"):
            raise ArtifactError("Invalid PDF filename.")
        notice = by_id[entry["id"]]
        if (
            notice["filename"] != filename
            or notice["title"] != entry["title"]
            or not notice.get("authors")
            or notice["license_id"] not in {"CC-BY-4.0", "CC-BY-NC-4.0"}
        ):
            raise ArtifactError("Invalid attribution or license metadata.")
        fingerprint = digest(read_file(root, f"papers/{filename}"))
        if fingerprint != notice["sha256"]:
            raise ArtifactError("PDF differs from the approved attribution fingerprint.")
        files[f"papers/{filename}"] = fingerprint
        filenames.append(filename)
    if len(set(filenames)) != 5 or {p.name for p in (root / "papers").iterdir()} != set(filenames):
        raise ArtifactError("PDF inventory does not match the manifest.")
    pages = load_corpus(root / "manifest.json", root / "papers")
    chunks = chunk_documents(pages, chunk_size=1000, chunk_overlap=200)
    if not chunks or len({d.metadata["chunk_id"] for d in chunks}) != len(chunks):
        raise ArtifactError("Empty corpus or duplicate chunk IDs.")
    tokenizer = tiktoken.get_encoding("cl100k_base")
    payload = []
    normalizations = []
    tokens = []
    for chunk in chunks:
        raw = chunk.page_content
        text, changes = escape_controls(raw)
        if changes:
            normalizations.append(
                {
                    "chunk_id": chunk.metadata["chunk_id"],
                    "raw_text_sha256": digest(raw.encode()),
                    "normalized_text_sha256": digest(text.encode()),
                    "changes": changes,
                }
            )
        count = len(tokenizer.encode(text, disallowed_special=()))
        if not count or count > 8192:
            raise ArtifactError("Chunk exceeds embedding input limits.")
        tokens.append(count)
        payload.append({"text": text, "metadata": chunk.metadata, "tokens": count})
    batch_tokens = [sum(tokens[i : i + BATCH_SIZE]) for i in range(0, len(tokens), BATCH_SIZE)]
    if max(batch_tokens) > 300000:
        raise ArtifactError("Embedding batch exceeds token limits.")
    generated = {"chunks.json": canonical(payload), "normalization.json": canonical(normalizations)}
    plan = {
        "format_version": 1,
        "corpus_version": "veridex-corpus-v2",
        "status": "prepared-offline-awaiting-paid-call-approval",
        "source_files": files,
        "lock_sha256": digest(lock_file.read_bytes()),
        "dependencies": {name: version(name) for name in DEPENDENCIES},
        "extraction": "existing load_corpus: PyMuPDF get_text('text').strip(), page order",
        "chunking": {"chunk_size": 1000, "chunk_overlap": 200, "add_start_index": True},
        "normalization": "after chunking: Cc except TAB/LF/CR to visible ⟦U+XXXX⟧; no guessed glyphs",
        "parsed_pages": len(pages),
        "chunk_count": len(payload),
        "chunks_per_document": dict(
            sorted(Counter(d.metadata["document_id"] for d in chunks).items())
        ),
        "generated_files": {name: digest(data) for name, data in generated.items()},
        "embedding_plan": {
            "model": MODEL,
            "dimensions": DIMENSIONS,
            "tokenizer": "cl100k_base",
            "tokens": sum(tokens),
            "largest_chunk_tokens": max(tokens),
            "batch_size": BATCH_SIZE,
            "request_count": math.ceil(len(tokens) / BATCH_SIZE),
            "batch_tokens": batch_tokens,
            "timeout_seconds": 30,
            "max_retries": 0,
            "price_usd_per_million_tokens": PRICE_PER_MILLION,
            "estimated_usd": sum(tokens) * PRICE_PER_MILLION / 1000000,
            "proposed_budget_usd": 0.05,
            "authorized_budget_usd": None,
            "paid_requests_executed": 0,
        },
    }
    for name, fingerprint in files.items():
        if digest(read_file(root, name)) != fingerprint:
            raise ArtifactError("Source changed during offline preparation.")
    generated["preparation.json"] = canonical(plan)
    # Verify all existing outputs before writing anything; reruns never overwrite.
    for name, data in generated.items():
        if (root / name).exists() and read_file(root, name) != data:
            raise ArtifactError("Existing preparation differs; choose a new version directory.")
    for name, data in generated.items():
        if not (root / name).exists():
            with (root / name).open("xb") as stream:
                stream.write(data)
    return plan
