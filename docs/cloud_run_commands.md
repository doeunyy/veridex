> Step 4.8.1b now confirms project `zeta-store-511505-i7`, USC bootstrap identity,
> and existing billing. Use the separately gated A–E blocks in
> [gcp_provisioning_review_481b.md](gcp_provisioning_review_481b.md) for provisioning.
> They supersede the generic bootstrap/budget blocks below. Do not create a project,
> link billing, or re-enable existing APIs. All publication/deployment/public gates
> below remain unexecuted and separately authorized.

# Reviewed future Cloud Run commands — NOT EXECUTED

These blocks are a proposed sequence for Step 4.8, not authorization and not a
run-all script. Stop at each gate in [cloud_run_preflight.md](cloud_run_preflight.md).
Values are nonsecret placeholders. Current preparation/discovery status and approval order
are in [gcp_preparation_480.md](gcp_preparation_480.md). Never enable shell tracing or put API keys in
these commands. SDK 588.0.0 is installed outside PATH at `$HOME/google-cloud-sdk/bin/gcloud`; use its explicit path or an approved local PATH setup.
Flag spellings were checked against the current
[gcloud run deploy reference](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy).
No cloud-side syntax/policy validation has been executed.
The [Step 4.7b approval checklist](deployment_approval_checklist.md) records unresolved
public grading approval, accepted anonymous-session limits, rights, model and spending gates. Do not execute these
blocks until the relevant decisions and named actions are explicitly approved.

## 1. Proposed identifiers — unapproved placeholders (no secrets)

```bash
export VERIDEX_PROJECT_ID='zeta-store-511505-i7'
export VERIDEX_BILLING_ACCOUNT='REPLACE_WITH_APPROVED_BILLING_ACCOUNT_ID'
export VERIDEX_PROJECT_NUMBER='REPLACE_WITH_PROJECT_NUMBER'
export VERIDEX_OPERATOR_ACCOUNT='REPLACE_WITH_APPROVED_OPERATOR_ACCOUNT'
export VERIDEX_REGION='us-west1'
export VERIDEX_REPOSITORY='veridex'
export VERIDEX_SERVICE='veridex-staging'
export VERIDEX_RUNTIME_SA="veridex-runtime@${VERIDEX_PROJECT_ID}.iam.gserviceaccount.com"
export VERIDEX_DEPLOYER_MEMBER='user:REPLACE_WITH_APPROVED_DEPLOYER'
export VERIDEX_PUBLISHER_MEMBER='user:REPLACE_WITH_APPROVED_PUBLISHER'
export VERIDEX_INVOKER_MEMBER='user:REPLACE_WITH_APPROVED_TRUSTED_INVOKER'
export VERIDEX_OPENAI_SECRET_VERSION='REPLACE_WITH_ENABLED_NUMERIC_VERSION'
export VERIDEX_TAVILY_SECRET_VERSION='REPLACE_WITH_ENABLED_NUMERIC_VERSION'
export VERIDEX_OPENAI_MODEL='REPLACE_WITH_APPROVED_GENERATION_MODEL'
export VERIDEX_EMBEDDING_MODEL='text-embedding-3-small'
export VERIDEX_IMAGE_TAG="${VERIDEX_REGION}-docker.pkg.dev/${VERIDEX_PROJECT_ID}/${VERIDEX_REPOSITORY}/veridex:phase04-v2-47h"
```

Confirm the CLI active identity/project without retrieving secret payloads. Use
interactive user authentication or approved workload federation; no SA key files.
Do not accept unresolved placeholders, inherited project defaults, or an arbitrary
existing tag as the reviewed image. All cloud commands use explicit project/region.

## 2. Bootstrap administrator: only after resource/billing approval

Prefer an approved existing project. If a new project is selected, these are
separate mutations requiring parent organization/folder selection and authority.
The project-create command below is only suitable if no parent argument is required
by the approved policy; otherwise add the approved `--folder` or `--organization`.

```bash
gcloud projects create "$VERIDEX_PROJECT_ID" --name='Veridex grading demo'
gcloud billing projects link "$VERIDEX_PROJECT_ID" --billing-account="$VERIDEX_BILLING_ACCOUNT"
```

Before further provisioning, the billing operator creates the approved project
alerts-only $5 monthly budget in the console, thresholds 50/80/100% and forecast
100%, with approved notification recipients. Separately review a $5 monthly Cloud
Run spend cap (single project + Cloud Run service billing category), if eligible.
Do not conflate the two or count either as an external-provider spending limit.
Budget configuration is deliberately an operator gate, not an unreviewed CLI call.

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com --project="$VERIDEX_PROJECT_ID"
gcloud artifacts repositories create "$VERIDEX_REPOSITORY" --repository-format=docker --location="$VERIDEX_REGION" --description='Approved Veridex private images' --project="$VERIDEX_PROJECT_ID"
gcloud iam service-accounts create veridex-runtime --display-name='Veridex Cloud Run runtime' --project="$VERIDEX_PROJECT_ID"
gcloud secrets create veridex-openai-api-key --replication-policy=automatic --project="$VERIDEX_PROJECT_ID"
gcloud secrets create veridex-tavily-api-key --replication-policy=automatic --project="$VERIDEX_PROJECT_ID"
gcloud secrets add-iam-policy-binding veridex-openai-api-key --member="serviceAccount:${VERIDEX_RUNTIME_SA}" --role=roles/secretmanager.secretAccessor --project="$VERIDEX_PROJECT_ID"
gcloud secrets add-iam-policy-binding veridex-tavily-api-key --member="serviceAccount:${VERIDEX_RUNTIME_SA}" --role=roles/secretmanager.secretAccessor --project="$VERIDEX_PROJECT_ID"
gcloud iam service-accounts add-iam-policy-binding "$VERIDEX_RUNTIME_SA" --member="$VERIDEX_DEPLOYER_MEMBER" --role=roles/iam.serviceAccountUser --project="$VERIDEX_PROJECT_ID"
gcloud artifacts repositories add-iam-policy-binding "$VERIDEX_REPOSITORY" --location="$VERIDEX_REGION" --member="$VERIDEX_DEPLOYER_MEMBER" --role=roles/artifactregistry.reader --project="$VERIDEX_PROJECT_ID"
gcloud artifacts repositories add-iam-policy-binding "$VERIDEX_REPOSITORY" --location="$VERIDEX_REGION" --member="$VERIDEX_PUBLISHER_MEMBER" --role=roles/artifactregistry.writer --project="$VERIDEX_PROJECT_ID"
```

The approved secret operator adds versions directly in Secret Manager using their
trusted workflow, without this agent seeing values. Version Adder permissions are
scoped to these two secrets. No secret payload command is supplied here. Populate
the numeric references above only after confirming metadata and runtime access.
Secrets must not be provided through Docker build args, environment files in the
build context, terminal history, or logs.

These creates are not idempotent updates: if resources already exist, stop and
inspect rather than replacing/deleting them. Bootstrap IAM is separately reviewed;
do not grant Owner/Editor to the runtime or publisher. See the preflight identity
table for administrator permissions; not every bootstrap permission is needed
when infrastructure already exists.

## 3. Image publisher: only after explicit PDF/remote-copy approval

Use the already verified image after rechecking its identity and bundle. Step 4.7h verified Corpus v2 with 33 Docker TCP tests and packaged attribution. The image is still
local-only: explicit approval of remote image publication is required. Any
corpus/notices/image change requires a new build, verification and identity review. A local image ID is not the registry manifest digest.

```bash
publish_approved_v2_image() {
  if [ "${VERIDEX_PUBLICATION_APPROVAL:-}" != "APPROVED:${VERIDEX_PROJECT_ID}:${VERIDEX_REPOSITORY}" ]; then
    printf '%s\n' 'Image publication has not been explicitly approved.' >&2
    return 1
  fi
  local observed
  observed=$(docker image inspect veridex:phase04-v2-local --format '{{.Id}}') || return 1
  if [ "$observed" != 'sha256:38c2bb0aed856da0fa8724e4ffc0dd27cf4c461b69b97b8822d5b854ee544289' ]; then
    printf '%s\n' 'Local image differs from the reviewed v2 release.' >&2
    return 1
  fi
  gcloud auth configure-docker "${VERIDEX_REGION}-docker.pkg.dev" || return 1
  docker tag "$observed" "$VERIDEX_IMAGE_TAG" || return 1
  docker push "$VERIDEX_IMAGE_TAG" || return 1
  gcloud artifacts docker images describe "$VERIDEX_IMAGE_TAG" \
    --project="$VERIDEX_PROJECT_ID" --format='value(image_summary.digest)'
}
# Do not set the approval marker or invoke this function during preparation.
# Only after reviewed publication and manifest-digest inspection:
export VERIDEX_IMAGE_DIGEST='REPLACE_WITH_REVIEWED_REGISTRY_SHA256_DIGEST'
export VERIDEX_IMAGE="${VERIDEX_REGION}-docker.pkg.dev/${VERIDEX_PROJECT_ID}/${VERIDEX_REPOSITORY}/veridex@${VERIDEX_IMAGE_DIGEST}"
```

The locally verified Step 4.7h image ID is
`sha256:38c2bb0aed856da0fa8724e4ffc0dd27cf4c461b69b97b8822d5b854ee544289`.
If inspect differs, stop and establish the reviewed image; don't silently push it.
The bundle digest remains
`7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
The original/recovered/v1 and v2 source artifacts remain untouched.
Reusing this image is conditional on completed rights/notices review. If that
review requires new attribution files or corpus changes, stop: authorize and verify
a new local image separately, then replace this identity pin through review.

## 4. Bootstrap/access administrator: authorized PRIVATE deployment

Run the initial create/policy operation with the approved administrator identity.
Do not pass the API keys. The entrypoint, worker count, and filesystem paths are
inherited from the image; no `--command` override and no independent `PORT` env.

```bash
gcloud run deploy "$VERIDEX_SERVICE" \
  --project="$VERIDEX_PROJECT_ID" --region="$VERIDEX_REGION" \
  --image="$VERIDEX_IMAGE" --service-account="$VERIDEX_RUNTIME_SA" \
  --execution-environment=gen2 --port=8080 --cpu=1 --memory=2Gi \
  --concurrency=1 --min=0 --max=1 --max-instances=1 \
  --timeout=300s --cpu-throttling --cpu-boost --no-session-affinity \
  --ingress=all --no-allow-unauthenticated --invoker-iam-check \
  --startup-probe='httpGet.path=/ready,httpGet.port=8080,initialDelaySeconds=0,periodSeconds=10,timeoutSeconds=3,failureThreshold=24' \
  --set-env-vars="APP_ENV=production,LOG_LEVEL=INFO,API_MAX_REQUEST_BODY_BYTES=65536,API_MAX_ACTIVE_REQUESTS=1,API_MAX_WAITING_REQUESTS=0,API_REQUEST_TIMEOUT_SECONDS=180,API_QUEUE_TIMEOUT_SECONDS=30,OPENAI_MODEL=${VERIDEX_OPENAI_MODEL},OPENAI_EMBEDDING_MODEL=${VERIDEX_EMBEDDING_MODEL}" \
  --set-secrets="OPENAI_API_KEY=veridex-openai-api-key:${VERIDEX_OPENAI_SECRET_VERSION},TAVILY_API_KEY=veridex-tavily-api-key:${VERIDEX_TAVILY_SECRET_VERSION}"
gcloud run services add-iam-policy-binding "$VERIDEX_SERVICE" --member="$VERIDEX_DEPLOYER_MEMBER" --role=roles/run.developer --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID"
```

The service-wide `--max=1` covers traffic-bearing revisions; revision-level
`--max-instances=1` alone would not be a service-wide limit. Neither is a hard
spend/durability guarantee. This proposed create can route traffic to the new
revision; keep it IAM-private until review succeeds. For later updates, review
`--no-traffic` staging/traffic migration explicitly and preserve access policy.
Routine deployer updates should not attempt IAM changes they lack permission for.
Retire unnecessary bootstrap grants after successful creation/policy audit.

## 5. Read-only audit and separately approved trusted invoker

```bash
gcloud run services describe "$VERIDEX_SERVICE" --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID" --format='yaml(metadata.name,status.url,status.latestReadyRevisionName,spec.template.spec.serviceAccountName,spec.template.spec.timeoutSeconds,spec.template.spec.containerConcurrency,spec.template.spec.containers.image,spec.template.spec.containers.ports,spec.template.spec.containers.resources,spec.template.spec.containers.startupProbe)'
gcloud run services get-iam-policy "$VERIDEX_SERVICE" --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID" --format=json
gcloud projects get-iam-policy "$VERIDEX_PROJECT_ID" --format=json
gcloud secrets versions list veridex-openai-api-key --project="$VERIDEX_PROJECT_ID"
gcloud secrets versions list veridex-tavily-api-key --project="$VERIDEX_PROJECT_ID"
gcloud secrets get-iam-policy veridex-openai-api-key --project="$VERIDEX_PROJECT_ID"
gcloud secrets get-iam-policy veridex-tavily-api-key --project="$VERIDEX_PROJECT_ID"
```

The selected service description deliberately omits env values and arbitrary annotations.
Use the Console or a specifically reviewed metadata-only query for secret references,
scaling/ingress/IAM-check annotations and model/limit settings; never print literal
secret values from an existing service. Verify pinned image/secrets, IAM check enabled, no public grant, runtime SA, resource
allocation, probe, scaling and API limits. Inspect metadata only; do not access
secret payloads. Audit inherited project/ancestor IAM and any group membership too;
absence of a service-level public binding alone is insufficient. When reusing an
existing service, check for literal secret env values before printing a full service
description. A trusted invoker grant is a separate approved access mutation:

```bash
gcloud run services add-iam-policy-binding "$VERIDEX_SERVICE" --member="$VERIDEX_INVOKER_MEMBER" --role=roles/run.invoker --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID"
gcloud run services describe "$VERIDEX_SERVICE" --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID" --format='value(status.url)'
```

For an approved user invoker, use `gcloud run services proxy` and GET `/health` and
`/ready` through its localhost listener. For service-account invocation, use a
short-lived audience-bound ID token through approved impersonation/federation.
Do not print/store tokens or use persistent keys. These are private-staging diagnostics, not mandatory grading authentication.
The selected grading target uses the separately approved public gate below. No `/chat` live-provider
command is included: the counted minimal call plan needs separate approval.

## 6. Measurements, rollback and grading gate

After authorized deployment, collect native startup/ready timestamps, revision
CPU/memory, warm health latency, instance restarts/OOMs, idle-resume MCP health and
shutdown logs. Correlate with image digest and resource allocation. Do not log
query text, source passages, secret env values, raw tool outputs or conversation
history. Avoid DEBUG logging and unapproved tracing integrations.

If native checks fail, with separate operational authorization remove the approved
invoker binding to stop new access, or restore traffic to a previously approved
healthy revision. Neither action ensures already-running provider calls stop.
No rollback target exists before the first successful deployment; do not invent one.
Record the actual good revision before a later update. Resource deletion, secret destruction and automatic spending kill switches are not
included in this proposal. Public access is prepared only in the separate gate below. Grade only after rights/access/provider gates pass;
approve time-limited access and its eventual revocation explicitly.

## 7. Public grading gate — PREPARED, NOT EXECUTED

The instructor example uses `--allow-unauthenticated`. Keep initial staging private,
then grant anonymous invocation as a separate access action only after explicit
user approval of rights, provider spending, expiry and anonymous shared-ID risks.
No required authentication header, token or new JSON field is added. This function
is merely defined; unrelated provisioning/deployment commands do not invoke it.
The approval marker is an operator guard, not evidence of user authorization.

```bash
enable_approved_public_grading() {
  if [ "${VERIDEX_PUBLIC_APPROVAL:-}" != "APPROVED:${VERIDEX_PROJECT_ID}:${VERIDEX_SERVICE}" ]; then
    printf '%s\n' 'Public grading access has not been explicitly approved.' >&2
    return 1
  fi
  gcloud run services add-iam-policy-binding "$VERIDEX_SERVICE" \
    --member=allUsers --role=roles/run.invoker \
    --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID"
}
```

Do not set the marker or call the function during setup. Its effect is public
Cloud Run invocation, equivalent in access intent to the example's unauthenticated
flag. Organization policy may prohibit the grant; stop rather than bypassing it.
Record the approved grading end date and operator. Separately approved expiry
removes this grant and audits inherited access; min 0 and max 1 do not expire a URL.
Revocation cannot recall exposed conversation content or cancel all in-flight
provider requests. Cloud resource deletion, secret rotation and image retention are
separate reviewed cleanup actions. The public service has no verified ownership;
colliding session IDs share retained history. No confidential data should be used.

## Step 4.7h release selection — PREPARED, NOT EXECUTED

Publish only the exact reviewed `veridex:phase04-v2-local` candidate identified in
[release_readiness_47h.md](release_readiness_47h.md), after explicit publication
authorization. Its bundled corpus digest is
`7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
The query embedding model must remain `text-embedding-3-small` to match v2.
This model setting does not authorize paid queries or cloud mutations. Keep public
admission separate from provisioning/private deployment; do not run these blocks
until project, identities, secrets, provider allowance and expiry are approved.

## Step 4.8.0 gates and $5 alert budget — PREPARED, NOT EXECUTED

Every create, services-enable, IAM-binding, billing-link, budget-create, deploy,
Docker credential configuration, image tag/push and public-access command above is
a mutation or publication action requiring its own stage approval. Neither defining
variables nor confirming an image authorizes these actions. Do not run the blocks
as a batch. No resource/project name is approved yet.

The budget amount is confirmed, but creating the budget is not authorized. After
project/billing/notification selection and approval, the billing operator may use
the Console or this reviewed alerts-only command. Gross usage excluding credits is
proposed for conservative alerts; confirm that basis and recipient delivery first.
Use the approved project ID, not the shell's active project. The billing account
must use USD; stop on a different currency. This requires billingbudgets API setup
for the chosen administrative/quota project, or use the Console instead.

```bash
gcloud billing budgets create \
  --billing-account="$VERIDEX_BILLING_ACCOUNT" \
  --project="$VERIDEX_PROJECT_ID" \
  --display-name='Veridex coursework monthly USD 5 alerts' \
  --budget-amount=5USD --calendar-period=month \
  --filter-projects="projects/${VERIDEX_PROJECT_ID}" \
  --credit-types-treatment=exclude-all-credits \
  --threshold-rule=percent=0.5,basis=current-spend \
  --threshold-rule=percent=0.8,basis=current-spend \
  --threshold-rule=percent=1.0,basis=current-spend \
  --threshold-rule=percent=1.0,basis=forecasted-spend
```

This does not configure a spend cap or authorize provider spending. Default IAM
notification recipients must be checked in the Console; add approved email
notification channels only if needed, with separate approval. Cloud Run spend-cap
eligibility, available billing permissions and first-party account status remain
unverified. Do not create or lift a cap by inference from this alert budget.

### Post-grading shutdown — MUTATIONS, NOT EXECUTED

Approve the end date/operator separately. First revoke the explicit public binding
and inspect inherited access. Removing it does not revoke trusted-invoker access
or terminate in-flight turns. Then, if service deletion is specifically approved,
delete the single service after recording necessary release/measurement metadata.
This is not project deletion or billing disablement. Registry storage and active
secret-version charges persist until separately reviewed cleanup.

```bash
gcloud run services remove-iam-policy-binding "$VERIDEX_SERVICE" \
  --member=allUsers --role=roles/run.invoker \
  --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID"
gcloud run services get-iam-policy "$VERIDEX_SERVICE" \
  --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID" --format=json
# DESTRUCTIVE: only after explicit approval to delete this named service.
gcloud run services delete "$VERIDEX_SERVICE" \
  --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID"
```
