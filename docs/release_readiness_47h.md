# Step 4.7h — Corpus v2 local Docker release

Verified 2026-10-12 (UTC reports extend into 2026-10-13). Local Docker only; no
registry upload, GCP mutation, provider validation, Git staging/commit/push or
PROCESS_LOG/README finalization. Protected corpus/index/bundle files are unchanged.

## Exact release identity

- Tag: `veridex:phase04-v2-local`, Linux/amd64, Python 3.13.16.
- Local image configuration ID:
  `sha256:38c2bb0aed856da0fa8724e4ffc0dd27cf4c461b69b97b8822d5b854ee544289`.
- Size: **834,267,880 bytes / 795.62 MiB**. No registry manifest digest exists;
  `RepoDigests` is empty because the image was loaded locally, not pushed.
- Bundle: `.artifacts/versions/veridex-rag-v2-local`.
- Pinned `bundle.json` SHA-256:
  `7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
- Runtime UID/GID `10001:10001`, entrypoint `/opt/venv/bin/python
  /app/scripts/container_entrypoint.py`, which execs the existing one-worker runner.

Exact successful build:

```sh
docker buildx build --platform linux/amd64 \
  --build-context rag=.artifacts/versions/veridex-rag-v2-local \
  --build-arg RAG_BUNDLE_SHA256=7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb \
  --load --tag veridex:phase04-v2-local .
```

Pinned base/frontend/uv and locked dependencies remain unchanged. Explicit COPY
selects `rag_long_context_2024.pdf` and the four retained PDFs. Neither raw `data/`
nor original/recovered/v1 artifacts enter the default context. Ignore rules remain
unchanged. Only specifically selected scripts, application source, approved named
bundle and official license texts are copied; docs/tests/notes/credentials are not
broadly included. Provider secrets remain runtime-only.

## Linux compatibility and attribution

Build and non-root runtime audits passed: SQLite **3.46.1**, SQLite/FTS5 integrity,
collection `veridex_documents`, 586 chunks, five v2 IDs, dimension 1536, model
`text-embedding-3-small`, exact per-vector hashes, metadata/text comparisons and
**586 native self-queries**. `$contains` checks passed for `RAG`, `MixMHC2pred`,
`⟦U+0003⟧` and `SELF`. Chroma saw only disposable/private writable copies; the
canonical bundle stayed read-only. This proves Linux/amd64 library reopening under
emulation; it is not native Cloud Run performance certification.

The image build generates `/opt/veridex/notices/attribution.json` and
`CORPUS_NOTICE.txt` from the digest-validated bundle's provenance, checking PDF hashes
and release IDs. It also ships the official texts downloaded from:

- https://creativecommons.org/licenses/by/4.0/legalcode.txt
- https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt

All four image notice files are 0444, with directory 0555. `CORPUS_ATTRIBUTION_PATH`
points at the generated JSON. GET `/attribution` serves only public notice fields:
full authors, title, source, version, PDF checksum, license, copyright notice,
modifications and third-party scope. It is independent of Agent readiness, invokes
no provider, and has no write endpoint. Successful `/chat` replies link to it via
`Link: </attribution>; rel="describedby"` while still returning exactly
`{"response":"..."}`. Missing local notice configuration yields safe 503 for that
endpoint, with existing API behavior preserved. [Review copy](rag_attribution_v2.json)
reflects the actual served payload; historical v1 rights records remain intact.

ReAct/Self-RAG/replacement use CC BY 4.0; NetMHCpan/MixMHC2pred use CC BY-NC 4.0.
Noncommercial conditions remain explicit. Independent datasets/software/external
supplements and excluded third-party material are not cleared by article licenses.
Extraction/chunking and control escaping are disclosed; PDFs are unchanged. There
is no blanket grant for arbitrary commercial redistribution or remote publication.

## Offline verification

```sh
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/test_attribution.py tests/test_api.py tests/test_api_limits.py tests/test_container_runtime.py
.venv/bin/python -m pytest -m integration tests/test_corpus_v2.py tests/test_rebuild_v2.py
VERIDEX_RUN_DOCKER_E2E=1 .venv/bin/python -m pytest -m integration tests/test_docker_e2e.py
.venv/bin/ruff check .
.venv/bin/ruff format --check .
git diff --check
```

Results: **441 ordinary passed, 45 deselected** (140.97s); **76 focused passed**
(9.51s); **2 offline corpus integration passed, 35 deselected** (3.36s);
**33 Docker TCP E2E passed** (59.59s). Ruff lint and format passed (105 files already
formatted); Git whitespace check passed. Five existing PyMuPDF/SWIG warnings remain.
Historical v1 artifact/recovery fixtures were not rewritten.

The task-owned TCP fixture binds only `127.0.0.1:18846`. It mounts test-only SDK/model
replacements and a Python external-socket guard while invoking the unchanged three
production STDIO server entrypoints. Placeholder keys are used. Provider fixtures
never appear in the production image. The bridge network permits localhost port
forwarding; do not describe it as Docker-level egress isolation. Separate artifact
and production-entrypoint checks use `--network none`.

TCP checks verify actual traces for no-tool, Evidence, Web, Workspace PDF reading,
multi-server orchestration, recovery/insufficient evidence, two-turn memory and
non-colliding session isolation, tool/model budgets, retention/capacity, HTTP limits,
overload/queue/total deadlines, disconnect cancellation and balanced history.
New-paper evidence resolves `rag_long_context_2024_p1_c00000`, page 1, distance 0,
with the exact ACL title/source metadata. Workspace uses the new PDF filename as
its identifier, preserving the distinction from Evidence paper IDs.

Non-root network-disabled check:

```sh
docker run --rm --platform linux/amd64 --network none --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=256m \
  --entrypoint /opt/venv/bin/python veridex:phase04-v2-local \
  /app/scripts/check_container.py --smoke
```

Passed as UID 10001, with three real production MCP servers/four tools, readiness
transitions, exact HTTP contract and child cleanup; lifecycle startup portion
56.707s. The actual production entrypoint also passed health/readiness/attribution
at `PORT=8091`, network disabled, placeholder credentials, 1 CPU/2 GiB, with three
children and a separate private index. No production `/chat` provider call was made.

## Measurements and graceful shutdown

These are Apple Silicon **amd64 emulation** measurements with local contention,
not native Cloud Run estimates. Model/Web responses are deterministic fixtures.

| Measurement | Result |
| --- | --- |
| Uncapped TCP fixture container -> ready | 90.690s |
| Fixture lifecycle/import portion after prepare | 53.573s |
| Active fixture startup, 1 CPU / 2 GiB | 95.460s |
| Actual production startup, 1 CPU / 2 GiB | 121.139s |
| Warm greeting median / maximum, five samples | 0.02464s / 0.04408s |
| Warm Chroma Evidence HTTP turn, stored-vector fixture | 0.27453s |
| TCP fixture idle / sampled peak memory | 823.85 / 823.85 MiB |
| Active fixture idle / active sampled peak | 737.63 / 739.15 MiB |
| Production sampled memory | 765.92 MiB |
| Fixture idle SIGTERM cleanup | 2.862s |
| Active-turn SIGTERM cleanup | 5.469s |
| Actual production idle SIGTERM cleanup | 3.134s |

Peak is sampled cgroup `memory.current`; kernel `memory.peak` was unavailable. The
uncapped fixture values are not interchangeable with resource-capped runs. Native
Cloud Run cold starts, image pull cost, memory peaks and provider latency still need
measurement. Image size/import-heavy subprocesses remain cold-start considerations.

Idle/active fixtures withdrew readiness, closed the registry, reaped all children,
and exited 143 without OOM/SIGKILL. Active history was balanced with one interrupted
ToolCall. The interrupted TCP response was safe HTTP 500, plain text `Internal
Server Error`; it was never reported successful. Uvicorn can synthesize that
plain-text error on shutdown cancellation, distinct from normal application JSON
errors. Cancellation propagation and the 0.5s Uvicorn/8s application cleanup policy
remain unchanged. Synchronous PDF/Chroma work cannot be forcibly interrupted as a
Python thread; platform termination remains the final bound for such work.

The first active measurement harness incorrectly assumed aborted responses were
JSON; it failed parsing Uvicorn's plain-text 500. The harness was corrected and the
measurement repeated. No production fix was needed. The first cleanup report is
retained locally for audit. Ignored reports are under `.artifacts/release-47h/`.
All **75 protected v1/v2/original/recovered files** retained size/mtime/SHA-256.
Task-owned containers/network are cleaned up; the image and reports remain local.

## Step 4.8 gate

The v2 release candidate is **technically ready for publication review**. No remote
publication/deployment is authorized. Before Step 4.8 approve the noncommercial
use/recipients/expiry, public grading access and anonymous session collision/no
verified ownership risks, generation model and separately counted live/provider
spending plan, exact project/billing/region/registry/service/identities/secrets, and
named publication/provisioning/IAM/deployment actions. Public admission stays a
separate gate after private/native/live acceptance. Max one instance does not make
memory durable or prevent collisions/abuse; billing alerts are not hard limits.
See [deployment_approval_checklist.md](deployment_approval_checklist.md).
