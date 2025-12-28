"""Reporter module for dashboard generation and result aggregation."""

from src.reporter.aggregator import (
    AggregatedStatistics,
    ArchitectureSourceInfo,
    FailureInfo,
    GeneratedAppInfo,
    PassingInfo,
    ResultsAggregator,
    TerraformCodeInfo,
)
from src.reporter.downloads import AppDownloadGenerator
from src.reporter.issues import (
    FailureTrackerManager,
    GitHubIssueManager,
    IssueContentFormatter,
    process_results_for_issues,
)
from src.reporter.notifications import (
    SlackMessage,
    SlackNotifier,
    send_slack_notification,
)
from src.reporter.site import SiteGenerator
from src.reporter.trends import RunSummary, TrendAnalyzer, TrendData

__all__ = [
    # Aggregator
    "AggregatedStatistics",
    "ArchitectureSourceInfo",
    "FailureInfo",
    "GeneratedAppInfo",
    "PassingInfo",
    "ResultsAggregator",
    "TerraformCodeInfo",
    # Trends
    "RunSummary",
    "TrendAnalyzer",
    "TrendData",
    # Site
    "SiteGenerator",
    # Downloads
    "AppDownloadGenerator",
    # Issues
    "FailureTrackerManager",
    "GitHubIssueManager",
    "IssueContentFormatter",
    "process_results_for_issues",
    # Notifications
    "SlackMessage",
    "SlackNotifier",
    "send_slack_notification",
]
