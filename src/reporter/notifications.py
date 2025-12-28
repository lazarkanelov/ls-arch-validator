"""Notification services for validation results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from src.models import RunStatistics, ValidationRun
from src.utils.logging import get_logger

logger = get_logger("reporter.notifications")


@dataclass
class SlackMessage:
    """A Slack message payload."""

    text: str
    color: str = "good"  # good, warning, danger
    title: Optional[str] = None
    title_link: Optional[str] = None
    fields: list[dict] = None

    def to_dict(self) -> dict:
        """Convert to Slack API format."""
        attachment = {
            "color": self.color,
            "text": self.text,
        }

        if self.title:
            attachment["title"] = self.title

        if self.title_link:
            attachment["title_link"] = self.title_link

        if self.fields:
            attachment["fields"] = self.fields

        return {"attachments": [attachment]}


class SlackNotifier:
    """
    Sends notifications to Slack via webhook.

    Implements FR-047: Optional Slack notifications.
    """

    def __init__(self, webhook_url: str) -> None:
        """
        Initialize the notifier.

        Args:
            webhook_url: Slack incoming webhook URL
        """
        self.webhook_url = webhook_url

    def send(self, message: SlackMessage) -> bool:
        """
        Send a message to Slack.

        Args:
            message: Message to send

        Returns:
            True if sent successfully
        """
        try:
            payload = json.dumps(message.to_dict()).encode("utf-8")

            request = Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )

            with urlopen(request, timeout=10) as response:
                if response.status == 200:
                    logger.debug("slack_message_sent")
                    return True

            logger.warning("slack_send_failed", status=response.status)
            return False

        except URLError as e:
            logger.error("slack_error", error=str(e))
            return False

    def notify_run_complete(
        self,
        run: ValidationRun,
        dashboard_url: str = "",
    ) -> bool:
        """
        Send notification for completed run.

        Args:
            run: Completed validation run
            dashboard_url: URL to dashboard

        Returns:
            True if sent successfully
        """
        stats = run.statistics

        # Determine color based on results
        if stats and stats.pass_rate >= 0.9:
            color = "good"
        elif stats and stats.pass_rate >= 0.5:
            color = "warning"
        else:
            color = "danger"

        # Build fields
        fields = []
        if stats:
            fields.extend([
                {"title": "Passed", "value": str(stats.passed), "short": True},
                {"title": "Failed", "value": str(stats.failed), "short": True},
                {"title": "Pass Rate", "value": f"{stats.pass_rate:.1%}", "short": True},
                {"title": "Total", "value": str(stats.total_architectures), "short": True},
            ])

        if run.timing:
            fields.append({
                "title": "Duration",
                "value": f"{run.timing.total_seconds:.1f}s",
                "short": True,
            })

        message = SlackMessage(
            text=f"Validation run `{run.id}` completed with status: {run.status}",
            color=color,
            title="LocalStack Architecture Validation",
            title_link=dashboard_url if dashboard_url else None,
            fields=fields,
        )

        return self.send(message)


def send_slack_notification(
    webhook_url: Optional[str],
    run: ValidationRun,
    dashboard_url: str = "",
) -> bool:
    """
    Send Slack notification if webhook is configured.

    Args:
        webhook_url: Slack webhook URL (None to skip)
        run: Completed validation run
        dashboard_url: URL to dashboard

    Returns:
        True if sent (or skipped because not configured)
    """
    if not webhook_url:
        logger.debug("slack_not_configured")
        return True

    notifier = SlackNotifier(webhook_url)
    return notifier.notify_run_complete(run, dashboard_url)
