"""Data models for service coverage and failure tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ServiceCoverage:
    """
    Aggregated statistics for an AWS service.

    Computed from ArchitectureResult + Architecture.metadata.services.

    Attributes:
        service_name: AWS service name (e.g., "lambda", "s3", "dynamodb")
        architectures_tested: Count of architectures using this service
        architectures_passed: Count that passed with this service
        architectures_failed: Count that failed with this service
        pass_rate: Ratio of passed to tested
        last_tested_run: Most recent run_id where this service was tested
    """

    service_name: str
    architectures_tested: int
    architectures_passed: int
    architectures_failed: int
    pass_rate: float
    last_tested_run: str

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "service_name": self.service_name,
            "architectures_tested": self.architectures_tested,
            "architectures_passed": self.architectures_passed,
            "architectures_failed": self.architectures_failed,
            "pass_rate": round(self.pass_rate, 4),
            "last_tested_run": self.last_tested_run,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ServiceCoverage":
        """Create from dictionary."""
        return cls(
            service_name=data["service_name"],
            architectures_tested=data.get("architectures_tested", 0),
            architectures_passed=data.get("architectures_passed", 0),
            architectures_failed=data.get("architectures_failed", 0),
            pass_rate=data.get("pass_rate", 0.0),
            last_tested_run=data.get("last_tested_run", ""),
        )

    @classmethod
    def calculate(
        cls,
        service_name: str,
        passed: int,
        failed: int,
        run_id: str,
    ) -> "ServiceCoverage":
        """Calculate service coverage from counts."""
        tested = passed + failed
        pass_rate = passed / tested if tested > 0 else 0.0

        return cls(
            service_name=service_name,
            architectures_tested=tested,
            architectures_passed=passed,
            architectures_failed=failed,
            pass_rate=pass_rate,
            last_tested_run=run_id,
        )


@dataclass
class FailureEntry:
    """
    Tracks consecutive failures for a single architecture.

    State transitions:
    - On failure: increment consecutive_failures, update last_failure_run
    - On success: reset entry (remove from tracker)
    - On issue creation: set issue_number, issue_created_at

    Attributes:
        architecture_id: Reference to Architecture.id
        consecutive_failures: Number of consecutive failures
        first_failure_run: Run ID of first failure in current streak
        last_failure_run: Run ID of most recent failure
        issue_number: GitHub issue number if created
        issue_created_at: When the issue was created
    """

    architecture_id: str
    consecutive_failures: int
    first_failure_run: str
    last_failure_run: str
    issue_number: Optional[int] = None
    issue_created_at: Optional[datetime] = None

    def increment(self, run_id: str) -> None:
        """Increment failure count and update last failure run."""
        self.consecutive_failures += 1
        self.last_failure_run = run_id

    def should_create_issue(self) -> bool:
        """Check if an issue should be created (2+ consecutive failures, no existing issue)."""
        return self.consecutive_failures >= 2 and self.issue_number is None

    def record_issue(self, issue_number: int) -> None:
        """Record that an issue was created."""
        self.issue_number = issue_number
        self.issue_created_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "architecture_id": self.architecture_id,
            "consecutive_failures": self.consecutive_failures,
            "first_failure_run": self.first_failure_run,
            "last_failure_run": self.last_failure_run,
            "issue_number": self.issue_number,
            "issue_created_at": (
                self.issue_created_at.isoformat() if self.issue_created_at else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FailureEntry":
        """Create from dictionary."""
        return cls(
            architecture_id=data["architecture_id"],
            consecutive_failures=data.get("consecutive_failures", 1),
            first_failure_run=data["first_failure_run"],
            last_failure_run=data["last_failure_run"],
            issue_number=data.get("issue_number"),
            issue_created_at=(
                datetime.fromisoformat(data["issue_created_at"])
                if data.get("issue_created_at")
                else None
            ),
        )

    @classmethod
    def create(cls, architecture_id: str, run_id: str) -> "FailureEntry":
        """Create a new failure entry for first failure."""
        return cls(
            architecture_id=architecture_id,
            consecutive_failures=1,
            first_failure_run=run_id,
            last_failure_run=run_id,
        )


@dataclass
class FailureTracker:
    """
    Tracks consecutive failures per architecture for issue creation logic.

    Attributes:
        entries: Map of architecture_id to FailureEntry
        updated_at: When the tracker was last updated
    """

    entries: dict[str, FailureEntry] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def record_failure(self, architecture_id: str, run_id: str) -> FailureEntry:
        """Record a failure for an architecture."""
        if architecture_id in self.entries:
            entry = self.entries[architecture_id]
            entry.increment(run_id)
        else:
            entry = FailureEntry.create(architecture_id, run_id)
            self.entries[architecture_id] = entry

        self.updated_at = datetime.now(timezone.utc)
        return entry

    def record_success(self, architecture_id: str) -> Optional[FailureEntry]:
        """Record a success for an architecture, resetting failure tracking."""
        entry = self.entries.pop(architecture_id, None)
        if entry:
            self.updated_at = datetime.now(timezone.utc)
        return entry

    def get_pending_issues(self) -> list[FailureEntry]:
        """Get entries that need issues created (2+ failures, no existing issue)."""
        return [e for e in self.entries.values() if e.should_create_issue()]

    def get_entry(self, architecture_id: str) -> Optional[FailureEntry]:
        """Get the failure entry for an architecture."""
        return self.entries.get(architecture_id)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FailureTracker":
        """Create from dictionary."""
        entries = {
            k: FailureEntry.from_dict(v)
            for k, v in data.get("entries", {}).items()
        }
        return cls(
            entries=entries,
            updated_at=(
                datetime.fromisoformat(data["updated_at"])
                if data.get("updated_at")
                else datetime.now(timezone.utc)
            ),
        )


# Known AWS services supported by LocalStack
KNOWN_AWS_SERVICES = {
    "lambda",
    "s3",
    "dynamodb",
    "sqs",
    "sns",
    "apigateway",
    "events",
    "eventbridge",
    "stepfunctions",
    "kinesis",
    "firehose",
    "cloudwatch",
    "logs",
    "iam",
    "sts",
    "secretsmanager",
    "ssm",
    "kms",
    "ec2",
    "ecs",
    "ecr",
    "rds",
    "elasticache",
    "elasticsearch",
    "opensearch",
    "cognito",
    "ses",
    "route53",
    "cloudfront",
    "acm",
    "elb",
    "elbv2",
    "autoscaling",
    "cloudformation",
    "sagemaker",
    "batch",
    "glue",
    "athena",
    "redshift",
    "emr",
    "msk",
    "mq",
    "appconfig",
    "appsync",
    "backup",
    "ce",
    "config",
    "connect",
    "docdb",
    "dms",
    "eks",
    "fis",
    "glacier",
    "guardduty",
    "inspector",
    "lakeformation",
    "mediaconvert",
    "mediastore",
    "neptune",
    "organizations",
    "pinpoint",
    "pipes",
    "qldb",
    "ram",
    "resourcegroups",
    "scheduler",
    "servicediscovery",
    "shield",
    "swf",
    "timestream",
    "transcribe",
    "transfer",
    "waf",
    "wafv2",
    "xray",
}

# Services known to have limited or no LocalStack support
UNSUPPORTED_SERVICES = {
    "workspaces",
    "workmail",
    "chime",
    "alexa",
    "iot",
    "iotevents",
    "iotsitewise",
    "lookout",
    "lex",
    "polly",
    "rekognition",
    "textract",
    "translate",
    "comprehend",
    "forecast",
    "personalize",
    "kendra",
    "fraud-detector",
    "macie",
}
