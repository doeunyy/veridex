# Step 4.8.0 — GCP discovery and approval-gated preparation

Preparation only, 2026-10-12. No cloud mutation or paid provider request is
approved. No gcloud installation/authentication, active-project changes, Docker
rebuild/tag/push, secret access, provisioning, IAM changes or deployment occurred.
Only planning documents were updated. Confirmed decisions will not be re-requested;
resource/action authorization is a separate gate.

## Discovery performed and remaining Console checks

Git worktree was clean at entry. Local checks found:

| Tool/fact | Read-only result |
| --- | --- |
| gcloud | Not in PATH or checked Homebrew/standard SDK locations |
| Docker / Buildx | `/usr/local/bin/docker`; Buildx `v0.11.2-desktop.1`; local daemon image inspection succeeded |
| uv / Git / Python | uv 0.12.23, Git 2.43.0, project Python 3.13.16 |
| gcloud account/configuration/projects/billing | Not queried: gcloud unavailable. Authentication and existing projects are **unverified**, not known absent. No credential-cache files were inspected. |
| USC account / educational credit | Unverified; no access to institutional billing or credit records |

In Cloud Console the user must check: signed-in account and permitted coursework
use; project selector for existing suitable projects; organization/folder and
project-creation authority; Billing -> My projects for the linked/open billing
account; Billing -> Credits for any educational grant, amount, expiry and covered
services; currency and account type; budget-recipient permissions/delivery; API and
us-west1 policies; public-invocation/domain-restriction policy; spend-cap UI and
permissions. A USC login alone does not prove credits or billing authorization.
Prefer an approved suitable existing coursework project; do not assume ownership,
credit eligibility or permission to use a shared USC billing account.

After separately approved CLI installation/login, these commands are read-only
local/cloud discovery, not executed here:

```bash
gcloud version
gcloud config configurations list --format='table(name,is_active)'
gcloud config get-value account
gcloud config get-value project
gcloud config get-value run/region
gcloud auth list --filter=status:ACTIVE --format='table(account,status)'
gcloud projects list --format='table(projectId,name,lifecycleState)'
gcloud billing accounts list --format='table(name,displayName,open)'
# Only after selecting a project; use an explicit approved ID.
gcloud projects describe "$VERIDEX_PROJECT_ID" --format='yaml(projectId,projectNumber,parent,lifecycleState)'
gcloud billing projects describe "$VERIDEX_PROJECT_ID" --format='yaml(projectId,billingAccountName,billingEnabled)'
gcloud services list --enabled --project="$VERIDEX_PROJECT_ID" --format='value(config.name)'
```

Never print access/ID tokens, ADC files or service-account private keys. Installation,
`gcloud auth login` and `gcloud auth configure-docker` are local configuration/credential
mutations requiring their own later authorization. Do not run `gcloud config set
project`; subsequent commands use explicit project/region and the approved operator.

## Proposed inventory — identifiers not approved

| Resource | Concrete proposal | Outstanding check |
| --- | --- | --- |
| New project candidate | `veridex-usc599-2026`, display name `Veridex CSCI 599 Coursework` | Global availability, parent and billing; prefer existing approved project if available |
| Region | `us-west1` | Confirmed user decision; institutional policy still unverified |
| Artifact Registry | Docker repository `veridex`, private, `us-west1` | Name/creation/publication approval |
| Cloud Run | `veridex-staging`, `us-west1`; same URL can later become grading URL | Name/creation approval; initially IAM-authenticated |
| Runtime identity | `veridex-runtime@<APPROVED_PROJECT_ID>.iam.gserviceaccount.com` | Dedicated SA, no keys |
| Deployment identity | `user:<APPROVED_GCLOUD_LOGIN>` | Approved human login; separate from runtime SA; no new deployer SA needed initially |
| Publisher/access/secret operators | Approved human principals; one person can hold distinct scoped duties | Exact principals/permissions pending |
| Secret Manager | `veridex-openai-api-key`, `veridex-tavily-api-key` | Create approval; trusted operator supplies values directly, never to this agent |
| Budget | `Veridex coursework monthly USD 5 alerts` | $5 amount confirmed; account/project/recipient/action approval pending |
| Remote image tag | `us-west1-docker.pkg.dev/<PROJECT>/veridex/veridex:phase04-v2-47h` | Proposed only; no remote digest exists |

Do not assign a random suffix or use an unavailable project ID without review.
No Cloud SQL, GKE, VM, VPC connector/NAT, load balancer, scheduled warm-up, Cloud Build
or additional persistent infrastructure is needed for the initial demo.

## APIs and least-privilege stages

Runtime/publication prerequisites: `run.googleapis.com`,
`artifactregistry.googleapis.com`, `secretmanager.googleapis.com`,
`iam.googleapis.com`. Bootstrap/discovery can also require
`serviceusage.googleapis.com`, `cloudresourcemanager.googleapis.com`, and
`cloudbilling.googleapis.com`; inspect existing enablement and enable only missing
approved APIs. `billingbudgets.googleapis.com` is needed for the optional budget CLI
workflow in the chosen administration/quota project; Console budget creation is an
alternative. `iamcredentials.googleapis.com` is only needed if an approved workflow
uses SA impersonation; user login avoids that initial dependency. Cloud Build API
is not needed for pushing this already-built image. Default service logs/metrics use
Google-managed integrations; optional logging/monitoring API changes are separately
reviewed if metadata queries require them.

| Stage/identity | Scoped predefined roles or required permissions |
| --- | --- |
| Optional project creation | `roles/resourcemanager.projectCreator` on approved organization/folder; skip if reusing a project |
| Billing linkage | `roles/billing.user` on approved billing account and `roles/billing.projectManager` on target project; skip if already correctly linked |
| API/bootstrap operator | `roles/serviceusage.serviceUsageAdmin` for enablement; `roles/artifactregistry.admin`, `roles/iam.serviceAccountAdmin`, `roles/secretmanager.admin` only as needed for resource creation. Project IAM bindings require `resourcemanager.projects.setIamPolicy` (e.g. temporary `roles/resourcemanager.projectIamAdmin`). Prefer existing administrator/custom narrowed permissions; do not grant these to runtime. |
| Budget operator | Existing billing operator with budget create/update/read permissions, e.g. `roles/billing.costsManager` at billing-account scope for alerts-only budgets; optional spend-cap permissions are additional and must be verified |
| Image publisher | `roles/artifactregistry.writer` on this repository only |
| Initial Run create/access admin | `roles/run.admin` at project scope for first creation/access policy, plus `roles/iam.serviceAccountUser` on runtime SA and repo Reader; narrow/remove broad grants afterward |
| Routine deployer | `roles/run.developer` on created service, `roles/iam.serviceAccountUser` on runtime SA, `roles/artifactregistry.reader` on repository |
| Runtime SA | `roles/secretmanager.secretAccessor` on exactly the two secrets; no Owner/Editor, deployment, registry writer or billing role |
| Secret-value operator | `roles/secretmanager.secretVersionAdder` on these two secrets; use trusted Console workflow without showing values to this agent |
| Staging invoker | `roles/run.invoker` on this service only |

Google's [deployment roles](https://docs.cloud.google.com/run/docs/deploying) separate
deployer permissions from [runtime identity](https://docs.cloud.google.com/run/docs/securing/service-identity).
The Google-managed Cloud Run service agent pulls same-project images through its
standard service-agent permissions; do not assign service-agent roles to humans or
the runtime SA. If project boundaries change, explicitly review repository access.
A new service cannot be the scope of a role binding before it exists. Bootstrap and
access-policy administrators are separate duties from routine revision updates.
Exact principal/role grants remain unapproved.

## Existing release and publication gate

Read-only Docker inspection matched the verified release:

- Local tag `veridex:phase04-v2-local`, Linux/amd64, UID/GID 10001.
- Local image configuration ID:
  `sha256:38c2bb0aed856da0fa8724e4ffc0dd27cf4c461b69b97b8822d5b854ee544289`.
- Size 834,267,880 bytes; `RepoDigests=[]`.
- Pinned bundle metadata SHA-256:
  `7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
- Read-only strict bundle validation also passed all 11 payload files, inventory,
  checksums and SQLite/FTS5 checks without opening Chroma through its public API.
  Source bundle metadata lists collection `veridex_documents`, 586 chunks, dimension
  1536, `text-embedding-3-small`, and exactly `rag_long_context_2024`, `react_2022`,
  `self_rag_2023`, `netmhcpan_2020`, `mixmhc2pred_2023`.

Image identity matches [4.7h verification](release_readiness_47h.md), which established
correct papers, image notices, GET `/attribution`, original/corrupt/v1 exclusions,
non-root Linux checks and 33 offline TCP tests. It was not rebuilt or rerun here.
The local image configuration ID and bundle metadata digest are **not an OCI registry
manifest digest**. Only after explicit image-byte publication approval: verify the
local ID again, configure approved Docker credentials, tag that exact image, push
to the approved private repository, obtain/review the registry manifest digest,
and deploy using `.../veridex@sha256:<REGISTRY_MANIFEST_DIGEST>`. Stop if identity
changes. Tagging and credentials configuration are also mutations, prepared only.

[cloud_run_commands.md](cloud_run_commands.md) contains the reviewed, unexecuted
create/IAM/tag/push/private-deploy/public/cleanup commands. Stale v1 publication
commands have been updated to v2. No image bytes may be pushed merely because the
region, use or local release was approved.

## Private staging configuration and validation gate

Use the reviewed `gcloud run deploy` block with explicit project/region, pinned
remote manifest digest, runtime SA and **numeric enabled secret versions**. Never
use `latest`, command-line key values or image build arguments. Generation model
selection is still pending; query embeddings stay `text-embedding-3-small`.

| Setting | Prepared value |
| --- | --- |
| Region / generation | us-west1 / second generation |
| Identity / access | Dedicated runtime SA; Invoker IAM check enabled; no allUsers/allAuthenticatedUsers binding; approved staging invoker only |
| Ingress | `all`, so authenticated user invocation works through the default URL; this is internet-reachable IAM-private staging, not internal-network-only access |
| Processes | One existing ASGI worker, three persistent STDIO children/four tools |
| CPU / memory | 1 vCPU / 2 GiB, request-based CPU allocation, startup CPU boost |
| Scale / concurrency | Service min 0/max 1, revision max 1; concurrency 1; no session affinity |
| Application limits | Active 1 / waiting 0, body cap 65536, HTTP 180s, queue 30s; Agent 120s, provider 30s/retries 0; shutdown budget unchanged |
| Port | `--port=8080`; Cloud Run injects reserved `PORT`; do not set it separately |
| Startup probe | GET `/ready`, HTTP/1, port 8080, delay 0, period 10s, timeout 3s, failure threshold 24 |
| Cloud request timeout | 300s initially, subject to native measurement |
| Secrets | Only runtime Secret Manager references, two approved numeric versions |

Startup probe window is **240 seconds**, distinct from the request timeout. It
accommodates ~121s measured emulated startup with ~119s margin, without guaranteeing
native success. Current [health-check docs](https://docs.cloud.google.com/run/docs/configuring/healthchecks)
allow broader windows, while the [container contract](https://docs.cloud.google.com/run/docs/container-contract)
still specifies listening within four minutes. Keep this conservative 240s proposal.
The container contract also includes startup in request timeout: cold 121s + Agent
120s is ~241s before overhead; cold 121s + full app 180s is ~301s, so platform 504 is
possible before the app timer. Preserve app deadlines; authenticate and warm-check
readiness before live validation, measure native startup, then review any timeout
change. There is no automatic `/chat` retry or readiness-based spend approval.

After separately approved deployment/invoker grant, prepared diagnostics are:

```bash
gcloud run services proxy "$VERIDEX_SERVICE" \
  --project="$VERIDEX_PROJECT_ID" --region=us-west1 --port=18080
# Separate terminal; proxy handles authentication without printing/storing tokens.
curl --fail --max-time 15 http://127.0.0.1:18080/health
curl --fail --max-time 15 http://127.0.0.1:18080/ready
curl --fail --max-time 15 http://127.0.0.1:18080/attribution
```

These requests incur Cloud Run compute even though they make no provider calls;
they are not executed in preparation. Audit inherited IAM/public principals too.

Proposed future live verification, **not authorized**: three sequential HTTP turns
with a fresh random non-sensitive session, first an evidence-backed question about
Li et al. SELF-ROUTE, second a follow-up using that same session, third an explicitly
Web-oriented question under a distinct session. Stop on first failure; no retries.
Default envelope: at most 18 outer generation calls, 24 accepted tools across three
turns, at most 24 query-embedding calls and 24 Tavily searches individually (combined
accepted tool count still <=24); no document ingestion. Each Evidence invocation
uses similarity search, not an extra self-query LLM in the current production tool.
SDK input splitting can affect embedding request count; agree exact provider-level
attempt caps after inspecting selected prompts/model/SDK. Approve a dollar ceiling,
Tavily plan units and usage-recording method before any request. Bounds are ceilings,
not predicted calls or a hard aggregate billing guarantee. Ordinary `/chat` returns
only `response`; live trace evidence needs an approved safe observation method that
does not expose full internal traces or change the grading contract.

## Public grading and post-grading gate

Private staging is confirmed; public invocation remains unapproved. The isolated
`enable_approved_public_grading` function in the command document adds only a
service-level allUsers Invoker binding after an explicit operator approval marker.
Unrelated setup commands cannot call it. Do not disable the IAM check or change
ingress as a workaround for organization policy. Review inherited policy first.

Required contract stays POST `/chat`, `{"query": string, "session_id": string}` ->
`{"response": string}`, without new required headers/fields for public grading.
Same-instance two-turn memory works, but caller-selected anonymous IDs provide no
verified ownership; collisions share history. Distinct IDs isolate ordinary sessions,
not verified users. InMemorySaver is ephemeral across recycling/revisions, expires
idle sessions and retains bounded history. Max one instance is not durability or
complete abuse prevention. Provider spending remains possible under sustained load.

Recommend a **72-hour grading window**, adjusted to the instructor's schedule, with
an approved UTC end date and cleanup operator. No date is selected yet. At expiry,
revoke public binding and audit inherited/trusted access; explicitly approved deletion
of the single Cloud Run service is the clean shutdown for all invocation paths.
In-flight work may finish; registry/secret storage persists until separate cleanup.
Do not disable billing or delete a shared project as an automatic kill switch.

## $5 alerts and spend-cap assessment

Confirmed plan: **USD $5 monthly project-wide alerts-only budget**, actual thresholds
50% ($2.50), 80% ($4), 100% ($5), recommended forecast 100%, approved recipients.
Budget creation is still a mutation requiring approval. Propose excluding credits
from the alert basis so educational credit doesn't hide gross usage; confirm that
basis/notifications with the billing operator. No project/account/currency/recipients
are verified. [Budget CLI reference](https://docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create)
supports the prepared command; API setup or Console workflow must be selected.
Alerts are **not hard spending caps** and may arrive after costs accrue.

[Cloud Billing spend-cap documentation](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
currently includes Cloud Run, limited to a single project and eligible billing service,
monthly gross estimates and first-party accounts (resellers excluded). Enforcement
can lag and fixed/in-flight costs can remain; caps reset monthly. **Account eligibility
and UI/permissions are unverified.** Consider a separately approved $5 Cloud Run-only
cap if eligible, in addition to all-service alerts; it can interrupt grading and does
not cover Artifact Registry, Secret Manager, OpenAI or Tavily. Do not assume a total
project hard cap or configure one from the alert approval.

Illustrative USD list-price assumptions, no free allowances/credits, startup boost,
networking/logs/tax or providers included:

| Item | Illustration |
| --- | --- |
| Cloud Run 1 CPU / 2 GiB active | ~$0.1044 per active hour; five hours ~$0.522 plus request charges, startup/boost/shutdown |
| Continuously busy same instance | ~$75.17 compute for 30 days; max 1 is not a $5 limit |
| Artifact Registry | About $0.08/month for hypothetical 0.8 GiB stored layers before allowances; compressed stored size must be measured |
| Secret Manager | Two active versions ~$0.12/month before allowances, plus accesses |
| Cloud Build | $0 for this local-image publication plan; not provisioned/enabled |

Sources: [Run pricing](https://cloud.google.com/run/pricing),
[Registry pricing](https://cloud.google.com/artifact-registry/pricing),
[Secret pricing](https://cloud.google.com/secret-manager/pricing).
Billing-account free allowances may already be used elsewhere; don't assume free
USC credits. Avoid min instances, VPC connectors, Cloud SQL and unnecessary builds.
OpenAI generation/query embeddings and Tavily have separate accounts/budgets and
need independently approved allowances. The previous 12 embedding requests authorize
no ongoing demo spend. Measure native startup, cgroup/Cloud Monitoring memory peaks,
provider usage and shutdown after authorized staging; never log secrets, source
passages, conversations or raw tool artifacts.

## Execution order and authorization

1. **Tool/account readiness:** approve local CLI installation/login if needed; read-only
   discovery or user-provided Console metadata confirms account/project/billing/credits.
2. **Step 4.8.1 selection:** select/approve exact existing project or new ID+parent,
   billing account, principals, repo/service/SA/secret names, notification recipients.
3. **Provisioning approval:** separately authorize project creation/linkage if needed,
   required API enablement, $5 alert creation, repository/SA/secret resources and exact
   IAM grants. No cap or cloud deployment is included by inference.
4. **Secret operator gate:** operator adds values privately and supplies enabled numeric
   version metadata; never key values. Separate operation approval.
5. **Image publication gate:** approve exact image ID and registry/recipients; verify,
   configure credentials, tag/push, obtain/review remote manifest digest. No rebuild.
6. **Private deploy gate:** select generation model, approve runtime references/settings,
   named private deployment and staging-invoker IAM grant; no anonymous invocation.
7. **Native/live acceptance:** approve bounded cloud diagnostics and a counted provider
   plan/dollar ceiling; measure/record results before any public grading transition.
8. **Public/expiry gate:** separately approve allUsers binding, anonymous risks, grading
   dates/operator and post-grading cleanup operations. No automatic public grant.

**Step 4.8.0 preparation is complete. Step 4.8.1 is not executable yet:** gcloud and
account discovery are missing; project/billing/principals and provisioning action
approval remain pending. It can proceed after those prerequisites and explicit user
approval, without re-requesting confirmed region/private-first/noncommercial/$5-alert
choices. No cloud mutation or remote publication occurred.
