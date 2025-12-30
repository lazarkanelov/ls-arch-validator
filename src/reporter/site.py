"""Static site generator for the dashboard."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import __version__
from src.models import Architecture, ValidationRun
from src.reporter.aggregator import ResultsAggregator
from src.reporter.downloads import AppDownloadGenerator
from src.reporter.trends import TrendAnalyzer
from src.utils.cache import AppCache
from src.utils.logging import get_logger

logger = get_logger("reporter.site")


class SiteGenerator:
    """Generates static HTML dashboard from validation results."""

    def __init__(
        self,
        templates_dir: Path,
        output_dir: Path,
        base_url: str = "",
    ) -> None:
        """
        Initialize the site generator.

        Args:
            templates_dir: Directory containing Jinja2 templates
            output_dir: Output directory for generated site
            base_url: Base URL for assets and links (e.g., "/dashboard")
        """
        self.templates_dir = Path(templates_dir)
        self.output_dir = Path(output_dir)
        self.base_url = base_url.rstrip("/")

        # Set up Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        run: Optional[ValidationRun] = None,
        data_dir: Optional[Path] = None,
        architectures: Optional[dict[str, Architecture]] = None,
        app_cache: Optional[AppCache] = None,
    ) -> Path:
        """
        Generate the static dashboard site.

        Args:
            run: ValidationRun to generate dashboard for (optional if using cached data)
            data_dir: Directory containing cached data files
            architectures: Dict of architecture_id -> Architecture objects
            app_cache: App cache for retrieving generated code

        Returns:
            Path to the generated index.html
        """
        # Debug: Log paths and parameters
        logger.info(
            "generate_called",
            output_dir=str(self.output_dir),
            output_dir_absolute=str(self.output_dir.resolve()),
            has_run=run is not None,
            has_data_dir=data_dir is not None,
            architectures_count=len(architectures) if architectures else 0,
            has_app_cache=app_cache is not None,
        )

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Copy static assets
        self._copy_assets()

        # Prepare data directory
        data_output_dir = self.output_dir / "data"
        data_output_dir.mkdir(parents=True, exist_ok=True)
        (data_output_dir / "runs").mkdir(parents=True, exist_ok=True)

        logger.info(
            "data_dir_created",
            data_dir=str(data_output_dir),
            data_dir_exists=data_output_dir.exists(),
            runs_dir_exists=(data_output_dir / "runs").exists(),
        )

        # Get dashboard data
        if run is not None:
            dashboard_data = self._prepare_data_from_run(
                run, data_output_dir, architectures, app_cache
            )
        elif data_dir is not None:
            dashboard_data = self._load_data_from_files(data_dir)
        else:
            # Try to load from output directory's data folder
            dashboard_data = self._load_data_from_files(data_output_dir)

        # Render dashboard
        index_path = self._render_dashboard(dashboard_data)

        logger.info(
            "site_generated",
            output_path=str(index_path),
            has_run=run is not None,
        )

        return index_path

    def _prepare_data_from_run(
        self,
        run: ValidationRun,
        data_output_dir: Path,
        architectures: Optional[dict[str, Architecture]] = None,
        app_cache: Optional[AppCache] = None,
    ) -> dict[str, Any]:
        """
        Prepare dashboard data from a validation run.

        Args:
            run: The validation run
            data_output_dir: Output directory for data files
            architectures: Dict of architecture_id -> Architecture objects
            app_cache: App cache for retrieving generated code

        Returns:
            Dashboard data dictionary
        """
        # Initialize trend analyzer
        trend_analyzer = TrendAnalyzer(data_output_dir)
        previous_pass_rate = trend_analyzer.get_previous_pass_rate()

        # Load app data from cache
        app_data: dict[str, dict] = {}
        if app_cache and architectures:
            for arch_id, arch in architectures.items():
                if arch.content_hash:
                    loaded = app_cache.load_app(arch.content_hash)
                    if loaded:
                        app_data[arch.content_hash] = loaded

        # Generate download files if we have architectures and app cache
        if architectures and app_cache:
            download_generator = AppDownloadGenerator(app_cache, self.output_dir)
            download_generator.generate_for_architectures(architectures)

        # Debug: Log architecture info
        if architectures:
            logger.info(
                "architectures_for_dashboard",
                count=len(architectures),
                sample_ids=list(architectures.keys())[:5],
            )
        else:
            logger.warning("no_architectures_for_dashboard")

        # Debug: Log result IDs
        if run.results:
            result_ids = [r.architecture_id for r in run.results[:5]]
            logger.info(
                "result_architecture_ids",
                count=len(run.results),
                sample_ids=result_ids,
            )

        # Aggregate results with architecture and app data
        aggregator = ResultsAggregator(run)
        dashboard_data = aggregator.to_dashboard_data(
            previous_pass_rate=previous_pass_rate,
            base_logs_url=f"{self.base_url}/data/runs",
            architectures=architectures,
            app_data=app_data,
            base_download_url=f"{self.base_url}/data/apps",
        )

        # Add trend data
        trend_data = trend_analyzer.to_dashboard_data()
        dashboard_data.update(trend_data)

        # Add run metadata
        dashboard_data["run_id"] = run.id
        dashboard_data["localstack_version"] = run.localstack_version

        # Save latest.json
        self._save_latest_json(run, dashboard_data, data_output_dir)

        # Save run data
        self._save_run_json(run, data_output_dir)

        # Update history
        self._update_history(run, trend_analyzer)

        return dashboard_data

    def _load_data_from_files(self, data_dir: Path) -> dict[str, Any]:
        """
        Load dashboard data from cached JSON files.

        Args:
            data_dir: Directory containing data files

        Returns:
            Dashboard data dictionary
        """
        data_dir = Path(data_dir)
        dashboard_data: dict[str, Any] = {}

        # Load latest.json
        latest_file = data_dir / "latest.json"
        if latest_file.exists():
            try:
                latest = json.loads(latest_file.read_text())
                dashboard_data["run_id"] = latest.get("id", "")
                dashboard_data["localstack_version"] = latest.get(
                    "localstack_version", ""
                )
                dashboard_data["statistics"] = latest.get("statistics", {})
                dashboard_data["template_count"] = latest.get("template_count", 0)
                dashboard_data["diagram_count"] = latest.get("diagram_count", 0)

                # Process results into failures and passing
                # Preserve enriched data (source_info, terraform_code, generated_app)
                results = latest.get("results", [])
                failures = []
                passing = []

                for result in results:
                    if result.get("status") in ("failed", "partial"):
                        failure = {
                            "architecture_id": result.get("architecture_id", ""),
                            "source_type": result.get("source_type", "template"),
                            "services": result.get("services", []),
                            "error_summary": result.get("error_summary", ""),
                            "infrastructure_error": result.get("infrastructure_error"),
                            "test_failures": result.get("test_failures", []),
                            "logs_url": result.get("logs_url"),
                            "issue_url": result.get("issue_url"),
                        }
                        # Preserve enriched architecture and app data
                        if result.get("source_info"):
                            failure["source_info"] = result["source_info"]
                        if result.get("terraform_code"):
                            failure["terraform_code"] = result["terraform_code"]
                        if result.get("generated_app"):
                            failure["generated_app"] = result["generated_app"]
                        failures.append(failure)
                    elif result.get("status") == "passed":
                        passing_item = {
                            "architecture_id": result.get("architecture_id", ""),
                            "source_type": result.get("source_type", "template"),
                            "services": result.get("services", []),
                        }
                        # Preserve enriched architecture and app data
                        if result.get("source_info"):
                            passing_item["source_info"] = result["source_info"]
                        if result.get("terraform_code"):
                            passing_item["terraform_code"] = result["terraform_code"]
                        if result.get("generated_app"):
                            passing_item["generated_app"] = result["generated_app"]
                        passing.append(passing_item)

                dashboard_data["failures"] = failures
                dashboard_data["passing"] = passing
                dashboard_data["service_coverage"] = latest.get("service_coverage", [])
                dashboard_data["unsupported_services"] = latest.get(
                    "unsupported_services", []
                )

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("latest_load_error", error=str(e))

        # Load history.json for trends
        history_file = data_dir / "history.json"
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text())
                dashboard_data["trend_data"] = history.get("trend", {})
                dashboard_data["run_history"] = history.get("runs", [])
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("history_load_error", error=str(e))

        return dashboard_data

    def _render_dashboard(self, data: dict[str, Any]) -> Path:
        """
        Render the dashboard HTML.

        Args:
            data: Dashboard data dictionary

        Returns:
            Path to rendered index.html
        """
        template = self.env.get_template("index.html")

        # Prepare context
        context = {
            "base_url": self.base_url,
            "version": __version__,
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            **data,
        }

        # Render template
        html = template.render(**context)

        # Write output
        index_path = self.output_dir / "index.html"
        index_path.write_text(html)

        return index_path

    def _copy_assets(self) -> None:
        """Copy static assets to output directory."""
        assets_src = self.output_dir / "assets"
        if not assets_src.exists():
            assets_src.mkdir(parents=True, exist_ok=True)

        # Check if templates have assets
        template_assets = self.templates_dir.parent / "docs" / "assets"
        if template_assets.exists():
            for asset in template_assets.iterdir():
                if asset.is_file():
                    dest = assets_src / asset.name
                    if not dest.exists():
                        shutil.copy2(asset, dest)

    def _save_latest_json(
        self,
        run: ValidationRun,
        dashboard_data: dict[str, Any],
        data_dir: Path,
    ) -> None:
        """
        Save latest.json with full run data.

        Args:
            run: The validation run
            dashboard_data: Aggregated dashboard data
            data_dir: Output directory for data files
        """
        # Combine enriched failures and passing data into results
        # This preserves source_info, terraform_code, and generated_app
        enriched_results = []

        # Debug: Check if dashboard_data has enriched info
        failures = dashboard_data.get("failures", [])
        passing = dashboard_data.get("passing", [])
        failures_with_source = sum(1 for f in failures if f.get("source_info"))
        passing_with_source = sum(1 for p in passing if p.get("source_info"))
        logger.info(
            "enriched_data_check",
            total_failures=len(failures),
            failures_with_source_info=failures_with_source,
            total_passing=len(passing),
            passing_with_source_info=passing_with_source,
        )

        # Add failures with status
        for failure in failures:
            result = dict(failure)  # Copy the enriched data
            result["status"] = "failed"
            if not result.get("infrastructure_error") and result.get("test_failures"):
                result["status"] = "partial"
            enriched_results.append(result)

        # Add passing results
        for passing in dashboard_data.get("passing", []):
            result = dict(passing)
            result["status"] = "passed"
            enriched_results.append(result)

        latest = {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "localstack_version": run.localstack_version,
            "statistics": dashboard_data.get("statistics", {}),
            "template_count": dashboard_data.get("template_count", 0),
            "diagram_count": dashboard_data.get("diagram_count", 0),
            "results": enriched_results,
            "service_coverage": dashboard_data.get("service_coverage", []),
            "unsupported_services": dashboard_data.get("unsupported_services", []),
        }

        latest_file = data_dir / "latest.json"
        latest_file.write_text(json.dumps(latest, indent=2, default=str))
        logger.info(
            "latest_json_saved",
            path=str(latest_file),
            file_exists=latest_file.exists(),
            file_size=latest_file.stat().st_size if latest_file.exists() else 0,
            results_count=len(enriched_results),
        )

    def _save_run_json(self, run: ValidationRun, data_dir: Path) -> None:
        """
        Save individual run data to runs directory.

        Args:
            run: The validation run
            data_dir: Output directory for data files
        """
        runs_dir = data_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        run_file = runs_dir / f"{run.id}.json"
        run_file.write_text(json.dumps(run.to_dict(), indent=2, default=str))
        logger.debug("run_json_saved", path=str(run_file))

    def _update_history(
        self,
        run: ValidationRun,
        trend_analyzer: TrendAnalyzer,
    ) -> None:
        """
        Update history.json with new run.

        Args:
            run: The validation run
            trend_analyzer: Trend analyzer instance
        """
        from src.reporter.trends import RunSummary

        stats = run.statistics
        duration = (
            stats.mining_seconds
            + stats.generation_seconds
            + stats.running_seconds
            + stats.reporting_seconds
        ) if stats else 0

        summary = RunSummary(
            id=run.id,
            date=run.started_at.strftime("%Y-%m-%d") if run.started_at else "",
            total=stats.total if stats else 0,
            passed=stats.passed if stats else 0,
            partial=stats.partial if stats else 0,
            failed=stats.failed if stats else 0,
            pass_rate=stats.pass_rate if stats else 0,
            duration_seconds=duration,
            duration_formatted=TrendAnalyzer._format_duration(duration),
        )

        trend_analyzer.add_run_to_history(summary)

    def list_run_archives(self) -> list[dict[str, str]]:
        """
        List available run archives.

        Returns:
            List of run archive info dicts
        """
        runs_dir = self.output_dir / "data" / "runs"
        archives = []

        if runs_dir.exists():
            for run_file in sorted(runs_dir.glob("run-*.json"), reverse=True):
                try:
                    data = json.loads(run_file.read_text())
                    archives.append({
                        "id": data.get("id", run_file.stem),
                        "file": run_file.name,
                        "url": f"{self.base_url}/data/runs/{run_file.name}",
                    })
                except json.JSONDecodeError:
                    pass

        return archives
