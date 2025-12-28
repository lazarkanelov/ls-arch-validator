"""Claude Vision-based architecture diagram parser."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.utils.logging import get_logger
from src.utils.tokens import TokenTracker

logger = get_logger("miner.diagram_parser")

# Azure to AWS service mapping
AZURE_TO_AWS: dict[str, str] = {
    # Compute
    "azure-functions": "lambda",
    "virtual-machines": "ec2",
    "app-service": "elasticbeanstalk",
    "aks": "eks",
    "container-instances": "ecs",
    # Storage
    "blob-storage": "s3",
    "azure-files": "efs",
    "queue-storage": "sqs",
    "table-storage": "dynamodb",
    # Database
    "cosmos-db": "dynamodb",
    "azure-sql": "rds",
    "azure-cache": "elasticache",
    "azure-synapse": "redshift",
    # Messaging
    "service-bus": "sqs",
    "event-hubs": "kinesis",
    "event-grid": "eventbridge",
    # API & Integration
    "api-management": "apigateway",
    "logic-apps": "stepfunctions",
    # Identity
    "azure-ad": "cognito",
    # CDN & Networking
    "cdn": "cloudfront",
    "front-door": "cloudfront",
    "application-gateway": "elbv2",
    "load-balancer": "elb",
    # Monitoring
    "application-insights": "cloudwatch",
    "monitor": "cloudwatch",
    # Search & AI
    "cognitive-search": "opensearch",
}


@dataclass
class DiagramComponent:
    """Represents a component identified in an architecture diagram."""

    service: str
    confidence: float
    position: Optional[tuple[float, float]] = None
    connections: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagramAnalysis:
    """Result of analyzing an architecture diagram."""

    components: list[DiagramComponent]
    connections: list[tuple[str, str]]
    description: str
    confidence_score: float
    is_azure: bool = False
    mapped_services: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class DiagramParser:
    """
    Parses architecture diagrams using Claude Vision API.

    Extracts services and connections from PNG/JPG diagrams
    and synthesizes Terraform configurations.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        """
        Initialize the diagram parser.

        Args:
            api_key: Anthropic API key (uses ANTHROPIC_API_KEY env var if not provided)
            model: Claude model to use (must support vision)
        """
        self.api_key = api_key
        self.model = model
        self._client = None

    async def _get_client(self):
        """Get or create the Anthropic client."""
        if self._client is None:
            import anthropic
            import os

            api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")

            self._client = anthropic.AsyncAnthropic(api_key=api_key)

        return self._client

    async def parse_diagram(
        self,
        image_path: Optional[Path] = None,
        image_url: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
    ) -> DiagramAnalysis:
        """
        Parse an architecture diagram to extract services and connections.

        Args:
            image_path: Path to local image file
            image_url: URL to image
            image_bytes: Raw image bytes

        Returns:
            DiagramAnalysis with extracted components

        Raises:
            ValueError: If no image source provided
        """
        if not any([image_path, image_url, image_bytes]):
            raise ValueError("Must provide image_path, image_url, or image_bytes")

        # Get image data
        if image_path:
            image_bytes = Path(image_path).read_bytes()
            media_type = self._get_media_type(image_path)
        elif image_url:
            image_bytes, media_type = await self._download_image(image_url)
        else:
            media_type = "image/png"  # Default assumption

        # Encode image
        image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

        # Create prompt for Claude Vision
        prompt = self._create_analysis_prompt()

        try:
            client = await self._get_client()

            response = await client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            # Track token usage
            tracker = TokenTracker.get_instance()
            tracker.record_from_response(response.usage)

            # Parse response
            analysis = self._parse_response(response.content[0].text)

            logger.info(
                "diagram_parsed",
                components=len(analysis.components),
                connections=len(analysis.connections),
                confidence=analysis.confidence_score,
            )

            return analysis

        except Exception as e:
            logger.error("diagram_parse_error", error=str(e))
            raise

    def map_azure_to_aws(self, analysis: DiagramAnalysis) -> DiagramAnalysis:
        """
        Map Azure services to AWS equivalents.

        Args:
            analysis: Original diagram analysis

        Returns:
            Analysis with mapped services
        """
        if not analysis.is_azure:
            return analysis

        mapped = {}
        warnings = list(analysis.warnings)

        for component in analysis.components:
            azure_service = component.service.lower()

            if azure_service in AZURE_TO_AWS:
                aws_service = AZURE_TO_AWS[azure_service]
                mapped[component.service] = aws_service
                component.service = aws_service
            else:
                warnings.append(
                    f"No AWS mapping for Azure service: {component.service}"
                )

        analysis.mapped_services = mapped
        analysis.warnings = warnings

        logger.debug(
            "azure_services_mapped",
            mappings=mapped,
            warnings=len(warnings),
        )

        return analysis

    async def synthesize_terraform(
        self,
        analysis: DiagramAnalysis,
        template_id: str,
    ) -> str:
        """
        Synthesize Terraform configuration from diagram analysis.

        Args:
            analysis: Diagram analysis result
            template_id: Template identifier

        Returns:
            Terraform HCL content
        """
        # Build Terraform from components
        terraform_parts = []

        # Provider
        terraform_parts.append(self._generate_provider())

        # Generate resources for each component
        for component in analysis.components:
            resource = self._generate_resource(component)
            if resource:
                terraform_parts.append(resource)

        # Add connection comments
        if analysis.connections:
            terraform_parts.append("\n# Connections identified in diagram:")
            for src, dst in analysis.connections:
                terraform_parts.append(f"# {src} -> {dst}")

        terraform = "\n\n".join(terraform_parts)

        logger.debug(
            "terraform_synthesized",
            template_id=template_id,
            components=len(analysis.components),
        )

        return terraform

    def calculate_confidence_score(self, analysis: DiagramAnalysis) -> float:
        """
        Calculate overall confidence score for the diagram analysis.

        Args:
            analysis: Diagram analysis

        Returns:
            Confidence score between 0 and 1
        """
        if not analysis.components:
            return 0.0

        # Average component confidence
        avg_confidence = sum(c.confidence for c in analysis.components) / len(
            analysis.components
        )

        # Penalize for warnings
        warning_penalty = min(len(analysis.warnings) * 0.05, 0.3)

        # Penalize for unmapped Azure services
        unmapped_penalty = 0
        if analysis.is_azure:
            unmapped = [
                c for c in analysis.components
                if c.service not in analysis.mapped_services.values()
            ]
            unmapped_penalty = min(len(unmapped) * 0.1, 0.3)

        final_score = max(0, avg_confidence - warning_penalty - unmapped_penalty)
        return round(final_score, 2)

    @staticmethod
    def _create_analysis_prompt() -> str:
        """Create the prompt for diagram analysis."""
        return """Analyze this architecture diagram and extract the following information:

1. **Cloud Provider**: Is this an AWS, Azure, or other cloud architecture?

2. **Components**: List all cloud services/components visible in the diagram. For each:
   - Service name (e.g., "Lambda", "S3", "DynamoDB", "Azure Functions", "Cosmos DB")
   - Confidence level (0-1) for the identification

3. **Connections**: List all connections/data flows between components.
   - Format: "Source -> Destination"

4. **Description**: Brief description of the architecture pattern (1-2 sentences).

Format your response as JSON:
```json
{
  "cloud_provider": "aws" or "azure" or "other",
  "components": [
    {"service": "ServiceName", "confidence": 0.95}
  ],
  "connections": [
    ["Source", "Destination"]
  ],
  "description": "Brief architecture description"
}
```

Focus on identifying the main services and their relationships.
If a component is unclear, still include it with lower confidence."""

    def _parse_response(self, response_text: str) -> DiagramAnalysis:
        """
        Parse Claude's response into DiagramAnalysis.

        Args:
            response_text: Claude's response text

        Returns:
            DiagramAnalysis object
        """
        import json
        import re

        # Extract JSON from response
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find JSON without code block
            json_str = response_text

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("json_parse_failed", response=response_text[:200])
            return DiagramAnalysis(
                components=[],
                connections=[],
                description="Failed to parse diagram",
                confidence_score=0.0,
            )

        # Build components
        components = []
        for comp in data.get("components", []):
            components.append(
                DiagramComponent(
                    service=comp.get("service", "unknown"),
                    confidence=comp.get("confidence", 0.5),
                )
            )

        # Build connections
        connections = []
        for conn in data.get("connections", []):
            if len(conn) >= 2:
                connections.append((conn[0], conn[1]))

        # Determine if Azure
        is_azure = data.get("cloud_provider", "").lower() == "azure"

        # Calculate confidence
        if components:
            avg_confidence = sum(c.confidence for c in components) / len(components)
        else:
            avg_confidence = 0.0

        return DiagramAnalysis(
            components=components,
            connections=connections,
            description=data.get("description", ""),
            confidence_score=avg_confidence,
            is_azure=is_azure,
        )

    async def _download_image(self, url: str) -> tuple[bytes, str]:
        """
        Download image from URL.

        Args:
            url: Image URL

        Returns:
            Tuple of (image bytes, media type)
        """
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "image/png")
            return response.content, content_type

    @staticmethod
    def _get_media_type(path: Path) -> str:
        """Get media type from file extension."""
        ext = path.suffix.lower()
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return media_types.get(ext, "image/png")

    @staticmethod
    def _generate_provider() -> str:
        """Generate AWS provider for LocalStack."""
        return '''provider "aws" {
  endpoints {
    apigateway     = "http://localhost:4566"
    dynamodb       = "http://localhost:4566"
    iam            = "http://localhost:4566"
    lambda         = "http://localhost:4566"
    s3             = "http://localhost:4566"
    sns            = "http://localhost:4566"
    sqs            = "http://localhost:4566"
    stepfunctions  = "http://localhost:4566"
  }

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  access_key = "test"
  secret_key = "test"
  region     = "us-east-1"
}'''

    def _generate_resource(self, component: DiagramComponent) -> Optional[str]:
        """
        Generate Terraform resource for a component.

        Args:
            component: Diagram component

        Returns:
            Terraform resource block or None
        """
        service = component.service.lower()
        resource_name = service.replace("-", "_").replace(" ", "_")

        # Service-specific resource generation
        generators = {
            "lambda": self._generate_lambda,
            "s3": self._generate_s3,
            "dynamodb": self._generate_dynamodb,
            "sqs": self._generate_sqs,
            "sns": self._generate_sns,
            "apigateway": self._generate_apigateway,
            "stepfunctions": self._generate_stepfunctions,
        }

        generator = generators.get(service)
        if generator:
            return generator(resource_name)

        # Generic placeholder
        return f"""# Placeholder for {component.service}
# Confidence: {component.confidence}
# TODO: Implement resource for {component.service}"""

    @staticmethod
    def _generate_lambda(name: str) -> str:
        """Generate Lambda function resource."""
        return f'''resource "aws_lambda_function" "{name}" {{
  function_name = "{name}"
  handler       = "handler.handler"
  runtime       = "python3.9"
  role          = aws_iam_role.lambda_exec.arn
  filename      = "lambda.zip"
}}

resource "aws_iam_role" "lambda_exec" {{
  name = "{name}-role"

  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {{
        Service = "lambda.amazonaws.com"
      }}
    }}]
  }})
}}'''

    @staticmethod
    def _generate_s3(name: str) -> str:
        """Generate S3 bucket resource."""
        return f'''resource "aws_s3_bucket" "{name}" {{
  bucket = "{name}-bucket"
}}'''

    @staticmethod
    def _generate_dynamodb(name: str) -> str:
        """Generate DynamoDB table resource."""
        return f'''resource "aws_dynamodb_table" "{name}" {{
  name         = "{name}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {{
    name = "id"
    type = "S"
  }}
}}'''

    @staticmethod
    def _generate_sqs(name: str) -> str:
        """Generate SQS queue resource."""
        return f'''resource "aws_sqs_queue" "{name}" {{
  name = "{name}"
}}'''

    @staticmethod
    def _generate_sns(name: str) -> str:
        """Generate SNS topic resource."""
        return f'''resource "aws_sns_topic" "{name}" {{
  name = "{name}"
}}'''

    @staticmethod
    def _generate_apigateway(name: str) -> str:
        """Generate API Gateway resource."""
        return f'''resource "aws_apigatewayv2_api" "{name}" {{
  name          = "{name}"
  protocol_type = "HTTP"
}}'''

    @staticmethod
    def _generate_stepfunctions(name: str) -> str:
        """Generate Step Functions state machine."""
        return f'''resource "aws_sfn_state_machine" "{name}" {{
  name     = "{name}"
  role_arn = aws_iam_role.stepfunctions_exec.arn

  definition = jsonencode({{
    StartAt = "Start"
    States = {{
      Start = {{
        Type = "Pass"
        End  = true
      }}
    }}
  }})
}}

resource "aws_iam_role" "stepfunctions_exec" {{
  name = "{name}-role"

  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {{
        Service = "states.amazonaws.com"
      }}
    }}]
  }})
}}'''
