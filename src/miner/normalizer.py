"""Template normalizer for LocalStack compatibility."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.models import Architecture, ArchitectureMetadata, ArchitectureSourceType
from src.utils.logging import get_logger

logger = get_logger("miner.normalizer")

# AWS services that LocalStack supports
LOCALSTACK_SUPPORTED_SERVICES = {
    # Core services
    "s3", "sqs", "sns", "lambda", "dynamodb", "kinesis",
    # API & Integration
    "apigateway", "apigatewayv2", "appsync", "eventbridge", "stepfunctions",
    # Compute
    "ec2", "ecs", "ecr",
    # Database
    "rds", "elasticache", "redshift", "opensearch",
    # Security & Identity
    "iam", "cognito", "secretsmanager", "ssm", "kms",
    # Monitoring & Logging
    "cloudwatch", "cloudwatchlogs", "cloudwatchevents",
    # Storage & CDN
    "cloudfront", "efs",
    # Networking
    "vpc", "elb", "elbv2", "route53",
    # Other
    "ses", "acm", "athena", "glue",
}

# Services known to be unsupported or have limited support
KNOWN_LIMITATIONS = {
    "eks": "EKS has limited support in LocalStack Community",
    "lakeformation": "Lake Formation is not supported",
    "iotanalytics": "IoT Analytics is not supported",
    "rekognition": "Rekognition has limited support",
    "textract": "Textract has limited support",
    "comprehend": "Comprehend has limited support",
}


@dataclass
class NormalizationResult:
    """Result of normalizing a template."""

    main_tf: str = ""
    variables_tf: Optional[str] = None
    outputs_tf: Optional[str] = None
    services: set[str] = field(default_factory=set)
    unsupported_services: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    complexity_score: int = 0


class TemplateNormalizer:
    """
    Normalizes templates for LocalStack compatibility.

    This includes:
    - Configuring LocalStack endpoints
    - Removing hardcoded regions and account IDs
    - Parameterizing resource names
    - Detecting used services
    """

    def __init__(self) -> None:
        """Initialize the normalizer."""
        pass

    def normalize(
        self,
        terraform_content: str,
        template_id: str,
    ) -> NormalizationResult:
        """
        Normalize a Terraform template for LocalStack.

        Args:
            terraform_content: Terraform HCL content
            template_id: Template identifier

        Returns:
            NormalizationResult with normalized content
        """
        result = NormalizationResult()

        # Detect services used
        result.services = self._detect_services(terraform_content)

        # Check for unsupported services
        result.unsupported_services = self._check_unsupported(result.services)

        # Normalize the content
        normalized = terraform_content

        # Add/update provider configuration for LocalStack
        normalized = self._ensure_localstack_provider(normalized)

        # Replace hardcoded regions
        normalized = self._normalize_region(normalized)

        # Replace hardcoded account IDs
        normalized = self._normalize_account_id(normalized)

        # Parameterize resource names
        normalized = self._parameterize_names(normalized, template_id)

        result.main_tf = normalized

        # Generate variables.tf
        result.variables_tf = self._generate_variables(template_id)

        # Generate outputs.tf
        result.outputs_tf = self._generate_outputs(result.services)

        # Calculate complexity
        result.complexity_score = self._calculate_complexity(
            terraform_content,
            result.services,
        )

        # Add warnings for limitations
        for service in result.unsupported_services:
            if service in KNOWN_LIMITATIONS:
                result.warnings.append(KNOWN_LIMITATIONS[service])

        logger.debug(
            "template_normalized",
            template_id=template_id,
            services=list(result.services),
            unsupported=list(result.unsupported_services),
            complexity=result.complexity_score,
        )

        return result

    def extract_metadata(
        self,
        terraform_content: str,
        original_format: str = "terraform",
    ) -> ArchitectureMetadata:
        """
        Extract metadata from a template.

        Args:
            terraform_content: Terraform HCL content
            original_format: Original template format

        Returns:
            ArchitectureMetadata
        """
        services = self._detect_services(terraform_content)
        resource_count = self._count_resources(terraform_content)
        complexity = ArchitectureMetadata.calculate_complexity(resource_count, list(services))

        return ArchitectureMetadata(
            services=list(services),
            resource_count=resource_count,
            complexity=complexity,
            original_format=original_format,
        )

    def create_architecture(
        self,
        template_id: str,
        normalized: NormalizationResult,
        source_type: ArchitectureSourceType,
        source_name: str,
        source_url: str,
        original_format: str = "terraform",
    ) -> Architecture:
        """
        Create an Architecture object from normalized result.

        Args:
            template_id: Template identifier
            normalized: Normalization result
            source_type: Source type
            source_name: Source name
            source_url: Source URL
            original_format: Original template format

        Returns:
            Architecture object
        """
        resource_count = self._count_resources(normalized.main_tf)
        complexity = ArchitectureMetadata.calculate_complexity(
            resource_count, list(normalized.services)
        )

        metadata = ArchitectureMetadata(
            services=list(normalized.services),
            resource_count=resource_count,
            complexity=complexity,
            original_format=original_format,
        )

        return Architecture(
            id=template_id,
            source_type=source_type,
            source_name=source_name,
            source_url=source_url,
            main_tf=normalized.main_tf,
            variables_tf=normalized.variables_tf,
            outputs_tf=normalized.outputs_tf,
            metadata=metadata,
        )

    def _detect_services(self, content: str) -> set[str]:
        """
        Detect AWS services used in the template.

        Args:
            content: Terraform content

        Returns:
            Set of service names
        """
        services = set()

        # Pattern to match AWS resource types
        # e.g., aws_lambda_function, aws_s3_bucket
        pattern = r'resource\s+"aws_([a-z0-9_]+)"'

        for match in re.finditer(pattern, content, re.IGNORECASE):
            resource_type = match.group(1)

            # Map resource type to service
            service = self._resource_to_service(resource_type)
            if service:
                services.add(service)

        return services

    def _check_unsupported(self, services: set[str]) -> set[str]:
        """
        Check for unsupported services.

        Args:
            services: Set of service names

        Returns:
            Set of unsupported service names
        """
        unsupported = set()

        for service in services:
            if service not in LOCALSTACK_SUPPORTED_SERVICES:
                unsupported.add(service)

        return unsupported

    def _ensure_localstack_provider(self, content: str) -> str:
        """
        Ensure LocalStack provider configuration is present.

        Args:
            content: Terraform content

        Returns:
            Content with LocalStack provider
        """
        # Check if provider block exists
        if 'provider "aws"' in content:
            # Replace existing provider with LocalStack config
            # This is simplified - a real implementation would parse HCL
            pattern = r'provider\s+"aws"\s*\{[^}]*\}'
            replacement = self._localstack_provider()
            return re.sub(pattern, replacement, content, flags=re.DOTALL)
        else:
            # Add provider at the beginning
            return f"{self._localstack_provider()}\n\n{content}"

    def _normalize_region(self, content: str) -> str:
        """
        Replace hardcoded regions with variable.

        Args:
            content: Terraform content

        Returns:
            Content with region variable
        """
        # Replace common region patterns
        regions = [
            "us-east-1", "us-east-2", "us-west-1", "us-west-2",
            "eu-west-1", "eu-west-2", "eu-central-1",
            "ap-northeast-1", "ap-southeast-1", "ap-southeast-2",
        ]

        for region in regions:
            content = content.replace(f'"{region}"', 'var.aws_region')

        return content

    def _normalize_account_id(self, content: str) -> str:
        """
        Replace hardcoded account IDs.

        Args:
            content: Terraform content

        Returns:
            Content with account ID variable
        """
        # Match 12-digit account IDs
        pattern = r'"(\d{12})"'
        return re.sub(pattern, 'data.aws_caller_identity.current.account_id', content)

    def _parameterize_names(self, content: str, template_id: str) -> str:
        """
        Parameterize resource names to avoid conflicts.

        Args:
            content: Terraform content
            template_id: Template identifier

        Returns:
            Content with parameterized names
        """
        # Add prefix variable to bucket names, function names, etc.
        # This is a simplified implementation
        prefix = template_id.replace("-", "_")

        # Replace common naming patterns
        content = re.sub(
            r'(name\s*=\s*)"([^"]+)"',
            f'\\1"${{var.name_prefix}}-\\2"',
            content,
        )

        return content

    def _generate_variables(self, template_id: str) -> str:
        """
        Generate variables.tf content.

        Args:
            template_id: Template identifier

        Returns:
            Variables file content
        """
        return f'''variable "aws_region" {{
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}}

variable "name_prefix" {{
  description = "Prefix for resource names"
  type        = string
  default     = "{template_id}"
}}

variable "environment" {{
  description = "Environment name"
  type        = string
  default     = "test"
}}

data "aws_caller_identity" "current" {{}}
'''

    def _generate_outputs(self, services: set[str]) -> str:
        """
        Generate outputs.tf content.

        Args:
            services: Set of services used

        Returns:
            Outputs file content
        """
        outputs = ['# Outputs for testing and validation\n']

        if "lambda" in services:
            outputs.append('''output "lambda_functions" {
  description = "Lambda function ARNs"
  value       = { for k, v in aws_lambda_function : k => v.arn }
}
''')

        if "s3" in services:
            outputs.append('''output "s3_buckets" {
  description = "S3 bucket names"
  value       = { for k, v in aws_s3_bucket : k => v.id }
}
''')

        if "dynamodb" in services:
            outputs.append('''output "dynamodb_tables" {
  description = "DynamoDB table names"
  value       = { for k, v in aws_dynamodb_table : k => v.name }
}
''')

        if "sqs" in services:
            outputs.append('''output "sqs_queues" {
  description = "SQS queue URLs"
  value       = { for k, v in aws_sqs_queue : k => v.url }
}
''')

        return "\n".join(outputs)

    def _count_resources(self, content: str) -> int:
        """
        Count the number of resources in the template.

        Args:
            content: Terraform content

        Returns:
            Resource count
        """
        pattern = r'resource\s+"[^"]+"\s+"[^"]+"'
        return len(re.findall(pattern, content))

    def _calculate_complexity(
        self,
        content: str,
        services: set[str],
    ) -> int:
        """
        Calculate complexity score for the template.

        Scoring:
        - Base: 10 points per resource
        - Services: 5 points per unique service
        - Lines: 1 point per 50 lines

        Args:
            content: Terraform content
            services: Set of services

        Returns:
            Complexity score
        """
        resource_count = self._count_resources(content)
        line_count = len(content.splitlines())

        score = (
            resource_count * 10
            + len(services) * 5
            + line_count // 50
        )

        return score

    @staticmethod
    def _resource_to_service(resource_type: str) -> Optional[str]:
        """
        Map Terraform resource type to AWS service name.

        Args:
            resource_type: Terraform resource type (without aws_ prefix)

        Returns:
            Service name or None
        """
        # Common mappings
        mappings = {
            "lambda": "lambda",
            "s3_bucket": "s3",
            "dynamodb_table": "dynamodb",
            "sqs_queue": "sqs",
            "sns_topic": "sns",
            "api_gateway": "apigateway",
            "apigatewayv2": "apigatewayv2",
            "iam": "iam",
            "ec2": "ec2",
            "ecs": "ecs",
            "ecr": "ecr",
            "eks": "eks",
            "rds": "rds",
            "elasticache": "elasticache",
            "cloudwatch": "cloudwatch",
            "secretsmanager": "secretsmanager",
            "ssm": "ssm",
            "kms": "kms",
            "kinesis": "kinesis",
            "stepfunctions": "stepfunctions",
            "eventbridge": "eventbridge",
            "cognito": "cognito",
            "ses": "ses",
            "route53": "route53",
            "cloudfront": "cloudfront",
            "vpc": "vpc",
            "elb": "elb",
            "lb": "elbv2",
            "acm": "acm",
            "athena": "athena",
            "glue": "glue",
            "appsync": "appsync",
        }

        # Check direct matches
        for prefix, service in mappings.items():
            if resource_type.startswith(prefix):
                return service

        # Default: use first part as service name
        parts = resource_type.split("_")
        if parts:
            return parts[0]

        return None

    @staticmethod
    def _localstack_provider() -> str:
        """Generate LocalStack provider configuration."""
        return '''provider "aws" {
  # LocalStack configuration
  endpoints {
    apigateway      = "http://localhost:4566"
    apigatewayv2    = "http://localhost:4566"
    cloudwatch      = "http://localhost:4566"
    dynamodb        = "http://localhost:4566"
    ec2             = "http://localhost:4566"
    ecs             = "http://localhost:4566"
    ecr             = "http://localhost:4566"
    elasticache     = "http://localhost:4566"
    eventbridge     = "http://localhost:4566"
    iam             = "http://localhost:4566"
    kinesis         = "http://localhost:4566"
    kms             = "http://localhost:4566"
    lambda          = "http://localhost:4566"
    rds             = "http://localhost:4566"
    route53         = "http://localhost:4566"
    s3              = "http://localhost:4566"
    secretsmanager  = "http://localhost:4566"
    ses             = "http://localhost:4566"
    sns             = "http://localhost:4566"
    sqs             = "http://localhost:4566"
    ssm             = "http://localhost:4566"
    stepfunctions   = "http://localhost:4566"
  }

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  access_key = "test"
  secret_key = "test"
  region     = var.aws_region
}'''
