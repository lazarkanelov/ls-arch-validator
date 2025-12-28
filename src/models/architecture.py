"""Data models for template sources and architectures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SourceType(Enum):
    """Type of template source."""

    GITHUB_REPO = "github_repo"
    TERRAFORM_REGISTRY = "terraform_registry"
    DIAGRAM = "diagram"


@dataclass
class TemplateSource:
    """
    Represents a repository or registry from which infrastructure templates are mined.

    Attributes:
        id: Unique identifier (e.g., "aws-quickstart", "terraform-registry")
        name: Human-readable name
        source_type: Type of source (github, registry, diagram)
        url: Base URL or repo URL
        last_mined_at: Timestamp of last mining operation
        last_commit_sha: Git commit SHA for GitHub sources
        enabled: Whether this source is enabled for mining
    """

    id: str
    name: str
    source_type: SourceType
    url: str
    last_mined_at: Optional[datetime] = None
    last_commit_sha: Optional[str] = None
    enabled: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type.value,
            "url": self.url,
            "last_mined_at": self.last_mined_at.isoformat() if self.last_mined_at else None,
            "last_commit_sha": self.last_commit_sha,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateSource":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            source_type=SourceType(data["source_type"]),
            url=data["url"],
            last_mined_at=(
                datetime.fromisoformat(data["last_mined_at"])
                if data.get("last_mined_at")
                else None
            ),
            last_commit_sha=data.get("last_commit_sha"),
            enabled=data.get("enabled", True),
        )


class ArchitectureStatus(Enum):
    """Status of an architecture in the processing pipeline."""

    PENDING = "pending"  # Discovered, not yet processed
    NORMALIZED = "normalized"  # Successfully converted to Terraform
    CONVERSION_FAILED = "conversion_failed"  # CloudFormation conversion failed
    GENERATION_FAILED = "generation_failed"  # Sample app generation failed
    READY = "ready"  # Has generated sample app, ready for validation


class ArchitectureSourceType(Enum):
    """Origin type of an architecture."""

    TEMPLATE = "template"  # From code template
    DIAGRAM = "diagram"  # From architecture diagram


@dataclass
class ArchitectureMetadata:
    """
    Metadata extracted from an architecture.

    Attributes:
        services: AWS services used (e.g., ["lambda", "s3", "dynamodb"])
        resource_count: Number of Terraform resources
        complexity: Complexity level ("low", "medium", "high")
        original_format: Original template format before conversion
        diagram_confidence: Confidence score for diagram-sourced architectures (0.0-1.0)
    """

    services: list[str]
    resource_count: int
    complexity: str  # "low", "medium", "high"
    original_format: str  # "cloudformation", "terraform", "sam", "serverless", "diagram"
    diagram_confidence: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "services": self.services,
            "resource_count": self.resource_count,
            "complexity": self.complexity,
            "original_format": self.original_format,
            "diagram_confidence": self.diagram_confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchitectureMetadata":
        """Create from dictionary."""
        return cls(
            services=data.get("services", []),
            resource_count=data.get("resource_count", 0),
            complexity=data.get("complexity", "medium"),
            original_format=data.get("original_format", "unknown"),
            diagram_confidence=data.get("diagram_confidence"),
        )

    @classmethod
    def calculate_complexity(cls, resource_count: int, services: list[str]) -> str:
        """
        Calculate complexity score based on resources and services.

        Complexity rules from spec.md:
        - Low: 1-5 resources
        - Medium: 6-15 resources OR 3+ services
        - High: 16+ resources OR 5+ services OR nested modules
        """
        service_count = len(services)

        if resource_count >= 16 or service_count >= 5:
            return "high"
        elif resource_count >= 6 or service_count >= 3:
            return "medium"
        else:
            return "low"


@dataclass
class Architecture:
    """
    A normalized infrastructure template ready for validation.

    Unique by source_id + template_path.

    Attributes:
        id: Unique identifier derived from source_id/template_path_slug
        source_id: Reference to TemplateSource.id
        template_path: Path within source (or diagram URL for diagrams)
        source_type: Whether from template or diagram
        status: Current processing status
        terraform_content: Normalized main.tf content
        variables_content: Optional variables.tf content
        outputs_content: Optional outputs.tf content
        metadata: Extracted metadata (services, complexity, etc.)
        created_at: When this architecture was first discovered
        updated_at: When this architecture was last modified
        content_hash: SHA256 of terraform_content for cache invalidation
        synthesis_notes: For diagram-sourced: assumptions made during synthesis
    """

    id: str
    source_id: str
    template_path: str
    source_type: ArchitectureSourceType
    status: ArchitectureStatus
    terraform_content: str
    variables_content: Optional[str] = None
    outputs_content: Optional[str] = None
    metadata: Optional[ArchitectureMetadata] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""
    synthesis_notes: Optional[str] = None

    @property
    def is_diagram_sourced(self) -> bool:
        """Check if this architecture was derived from a diagram."""
        return self.source_type == ArchitectureSourceType.DIAGRAM

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "template_path": self.template_path,
            "source_type": self.source_type.value,
            "status": self.status.value,
            "terraform_content": self.terraform_content,
            "variables_content": self.variables_content,
            "outputs_content": self.outputs_content,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "content_hash": self.content_hash,
            "synthesis_notes": self.synthesis_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Architecture":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            source_id=data["source_id"],
            template_path=data["template_path"],
            source_type=ArchitectureSourceType(data["source_type"]),
            status=ArchitectureStatus(data["status"]),
            terraform_content=data["terraform_content"],
            variables_content=data.get("variables_content"),
            outputs_content=data.get("outputs_content"),
            metadata=(
                ArchitectureMetadata.from_dict(data["metadata"])
                if data.get("metadata")
                else None
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            content_hash=data.get("content_hash", ""),
            synthesis_notes=data.get("synthesis_notes"),
        )


@dataclass
class SampleApp:
    """
    A generated application that exercises an architecture.

    Attributes:
        architecture_id: Reference to Architecture.id
        source_code: Filename to content mapping for application source
        test_code: Filename to content mapping for test files
        requirements: Python package requirements
        compile_status: Compilation status ("success", "failed", "pending")
        compile_errors: Compilation error messages if failed
        generated_at: When this app was generated
        prompt_version: Version of generation prompt used
        token_usage: Claude API tokens used for generation
    """

    architecture_id: str
    source_code: dict[str, str]  # filename -> content
    test_code: dict[str, str]  # test filename -> content
    requirements: list[str]
    compile_status: str = "pending"  # "success", "failed", "pending"
    compile_errors: Optional[str] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    prompt_version: str = "1.0"
    token_usage: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "architecture_id": self.architecture_id,
            "source_code": self.source_code,
            "test_code": self.test_code,
            "requirements": self.requirements,
            "compile_status": self.compile_status,
            "compile_errors": self.compile_errors,
            "generated_at": self.generated_at.isoformat(),
            "prompt_version": self.prompt_version,
            "token_usage": self.token_usage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SampleApp":
        """Create from dictionary."""
        return cls(
            architecture_id=data["architecture_id"],
            source_code=data.get("source_code", {}),
            test_code=data.get("test_code", {}),
            requirements=data.get("requirements", []),
            compile_status=data.get("compile_status", "pending"),
            compile_errors=data.get("compile_errors"),
            generated_at=(
                datetime.fromisoformat(data["generated_at"])
                if data.get("generated_at")
                else datetime.now(timezone.utc)
            ),
            prompt_version=data.get("prompt_version", "1.0"),
            token_usage=data.get("token_usage", 0),
        )
