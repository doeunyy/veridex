# Current build prerequisite: external Corpus v2 bundle

The current Dockerfile/runtime consume only `.artifacts/versions/veridex-rag-v2-local`
and its pinned bundle digest. The historical Step 4.5 commands below refer to v1;
they require the corresponding historical checkout and are not current build commands.
See [release_readiness_47h.md](release_readiness_47h.md) for initial v2 verification.

The original source ZIP (source-only) and Git checkout contain no PDFs, Chroma index or
deployment bundle. An optional private coursework ZIP supplies the same approved
bundle under `submission_artifacts/veridex-rag-v2-local/`; its notice stays outside
the immutable bundle. Never attach the corpus automatically to a public release.
Use the already deployed public `/chat` API without local artifacts, or obtain the
exact approved external bundle through a separately authorized handoff before building.
The public URL and contract are in [README.md](../README.md#api-contract).
Required bundle files are `bundle.json`, `manifest.json`, five approved `papers/*.pdf`
files and the complete `chroma/` directory. The pinned **SHA-256 of `bundle.json`** is
`7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
It describes `veridex_documents`, 586 chunks, `text-embedding-3-small`, dimension 1536.
See [corpus_v2.md](corpus_v2.md) for provenance, rights and reproduction limits.

From the repository root, choose the supplied bundle directory; its location may differ
from the original ignored local path. These commands are instructions only and were
not executed during documentation cleanup. The build needs Docker Buildx/BuildKit,
Linux/amd64 support and access to pinned base images/dependencies, but no provider keys.
Run `uv sync` first to install the locked local validation dependencies.

```sh
RAG_BUNDLE_DIR="$PWD/.artifacts/versions/veridex-rag-v2-local"
.venv/bin/python scripts/rebuild_corpus_v2.py validate \
  --bundle "$RAG_BUNDLE_DIR" \
  --metadata-sha256 7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb
docker buildx build --platform linux/amd64 \
  --build-context "rag=$RAG_BUNDLE_DIR" \
  --build-arg RAG_BUNDLE_SHA256=7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb \
  --load --tag veridex:phase04-v2-local .
```

The named **`rag`** context must be the bundle directory itself, not its parent.
The default build context intentionally excludes `data/`, `.artifacts/`, `.env`,
Git metadata and private files. Do not weaken `.dockerignore`, substitute a v1 digest,
or use `scripts/ingest.py` to satisfy a missing v2 prerequisite. The pinned digest,
inventory and index checks fail closed; no build step re-ingests or re-embeds.
The serving image includes the MCP SDK logging safeguard and was built from
`35bbef63f6b7b704ac8c5b34c080f433b40faffd`, with that source revision recorded
in its OCI label. Step 4.12g verified 35 offline Docker tests against this image.
Match the recorded source, Dockerfile, lock and external bundle when reproducing
that release; later documentation commits are not its build provenance.
Byte-identical image reconstruction has not been demonstrated. See the
[deployment provenance](../README.md#cloud-run-deployment) for its immutable digest.

The verified stage explicitly selects the replacement PDF, validates 586 vectors,
five v2 IDs, metadata, SQLite/FTS5, four text filters and all native self-queries.
No original/corrupt/v1 index is supplied. The minimal runtime remains non-root,
one worker, `0.0.0.0:$PORT`, with the original bounded shutdown policy.
`OPENAI_EMBEDDING_MODEL` is set to `text-embedding-3-small`; private Chroma copies
remain separate from the immutable canonical bundle. Main context exclusions are
unchanged. Full CC BY/CC BY-NC 4.0 texts are specifically included under source;
no documentation directory, credential or private note is broadly copied.

Image notices: `/opt/veridex/notices/attribution.json`, `CORPUS_NOTICE.txt`,
`CC-BY-4.0.txt`, `CC-BY-NC-4.0.txt`, all read-only. GET `/attribution` serves
whitelisted authors/titles/versions/sources/licenses/modifications/scope information
without provider calls or internal provenance. Successful `/chat` responses link
to it with an HTTP `Link` header; the exact JSON response remains unchanged.
`CORPUS_ATTRIBUTION_PATH` configures the packaged notice location. Local apps without
that configuration return a safe 503 from `/attribution`, with existing APIs intact.
No POST/update mechanism exists. [Current notice](rag_attribution_v2.json) is a
review copy; the build generates notices from the digest-validated bundle itself.

For a current production-equivalent container run with runtime-only credentials,
localhost port binding and health/readiness/chat checks, follow the
[README workflow](../README.md#production-equivalent-corpus-v2-container).
It requires the approved bundle: an external handoff for a source-only ZIP, or
the included `submission_artifacts/veridex-rag-v2-local/` in the private coursework
ZIP. Use that directory as the `rag` named context. The default Docker context
excludes `submission_artifacts/`; global corpus/security exclusions remain intact.
The historical `veridex:phase04-local` smoke examples below are not substitutes
for that v2 run procedure.

## Entrypoints and private writable index

The actual Docker entrypoint is
`/opt/venv/bin/python /app/scripts/container_entrypoint.py`. It calls the existing
deployment bootstrap to validate the immutable bundle and prepare a private writable
Chroma copy under `/tmp`, then execs `/app/scripts/serve_api.py`. That runner binds
`0.0.0.0:$PORT`, uses one Uvicorn worker and preserves the 0.5-second HTTP drain and
eight-second application cleanup budget. UID/GID is `10001:10001`; canonical corpus
files remain read-only. No new runtime path or automatic indexing is introduced.
For a direct local API process, use `uv run python scripts/serve_api.py` after explicitly
configuring valid corpus paths and runtime credentials. Default local paths and the
tracked sample manifest are historical v1 configuration, not v2 container bootstrap.
The empty root `main.py` was unused and is removed.

NetMHCpan/MixMHC2pred retain noncommercial conditions and third-party exclusions.
This local release is not clearance for arbitrary commercial redistribution.
Any new remote registry publication or Cloud Run deployment requires separate authorization.

---

# Historical Step 4.5 local Linux/amd64 image (Corpus v1)

The following commands and measurements are a historical record, not current v2
setup instructions. They require the historical Dockerfile/runtime checkout.
This image was a local/internal candidate. Do not push it or use a remote builder:
PDF distribution authorization and historical embedding-model identity remain
unresolved. Cloud Run IAM, session ownership, resources, and deployment remain
separate work. No unauthenticated public access is configured by this workflow.

From the repository root, validate the named context and build locally:

```sh
.venv/bin/python scripts/package_rag.py validate \
  .artifacts/versions/veridex-rag-v1-local \
  --embedding-model unverified-legacy-model \
  --metadata-sha256 6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8 \
  --runtime-probe
docker buildx build --platform linux/amd64 \
  --build-context "rag=$PWD/.artifacts/versions/veridex-rag-v1-local" \
  --build-arg RAG_BUNDLE_SHA256=6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8 \
  --load --tag veridex:phase04-local .
```

Dockerfile frontend, Python 3.13.16 slim-trixie, and uv 0.12.23 image manifests
are digest-pinned. Dependencies use `uv sync --locked --no-dev`; neither the host
virtual environment nor a Python download is used. Bytecode is compiled during
the build. The dependencies stage retains uv/cache; the final Python runtime
stage contains only the Linux virtual environment, explicit application source,
three selected runner/check scripts, lock/project metadata, and approved artifacts.
The source package uses `/app/src` so existing STDIO project-root discovery still
resolves `/app`. Children execute `/opt/venv/bin/python`, never a macOS path.

The separate `rag` context supplies manifest, five named PDFs, and complete Chroma
persistence. The existing validator checks the pinned metadata digest, exact file
inventory/checksums, dependency versions, lock, PDFs, SQLite/FTS5 and index layout.
The Linux build additionally checks all 615 native vectors, metadata, self-queries,
three document filters, and the repaired chunk's hash. Missing context/files,
corruption, or a mismatched digest fails the build. Main context exclusions remain
unchanged: raw data, artifacts, Git, credentials, env files, and private notes are
excluded. Do not relax them or pass provider keys as build arguments.

UID/GID 10001 owns no canonical application or corpus files. Corpus directories
are 0555 and files 0444. Bootstrap validates them again and creates a fresh private
0700 instance directory under `/tmp`, with writable 0600 Chroma files. It never
opens the canonical database through Chroma. No ingestion or vector regeneration
occurs. `exec` replaces bootstrap with the existing `scripts/serve_api.py` runner,
which binds `0.0.0.0:$PORT`, uses one worker, and preserves the 0.5-second Uvicorn
drain plus the existing eight-second application cleanup budget. API limits and
same-task AnyIO ownership remain unchanged.

Offline non-root artifact and real production-STDIO/FastAPI lifespan check:

```sh
docker run --rm --platform linux/amd64 --network none --read-only \
  --tmpfs /tmp:rw,nosuid,noexec,size=256m \
  --entrypoint /opt/venv/bin/python veridex:phase04-local \
  /app/scripts/check_container.py --smoke
```

This uses a deterministic injected LLM and the real three STDIO servers. It calls
only the local Workspace tool; provider APIs are unavailable with networking off.
It checks readiness before/after lifespan, liveness/readiness during service,
exact chat response, and child cleanup. Production bootstrap has no mock fallback.
For real usage supply OpenAI/Tavily secrets only at runtime, keep the listener
private, and configure the deployment access policy separately.

Local API-runner health tests may supply clearly invalid placeholder keys with
networking disabled, without issuing chat requests. This tests initialization and
PORT binding, not provider credentials or model quality. Source PDFs/index, the
recovered candidate, and canonical bundle are never changed by container tests.

Writable copies and audit scratch files consume instance-local ephemeral storage.
With a tmpfs, that storage also counts toward memory. Remove the container to
release its storage; restarting a container without tmpfs may retain old scratch
copies. Synchronous PDF/Chroma threads remain noninterruptible, as documented by
the existing lifespan policy. Measure actual Linux/amd64 cold start and aggregate
parent/three-child memory before selecting cloud resources; Apple Silicon amd64
emulation timings do not predict native Cloud Run performance.

## Recorded local verification

The final image `veridex:phase04-local` is
`sha256:98ac51911d53361ac7762351a36327d6513b10e96daaaf149193aa4257f8284f`,
834,613,416 bytes (about 796 MiB), Linux/amd64, user `10001:10001`.
The uncompiled prototype's emulated evidence-server import exceeded the existing
45-second initialization deadline; precompiled bytecode resolved that without
changing Agent/MCP deadlines. A regression also fixed the audit's initial failure
to honor the build-argument digest. Mismatched-digest, missing-file, and corrupted
context builds now fail.

Final non-root Linux container verification used SQLite 3.46.1 and passed all 615
vector/metadata comparisons, all self-queries, five paper IDs, 1536 dimensions,
SQLite/FTS5 integrity, three text filters, and the repaired chunk hash. Real STDIO
lifespan smoke found three persistent children/four tools, passed mocked chat and
health/readiness checks, withdrew readiness, and closed every child. The actual
runner bound `0.0.0.0:9091`; its liveness/readiness endpoints returned 200 with
networking disabled. SIGTERM completed application shutdown in 2.82 seconds; exit
143 reflects SIGTERM propagation after graceful shutdown, not SIGKILL (137).

Docker Desktop's Linux x86_64 VM/emulator on Apple Silicon took about 98 seconds
from container start to readiness. Idle aggregate memory was about 712 MiB. The
ASGI/MCP-only startup measurement was 55.923 seconds. These are emulation results,
not a native Cloud Run latency or memory guarantee. Precompiled bytecode trades
additional image space for faster cold imports. Production dependencies account
for most image weight; pruning them is outside this step.

Canonical files were root-owned/read-only; the single private Chroma copy was
UID-10001-owned with 0700 directories and writable files. All host original,
recovered, and bundle fingerprints remain unchanged. Provider calls were zero.
The immutable bundle retains its historical Linux-unverified metadata; this
separate image verification records the successful Linux test without rewriting it.


## Historical release candidate (Step 4.7d, Corpus v1)

The Step 4.5 measurements above are historical. The candidate at Step 4.7d was
`veridex:phase04-47d`; its identity, 32 offline TCP passes, native index checks,
non-root production startup and shutdown/resource results are recorded in
[release_readiness_47d.md](release_readiness_47d.md). It remains local/internal.
