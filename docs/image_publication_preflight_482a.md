# Step 4.8.2a — image publication preflight

PREPARATION ONLY. No build, tag, push, registry write, or deployment was executed.

The current candidate is `veridex:phase04-v2-local`, Linux/amd64, local image ID
`sha256:38c2bb0aed856da0fa8724e4ffc0dd27cf4c461b69b97b8822d5b854ee544289`,
834,267,880 bytes (795.62 MiB). It matches the Step 4.7h verified release.
No registry RepoDigest exists yet. Source bundle is
`.artifacts/versions/veridex-rag-v2-local`; its bundle.json SHA-256 is
`7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb`.
All recorded inventory sizes/checksums match. Collection `veridex_documents`
contains 586 chunks, five v2 document IDs, and 1536-dimensional
`text-embedding-3-small` vectors. The image's immutable canonical bundle is
validated before creating a private writable Chroma copy under /tmp.

Runtime uses UID/GID 10001:10001, one worker, 0.0.0.0:$PORT (8080 default),
SIGTERM and the existing 0.5-second HTTP drain / 8-second lifecycle budget.
Entrypoint: /opt/venv/bin/python /app/scripts/container_entrypoint.py.
Secrets must be supplied at runtime; none are needed for offline validation.

Registry `us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex` is a private,
empty standard Docker repository; scanning remains disabled. The USC operator
has verified uploadArtifacts, downloadArtifacts, tags.create and tags.update.
No IAM changes are needed for this operator. Existing Owner privileges are broad;
this verification does not make the deployment identity least-privilege.

## Prepared commands — NOT EXECUTED

Rebuild is unnecessary. This fallback build requires new approval and the release
source/lockfile corresponding to the verified image; pinned dependencies/base
images improve reproducibility but do not promise a byte-identical image ID:

```bash
docker buildx build --platform linux/amd64 \
  --build-context rag=.artifacts/versions/veridex-rag-v2-local \
  --build-arg RAG_BUNDLE_SHA256=7f1398ecc8958faa6b0bb24cb9061ab0ec33d8e87f9782d8d9e72938891ae1fb \
  --load --tag veridex:phase04-v2-local .
```

Proposed unique release tag: `phase04-v2-47h-38c2bb0aed85`.
Repository tag immutability is not enabled; do not change that configuration in
this step. This tag is immutable by release policy only. Recheck tag absence
before publication and never overwrite it; use the resulting digest for Run.
Local tagging, Docker authentication configuration, and pushing require the next
explicit publication approval:

```bash
(
set -e
GCLOUD="$HOME/google-cloud-sdk/bin/gcloud"
IMAGE=us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex/veridex
TAG=phase04-v2-47h-38c2bb0aed85
EXPECTED=sha256:38c2bb0aed856da0fa8724e4ffc0dd27cf4c461b69b97b8822d5b854ee544289
OBSERVED=$(docker image inspect veridex:phase04-v2-local --format '{{.Id}}')
test "$OBSERVED" = "$EXPECTED"
# Inspect this list; STOP if the proposed tag exists.
"$GCLOUD" artifacts docker tags list "$IMAGE" \
  --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
# Configure the helper only for the approved hostname; no literal credentials.
"$GCLOUD" auth configure-docker us-west1-docker.pkg.dev --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
docker tag "$EXPECTED" "$IMAGE:$TAG"
docker push "$IMAGE:$TAG"
"$GCLOUD" artifacts docker images describe "$IMAGE:$TAG" \
  --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}" --format=json
docker buildx imagetools inspect "$IMAGE:$TAG"
)
```

The manual absence check must finish before executing the remaining commands.
Record the push/registry manifest digest and verify it matches both remote
inspection outputs. Future deployment reference:
`us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex/veridex@sha256:<VERIFIED_REGISTRY_DIGEST>`.
The local image ID is a config digest; the registry manifest digest is a different
object, and neither equals the source bundle metadata checksum. A tag is a name.

Cleanup requires separate approval; inspect references first. Remote deletion is
destructive and may affect any tags referencing that digest. Keep local verified
candidate and source bundle:

```bash
"$HOME/google-cloud-sdk/bin/gcloud" artifacts docker images delete \
  us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex/veridex@sha256:REPLACE_WITH_VERIFIED_DIGEST \
  --delete-tags --project=zeta-store-511505-i7 --account="${VERIDEX_OPERATOR_ACCOUNT:?}"
# Optional removal of only the added local destination tag:
docker image rm us-west1-docker.pkg.dev/zeta-store-511505-i7/veridex/veridex:phase04-v2-47h-38c2bb0aed85
```

## Rights and costs

Image includes read-only attribution.json, CORPUS_NOTICE.txt, CC BY 4.0 and
CC BY-NC 4.0 texts; GET /attribution exposes notices. ACL replacement, ReAct and
Self-RAG use CC BY 4.0; NetMHCpan and MixMHC2pred use CC BY-NC 4.0.
Retain attribution, source/version and processing disclosures and third-party
scope limitations. Intended use is the approved noncommercial coursework demo;
publication authorization is still pending. Embedded historic authorization flags
remain false and are not rewritten to obtain publication approval. This is not
commercial-use clearance or a grant for separate datasets/software/supplements.

[Registry pricing](https://cloud.google.com/artifact-registry/pricing): storage
has a billing-account-wide 0.5 GiB free allowance; paid storage is approximately
$0.10/GiB-month. The 0.777 GiB local size is not compressed registry storage size.
Using it conservatively as an estimate gives about $0.028/month with the free
allowance unused, or $0.078/month if exhausted. Actual registry size must be
measured after an approved push. Upload ingress and same-region Cloud Run pulls
are free; Internet downloads/cross-region transfers can incur charges.
Scanning is disabled. The $5 budget alerts are not spending caps.

Next single gate: approve tagging/auth-helper configuration/publication of exactly
this reviewed image to this private repository. No rebuild, IAM change, Cloud Run
deployment, public invocation, secret access, or paid-provider test is included.

## Verification performed

Offline Linux/amd64 container audit succeeded: SQLite 3.46.1 / FTS5 integrity OK,
586 metadata records and vectors preserved, 586 native self-queries passed, four
functional text filters passed, UID 10001. Chroma operated only on disposable
container copies, with networking disabled and no host artifact mounts.
All ten image layers were inspected; excluded-file and credential-pattern checks
found no suspicious matches (a targeted audit, not a universal secret-detection
guarantee). /app contains only src, scripts, pyproject.toml and uv.lock. Image
PDF inventory is exactly the five v2 filenames; all four notice files are present.
All 75 protected artifact size/mtime/SHA-256 records remain unchanged.
`git diff --check` passed. No production files changed and no full test-suite rerun
was needed for this documentation/read-only preflight. No rebuild is indicated.
The audit's remote_publication=BLOCKED reflects the intentional authorization gate,
not an integrity failure. No registry manifest digest is available before push.
