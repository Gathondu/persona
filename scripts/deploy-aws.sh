#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-dev}"
PROJECT_NAME="${2:-persona}"
AWS_REGION="${3:-us-east-1}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Packaging Lambda..."
(cd backend && uv run python package_lambda.py)

cd "$ROOT/terraform"
if [[ ! -d .terraform ]]; then
  terraform init
fi
terraform apply \
  -var="project_name=${PROJECT_NAME}" \
  -var="environment=${ENVIRONMENT}" \
  -var="aws_region=${AWS_REGION}" \
  -auto-approve

API_URL="$(terraform output -raw api_gateway_url)"
BUCKET="$(terraform output -raw s3_frontend_bucket)"
CF_URL="$(terraform output -raw cloudfront_url)"

echo "Building static site..."
cd "$ROOT/frontend"
export VITE_API_BASE_URL="$API_URL"
npm run build:static

echo "Uploading to S3..."
aws s3 sync ./dist-static "s3://${BUCKET}/" --delete

echo "Done."
echo "CloudFront: $CF_URL"
echo "API:        $API_URL"
