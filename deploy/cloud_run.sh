#!/usr/bin/env bash
# Deploy Veridex v2 to Cloud Run.
#
#   bash deploy/cloud_run.sh bootstrap   # once per fresh GCP project (APIs, registry, Firestore, IAM, secrets)
#   bash deploy/cloud_run.sh deploy      # build with Cloud Build and deploy a new revision
#   bash deploy/cloud_run.sh verify      # health, readiness and service description
#
# Configuration comes from the environment (defaults in brackets):
#   GCP_PROJECT_ID [veridex-v2]  GCP_REGION [us-west1]  CLOUD_RUN_SERVICE [veridex-v2]
#   IMAGE_TAG [git short SHA]
# Prerequisites: gcloud authenticated for the project, uv, and the Corpus v3 bundle in
# .artifacts/corpus_v3 (uv run python scripts/corpus_v3.py download|plan|build|catalog).
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-veridex-v2}"
REGION="${GCP_REGION:-us-west1}"
SERVICE="${CLOUD_RUN_SERVICE:-veridex-v2}"
REPOSITORY="veridex"
RUNTIME_SA="veridex-v2-runtime@${PROJECT}.iam.gserviceaccount.com"
MIN_INSTANCES="${MIN_INSTANCES:-0}"  # 1 keeps a warm instance (no cold start, ~$0.86/day)
TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/veridex:${TAG}"
SECRETS=(openai-api-key gemini-api-key tavily-api-key)
G=(--project="${PROJECT}" --quiet)

bootstrap() {
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com secretmanager.googleapis.com firestore.googleapis.com \
    iam.googleapis.com "${G[@]}"
  gcloud artifacts repositories describe "${REPOSITORY}" --location="${REGION}" "${G[@]}" >/dev/null 2>&1 ||
    gcloud artifacts repositories create "${REPOSITORY}" --repository-format=docker \
      --location="${REGION}" "${G[@]}"
  gcloud firestore databases describe --database='(default)' "${G[@]}" >/dev/null 2>&1 ||
    gcloud firestore databases create --location="${REGION}" --type=firestore-native "${G[@]}"
  gcloud iam service-accounts describe "${RUNTIME_SA}" "${G[@]}" >/dev/null 2>&1 ||
    gcloud iam service-accounts create veridex-v2-runtime --display-name="Veridex v2 runtime" "${G[@]}"
  gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/datastore.user --condition=None "${G[@]}" >/dev/null
  # Cloud Build runs as the default compute service account in new projects.
  local number build_sa
  number="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
  build_sa="${number}-compute@developer.gserviceaccount.com"
  for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
    gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${build_sa}" \
      --role="${role}" --condition=None "${G[@]}" >/dev/null
  done
  for secret in "${SECRETS[@]}"; do
    if ! gcloud secrets describe "${secret}" "${G[@]}" >/dev/null 2>&1; then
      read -r -s -p "Value for ${secret}: " value && echo
      printf %s "${value}" | gcloud secrets create "${secret}" --replication-policy=automatic \
        --data-file=- "${G[@]}"
      unset value
    fi
    gcloud secrets add-iam-policy-binding "${secret}" --member="serviceAccount:${RUNTIME_SA}" \
      --role=roles/secretmanager.secretAccessor "${G[@]}" >/dev/null
  done
  echo "Bootstrap complete for ${PROJECT}."
}

deploy() {
  uv run python scripts/check_bundle.py
  gcloud builds submit --tag="${IMAGE}" --timeout=1800 "${G[@]}" .
  gcloud run deploy "${SERVICE}" --image="${IMAGE}" --region="${REGION}" "${G[@]}" \
    --service-account="${RUNTIME_SA}" \
    --allow-unauthenticated \
    --memory=2Gi --cpu=2 --cpu-boost \
    --concurrency=10 --timeout=300 \
    --min-instances="${MIN_INSTANCES}" --max-instances=3 \
    --set-env-vars="STATE_BACKEND=firestore,FIRESTORE_PROJECT_ID=${PROJECT},API_MAX_ACTIVE_REQUESTS=4,API_MAX_WAITING_REQUESTS=6,API_REQUEST_TIMEOUT_SECONDS=240" \
    --set-secrets="OPENAI_API_KEY=openai-api-key:latest,GOOGLE_API_KEY=gemini-api-key:latest,TAVILY_API_KEY=tavily-api-key:latest"
  verify
}

verify() {
  local url
  url="$(gcloud run services describe "${SERVICE}" --region="${REGION}" "${G[@]}" --format='value(status.url)')"
  echo "Service URL: ${url}"
  curl -fsS "${url}/health" && echo
  curl -fsS --max-time 120 "${url}/ready" && echo
  curl -fsS "${url}/api/info" && echo
}

case "${1:-}" in
  bootstrap) bootstrap ;;
  deploy) deploy ;;
  verify) verify ;;
  *) echo "usage: bash deploy/cloud_run.sh bootstrap|deploy|verify" >&2; exit 2 ;;
esac
