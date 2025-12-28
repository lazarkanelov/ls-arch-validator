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

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "architecture_id": self.architecture_id,
            "source_type": self.source_type,
            "services": self.services,
            "error_summary": self.error_summary,
            "infrastructure_error": self.infrastructure_error,
            "test_failures": self.test_failures,
            "logs_url": self.logs_url,
            "issue_url": self.issue_url,
        }


@dataclass
class PassingInfo:
    """Information about a passing architecture for dashboard display."""

    architecture_id: str
    source_type: str
    services: list[str]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "architecture_id": self.architecture_id,
            "source_type": self.source_type,
            "services": self.services,
        }


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

    def get_failures(self, base_logs_url: str = "") -> list[FailureInfo]:
        """
        Extract failure information for dashboard display.

        Args:
            base_logs_url: Base URL for log files

        Returns:
            List of failure information
        """
        if self._failures is not None:
            return self._failures

        failures = []
        for result in self.run.results:
            if result.status in (ResultStatus.FAILED, ResultStatus.PARTIAL):
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
                )
                failures.append(failure)

        self._failures = failures
        logger.debug("failures_extracted", count=len(failures))
        return failures

    def get_passing(self) -> list[PassingInfo]:
        """
        Extract passing architecture information.

        Returns:
            List of passing architecture information
        """
        if self._passing is not None:
            return self._passing

        passing = []
        for result in self.run.results:
            if result.status == ResultStatus.PASSED:
                passing.append(
                    PassingInfo(
                        architecture_id=result.architecture_id,
                        source_type=self._format_source_type(result.source_type),
                        services=list(result.services),
                    )
                )

        self._passing = passing
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
    ) -> dict[str, Any]:
        """
        Generate complete dashboard data structure.

        Args:
            previous_pass_rate: Pass rate from previous run
            base_logs_url: Base URL for log files

        Returns:
            Complete dashboard data dictionary
        """
        stats = self.compute_statistics(previous_pass_rate)
        source_counts = self.get_source_counts()

        return {
            "statistics": stats.to_dict(),
            "template_count": source_counts["template_count"],
            "diagram_count": source_counts["diagram_count"],
            "failures": [f.to_dict() for f in self.get_failures(base_logs_url)],
            "passing": [p.to_dict() for p in self.get_passing()],
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
