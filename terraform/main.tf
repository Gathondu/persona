data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # When an existing role ARN is provided, resolve it for optional inline policy attachment.
  use_existing_lambda_role = trimspace(var.lambda_execution_role_arn) != ""
  lambda_role_name         = local.use_existing_lambda_role ? regex("^arn:aws:iam::\\d+:role/(.+)$", var.lambda_execution_role_arn)[0] : ""
}

data "aws_iam_role" "lambda_existing" {
  count = local.use_existing_lambda_role ? 1 : 0
  name  = local.lambda_role_name
}

# --- DynamoDB: chat messages ---
resource "aws_dynamodb_table" "messages" {
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

# --- DynamoDB: profile memories + GSI for delete by source session ---
resource "aws_dynamodb_table" "profile_memories" {
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

# --- Lambda IAM (only when lambda_execution_role_arn is not set) ---
resource "aws_iam_role" "lambda" {
  count = local.use_existing_lambda_role ? 0 : 1

  name = "${local.name_prefix}-lambda"
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
        aws_dynamodb_table.messages.arn,
        "${aws_dynamodb_table.messages.arn}/index/*",
        aws_dynamodb_table.profile_memories.arn,
        "${aws_dynamodb_table.profile_memories.arn}/index/*",
      ]
    }]
  })
}

# Inline DynamoDB policy on your existing role (optional; skip if the role already has access)
resource "aws_iam_role_policy" "lambda_dynamodb_existing_role" {
  count = local.use_existing_lambda_role && var.attach_dynamodb_policy_to_existing_role ? 1 : 0

  name = "${local.name_prefix}-persona-ddb"
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
        aws_dynamodb_table.messages.arn,
        "${aws_dynamodb_table.messages.arn}/index/*",
        aws_dynamodb_table.profile_memories.arn,
        "${aws_dynamodb_table.profile_memories.arn}/index/*",
      ]
    }]
  })
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name_prefix}-api"
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
      DYNAMODB_MESSAGES_TABLE = aws_dynamodb_table.messages.name
      DYNAMODB_PROFILE_TABLE  = aws_dynamodb_table.profile_memories.name
      SERVE_STATIC            = "false"
      CEREBRAS_API_KEY        = var.cerebras_api_key
      OPENROUTER_API_KEY      = var.openrouter_api_key
      OPENROUTER_BASE_URL     = var.openrouter_base_url
      APP_URL                 = var.app_url
    }
  }

  tags = local.common_tags
}

# --- HTTP API ---
resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name_prefix}-http-api"
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
  bucket = "${local.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  tags   = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend-s3-oac"
  description                       = "OAC for private S3 frontend origin (avoids public bucket policies)"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCloudFrontServicePrincipalReadOnly"
      Effect = "Allow"
      Principal = {
        Service = "cloudfront.amazonaws.com"
      }
      Action = "s3:GetObject"
      Resource = "${aws_s3_bucket.frontend.arn}/*"
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
  comment             = "${local.name_prefix} persona static"
  tags                = local.common_tags

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
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
