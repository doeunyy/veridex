# Phase 04 Step 4.7: Cloud Run deployment preflight

Planning review: 2026-10-12. No cloud resources, IAM, billing, images, or remote
artifacts were changed. Step 4.8 is **not authorized**. Proposed commands are in
[cloud_run_commands.md](cloud_run_commands.md); they are review material, not an
executable provisioning script.

## Proposed initial configuration

| Setting | Proposal |
| --- | --- |
| Region | `us-central1` (Iowa): Tier 1 pricing baseline, no known residency requirement; keep registry and service together. `us-west1` is an alternative if Western US latency measurements justify it. Confirm project/location policy before provisioning. |
| Service | `veridex`, one ingress container, second-generation execution environment |
| Worker/processes | Existing runner: one Uvicorn worker, three persistent STDIO MCP children, four discovered tools |
| Resources | 1 vCPU / 2 GiB, subject to native measurements; startup CPU boost enabled |
| Scaling | Service-level minimum 0, maximum 1; revision maximum 1 as an additional safeguard; no session affinity |
| Concurrency | Cloud Run 1; application active requests 1, waiting requests 0 |
| Deadline | Cloud Run 240 seconds; existing ASGI deadline 180 seconds, Agent turn 120 seconds, provider/MCP request 45 seconds |
| Startup probe | HTTP/1 GET `/ready`, port 8080, initial delay 0, period 10 seconds, timeout 3 seconds, failure threshold 24 |
| Liveness | Initially omit a restart-triggering liveness probe; `/health` remains available for authenticated diagnostics. Add only after measuring event-loop responsiveness under load. |
| Access | Internet-reachable HTTPS URL, IAM invocation required, no `allUsers`/`allAuthenticatedUsers` grants, invoker IAM check enabled |
| CPU/billing | Request-based (`--cpu-throttling`); no required work scheduled while idle |
| Secrets | Two Secret Manager environment references pinned to numeric versions; never build arguments |
| Storage | Immutable canonical bundle, private writable `/tmp` Chroma copy; no ingestion or provider calls during artifact validation |

The application contract remains POST `/chat` with required strict strings
`query` (nonblank, at most 10,000 characters) and `session_id` (nonblank, at most
128 characters), no extra fields, returning exactly `{"response":"..."}`.
Body cap remains 65,536 bytes. Health/readiness do not make provider calls.
Application validation errors are 422, oversized bodies 413, invalid length
headers 400, capacity exhaustion 429, HTTP/queue deadline 504, unavailable service
503, and safe internal failures 500. Platform IAM/routing errors can have different
bodies; do not promise the application error schema for every platform failure.
Agent turn timeout has its existing safe fallback behavior, rather than necessarily
producing an HTTP 504. Cancellation must not be translated into a successful turn.
Cloud Run's [request timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout)
closes the connection with 504 without terminating the instance; code can continue.
The shorter application deadline and disconnect cancellation remain necessary.
Do not automatically retry POST `/chat`: a failed connection can leave a completed
or partially completed turn, and this contract has no idempotency key.

## Contract and runtime review

The image targets Linux/amd64 and runs UID/GID 10001. The exec entrypoint starts
`/opt/venv/bin/python /app/scripts/serve_api.py`; the runner listens on `0.0.0.0`
and configured `PORT`. Cloud Run supplies `PORT` with `--port=8080`; do not set that
reserved environment variable separately. Cloud Run terminates TLS; the container
serves HTTP/1. Subprocesses use `sys.executable` and `/app/src`, not a macOS venv.

Cloud Run's [container contract](https://docs.cloud.google.com/run/docs/container-contract)
requires Linux x86_64 support, startup within four minutes, and provides a
10-second SIGTERM period. Its writable filesystem is memory-backed and ephemeral.
Platform pending queues are outside the application deadline. Maximum-instance
settings can be temporarily exceeded; they do not ensure a single permanent process.

Startup validates bundle hashes, dependencies, PDFs, collection and SQLite/FTS
structure, prepares private Chroma storage, then initializes MCP in the same
lifespan task that later exits it. Readiness is published only after the three
servers and four tools are usable. Readiness does not certify working API keys,
provider quotas, semantic embedding compatibility, or live provider availability.
The [HTTP startup probe](https://docs.cloud.google.com/run/docs/configuring/healthchecks)
uses the existing readiness route without IAM headers inside the container; it
does not require public invocation. The proposed 240-second window is conservative
even though current health-check documentation permits longer probe windows.

Uvicorn drains for 0.5 seconds before the single eight-second lifespan shutdown
budget. Readiness is withdrawn and new work rejected; pending turns are canceled
with history repair before MCP teardown. This leaves about 1.5 seconds of platform
margin. Synchronous PDF/Chroma threads cannot be directly interrupted; hard kill,
OOM, or cancellation-resistant work prevents guaranteed history repair. No MCP
children exist during pre-server bundle preparation, which has no dedicated
SIGTERM cleanup handler. The whole instance filesystem is discarded on termination.

Request-based CPU suits idle STDIO readers, but does not promise progress for
background work after an HTTP response. Measure cancellation and connection health
after idle throttling; switch billing mode only if required and approved.
[Startup boost](https://docs.cloud.google.com/run/docs/configuring/services/cpu)
temporarily raises the proposed 1 vCPU to 2, including ten seconds after startup;
boosted allocation is billed. Three Python imports share this CPU allocation.
FastMCP update-check/telemetry behavior should be audited before deployment;
arbitrary parent environment switches are not forwarded by the scoped MCP config.
Do not assume setting an undocumented environment flag disables child networking.

No fatal container-contract incompatibility was identified. Operational risks:
45-second MCP initialization timeouts on a small CPU allocation, image/import
weight, memory-backed writes, unbounded session history/locks, provider latency,
and interrupted synchronous work. No runtime code was changed in this step.

## Infrastructure and identities

Dependency order: approved project + billing + budget -> enabled APIs -> regional
Docker repository + runtime service account + two empty secrets -> secret versions
and scoped IAM -> approved image upload -> private service -> approved invoker.
Select existing project/billing where appropriate; organization policy, quotas,
project number, principals, billing currency, and location restrictions are unknown.

| Identity | Minimum planned permissions/scope |
| --- | --- |
| Runtime `veridex-runtime` | `roles/secretmanager.secretAccessor` on each of the two secrets only; no Editor, Owner, registry writer, deployment, billing, or service-account keys |
| Routine deployer | `roles/run.developer` on existing service, `roles/iam.serviceAccountUser` on runtime SA, `roles/artifactregistry.reader` on repository |
| Local image publisher | `roles/artifactregistry.writer` on repository; local user credentials or federation, no exported SA key |
| Access administrator | Permission to get/set service IAM policy; `roles/run.admin` scoped to service after creation, or reviewed custom policy role. Keep separate from routine deployer. |
| Grader/trusted invoker | `roles/run.invoker` on this service only; decide exact principal before grant |
| Secret operator | `roles/secretmanager.secretVersionAdder` on those secrets; enters values directly using an approved operator workflow, never through this agent |
| Bootstrap administrator | Temporary resource-specific provisioning authority: Service Usage Admin, Artifact Registry Admin, Service Account Admin, Secret Manager Admin, and Cloud Run Admin as needed to create resources/manage initial policy; project IAM admin only if required to grant project roles. Existing administrator performs this, not runtime SA. Narrow/revoke bootstrap grants afterward. |
| Billing/project operator | Project Creator on approved parent if creating project; Billing Account User plus project billing assignment authority if linking billing; budget-specific permissions for approved budget scope |

New service creation requires project-level creation authority before a service
exists. Routine updates can subsequently be narrowed to that service. Initial
`--no-allow-unauthenticated` policy management requires the access administrator,
not just Cloud Run Developer. See [deployment IAM](https://docs.cloud.google.com/run/docs/deploying).
Cloud Run's service agent handles image pulling; do not give the application SA
registry permissions for this purpose. A cross-project registry would require
additional service-agent reader grants and is not proposed.

Use [Secret Manager references](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
`OPENAI_API_KEY=veridex-openai-api-key:<numeric-version>` and
`TAVILY_API_KEY=veridex-tavily-api-key:<numeric-version>`. Automatic replication is
proposed unless residency policy requires a specific location. Confirm enabled
versions and access permissions without accessing payloads. Rotate by adding a
version and deploying an approved reference update. Cloud Run resolves env secrets
at instance startup. No credentials belong in image layers, command arguments,
source files, logging, or this plan. Leave optional tracing credentials unset.

Explicit nonsecret settings: `APP_ENV=production`, `LOG_LEVEL=INFO`, the five API
limits in the command plan, approved `OPENAI_MODEL` and `OPENAI_EMBEDDING_MODEL`.
The existing defaults are `gpt-5` and `text-embedding-3-small`; deployment must
select/approve these explicitly. The latter is not attested as the historical
index model. Bundle paths/collection/digest are set and validated by bootstrap;
do not override them or point at `data/index`. Port and Settings values still need
operator review; successful readiness cannot replace live-provider validation.

## Costs and safeguards

USD list-price illustration, us-central1, request-based 1 vCPU / 2 GiB, no discounts,
excluding startup boost, startup/shutdown duration, networking, logs, storage,
providers, retries, and tax. Active rate: $0.000024/vCPU-second plus
$0.0000025/GiB-second = $0.000029/second; $0.40/million requests.
[Cloud Run pricing](https://cloud.google.com/run/pricing) applies monthly free
allowances across the billing account: 180,000 vCPU-seconds, 360,000 GiB-seconds,
and two million requests. Other projects can consume these allowances.

| Workload | Gross active compute + request charge | With otherwise unused monthly allowances |
| --- | --- | --- |
| 1,000 turns, 30 billed seconds each | $0.8704 | $0 for these items |
| 1,000 turns, 120 billed seconds each | $3.4804 | $0 for these items |
| 10,000 turns, 30 billed seconds each | $8.704 | $3.48 |
| One continuously busy instance for 30 days | $75.17 compute, plus requests | About $69.95 compute |

These are workload examples, not quotes or spending ceilings. Min 0 avoids reserved
idle-instance charges but permits cold starts. Maximum 1 limits capacity, not total
turns, token spending, retained sessions, or temporary scaling overshoot.

[Artifact Registry](https://cloud.google.com/artifact-registry/pricing) storage is
approximately $0.10/GiB-month above the billing account's 0.5 GiB free allowance.
A hypothetical 0.8 GiB stored image is about $0.03/month with unused allowance,
$0.08 without it. Actual compressed layer storage must be measured; local image
size is not registry billable size. Keep a rollback version and review cleanup
policies separately; no automatic deletion is proposed.
[Secret Manager](https://cloud.google.com/secret-manager/pricing): two active
automatically replicated versions are $0.12/month before the six-version free
allowance; accesses are $0.03/10,000 beyond the 10,000-access allowance. Disabled
versions also count as active for storage billing. Initial local-build publication
uses no Cloud Build. Optional [Cloud Build](https://cloud.google.com/build/pricing)
e2-standard-2 is $0.006/minute before applicable promotional allowances; ten minutes
is $0.06. Cloud Build would need its own explicit build identity and controlled RAG
staging workflow, and is deferred. Internet egress and Cloud Logging can add costs.

OpenAI generation/query embeddings and Tavily searches are separate bills, likely
the principal variable cost. The 120-second turn cap and retries are not token or
spend caps. Repeated turns/history, multiple tool rounds, and continuous traffic
can spend money indefinitely. Approve model pricing, output-token limits, retry
policy, per-principal quotas and provider-side controls before broad access.

Recommend an alerts-only project budget of $10/month (50%, 90%, 100%, forecast
100%) with approved owner notifications, and separately consider a $5/month Cloud
Run spend cap if available to this billing account. Ordinary
[budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets) do not
stop usage. Current [spend-cap documentation](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
includes Cloud Run, but caps are scoped to one project/service, use gross estimates,
can overshoot due to reporting latency, and allow in-flight work to finish. They
exclude external providers and other service costs; they are not a hard total-dollar
ceiling. A cap can interrupt grading and resets monthly; approval is required.

## Access, grading, and session ownership decisions

No assignment handout or README was found in the repository/parent project tree.
The public URL and exact POST schema are confirmed by the user's assignment
requirements; whether the grader accepts authentication headers is unverified.
A reachable HTTPS URL with IAM authentication may satisfy the URL requirement,
but must not be presented as verified grading compatibility.

Recommended initial access: one explicitly trusted IAM invoker and ephemeral
sessions, with the grading principal approved separately if compatible. If multiple
independent users are admitted, implement verified identity-scoped internal thread
IDs before use: verified issuer/subject + caller-provided session ID. Preserve the
JSON contract and never silently replace the supplied ID. IAM admission alone
does not isolate existing conversation namespaces; a shared service-account token
does not distinguish end users. Do not trust arbitrary identity headers or decoded
JWTs without verification. [Cloud Run token forwarding](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
can strip the `X-Serverless-Authorization` signature; choose a separately verifiable
end-user identity or trusted gateway protocol before implementation.

If the grader cannot authenticate, a temporary publicly reachable demo requires
explicit approval and additional implementation: grader-compatible header/gateway
authentication where possible, verified session ownership, bounded retention,
per-caller/global rate and provider-call/token budgets, a removal date and emergency
access revocation procedure. An entirely anonymous endpoint has no verified user
identity; random session IDs are not authorization. Do not approve anonymous
shared memory as safe by adding random IDs alone. Public Cloud Run IAM admission
would be a separate explicit change, absent from prepared commands. Standard Cloud
Run concurrency and current 429 handling are not per-user or time-based rate limits.

InMemorySaver and session-lock dictionaries have no eviction; restarts, scale-to-zero,
revision replacement and temporary extra instances lose/split history. Maximum 1
is no durability or isolation guarantee. State is disposable for the initial
trusted demo. Future durable checkpoints need a supported database backend,
identity ownership, retention, and cross-instance turn coordination; adding durable
storage alone does not provide these protections.

## Corpus and embedding publication gates

The canonical local bundle is `.artifacts/versions/veridex-rag-v1-local`, pinned
`bundle.json` SHA-256
`6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8`.
It has five PDFs, 615 preserved 1536-dimensional vectors, and validated recovered
text/SQLite/FTS. It remains local/internal, not remotely authorized.

| Document | Evidence and remaining decision |
| --- | --- |
| RAG 2020 | [arXiv v4](https://arxiv.org/abs/2005.11401v4) links its nonexclusive distribution grant to arXiv; downstream bundle permission is not established. Local exact-file modification also needs review. |
| ReAct 2022 | [arXiv v3](https://arxiv.org/abs/2210.03629v3) links CC BY 4.0; verify exact local file and required attribution/notices. |
| Self-RAG 2023 | [arXiv v1](https://arxiv.org/abs/2310.11511v1) links CC BY 4.0; same exact-file/attribution review. |
| NetMHCpan 2020 | Local PDF page 1 states CC BY-NC 4.0; confirm intended noncommercial scope and attribution. |
| MixMHC2pred 2023 | Local PDF page 2 states CC BY-NC 4.0; also review supplementary/third-party material in the 31-page file. |

See [existing exact-file rights review](rag_distribution_review.md),
[arXiv grant](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html),
[CC BY conditions](https://creativecommons.org/licenses/by/4.0/), and
[CC BY-NC conditions](https://creativecommons.org/licenses/by-nc/4.0/).
Distinguish current local usage, private image upload (remote copies of PDFs and
indexed text), and public service output (Workspace reading and evidence quotations).
Private registry access does not establish rights for either remote storage or
downstream content delivery. Finish recipient/use review and required attribution,
license links/notices, and modification notices before approving publication.

If rights remain unresolved, keep this bundle local. Seek rights-holder permission
or approve a new, clearly licensed corpus and versioned index, with grading
requirements reviewed before changing the five-paper corpus. Do not silently
remove papers, suppress the validator, or upload the current image anyway.

Embedding identity remains `unverified-legacy-model`: dimensions and self-query
tests prove structural preservation, not compatibility with current query embeddings.
Seek historical ingestion/model records; if unavailable, approve a new reproducible
corpus/index with explicit model and paid-embedding budget. Do not overwrite old
indexes or assume a live query proves which model produced historical vectors.
An explicitly approved exploratory deployment could acknowledge this uncertainty,
but must not claim reproducibility or semantic retrieval validation.

## Preflight checklist and authorized sequence

1. Approve project/billing, region, budget/cap, model selection, secret operator,
   and exact deployment/publisher/runtime/invoker identities; check organization
   policies and quotas. `gcloud` is not installed in the current local environment.
2. Resolve exact-file distribution conditions for all five PDFs and indexed text;
   prepare approved notices. Approve remote copies and intended service output.
3. Establish embedding provenance or explicitly decide whether exploratory use of
   unverified vectors is acceptable; approve any replacement/re-embedding separately.
4. Confirm grading authentication capability. Approve caller/session ownership and
   retention; implement/test any selected multi-user or public controls first.
5. Separately authorize the resource/IAM/billing provisioning commands, secret
   operator workflow, and budget setup. This document authorizes none of them.
6. Recheck approved local image identity/artifact digest and source exclusions;
   separately authorize one upload to the approved private repository. Capture the
   registry digest, then deploy that immutable digest with approved configuration.
7. Audit private IAM policy, effective scaling/CPU/secrets/probe configuration and
   secret version metadata, then make authorized authenticated health/readiness
   requests. Those requests incur cloud usage but no provider calls.
8. Measure native startup/import/validation/MCP readiness time, warm health latency,
   instance CPU/memory, `/tmp` size, post-idle reuse, and shutdown logs. Record image
   digest, revision, allocation, region and platform; compare against emulated local
   96.15-second startup, sampled ~821 MiB peak and 2.39/5.09-second shutdowns only
   as prior evidence, not native predictions. Capture p50/p95 and OOM/restart events.
9. Obtain separate approval for one bounded live Evidence+Web turn: at most two
   generation requests, one query embedding and one Tavily search; retries zero,
   top_k/max_results 1. Implement a counted fail-closed harness before calls; the
   current production retry configuration does not enforce this plan. Inspect
   private sanitized tool names/status/IDs without logging source text or tokens.
10. Approve grading access only after native checks and provider validation; record
    revocation/rollback procedure. Do not make an unvalidated revision public.

Preflight planning is complete with explicit open decisions. Native performance,
live-provider compatibility, actual project policies/quotas, grading authentication,
rights approval, and embedding provenance are not verified. Step 4.8 needs explicit
authorization and resolution/acceptance of the relevant gates before any mutation.

## Local verification performed for this planning step

- Inspected Dockerfile, entrypoint/runtime, Settings, runner, API/lifecycle/limits,
  MCP connection configuration, ignore rules and existing deployment/security/rights
  reviews. Searched repository/parent tree for assignment/README/AGENTS files.
- Re-ran `validate_bundle` with unchanged recovered `SPEC`, pinned metadata digest
  and `uv.lock`; passed for 615 chunks, five IDs, 1536 dimensions, 11 payload files.
- Compared SHA-256, sizes and mtimes before/after for original `data/index`, recovered
  candidate and final bundle: unchanged. Bundle remains Git-ignored.
- Parsed seven prepared Bash blocks with `bash -n`: passed; none executed.
- `.venv/bin/ruff check .`: passed; `.venv/bin/ruff format --check .`: 90 files
  already formatted; `git diff --check`: passed.
- No application/test code changed; full tests were not re-run for documentation
  changes. Prior Step 4.6 results remain 389 ordinary passed / 38 deselected and 28
  Docker TCP tests passed; these are prior results, not new deployment evidence.
- No image build/push/run, cloud commands, credentials access, or paid provider
  calls. Only the two new planning documents were added; no staging/commit/push.
