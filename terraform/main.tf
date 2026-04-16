data "aws_caller_identity" "current" {}

moved {
  from = aws_dynamodb_table.messages
  to   = aws_dynamodb_table.messages[0]
}

moved {
  from = aws_dynamodb_table.profile_memories
  to   = aws_dynamodb_table.profile_memories[0]
}

moved {
  from = aws_s3_bucket.frontend
  to   = aws_s3_bucket.frontend[0]
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # Canonical names: keep in sync with deploy.yml reuse/import (NAME_PREFIX = project-environment).
  lambda_function_name            = "${local.name_prefix}-api"
  iam_lambda_role_name            = "${local.name_prefix}-lambda"
  apigateway_http_api_name        = "${local.name_prefix}-http-api"
  cloudfront_oac_name             = "${local.name_prefix}-frontend-s3-oac"
  cloudfront_distribution_comment = "${local.name_prefix} persona static"

  # When an existing role ARN is provided, resolve it for optional inline policy attachment.
  use_existing_lambda_role = trimspace(var.lambda_execution_role_arn) != ""
  lambda_role_name         = local.use_existing_lambda_role ? regex("^arn:aws:iam::\\d+:role/(.+)$", var.lambda_execution_role_arn)[0] : ""

  use_existing_messages_table         = trimspace(var.existing_dynamodb_messages_table_name) != ""
  use_existing_profile_memories_table = trimspace(var.existing_dynamodb_profile_memories_table_name) != ""
  use_existing_frontend_s3_bucket     = trimspace(var.existing_frontend_s3_bucket_name) != ""

  # SPA / browser Origin(s) allowlisted for FastAPI CORS (Lambda env CORS_ORIGINS). This is NOT api_gateway_url:
  # the browser sends Origin = the page URL (CloudFront or a custom domain); Access-Control-Allow-Origin must match that.
  # With AWS_PROXY, OPTIONS preflights hit Lambda unless API-only CORS handles them—CORSMiddleware must be enabled here.
  cors_origins_effective = trimspace(var.cors_origins) != "" ? trimspace(var.cors_origins) : "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

data "aws_iam_role" "lambda_existing" {
  count = local.use_existing_lambda_role ? 1 : 0
  name  = local.lambda_role_name
}

# --- DynamoDB: chat messages ---
resource "aws_dynamodb_table" "messages" {
  count = local.use_existing_messages_table ? 0 : 1

  name         = "${local.name_prefix}-messages"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "message_id"

  attribute {
    name = "session_id"
    type = "S"
  }
  attribute {
    name = "message_id"
    type = "S"
  }

  tags = local.common_tags
}

data "aws_dynamodb_table" "messages_existing" {
  count = local.use_existing_messages_table ? 1 : 0
  name  = var.existing_dynamodb_messages_table_name
}

# --- DynamoDB: profile memories + GSI for delete by source session ---
resource "aws_dynamodb_table" "profile_memories" {
  count = local.use_existing_profile_memories_table ? 0 : 1

  name         = "${local.name_prefix}-profile-memories"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "mem_key"

  attribute {
    name = "session_id"
    type = "S"
  }
  attribute {
    name = "mem_key"
    type = "S"
  }
  attribute {
    name = "source_session_id"
    type = "S"
  }
  attribute {
    name = "owner_mem"
    type = "S"
  }

  global_secondary_index {
    name            = "BySourceSession"
    hash_key        = "source_session_id"
    range_key       = "owner_mem"
    projection_type = "ALL"
  }

  tags = local.common_tags
}

data "aws_dynamodb_table" "profile_memories_existing" {
  count = local.use_existing_profile_memories_table ? 1 : 0
  name  = var.existing_dynamodb_profile_memories_table_name
}

locals {
  messages_table_name = local.use_existing_messages_table ? data.aws_dynamodb_table.messages_existing[0].name : aws_dynamodb_table.messages[0].name
  messages_table_arn  = local.use_existing_messages_table ? data.aws_dynamodb_table.messages_existing[0].arn : aws_dynamodb_table.messages[0].arn

  profile_memories_table_name = local.use_existing_profile_memories_table ? data.aws_dynamodb_table.profile_memories_existing[0].name : aws_dynamodb_table.profile_memories[0].name
  profile_memories_table_arn  = local.use_existing_profile_memories_table ? data.aws_dynamodb_table.profile_memories_existing[0].arn : aws_dynamodb_table.profile_memories[0].arn
}

# --- Lambda IAM (only when lambda_execution_role_arn is not set) ---
resource "aws_iam_role" "lambda" {
  count = local.use_existing_lambda_role ? 0 : 1

  name = local.iam_lambda_role_name
  tags = local.common_tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  count = local.use_existing_lambda_role ? 0 : 1

  role       = aws_iam_role.lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  count = local.use_existing_lambda_role ? 0 : 1

  name = "${local.name_prefix}-lambda-ddb"
  role = aws_iam_role.lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:BatchWriteItem",
        "dynamodb:DescribeTable",
      ]
      Resource = [
        local.messages_table_arn,
        "${local.messages_table_arn}/index/*",
        local.profile_memories_table_arn,
        "${local.profile_memories_table_arn}/index/*",
      ]
    }]
  })
}

# Inline DynamoDB policy on your existing role (optional; skip if the role already has access)
resource "aws_iam_role_policy" "lambda_dynamodb_existing_role" {
  count = local.use_existing_lambda_role && var.attach_dynamodb_policy_to_existing_role ? 1 : 0

  name = "${local.name_prefix}-lambda-ddb-existing"
  role = data.aws_iam_role.lambda_existing[0].name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:BatchWriteItem",
        "dynamodb:DescribeTable",
      ]
      Resource = [
        local.messages_table_arn,
        "${local.messages_table_arn}/index/*",
        local.profile_memories_table_arn,
        "${local.profile_memories_table_arn}/index/*",
      ]
    }]
  })
}

resource "aws_lambda_function" "api" {
  function_name = local.lambda_function_name
  role          = local.use_existing_lambda_role ? var.lambda_execution_role_arn : aws_iam_role.lambda[0].arn
  handler       = "lambda_handler.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  environment {
    variables = {
      MEMORY_BACKEND          = "dynamodb"
      DYNAMODB_MESSAGES_TABLE = local.messages_table_name
      DYNAMODB_PROFILE_TABLE  = local.profile_memories_table_name
      SERVE_STATIC            = "false"
      CEREBRAS_API_KEY        = var.cerebras_api_key
      OPENROUTER_API_KEY      = var.openrouter_api_key
      OPENROUTER_BASE_URL     = var.openrouter_base_url
      OPENROUTER_MODEL        = var.openrouter_model
      APP_URL                 = var.app_url
      CORS_ORIGINS            = local.cors_origins_effective
    }
  }

  tags = local.common_tags
}

# --- HTTP API ---
resource "aws_apigatewayv2_api" "main" {
  name          = local.apigateway_http_api_name
  protocol_type = "HTTP"
  tags          = local.common_tags

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["*"]
    allow_methods     = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_origins     = ["*"]
    max_age           = 300
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
  tags        = local.common_tags

  default_route_settings {
    throttling_burst_limit = var.api_throttle_burst_limit
    throttling_rate_limit  = var.api_throttle_rate_limit
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# --- S3 static frontend ---
resource "aws_s3_bucket" "frontend" {
  count = local.use_existing_frontend_s3_bucket ? 0 : 1

  bucket = "${local.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  tags   = local.common_tags
}

data "aws_s3_bucket" "frontend_existing" {
  count  = local.use_existing_frontend_s3_bucket ? 1 : 0
  bucket = var.existing_frontend_s3_bucket_name
}

locals {
  frontend_bucket_id                   = local.use_existing_frontend_s3_bucket ? data.aws_s3_bucket.frontend_existing[0].id : aws_s3_bucket.frontend[0].id
  frontend_bucket_arn                  = local.use_existing_frontend_s3_bucket ? data.aws_s3_bucket.frontend_existing[0].arn : aws_s3_bucket.frontend[0].arn
  frontend_bucket_regional_domain_name = local.use_existing_frontend_s3_bucket ? data.aws_s3_bucket.frontend_existing[0].bucket_regional_domain_name : aws_s3_bucket.frontend[0].bucket_regional_domain_name
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = local.frontend_bucket_id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = local.cloudfront_oac_name
  description                       = "OAC for private S3 frontend origin (avoids public bucket policies)"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = local.frontend_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCloudFrontServicePrincipalReadOnly"
      Effect = "Allow"
      Principal = {
        Service = "cloudfront.amazonaws.com"
      }
      Action   = "s3:GetObject"
      Resource = "${local.frontend_bucket_arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })

  depends_on = [
    aws_cloudfront_distribution.frontend,
    aws_s3_bucket_public_access_block.frontend,
  ]
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = local.cloudfront_distribution_comment
  tags                = local.common_tags

  origin {
    domain_name              = local.frontend_bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "s3-frontend"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }
}
