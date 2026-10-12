# Reviewed future Cloud Run commands — NOT EXECUTED

These blocks are a proposed sequence for Step 4.8, not authorization and not a
run-all script. Stop at each gate in [cloud_run_preflight.md](cloud_run_preflight.md).
Values are nonsecret placeholders. Never enable shell tracing or put API keys in
these commands. Use an approved current Google Cloud CLI; it is not installed here.
Flag spellings were checked against the current
[gcloud run deploy reference](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy).
No cloud-side syntax/policy validation has been executed.
The [Step 4.7b approval checklist](deployment_approval_checklist.md) records unresolved
grading, session ownership, rights, model and spending gates. Do not execute these
blocks until the relevant decisions and named actions are explicitly approved.

## 1. Approved identifiers (no secrets)

```bash
export VERIDEX_PROJECT_ID='REPLACE_WITH_APPROVED_PROJECT_ID'
export VERIDEX_BILLING_ACCOUNT='REPLACE_WITH_APPROVED_BILLING_ACCOUNT_ID'
export VERIDEX_REGION='us-central1'
export VERIDEX_REPOSITORY='veridex'
export VERIDEX_SERVICE='veridex'
export VERIDEX_RUNTIME_SA="veridex-runtime@${VERIDEX_PROJECT_ID}.iam.gserviceaccount.com"
export VERIDEX_DEPLOYER_MEMBER='user:REPLACE_WITH_APPROVED_DEPLOYER'
export VERIDEX_PUBLISHER_MEMBER='user:REPLACE_WITH_APPROVED_PUBLISHER'
export VERIDEX_INVOKER_MEMBER='user:REPLACE_WITH_APPROVED_TRUSTED_INVOKER'
export VERIDEX_OPENAI_SECRET_VERSION='REPLACE_WITH_ENABLED_NUMERIC_VERSION'
export VERIDEX_TAVILY_SECRET_VERSION='REPLACE_WITH_ENABLED_NUMERIC_VERSION'
export VERIDEX_OPENAI_MODEL='REPLACE_WITH_APPROVED_GENERATION_MODEL'
export VERIDEX_EMBEDDING_MODEL='REPLACE_WITH_APPROVED_QUERY_EMBEDDING_MODEL'
export VERIDEX_IMAGE_TAG="${VERIDEX_REGION}-docker.pkg.dev/${VERIDEX_PROJECT_ID}/${VERIDEX_REPOSITORY}/veridex:phase04-reviewed"
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
alerts-only $10 monthly budget in the console, thresholds 50/90/100% and forecast
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

Use the already verified image after rechecking its identity and bundle. No new
build is proposed. A local image ID is not the registry manifest digest.

```bash
docker image inspect veridex:phase04-local --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Config.User}}'
gcloud auth configure-docker "${VERIDEX_REGION}-docker.pkg.dev"
docker tag veridex:phase04-local "$VERIDEX_IMAGE_TAG"
docker push "$VERIDEX_IMAGE_TAG"
gcloud artifacts docker images describe "$VERIDEX_IMAGE_TAG" --project="$VERIDEX_PROJECT_ID" --format='value(image_summary.digest)'
export VERIDEX_IMAGE_DIGEST='REPLACE_WITH_REVIEWED_REGISTRY_SHA256_DIGEST'
export VERIDEX_IMAGE="${VERIDEX_REGION}-docker.pkg.dev/${VERIDEX_PROJECT_ID}/${VERIDEX_REPOSITORY}/veridex@${VERIDEX_IMAGE_DIGEST}"
```

The locally recorded Step 4.6 image ID is
`sha256:248852fadfeb86354fabf542b41ae32cb932bfb9a213ed2db754646589d1a96d`.
If inspect differs, stop and establish the reviewed image; don't silently push it.
The bundle digest remains
`6fd0cb8b83f32e94beacb4788df1dcd251f662007264d5aa698c4c9b835a29e8`.
The approved original/recovered indexes and local bundle remain untouched.
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
  --timeout=240s --cpu-throttling --cpu-boost --no-session-affinity \
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
gcloud run services describe "$VERIDEX_SERVICE" --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID" --format=yaml
gcloud run services get-iam-policy "$VERIDEX_SERVICE" --region="$VERIDEX_REGION" --project="$VERIDEX_PROJECT_ID" --format=json
gcloud projects get-iam-policy "$VERIDEX_PROJECT_ID" --format=json
gcloud secrets versions list veridex-openai-api-key --project="$VERIDEX_PROJECT_ID"
gcloud secrets versions list veridex-tavily-api-key --project="$VERIDEX_PROJECT_ID"
gcloud secrets get-iam-policy veridex-openai-api-key --project="$VERIDEX_PROJECT_ID"
gcloud secrets get-iam-policy veridex-tavily-api-key --project="$VERIDEX_PROJECT_ID"
```

Verify pinned image/secrets, IAM check enabled, no public grant, runtime SA, resource
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
Do not print/store tokens or use persistent keys. Confirm the grader's actual
authentication capability before selecting either path. No `/chat` live-provider
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
Record the actual good revision before a later update. Public-access mutations,
resource deletion, secret destruction and automatic spending kill switches are not
included in this proposal. Grade only after rights/access/provider gates pass;
approve time-limited access and its eventual revocation explicitly.
