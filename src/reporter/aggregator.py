"""Results aggregation and statistics computation for dashboard."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from src.models import (
    ArchitectureResult,
    ArchitectureSourceType,
    ResultStatus,
    ServiceCoverage,
    ValidationRun,
)
from src.utils.logging import get_logger

logger = get_logger("reporter.aggregator")


@dataclass
class ArchitectureSourceInfo:
    """Source information for an architecture - where it was scraped from."""

    source_id: str
    source_name: str
    source_type: str  # "template" or "diagram"
    source_url: Optional[str] = None
    template_path: Optional[str] = None
    original_format: Optional[str] = None  # "cloudformation", "terraform", "sam", "diagram"
    diagram_confidence: Optional[float] = None  # 0.0-1.0 for diagram sources
    synthesis_notes: Optional[str] = None  # Assumptions made during conversion

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "template_path": self.template_path,
            "original_format": self.original_format,
            "diagram_confidence": self.diagram_confidence,
            "synthesis_notes": self.synthesis_notes,
        }


@dataclass
class TerraformCodeInfo:
    """Terraform infrastructure code for display."""

    main_tf: str
    variables_tf: Optional[str] = None
    outputs_tf: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "main_tf": self.main_tf,
            "variables_tf": self.variables_tf,
            "outputs_tf": self.outputs_tf,
        }


@dataclass
class GeneratedAppInfo:
    """Information about generated application code."""

    content_hash: str
    source_files: dict[str, str] = field(default_factory=dict)
    test_files: dict[str, str] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    download_url: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "content_hash": self.content_hash,
            "source_files": self.source_files,
            "test_files": self.test_files,
            "requirements": self.requirements,
            "download_url": self.download_url,
            "source_file_count": len(self.source_files),
            "test_file_count": len(self.test_files),
            "requirements_count": len(self.requirements),
        }


@dataclass
class AggregatedStatistics:
    """Aggregated statistics for a validation run."""

    total: int = 0
    passed: int = 0
    partial: int = 0
    failed: int = 0
    timeout: int = 0
    pass_rate: float = 0.0
    pass_rate_change: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            "total": self.total,
            "passed": self.passed,
            "partial": self.partial,
            "failed": self.failed,
            "timeout": self.timeout,
            "pass_rate": self.pass_rate,
        }
        if self.pass_rate_change is not None:
            result["pass_rate_change"] = self.pass_rate_change
        return result


@dataclass
class FailureInfo:
    """Information about a failed architecture for dashboard display."""

    architecture_id: str
    source_type: str
    services: list[str]
    error_summary: str
    infrastructure_error: Optional[str] = None
    test_failures: list[str] = field(default_factory=list)
    logs_url: Optional[str] = None
    issue_url: Optional[str] = None
    source_info: Optional[ArchitectureSourceInfo] = None
    terraform_code: Optional[TerraformCodeInfo] = None
    generated_app: Optional[GeneratedAppInfo] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            "architecture_id": self.architecture_id,
            "source_type": self.source_type,
            "services": self.services,
            "error_summary": self.error_summary,
            "infrastructure_error": self.infrastructure_error,
            "test_failures": self.test_failures,
            "logs_url": self.logs_url,
            "issue_url": self.issue_url,
        }
        if self.source_info:
            result["source_info"] = self.source_info.to_dict()
        if self.terraform_code:
            result["terraform_code"] = self.terraform_code.to_dict()
        if self.generated_app:
            result["generated_app"] = self.generated_app.to_dict()
        return result


@dataclass
class PassingInfo:
    """Information about a passing architecture for dashboard display."""

    architecture_id: str
    source_type: str
    services: list[str]
    source_info: Optional[ArchitectureSourceInfo] = None
    terraform_code: Optional[TerraformCodeInfo] = None
    generated_app: Optional[GeneratedAppInfo] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            "architecture_id": self.architecture_id,
            "source_type": self.source_type,
            "services": self.services,
        }
        if self.source_info:
            result["source_info"] = self.source_info.to_dict()
        if self.terraform_code:
            result["terraform_code"] = self.terraform_code.to_dict()
        if self.generated_app:
            result["generated_app"] = self.generated_app.to_dict()
        return result


class ResultsAggregator:
    """Aggregates validation results for dashboard display."""

    def __init__(self, run: ValidationRun) -> None:
        """
        Initialize the aggregator.

        Args:
            run: The validation run to aggregate
        """
        self.run = run
        self._statistics: Optional[AggregatedStatistics] = None
        self._failures: Optional[list[FailureInfo]] = None
        self._passing: Optional[list[PassingInfo]] = None
        self._service_coverage: Optional[list[ServiceCoverage]] = None
        self._unsupported_services: Optional[set[str]] = None

    def compute_statistics(
        self,
        previous_pass_rate: Optional[float] = None,
    ) -> AggregatedStatistics:
        """
        Compute aggregated statistics from the run.

        Args:
            previous_pass_rate: Pass rate from previous run for comparison

        Returns:
            Aggregated statistics
        """
        if self._statistics is not None:
            return self._statistics

        stats = AggregatedStatistics()

        for result in self.run.results:
            stats.total += 1
            if result.status == ResultStatus.PASSED:
                stats.passed += 1
            elif result.status == ResultStatus.PARTIAL:
                stats.partial += 1
            elif result.status == ResultStatus.FAILED:
                stats.failed += 1
            elif result.status == ResultStatus.TIMEOUT:
                stats.timeout += 1

        if stats.total > 0:
            stats.pass_rate = stats.passed / stats.total
        else:
            stats.pass_rate = 0.0

        if previous_pass_rate is not None:
            stats.pass_rate_change = stats.pass_rate - previous_pass_rate

        self._statistics = stats
        logger.debug(
            "statistics_computed",
            total=stats.total,
            passed=stats.passed,
            pass_rate=stats.pass_rate,
        )
        return stats

    def get_failures(
        self,
        base_logs_url: str = "",
        architectures: Optional[dict] = None,
        app_data: Optional[dict] = None,
        base_download_url: str = "",
    ) -> list[FailureInfo]:
        """
        Extract failure information for dashboard display.

        Args:
            base_logs_url: Base URL for log files
            architectures: Dict of architecture_id -> Architecture objects
            app_data: Dict of content_hash -> app data dicts
            base_download_url: Base URL for app downloads

        Returns:
            List of failure information
        """
        failures = []
        for result in self.run.results:
            if result.status in (ResultStatus.FAILED, ResultStatus.PARTIAL):
                # Get source info from architecture
                source_info = None
                terraform_code = None
                if architectures and result.architecture_id in architectures:
                    arch = architectures[result.architecture_id]
                    source_info = self._build_source_info(arch)
                    terraform_code = self._build_terraform_code(arch)

                # Get generated app info
                generated_app = None
                if architectures and result.architecture_id in architectures:
                    arch = architectures[result.architecture_id]
                    if arch.content_hash and app_data and arch.content_hash in app_data:
                        generated_app = self._build_generated_app_info(
                            arch.content_hash,
                            app_data[arch.content_hash],
                            base_download_url,
                        )

                failure = FailureInfo(
                    architecture_id=result.architecture_id,
                    source_type=self._format_source_type(result.source_type),
                    services=list(result.services),
                    error_summary=result.suggested_issue_title or "Unknown error",
                    infrastructure_error=(
                        result.infrastructure.error_message
                        if result.infrastructure and not result.infrastructure.passed
                        else None
                    ),
                    test_failures=(
                        [
                            f.test_name
                            for f in result.tests.failures
                        ]
                        if result.tests
                        else []
                    ),
                    logs_url=(
                        f"{base_logs_url}/{self.run.id}/{result.architecture_id}/"
                        if base_logs_url
                        else None
                    ),
                    issue_url=result.issue_url,
                    source_info=source_info,
                    terraform_code=terraform_code,
                    generated_app=generated_app,
                )
                failures.append(failure)

        logger.debug("failures_extracted", count=len(failures))
        return failures

    def get_passing(
        self,
        architectures: Optional[dict] = None,
        app_data: Optional[dict] = None,
        base_download_url: str = "",
    ) -> list[PassingInfo]:
        """
        Extract passing architecture information.

        Args:
            architectures: Dict of architecture_id -> Architecture objects
            app_data: Dict of content_hash -> app data dicts
            base_download_url: Base URL for app downloads

        Returns:
            List of passing architecture information
        """
        passing = []
        for result in self.run.results:
            if result.status == ResultStatus.PASSED:
                # Get source info from architecture
                source_info = None
                terraform_code = None
                if architectures and result.architecture_id in architectures:
                    arch = architectures[result.architecture_id]
                    source_info = self._build_source_info(arch)
                    terraform_code = self._build_terraform_code(arch)

                # Get generated app info
                generated_app = None
                if architectures and result.architecture_id in architectures:
                    arch = architectures[result.architecture_id]
                    if arch.content_hash and app_data and arch.content_hash in app_data:
                        generated_app = self._build_generated_app_info(
                            arch.content_hash,
                            app_data[arch.content_hash],
                            base_download_url,
                        )

                passing.append(
                    PassingInfo(
                        architecture_id=result.architecture_id,
                        source_type=self._format_source_type(result.source_type),
                        services=list(result.services),
                        source_info=source_info,
                        terraform_code=terraform_code,
                        generated_app=generated_app,
                    )
                )

        logger.debug("passing_extracted", count=len(passing))
        return passing

    def compute_service_coverage(self) -> list[ServiceCoverage]:
        """
        Compute per-service coverage statistics.

        Returns:
            List of service coverage data sorted by total count
        """
        if self._service_coverage is not None:
            return self._service_coverage

        service_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "passed": 0, "failed": 0}
        )

        for result in self.run.results:
            for service in result.services:
                service_stats[service]["total"] += 1
                if result.status == ResultStatus.PASSED:
                    service_stats[service]["passed"] += 1
                elif result.status in (ResultStatus.FAILED, ResultStatus.PARTIAL):
                    service_stats[service]["failed"] += 1

        coverage_list = []
        for service_name, stats in service_stats.items():
            pass_rate = (
                stats["passed"] / stats["total"]
                if stats["total"] > 0
                else 0.0
            )
            coverage_list.append(
                ServiceCoverage(
                    service_name=service_name,
                    total_tested=stats["total"],
                    passed=stats["passed"],
                    failed=stats["failed"],
                    pass_rate=pass_rate,
                )
            )

        # Sort by total count descending
        coverage_list.sort(key=lambda x: x.total_tested, reverse=True)

        self._service_coverage = coverage_list
        logger.debug("service_coverage_computed", services=len(coverage_list))
        return coverage_list

    def get_unsupported_services(self) -> set[str]:
        """
        Get list of unsupported services detected in templates.

        Returns:
            Set of unsupported service names
        """
        if self._unsupported_services is not None:
            return self._unsupported_services

        # This would be populated from the mining/validation process
        # For now, extract from infrastructure errors
        unsupported = set()
        for result in self.run.results:
            if (
                result.infrastructure
                and not result.infrastructure.passed
                and result.infrastructure.error_message
            ):
                error = result.infrastructure.error_message.lower()
                if "not supported" in error or "not available" in error:
                    # Try to extract service name from error
                    for service in result.services:
                        if service.lower() in error:
                            unsupported.add(service)

        self._unsupported_services = unsupported
        return unsupported

    def get_source_counts(self) -> dict[str, int]:
        """
        Count architectures by source type (template vs diagram).

        Returns:
            Dict with template_count and diagram_count
        """
        template_count = 0
        diagram_count = 0

        for result in self.run.results:
            if result.source_type == ArchitectureSourceType.DIAGRAM:
                diagram_count += 1
            else:
                template_count += 1

        return {
            "template_count": template_count,
            "diagram_count": diagram_count,
        }

    def filter_by_source_type(
        self,
        source_type: ArchitectureSourceType,
    ) -> list[ArchitectureResult]:
        """
        Filter results by source type (diagram vs template).

        Args:
            source_type: The source type to filter by

        Returns:
            Filtered list of results
        """
        return [
            result
            for result in self.run.results
            if result.source_type == source_type
        ]

    def to_dashboard_data(
        self,
        previous_pass_rate: Optional[float] = None,
        base_logs_url: str = "",
        architectures: Optional[dict] = None,
        app_data: Optional[dict] = None,
        base_download_url: str = "",
    ) -> dict[str, Any]:
        """
        Generate complete dashboard data structure.

        Args:
            previous_pass_rate: Pass rate from previous run
            base_logs_url: Base URL for log files
            architectures: Dict of architecture_id -> Architecture objects
            app_data: Dict of content_hash -> app data dicts
            base_download_url: Base URL for app downloads

        Returns:
            Complete dashboard data dictionary
        """
        stats = self.compute_statistics(previous_pass_rate)
        source_counts = self.get_source_counts()

        return {
            "statistics": stats.to_dict(),
            "template_count": source_counts["template_count"],
            "diagram_count": source_counts["diagram_count"],
            "failures": [
                f.to_dict()
                for f in self.get_failures(
                    base_logs_url, architectures, app_data, base_download_url
                )
            ],
            "passing": [
                p.to_dict()
                for p in self.get_passing(architectures, app_data, base_download_url)
            ],
            "service_coverage": [
                {
                    "name": sc.service_name,
                    "total": sc.total_tested,
                    "passed": sc.passed,
                    "failed": sc.failed,
                    "pass_rate": sc.pass_rate,
                }
                for sc in self.compute_service_coverage()
            ],
            "unsupported_services": list(self.get_unsupported_services()),
        }

    @staticmethod
    def _format_source_type(source_type: ArchitectureSourceType) -> str:
        """Format source type for display."""
        if source_type == ArchitectureSourceType.DIAGRAM:
            return "diagram"
        return "template"

    def _build_source_info(self, arch) -> ArchitectureSourceInfo:
        """Build source info from an Architecture object."""
        # Determine source name from source_id
        source_names = {
            "aws-quickstarts": "AWS QuickStart Templates",
            "terraform-registry": "Terraform Registry",
            "aws-solutions": "AWS Solutions Library",
            "serverless-examples": "Serverless Framework Examples",
            "aws-architecture-center": "AWS Architecture Center",
            "azure-architecture-center": "Azure Architecture Center",
        }
        source_name = source_names.get(arch.source_id, arch.source_id)

        # Build source URL if possible
        source_url = None
        if arch.template_path:
            if arch.source_id == "terraform-registry":
                source_url = f"https://registry.terraform.io/modules/{arch.template_path}"
            elif "github" in arch.source_id.lower() or arch.source_id == "aws-quickstarts":
                source_url = arch.template_path if arch.template_path.startswith("http") else None

        # For diagram sources, template_path often contains the page URL
        if arch.source_type == ArchitectureSourceType.DIAGRAM and arch.template_path:
            if arch.template_path.startswith("http"):
                source_url = arch.template_path

        return ArchitectureSourceInfo(
            source_id=arch.source_id,
            source_name=source_name,
            source_type=self._format_source_type(arch.source_type),
            source_url=source_url,
            template_path=arch.template_path if not (arch.template_path and arch.template_path.startswith("http")) else None,
            original_format=arch.metadata.original_format if arch.metadata else None,
            diagram_confidence=arch.metadata.diagram_confidence if arch.metadata else None,
            synthesis_notes=arch.synthesis_notes,
        )

    def _build_terraform_code(self, arch) -> TerraformCodeInfo:
        """Build terraform code info from an Architecture object."""
        return TerraformCodeInfo(
            main_tf=arch.terraform_content or "",
            variables_tf=arch.variables_content,
            outputs_tf=arch.outputs_content,
        )

    def _build_generated_app_info(
        self,
        content_hash: str,
        app_data_dict: dict,
        base_download_url: str,
    ) -> GeneratedAppInfo:
        """Build generated app info from app cache data."""
        return GeneratedAppInfo(
            content_hash=content_hash,
            source_files=app_data_dict.get("source_code", {}),
            test_files=app_data_dict.get("test_code", {}),
            requirements=app_data_dict.get("requirements", []),
            download_url=f"{base_download_url}/{content_hash}.zip" if base_download_url else None,
        )
