param()

$ErrorActionPreference = "Stop"

# --- helper: strip surrounding quotes from values in .env ---
function Strip-Quotes([string]$s) {
  if ($null -eq $s) { return $null }
  $t = $s.Trim()
  if (($t.StartsWith('"') -and $t.EndsWith('"')) -or ($t.StartsWith("'") -and $t.EndsWith("'"))) {
    return $t.Substring(1, $t.Length - 2)
  }
  return $t
}

# --- load .env into $env: (ignores comments / blank lines) ---
$envPath = Join-Path -Path (Get-Location) -ChildPath ".env"
if (-not (Test-Path $envPath)) {
  throw ".env not found. Create it (copy from .env.example) and fill values."
}
Get-Content $envPath | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$' -or $_ -notmatch '=') { return }
  $pair = $_ -split '=', 2
  $k = $pair[0].Trim()
  $v = Strip-Quotes($pair[1])
  if ($k) { Set-Item -Path "Env:$k" -Value $v }
}

# --- required env ---
if ([string]::IsNullOrWhiteSpace($env:GOOGLE_CLOUD_PROJECT)) { throw "GOOGLE_CLOUD_PROJECT must be set in .env" }
if ([string]::IsNullOrWhiteSpace($env:API_KEY))               { throw "API_KEY must be set in .env" }
if ([string]::IsNullOrWhiteSpace($env:BQ_DATASET))            { $env:BQ_DATASET = "demo_vectors" }
if ([string]::IsNullOrWhiteSpace($env:BQ_LOCATION))           { $env:BQ_LOCATION = "US" }

# --- defaults (overridable via .env) ---
$REGION  = if ([string]::IsNullOrWhiteSpace($env:REGION))  { "europe-west4" }    else { $env:REGION }
$REPO    = if ([string]::IsNullOrWhiteSpace($env:REPO))    { "containers"   }    else { $env:REPO }
$SERVICE = if ([string]::IsNullOrWhiteSpace($env:SERVICE)) { "secure-cloud-api" } else { $env:SERVICE }
$SA_NAME = if ([string]::IsNullOrWhiteSpace($env:SA_NAME)) { "secure-cloud-api-sa" } else { $env:SA_NAME }

# --- basic name validation (Cloud Run / AR) ---
if ($SERVICE -notmatch '^[a-z]([-a-z0-9]{0,62})$') { throw "SERVICE '$SERVICE' is invalid (lowercase letters, digits, hyphens; start with a letter; max 63 chars)." }
if ($REPO    -notmatch '^[a-z]([-a-z0-9]{0,62})$') { throw "REPO '$REPO' is invalid (lowercase letters, digits, hyphens; start with a letter; max 63 chars)." }

$PROJECT = $env:GOOGLE_CLOUD_PROJECT
$SA_EMAIL = "$SA_NAME@$PROJECT.iam.gserviceaccount.com"

# --- build robust image tag (cannot drop /SERVICE) ---
$IMAGE = ('{0}-docker.pkg.dev/{1}/{2}/{3}:latest' -f $REGION, $PROJECT, $REPO, $SERVICE)
if ($IMAGE -notmatch '^[a-z0-9-]+-docker\.pkg\.dev/[^/]+/[^/]+/[^/:]+:[^:]+$') {
  throw "Computed image tag '$IMAGE' looks wrong. Expected '<region>-docker.pkg.dev/<project>/<repo>/<service>:tag'."
}

Write-Host "Project     : $PROJECT"
Write-Host "Region      : $REGION"
Write-Host "Repo        : $REPO"
Write-Host "Service     : $SERVICE"
Write-Host "Dataset     : $($env:BQ_DATASET) ($($env:BQ_LOCATION))"
Write-Host "ServiceAcct : $SA_EMAIL"
Write-Host "IMAGE       : $IMAGE"
Write-Host ""

# --- enable required APIs ---
gcloud config set project $PROJECT | Out-Null
gcloud services enable `
  run.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  bigquery.googleapis.com `
  secretmanager.googleapis.com | Out-Null

# --- ensure Artifact Registry repo exists ---
gcloud artifacts repositories describe $REPO --location=$REGION *> $null
if ($LASTEXITCODE -ne 0) {
  gcloud artifacts repositories create $REPO `
    --repository-format=docker `
    --location=$REGION `
    --description="Containers for $PROJECT"
}

# --- build & push with Cloud Build ---
gcloud builds submit --tag $IMAGE

# --- ensure runtime service account exists ---
gcloud iam service-accounts describe $SA_EMAIL *> $null
if ($LASTEXITCODE -ne 0) {
  gcloud iam service-accounts create $SA_NAME --display-name "Secure API (Cloud Run)"
}

# --- grant BigQuery roles (idempotent) ---
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA_EMAIL" --role="roles/bigquery.user"        | Out-Null
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA_EMAIL" --role="roles/bigquery.dataEditor"  | Out-Null

# --- Secret Manager: store API_KEY (create or add version) ---
gcloud secrets describe api-key *> $null
$apiTmp = Join-Path $env:TEMP "api_key_$([Guid]::NewGuid().ToString('N')).txt"
[IO.File]::WriteAllText($apiTmp, $env:API_KEY)
if ($LASTEXITCODE -ne 0) { gcloud secrets create api-key --data-file="$apiTmp" } else { gcloud secrets versions add api-key --data-file="$apiTmp" }
Remove-Item $apiTmp -Force

# allow runtime SA to read the secret
gcloud secrets add-iam-policy-binding api-key --member="serviceAccount:$SA_EMAIL" --role="roles/secretmanager.secretAccessor" | Out-Null

# --- deploy to Cloud Run ---
gcloud run deploy $SERVICE `
  --image $IMAGE `
  --region $REGION `
  --service-account $SA_EMAIL `
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,BQ_DATASET=$($env:BQ_DATASET),BQ_LOCATION=$($env:BQ_LOCATION),TRANSFORMERS_CACHE=/tmp/hf,HF_HOME=/tmp/hf" `
  --set-secrets "API_KEY=api-key:latest" `
  --memory "1Gi" --cpu "1" --concurrency "20" `
  --allow-unauthenticated

# --- show URL & quick health check ---
$URL = gcloud run services describe $SERVICE --region $REGION --format "value(status.url)"
Write-Host ""
Write-Host "Deployed: $URL"