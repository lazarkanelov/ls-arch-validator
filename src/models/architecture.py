"""Data models for template sources and architectures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SourceType(Enum):
    """Type of template source."""

    GITHUB_REPO = "github_repo"
    GITHUB = "github_repo"  # Alias for backwards compatibility
    TERRAFORM_REGISTRY = "terraform_registry"
    REGISTRY = "terraform_registry"  # Alias for backwards compatibility
    DIAGRAM = "diagram"


@dataclass
class TemplateSource:
    """
    Represents an extracted infrastructure template with its source information.

    Attributes:
        source_type: Type of source (github, registry, diagram)
        source_name: Name of the source (e.g., "aws-quickstarts", "terraform-registry")
        source_url: URL to the original source
        template_path: Path to the template file within the source
        template_id: Unique identifier for this template
        raw_content: Raw template content (YAML, JSON, HCL, etc.)
        version: Version of the template (for registry sources)
        commit_sha: Git commit SHA (for GitHub sources)
        metadata: Additional metadata about the template
    """

    source_type: SourceType
    source_name: str
    source_url: str
    template_path: str
    template_id: str
    raw_content: str
    version: Optional[str] = None
    commit_sha: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "source_type": self.source_type.value,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "template_path": self.template_path,
            "template_id": self.template_id,
            "raw_content": self.raw_content,
            "version": self.version,
            "commit_sha": self.commit_sha,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TemplateSource":
        """Create from dictionary."""
        return cls(
            source_type=SourceType(data["source_type"]),
            source_name=data["source_name"],
            source_url=data["source_url"],
            template_path=data["template_path"],
            template_id=data["template_id"],
            raw_content=data["raw_content"],
            version=data.get("version"),
            commit_sha=data.get("commit_sha"),
            metadata=data.get("metadata", {}),
        )


class ArchitectureStatus(Enum):
    """Status of an architecture in the processing pipeline."""

    PENDING = "pending"  # Discovered, not yet processed
    NORMALIZED = "normalized"  # Successfully converted to Terraform
    CONVERSION_FAILED = "conversion_failed"  # CloudFormation conversion failed
    GENERATION_FAILED = "generation_failed"  # Sample app generation failed
    READY = "ready"  # Has generated sample app, ready for validation


class ProbeType(Enum):
    """Type of probe application for discovering LocalStack gaps."""

    API_PARITY = "api_parity"  # Tests advanced API parameters and response formats
    EDGE_CASES = "edge_cases"  # Tests edge cases: large payloads, unicode, limits
    INTEGRATION = "integration"  # Tests cross-service integrations and triggers
    STRESS = "stress"  # Tests concurrent operations, race conditions, throttling


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

    Attributes:
        id: Unique identifier for this architecture
        source_type: Whether from template or diagram
        source_name: Name of the source (e.g., "aws-quickstarts")
        source_url: URL to the original source
        main_tf: Normalized main.tf content
        variables_tf: Optional variables.tf content
        outputs_tf: Optional outputs.tf content
        metadata: Extracted metadata (services, complexity, etc.)
        created_at: When this architecture was first discovered
        updated_at: When this architecture was last modified
        content_hash: SHA256 of main_tf for cache invalidation
        synthesis_notes: For diagram-sourced: assumptions made during synthesis
    """

    id: str
    source_type: ArchitectureSourceType
    source_name: str
    source_url: str
    main_tf: str
    variables_tf: Optional[str] = None
    outputs_tf: Optional[str] = None
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
            "source_type": self.source_type.value,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "main_tf": self.main_tf,
            "variables_tf": self.variables_tf,
            "outputs_tf": self.outputs_tf,
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
            source_type=ArchitectureSourceType(data["source_type"]),
            source_name=data.get("source_name", ""),
            source_url=data.get("source_url", ""),
            main_tf=data.get("main_tf", ""),
            variables_tf=data.get("variables_tf"),
            outputs_tf=data.get("outputs_tf"),
            metadata=(
                ArchitectureMetadata.from_dict(data["metadata"])
                if data.get("metadata")
                else None
            ),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(timezone.utc),
            content_hash=data.get("content_hash", ""),
            synthesis_notes=data.get("synthesis_notes"),
        )


@dataclass
class SampleApp:
    """
    A generated probe application that tests LocalStack compatibility.

    Attributes:
        architecture_id: Reference to Architecture.id
        app_id: Unique identifier for this specific app (architecture_id + probe_type)
        probe_type: Type of probe (api_parity, edge_cases, integration, stress)
        probe_name: Human-readable name describing what this app tests
        probed_features: List of specific features being tested
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
    app_id: str = ""  # Will be set to "{architecture_id}_{probe_type}"
    probe_type: ProbeType = ProbeType.API_PARITY
    probe_name: str = ""  # e.g., "DynamoDB API Parity Probe"
    probed_features: list[str] = field(default_factory=list)  # e.g., ["transactions", "streams", "gsi"]
    source_code: dict[str, str] = field(default_factory=dict)  # filename -> content
    test_code: dict[str, str] = field(default_factory=dict)  # test filename -> content
    requirements: list[str] = field(default_factory=list)
    compile_status: str = "pending"  # "success", "failed", "pending"
    compile_errors: Optional[str] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    prompt_version: str = "2.0"  # Updated version for multi-app support
    token_usage: int = 0

    def __post_init__(self):
        """Set app_id if not provided."""
        if not self.app_id:
            self.app_id = f"{self.architecture_id}_{self.probe_type.value}"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "architecture_id": self.architecture_id,
            "app_id": self.app_id,
            "probe_type": self.probe_type.value,
            "probe_name": self.probe_name,
            "probed_features": self.probed_features,
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
            app_id=data.get("app_id", ""),
            probe_type=ProbeType(data.get("probe_type", "api_parity")),
            probe_name=data.get("probe_name", ""),
            probed_features=data.get("probed_features", []),
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
            prompt_version=data.get("prompt_version", "2.0"),
            token_usage=data.get("token_usage", 0),
        )
