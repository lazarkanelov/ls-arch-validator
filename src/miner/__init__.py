"""Template mining and normalization module."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.models import Architecture, ArchitectureSourceType, TemplateSource
from src.miner.builtin import get_builtin_architectures
from src.miner.converter import CloudFormationConverter, ConversionError
from src.miner.diagram_parser import DiagramParser
from src.miner.normalizer import NormalizationResult, TemplateNormalizer
from src.miner.sources import (
    DIAGRAM_SOURCES,
    TEMPLATE_SOURCES,
    ExtractionResult,
    get_extractor,
    list_sources,
)
from src.utils.cache import ArchitectureCache
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.registry import ArchitectureRegistry

logger = get_logger("miner")


class MiningResult:
    """Result of a mining operation."""

    def __init__(self) -> None:
        self.architectures: list[Architecture] = []
        self.errors: list[str] = []
        self.sources_mined: list[str] = []
        self.templates_found: int = 0
        self.templates_normalized: int = 0
        self.diagrams_parsed: int = 0
        # Incremental mining stats
        self.new_architectures: int = 0
        self.skipped_known: int = 0

    @property
    def success(self) -> bool:
        """Check if mining was successful."""
        return len(self.architectures) > 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "architectures": len(self.architectures),
            "errors": len(self.errors),
            "sources_mined": self.sources_mined,
            "templates_found": self.templates_found,
            "templates_normalized": self.templates_normalized,
            "diagrams_parsed": self.diagrams_parsed,
            "new_architectures": self.new_architectures,
            "skipped_known": self.skipped_known,
        }


async def mine_all(
    cache_dir: Path,
    sources: Optional[list[str]] = None,
    include_diagrams: bool = True,
    max_per_source: Optional[int] = None,
    skip_cache: bool = False,
    registry: Optional["ArchitectureRegistry"] = None,
    incremental: bool = False,
) -> MiningResult:
    """
    Mine templates from all configured sources.

    Args:
        cache_dir: Directory for caching
        sources: Specific sources to mine (default: all)
        include_diagrams: Whether to include diagram sources
        max_per_source: Maximum templates per source
        skip_cache: Force re-mining even if cached
        registry: Architecture registry for incremental mining
        incremental: Only process NEW architectures (skip already-known)

    Returns:
        MiningResult with all architectures
    """
    result = MiningResult()

    # Determine which sources to mine
    if sources:
        source_list = sources
    else:
        source_list = list_sources(include_diagrams=include_diagrams)

    logger.info(
        "mining_started",
        sources=source_list,
        max_per_source=max_per_source,
        incremental=incremental,
    )

    # ALWAYS include built-in architectures first (guaranteed baseline)
    builtin_archs = get_builtin_architectures()
    for arch in builtin_archs:
        # In incremental mode, skip already-known built-ins
        if incremental and registry and registry.exists(arch.id):
            logger.debug("skipping_known_builtin", arch_id=arch.id)
            result.skipped_known += 1
            continue

        result.architectures.append(arch)
        result.new_architectures += 1

        # Register with registry
        if registry:
            services = arch.metadata.aws_services if arch.metadata else []
            registry.register(
                arch_id=arch.id,
                source_name=arch.source_name,
                source_url=arch.source_url,
                services=services,
            )

    logger.info(
        "builtin_architectures_added",
        count=len([a for a in builtin_archs if a in result.architectures]),
        skipped=result.skipped_known,
    )

    # Initialize components
    arch_cache = ArchitectureCache(cache_dir)
    converter = CloudFormationConverter(cache_dir)
    normalizer = TemplateNormalizer()
    diagram_parser = DiagramParser()

    # Process each source
    for source_name in source_list:
        try:
            logger.info("mining_source", source=source_name)

            # Get extractor
            extractor = get_extractor(
                source_name,
                cache_dir=cache_dir,
                max_templates=max_per_source,
            )

            # Extract templates
            extraction = await extractor.extract()
            result.sources_mined.append(source_name)
            result.templates_found += extraction.template_count

            # Process extracted templates
            for template in extraction.templates:
                try:
                    # Incremental mode: skip already-known architectures
                    if incremental and registry and registry.exists(template.template_id):
                        logger.debug(
                            "skipping_known_architecture",
                            template_id=template.template_id,
                        )
                        result.skipped_known += 1
                        continue

                    # Determine processing path
                    if source_name in DIAGRAM_SOURCES:
                        # Process as diagram
                        arch = await _process_diagram(
                            template,
                            diagram_parser,
                            normalizer,
                            arch_cache,
                            skip_cache,
                        )
                        if arch:
                            result.architectures.append(arch)
                            result.diagrams_parsed += 1
                            result.new_architectures += 1
                            # Register with registry
                            if registry:
                                services = _extract_services(arch.main_tf)
                                registry.register(
                                    arch_id=arch.id,
                                    source_name=arch.source_name,
                                    source_url=arch.source_url,
                                    services=services,
                                )
                    else:
                        # Process as template
                        arch = await _process_template(
                            template,
                            converter,
                            normalizer,
                            arch_cache,
                            skip_cache,
                        )
                        if arch:
                            result.architectures.append(arch)
                            result.templates_normalized += 1
                            result.new_architectures += 1
                            # Register with registry
                            if registry:
                                services = _extract_services(arch.main_tf)
                                registry.register(
                                    arch_id=arch.id,
                                    source_name=arch.source_name,
                                    source_url=arch.source_url,
                                    services=services,
                                )

                except Exception as e:
                    error_msg = f"Error processing {template.template_id}: {e}"
                    result.errors.append(error_msg)
                    logger.warning("template_processing_error", error=error_msg)

            # Add extraction errors
            result.errors.extend(extraction.errors)

        except Exception as e:
            error_msg = f"Error mining source {source_name}: {e}"
            result.errors.append(error_msg)
            logger.error("source_mining_error", error=error_msg)

    # Update source state
    _update_source_state(cache_dir, result.sources_mined)

    logger.info(
        "mining_completed",
        architectures=len(result.architectures),
        errors=len(result.errors),
    )

    return result


async def _process_template(
    template: TemplateSource,
    converter: CloudFormationConverter,
    normalizer: TemplateNormalizer,
    cache: ArchitectureCache,
    skip_cache: bool,
) -> Optional[Architecture]:
    """
    Process a code-based template.

    Args:
        template: Template source
        converter: CloudFormation converter
        normalizer: Template normalizer
        cache: Architecture cache
        skip_cache: Skip cache check

    Returns:
        Architecture or None if processing fails
    """
    # Check cache
    if not skip_cache:
        cached = cache.load_architecture(template.template_id)
        if cached:
            logger.debug("using_cached", template_id=template.template_id)
            return _architecture_from_cache(cached, template)

    content = template.raw_content

    # Convert CloudFormation/Serverless to Terraform if needed
    if _is_cloudformation(content):
        try:
            content = await converter.convert(content, template.template_id)
        except ConversionError as e:
            logger.warning(
                "conversion_failed",
                template_id=template.template_id,
                error=str(e),
            )
            return None
    elif _is_serverless(content):
        try:
            content = await converter.convert_serverless(content, template.template_id)
        except ConversionError as e:
            logger.warning(
                "serverless_conversion_failed",
                template_id=template.template_id,
                error=str(e),
            )
            return None

    # Normalize for LocalStack
    normalized = normalizer.normalize(content, template.template_id)

    # Create architecture
    arch = normalizer.create_architecture(
        template_id=template.template_id,
        normalized=normalized,
        source_type=ArchitectureSourceType.TEMPLATE,
        source_name=template.source_name,
        source_url=template.source_url,
    )

    # Save to cache with source info
    cache.save_architecture(
        arch_id=arch.id,
        main_tf=arch.main_tf,
        variables_tf=arch.variables_tf,
        outputs_tf=arch.outputs_tf,
        metadata=arch.metadata.to_dict() if arch.metadata else None,
        source_type=arch.source_type.value,
        source_name=arch.source_name,
        source_url=arch.source_url,
    )

    return arch


async def _process_diagram(
    template: TemplateSource,
    parser: DiagramParser,
    normalizer: TemplateNormalizer,
    cache: ArchitectureCache,
    skip_cache: bool,
) -> Optional[Architecture]:
    """
    Process a diagram-based template.

    Args:
        template: Template source (with diagram metadata)
        parser: Diagram parser
        normalizer: Template normalizer
        cache: Architecture cache
        skip_cache: Skip cache check

    Returns:
        Architecture or None if processing fails
    """
    # Check cache
    if not skip_cache:
        cached = cache.load_architecture(template.template_id)
        if cached:
            logger.debug("using_cached_diagram", template_id=template.template_id)
            return _architecture_from_cache(cached, template)

    # Get image URL from metadata
    metadata = template.metadata or {}
    image_url = metadata.get("image_url")

    if not image_url:
        logger.warning(
            "no_diagram_url",
            template_id=template.template_id,
        )
        return None

    try:
        # Parse diagram
        analysis = await parser.parse_diagram(image_url=image_url)

        # Map Azure services if needed
        if analysis.is_azure or metadata.get("requires_mapping"):
            analysis = parser.map_azure_to_aws(analysis)

        # Calculate confidence
        confidence = parser.calculate_confidence_score(analysis)

        # Skip low-confidence diagrams
        if confidence < 0.3:
            logger.warning(
                "low_confidence_diagram",
                template_id=template.template_id,
                confidence=confidence,
            )
            return None

        # Synthesize Terraform
        terraform = await parser.synthesize_terraform(analysis, template.template_id)

        # Normalize
        normalized = normalizer.normalize(terraform, template.template_id)

        # Create architecture
        arch = Architecture(
            id=template.template_id,
            source_type=ArchitectureSourceType.DIAGRAM,
            source_name=template.source_name,
            source_url=template.source_url,
            main_tf=normalized.main_tf,
            variables_tf=normalized.variables_tf,
            outputs_tf=normalized.outputs_tf,
            metadata=normalizer.extract_metadata(
                normalized.main_tf,
                {
                    "title": metadata.get("title", ""),
                    "description": metadata.get("description", ""),
                    "confidence": confidence,
                    "components": len(analysis.components),
                    "is_azure_mapped": analysis.is_azure,
                },
            ),
        )

        # Save to cache with source info
        cache.save_architecture(
            arch_id=arch.id,
            main_tf=arch.main_tf,
            variables_tf=arch.variables_tf,
            outputs_tf=arch.outputs_tf,
            metadata=arch.metadata.to_dict() if arch.metadata else None,
            source_type=arch.source_type.value,
            source_name=arch.source_name,
            source_url=arch.source_url,
        )

        return arch

    except Exception as e:
        logger.error(
            "diagram_processing_failed",
            template_id=template.template_id,
            error=str(e),
        )
        return None


def _is_cloudformation(content: str) -> bool:
    """Check if content is CloudFormation."""
    markers = [
        "AWSTemplateFormatVersion",
        '"Resources"',
        "Resources:",
        "Transform:",
    ]
    return any(marker in content for marker in markers)


def _is_serverless(content: str) -> bool:
    """Check if content is Serverless Framework."""
    markers = [
        "service:",
        "provider:",
        "functions:",
    ]
    return sum(1 for marker in markers if marker in content) >= 2


def _architecture_from_cache(cached: dict, template: TemplateSource) -> Architecture:
    """Create Architecture from cached data."""
    from src.models import ArchitectureMetadata

    metadata = None
    if cached.get("metadata"):
        metadata = ArchitectureMetadata.from_dict(cached["metadata"])

    return Architecture(
        id=template.template_id,
        source_type=ArchitectureSourceType.TEMPLATE,
        source_name=template.source_name,
        source_url=template.source_url,
        main_tf=cached.get("main_tf", ""),
        variables_tf=cached.get("variables_tf"),
        outputs_tf=cached.get("outputs_tf"),
        metadata=metadata,
    )


def _extract_services(terraform_code: str) -> list[str]:
    """Extract AWS service names from Terraform code."""
    import re

    # Common AWS service resource prefixes
    service_patterns = {
        "aws_lambda": "Lambda",
        "aws_dynamodb": "DynamoDB",
        "aws_s3": "S3",
        "aws_sqs": "SQS",
        "aws_sns": "SNS",
        "aws_api_gateway": "API Gateway",
        "aws_apigatewayv2": "API Gateway v2",
        "aws_ecs": "ECS",
        "aws_ecr": "ECR",
        "aws_rds": "RDS",
        "aws_ec2": "EC2",
        "aws_iam": "IAM",
        "aws_cloudwatch": "CloudWatch",
        "aws_kinesis": "Kinesis",
        "aws_step_functions": "Step Functions",
        "aws_sfn": "Step Functions",
        "aws_cognito": "Cognito",
        "aws_secretsmanager": "Secrets Manager",
        "aws_ssm": "SSM",
        "aws_kms": "KMS",
        "aws_elasticsearch": "Elasticsearch",
        "aws_opensearch": "OpenSearch",
        "aws_elasticache": "ElastiCache",
        "aws_rekognition": "Rekognition",
        "aws_textract": "Textract",
        "aws_comprehend": "Comprehend",
        "aws_sagemaker": "SageMaker",
        "aws_lex": "Lex",
        "aws_polly": "Polly",
        "aws_transcribe": "Transcribe",
        "aws_translate": "Translate",
    }

    services = set()
    for pattern, service_name in service_patterns.items():
        if re.search(rf'resource\s+"{pattern}', terraform_code):
            services.add(service_name)

    return sorted(list(services))


def _update_source_state(cache_dir: Path, sources: list[str]) -> None:
    """Update source state tracking file."""
    state_file = cache_dir / "sources_state.json"

    # Load existing state
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except json.JSONDecodeError:
            state = {}
    else:
        state = {}

    # Update timestamps
    now = datetime.utcnow().isoformat()
    for source in sources:
        if source not in state:
            state[source] = {}
        state[source]["last_mined_at"] = now

    # Write state
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


__all__ = [
    # Main function
    "mine_all",
    "MiningResult",
    # Components
    "CloudFormationConverter",
    "ConversionError",
    "DiagramParser",
    "TemplateNormalizer",
    "NormalizationResult",
    # Sources
    "ExtractionResult",
    "get_extractor",
    "list_sources",
    "TEMPLATE_SOURCES",
    "DIAGRAM_SOURCES",
]
