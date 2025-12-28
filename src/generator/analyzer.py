"""Terraform analyzer for extracting infrastructure details."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger("generator.analyzer")


@dataclass
class ResourceInfo:
    """Information about a Terraform resource."""

    resource_type: str
    resource_name: str
    service: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class InfrastructureAnalysis:
    """Result of analyzing Terraform infrastructure."""

    resources: list[ResourceInfo]
    services: set[str]
    integration_points: list[tuple[str, str]]
    lambda_functions: list[str]
    api_endpoints: list[str]
    storage_resources: list[str]
    database_tables: list[str]
    queue_resources: list[str]
    event_sources: list[str]

    @property
    def resource_count(self) -> int:
        """Total number of resources."""
        return len(self.resources)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "resource_count": self.resource_count,
            "services": list(self.services),
            "lambda_functions": self.lambda_functions,
            "api_endpoints": self.api_endpoints,
            "storage_resources": self.storage_resources,
            "database_tables": self.database_tables,
            "queue_resources": self.queue_resources,
            "event_sources": self.event_sources,
        }


class TerraformAnalyzer:
    """
    Analyzes Terraform configurations to extract infrastructure details.

    This information is used to generate appropriate sample applications
    that exercise the infrastructure.
    """

    def __init__(self) -> None:
        """Initialize the analyzer."""
        pass

    def analyze(self, terraform_content: str) -> InfrastructureAnalysis:
        """
        Analyze Terraform content to extract infrastructure details.

        Args:
            terraform_content: Terraform HCL content

        Returns:
            InfrastructureAnalysis with extracted details
        """
        resources = self._extract_resources(terraform_content)
        services = self._extract_services(resources)

        analysis = InfrastructureAnalysis(
            resources=resources,
            services=services,
            integration_points=self._find_integration_points(resources),
            lambda_functions=self._find_lambda_functions(resources),
            api_endpoints=self._find_api_endpoints(resources),
            storage_resources=self._find_storage_resources(resources),
            database_tables=self._find_database_tables(resources),
            queue_resources=self._find_queue_resources(resources),
            event_sources=self._find_event_sources(resources),
        )

        logger.debug(
            "terraform_analyzed",
            resources=len(resources),
            services=list(services),
        )

        return analysis

    def _extract_resources(self, content: str) -> list[ResourceInfo]:
        """
        Extract all resources from Terraform content.

        Args:
            content: Terraform HCL content

        Returns:
            List of ResourceInfo objects
        """
        resources = []

        # Pattern to match resource blocks
        # resource "aws_lambda_function" "my_function" { ... }
        pattern = r'resource\s+"(aws_[a-z0-9_]+)"\s+"([a-z0-9_]+)"\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}'

        for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
            resource_type = match.group(1)
            resource_name = match.group(2)
            block_content = match.group(3)

            # Extract key attributes
            attributes = self._parse_attributes(block_content)

            # Determine service
            service = self._resource_type_to_service(resource_type)

            resources.append(
                ResourceInfo(
                    resource_type=resource_type,
                    resource_name=resource_name,
                    service=service,
                    attributes=attributes,
                )
            )

        return resources

    def _parse_attributes(self, block_content: str) -> dict[str, Any]:
        """
        Parse key attributes from a resource block.

        Args:
            block_content: Content inside resource braces

        Returns:
            Dictionary of attributes
        """
        attributes = {}

        # Extract common attributes
        patterns = {
            "name": r'(?:function_name|name|bucket|table_name)\s*=\s*"([^"]+)"',
            "handler": r'handler\s*=\s*"([^"]+)"',
            "runtime": r'runtime\s*=\s*"([^"]+)"',
            "memory_size": r'memory_size\s*=\s*(\d+)',
            "timeout": r'timeout\s*=\s*(\d+)',
            "hash_key": r'hash_key\s*=\s*"([^"]+)"',
            "billing_mode": r'billing_mode\s*=\s*"([^"]+)"',
        }

        for attr_name, pattern in patterns.items():
            match = re.search(pattern, block_content)
            if match:
                attributes[attr_name] = match.group(1)

        return attributes

    def _extract_services(self, resources: list[ResourceInfo]) -> set[str]:
        """Extract unique services from resources."""
        return {r.service for r in resources if r.service}

    def _resource_type_to_service(self, resource_type: str) -> str:
        """Map Terraform resource type to AWS service name."""
        # Remove aws_ prefix
        type_without_prefix = resource_type.replace("aws_", "")

        # Common mappings
        service_map = {
            "lambda_function": "lambda",
            "lambda_permission": "lambda",
            "lambda_event_source_mapping": "lambda",
            "s3_bucket": "s3",
            "s3_bucket_object": "s3",
            "s3_bucket_notification": "s3",
            "dynamodb_table": "dynamodb",
            "dynamodb_table_item": "dynamodb",
            "sqs_queue": "sqs",
            "sqs_queue_policy": "sqs",
            "sns_topic": "sns",
            "sns_topic_subscription": "sns",
            "api_gateway_rest_api": "apigateway",
            "api_gateway_resource": "apigateway",
            "api_gateway_method": "apigateway",
            "apigatewayv2_api": "apigatewayv2",
            "apigatewayv2_route": "apigatewayv2",
            "apigatewayv2_integration": "apigatewayv2",
            "iam_role": "iam",
            "iam_policy": "iam",
            "cloudwatch_log_group": "cloudwatch",
            "cloudwatch_metric_alarm": "cloudwatch",
            "sfn_state_machine": "stepfunctions",
            "kinesis_stream": "kinesis",
            "eventbridge_rule": "eventbridge",
            "cloudwatch_event_rule": "eventbridge",
        }

        # Check direct mapping
        if type_without_prefix in service_map:
            return service_map[type_without_prefix]

        # Fall back to first part
        parts = type_without_prefix.split("_")
        return parts[0] if parts else "unknown"

    def _find_integration_points(
        self,
        resources: list[ResourceInfo],
    ) -> list[tuple[str, str]]:
        """
        Find integration points between services.

        Args:
            resources: List of resources

        Returns:
            List of (source, target) tuples
        """
        integrations = []

        # Common integration patterns
        lambda_resources = [r for r in resources if r.service == "lambda"]
        api_resources = [r for r in resources if r.service in ("apigateway", "apigatewayv2")]
        sqs_resources = [r for r in resources if r.service == "sqs"]
        sns_resources = [r for r in resources if r.service == "sns"]
        dynamodb_resources = [r for r in resources if r.service == "dynamodb"]

        # API Gateway -> Lambda
        if api_resources and lambda_resources:
            integrations.append(("apigateway", "lambda"))

        # SQS -> Lambda (event source mapping)
        if sqs_resources and lambda_resources:
            integrations.append(("sqs", "lambda"))

        # SNS -> Lambda
        if sns_resources and lambda_resources:
            integrations.append(("sns", "lambda"))

        # Lambda -> DynamoDB
        if lambda_resources and dynamodb_resources:
            integrations.append(("lambda", "dynamodb"))

        # Lambda -> S3
        s3_resources = [r for r in resources if r.service == "s3"]
        if lambda_resources and s3_resources:
            integrations.append(("lambda", "s3"))

        return integrations

    def _find_lambda_functions(self, resources: list[ResourceInfo]) -> list[str]:
        """Find Lambda function names."""
        return [
            r.attributes.get("name", r.resource_name)
            for r in resources
            if r.resource_type == "aws_lambda_function"
        ]

    def _find_api_endpoints(self, resources: list[ResourceInfo]) -> list[str]:
        """Find API Gateway endpoints."""
        endpoints = []
        for r in resources:
            if r.resource_type in ("aws_api_gateway_rest_api", "aws_apigatewayv2_api"):
                endpoints.append(r.attributes.get("name", r.resource_name))
        return endpoints

    def _find_storage_resources(self, resources: list[ResourceInfo]) -> list[str]:
        """Find S3 bucket names."""
        return [
            r.attributes.get("name", r.resource_name)
            for r in resources
            if r.resource_type == "aws_s3_bucket"
        ]

    def _find_database_tables(self, resources: list[ResourceInfo]) -> list[str]:
        """Find DynamoDB table names."""
        return [
            r.attributes.get("name", r.resource_name)
            for r in resources
            if r.resource_type == "aws_dynamodb_table"
        ]

    def _find_queue_resources(self, resources: list[ResourceInfo]) -> list[str]:
        """Find SQS queue names."""
        return [
            r.attributes.get("name", r.resource_name)
            for r in resources
            if r.resource_type == "aws_sqs_queue"
        ]

    def _find_event_sources(self, resources: list[ResourceInfo]) -> list[str]:
        """Find event source resources (SNS, EventBridge, etc.)."""
        event_types = ("aws_sns_topic", "aws_cloudwatch_event_rule", "aws_eventbridge_rule")
        return [
            r.attributes.get("name", r.resource_name)
            for r in resources
            if r.resource_type in event_types
        ]
