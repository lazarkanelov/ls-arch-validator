"""GitHub issue management for validation failures."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.models import ArchitectureResult, FailureEntry, FailureTracker, ResultStatus
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from github import Github
    from github.Issue import Issue

logger = get_logger("reporter.issues")

# Labels for issues
LABELS = {
    "validator": "arch-validator",
    "bug": "bug",
    "service_prefix": "service/",
}

# Consecutive failures required for issue creation
CONSECUTIVE_FAILURES_THRESHOLD = 2


class FailureTrackerManager:
    """
    Manages persistent failure tracking.

    Tracks consecutive failures per architecture to determine
    when issues should be created or closed.
    """

    def __init__(self, data_dir: Path) -> None:
        """
        Initialize the failure tracker manager.

        Args:
            data_dir: Directory for data files
        """
        self.data_dir = data_dir
        self.tracker_file = data_dir / "failure_tracker.json"
        self._tracker: Optional[FailureTracker] = None

    def load(self) -> FailureTracker:
        """Load the failure tracker from disk."""
        if self._tracker is not None:
            return self._tracker

        if self.tracker_file.exists():
            try:
                data = json.loads(self.tracker_file.read_text())
                self._tracker = FailureTracker.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("tracker_load_error", error=str(e))
                self._tracker = FailureTracker()
        else:
            self._tracker = FailureTracker()

        return self._tracker

    def save(self) -> None:
        """Save the failure tracker to disk."""
        if self._tracker is None:
            return

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tracker_file.write_text(
            json.dumps(self._tracker.to_dict(), indent=2, default=str)
        )
        logger.debug("tracker_saved", path=str(self.tracker_file))

    def update_from_results(
        self,
        results: list[ArchitectureResult],
    ) -> tuple[list[FailureEntry], list[FailureEntry]]:
        """
        Update tracker based on validation results.

        Args:
            results: List of architecture results

        Returns:
            Tuple of (new_failures, recovered) where:
            - new_failures: Entries that crossed the threshold (need issue creation)
            - recovered: Entries that recovered (need issue closing)
        """
        tracker = self.load()
        new_failures: list[FailureEntry] = []
        recovered: list[FailureEntry] = []

        for result in results:
            arch_id = result.architecture_id

            if result.status in (ResultStatus.FAILED, ResultStatus.PARTIAL):
                # Architecture failed - increment counter
                entry = tracker.get_entry(arch_id)

                if entry is None:
                    # First failure
                    entry = FailureEntry(
                        architecture_id=arch_id,
                        consecutive_failures=1,
                        first_failure=datetime.now(timezone.utc),
                        last_failure=datetime.now(timezone.utc),
                    )
                    tracker.entries[arch_id] = entry
                else:
                    # Increment existing
                    entry.consecutive_failures += 1
                    entry.last_failure = datetime.now(timezone.utc)

                # Check if we crossed the threshold
                if (
                    entry.consecutive_failures == CONSECUTIVE_FAILURES_THRESHOLD
                    and entry.issue_number is None
                ):
                    new_failures.append(entry)
                    logger.info(
                        "failure_threshold_crossed",
                        arch_id=arch_id,
                        count=entry.consecutive_failures,
                    )

            elif result.status == ResultStatus.PASSED:
                # Architecture passed - check for recovery
                entry = tracker.get_entry(arch_id)

                if entry is not None and entry.consecutive_failures > 0:
                    if entry.issue_number is not None:
                        recovered.append(entry)
                        logger.info(
                            "architecture_recovered",
                            arch_id=arch_id,
                            issue_number=entry.issue_number,
                        )

                    # Reset the entry
                    entry.consecutive_failures = 0
                    entry.first_failure = None
                    entry.last_failure = None

        self.save()
        return new_failures, recovered


class IssueContentFormatter:
    """Formats issue content for GitHub."""

    def __init__(self, dashboard_url: str = "") -> None:
        """
        Initialize the formatter.

        Args:
            dashboard_url: Base URL for dashboard links
        """
        self.dashboard_url = dashboard_url

    def format_title(self, result: ArchitectureResult) -> str:
        """Format issue title."""
        if result.suggested_issue_title:
            return result.suggested_issue_title
        return f"[arch-validator] Validation failed: {result.architecture_id}"

    def format_body(
        self,
        result: ArchitectureResult,
        failure_entry: FailureEntry,
    ) -> str:
        """
        Format issue body with full details.

        Args:
            result: Architecture result
            failure_entry: Failure tracking entry

        Returns:
            Formatted markdown body
        """
        lines = []

        # Header
        lines.append("## Architecture Validation Failure")
        lines.append("")
        lines.append(
            f"The architecture `{result.architecture_id}` has failed validation "
            f"{failure_entry.consecutive_failures} times consecutively."
        )
        lines.append("")

        # Architecture details
        lines.append("### Architecture Details")
        lines.append("")
        lines.append(f"- **Architecture ID**: `{result.architecture_id}`")
        lines.append(
            f"- **Source Type**: {result.source_type.value if hasattr(result.source_type, 'value') else result.source_type}"
        )
        if result.services:
            lines.append(f"- **AWS Services**: {', '.join(sorted(result.services))}")
        lines.append("")

        # Failure details
        lines.append("### Failure Details")
        lines.append("")
        lines.append(f"- **Status**: {result.status.value}")
        lines.append(
            f"- **First Failure**: {failure_entry.first_failure.isoformat() if failure_entry.first_failure else 'N/A'}"
        )
        lines.append(
            f"- **Last Failure**: {failure_entry.last_failure.isoformat() if failure_entry.last_failure else 'N/A'}"
        )
        lines.append("")

        # Infrastructure result
        if result.infrastructure:
            lines.append("### Infrastructure Deployment")
            lines.append("")
            if result.infrastructure.passed:
                lines.append("Infrastructure deployed successfully.")
            else:
                lines.append("**Infrastructure deployment failed.**")
                if result.infrastructure.error_message:
                    lines.append("")
                    lines.append("```")
                    lines.append(result.infrastructure.error_message[:2000])
                    lines.append("```")
            lines.append("")

        # Test result
        if result.tests:
            lines.append("### Test Results")
            lines.append("")
            lines.append(f"- **Passed**: {result.tests.passed}")
            lines.append(f"- **Failed**: {result.tests.failed}")
            lines.append(f"- **Skipped**: {result.tests.skipped}")

            if result.tests.failures:
                lines.append("")
                lines.append("#### Failed Tests")
                lines.append("")
                for failure in result.tests.failures[:5]:  # Limit to 5
                    lines.append(f"- `{failure.test_name}`")
                    if failure.error_message:
                        # Truncate long error messages
                        msg = failure.error_message[:500]
                        if len(failure.error_message) > 500:
                            msg += "..."
                        lines.append(f"  ```")
                        lines.append(f"  {msg}")
                        lines.append(f"  ```")

            lines.append("")

        # Logs section (truncated)
        if result.logs:
            lines.append("### Logs")
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>Click to expand Terraform logs</summary>")
            lines.append("")
            lines.append("```")
            terraform_log = result.logs.terraform_log[:3000] if result.logs.terraform_log else "No logs"
            lines.append(terraform_log)
            lines.append("```")
            lines.append("</details>")
            lines.append("")

        # Reproduction steps
        lines.append("### Reproduction Steps")
        lines.append("")
        lines.append("```bash")
        lines.append("# Run validation for this architecture")
        lines.append(f"ls-arch-validator validate --architecture {result.architecture_id}")
        lines.append("```")
        lines.append("")

        # Dashboard link
        if self.dashboard_url:
            lines.append("### Dashboard")
            lines.append("")
            lines.append(
                f"View the [full report]({self.dashboard_url}) for more details."
            )
            lines.append("")

        # Footer
        lines.append("---")
        lines.append(
            "*This issue was automatically created by the LocalStack Architecture Validator.*"
        )

        return "\n".join(lines)

    def get_labels(self, result: ArchitectureResult) -> list[str]:
        """
        Get labels for the issue.

        Args:
            result: Architecture result

        Returns:
            List of label names
        """
        labels = [LABELS["validator"], LABELS["bug"]]

        # Add service labels
        for service in result.services:
            labels.append(f"{LABELS['service_prefix']}{service}")

        return labels


class GitHubIssueManager:
    """
    Manages GitHub issue creation and lifecycle.

    Creates issues for persistent failures, prevents duplicates,
    and auto-closes issues when architectures recover.
    """

    def __init__(
        self,
        token: str,
        repo: str,
        dashboard_url: str = "",
        dry_run: bool = False,
    ) -> None:
        """
        Initialize the issue manager.

        Args:
            token: GitHub API token
            repo: Repository in format "owner/repo"
            dashboard_url: URL to the dashboard
            dry_run: If True, don't actually create/close issues
        """
        self.token = token
        self.repo = repo
        self.dry_run = dry_run
        self.formatter = IssueContentFormatter(dashboard_url)
        self._github: Optional["Github"] = None
        self._rate_limited = False

    def _get_client(self) -> "Github":
        """Get or create GitHub client."""
        if self._github is None:
            from github import Github

            self._github = Github(self.token)
        return self._github

    def _check_rate_limit(self) -> bool:
        """
        Check if we're rate limited.

        Returns:
            True if we can proceed, False if rate limited
        """
        try:
            client = self._get_client()
            rate_limit = client.get_rate_limit()
            remaining = rate_limit.core.remaining

            if remaining < 10:
                logger.warning(
                    "rate_limit_low",
                    remaining=remaining,
                    reset_time=rate_limit.core.reset.isoformat(),
                )
                self._rate_limited = True
                return False

            return True

        except Exception as e:
            logger.error("rate_limit_check_failed", error=str(e))
            return True  # Proceed anyway and let it fail

    def create_issue(
        self,
        result: ArchitectureResult,
        failure_entry: FailureEntry,
    ) -> Optional[int]:
        """
        Create a GitHub issue for a failure.

        Args:
            result: Architecture result
            failure_entry: Failure tracking entry

        Returns:
            Issue number if created, None otherwise
        """
        if self._rate_limited:
            logger.warning("skipping_issue_rate_limited", arch_id=result.architecture_id)
            return None

        if not self._check_rate_limit():
            return None

        # Check for existing issue
        if failure_entry.issue_number is not None:
            logger.debug(
                "issue_already_exists",
                arch_id=result.architecture_id,
                issue_number=failure_entry.issue_number,
            )
            return failure_entry.issue_number

        title = self.formatter.format_title(result)
        body = self.formatter.format_body(result, failure_entry)
        labels = self.formatter.get_labels(result)

        if self.dry_run:
            logger.info(
                "dry_run_create_issue",
                arch_id=result.architecture_id,
                title=title,
                labels=labels,
            )
            return None

        try:
            client = self._get_client()
            repo = client.get_repo(self.repo)

            # Ensure labels exist
            self._ensure_labels_exist(repo, labels)

            # Create issue
            issue = repo.create_issue(
                title=title,
                body=body,
                labels=labels,
            )

            logger.info(
                "issue_created",
                arch_id=result.architecture_id,
                issue_number=issue.number,
                url=issue.html_url,
            )

            return issue.number

        except Exception as e:
            logger.error(
                "issue_creation_failed",
                arch_id=result.architecture_id,
                error=str(e),
            )
            return None

    def close_issue(
        self,
        failure_entry: FailureEntry,
        message: str = "Architecture now passes validation.",
    ) -> bool:
        """
        Close an issue when architecture recovers.

        Args:
            failure_entry: Failure entry with issue number
            message: Comment to add before closing

        Returns:
            True if issue was closed
        """
        if failure_entry.issue_number is None:
            return False

        if self._rate_limited:
            logger.warning(
                "skipping_close_rate_limited",
                issue_number=failure_entry.issue_number,
            )
            return False

        if not self._check_rate_limit():
            return False

        if self.dry_run:
            logger.info(
                "dry_run_close_issue",
                issue_number=failure_entry.issue_number,
                message=message,
            )
            return True

        try:
            client = self._get_client()
            repo = client.get_repo(self.repo)
            issue = repo.get_issue(failure_entry.issue_number)

            # Check if already closed
            if issue.state == "closed":
                logger.debug(
                    "issue_already_closed",
                    issue_number=failure_entry.issue_number,
                )
                return True

            # Add comment
            issue.create_comment(
                f"This issue is being automatically closed.\n\n{message}\n\n"
                "*Closed by LocalStack Architecture Validator*"
            )

            # Close issue
            issue.edit(state="closed")

            logger.info(
                "issue_closed",
                issue_number=failure_entry.issue_number,
            )

            return True

        except Exception as e:
            logger.error(
                "issue_close_failed",
                issue_number=failure_entry.issue_number,
                error=str(e),
            )
            return False

    def _ensure_labels_exist(self, repo, labels: list[str]) -> None:
        """Ensure all required labels exist in the repository."""
        try:
            existing_labels = {label.name for label in repo.get_labels()}

            for label in labels:
                if label not in existing_labels:
                    # Create with default color
                    color = "d73a4a" if label == "bug" else "0366d6"
                    try:
                        repo.create_label(name=label, color=color)
                        logger.debug("label_created", label=label)
                    except Exception:
                        pass  # Label may have been created concurrently

        except Exception as e:
            logger.warning("label_check_failed", error=str(e))


def process_results_for_issues(
    results: list[ArchitectureResult],
    data_dir: Path,
    github_token: Optional[str] = None,
    github_repo: Optional[str] = None,
    dashboard_url: str = "",
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Process validation results and manage issues.

    Args:
        results: List of architecture results
        data_dir: Directory for data files
        github_token: GitHub API token (optional)
        github_repo: Repository in format "owner/repo" (optional)
        dashboard_url: Dashboard URL for links
        dry_run: If True, don't actually create/close issues

    Returns:
        Dict with counts: {"created": N, "closed": N, "skipped": N}
    """
    tracker_manager = FailureTrackerManager(data_dir)

    # Update tracker and get lists
    new_failures, recovered = tracker_manager.update_from_results(results)

    stats = {"created": 0, "closed": 0, "skipped": 0}

    # If no GitHub credentials, just track failures
    if not github_token or not github_repo:
        logger.info(
            "github_not_configured",
            new_failures=len(new_failures),
            recovered=len(recovered),
        )
        stats["skipped"] = len(new_failures) + len(recovered)
        return stats

    # Create issue manager
    issue_manager = GitHubIssueManager(
        token=github_token,
        repo=github_repo,
        dashboard_url=dashboard_url,
        dry_run=dry_run,
    )

    # Create map of results by arch_id for lookup
    results_map = {r.architecture_id: r for r in results}

    # Create issues for new failures
    for entry in new_failures:
        result = results_map.get(entry.architecture_id)
        if result:
            issue_number = issue_manager.create_issue(result, entry)
            if issue_number:
                entry.issue_number = issue_number
                stats["created"] += 1
            else:
                stats["skipped"] += 1

    # Close issues for recovered
    for entry in recovered:
        if issue_manager.close_issue(entry):
            entry.issue_number = None  # Clear the issue number
            stats["closed"] += 1
        else:
            stats["skipped"] += 1

    # Save updated tracker
    tracker_manager.save()

    logger.info(
        "issue_processing_complete",
        created=stats["created"],
        closed=stats["closed"],
        skipped=stats["skipped"],
    )

    return stats
