"""Data models for ls-arch-validator."""

from src.models.architecture import (
    Architecture,
    ArchitectureMetadata,
    ArchitectureSourceType,
    ArchitectureStatus,
    ProbeType,
    SampleApp,
    SourceType,
    TemplateSource,
)
from src.models.coverage import (
    KNOWN_AWS_SERVICES,
    UNSUPPORTED_SERVICES,
    FailureEntry,
    FailureTracker,
    ServiceCoverage,
)
from src.models.results import (
    ArchitectureResult,
    InfrastructureResult,
    LogBundle,
    ResultStatus,
    RunStatistics,
    StageTiming,
    TestFailure,
    TestResult,
    ValidationRun,
)

__all__ = [
    # Architecture models
    "SourceType",
    "TemplateSource",
    "ArchitectureStatus",
    "ArchitectureSourceType",
    "ArchitectureMetadata",
    "Architecture",
    "ProbeType",
    "SampleApp",
    # Result models
    "RunStatistics",
    "StageTiming",
    "ValidationRun",
    "InfrastructureResult",
    "TestFailure",
    "TestResult",
    "LogBundle",
    "ResultStatus",
    "ArchitectureResult",
    # Coverage models
    "ServiceCoverage",
    "FailureEntry",
    "FailureTracker",
    "KNOWN_AWS_SERVICES",
    "UNSUPPORTED_SERVICES",
]
