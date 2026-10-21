# Step 4.8.3a — private staging preflight

PREPARED ONLY; no deployment, provider invocation, IAM change or secret payload
access executed. Read-only discovery confirms no Cloud Run services in us-west1.

Pinned image:
`us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex/veridex@sha256:894225e0e0e676759809d658b83a1a1948d9056966214ad83d46a6d7feb4ca04`.
Registry configuration confirms linux/amd64, UID/GID 10001:10001, expected
entrypoint and approved v2 bundle checksum. Its config digest matches the verified
local image ID. Same-project private image retrieval uses the Cloud Run service
agent `service-<PROJECT_NUMBER>@serverless-robot-prod.iam.gserviceaccount.com`, whose
existing `roles/run.serviceAgent` binding was verified. This is distinct from the
runtime identity; do not grant runtime registry writer or service-agent roles.

Both numeric secret versions 1 are ENABLED. Each secret's only direct binding is
Secret Accessor for `veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com`.
Project policy grants no role to that runtime identity; no project-wide accessor
exists. These checks establish the intended project/secret scope, not an exhaustive
organization-wide effective-permissions audit. Existing Run, Registry, Secret
Manager, IAM and Service Usage APIs are enabled; no new API is indicated.
USC operator permission introspection verified run.services.create/get/setIamPolicy,
run.routes.invoke and iam.serviceAccounts.actAs on runtime. Registry read permission
was verified in publication preflight. No additional IAM grant is proposed.

## Recommended configuration

us-west1, gen2, 1 vCPU / 2 GiB, request-based CPU allocation, startup CPU boost,
concurrency 1, service min 0/max 1 and revision max 1, timeout 300 seconds.
One ASGI worker and three persistent STDIO children are owned in the same lifespan
task. Executables use sys.executable (/opt/venv/bin/python); cwd=/app. Uvicorn binds
0.0.0.0:$PORT; Cloud Run supplies PORT through --port=8080, not --set-env-vars.
Startup HTTP probe /ready: period 10s, timeout 3s, failure threshold 24, delay 0
(240-second window). No provider calls are required for startup/health/readiness.
The HTTP probe reaches the container directly and does not need an IAM token.

Application startup validates the immutable bundle and copies only Chroma into a
private writable /tmp directory. It never ingests or embeds automatically. Native
Linux validation previously passed all 586 self-queries, dimensions, vector hashes,
metadata, SQLite/FTS5 and functional text filters. PDFs/manifest/notices remain
read-only. Cloud Run filesystem writes consume instance memory and are ephemeral.

Local amd64-emulated production startup was 121.139s at 1 CPU / 2 GiB; production
sampled memory 765.92 MiB, fixture peak 823.85 MiB. Idle production shutdown 3.134s;
active fixture shutdown 5.469s. These are not native Cloud Run measurements or true
peak bounds. Runner drains HTTP for 0.5s, lifecycle uses one 8s budget, within the
platform's approximately 10s SIGTERM grace. Synchronous PDF/Chroma threads are not
directly interruptible; cancellation repair is best effort under forced termination.

Deadlines remain HTTP180s, Agent120s, MCP45s, provider30s with zero retries.
The platform300s timeout includes cold startup. At measured121s startup plus a
full180s HTTP turn it can narrowly expire first; real Agent turns are bounded120s.
Native cold-start/request measurements are required; a 240s startup plus a long
request is not guaranteed to fit300s. Startup probe budget and request timeout are
separate controls. Max1 is neither a hard cost cap nor a guarantee against transient
replacement overlap. InMemorySaver and session retention survive only the instance.

## Exact deployment — NOT EXECUTED, requires explicit approval

Explicit generation model gpt-5 preserves the current configured default. Approve
this model with deployment; no live-provider chat is included in that approval.
Only numeric secret references, never values, appear below. IAM-authenticated
Internet reachability uses ingress=all; it does not permit anonymous invocation.
No additional add-iam-policy-binding command is needed for the verified USC user.

```bash
CLOUDSDK_CORE_DISABLE_PROMPTS=false "$HOME/google-cloud-sdk/bin/gcloud" run deploy veridex-staging \
  --project=zeta-store-511505-i7 --region=us-west1 --account="${VERIDEX_OPERATOR_ACCOUNT:?}" \
  --image=us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex/veridex@sha256:894225e0e0e676759809d658b83a1a1948d9056966214ad83d46a6d7feb4ca04 \
  --service-account=veridex-runtime@zeta-store-511505-i7.iam.gserviceaccount.com \
  --execution-environment=gen2 --port=8080 --cpu=1 --memory=2Gi \
  --concurrency=1 --min=0 --max=1 --max-instances=1 \
  --timeout=300s --cpu-throttling --cpu-boost --no-session-affinity \
  --ingress=all --no-allow-unauthenticated --invoker-iam-check \
  --startup-probe='httpGet.path=/ready,httpGet.port=8080,initialDelaySeconds=0,periodSeconds=10,timeoutSeconds=3,failureThreshold=24' \
  --set-env-vars='APP_ENV=production,LOG_LEVEL=INFO,OPENAI_MODEL=gpt-5,OPENAI_EMBEDDING_MODEL=text-embedding-3-small,API_MAX_REQUEST_BODY_BYTES=65536,API_MAX_ACTIVE_REQUESTS=1,API_MAX_WAITING_REQUESTS=0,API_REQUEST_TIMEOUT_SECONDS=180,API_QUEUE_TIMEOUT_SECONDS=30,AGENT_MAX_TOOL_CALLS=8,AGENT_MAX_MODEL_CALLS=6,AGENT_MAX_COMPLETION_TOKENS=4096,AGENT_MAX_CONTEXT_CHARACTERS=64000,AGENT_MAX_SESSIONS=128,AGENT_SESSION_TTL_SECONDS=1800,AGENT_HISTORY_TURNS=6,PROVIDER_TIMEOUT_SECONDS=30,PROVIDER_MAX_RETRIES=0' \
  --set-secrets='OPENAI_API_KEY=veridex-openai-api-key:1,TAVILY_API_KEY=veridex-tavily-api-key:1'
```

Stop on unexpected API enablement prompts or permission failures. Do not approve
public access, add roles, change model, retry deployments or increase resources
as an automatic workaround. Recheck service absence immediately before execution.

## Post-deployment verification — PREPARED ONLY

```bash
GCLOUD="$HOME/google-cloud-sdk/bin/gcloud"
"$GCLOUD" run services describe veridex-staging --region=us-west1 \
  --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}" --format=export
"$GCLOUD" run services get-iam-policy veridex-staging --region=us-west1 \
  --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}" --format=json
```

Verify ready revision, pinned image, secrets references, runtime identity, resource
settings, startup probe, IAM check enabled and no allUsers/allAuthenticatedUsers.
Do not inspect/export container environment payloads or broadly print application
logs. No secret values are included in service metadata.

Authenticated GETs (token stays in Python memory, not shell arguments or output):

```bash
python3 - <<'PY'
import os, subprocess, urllib.request
sdk=os.path.expanduser('~/google-cloud-sdk/bin/gcloud')
common=['--project=zeta-store-511505-i7','--region=us-west1','--account='+os.environ['VERIDEX_OPERATOR_ACCOUNT']]
url=subprocess.run([sdk,'run','services','describe','veridex-staging',*common,'--format=value(status.url)'],capture_output=True,text=True,check=True).stdout.strip()
token=subprocess.run([sdk,'auth','print-identity-token','--account='+os.environ['VERIDEX_OPERATOR_ACCOUNT']],capture_output=True,text=True,check=True).stdout.strip()
for endpoint in ['/health','/ready','/attribution']:
    request=urllib.request.Request(url+endpoint,headers={'Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=300) as response:
        print(endpoint,response.status,response.read().decode())
PY
```

These GETs incur Cloud Run startup/request usage but no provider calls. Expected
health/ready200, attribution200 with notices. Check an anonymous GET is denied
403/401 separately without /chat. Live chat/provider validation needs a new
bounded call-plan approval; no POST /chat command is prepared for execution here.
Developer user ID tokens are for manual staging checks, not a production auth design.

## Costs, rights and cleanup

Request-based min0 avoids continuously reserved warm capacity; startup CPU boost,
startup/shutdown, requests, Secret Manager accesses and logging can incur charges.
At indicative Tier1 rates $0.000024/vCPU-second and $0.0000025/GiB-second,
1CPU/2Gi costs about $0.00174 per active minute before allowances; boost makes
startup higher. One 121-second startup is roughly $0.0035 without boost, plus
request/secret/logging charges. Native time may differ. Existing registry storage
is ~248MiB, account-wide allowance dependent. No load balancer/VPC connector/Cloud
Build is needed. USD5 alerts are not hard caps; OpenAI/Tavily costs are separate.
Use a short private verification window, then permit scale-to-zero; delete staging
when no longer needed. Retain billing alerts through cleanup.

Noncommercial coursework only; preserve bundled attribution endpoint/notices,
CC BY and two CC BY-NC papers, and documented third-party exclusions. Private
staging is not arbitrary commercial redistribution clearance.

Cleanup is destructive and separately approved; do not execute now:

```bash
"$HOME/google-cloud-sdk/bin/gcloud" run services delete veridex-staging \
  --project=zeta-store-511505-i7 --region=us-west1 --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
```

This leaves registry/secret versions/budget intact; their costs and cleanup are
separate. Next single gate: approve exactly this private staging deployment and
non-provider metadata/GET verification, including the explicit gpt-5 default.
No technical blocker found; native performance, provider credentials/model access,
organization policy/quota enforcement at deploy, and live-provider behavior remain
unverified. No public transition or provider testing is authorized by this preflight.

Sources: [container contract](https://docs.cloud.google.com/run/docs/container-contract),
[health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks),
[developer authentication](https://docs.cloud.google.com/run/docs/authenticating/developers),
[pricing](https://cloud.google.com/run/pricing).
