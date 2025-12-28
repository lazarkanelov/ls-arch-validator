"""Data models for validation runs and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


@dataclass
class RunStatistics:
    """
    Statistics for a validation run.

    Attributes:
        total_architectures: Total number of architectures processed
        passed: Number that passed all tests
        partial: Number with some test failures
        failed: Number with deployment or critical failures
        skipped: Number skipped (e.g., generation failed)
        pass_rate: Ratio of passed to total validated
    """

    total_architectures: int
    passed: int
    partial: int
    failed: int
    skipped: int
    pass_rate: float

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total_architectures": self.total_architectures,
            "passed": self.passed,
            "partial": self.partial,
            "failed": self.failed,
            "skipped": self.skipped,
            "pass_rate": round(self.pass_rate, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunStatistics":
        """Create from dictionary."""
        return cls(
            total_architectures=data.get("total_architectures", 0),
            passed=data.get("passed", 0),
            partial=data.get("partial", 0),
            failed=data.get("failed", 0),
            skipped=data.get("skipped", 0),
            pass_rate=data.get("pass_rate", 0.0),
        )

    @classmethod
    def calculate(
        cls,
        passed: int,
        partial: int,
        failed: int,
        skipped: int,
    ) -> "RunStatistics":
        """Calculate statistics from counts."""
        total = passed + partial + failed + skipped
        validated = passed + partial + failed
        pass_rate = passed / validated if validated > 0 else 0.0

        return cls(
            total_architectures=total,
            passed=passed,
            partial=partial,
            failed=failed,
            skipped=skipped,
            pass_rate=pass_rate,
        )


@dataclass
class StageTiming:
    """
    Timing information for pipeline stages.

    Attributes:
        mining_seconds: Time spent mining templates
        generation_seconds: Time spent generating sample apps
        running_seconds: Time spent running validations
        reporting_seconds: Time spent generating reports
        total_seconds: Total pipeline duration
    """

    mining_seconds: float = 0.0
    generation_seconds: float = 0.0
    running_seconds: float = 0.0
    reporting_seconds: float = 0.0
    total_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "mining_seconds": round(self.mining_seconds, 3),
            "generation_seconds": round(self.generation_seconds, 3),
            "running_seconds": round(self.running_seconds, 3),
            "reporting_seconds": round(self.reporting_seconds, 3),
            "total_seconds": round(self.total_seconds, 3),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StageTiming":
        """Create from dictionary."""
        return cls(
            mining_seconds=data.get("mining_seconds", 0.0),
            generation_seconds=data.get("generation_seconds", 0.0),
            running_seconds=data.get("running_seconds", 0.0),
            reporting_seconds=data.get("reporting_seconds", 0.0),
            total_seconds=data.get("total_seconds", 0.0),
        )


@dataclass
class ValidationRun:
    """
    A complete execution of the validation pipeline.

    Attributes:
        id: Run identifier in format "run-{YYYYMMDD}-{HHMMSS}"
        started_at: When the run started
        completed_at: When the run completed (None if still running)
        status: Run status ("running", "completed", "failed")
        trigger: How the run was triggered ("scheduled", "manual")
        parallelism: Number of concurrent validations
        localstack_version: LocalStack image tag used
        statistics: Aggregated run statistics
        timing: Stage timing information
        results: List of ArchitectureResult IDs
        token_usage: Total Claude API tokens used
        token_budget: Configured token budget
    """

    id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str = "running"  # "running", "completed", "failed"
    trigger: str = "scheduled"  # "scheduled", "manual"
    parallelism: int = 4
    localstack_version: str = "latest"
    statistics: Optional[RunStatistics] = None
    timing: Optional[StageTiming] = None
    results: list["ArchitectureResult"] = field(default_factory=list)
    token_usage: int = 0
    token_budget: int = 500000

    @classmethod
    def create(
        cls,
        trigger: str = "manual",
        parallelism: int = 4,
        localstack_version: str = "latest",
        token_budget: int = 500000,
    ) -> "ValidationRun":
        """Create a new validation run with generated ID."""
        now = datetime.now(timezone.utc)
        run_id = f"run-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"

        return cls(
            id=run_id,
            started_at=now,
            trigger=trigger,
            parallelism=parallelism,
            localstack_version=localstack_version,
            token_budget=token_budget,
        )

    def complete(
        self,
        statistics: Optional[RunStatistics] = None,
        timing: Optional[StageTiming] = None,
    ) -> None:
        """Mark the run as completed with final statistics."""
        self.completed_at = datetime.now(timezone.utc)
        self.status = "completed"

        # Calculate statistics from results if not provided
        if statistics:
            self.statistics = statistics
        elif self.results:
            passed = sum(1 for r in self.results if r.status == ResultStatus.PASSED)
            partial = sum(1 for r in self.results if r.status == ResultStatus.PARTIAL)
            failed = sum(1 for r in self.results if r.status == ResultStatus.FAILED)
            skipped = sum(1 for r in self.results if r.status == ResultStatus.SKIPPED)
            self.statistics = RunStatistics.calculate(passed, partial, failed, skipped)

        if timing:
            self.timing = timing

    def fail(self, error: str) -> None:
        """Mark the run as failed."""
        self.completed_at = datetime.now(timezone.utc)
        self.status = "failed"

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        # Handle both ArchitectureResult objects and plain IDs
        results_data = []
        for r in self.results:
            if hasattr(r, 'to_dict'):
                results_data.append(r.to_dict())
            else:
                results_data.append(r)

        return {
            "id": self.id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "trigger": self.trigger,
            "parallelism": self.parallelism,
            "localstack_version": self.localstack_version,
            "statistics": self.statistics.to_dict() if self.statistics else None,
            "timing": self.timing.to_dict() if self.timing else None,
            "results": results_data,
            "token_usage": self.token_usage,
            "token_budget": self.token_budget,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ValidationRun":
        """Create from dictionary."""
        # Handle both serialized ArchitectureResult dicts and plain IDs
        results = []
        for r in data.get("results", []):
            if isinstance(r, dict) and "architecture_id" in r:
                results.append(ArchitectureResult.from_dict(r))
            else:
                results.append(r)

        return cls(
            id=data["id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            status=data.get("status", "running"),
            trigger=data.get("trigger", "manual"),
            parallelism=data.get("parallelism", 4),
            localstack_version=data.get("localstack_version", "latest"),
            statistics=(
                RunStatistics.from_dict(data["statistics"])
                if data.get("statistics")
                else None
            ),
            timing=(
                StageTiming.from_dict(data["timing"]) if data.get("timing") else None
            ),
            results=results,
            token_usage=data.get("token_usage", 0),
            token_budget=data.get("token_budget", 500000),
        )


@dataclass
class InfrastructureResult:
    """
    Result of infrastructure deployment.

    Attributes:
        passed: Whether deployment succeeded
        duration_seconds: Time taken for deployment
        resources_created: List of created Terraform resources
        error_message: Error message if deployment failed
        outputs: Terraform outputs
    """

    passed: bool = False
    duration_seconds: float = 0.0
    resources_created: list[str] = field(default_factory=list)
    error_message: Optional[str] = None
    outputs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "duration_seconds": round(self.duration_seconds, 3),
            "resources_created": self.resources_created,
            "error_message": self.error_message,
            "outputs": self.outputs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InfrastructureResult":
        """Create from dictionary."""
        return cls(
            passed=data.get("passed", False),
            duration_seconds=data.get("duration_seconds", 0.0),
            resources_created=data.get("resources_created", []),
            error_message=data.get("error_message"),
            outputs=data.get("outputs", {}),
        )


@dataclass
class TestFailure:
    """
    Details of a single test failure.

    Attributes:
        test_name: Name/path of the failed test
        error_message: Error message or traceback
        duration_seconds: Time the test took before failing
    """

    test_name: str
    error_message: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "test_name": self.test_name,
            "error_message": self.error_message,
            "duration_seconds": round(self.duration_seconds, 3),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestFailure":
        """Create from dictionary."""
        return cls(
            test_name=data.get("test_name", "unknown"),
            error_message=data.get("error_message", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class TestResult:
    """
    Result of test execution.

    Attributes:
        passed: Number of tests that passed
        failed: Number of tests that failed
        skipped: Number of tests skipped
        duration_seconds: Total test execution time
        failures: List of TestFailure details
    """

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failures: list[TestFailure] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Total number of tests."""
        return self.passed + self.failed + self.skipped

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": round(self.duration_seconds, 3),
            "failures": [f.to_dict() for f in self.failures],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestResult":
        """Create from dictionary."""
        failures = [
            TestFailure.from_dict(f) if isinstance(f, dict) else f
            for f in data.get("failures", [])
        ]
        return cls(
            passed=data.get("passed", 0),
            failed=data.get("failed", 0),
            skipped=data.get("skipped", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            failures=failures,
        )


@dataclass
class LogBundle:
    """
    Bundle of logs from a validation.

    Attributes:
        terraform_log: Output from Terraform commands
        localstack_log: LocalStack container logs
        app_log: Application execution logs
        test_output: pytest output
    """

    terraform_log: str = ""
    localstack_log: str = ""
    app_log: str = ""
    test_output: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "terraform_log": self.terraform_log,
            "localstack_log": self.localstack_log,
            "app_log": self.app_log,
            "test_output": self.test_output,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogBundle":
        """Create from dictionary."""
        return cls(
            terraform_log=data.get("terraform_log", ""),
            localstack_log=data.get("localstack_log", ""),
            app_log=data.get("app_log", ""),
            test_output=data.get("test_output", ""),
        )


class ResultStatus(Enum):
    """Status of an architecture validation result."""

    PASSED = "passed"  # All tests pass
    PARTIAL = "partial"  # Some tests fail
    FAILED = "failed"  # Deployment or critical failure
    SKIPPED = "skipped"  # Generation failed, no app to run
    TIMEOUT = "timeout"  # Exceeded time limit


@dataclass
class ArchitectureResult:
    """
    Outcome of validating a single architecture within a run.

    Attributes:
        architecture_id: Reference to Architecture.id
        source_type: Source type of the architecture (template, diagram)
        status: Result status
        services: Set of AWS services used
        infrastructure: Infrastructure deployment result
        tests: Test execution result
        logs: Log bundle from validation
        duration_seconds: Total validation time
        issue_number: GitHub issue number if created
        suggested_issue_title: Suggested title for issue creation
        id: Result identifier (optional, for legacy compatibility)
        run_id: Reference to ValidationRun.id (optional)
    """

    architecture_id: str
    source_type: "ArchitectureSourceType"
    status: ResultStatus
    services: set[str] = field(default_factory=set)
    infrastructure: Optional[InfrastructureResult] = None
    tests: Optional[TestResult] = None
    logs: Optional[LogBundle] = None
    duration_seconds: float = 0.0
    issue_number: Optional[int] = None
    suggested_issue_title: Optional[str] = None
    id: Optional[str] = None
    run_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Generate ID if not provided."""
        if self.id is None and self.run_id:
            self.id = f"{self.run_id}/{self.architecture_id}"

    @classmethod
    def create(
        cls,
        run_id: str,
        architecture_id: str,
        status: ResultStatus,
        source_type: "ArchitectureSourceType",
        services: Optional[set[str]] = None,
    ) -> "ArchitectureResult":
        """Create a new architecture result."""
        return cls(
            id=f"{run_id}/{architecture_id}",
            run_id=run_id,
            architecture_id=architecture_id,
            source_type=source_type,
            status=status,
            services=services or set(),
        )

    def determine_status(self) -> ResultStatus:
        """Determine status based on infrastructure and test results."""
        if self.infrastructure is None:
            return ResultStatus.SKIPPED

        if not self.infrastructure.passed:
            return ResultStatus.FAILED

        if self.tests is None:
            return ResultStatus.FAILED

        if self.tests.failed == 0:
            return ResultStatus.PASSED
        else:
            return ResultStatus.PARTIAL

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "architecture_id": self.architecture_id,
            "source_type": self.source_type.value if hasattr(self.source_type, 'value') else str(self.source_type),
            "status": self.status.value,
            "services": list(self.services),
            "infrastructure": (
                self.infrastructure.to_dict() if self.infrastructure else None
            ),
            "tests": self.tests.to_dict() if self.tests else None,
            "logs": self.logs.to_dict() if self.logs else None,
            "duration_seconds": round(self.duration_seconds, 3),
            "issue_number": self.issue_number,
            "suggested_issue_title": self.suggested_issue_title,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchitectureResult":
        """Create from dictionary."""
        from src.models.architecture import ArchitectureSourceType

        source_type_value = data.get("source_type", "template")
        if isinstance(source_type_value, str):
            source_type = ArchitectureSourceType(source_type_value)
        else:
            source_type = source_type_value

        return cls(
            architecture_id=data["architecture_id"],
            source_type=source_type,
            status=ResultStatus(data["status"]),
            services=set(data.get("services", [])),
            infrastructure=(
                InfrastructureResult.from_dict(data["infrastructure"])
                if data.get("infrastructure")
                else None
            ),
            tests=(
                TestResult.from_dict(data["tests"]) if data.get("tests") else None
            ),
            logs=LogBundle.from_dict(data["logs"]) if data.get("logs") else None,
            duration_seconds=data.get("duration_seconds", 0.0),
            issue_number=data.get("issue_number"),
            suggested_issue_title=data.get("suggested_issue_title"),
            id=data.get("id"),
            run_id=data.get("run_id"),
        )
