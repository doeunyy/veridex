> Current verification: [Step 4.8.1c](gcp_preflight_481c.md) confirms Block A enabled, all B–E names available, budget permissions and default USC recipient verified. The observations below describe the earlier review. Blocks B–E remain unexecuted; E is the next approval gate.

# Step 4.8.1b — Provisioning review, NOT EXECUTED

Project `zeta-store-511505-i7`, region `us-west1`. Every A–E block below changes
cloud state and requires separate explicit approval. These are review blocks, not
a run-all script. No API was enabled in this review; API-enable prompts were
explicitly answered **n**. No resource, key, budget, image upload or deployment was
created. No provider request was made. Existing image/bundle remain unchanged.

## Read-only discovery

SDK 588.0.0 exists at `$HOME/google-cloud-sdk/bin/gcloud` outside PATH.
Active identity is `<OPERATOR_ACCOUNT>`; its project role is `roles/owner`. Default
CLI project is unset, so commands explicitly name the project. The user confirmed
Free Trial credits in Console; no credit balance/payment information was retrieved.

| Check | Result |
| --- | --- |
| Project | ACTIVE, project number `<PROJECT_NUMBER>` |
| Billing | Enabled; linked account `<BILLING_ACCOUNT_ID>`, open, USD |
| APIs already enabled | `run.googleapis.com`, `artifactregistry.googleapis.com`, `serviceusage.googleapis.com`, logging and monitoring, plus unrelated existing defaults |
| APIs not listed enabled | `iam.googleapis.com`, `secretmanager.googleapis.com`, `billingbudgets.googleapis.com` |
| Repository collision | us-west1 repository list empty: `veridex` not present |
| Runtime SA collision | `veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com` absent. The automatically created Compute default SA exists; leave it untouched. |
| Cloud Run | us-west1 service list empty |
| Secret name collision | Unverified: listing blocked by disabled Secret Manager API; enable prompt declined |
| Existing budget collision / create permission | Unverified: listing blocked by disabled Billing Budgets API; enable prompt declined. SERVICE_DISABLED is not proof of missing billing IAM. |

IAM listing and billing/project metadata reads worked even though those APIs were
not all in the enabled-service listing. Explicit IAM enablement is proposed for
provisioning; do not enable extra discovery APIs merely because they are absent.
No new project or billing linkage is needed. Existing enabled APIs must not be
rolled back or disabled by this workflow.

Read-only commands used (no secret values/tokens):

```bash
GCLOUD="$HOME/google-cloud-sdk/bin/gcloud"
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" services list --enabled \
  --project=zeta-store-511505-i7 --format='value(config.name)'
"$GCLOUD" projects describe zeta-store-511505-i7 \
  --format='yaml(projectId,projectNumber,lifecycleState)'
"$GCLOUD" billing projects describe zeta-store-511505-i7 \
  --format='yaml(projectId,billingEnabled,billingAccountName)'
"$GCLOUD" artifacts repositories list --project=zeta-store-511505-i7 \
  --location=us-west1 --format='table(name,format)'
"$GCLOUD" iam service-accounts list --project=zeta-store-511505-i7 \
  --format='table(email,disabled)'
```

Future commands presume that SDK path, approved USC bootstrap identity, and
interactive prompts enabled. No `--quiet`, yes-pipe or automatic prompt acceptance
is supplied. Local shell variables do not change gcloud configuration.

## A. Missing API enablement — MUTATION, approval required

```bash
GCLOUD="$HOME/google-cloud-sdk/bin/gcloud"
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" services enable \
  iam.googleapis.com secretmanager.googleapis.com billingbudgets.googleapis.com \
  --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
```

Required: `serviceusage.services.enable`, e.g. Service Usage Admin; the existing
bootstrap Owner should already have project enablement rights, subject to policy.
Do not add that role redundantly or grant it to runtime. API enablement itself has
no metered usage charge; subsequent resource/use operations can incur costs. Google
may provision service identities as part of enablement. Cloud Run/Registry/Service
Usage are already enabled and are deliberately omitted. Cloud Build/IAM Credentials,
VPC/SQL or other optional services are not needed.

After approved A, rerun read-only checks before approving D/E:

```bash
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" secrets list \
  --project=zeta-store-511505-i7 --format='table(name)'
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" billing budgets list \
  --billing-account="${VERIDEX_BILLING_ACCOUNT:?}" --project=zeta-store-511505-i7 \
  --format='table(name,displayName,amount.specifiedAmount,budgetFilter.projects)'
```

If any name or project-scoped budget already exists, stop and inspect metadata;
never delete, replace or create duplicates by default. API propagation may require
a short wait; retry only read-only checks, not mutations. Billing budget IAM and
recipient delivery still need verification. D/E cannot be described as collision
cleared until these checks succeed.

## B. Artifact Registry — MUTATION, approval required

Recheck the us-west1 repository list immediately before execution. Create only if
`veridex` remains absent:

```bash
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" artifacts repositories create veridex \
  --project=zeta-store-511505-i7 --location=us-west1 \
  --repository-format=docker --description='Veridex noncommercial coursework images' \
  --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
```

Required: `artifactregistry.repositories.create`, typically bootstrap Artifact
Registry Admin. Empty repository creation has no stored-image charge; later stored
bytes, downloads and optional scanning can incur costs. Do not enable scanning,
configure automatic deletion, tag/push an image or configure Docker credentials in
this block. Repository remains IAM-private. No public repository role is proposed.

## C. Dedicated runtime SA — MUTATION, approval required

Recheck service-account listing first. Do not reuse the Compute default account.

```bash
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" iam service-accounts create veridex-runtime \
  --project=zeta-store-511505-i7 --display-name='Veridex Cloud Run runtime' \
  --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
```

Required: `iam.serviceAccounts.create`, typically bootstrap Service Account Admin.
SA creation has no usage charge. No keys, project-wide Owner/Editor, deploy, registry
writer, billing or broad secret role is assigned to runtime. No Cloud Run service
is created here. Runtime gets only D's two resource-scoped access bindings.

## D. Secret Manager and scoped runtime IAM — MUTATIONS, approval required

Requires A/C and successful name-collision checks. Secret shells only; this block
adds **no secret versions or values**. The trusted operator supplies values later
through an approved Secret Manager workflow, never through this agent.

```bash
(
set -e  # Stop on first failure; do not continue into IAM/deletion after a failed create.
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" secrets create veridex-openai-api-key \
  --project=zeta-store-511505-i7 --replication-policy=automatic --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" secrets create veridex-tavily-api-key \
  --project=zeta-store-511505-i7 --replication-policy=automatic --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" secrets add-iam-policy-binding veridex-openai-api-key \
  --project=zeta-store-511505-i7 \
  --member=serviceAccount:veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" secrets add-iam-policy-binding veridex-tavily-api-key \
  --project=zeta-store-511505-i7 \
  --member=serviceAccount:veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
)
```

Required: `secretmanager.secrets.create` and `secretmanager.secrets.setIamPolicy`,
typically bootstrap Secret Manager Admin. Runtime is granted Secret Accessor only
on these two secrets; no project-wide accessor grant. Audit effective inherited
IAM after creation. IAM changes are free; empty secret shells have no active-version
storage cost. Adding/accessing versions later can incur costs: two versions ~$0.12
per month before free allowances, accesses extra. Creation doesn't authorize provider
spending. Future trusted version operator needs Version Adder on these secrets,
not runtime/admin privileges. That optional binding requires its own approval.

Future deployment must reference separately verified **enabled numeric versions**,
for example `veridex-openai-api-key:<APPROVED_NUMBER>` and
`veridex-tavily-api-key:<APPROVED_NUMBER>`, never `latest` or literal key values.
Do not provide a version-add command containing credentials in shell history/files.

## E. Project-scoped USD $5 alerts — MUTATION, approval required

Requires A and verified budget collisions, billing permissions, notification
recipients and USD currency. USD/open status is verified; create permission and
recipient delivery remain pending. Proposed basis is **gross usage excluding
credits**, so Free Trial credit does not hide consumption; approve this basis with
E. This alerts on usage even when credits reduce the cash bill.

```bash
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$GCLOUD" billing budgets create \
  --billing-account="${VERIDEX_BILLING_ACCOUNT:?}" \
  --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}" \
  --display-name='Veridex coursework monthly USD 5 alerts' \
  --budget-amount=5USD --calendar-period=month \
  --filter-projects="projects/${VERIDEX_PROJECT_NUMBER:?}" \
  --credit-types-treatment=exclude-all-credits \
  --threshold-rule=percent=0.5,basis=current-spend \
  --threshold-rule=percent=0.8,basis=current-spend \
  --threshold-rule=percent=1.0,basis=current-spend
```

No service filter: all GCP services in only this project count. Three requested
actual thresholds: $2.50/$4/$5. No optional forecast/cap/PubSub automation is added.
Default billing IAM email recipients must be confirmed to reach the intended user;
project Owner alone does not prove budget email delivery or account-wide budget
create authority. If insufficient, request the billing operator's help or reviewed
project-scoped budget permissions; do not grant runtime billing roles. A custom
email notification channel would be an additional separately approved resource.

Creating a budget/alerts does not itself incur compute/storage usage charges.
Alerts can be delayed and **do not cap spending**. Free Trial credits/eligibility
are not a guarantee of zero cost. Cloud Run/max-one-instance and provider limits
are also not aggregate dollar caps. OpenAI/Tavily bills are separate and unapproved.
No spend cap, billing linkage or payment change is proposed in E.

Reference: [budget CLI](https://docs.cloud.google.com/sdk/gcloud/reference/billing/budgets/create),
[budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets).

## Deployment/publication IAM — separately approved, not part of A–E

The current USC operator already has **Owner**, which includes broad bootstrap
powers. Adding narrow roles to this same identity would not reduce those powers;
no redundant Owner/Editor/Writer/Developer grants are proposed. Owner removal or a
new deployment identity requires separate review to avoid lockout.

For a separately approved limited human/federated operator (no SA keys), minimum
future profile: repository Writer for publication; runtime-SA User and repository
Reader for deployment; Run Developer on an already-created service for updates.
Initial service creation requires suitable project-scoped Run permissions; policy
changes require an access administrator. Service-level bindings cannot precede the
service. Google-managed Cloud Run service-agent permissions handle same-project image
pulls; do not grant service-agent roles to humans/runtime.

Prepared optional IAM changes, NOT EXECUTED; replace the limited principal only
after it is selected, and do not run this block for the existing Owner by default:

```bash
(
set -e  # Stop on first failure; do not continue into IAM/deletion after a failed create.
VERIDEX_LIMITED_MEMBER='user:REPLACE_WITH_APPROVED_LIMITED_OPERATOR'
"$GCLOUD" artifacts repositories add-iam-policy-binding veridex \
  --project=zeta-store-511505-i7 --location=us-west1 \
  --member="$VERIDEX_LIMITED_MEMBER" --role=roles/artifactregistry.writer
"$GCLOUD" iam service-accounts add-iam-policy-binding \
  veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com \
  --project=zeta-store-511505-i7 --member="$VERIDEX_LIMITED_MEMBER" \
  --role=roles/iam.serviceAccountUser
# Only after an approved IAM-private service has actually been created:
"$GCLOUD" run services add-iam-policy-binding veridex-staging \
  --project=zeta-store-511505-i7 --region=us-west1 \
  --member="$VERIDEX_LIMITED_MEMBER" --role=roles/run.developer
)
```

Repo Writer also covers reads for the same limited principal; a distinct deployer
without publication rights should instead receive repo Reader. All optional grants
and first deployment remain separate approval gates. No public invocation, image
push, Run deployment or Invoker IAM-check disabling command is part of A–E.

## Partial failures and rollback/cleanup — MUTATIONS, NOT EXECUTED

Stop on a failed mutation; record resources actually created and verify read-only
state before deciding next action. Do not automatically retry create commands,
overwrite collisions or roll back prior/shared resources. IAM-binding rollback
removes only a binding this run newly added, not a pre-existing grant. Never disable
pre-existing Cloud Run/Registry/Service Usage APIs; API disablement isn't a routine
rollback and is not prepared here.

With **separate explicit cleanup approval**, confirm resources are task-created,
unreferenced and empty (or explicitly approve deleting their contents), then:

```bash
(
set -e  # Stop on first failure; do not continue into IAM/deletion after a failed create.
"$GCLOUD" secrets remove-iam-policy-binding veridex-openai-api-key \
  --project=zeta-store-511505-i7 \
  --member=serviceAccount:veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
"$GCLOUD" secrets remove-iam-policy-binding veridex-tavily-api-key \
  --project=zeta-store-511505-i7 \
  --member=serviceAccount:veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
# DESTRUCTIVE: secret versions, if later added, would be deleted too.
"$GCLOUD" secrets delete veridex-openai-api-key --project=zeta-store-511505-i7
"$GCLOUD" secrets delete veridex-tavily-api-key --project=zeta-store-511505-i7
"$GCLOUD" iam service-accounts delete \
  veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com --project=zeta-store-511505-i7
# DESTRUCTIVE: only if repo remains empty, or its exact contents are approved for deletion.
"$GCLOUD" artifacts repositories delete veridex --location=us-west1 --project=zeta-store-511505-i7
# Use only the exact budget ID returned by approved E, never a guessed/shared ID.
"$GCLOUD" billing budgets delete REPLACE_WITH_CREATED_BUDGET_ID \
  --billing-account="${VERIDEX_BILLING_ACCOUNT:?}" --project=zeta-store-511505-i7
)
```

Optional limited-operator grants must also be removed, if and only if this run added
them, using the corresponding remove-iam-policy-binding command with the same
resource/member/role. Do not delete this existing project, unlink billing, disable
its pre-existing APIs or delete the Compute default SA. Budget deletion removes
alerts, not usage/spend; prefer retaining safety alerts until cleanup is complete.

## Recommended next approval

Approve **A only** first: enable the three named missing APIs in this exact project.
Then perform metadata-only secret/budget collision checks and verify budget
permissions/recipients. Prefer E next, before any billable image bytes/secret versions;
B/C can be approved independently after fresh collision checks, and D after C.
Each approval covers only its named commands, not subsequent blocks. No cloud state
was changed in this review; prompts were declined. Validated v2 image/bundle and
PROCESS_LOG remain untouched; no staging/commit/push.

Validation: nine prepared shell blocks passed `bash -n`; none of the A–E,
optional IAM or cleanup blocks was executed. Multi-command mutation blocks stop
on the first failure and require post-failure metadata review rather than automatic
retry/rollback. `git diff --check` passed; 75 protected artifact records remain
unchanged. Pricing references: [Registry](https://cloud.google.com/artifact-registry/pricing),
[Secret Manager](https://cloud.google.com/secret-manager/pricing).
