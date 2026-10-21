# Step 4.7d — local release candidate and final action gates

Local verification completed 2026-10-12 (UTC timestamps cross into October 13).
No remote publication, GCP resource/IAM change, paid provider call, PDF download,
embedding regeneration, corpus write or PROCESS_LOG modification occurred.

## Exact local candidate

Tag: `veridex:phase04-47d`

Local image/config SHA-256:
`6ac318560e55e8a37a4f7145ff38a4300ec33d9b08f02f836bb0875b476b6d07`

Size: 834,635,781 bytes (795.97 MiB), Linux/amd64, UID/GID 10001.
Entrypoint: `/opt/venv/bin/python /app/scripts/container_entrypoint.py`.
No registry manifest digest exists (`RepoDigests=[]`); don't substitute this local
config digest for a future registry manifest digest in a Cloud Run image reference.
The older `veridex:phase04-local` image was preserved.

Executed local build:

```bash
docker buildx build --platform linux/amd64 \
  --build-context rag=.artifacts/versions/veridex-rag-v1-local \
  --build-arg RAG_BUNDLE_SHA256=6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8 \
  --load --tag veridex:phase04-47d .
```

Build audit passed: 615 identical vectors/metadata, 615 native self-queries, five
paper IDs, dimension 1536, SQLite/FTS integrity, three `$contains` terms including
the recovered chunk. No model-origin attestation is inferred. Canonical database
0444/non-writable to UID 10001; one separate writable Chroma directory 0700.
All 29 original/recovered/bundle/PDF/manifest hashes, sizes and mtimes remained
unchanged. No new notices/license package is included in this image: the attribution
inventory remains local documentation, and final recipient/image attribution must
be completed before approving publication.

## TCP/MCP and resource verification

```bash
VERIDEX_RUN_DOCKER_E2E=1 .venv/bin/python -m pytest tests/test_docker_e2e.py -m integration -q --tb=short
```

**32 passed in 85.74 seconds.** Real TCP through `127.0.0.1:18846`, three persistent
real production STDIO server entrypoints/four tools, deterministic injected LLM,
stored-vector query embedding fixture and mocked Tavily. Fixture files are mounted
read-only, excluded from the image. Socket guards reject external Python connections
in parent/children; no real provider credentials are supplied. A first run on Docker
Desktop's internal network had 32 setup errors because published-port forwarding
failed; no endpoint assertions ran. Recreated with bridge networking, localhost-only
publication, guards and fixtures; the complete rerun passed. Bridge connectivity is
not claimed to be OS-level egress isolation. Production startup smoke used network
none, invalid placeholder keys, no chat/provider calls and the unmodified entrypoint.

Verified exact `/chat` JSON, strict validation/body cap, safe failures, readiness,
actual Evidence/Web/Workspace invocation and orchestration, two-turn memory,
isolation for distinct IDs, cancellation/history repair, overload/queue/total
HTTP deadlines, eight-call tool budget, model-call budget, active 1/waiting 0,
six-turn retention, one latest checkpoint, session capacity 429 and idle expiry.
Provider output-token enforcement was not tested against a live provider; configured
4096 cap/30s/zero retries are present, with construction regression coverage.

| Measurement | Local result |
| --- | --- |
| TCP fixture container start -> ready | 101.121 seconds |
| Fixture lifespan/import portion after prepare | 55.753 seconds |
| Production entrypoint start -> startup complete, 1 CPU / 2 GiB | 104.477 seconds |
| Warm greeting median / maximum, five samples | 0.0309 / 0.1116 seconds |
| Warm real Chroma retrieval HTTP turn with stored-vector fixture | 0.3270 seconds |
| TCP fixture idle/sample peak cgroup memory | 821.61 MiB |
| Production health-only idle memory, 1 CPU / 2 GiB | About 711.7 MiB |
| Idle SIGTERM Docker-stop elapsed | 3.00 seconds |
| Active-turn SIGTERM Docker-stop elapsed, 1 CPU / 2 GiB | 5.67 seconds |

These are amd64 emulation on Apple Silicon, not native Cloud Run measurements.
Peak was sampled `memory.current`; `memory.peak` was unavailable. TCP fixture ran
without a Docker resource cap; separate production and active-shutdown checks used
1 CPU/2 GiB. Mock model/provider latency and billing are excluded. Both idle/active
shutdowns withdrew readiness, closed the registry, reaped all children and exited
143 without OOM/SIGKILL. Active HTTP returned safe 500, never a fabricated success;
its interrupted ToolCall history was balanced before memory teardown. Task-owned
containers/network were removed; candidate image and ignored reports remain.

## Cloud runtime review

Retain us-west1, colocated registry, one worker, concurrency 1/application 1+0,
min 0/service max 1, 1 CPU/2 GiB plus startup boost and HTTP `/ready` startup probe
(10s period, 3s timeout, threshold 24). Runtime identity has only per-secret access;
provider secrets are numeric Secret Manager env references, not build args. Public
admission remains a separate explicitly approved allUsers grant after private checks.
Anonymous colliding IDs share history; limits do not prove user ownership or a hard
provider-dollar ceiling. Approve a grading expiry/operator revocation date, provider
allowance, alert recipients and optional spending controls; maximum instances and
alerts alone cannot prevent sustained abuse or overspend.

The [Cloud Run contract](https://docs.cloud.google.com/run/docs/container-contract)
includes container startup in the request timeout. The former 240s proposal can be
shorter than measured emulated startup + the 180s HTTP allowance. Propose **300s**
initial platform timeout (about 104+180+16 seconds), keeping local deadlines intact.
This is an unexecuted proposal, not a universal worst-case guarantee: a startup near
its 240s probe window can still exceed this combined budget. Measure native cold
startup and tune before grading. Platform 504 does not itself terminate work;
application deadline/disconnect cancellation remains necessary. Shutdown budget
0.5s + 8s fits the platform's 10s grace; synchronous threads cannot be directly
interrupted and forced termination cannot guarantee repair.

## PDF-by-PDF disposition

| Exact file | Evidence/disposition | What blocks remote use |
| --- | --- | --- |
| RAG 2020, 19 pages | No local CC notice; arXiv v4 nonexclusive grant and NeurIPS availability do not establish our downstream grant. | Applicable permission/license evidence missing: strongest rights blocker. |
| ReAct 2022, 33 pages | Version-specific arXiv CC BY 4.0 evidence; authors/title/version match local attribution record. | Conditional retention: finish exact-material applicability, notices and attribution; no need to replace solely for absent interior license notice. |
| Self-RAG 2023, 30 pages | Same CC BY evidence for arXiv v1. | Same conditional retention/attribution completion. |
| NetMHCpan 2020, 6 pages | Exact PDF p1 CC BY-NC 4.0, corroborated by PMC; attribution prepared. | Retention supported for compliant noncommercial coursework; confirm intended purpose/recipients and retain notices. |
| MixMHC2pred 2023, 31 pages | Exact PDF p2 CC BY-NC 4.0; ends at article methods e13, not a separate supplemental attachment. | Retain conditionally for noncommercial coursework; final notices/third-party scope review. No additional exclusion found is not comprehensive clearance. |

All five are held from remote publication until the aggregate bundle conditions
pass. RAG is the only file with no established downstream license grant; the other
files have license evidence but incomplete release conditions. The user's deployment
approval cannot manufacture missing copyright permission. Private storage or
educational use is not automatically a grant. See [attribution inventory](rag_attribution.json)
and [rights review](../rag_distribution_review.md).

Prioritize rights evidence/permission for the existing RAG work, preserving the
snapshot. If unavailable, approve just one replacement candidate:
[Li et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-industry.66/) or
[RAGTruth, ACL 2024](https://aclanthology.org/2024.acl-long.585/), whose post-2016
Anthology policy offers CC BY evidence. Confirm course suitability, exact downloaded
material/scope and attribution first. No PDFs were downloaded here. A new work gets
its own truthful ID/filename; remaining papers can stay if compliant. New manifest,
chunks/counts, index/bundle/SPEC/digests, semantic evaluation and image are required;
do not fabricate 615 or overwrite old artifacts.

## Embeddings and final approval table

Rechecked Git model defaults and index/provenance records: configured
text-embedding-3-small, dimension 1536 and preserved vectors are verified facts;
**historical model identity is not verified**. No ingestion-run attestation linked
to the source hash was found. The bundle's unverified marker stays unchanged.
For this coursework demo, explicit documented uncertainty can be an acceptable
operator decision because reproducibility of historical vectors is not a stated
handout requirement. It does not establish semantic compatibility: require an
approved minimal live retrieval evaluation before grading. For a reproducibility
claim, or replacement with an unknown old embedding space, prefer a new coherent
index with explicit model/dimensions and approved paid budget. Re-embed all approved
chunks if origin cannot be established; don't combine new/old vectors on dimension
alone. Deterministic input preparation plus hashed evaluated outputs is achievable;
mutable external model aliases cannot guarantee future byte-identical outputs.

| Gate | Exact decision/action | Status |
| --- | --- | --- |
| Local technical release | Current code Linux build, 32 offline Docker tests, memory/budgets/shutdown | Passed; no production source/server changes in 4.7d |
| Rights | Applicable RAG permission or approved replacement; final four-paper scope/NC/notices | Unresolved; user approval is not a substitute for rights |
| Attribution release packaging | Approve final attribution/license delivery, package it and rebuild/reverify image if changed | Current image is local/internal only; not final distribution image |
| Model provenance | Accept documented uncertainty for coursework or approve coherent new index/paid allowance | Unselected; no embeddings regenerated |
| Public-demo policy | Accept collisions/no confidentiality, retention, provider allowance and dated expiry | Explicit user approval needed |
| Cloud identifiers/security | Project/billing, deployer/publisher/runtime identities, secret operator, enabled numeric versions, models, budgets | Fill/review placeholders; don't disclose keys |
| Remote publication | Approve exact image/registry/recipients after rights/package conditions pass | Prohibited now; no registry digest exists |
| Provision/private deploy | Authorize named resource/IAM/billing/deployment operations and proposed 300s timeout | Prohibited now |
| Native/live acceptance | Native resources/startup/shutdown and separately approved counted live turn | Deferred until authorization; no live validation performed |
| Public admission | Approve separate grant after private/native/live checks; schedule removal | Prohibited now |

Recommended next action: decide the RAG rights path first and choose documented
embedding uncertainty versus a fresh index. Resolve notices/delivery and approve
public-demo risk/budget/expiry and concrete cloud parameters. Any corpus/notices
change requires a new approved image before upload. **Step 4.8 is not ready for
unconditional authorization**; local technical readiness is now verified, while
rights and named action approvals remain unresolved. No staging/commit/push occurred.

## Final regression and preservation record

`.venv/bin/python -m pytest -q --tb=short`: **400 passed, 42 deselected**, five existing
PyMuPDF/SWIG warnings, 144.05 seconds. Four new Docker cases account for the increased
ordinary deselection count. No live-provider test was selected. Ruff lint passed,
format check reported 94 files already formatted, and `git diff --check` passed.
Unchanged artifact validator passed and all 29 protected fingerprints matched again
at completion. No production source, Dockerfile, dependency lock, ignore rules or
PROCESS_LOG changed in this step. Changes are test-only fixtures/TCP cases and release
planning documents. Exact ignored measurements/report files are under
`.artifacts/release-47d/`; summary digest is recorded locally, not a publication.
