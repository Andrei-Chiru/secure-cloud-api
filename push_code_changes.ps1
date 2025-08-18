$PROJECT="alpine-fin-469115-p2"
$REGION="europe-west4"
$REPO="containers"
$SERVICE="secure-cloud-api"
$TAG = (Get-Date -Format "yyyyMMddHHmmss")
$IMAGE = "{0}-docker.pkg.dev/{1}/{2}/{3}:{4}" -f $REGION, $PROJECT, $REPO, $SERVICE, $TAG

gcloud config set project $PROJECT | Out-Null

# ensure Artifact Registry repo exists (safe to re-run)
gcloud artifacts repositories describe $REPO --location=$REGION *> $null
if ($LASTEXITCODE -ne 0) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION
}

# build & push
gcloud builds submit --tag $IMAGE

# deploy (keep your env vars + secret wiring)
gcloud run deploy $SERVICE `
  --image $IMAGE `
  --region $REGION `
  --allow-unauthenticated `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,BQ_DATASET=demo_vectors,BQ_LOCATION=US,TRANSFORMERS_CACHE=/tmp/hf,HF_HOME=/tmp/hf" `
  --set-secrets "API_KEY=api-key:latest"