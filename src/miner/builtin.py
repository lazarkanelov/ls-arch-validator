"""Built-in test architectures for guaranteed baseline testing."""

from __future__ import annotations

from src.models import Architecture, ArchitectureMetadata, ArchitectureSourceType

# Built-in architectures that are guaranteed to work with LocalStack
BUILTIN_ARCHITECTURES = [
    {
        "id": "builtin-s3-lambda-trigger",
        "name": "S3 Lambda Trigger",
        "description": "S3 bucket that triggers Lambda function on object creation",
        "services": ["S3", "Lambda", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "source" {
  bucket = "my-source-bucket-${random_id.suffix.hex}"
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_iam_role" "lambda" {
  name = "lambda-s3-trigger-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "processor" {
  filename         = "lambda.zip"
  function_name    = "s3-processor"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")
}

resource "aws_lambda_permission" "s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.source.arn
}

resource "aws_s3_bucket_notification" "trigger" {
  bucket = aws_s3_bucket.source.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.s3]
}
''',
    },
    {
        "id": "builtin-sqs-lambda",
        "name": "SQS Lambda Consumer",
        "description": "SQS queue with Lambda consumer",
        "services": ["SQS", "Lambda", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_sqs_queue" "main" {
  name                       = "my-queue"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 86400
}

resource "aws_iam_role" "lambda" {
  name = "lambda-sqs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "sqs" {
  name = "sqs-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ]
      Resource = aws_sqs_queue.main.arn
    }]
  })
}

resource "aws_lambda_function" "consumer" {
  filename         = "lambda.zip"
  function_name    = "sqs-consumer"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")
}

resource "aws_lambda_event_source_mapping" "sqs" {
  event_source_arn = aws_sqs_queue.main.arn
  function_name    = aws_lambda_function.consumer.arn
  batch_size       = 10
}
''',
    },
    {
        "id": "builtin-dynamodb-api",
        "name": "DynamoDB REST API",
        "description": "API Gateway with Lambda backend and DynamoDB",
        "services": ["API Gateway", "Lambda", "DynamoDB", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_dynamodb_table" "items" {
  name           = "items"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "id"

  attribute {
    name = "id"
    type = "S"
  }
}

resource "aws_iam_role" "lambda" {
  name = "lambda-dynamodb-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "dynamodb" {
  name = "dynamodb-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:DeleteItem",
        "dynamodb:Scan"
      ]
      Resource = aws_dynamodb_table.items.arn
    }]
  })
}

resource "aws_lambda_function" "api" {
  filename         = "lambda.zip"
  function_name    = "items-api"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.items.name
    }
  }
}

resource "aws_apigatewayv2_api" "main" {
  name          = "items-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id             = aws_apigatewayv2_api.main.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.api.invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "prod"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
''',
    },
    {
        "id": "builtin-sns-sqs-fanout",
        "name": "SNS SQS Fanout",
        "description": "SNS topic with multiple SQS subscribers",
        "services": ["SNS", "SQS", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_sns_topic" "events" {
  name = "events-topic"
}

resource "aws_sqs_queue" "worker1" {
  name = "worker1-queue"
}

resource "aws_sqs_queue" "worker2" {
  name = "worker2-queue"
}

resource "aws_sqs_queue_policy" "worker1" {
  queue_url = aws_sqs_queue.worker1.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = "*"
      Action = "sqs:SendMessage"
      Resource = aws_sqs_queue.worker1.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_sns_topic.events.arn
        }
      }
    }]
  })
}

resource "aws_sqs_queue_policy" "worker2" {
  queue_url = aws_sqs_queue.worker2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = "*"
      Action = "sqs:SendMessage"
      Resource = aws_sqs_queue.worker2.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_sns_topic.events.arn
        }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "worker1" {
  topic_arn = aws_sns_topic.events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.worker1.arn
}

resource "aws_sns_topic_subscription" "worker2" {
  topic_arn = aws_sns_topic.events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.worker2.arn
}
''',
    },
    {
        "id": "builtin-step-functions",
        "name": "Step Functions Workflow",
        "description": "Step Functions state machine with Lambda tasks",
        "services": ["Step Functions", "Lambda", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_iam_role" "lambda" {
  name = "lambda-step-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_lambda_function" "task1" {
  filename         = "lambda.zip"
  function_name    = "step-task1"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")
}

resource "aws_lambda_function" "task2" {
  filename         = "lambda.zip"
  function_name    = "step-task2"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")
}

resource "aws_iam_role" "sfn" {
  name = "sfn-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "states.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "sfn_lambda" {
  name = "invoke-lambda"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "lambda:InvokeFunction"
      Resource = [
        aws_lambda_function.task1.arn,
        aws_lambda_function.task2.arn
      ]
    }]
  })
}

resource "aws_sfn_state_machine" "workflow" {
  name     = "workflow"
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    StartAt = "Task1"
    States = {
      Task1 = {
        Type     = "Task"
        Resource = aws_lambda_function.task1.arn
        Next     = "Task2"
      }
      Task2 = {
        Type     = "Task"
        Resource = aws_lambda_function.task2.arn
        End      = true
      }
    }
  })
}
''',
    },
    {
        "id": "builtin-kinesis-lambda",
        "name": "Kinesis Stream Processor",
        "description": "Kinesis Data Stream with Lambda consumer",
        "services": ["Kinesis", "Lambda", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_kinesis_stream" "events" {
  name             = "events-stream"
  shard_count      = 1
  retention_period = 24
}

resource "aws_iam_role" "lambda" {
  name = "lambda-kinesis-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "kinesis" {
  name = "kinesis-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "kinesis:GetRecords",
        "kinesis:GetShardIterator",
        "kinesis:DescribeStream",
        "kinesis:ListShards"
      ]
      Resource = aws_kinesis_stream.events.arn
    }]
  })
}

resource "aws_lambda_function" "processor" {
  filename         = "lambda.zip"
  function_name    = "kinesis-processor"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")
}

resource "aws_lambda_event_source_mapping" "kinesis" {
  event_source_arn  = aws_kinesis_stream.events.arn
  function_name     = aws_lambda_function.processor.arn
  starting_position = "LATEST"
  batch_size        = 100
}
''',
    },
    {
        "id": "builtin-eventbridge-lambda",
        "name": "EventBridge Rule",
        "description": "EventBridge scheduled rule triggering Lambda",
        "services": ["EventBridge", "Lambda", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_iam_role" "lambda" {
  name = "lambda-eventbridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_lambda_function" "handler" {
  filename         = "lambda.zip"
  function_name    = "scheduled-handler"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")
}

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "hourly-trigger"
  schedule_expression = "rate(1 hour)"
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "lambda"
  arn       = aws_lambda_function.handler.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
''',
    },
    {
        "id": "builtin-secrets-lambda",
        "name": "Secrets Manager Lambda",
        "description": "Lambda function accessing Secrets Manager",
        "services": ["Secrets Manager", "Lambda", "IAM"],
        "main_tf": '''
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_secretsmanager_secret" "db_creds" {
  name = "db-credentials"
}

resource "aws_secretsmanager_secret_version" "db_creds" {
  secret_id = aws_secretsmanager_secret.db_creds.id
  secret_string = jsonencode({
    username = "admin"
    password = "password123"
  })
}

resource "aws_iam_role" "lambda" {
  name = "lambda-secrets-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "secrets" {
  name = "secrets-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.db_creds.arn
    }]
  })
}

resource "aws_lambda_function" "app" {
  filename         = "lambda.zip"
  function_name    = "secrets-app"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  source_code_hash = filebase64sha256("lambda.zip")

  environment {
    variables = {
      SECRET_ARN = aws_secretsmanager_secret.db_creds.arn
    }
  }
}
''',
    },
]


def get_builtin_architectures() -> list[Architecture]:
    """Get list of built-in test architectures."""
    architectures = []

    for arch_data in BUILTIN_ARCHITECTURES:
        # Count resources in the terraform code
        resource_count = arch_data["main_tf"].count('resource "')

        # Determine complexity based on resource count
        if resource_count <= 3:
            complexity = "low"
        elif resource_count <= 6:
            complexity = "medium"
        else:
            complexity = "high"

        arch = Architecture(
            id=arch_data["id"],
            source_type=ArchitectureSourceType.TEMPLATE,
            source_name="builtin",
            source_url=None,
            main_tf=arch_data["main_tf"].strip(),
            metadata=ArchitectureMetadata(
                services=arch_data["services"],
                resource_count=resource_count,
                complexity=complexity,
                original_format="terraform",
            ),
        )
        architectures.append(arch)

    return architectures
