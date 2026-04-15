output "api_gateway_url" {
  description = "API Gateway base URL (set VITE_API_BASE_URL to this when building static)"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "cloudfront_url" {
  description = "CloudFront URL for static site"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "s3_frontend_bucket" {
  description = "S3 bucket for static assets"
  value       = local.frontend_bucket_id
}

output "dynamodb_messages_table" {
  value = local.messages_table_name
}

output "dynamodb_profile_table" {
  value = local.profile_memories_table_name
}

output "lambda_function_name" {
  value = aws_lambda_function.api.function_name
}

output "lambda_execution_role_arn" {
  description = "IAM role used by the Lambda function"
  value       = aws_lambda_function.api.role
}
