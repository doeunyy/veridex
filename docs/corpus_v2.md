# Corpus v2 reproducibility and preparation record

## Current use and external prerequisite

The deployed public service uses Corpus v2:
`https://veridex-staging-200331083905.us-west1.run.app/chat`.
Its JSON contract remains `{"query": string, "session_id": string}` →
`{"response": string}`. Using that service does not require local corpus files.

The repository and source ZIP omit all PDFs, indexes and the approved external bundle.
Rebuilding a v2 container requires a separately authorized handoff of
`.artifacts/versions/veridex-rag-v2-local` (or the same bundle at an external path):
`bundle.json`, `manifest.json`, five `papers/*.pdf` files and the complete `chroma/`
directory. The pinned **SHA-256 of `bundle.json`** is
`7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
The expected collection is `veridex_documents`, with 586 chunks and 1,536-dimensional
`text-embedding-3-small` vectors. Supply it as Docker's named context **`rag`**, never
by relaxing default-context exclusions. Exact validation/build commands are in
[docker_local.md](docker_local.md).

Source-only recipients can inspect and test the implementation with synthetic fixtures,
but cannot reproduce the released corpus/index without that external dependency.
The bundle preserves completed model/usage and vector provenance; regenerating embeddings
from the PDFs is a new paid, versioned operation, not a way to recreate the pinned bytes.
It needs separate approval, rights review, a new digest and full index/retrieval validation.
Model alias identity and a pinned extraction recipe do not guarantee future bit-identical
provider vectors or native database/image bytes.

The tracked `data/samples/manifest.json` and `scripts/ingest.py` belong to historical
Corpus v1 (`rag_2020`, 615 original chunks), not this v2 release. That ingestion script
cannot reproduce v2. Do not re-ingest or alter the protected original/recovered/v1/v2
artifacts. The original v1 index failed FTS5 checks; its recovered copy is a separate
historical candidate. The source ZIP distributes neither version's PDFs or index.

## Historical preparation record (Steps 4.7f–4.7g)

Steps 4.7f–4.7g, 2026-10-12: PDF acquisition, approved embedding execution,
Chroma construction and local bundle export completed. The original offline
preparation record is retained unchanged; the completed embedding journal records
the subsequent authorization and results. No original/recovered/v1 files are changed and no remote publication is
approved by that preparation step. Statements below about pending work refer to
that historical handoff, not the current v2 deployment.

## Sources and rights

The approved replacement was downloaded from the exact publisher-hosted URL:
`https://aclanthology.org/2024.emnlp-industry.66.pdf`.

- Zhuowan Li, Cheng Li, Mingyang Zhang, Qiaozhu Mei and Michael Bendersky.
- *Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and
  Hybrid Approach*, EMNLP Industry Track 2024, pages 881–893, 13-page publisher PDF.
- DOI: `10.18653/v1/2024.emnlp-industry.66`.
- 582,318 bytes; SHA-256:
  `90407fd3c2bcf11d52868f0aaee3d39d6a9919351c89636555a641950531a070`.
- Download timestamp recorded in the local `attribution.json`.
- Page 1: ©2024 Association for Computational Linguistics. The
  [official article record](https://aclanthology.org/2024.emnlp-industry.66/) names
  this PDF; [ACL's copyright policy](https://aclanthology.org/faq/copyright/)
  licenses post-2016 ACL materials under CC BY 4.0. No conflicting notice or
  separate reproduction exclusion located in local text/caption review. The
  paper's benchmark/prompt examples do not independently license underlying
  datasets, code or separately linked attachments.

Four retained PDFs are byte-identical copies of the reviewed originals. ReAct and
Self-RAG have version-specific CC BY 4.0 evidence; NetMHCpan and MixMHC2pred carry
CC BY-NC 4.0 notices in their actual PDFs. See [rights review](rag_distribution_review.md)
for scope and attribution requirements. This is a noncommercial coursework candidate,
not permission for commercial reuse. The manifest, notice inventory and rights
review do not independently authorize new remote publication. The release image now
ships full CC BY/CC BY-NC 4.0 license texts and notices and provides GET `/attribution`
without changing `/chat` JSON. No independent supplements or datasets are included.

## Local preparation

Root: `.artifacts/corpus/veridex-corpus-v2/` (Git/Docker ignored).

| Document ID | PDF filename | Chunks |
| --- | --- | ---: |
| `rag_long_context_2024` | `rag_long_context_2024.pdf` | 63 |
| `react_2022` | `react_2022.pdf` | 147 |
| `self_rag_2023` | `self_rag_2023.pdf` | 139 |
| `netmhcpan_2020` | `netmhcpan_2020.pdf` | 38 |
| `mixmhc2pred_2023` | `mixmhc2pred_2023.pdf` | 199 |

Total: 113 nonempty pages, **586 chunks**. Five PDFs occupy 13,143,534 bytes.
`manifest.json` retains the existing catalog schema; separate `attribution.json`
records authors, source fingerprints, licenses, source version and modifications.
`chunks.json` freezes text, metadata and per-chunk token counts. `normalization.json`
records every changed extracted codepoint and original offset, with before/after
chunk text hashes. `preparation.json` records source/output SHA-256, dependency and
lock versions, recipe, counts and unpaid embedding plan. `workflow.json` pins the
preparation and implementation file hashes.

Reuses existing `load_corpus` and `chunk_documents`: PyMuPDF page extraction,
chunk size 1000 characters, overlap 200, start indexes and global ordinal chunk IDs.
The replacement has its own stable document ID. Later retained chunk ordinals shift
with the new document; these are new-version IDs, not promises of v1 ID preservation.

ReAct/MixMHC2pred extraction contains controls, predominantly font encoding artifacts.
After chunking, Cc characters except TAB/LF/CR become explicit `⟦U+XXXX⟧` markers:
**2,504 occurrences across 37 chunks**, including overlap repetitions. No glyph
meaning is guessed, no bytes in PDFs are changed, and all transformations can be
reversed from the audit offsets. No NUL remains in prepared text. Marker expansion
can exceed the nominal 1000-character chunk length; the largest resulting chunk is
2,973 tokens, below the provider limit. Existing font-encoded figure text remains a
retrieval-quality limitation; escaping prevents unsafe controls, not font decoding.
No old RAG parenthesis repair is applied to the replacement.

Reproduce/verify offline (existing outputs are compared, never overwritten):

```sh
.venv/bin/python scripts/prepare_corpus_v2.py .artifacts/corpus/veridex-corpus-v2
```

## Approved embedding call plan and actual results

- Model: **`text-embedding-3-small`**, dimensions **1536**, float response encoding.
- All 586 chunks freshly embedded; no legacy vectors reused.
- 12 sequential embeddings HTTP requests, batches of at most 50 chunks.
- `cl100k_base` exact local input count: **164,002 tokens**.
- Largest batch: 24,185 tokens; largest input: 2,973 tokens.
- Timeout: 30 seconds; automatic retries: **0**. Failed/ambiguous attempts stop;
  retries need a reviewed remaining-budget calculation and authorization.
- [Official model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-small):
  $0.02/million tokens; estimated **$0.00328004** before taxes/account differences.
- Authorized total ceiling **$0.05 USD**. Exactly 12 requests succeeded; no retry
  or additional provider request was made.
- No chat, Tavily, query-embedding or other live provider calls in this plan.

The user explicitly approved this scope and ceiling, including transmission of the
prepared text. All 12 requests returned `text-embedding-3-small`; actual usage was
**164,002 prompt/total tokens**, exactly matching the estimate. Usage-derived cost
is **$0.00328004** at published pricing; provider invoice/tax/credit effects were not
independently inspected. Requests took 0.549–1.830 seconds each. The executor rechecked
frozen source hashes, set SDK timeout 30 seconds and retries zero, and journaled each
attempt before sending. A pre-existing run cannot be executed again. No new paid
request is authorized by rerunning a command. Errors stop safely without raw response
bodies. The journal contains request IDs, outcomes, returned model and token usage.
FLOAT32 vectors have per-chunk and aggregate hashes; all 586 were compared against
Chroma without further embedding calls. The ceiling is an operational request budget based on
published pricing, not an account-wide hard billing guarantee. Model alias pinning
records the requested identity, not guaranteed future bit-identical provider outputs.

## Completed index/bundle validation and Docker handoff

The new index is `.artifacts/corpus/veridex-corpus-v2/chroma`. A fresh worker used
Chroma's public `create_collection`/`add` APIs with explicit numeric embeddings and
no embedding function, then exited before snapshot operations. No legacy vectors
were loaded. The expected spec is `veridex_documents`, 586 chunks, five v2 IDs,
`text-embedding-3-small`, dimension 1536; no validator rules were relaxed.

Final bundle: `.artifacts/versions/veridex-rag-v2-local`, **24,198,047 bytes**, with
11 payload files plus `bundle.json`. Metadata SHA-256:

`7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`

Aggregate FLOAT32 vector SHA-256, in frozen prepared-chunk order:

`641edca770615c98465530eef1287a7a611b5e1ffc7c7d74a6d675928a6f4a60`

Unchanged format-version-1 `bundle.json` embeds the preparation, completed journal,
full attribution inventory/license links, per-vector fingerprints and validation in
its existing `embedding_model_provenance` string. It does not introduce extra files
that evade the validator's exact inventory contract. The source PDF hashes, index
files and metadata are pinned; packaged files are read-only. Step 4.7h completed
service-facing notice presentation and full license-text packaging in the image,
without changing this bundle's inventory.

SQLite `PRAGMA integrity_check`, explicit FTS5 integrity diagnostics on disposable
copies, native `get` comparison of all vectors/text/metadata, **586 self-queries**,
and `$contains` tests for `RAG`, `MixMHC2pred`, `⟦U+0003⟧` and `SELF` passed.
The final bundle itself was independently reopened/tested on a disposable writable
copy. Canonical sources/bundle were unchanged by those probes. Quiescent export
used the existing lsof and source-fingerprint safeguards. Re-export rejects an
existing destination. All 29 original/recovered/v1 protected files retained their
size, mtime and SHA-256 fingerprints.

An initial report listed legacy filter names although the native loop tested v2
terms. The reporting substitution was corrected and regression-tested. The first
candidate remains unchanged at
`.artifacts/quarantine/veridex-rag-v2-initial-filter-label`; it is not the release
handoff. A corrected candidate was exported from the same unchanged v2 index with
no additional embedding calls. The embedding-time executor is archived under
`embedding-run/executor.py`, matching the journal's implementation fingerprint.

Offline validation (no provider calls):

```sh
.venv/bin/python scripts/rebuild_corpus_v2.py validate \
  --metadata-sha256 7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb
.venv/bin/python -m pytest -m integration tests/test_corpus_v2.py tests/test_rebuild_v2.py
```

The approved bundle's named-context handoff (shown for reproduction, not executed
by reading this document) is:

```sh
docker buildx build --platform linux/amd64 \
  --build-context "rag=$PWD/.artifacts/versions/veridex-rag-v2-local" \
  --build-arg RAG_BUNDLE_SHA256=7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb \
  --load --tag veridex:phase04-v2-local .
```

This build and Linux/amd64 reopening were subsequently verified in Step 4.7h.
The current Dockerfile/runtime explicitly validate the v2 IDs, 586 chunks and selected
PDFs. Original, recovered and v1 deployment artifacts remain rollback references;
they are not acceptable substitutions for the v2 named context. A fresh build from
current source is a new image; no additional build, publication or deployment is
authorized by these instructions.

## Step 4.7h release handoff

Linux/amd64 reopening, native validation, non-root MCP/HTTP verification and notice
delivery are now recorded in [release_readiness_47h.md](release_readiness_47h.md).
The source bundle digest and all protected artifacts remain unchanged. Attribution
is generated into the image rather than added to the immutable bundle inventory.
Historical statements about pending Docker work describe the 4.7g handoff. Subsequent
approved publication, Cloud Run staging and public/live verification are summarized in
[README.md](../README.md#cloud-run-deployment). Those approvals do not authorize
redistributing this external bundle or publishing a new image. The local Step 4.12c
MCP SDK logging change has not been deployed.
