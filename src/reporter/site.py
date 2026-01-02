"""Static site generator for the dashboard."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from src import __version__
from src.models import Architecture, ValidationRun
from src.reporter.aggregator import ResultsAggregator
from src.reporter.downloads import AppDownloadGenerator
from src.reporter.storage import IndexBuilder, ObjectStore
from src.reporter.trends import TrendAnalyzer
from src.utils.atomic import atomic_write_json, atomic_write_text
from src.utils.cache import AppCache
from src.utils.logging import get_logger
from src.utils.result import DashboardError, Err, Ok, Result

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
    ) -> Result[Path, DashboardError]:
        """
        Generate the static dashboard site.

        Args:
            run: ValidationRun to generate dashboard for (optional if using cached data)
            data_dir: Directory containing cached data files
            architectures: Dict of architecture_id -> Architecture objects
            app_cache: App cache for retrieving generated code

        Returns:
            Result with path to generated index.html or DashboardError
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
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return Err(DashboardError(
                phase="setup",
                message=f"Cannot create output directory: {self.output_dir}",
                cause=e,
            ))

        # Copy static assets
        self._copy_assets()

        # Prepare data directory
        data_output_dir = self.output_dir / "data"
        try:
            data_output_dir.mkdir(parents=True, exist_ok=True)
            (data_output_dir / "runs").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return Err(DashboardError(
                phase="setup",
                message=f"Cannot create data directory: {data_output_dir}",
                cause=e,
            ))

        logger.info(
            "data_dir_created",
            data_dir=str(data_output_dir),
            data_dir_exists=data_output_dir.exists(),
            runs_dir_exists=(data_output_dir / "runs").exists(),
        )

        # Get dashboard data
        try:
            if run is not None:
                dashboard_data = self._prepare_data_from_run(
                    run, data_output_dir, architectures, app_cache
                )
            elif data_dir is not None:
                dashboard_data = self._load_data_from_files(data_dir)
            else:
                # Try to load from output directory's data folder
                dashboard_data = self._load_data_from_files(data_output_dir)
        except Exception as e:
            logger.error("dashboard_data_preparation_failed", error=str(e))
            return Err(DashboardError(
                phase="data_preparation",
                message="Failed to prepare dashboard data",
                cause=e,
            ))

        # Render dashboard
        render_result = self._render_dashboard_safe(dashboard_data)
        if render_result.is_err():
            return render_result

        index_path = render_result.unwrap()

        logger.info(
            "site_generated",
            output_path=str(index_path),
            has_run=run is not None,
        )

        return Ok(index_path)

    def generate_legacy(
        self,
        run: Optional[ValidationRun] = None,
        data_dir: Optional[Path] = None,
        architectures: Optional[dict[str, Architecture]] = None,
        app_cache: Optional[AppCache] = None,
    ) -> Path:
        """
        Legacy generate method for backward compatibility.

        Calls generate() and unwraps the result, creating a fallback page on error.
        """
        result = self.generate(run, data_dir, architectures, app_cache)

        if result.is_ok():
            return result.unwrap()
        else:
            error = result.unwrap_err()
            logger.error("dashboard_generation_failed", error=str(error))
            return self._create_fallback_page(str(error))

    def _create_fallback_page(self, error_message: str) -> Path:
        """Create a minimal fallback page when generation fails."""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>LocalStack Architecture Validator - Error</title>
    <style>
        body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }}
        .container {{ max-width: 600px; margin: 0 auto; text-align: center; }}
        h1 {{ color: #f87171; }}
        .error {{ background: #1e293b; padding: 1rem; border-radius: 0.5rem; margin: 1rem 0; }}
        code {{ font-size: 0.9rem; color: #94a3b8; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Dashboard Generation Error</h1>
        <p>The validation pipeline ran but failed to generate the dashboard.</p>
        <div class="error">
            <code>{error_message}</code>
        </div>
        <p>Check the workflow logs for more details.</p>
    </div>
</body>
</html>"""
        index_path = self.output_dir / "index.html"
        index_path.write_text(html)
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

        Supports both legacy (latest.json) and CAS (index.json) formats.

        Args:
            data_dir: Directory containing data files

        Returns:
            Dashboard data dictionary
        """
        data_dir = Path(data_dir)
        dashboard_data: dict[str, Any] = {}

        # Try CAS format first (index.json)
        index_file = data_dir / "index.json"
        if index_file.exists():
            try:
                index_data = json.loads(index_file.read_text())

                # Map CAS format to dashboard format
                dashboard_data["run_id"] = index_data.get("latest_run", "")
                dashboard_data["localstack_version"] = ""  # Not in index.json
                dashboard_data["statistics"] = index_data.get("statistics", {})
                dashboard_data["template_count"] = index_data.get("statistics", {}).get("total", 0)
                dashboard_data["diagram_count"] = 0

                # Process results into failures and passing
                results = index_data.get("results", [])
                failures = []
                passing = []

                for result in results:
                    item = {
                        "architecture_id": result.get("arch_id", ""),
                        "services": result.get("services", []),
                        "arch_hash": result.get("arch_hash"),
                        "tf_hash": result.get("tf_hash"),
                        "app_hashes": result.get("app_hashes", []),
                        "error_summary": result.get("error_summary"),
                        "test_failures": result.get("test_failures", []),
                    }

                    if result.get("status") in ("failed", "partial"):
                        failures.append(item)
                    elif result.get("status") == "passed":
                        passing.append(item)

                dashboard_data["failures"] = failures
                dashboard_data["passing"] = passing
                dashboard_data["service_coverage"] = index_data.get("service_summary", [])
                dashboard_data["use_lazy_loading"] = True

                logger.info("loaded_from_cas_index", results_count=len(results))
                return dashboard_data

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("index_load_error", error=str(e))

        # Fall back to legacy format (latest.json)
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

        # Load registry.json for cumulative tracking
        registry_file = data_dir / "registry.json"
        if registry_file.exists():
            try:
                registry = json.loads(registry_file.read_text())
                dashboard_data["registry_stats"] = registry.get("stats", {})
                dashboard_data["weekly_summary"] = registry.get("weekly_summary", {})
                dashboard_data["growth_data"] = registry.get("growth_data", [])
                logger.info("registry_data_loaded")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("registry_load_error", error=str(e))

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

        # Calculate report period (week containing the run)
        now = datetime.utcnow()
        week_start = now - timedelta(days=now.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday
        report_period = {
            "start": week_start.strftime("%B %d, %Y"),
            "end": week_end.strftime("%B %d, %Y"),
        }

        # Prepare context
        context = {
            "base_url": self.base_url,
            "version": __version__,
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "latest_run_id": data.get("run_id", ""),
            "report_period": report_period,
            **data,
        }

        # Render template
        html = template.render(**context)

        # Write output
        index_path = self.output_dir / "index.html"
        index_path.write_text(html)

        return index_path

    def _render_dashboard_safe(self, data: dict[str, Any]) -> Result[Path, DashboardError]:
        """
        Render the dashboard HTML with explicit error handling.

        Uses atomic writes to prevent partial/corrupt output.

        Args:
            data: Dashboard data dictionary

        Returns:
            Result with path to rendered index.html or DashboardError
        """
        # Load template
        try:
            template = self.env.get_template("index.html")
        except TemplateNotFound:
            return Err(DashboardError(
                phase="template_loading",
                message="Template 'index.html' not found",
            ))
        except Exception as e:
            return Err(DashboardError(
                phase="template_loading",
                message="Failed to load template",
                cause=e,
            ))

        # Calculate report period (week containing the run)
        now = datetime.utcnow()
        week_start = now - timedelta(days=now.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday
        report_period = {
            "start": week_start.strftime("%B %d, %Y"),
            "end": week_end.strftime("%B %d, %Y"),
        }

        # Prepare context
        context = {
            "base_url": self.base_url,
            "version": __version__,
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "latest_run_id": data.get("run_id", ""),
            "report_period": report_period,
            **data,
        }

        # Render template
        try:
            html = template.render(**context)
        except Exception as e:
            return Err(DashboardError(
                phase="rendering",
                message="Failed to render template",
                cause=e,
            ))

        # Validate rendered content
        if not html or len(html) < 100:
            return Err(DashboardError(
                phase="validation",
                message=f"Rendered HTML is too short ({len(html)} bytes), likely failed",
            ))

        if "<!DOCTYPE html>" not in html and "<html" not in html.lower():
            return Err(DashboardError(
                phase="validation",
                message="Rendered content does not appear to be valid HTML",
            ))

        # Write output atomically
        index_path = self.output_dir / "index.html"
        try:
            atomic_write_text(index_path, html)
        except Exception as e:
            return Err(DashboardError(
                phase="writing",
                message=f"Failed to write index.html to {index_path}",
                cause=e,
            ))

        logger.info(
            "dashboard_rendered",
            path=str(index_path),
            size_bytes=len(html),
        )

        return Ok(index_path)

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
        # Calculate duration from run times if available
        duration = 0
        if run.started_at and run.completed_at:
            duration = (run.completed_at - run.started_at).total_seconds()

        summary = RunSummary(
            id=run.id,
            date=run.started_at.strftime("%Y-%m-%d") if run.started_at else "",
            total=getattr(stats, 'total_architectures', 0) if stats else 0,
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

    def generate_cas(
        self,
        run: ValidationRun,
        architectures: dict[str, Architecture],
        app_cache: Optional[AppCache] = None,
    ) -> Path:
        """
        Generate dashboard using Content-Addressable Storage format.

        This is the new storage format that:
        - Stores objects by content hash (deduplication)
        - Creates lightweight index.json (~3KB vs 127KB)
        - Supports lazy loading of details

        Args:
            run: ValidationRun to generate dashboard for
            architectures: Dict of architecture_id -> Architecture objects
            app_cache: App cache for retrieving generated code

        Returns:
            Path to the generated index.json
        """
        logger.info(
            "generate_cas_started",
            run_id=run.id,
            architecture_count=len(architectures),
        )

        # Ensure output directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        data_dir = self.output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize object store
        store = ObjectStore(data_dir)
        builder = IndexBuilder(store)

        # Load app data from cache
        app_data: dict[str, dict] = {}
        if app_cache:
            for arch_id, arch in architectures.items():
                if arch.content_hash:
                    loaded = app_cache.load_app(arch.content_hash)
                    if loaded:
                        app_data[arch.content_hash] = loaded

        # Build result refs
        results = []
        for arch_result in run.results:
            arch = architectures.get(arch_result.architecture_id)
            if not arch:
                continue

            # Get terraform code
            terraform_code = None
            if hasattr(arch, "terraform") and arch.terraform:
                terraform_code = {
                    "main_tf": arch.terraform.main_tf,
                    "variables_tf": getattr(arch.terraform, "variables_tf", None),
                    "outputs_tf": getattr(arch.terraform, "outputs_tf", None),
                }

            # Get generated apps from cache
            generated_apps = []
            if arch.content_hash and arch.content_hash in app_data:
                cached_app = app_data[arch.content_hash]
                # Support both single app and multiple apps
                if isinstance(cached_app.get("apps"), list):
                    generated_apps = cached_app["apps"]
                elif cached_app.get("source_files"):
                    generated_apps = [cached_app]

            # Get source info
            source_info = None
            if hasattr(arch, "source_info") and arch.source_info:
                source_info = (
                    arch.source_info
                    if isinstance(arch.source_info, dict)
                    else arch.source_info.__dict__
                )

            # Build result with refs
            result_ref = builder.build_result_ref(
                arch_id=arch_result.architecture_id,
                services=list(arch.services) if arch.services else [],
                source_info=source_info,
                terraform_code=terraform_code,
                generated_apps=generated_apps,
                status=arch_result.status,
                error_summary=arch_result.error_summary if hasattr(arch_result, "error_summary") else None,
                test_failures=arch_result.failed_tests if hasattr(arch_result, "failed_tests") else None,
            )
            results.append(result_ref)

            # Also store per-architecture result
            store.put_result(
                run_id=run.id,
                arch_hash=result_ref["arch_hash"],
                status=arch_result.status,
                error_summary=result_ref.get("error_summary"),
                test_results=[
                    {"name": t, "status": "failed"}
                    for t in (result_ref.get("test_failures") or [])
                ],
            )

        # Calculate statistics
        stats = run.statistics
        statistics = {
            "total": stats.total if stats else len(results),
            "passed": stats.passed if stats else 0,
            "partial": stats.partial if stats else 0,
            "failed": stats.failed if stats else 0,
            "pass_rate": stats.pass_rate if stats else 0,
        }

        # Get service coverage
        service_counts: dict[str, dict] = {}
        for result in results:
            for service in result.get("services", []):
                if service not in service_counts:
                    service_counts[service] = {"total": 0, "passed": 0}
                service_counts[service]["total"] += 1
                if result["status"] == "passed":
                    service_counts[service]["passed"] += 1

        service_coverage = [
            {
                "name": name,
                "total": counts["total"],
                "passed": counts["passed"],
                "pass_rate": (counts["passed"] / counts["total"] * 100) if counts["total"] > 0 else 0,
            }
            for name, counts in sorted(service_counts.items())
        ]

        # Build index
        index_data = builder.build_index(
            run_id=run.id,
            statistics=statistics,
            results=results,
            service_coverage=service_coverage,
            recent_runs=[],  # TODO: Load from history
        )

        # Save index
        index_path = builder.save_index(index_data)

        # Save run manifest
        store.put_run(
            run_id=run.id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status,
            localstack_version=run.localstack_version,
            statistics=statistics,
            architecture_refs=[r["arch_hash"] for r in results],
        )

        # Copy assets and render dashboard
        self._copy_assets()
        self._render_dashboard_v2(index_data)

        logger.info(
            "generate_cas_completed",
            index_path=str(index_path),
            object_stats=store.get_stats(),
        )

        return index_path

    def _render_dashboard_v2(self, index_data: dict[str, Any]) -> Path:
        """
        Render dashboard HTML for CAS format.

        Uses index.json data with lazy loading for details.

        Args:
            index_data: Index data from IndexBuilder

        Returns:
            Path to rendered index.html
        """
        template = self.env.get_template("index.html")

        # Transform index data for template
        # The template expects failures/passing lists, we provide results
        failures = []
        passing = []

        for result in index_data.get("results", []):
            item = {
                "architecture_id": result["arch_id"],
                "services": result["services"],
                "arch_hash": result["arch_hash"],
                "tf_hash": result.get("tf_hash"),
                "app_hashes": result.get("app_hashes", []),
                "error_summary": result.get("error_summary"),
                "test_failures": result.get("test_failures"),
            }

            if result["status"] in ("failed", "partial"):
                failures.append(item)
            else:
                passing.append(item)

        # Calculate report period (week containing the run)
        now = datetime.utcnow()
        week_start = now - timedelta(days=now.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday
        report_period = {
            "start": week_start.strftime("%B %d, %Y"),
            "end": week_end.strftime("%B %d, %Y"),
        }

        context = {
            "base_url": self.base_url,
            "version": __version__,
            "last_updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "run_id": index_data.get("latest_run", ""),
            "latest_run_id": index_data.get("latest_run", ""),
            "report_period": report_period,
            "statistics": index_data.get("statistics", {}),
            "failures": failures,
            "passing": passing,
            "service_coverage": index_data.get("service_summary", []),
            "use_lazy_loading": True,  # Flag for template to use lazy loading
        }

        html = template.render(**context)
        index_path = self.output_dir / "index.html"
        index_path.write_text(html)

        return index_path
