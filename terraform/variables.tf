variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for resources"
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "Project name must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Environment name (dev, test, prod)"
  type        = string
  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "Environment must be one of: dev, test, prod."
  }
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 120
}

variable "lambda_memory_size" {
  description = "Lambda memory in MB"
  type        = number
  default     = 512
}

variable "api_throttle_burst_limit" {
  description = "API Gateway throttle burst"
  type        = number
  default     = 100
}

variable "api_throttle_rate_limit" {
  description = "API Gateway throttle rate"
  type        = number
  default     = 50
}

variable "lambda_zip_path" {
  description = "Path to lambda-deployment.zip (run scripts/build-lambda.ps1 or .sh first)"
  type        = string
  default     = "../backend/lambda-deployment.zip"
}

variable "lambda_execution_role_arn" {
  description = <<-EOT
    Existing IAM role ARN for the Lambda (e.g. arn:aws:iam::123456789012:role/my-lambda-role).
    When set, Terraform does not create a new Lambda execution role; it attaches a DynamoDB policy to that role.
    Leave empty to let Terraform create and manage a dedicated role (default).
  EOT
  type        = string
  default     = ""
}

variable "attach_dynamodb_policy_to_existing_role" {
  description = "When using lambda_execution_role_arn, whether to attach Terraform-managed DynamoDB table access (inline policy). Set false if your role already has the needed DynamoDB permissions."
  type        = bool
  default     = true
}

variable "existing_dynamodb_messages_table_name" {
  description = <<-EOT
    When set, Terraform does not create the messages table; it uses this existing table name.
    The table schema must match what this stack expects (keys and attributes as in main.tf).
    Leave empty to create and manage the table (default).
  EOT
  type        = string
  default     = ""
  validation {
    condition     = var.existing_dynamodb_messages_table_name == "" || can(regex("^[a-zA-Z0-9_.-]{3,255}$", var.existing_dynamodb_messages_table_name))
    error_message = "When set, must be a valid DynamoDB table name (3-255 chars: letters, numbers, . _ -)."
  }
}

variable "existing_dynamodb_profile_memories_table_name" {
  description = <<-EOT
    When set, Terraform does not create the profile-memories table; it uses this existing table name.
    The table schema must match what this stack expects (keys, GSI BySourceSession, etc.).
    Leave empty to create and manage the table (default).
  EOT
  type        = string
  default     = ""
  validation {
    condition     = var.existing_dynamodb_profile_memories_table_name == "" || can(regex("^[a-zA-Z0-9_.-]{3,255}$", var.existing_dynamodb_profile_memories_table_name))
    error_message = "When set, must be a valid DynamoDB table name (3-255 chars: letters, numbers, . _ -)."
  }
}

variable "existing_frontend_s3_bucket_name" {
  description = <<-EOT
    When set, Terraform does not create the frontend S3 bucket; it uses this existing bucket.
    Terraform still manages the bucket public access block and bucket policy for CloudFront OAC.
    Leave empty to create and manage the bucket (default).
  EOT
  type        = string
  default     = ""
  validation {
    condition     = var.existing_frontend_s3_bucket_name == "" || can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.existing_frontend_s3_bucket_name)) && length(var.existing_frontend_s3_bucket_name) >= 3 && length(var.existing_frontend_s3_bucket_name) <= 63
    error_message = "When set, must be a valid S3 bucket name (3-63 chars, DNS-compliant)."
  }
}

variable "cerebras_api_key" {
  description = "Cerebras API key (sensitive)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "openrouter_api_key" {
  description = "OpenRouter API key (sensitive)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "openrouter_base_url" {
  description = "OpenRouter base URL"
  type        = string
  default     = "https://openrouter.ai/api/v1"
}

variable "app_url" {
  description = "APP_URL for LLM client headers"
  type        = string
  default     = "https://localhost"
}
