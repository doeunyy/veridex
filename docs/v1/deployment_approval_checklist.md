> Current deployment (2026-10-13): the approved public service is
> `veridex-staging-mcp-log-35bbef6` at 100% normal traffic, built from `35bbef6`.
> Digest: `sha256:8657fdecc15737cc29abec5dfdd7f79052332f3065f03e78678044f80cd4a391`.
> Timeout45 remains at 0% for rollback. Provider timeout 45s, retries 0; min0/max1.
> OpenAI's USD 5 enforced limit and Tavily Free/PAYG-disabled settings were manually
> confirmed; the GCP USD 5 budget is alerts-only. Corpus v2 notices and noncommercial
> restrictions remain applicable. Earlier dated planning/approval sections below
> are historical records. See [README](README_v1.md#cloud-run-deployment) for current
> provenance and [commands](cloud_run_commands.md) for prepared rollback/revocation.

# Step 4.7c — public grading approval gate

No cloud mutation, publication, paid provider request or artifact replacement is
approved by this review. Commands remain PREPARED, NOT EXECUTED.

## Assignment-aligned decision

The user supplied findings from the reviewed actual handout: live Cloud Run URL,
exact POST `/chat` JSON, arbitrary reasonable queries, real MCP discovery/invocation,
and at least two turns sharing a session ID. Instance-recycling persistence is not
required. The instructor example permits unauthenticated access and recommends
us-west1/scale-to-zero/max one. Authentication is not expressly forbidden, but the
recommended grading target is anonymous invocation without extra headers/fields.
These findings supersede Step 4.7b's missing-handout assumptions. The raw handout
has not been added locally; no claim is made that this agent independently read it.

Recommend us-west1, colocated registry/service, concurrency 1, active 1/waiting 0,
min 0/max 1, one worker, 1 CPU/2 GiB and startup boost, subject to native measurement.
Both us-west1 and us-central1 have Tier 1 Cloud Run pricing; the course recommendation
and Western US location favor us-west1. No region or cloud configuration changed.

Stage IAM-private. A separate access-administrator function grants allUsers only
following explicit public-grading approval. Setup and initial deployment never make
that grant. No mandatory token/header/cookie is implemented or planned for this
selected anonymous demo. An approved expiry/operator must revoke public admission
and check inherited access after grading; deletion/secret rotation are separate gates.

Anonymous shared session IDs cannot establish ownership. Distinct normal IDs are
separate, but deliberate collisions share/contaminate history. No full cross-user
confidentiality is claimed. Use no confidential input. Verified ownership requires
an authenticated protocol in a future deployment, not a hidden grading constraint.

## Implemented local protections

See [api_security.md](api_security.md) for exact defaults and safe status mapping.
In addition to body/field/admission/deadline/recursion/shutdown controls:

- Eight tool calls/six model calls per turn; over-budget rounds are rejected before
  invocation and interrupted calls repaired. Real MCP tool selection is unchanged.
- Provider completion cap 4096 per generation request, timeout 30s and retries 0;
  embeddings share explicit timeout/retry settings. Existing Tavily 20s/single POST.
- Model input capped at 64,000 serialized message characters (not exact token cost).
- Session cap 128; idle TTL 30 minutes; active/waiting sessions protected from expiry.
  Full unexpired capacity gives 429, never silent LRU eviction.
- Six complete recent human turns; exact default InMemorySaver compacted through
  public APIs after turns/repair under session lock. Same saver persists across
  requests, with one latest checkpoint; default memory/bookkeeping cleared on close.

No aggregate durable rate/spend ceiling, verified ownership or external-provider
billing guarantee is implemented. Provider token overhead, embedding splitting,
optional retries, continuous traffic and restarts matter. Step 4.7d has now verified the changed code in a new local image with 32 Docker
TCP tests. See [release readiness](release_readiness_47d.md); rights/notices and
publication gates remain. Any further packaging change needs new image verification.

## Corpus rights and attribution

[rag_attribution.json](rag_attribution.json) records all five exact PDF SHA-256s,
authors/titles/source URLs, licenses/evidence, notices and extraction/normalization
changes. It is an attribution inventory, not a publication authorization or a complete
bundled license package. PDFs/index/bundle remain unchanged. Applicable license
notices must accompany an approved image and be available to service recipients.

| Paper | Findings | Remaining disposition |
| --- | --- | --- |
| RAG 2020 | arXiv v4 nonexclusive grant authorizes arXiv distribution, not established downstream rights. Local file is modified. NeurIPS availability alone is no downstream grant. | Obtain applicable permission/evidence or approve replacement before publication. |
| ReAct 2022 | arXiv v3 CC BY 4.0; local authors/version identified, no interior license notice found. | Conditional retention; verify exact local material is covered, preserve attribution/notices. Canonical licensed file replacement is an alternative, not performed. |
| Self-RAG 2023 | arXiv v1 CC BY 4.0; same exact-material limitation. | Conditional retention with attribution/source/license/modification information. |
| NetMHCpan 2020 | Exact six-page PDF p1 CC BY-NC 4.0 and copyright notice; PMC publisher-hosted article now corroborates it. | Retain for confirmed compliant noncommercial coursework with attribution; no general commercial permission claimed. |
| MixMHC2pred 2023 | Exact PDF p2 CC BY-NC 4.0. Pages 19-31 are article STAR+METHODS through e13; not a separately identified supplement. No additional exclusion notice located in text review. | Conditional retention for noncommercial coursework; retain authors/publisher notices. Third-party figure/material scope is not comprehensively cleared. |

Educational purpose or private registry alone does not authorize redistribution.
Compliant CC-covered reuse need not require a separate grant; user approval cannot
supply missing copyrights. A commercial/broadly reused service would need a new
noncommercial/scope assessment. Do not bundle unreviewed linked supplementary
files, datasets, source code, or third-party material merely because the paper is open.

Minimum fallback is rights evidence for the current paper; otherwise replace only
RAG with one approved topic-equivalent paper. Candidate sources:

- [Li et al., EMNLP Industry 2024](https://aclanthology.org/2024.emnlp-industry.66/),
  “Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and
  Hybrid Approach.” Anthology's post-2016 CC BY 4.0 policy provides candidate license
  evidence; exact downloaded PDF/scope and attribution still need validation.
- [Niu et al., ACL 2024, RAGTruth](https://aclanthology.org/2024.acl-long.585/), a more
  evaluation-oriented alternative under the same anthology policy. Confirm course
  corpus expectations and topical suitability before choosing either.

These are candidates, not approved replacements. A different work gets a truthful
new paper ID/filename and separate versioned manifest/index/bundle. Counts/chunk IDs
may change; do not fabricate 615. Update SPEC/checksums/fixtures, native retrieval
and semantic evaluation, license notices and image pin through reviewed changes.
Keep remaining papers only when their conditions pass; replace any NC material if
intended use falls outside its grant. Never change protected old artifacts.

## Embedding model provenance and rebuild proposal

Git foundation fc9ba8f and embedding implementation 757677d configure
text-embedding-3-small. Settings allow env overrides. Neither ignored local PDFs/index
nor an ingestion-run attestation is versioned. Read-only original/recovered SQLite
collections have dimension 1536, config `{}`, no collection model metadata, no chunk
model field and only an unknown sparse function in schema. Bundle still explicitly
records unverified-legacy-model. These facts make small a hypothesis, not verified
historical provenance. Self-query/preservation tests do not establish compatibility
with newly generated query vectors. No secret files/provider records were accessed.

If reliable operator run records linked to the source fingerprint exist, review
those first. Otherwise choose explicitly between accepted exploratory uncertainty
with approved limited live evaluation and regeneration for known provenance.

Proposed rebuild, NOT EXECUTED: approved corpus into a new directory; fixed
manifest/PDF hashes, locked parser/chunker versions, deterministic chunking and
reviewed text normalization, explicit OpenAI text-embedding-3-small model ID with
1536 dimensions (subject to model approval), offline token-count/cost estimate and
paid-call allowance. Record effective/returned model identity, date and provider
response metadata, chunk/vector hashes and dependencies. Model aliases can change;
claim deterministic input preparation plus a pinned evaluated output snapshot,
not future byte-identical provider outputs. Re-embed all approved chunks if old
model cannot be verified; don't mix new and old vectors merely on equal dimension.
Validate IDs/metadata, finite FLOAT32 vectors, SQLite/FTS/contains, native vector
retrieval plus semantic queries/citations, checksum inventory and container reopening.
Old indexes/bundles stay intact; no API calls or rebuild are approved by this plan.

## Final decision table

| Category | Item | Status/action |
| --- | --- | --- |
| Confirmed implementation | Exact HTTP schema, real 3-server/4-tool MCP, ordinary two-turn memory, cancellation | Existing behavior retained and local budget/retention regressions added |
| Confirmed artifact | Local recovered 615-vector/five-paper snapshot | Protected files unchanged; publication authorization absent |
| Resolved assignment fact | Public example/us-west1/two-turn/recycling requirements | Supplied reviewed-handout findings; adopt anonymous grading recommendation |
| Factual blocker | Exact arXiv-file license scope, historical model attestation, project policies/quotas | Still unresolved; approval cannot convert assumptions into verification |
| Rights blocker | RAG downstream permission; attribution/NC and third-party scope conditions | Resolve or approve a rights-compliant separate corpus workflow |
| Technical follow-up | Local image/Docker checks passed in 4.7d; native Cloud Run and live providers pending | Local code tests now; container rebuild before upload; native/live only after authorization |
| User approval | Anonymous session limitations, rights-compliant corpus, provenance acceptance/rebuild | Explicit choices required; no mandatory grading authentication |
| User approval | Project/billing/identities/secrets/model/budget/expiry; publication/deployment | Placeholders remain; no cloud action authorized |
| Prohibited now | GCP/IAM/billing mutation, image push, paid calls, corpus writes, Git stage/commit/push, PROCESS_LOG edits | None performed |

Minimum work before Step 4.8: resolve rights/notices or approved replacement;
choose provenance acceptance/new-index path; approve public risk/provider allowance
and expiry; rebuild/test the local image with approved notices and current code;
fill project/runtime/deployer/model/budget references; approve named provisioning,
publication and private deployment actions. Native health/resources and a separately
approved counted live turn precede the explicit public-admission grant.

Cloud deployment is not yet ready for approval: access design and local safeguards
are prepared, but artifact rights/provenance decisions, attribution release packaging and
concrete cloud/public spending approvals remain. README, three diagrams and
PROCESS_LOG final narrative are deferred to Step 4.11; none was modified here.

## Step 4.7c verification

- `.venv/bin/python -m pytest -q --tb=short`: **400 passed, 38 deselected**,
  five existing PyMuPDF/SWIG warnings, 151.81 seconds.
- `.venv/bin/python -m pytest tests/test_agent_budgets.py tests/test_api_lifecycle.py tests/test_api_limits.py tests/test_agent_mcp.py -q --tb=short`:
  **66 passed** at that focused checkpoint, 52.20 seconds. Later added budget/guard
  regressions are included in the final ordinary and targeted results below.
- `.venv/bin/python -m pytest tests/test_agent_budgets.py tests/test_agent_mcp_protocol.py tests/test_agent_mcp_reliability.py -k 'not live_llm' -q --tb=short`:
  **18 passed, 1 deselected**, 29.29 seconds. Real STDIO processes, deterministic LLM/
  provider fixtures; routing, memory/isolation, cancellation/cleanup and limits.
- Live-test guard verification with the single live test and `-m integration`:
  **1 skipped** without opt-in, 1.85 seconds; no provider construction/request.
- Ruff lint/format passed (93 files formatted); `git diff --check` passed.
- Unchanged artifact validator passed: 615 chunks, five IDs, 1536 dimensions.
  All 29 protected files matched SHA-256, size and mtime. Attribution hashes match
  all five PDFs. Eight command blocks passed Bash syntax checks; none executed.

Verification incident: an earlier overly broad `-m integration` selection selected
one legacy live test. It attempted an OpenAI connection and failed at DNS resolution
before a provider response/request could be reached. It was not retried or escalated.
The test now requires explicit `VERIDEX_RUN_LIVE_PROVIDERS=1`, with an ordinary
regression verifying its skip before provider use. No successful live-provider
validation was performed; do not characterize the investigation as having made no
connection attempt. Initial queue/concurrency regressions were corrected by explicitly
enabling the higher limits those tests intend to exercise, preserving their assertions.

No cloud mutation, image build/push/publication, paid embedding regeneration,
corpus write, dependency/production MCP-server change, Git staging/commit/push,
README/PROCESS_LOG/development-notes change was performed. The existing image and
prior 28 Docker E2E passes are historical evidence, not verification of this changed
source. A new offline image build/E2E run remains before publication approval.


## Step 4.7d current release gate

[release_readiness_47d.md](release_readiness_47d.md) records the exact new image,
32 Docker TCP passes, 400 ordinary tests, non-root production startup at 1 CPU/2 GiB,
101/104-second emulated cold starts and 3.00/5.67-second idle/active shutdowns.
RAG downstream rights remain the priority blocker; four other papers have conditional
retention/license evidence. Attribution is not yet packaged for image/service
recipients. Historical model identity stays unverified: choose explicit coursework
uncertainty acceptance or a separately approved coherent new index. Proposed cloud
timeout is now 300s because Cloud Run includes startup, with native tuning required.
All public/provider/cloud/registry action gates remain unapproved. No PDF downloads,
corpus changes, provider API calls, GCP changes or image pushes occurred in 4.7d.

## Step 4.7h superseding release gate

Corpus v2 replaces RAG 2020 with the approved ACL CC BY paper; all 586 vectors now
have recorded `text-embedding-3-small` provenance. Image/service attribution is
implemented. [Current release evidence](release_readiness_47h.md) supersedes the
v1 rights/model/notice blockers above, preserving those sections as history.

Before Step 4.8 explicitly approve:

1. Noncommercial coursework recipients/use and dated demo expiry; acknowledge the
   two CC BY-NC papers and third-party scope limitations. Commercial expansion needs
   new permission/replacement review.
2. Public grading invocation and anonymous session-ID collision/no verified ownership
   risks; memory is per-instance and neither durable nor confidential for colliding IDs.
3. Generation model, separately counted live OpenAI/Tavily validation plan, ongoing
   provider spending allowance/caps and shutdown/expiry procedure. No new paid call is
   authorized by the completed embedding run or offline Docker tests.
4. Exact GCP project/billing, us-west1 region, registry/service, runtime and deployment
   identities, per-secret access and enabled Secret Manager versions (never key values).
5. Publication of the exact reviewed image to the named registry/recipients, followed
   by the named provisioning/IAM/private deployment operations; separately approve
   public admission after native/live acceptance.

Local technical validation is complete; native Cloud Run performance and live
provider behavior remain unmeasured. No cloud mutation or remote publication has
been authorized or performed. PROCESS_LOG/README finalization stays Step 4.11.

## Step 4.8.0 confirmed decisions and next gate

[Environment preparation](gcp_preparation_480.md) is the current approval record.
Confirmed: us-west1, IAM-private staging first, noncommercial coursework with the
two CC BY-NC restrictions acknowledged, $5 monthly GCP alerts, v2 release, 1 CPU/2 GiB,
min 0/max 1, concurrency/application active 1/waiting 0, runtime Secret Manager.
These choices are not new permission requests. Anonymous public invocation, resource
creation, IAM/billing changes, image upload and paid provider calls remain unapproved.

Read-only checks found no gcloud installation, so active login/configuration, existing
projects, billing and USC credits remain unverified. Docker Buildx and the exact v2
image/bundle identity were checked without rebuild/publication. Next select the
project/billing/parent, exact principals/resource names/recipients; approve CLI setup
if needed, then the specifically named Step 4.8.1 provisioning actions. $5 alert
creation still needs action approval; optional Cloud Run spend caps need separate
eligibility/permission/availability checks and approval. Public grading and live
provider allowances remain later gates. No cloud command was executed here.

## Step 4.8.1b resource review

Current [A–E provisioning review](gcp_provisioning_review_481b.md) confirms USC login,
ACTIVE project `zeta-store-511505-i7` / number `<PROJECT_NUMBER>`, linked open USD billing,
no us-west1 repositories/services, and no `veridex-runtime` SA. An existing Compute
default account is left untouched. Cloud Run/Registry/Service Usage are enabled;
IAM, Secret Manager and Billing Budgets are proposed missing enablement. Prompts
for the latter two were explicitly declined. Secret/budget collisions and budget
permission/recipient checks remain pending until approved A enables their APIs.

Approve only A first if desired; E can follow successful read-only budget checks
before billable contents, and B/C/D require individual approval. The current user
is project Owner; narrow grants to that same identity would not narrow Owner.
Runtime receives only two secret-scoped Accessor grants. No API/resource/IAM/budget
mutation, key creation, image upload, Run deployment or public access occurred.
