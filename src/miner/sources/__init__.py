"""Source extractors for mining templates from various sources."""

from pathlib import Path
from typing import Optional

from src.miner.sources.base import (
    ExtractionResult,
    GitHubSourceExtractor,
    RegistrySourceExtractor,
    SourceExtractor,
)
from src.miner.sources.diagrams import (
    AWSArchitectureCenterScraper,
    AzureArchitectureCenterScraper,
    DiagramInfo,
)
from src.miner.sources.quickstart import QuickStartExtractor
from src.miner.sources.serverless import ServerlessExtractor
from src.miner.sources.solutions import AWSSolutionsExtractor
from src.miner.sources.terraform import TerraformRegistryExtractor

# Source registry mapping source names to extractor classes
SOURCE_REGISTRY: dict[str, type[SourceExtractor]] = {
    "aws-quickstarts": QuickStartExtractor,
    "terraform-registry": TerraformRegistryExtractor,
    "aws-solutions": AWSSolutionsExtractor,
    "serverless-examples": ServerlessExtractor,
    "aws-architecture-center": AWSArchitectureCenterScraper,
    "azure-architecture-center": AzureArchitectureCenterScraper,
}

# Template sources (code-based)
TEMPLATE_SOURCES = [
    "aws-quickstarts",
    "terraform-registry",
    "aws-solutions",
    "serverless-examples",
]

# Diagram sources (image-based)
DIAGRAM_SOURCES = [
    "aws-architecture-center",
    "azure-architecture-center",
]


def get_extractor(
    source_name: str,
    cache_dir: Optional[Path] = None,
    max_templates: Optional[int] = None,
) -> SourceExtractor:
    """
    Factory function to get an extractor by source name.

    Args:
        source_name: Name of the source
        cache_dir: Directory for caching
        max_templates: Maximum templates to extract

    Returns:
        Configured SourceExtractor instance

    Raises:
        ValueError: If source_name is not registered
    """
    if source_name not in SOURCE_REGISTRY:
        available = ", ".join(SOURCE_REGISTRY.keys())
        raise ValueError(
            f"Unknown source: {source_name}. Available: {available}"
        )

    extractor_class = SOURCE_REGISTRY[source_name]
    return extractor_class(cache_dir=cache_dir, max_templates=max_templates)


def list_sources(include_diagrams: bool = True) -> list[str]:
    """
    List available source names.

    Args:
        include_diagrams: Whether to include diagram sources

    Returns:
        List of source names
    """
    sources = list(TEMPLATE_SOURCES)
    if include_diagrams:
        sources.extend(DIAGRAM_SOURCES)
    return sources


__all__ = [
    # Base classes
    "ExtractionResult",
    "SourceExtractor",
    "GitHubSourceExtractor",
    "RegistrySourceExtractor",
    # Extractors
    "QuickStartExtractor",
    "TerraformRegistryExtractor",
    "AWSSolutionsExtractor",
    "ServerlessExtractor",
    "AWSArchitectureCenterScraper",
    "AzureArchitectureCenterScraper",
    "DiagramInfo",
    # Registry functions
    "SOURCE_REGISTRY",
    "TEMPLATE_SOURCES",
    "DIAGRAM_SOURCES",
    "get_extractor",
    "list_sources",
]
