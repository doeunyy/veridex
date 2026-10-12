# Step 4.7b — blocker resolution and final approval gate

Reviewed 2026-10-12. Planning only: Step 4.8 remains unauthorized. This supplements
[preflight](cloud_run_preflight.md) and the [unexecuted commands](cloud_run_commands.md).
No original, recovered, or bundled artifact is replaced by these recommendations.

## Assignment and smallest viable access design

No CSCI 599 Assignment 1 handout/README was found in the repository, its parent
project tree, or tracked filename history. The exact `/chat` JSON and public URL
requirements are supplied by the user. **Whether grading requires requests without
authentication is unverified.** A URL being reachable is not proof that IAM-protected
requests satisfy grading. Obtain the handout or instructor confirmation of accepted
headers, cookies, Google identities, session behavior and any required paper corpus.

| Grader capability | Smallest proposed design | Security/compatibility gate |
| --- | --- | --- |
| Google ID token supported | IAM-private Cloud Run; one approved trusted principal for a single-user demo | Confirm grader can obtain/send an audience-appropriate token. Multiple independent callers still need application session ownership. |
| HTTP bearer header supported, Google IAM unsupported | Internet-reachable demo with application bearer authentication; one high-entropy revocable credential per approved caller, mapped server-side to a caller identity | Requires explicit Cloud Run public-admission approval, auth/ownership implementation and a new runtime-secret plan. A shared credential represents one trust domain, not separate users. |
| Cookies supported but no supplied auth header | A separate reviewed capability/session-cookie design may be possible | Grader cookie persistence and credential bootstrap are unverified; do not implement or claim compatibility yet. |
| Bare anonymous JSON only | Current shared-memory API cannot establish caller ownership | No verified caller signal distinguishes two people selecting the same session ID. Need instructor-approved protocol support or an approved behavior change; do not claim random IDs, IP addresses or max_instances=1 solve ownership. |

Recommendation: confirm headers first. Prefer IAM if accepted; otherwise a small
application bearer-auth layer is less infrastructure than a gateway/load balancer
for this demo. It preserves request `{"query":"...","session_id":"..."}` and
response `{"response":"..."}`. Internally namespace threads by the registered
caller identity and supplied session ID; keep the caller's ID unchanged. Reject
missing/invalid credentials before Agent admission, using fixed errors and
constant-time credential comparison. Never use the secret token itself as the
stored thread ID, and never trust an unverified identity header.

For multiple IAM users, verify a suitable end-user identity token or approved
gateway identity before namespacing. Cloud Run admission alone is insufficient;
[token forwarding](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
has header/signature semantics that must be tested before relying on an application
JWT verifier. No authentication/ownership code is implemented in this step.

Any reachable paid-provider demo also needs explicit global/per-caller request
quotas, counted provider-call/output-token limits, bounded session count/history/TTL,
and an expiry/revocation policy. Concurrency 1 and maximum 1 are capacity controls,
not rate, session-memory or spend limits. Proposed initial time-based quotas must
be selected against expected grading traffic, not invented as grading requirements.
Suggested review starting point: five chat admissions/minute per credential,
100 total accepted turns per grading window, and a fixed provider-dollar allowance;
approve actual numbers and enforce provider reservations before calls. An elapsed
time limit cannot enforce a dollar allowance. In-process counters are not durable
across restarts/temporary extra instances; combine them with independently enforced
provider/account controls or a durable quota store when a hard aggregate allowance
is required. Verify whether provider controls are enforced limits or alerts.

For a single trusted IAM demo, accepting disposable process-local memory is the
smallest initial policy. For public/multiple-caller operation, implement ownership
and retention before deployment. A process restart can lose history even with
max_instances=1; statefulness, durability and user isolation are separate properties.

## Five-paper rights decisions

Existing exact-file findings are in [rag_distribution_review.md](rag_distribution_review.md).
Rechecked arXiv license links and both local biomedical PDF notices. The applicable
[CC BY](https://creativecommons.org/licenses/by/4.0/legalcode.en) and
[CC BY-NC](https://creativecommons.org/licenses/by-nc/4.0/legalcode.en) grants can
authorize covered reuse if their conditions are met; an additional rights-holder
permission is not automatically necessary for a compliant CC-licensed use. User
approval here authorizes our deployment action; it cannot confer missing copyrights.

| Paper | Evidence | Disposition before remote publication |
| --- | --- | --- |
| `rag_2020` | arXiv v4 uses an [arXiv distribution grant](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html), not a downstream public license. The [NeurIPS paper page](https://proceedings.neurips.cc/paper/2020/hash/6b493230-Abstract.html) provides access but no downstream grant was established; its [copyright FAQ](https://neurips.cc/FAQ/Copyright) describes a grant to NeurIPS. | Obtain applicable permission or approved license evidence for the intended use. If neither is available, replace this paper before publishing this corpus. Downloading the NeurIPS copy alone does not resolve rights. |
| `react_2022` | [arXiv v3](https://arxiv.org/abs/2210.03629v3) links CC BY 4.0 | Keep if exact local text/material is covered and notices/attribution are completed; no demonstrated need to replace it. |
| `self_rag_2023` | [arXiv v1](https://arxiv.org/abs/2310.11511v1) links CC BY 4.0 | Same conditional retention as ReAct. |
| `netmhcpan_2020` | Local PDF p1: CC BY-NC 4.0 | Keep for a use that satisfies noncommercial conditions and attribution; hosting on paid infrastructure alone does not establish commercial purpose. Confirm actual purpose/recipients; seek separate permission or replace if the planned use falls outside the grant. |
| `mixmhc2pred_2023` | Local PDF p2: CC BY-NC 4.0; additional material included | Same noncommercial decision, plus supplementary/third-party scope review. Replace or omit unlicensed material only through an approved new corpus if scope cannot be established. |

Complete a notices inventory with creators, title/source/version, license link,
supplied copyright/disclaimer notices and relevant modification information,
including extraction and the two-character recovered-chunk normalization where
applicable. License conditions also apply to indexed source text and service
outputs; storing PDFs privately is not a blanket permission to redistribute text.
Check that required notices accompany the distributed image and are available to
service recipients without changing the `/chat` JSON schema. If the present image
lacks required notices, the future reuse/push command is blocked until a reviewed
notices packaging change, local rebuild and verification produce a new approved
image digest. Keep immutable old bundles unchanged; do not infer that the current
Docker image already has a complete attribution package.
Local possession, private remote image copies and public Workspace/Evidence output
are separate uses to review. No blanket fair-use or educational exemption is assumed.

Minimum-change fallback, **not executed**:

1. Prefer establishing rights for the existing five papers, preserving all artifacts.
2. If RAG permission remains unavailable, propose replacing only that paper with an
   instructor-approved, source-verified CC BY/CC0 paper covering the required topic;
   no specific substitute is represented as approved. Retain the other four only
   after their conditions pass. For a noncommercial-scope failure, replace the
   affected biomedical paper(s) as well.
3. Use a separate versioned corpus/manifest/index/bundle. Give a different paper a
   truthful new paper ID and Workspace filename; never label it `rag_2020`. Preserve
   remaining paper IDs, page attribution and metadata. New pagination/chunk text
   can change chunk IDs and counts; 615 is the old snapshot invariant, not a count
   to fabricate for the replacement. Verify assignment acceptance before proceeding.
4. Pin input file hashes, parser/chunker/dependency versions and model/dimensions.
   Because legacy model identity is unresolved, do not combine newly generated
   embeddings with old vectors on dimensional equality alone. If provenance cannot
   be established, regenerate the entire approved corpus in one coherent embedding
   space with an explicit paid-call budget.
5. Revalidate SQLite/FTS, documents/metadata/vector consistency, functional filtering,
   native retrieval and semantic relevance, package inventory and checksums; update
   runtime SPEC/digest and affected fixtures through explicit reviewed changes.
   Build a newly approved image after tests. Preserve all old artifacts for rollback.

## Embedding provenance investigation

Verified local evidence:

- Git foundation `fc9ba8f` sets `text-embedding-3-small` in Settings and `.env.example`.
  Searching all refs for `text-embedding` found no alternative configured model in
  tracked source history. Initial embedding implementation `757677d` and current
  `embeddings.py` both construct OpenAIEmbeddings from Settings.
- Settings permit environment/ignored `.env` overrides. Neither source defaults nor
  tests attest to the effective configuration of a particular ingestion run.
  No secret file or provider account was accessed in this investigation.
- Git tracks the manifest/evaluation questions, not the SQLite index/PDFs. There is
  no versioned ingestion-run record linking this database fingerprint to an API
  response model identity or effective ingestion configuration.
- Read-only SQLite inspection of original and recovered candidates shows collection
  `veridex_documents`, dimension 1536, `config_json_str='{}'` and no collection metadata.
  Schema inspection also found only a sparse-vector function marked `unknown`,
  with no dense model identity; chunk metadata has no model-origin field. Thus
  those records provide no historical model identity.
- Pinned `bundle.json` still declares `unverified-legacy-model`; recovery preserves
  FLOAT32 vectors and records source hashes. A preservation attestation is not a
  model-origin attestation. Self-query tests verify existing vector structure, not
  new query embedding semantic compatibility.

Conclusion: `text-embedding-3-small` is a plausible hypothesis, **not verified**.
Additional operator ingestion logs/API records tied to the source fingerprint
could establish provenance if they exist; they were not found in inspected records.
Comparing freshly embedded sample vectors would require paid-call approval and
cannot by itself prove the origin of every historical vector.

| Option | Benefit | Limit / approval |
| --- | --- | --- |
| Accept documented uncertainty | Preserve all 615 vectors; no re-embedding cost or artifact changes | Explicit exploratory-use acceptance; mark semantic compatibility/reproducibility unverified, approve limited live query checks separately. Not a claim that the model is known. |
| Establish historical evidence | Can preserve vectors with a supportable model attestation | Requires reliable run/model evidence linked to the database fingerprint; current Git defaults are insufficient. |
| Regenerate approved corpus | Known configured model, dimensions and corpus/run provenance; one coherent vector space | Separate paid API budget, new index/version/validation/image; never rebuild the protected original. Pin a provider model/version where supported and record returned identity/date; mutable model aliases are not a guarantee of future byte-identical outputs. |

Recommendation: seek operator evidence first. If unavailable, explicit uncertainty
acceptance is the minimum-change exploratory path; regeneration is preferred for a
reproducibility claim and necessary to avoid unverified mixed spaces after replacing
documents. Token count/cost must be estimated offline from the approved new chunks
before requesting a paid embedding allowance. No embeddings were generated here.

## Command security review

- Prepared deploy commands require IAM (`--no-allow-unauthenticated` and
  `--invoker-iam-check`); `--ingress=all` controls reachability, not authorization.
  No public grant is included. Also inspect inherited project/ancestor IAM; a
  service-only policy audit is insufficient to rule out effective broad access.
- Runtime secret access is scoped to two secrets; no Owner/Editor or registry writer
  is granted to runtime. Bootstrap administrators need temporary creation authority;
  routine deployer and publisher grants stay resource-scoped. A deployer able to
  execute code as the runtime SA is trusted with its effective secret access, even
  without direct Secret Accessor. Require reviewed image digests and trusted deployers.
- Numeric secret references expose names/versions, not values. No payload retrieval,
  key files, shell tracing or secret build arguments are in the plan. Audit existing
  literal env settings before printing descriptions of reused services.
- Min 0/max 1 and budgets reduce exposure but do not bound provider spend. No paid
  request should be made until a counted live-test plan is approved. Current code
  lacks a persistent aggregate spend/rate limiter and unbounded histories remain.
- Command blocks are sequential review material, not an idempotent run-all script.
  Resolve every placeholder and verify effective IAM, digest and model decisions;
  do not treat shell syntax checks as cloud-side validation. The CLI is not installed.

## Decision table and approval checklist

| Category | Item | Status / next gate |
| --- | --- | --- |
| Confirmed implementation | Exact HTTP contract, persistent MCP, cancellation/shutdown, offline Docker E2E | Prior 389 ordinary / 28 Docker passes; no live-provider/native Cloud Run verification |
| Confirmed artifact | Five papers, 615 FLOAT32 vectors, dimension 1536, recovered integrity and pinned bundle | Existing validated local/internal snapshot; unchanged by this step |
| Outstanding factual check | Assignment authentication and paper-substitution requirements | Handout/instructor confirmation needed; IAM grading compatibility unverified |
| Outstanding factual check | Exact-file license scope/notices, intended noncommercial purpose, RAG permission | Resolve before remote PDF/index copies or public source output |
| Outstanding factual check | Historical ingestion model; project policies/quotas; native performance | Model unresolved; cloud checks only after separately authorized access/deployment |
| User approval | IAM versus application-auth demo; callers/ownership/retention/quotas and grading window | Approve one design; implement/test missing controls before public/multi-user use |
| User approval | Rights-compliant corpus versus replacement | User approval cannot substitute for missing rights; authorize new artifacts/re-embedding only separately |
| User approval | Accept embedding uncertainty versus verified new index | Record choice and any paid-call/model budget explicitly |
| User approval | Project/billing/region, identities, budgets/cap, secret operator, image digest and remote recipients | Concrete identifiers still unset; secrets entered outside this agent |
| User approval | Provisioning, publication, private deployment, live test, later grading access | Separate action gates; no approval inferred from review or prior local builds |
| Prohibited now | Cloud mutations, IAM/billing changes, Docker push/publication, paid providers | Not performed; remain prohibited without explicit authorization |
| Prohibited now | Artifact replacement/re-indexing, original/recovered/bundle writes, Git stage/commit/push, PROCESS_LOG edits | Not performed; no artifact replacement authorized |

Minimum path to Step 4.8: confirm grader capability -> choose/approve access and
session policy -> resolve rights/notices (or approve replacement workflow) ->
choose provenance acceptance/regeneration -> implement/test required controls ->
fill project/identity/model/budget placeholders -> approve the named publication
and provisioning/deployment actions. Limited live-provider and native validation
follow an authorized private deployment and precede grading exposure.

Step 4.7b investigation is complete. **Step 4.8 is not ready for unconditional
deployment approval**: unresolved factual/access/rights decisions still determine
what may be published and how grading can safely invoke it. The plan is ready for
those specific decisions; none of the prohibited actions is authorized.

## Verification for this step

The unchanged artifact validator passed against the pinned bundle/lock/SPEC:
615 chunks, 1536 dimensions, five IDs. All 29 protected original/recovered/bundle,
PDF and manifest files retained their recorded SHA-256, size and modification time.
Seven prepared Bash blocks passed `bash -n`; none executed. Ruff lint passed,
format check reported 91 files already formatted, and `git diff --check` passed.
Changes are confined to five planning/security/rights documents. Application code
and tests are unchanged; ordinary/Docker suites were not re-run for documentation
changes. No paid providers, cloud operations, remote publication, artifact writes,
Git staging/commit/push, or PROCESS_LOG changes were performed.
