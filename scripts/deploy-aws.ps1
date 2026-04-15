param(
    [string]$Environment = "dev",
    [string]$ProjectName = "persona",
    [string]$AwsRegion = "us-east-1"
)
$ErrorActionPreference = "Stop"

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

Write-Host "Packaging Lambda..." -ForegroundColor Yellow
Set-Location (Join-Path $Root "backend")
uv run python package_lambda.py

Set-Location (Join-Path $Root "terraform")
if (-not (Test-Path "terraform.tfstate") -and -not (Test-Path ".terraform")) {
    terraform init
}
terraform apply `
    -var="project_name=$ProjectName" `
    -var="environment=$Environment" `
    -var="aws_region=$AwsRegion" `
    -auto-approve

$ApiUrl = terraform output -raw api_gateway_url
$Bucket = terraform output -raw s3_frontend_bucket
$CfUrl = terraform output -raw cloudfront_url

Write-Host "Building static site with VITE_API_BASE_URL=$ApiUrl" -ForegroundColor Yellow
Set-Location (Join-Path $Root "frontend")
$env:VITE_API_BASE_URL = $ApiUrl
npm run build:static

Write-Host "Uploading to S3..." -ForegroundColor Yellow
aws s3 sync ./dist-static "s3://$Bucket/" --delete

Write-Host "Done." -ForegroundColor Green
Write-Host "CloudFront: $CfUrl"
Write-Host "API:        $ApiUrl"
Write-Host "Invalidate CloudFront cache if assets look stale: aws cloudfront create-invalidation ..."
