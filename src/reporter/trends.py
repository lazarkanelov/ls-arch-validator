"""Trend analysis for historical validation runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger("reporter.trends")


@dataclass
class RunSummary:
    """Summary of a single validation run for trend display."""

    id: str
    date: str
    total: int
    passed: int
    partial: int
    failed: int
    pass_rate: float
    duration_seconds: float
    duration_formatted: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "date": self.date,
            "total": self.total,
            "passed": self.passed,
            "partial": self.partial,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "duration_seconds": self.duration_seconds,
            "duration_formatted": self.duration_formatted,
        }


@dataclass
class TrendData:
    """Trend data for Chart.js display."""

    labels: list[str]
    pass_rates: list[float]
    totals: list[int]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "labels": self.labels,
            "pass_rates": self.pass_rates,
            "totals": self.totals,
        }


class TrendAnalyzer:
    """Analyzes trends across historical validation runs."""

    def __init__(self, data_dir: Path, days: int = 7) -> None:
        """
        Initialize the trend analyzer.

        Args:
            data_dir: Directory containing run data files
            days: Number of days to include in trends
        """
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.days = days
        self._runs: Optional[list[RunSummary]] = None

    def load_historical_runs(self) -> list[RunSummary]:
        """
        Load historical run summaries from data files.

        Returns:
            List of run summaries sorted by date descending
        """
        if self._runs is not None:
            return self._runs

        runs = []

        # Try to load from history.json first
        history_file = self.data_dir / "history.json"
        if history_file.exists():
            try:
                data = json.loads(history_file.read_text())
                for run_data in data.get("runs", []):
                    runs.append(
                        RunSummary(
                            id=run_data["id"],
                            date=run_data["date"],
                            total=run_data["total"],
                            passed=run_data["passed"],
                            partial=run_data.get("partial", 0),
                            failed=run_data["failed"],
                            pass_rate=run_data["pass_rate"],
                            duration_seconds=run_data.get("duration_seconds", 0),
                            duration_formatted=run_data.get("duration_formatted", ""),
                        )
                    )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("history_load_error", error=str(e))

        # Also scan runs directory for individual run files
        if self.runs_dir.exists():
            for run_file in self.runs_dir.glob("run-*.json"):
                try:
                    run_data = json.loads(run_file.read_text())
                    run_id = run_data.get("id", run_file.stem)

                    # Skip if already loaded from history.json
                    if any(r.id == run_id for r in runs):
                        continue

                    stats = run_data.get("statistics", {})
                    duration = stats.get("running_seconds", 0)

                    runs.append(
                        RunSummary(
                            id=run_id,
                            date=self._extract_date(run_id),
                            total=stats.get("total", 0),
                            passed=stats.get("passed", 0),
                            partial=stats.get("partial", 0),
                            failed=stats.get("failed", 0),
                            pass_rate=stats.get("pass_rate", 0),
                            duration_seconds=duration,
                            duration_formatted=self._format_duration(duration),
                        )
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(
                        "run_file_error",
                        file=str(run_file),
                        error=str(e),
                    )

        # Sort by date descending
        runs.sort(key=lambda r: r.date, reverse=True)

        # Limit to configured days
        runs = runs[: self.days]

        self._runs = runs
        logger.debug("historical_runs_loaded", count=len(runs))
        return runs

    def get_trend_data(self) -> TrendData:
        """
        Generate trend data for Chart.js.

        Returns:
            Trend data with labels, pass rates, and totals
        """
        runs = self.load_historical_runs()

        # Reverse for chronological order (oldest first)
        runs_chrono = list(reversed(runs))

        labels = []
        pass_rates = []
        totals = []

        for run in runs_chrono:
            # Format date label (e.g., "Dec 28")
            try:
                date = datetime.strptime(run.date, "%Y-%m-%d")
                labels.append(date.strftime("%b %d"))
            except ValueError:
                labels.append(run.date)

            pass_rates.append(round(run.pass_rate * 100, 1))
            totals.append(run.total)

        return TrendData(
            labels=labels,
            pass_rates=pass_rates,
            totals=totals,
        )

    def get_previous_pass_rate(self) -> Optional[float]:
        """
        Get the pass rate from the previous run.

        Returns:
            Previous pass rate or None if no previous run
        """
        runs = self.load_historical_runs()
        if len(runs) >= 2:
            return runs[1].pass_rate
        return None

    def get_run_history(self, limit: int = 7) -> list[RunSummary]:
        """
        Get recent run history for table display.

        Args:
            limit: Maximum number of runs to return

        Returns:
            List of run summaries
        """
        runs = self.load_historical_runs()
        return runs[:limit]

    def compute_pass_rate_change(self) -> Optional[float]:
        """
        Compute the change in pass rate from previous run.

        Returns:
            Change in pass rate (positive = improvement) or None
        """
        runs = self.load_historical_runs()
        if len(runs) >= 2:
            current = runs[0].pass_rate
            previous = runs[1].pass_rate
            return current - previous
        return None

    def add_run_to_history(self, run_summary: RunSummary) -> None:
        """
        Add a new run to the history file.

        Args:
            run_summary: The run summary to add
        """
        history_file = self.data_dir / "history.json"

        # Load existing history
        if history_file.exists():
            try:
                data = json.loads(history_file.read_text())
            except json.JSONDecodeError:
                data = {"runs": [], "trend": {"labels": [], "pass_rates": [], "totals": []}}
        else:
            data = {"runs": [], "trend": {"labels": [], "pass_rates": [], "totals": []}}

        # Add new run to the beginning
        runs = data.get("runs", [])
        runs.insert(0, run_summary.to_dict())

        # Keep only last N runs
        runs = runs[: self.days]
        data["runs"] = runs

        # Update trend data
        trend = self.get_trend_data()
        data["trend"] = trend.to_dict()

        # Write back
        self.data_dir.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps(data, indent=2))

        # Clear cache
        self._runs = None

        logger.info("run_added_to_history", run_id=run_summary.id)

    def to_dashboard_data(self) -> dict[str, Any]:
        """
        Generate trend data for dashboard template.

        Returns:
            Dictionary with trend_data and run_history
        """
        return {
            "trend_data": self.get_trend_data().to_dict(),
            "run_history": [r.to_dict() for r in self.get_run_history()],
        }

    @staticmethod
    def _extract_date(run_id: str) -> str:
        """Extract date from run ID (e.g., run-20241228-001 -> 2024-12-28)."""
        try:
            parts = run_id.split("-")
            if len(parts) >= 2:
                date_str = parts[1]
                if len(date_str) == 8:
                    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        except (IndexError, ValueError):
            pass
        return ""

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in seconds to human-readable string."""
        if seconds <= 0:
            return ""

        minutes = int(seconds // 60)
        secs = int(seconds % 60)

        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"
