"""Architecture registry tracker for cumulative discovery and testing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger("registry.tracker")


@dataclass
class TestRecord:
    """Record of a single test run for an architecture."""

    run_id: str
    date: str
    status: str  # passed, partial, failed, error
    passed_tests: int = 0
    failed_tests: int = 0
    error_summary: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "date": self.date,
            "status": self.status,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "error_summary": self.error_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TestRecord:
        return cls(
            run_id=data["run_id"],
            date=data["date"],
            status=data["status"],
            passed_tests=data.get("passed_tests", 0),
            failed_tests=data.get("failed_tests", 0),
            error_summary=data.get("error_summary"),
        )


@dataclass
class ArchitectureRecord:
    """Record of a discovered architecture with test history."""

    arch_id: str
    source_name: str
    source_url: Optional[str] = None
    services: list[str] = field(default_factory=list)
    first_discovered: str = ""
    last_tested: Optional[str] = None
    current_status: str = "untested"
    test_history: list[TestRecord] = field(default_factory=list)
    content_hash: Optional[str] = None

    def __post_init__(self):
        if not self.first_discovered:
            self.first_discovered = datetime.utcnow().strftime("%Y-%m-%d")

    def add_test_result(
        self,
        run_id: str,
        status: str,
        passed_tests: int = 0,
        failed_tests: int = 0,
        error_summary: Optional[str] = None,
    ) -> None:
        """Add a test result to history."""
        record = TestRecord(
            run_id=run_id,
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            status=status,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            error_summary=error_summary,
        )
        self.test_history.append(record)
        self.last_tested = record.date
        self.current_status = status

    def days_since_last_test(self) -> Optional[int]:
        """Get days since last test, or None if never tested."""
        if not self.last_tested:
            return None
        last = datetime.strptime(self.last_tested, "%Y-%m-%d")
        return (datetime.utcnow() - last).days

    def needs_retest(self, max_age_days: int = 7) -> bool:
        """Check if architecture needs retesting."""
        days = self.days_since_last_test()
        if days is None:
            return True
        return days >= max_age_days

    def to_dict(self) -> dict:
        return {
            "arch_id": self.arch_id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "services": self.services,
            "first_discovered": self.first_discovered,
            "last_tested": self.last_tested,
            "current_status": self.current_status,
            "content_hash": self.content_hash,
            "test_history": [t.to_dict() for t in self.test_history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArchitectureRecord:
        record = cls(
            arch_id=data["arch_id"],
            source_name=data["source_name"],
            source_url=data.get("source_url"),
            services=data.get("services", []),
            first_discovered=data.get("first_discovered", ""),
            last_tested=data.get("last_tested"),
            current_status=data.get("current_status", "untested"),
            content_hash=data.get("content_hash"),
        )
        record.test_history = [
            TestRecord.from_dict(t) for t in data.get("test_history", [])
        ]
        return record


@dataclass
class RegistryStats:
    """Statistics about the architecture registry."""

    total_architectures: int = 0
    tested_architectures: int = 0
    untested_architectures: int = 0
    passing: int = 0
    partial: int = 0
    failing: int = 0
    errors: int = 0
    new_this_week: int = 0
    new_today: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    services_coverage: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_architectures": self.total_architectures,
            "tested_architectures": self.tested_architectures,
            "untested_architectures": self.untested_architectures,
            "passing": self.passing,
            "partial": self.partial,
            "failing": self.failing,
            "errors": self.errors,
            "new_this_week": self.new_this_week,
            "new_today": self.new_today,
            "sources": self.sources,
            "services_coverage": self.services_coverage,
        }


class ArchitectureRegistry:
    """
    Registry for tracking discovered architectures over time.

    Provides:
    - Cumulative storage of all discovered architectures
    - Test history for each architecture
    - Incremental discovery (only add new)
    - Growth metrics and trends
    """

    def __init__(self, data_dir: Path) -> None:
        """
        Initialize the registry.

        Args:
            data_dir: Directory for storing registry data
        """
        self.data_dir = Path(data_dir)
        self.registry_file = self.data_dir / "registry.json"
        self._architectures: dict[str, ArchitectureRecord] = {}
        self._load()

    def _load(self) -> None:
        """Load registry from file."""
        if not self.registry_file.exists():
            logger.info("registry_not_found", path=str(self.registry_file))
            return

        try:
            data = json.loads(self.registry_file.read_text())
            for arch_data in data.get("architectures", []):
                record = ArchitectureRecord.from_dict(arch_data)
                self._architectures[record.arch_id] = record

            logger.info(
                "registry_loaded",
                architectures=len(self._architectures),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("registry_load_failed", error=str(e))

    def save(self) -> None:
        """Save registry to file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "updated_at": datetime.utcnow().isoformat(),
            "total_architectures": len(self._architectures),
            "architectures": [
                arch.to_dict() for arch in self._architectures.values()
            ],
        }

        self.registry_file.write_text(json.dumps(data, indent=2))
        logger.debug("registry_saved", architectures=len(self._architectures))

    def register(
        self,
        arch_id: str,
        source_name: str,
        source_url: Optional[str] = None,
        services: Optional[list[str]] = None,
        content_hash: Optional[str] = None,
    ) -> tuple[ArchitectureRecord, bool]:
        """
        Register an architecture (add if new, return existing if known).

        Args:
            arch_id: Architecture identifier
            source_name: Source name (e.g., 'terraform-registry')
            source_url: URL to source
            services: List of AWS services used
            content_hash: Content hash for deduplication

        Returns:
            Tuple of (ArchitectureRecord, is_new)
        """
        if arch_id in self._architectures:
            return self._architectures[arch_id], False

        record = ArchitectureRecord(
            arch_id=arch_id,
            source_name=source_name,
            source_url=source_url,
            services=services or [],
            content_hash=content_hash,
        )
        self._architectures[arch_id] = record

        logger.info(
            "architecture_registered",
            arch_id=arch_id,
            source=source_name,
        )

        return record, True

    def get(self, arch_id: str) -> Optional[ArchitectureRecord]:
        """Get architecture record by ID."""
        return self._architectures.get(arch_id)

    def exists(self, arch_id: str) -> bool:
        """Check if architecture is already registered."""
        return arch_id in self._architectures

    def record_test_result(
        self,
        arch_id: str,
        run_id: str,
        status: str,
        passed_tests: int = 0,
        failed_tests: int = 0,
        error_summary: Optional[str] = None,
    ) -> None:
        """Record a test result for an architecture."""
        record = self._architectures.get(arch_id)
        if not record:
            logger.warning("architecture_not_found", arch_id=arch_id)
            return

        record.add_test_result(
            run_id=run_id,
            status=status,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            error_summary=error_summary,
        )

    def get_untested(self) -> list[ArchitectureRecord]:
        """Get all untested architectures."""
        return [
            arch for arch in self._architectures.values()
            if arch.current_status == "untested"
        ]

    def get_needing_retest(self, max_age_days: int = 7) -> list[ArchitectureRecord]:
        """Get architectures that need retesting."""
        return [
            arch for arch in self._architectures.values()
            if arch.needs_retest(max_age_days)
        ]

    def get_by_status(self, status: str) -> list[ArchitectureRecord]:
        """Get architectures by current status."""
        return [
            arch for arch in self._architectures.values()
            if arch.current_status == status
        ]

    def get_new_since(self, days: int) -> list[ArchitectureRecord]:
        """Get architectures discovered in the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        return [
            arch for arch in self._architectures.values()
            if arch.first_discovered >= cutoff
        ]

    def get_all(self) -> list[ArchitectureRecord]:
        """Get all registered architectures."""
        return list(self._architectures.values())

    def get_stats(self) -> RegistryStats:
        """Get registry statistics."""
        stats = RegistryStats()
        stats.total_architectures = len(self._architectures)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        for arch in self._architectures.values():
            # Count by status
            if arch.current_status == "untested":
                stats.untested_architectures += 1
            else:
                stats.tested_architectures += 1
                if arch.current_status == "passed":
                    stats.passing += 1
                elif arch.current_status == "partial":
                    stats.partial += 1
                elif arch.current_status == "failed":
                    stats.failing += 1
                elif arch.current_status == "error":
                    stats.errors += 1

            # Count new architectures
            if arch.first_discovered == today:
                stats.new_today += 1
            if arch.first_discovered >= week_ago:
                stats.new_this_week += 1

            # Count by source
            source = arch.source_name
            stats.sources[source] = stats.sources.get(source, 0) + 1

            # Count services
            for service in arch.services:
                if service not in stats.services_coverage:
                    stats.services_coverage[service] = {
                        "total": 0,
                        "passing": 0,
                        "failing": 0,
                    }
                stats.services_coverage[service]["total"] += 1
                if arch.current_status == "passed":
                    stats.services_coverage[service]["passing"] += 1
                elif arch.current_status in ("failed", "partial"):
                    stats.services_coverage[service]["failing"] += 1

        return stats

    def get_growth_data(self, days: int = 30) -> list[dict]:
        """
        Get architecture discovery growth over time.

        Args:
            days: Number of days to include

        Returns:
            List of {date, total, new} dicts
        """
        # Count architectures by discovery date
        by_date: dict[str, int] = {}
        for arch in self._architectures.values():
            date = arch.first_discovered
            by_date[date] = by_date.get(date, 0) + 1

        # Build cumulative data
        start_date = datetime.utcnow() - timedelta(days=days)
        result = []
        cumulative = 0

        # Count architectures before start date
        for arch in self._architectures.values():
            if arch.first_discovered < start_date.strftime("%Y-%m-%d"):
                cumulative += 1

        # Build daily data
        for i in range(days + 1):
            date = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            new_count = by_date.get(date, 0)
            cumulative += new_count
            result.append({
                "date": date,
                "total": cumulative,
                "new": new_count,
            })

        return result

    def get_weekly_summary(self) -> dict:
        """
        Get weekly summary for team review.

        Returns:
            Summary dict with key metrics and action items
        """
        stats = self.get_stats()
        new_this_week = self.get_new_since(7)
        failing = self.get_by_status("failed")
        partial = self.get_by_status("partial")

        # Group failures by service
        failing_services: dict[str, list[str]] = {}
        for arch in failing + partial:
            for service in arch.services:
                if service not in failing_services:
                    failing_services[service] = []
                failing_services[service].append(arch.arch_id)

        # Sort by most failures
        priority_services = sorted(
            failing_services.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:10]

        return {
            "period": {
                "start": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "end": datetime.utcnow().strftime("%Y-%m-%d"),
            },
            "summary": {
                "total_architectures": stats.total_architectures,
                "tested": stats.tested_architectures,
                "passing": stats.passing,
                "partial": stats.partial,
                "failing": stats.failing,
                "pass_rate": (
                    (stats.passing / stats.tested_architectures * 100)
                    if stats.tested_architectures > 0
                    else 0
                ),
            },
            "growth": {
                "new_this_week": len(new_this_week),
                "new_architectures": [
                    {"id": a.arch_id, "source": a.source_name}
                    for a in new_this_week[:10]
                ],
            },
            "action_items": {
                "priority_services": [
                    {"service": s, "failing_count": len(archs), "architectures": archs[:5]}
                    for s, archs in priority_services
                ],
                "top_failures": [
                    {
                        "arch_id": a.arch_id,
                        "services": a.services,
                        "error": a.test_history[-1].error_summary if a.test_history else None,
                    }
                    for a in (failing + partial)[:10]
                ],
            },
        }
