# Versioned RAG deployment artifacts

Use an image-bundled, immutable versioned snapshot for this approximately 24 MiB
corpus. The bundle directory contains `manifest.json`, exactly the manifest's
approved PDFs in `papers/`, the complete supported Chroma persistence directory
in `chroma/`, and deterministic `bundle.json` metadata. Do not run ingestion,
rebuild an index, or create a missing collection at startup.

## Original index remains nondeployable; recovered local candidate available

Read-only inspection on 2026-10-10 found five papers, 615 chunks, dimension 1536,
and collection `veridex_documents`. Both Python SQLite `integrity_check` and
`quick_check` report a malformed FTS5 inverted index. One stored chunk contains
NUL text, consistent with the Chroma 1.5.9 issue linked below; causation has not
been independently proven. Export must fail closed. No validated deployment
bundle may be published from this source until a separately authorized recovery
produces a clean index. Neither this workflow nor the application repairs it.

The legacy index stores no verifiable embedding model identity. The configured
model is `text-embedding-3-small`; dimension 1536 alone does not prove that model.
The standard exporter records model identity as operator-attested, requiring ingestion provenance.
The recovered local exporter instead uses `unverified-legacy-model` and explicitly
records unresolved identity; this is not a model attestation.
The validator compares it to an independent expected specification. Checksums are
integrity checks, not signatures: pin the printed `bundle.json` SHA-256 outside the
bundle, and restrict who can publish it.

## Controlled export

Stop the API, CLI readers, ingestion jobs, and any other Chroma users. Keep them
stopped throughout export. `--source-quiescent` is an operator attestation, not an
automatic lock. The exporter checks `lsof` before and after copying, checks source
hashes/identity/mtime and inventory before/after, and rejects SQLite WAL/SHM/journal
sidecars. No new reader/writer may start during the operation. On Linux install
`lsof` on the export host; the runtime validator does not need it. The library's
audit bypass is only for controlled tests/offline environments, not live exports.

SQLite backup alone does not coordinate with HNSW files. This workflow intentionally
uses a stopped-source whole-directory copy, never a live database backup plus a
separate uncoordinated index copy. Copies are staged beside the destination,
validated, queried offline in a fresh process on a disposable writable copy, then
renamed into place. Existing versions are never overwritten. Failed staging is
removed; the source is never written. Copies use fixed permissions and file mtimes,
sorted inventory, and canonical JSON; repeated exports of the same source/version
and environment produce identical bytes. Native Chroma files themselves are not
recreated, so independently rebuilt indexes need not be byte-identical.

The approved recovery is now exported through a separate local-only command. It
requires the existing recovered candidate, pins its provenance digest, revalidates
all preserved vectors/text/metadata, and never falls back to rebuilding an index:

```sh
.venv/bin/python scripts/export_recovered_rag.py \
  .artifacts/versions/veridex-rag-v1-local \
  --snapshot-version veridex-rag-v1-local --source-quiescent
.venv/bin/python scripts/package_rag.py validate \
  .artifacts/versions/veridex-rag-v1-local \
  --embedding-model unverified-legacy-model \
  --metadata-sha256 6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8 \
  --runtime-probe
```

The unchanged format-version-1 metadata has no new fields. Its existing
`embedding_model_provenance` string contains canonical JSON with the unresolved
model status, reviewed recovery/source digests, source fingerprints, approved
normalization, recovered inventory, per-document rights review, local/internal
restriction, and unverified Linux status. This preserves the validation contract.
The final bundle contains only eleven approved payload files and `bundle.json`.
Re-running export rejects an existing destination without altering it.

V1 intentionally supports Chroma 1.5.9's observed Rust layout: SQLite plus four
binary files per vector segment, and a complete FLOAT32 replay log covering every
chunk. The supplied index has an allocated but empty persisted HNSW graph, so
retaining all 615 queued vectors is essential. A purged log, another storage
version, Python pickle metadata, or unrelated files are rejected, not silently
treated as compatible. Future layouts require an explicit validator revision.

Validation checks full SQLite integrity (including FTS5), checksums, sizes, exact
inventory, safe paths/regular files, PDFs, manifest membership, collection identity,
chunk count and metadata, paper-ID/filename mapping, vector dimensions and replay
coverage, HNSW layout/lengths, dependency versions, and the lockfile digest. The
optional native probe uses `get_collection`, never `get_or_create_collection`, and
supplies stored numeric embeddings, so it makes no embedding/provider calls.
Missing or invalid artifacts must prevent readiness in Step 4.5; FastAPI readiness
integration is intentionally deferred here.

## Docker handoff, Linux compatibility, and permissions

`.artifacts/` and `.docker-artifacts/` are Git-ignored and Docker-ignored. All raw
`data/` is Docker-ignored; secrets, Git history, private notes, and caches remain
excluded. Step 4.5 should pass one validated version as a **named Docker build
context** (for example `--build-context rag=/absolute/path/to/validated/version`)
and explicitly copy from that context. Do not relax the main-context exclusions
or use a broad repository/data copy. Validate the pinned metadata digest and exact
inventory before handing the directory to Docker; named contexts are separate
inputs and must not be assumed protected by the main `.dockerignore`.

Mount/package PDFs, manifest, and canonical metadata read-only. Chroma may write
during initialization and replay: copy only `chroma/` into an instance-local writable
directory before opening it. Never open the canonical bundle through Chroma APIs.
Use absolute configured paths. Preserve Evidence paper IDs (for example `rag_2020`)
and Workspace filenames (`rag_2020.pdf`) as separate identifiers.

SQLite is portable, but macOS/arm64 export does not certify Linux/amd64 HNSW/Rust
compatibility. V1 checks the observed 64-bit little-endian format, records exporter
platform and installed dependencies, and pins `uv.lock`. Install Linux dependencies
from the lock instead of copying `.venv`. Repeat strict validation plus the offline
native query probe on a disposable copy under Linux/amd64 before readiness or
release. No Linux certification or Docker build has been performed in Step 4.4.
The validator requires the Python SQLite driver to be at least 3.44: older
`PRAGMA integrity_check` implementations do not check FTS5 virtual-table content.
Verify that version on the selected Linux base; do not treat an older driver's
`ok` result as sufficient evidence of integrity.

## Redistribution decision

Public access to a PDF is not permission to redistribute it in an image. Record the
license/permission for each of the five actual PDF files, including the three arXiv
papers, the PMC-hosted NetMHCpan paper, and the ScienceDirect-hosted MixMHC2pred
paper. Publisher/repository hosting and metadata URLs alone are insufficient.
Keep any authorized private bundle/image in restricted storage. Public image
publication or distribution to other users requires an explicit approved rights
review; this step grants or assumes no redistribution rights.

References:
- https://github.com/chroma-core/chroma/issues/7388
- https://cookbook.chromadb.dev/core/storage-layout/
- https://sqlite.org/releaselog/3_44_0.html

## Step 4.5 exact local build handoff

Once Step 4.5 provides a Dockerfile, first run the validation command above, then
use a local Docker builder (do not send this restricted context to a remote builder):

```sh
docker buildx build --platform linux/amd64 \
  --build-context "rag=$PWD/.artifacts/versions/veridex-rag-v1-local" \
  --build-arg RAG_BUNDLE_SHA256=6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8 \
  --load --tag veridex:phase04-local .
```

The future Dockerfile should consume `ARG RAG_BUNDLE_SHA256`, copy explicitly
from named context `rag` (for example `COPY --from=rag / /opt/veridex/rag/`),
and validate that digest/spec before use. This is a handoff plan, not an implemented
Dockerfile or build. Keep all main-context exclusions unchanged. The canonical
corpus stays read-only; only an instance-local Chroma copy is writable. Repeat
SQLite/FTS5 integrity, native filtering, vector preservation and retrieval checks
in Linux/amd64. `--platform` alone does not prove native compatibility.

See [the distribution review](rag_distribution_review.md). Remote image publication
is blocked pending authorization, even to a private registry. No Linux container,
Docker image, registry upload, or cloud deployment has been performed here.
