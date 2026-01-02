"""CLI entry point for ls-arch-validator."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from src import __version__
from src.utils.logging import configure_logging, get_logger

# Default paths
DEFAULT_CONFIG = "./config"
DEFAULT_CACHE = "./cache"
DEFAULT_OUTPUT = "./docs"


class Context:
    """CLI context for sharing state between commands."""

    def __init__(
        self,
        config_dir: Path,
        cache_dir: Path,
        output_dir: Path,
        log_level: str,
        log_format: str,
        dry_run: bool,
    ) -> None:
        self.config_dir = config_dir
        self.cache_dir = cache_dir
        self.output_dir = output_dir
        self.log_level = log_level
        self.log_format = log_format
        self.dry_run = dry_run
        self.logger = get_logger("cli")


pass_context = click.make_pass_decorator(Context)


def output_json(data: dict) -> None:
    """Output JSON to stdout."""
    click.echo(json.dumps(data, indent=2, default=str))


@click.group()
@click.option(
    "--config",
    type=click.Path(exists=False, path_type=Path),
    default=DEFAULT_CONFIG,
    help="Path to config directory",
)
@click.option(
    "--cache",
    type=click.Path(exists=False, path_type=Path),
    default=DEFAULT_CACHE,
    help="Path to cache directory",
)
@click.option(
    "--output",
    type=click.Path(exists=False, path_type=Path),
    default=DEFAULT_OUTPUT,
    help="Path to output directory",
)
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warn", "error"], case_sensitive=False),
    default="info",
    help="Logging level",
)
@click.option(
    "--log-format",
    type=click.Choice(["json", "text"], case_sensitive=False),
    default="json",
    help="Log format",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without executing",
)
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    config: Path,
    cache: Path,
    output: Path,
    log_level: str,
    log_format: str,
    dry_run: bool,
) -> None:
    """
    LocalStack Architecture Validator - Automated AWS compatibility testing.

    Validates real-world AWS architecture patterns against LocalStack to ensure
    compatibility. Discovers templates from multiple sources, generates test
    applications, and reports results to a dashboard.
    """
    # Configure logging
    configure_logging(level=log_level, format_type=log_format)

    # Create context
    ctx.obj = Context(
        config_dir=config,
        cache_dir=cache,
        output_dir=output,
        log_level=log_level,
        log_format=log_format,
        dry_run=dry_run,
    )

    # Ensure directories exist
    config.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)


@cli.command()
@click.option(
    "--source",
    "sources",
    multiple=True,
    help="Mine only this source (can be repeated)",
)
@click.option(
    "--skip-cache",
    is_flag=True,
    default=False,
    help="Force re-mining even if cache is valid",
)
@click.option(
    "--include-diagrams/--no-diagrams",
    default=True,
    help="Include diagram sources",
)
@click.option(
    "--max-per-source",
    type=int,
    default=None,
    help="Maximum templates per source",
)
@pass_context
def mine(
    ctx: Context,
    sources: tuple[str, ...],
    skip_cache: bool,
    include_diagrams: bool,
    max_per_source: Optional[int],
) -> None:
    """Mine templates from configured sources."""
    import asyncio
    from src.miner import mine_all, list_sources

    ctx.logger.info(
        "mine_started",
        sources=list(sources) if sources else "all",
        skip_cache=skip_cache,
        include_diagrams=include_diagrams,
    )

    if ctx.dry_run:
        available_sources = list_sources(include_diagrams=include_diagrams)
        output_json({
            "status": "dry_run",
            "message": "Would mine templates from sources",
            "sources": list(sources) if sources else available_sources,
            "include_diagrams": include_diagrams,
            "max_per_source": max_per_source,
        })
        return

    try:
        # Run mining
        result = asyncio.run(
            mine_all(
                cache_dir=ctx.cache_dir,
                sources=list(sources) if sources else None,
                include_diagrams=include_diagrams,
                max_per_source=max_per_source,
                skip_cache=skip_cache,
            )
        )

        output_json({
            "status": "success" if result.success else "partial",
            "message": f"Mined {len(result.architectures)} architectures",
            **result.to_dict(),
        })

    except Exception as e:
        ctx.logger.error("mining_failed", error=str(e))
        output_json({
            "status": "error",
            "message": f"Mining failed: {e}",
        })


@cli.command()
@click.option(
    "--architecture",
    "architectures",
    multiple=True,
    help="Generate for specific architecture (can be repeated)",
)
@click.option(
    "--skip-cache",
    is_flag=True,
    default=False,
    help="Force regeneration even if cached",
)
@click.option(
    "--token-budget",
    type=int,
    default=500000,
    help="Maximum Claude API tokens",
)
@click.option(
    "--validate-only",
    is_flag=True,
    default=False,
    help="Check if generated code compiles, don't save",
)
@pass_context
def generate(
    ctx: Context,
    architectures: tuple[str, ...],
    skip_cache: bool,
    token_budget: int,
    validate_only: bool,
) -> None:
    """Generate sample applications for architectures."""
    import asyncio
    from src.generator import generate_all
    from src.utils.cache import ArchitectureCache
    from src.models import Architecture

    ctx.logger.info(
        "generate_started",
        architectures=list(architectures) if architectures else "all",
        skip_cache=skip_cache,
        token_budget=token_budget,
    )

    if ctx.dry_run:
        output_json({
            "status": "dry_run",
            "message": "Would generate sample applications",
            "architectures": list(architectures) if architectures else "all",
            "token_budget": token_budget,
            "validate_only": validate_only,
        })
        return

    try:
        # Load cached architectures
        arch_cache = ArchitectureCache(ctx.cache_dir)
        arch_ids = list(architectures) if architectures else arch_cache.list_keys()

        if not arch_ids:
            output_json({
                "status": "error",
                "message": "No architectures found. Run 'mine' first.",
            })
            return

        # Load architecture objects
        arch_list = []
        for arch_id in arch_ids:
            cached = arch_cache.load_architecture(arch_id)
            if cached:
                from src.models import ArchitectureMetadata, ArchitectureSourceType
                metadata = None
                meta_dict = cached.get("metadata", {})
                if meta_dict:
                    metadata = ArchitectureMetadata.from_dict(meta_dict)

                # Get content_hash and source info from metadata
                content_hash = meta_dict.get("content_hash", "") if meta_dict else ""

                arch = Architecture(
                    id=arch_id,
                    source_type=ArchitectureSourceType(cached.get("source_type", "template")),
                    source_name=cached.get("source_name", "cached"),
                    source_url=cached.get("source_url", ""),
                    main_tf=cached.get("main_tf", ""),
                    variables_tf=cached.get("variables_tf"),
                    outputs_tf=cached.get("outputs_tf"),
                    metadata=metadata,
                    content_hash=content_hash,
                )
                arch_list.append(arch)

        if not arch_list:
            output_json({
                "status": "error",
                "message": "No valid architectures found in cache.",
            })
            return

        # Generate applications
        result = asyncio.run(
            generate_all(
                architectures=arch_list,
                cache_dir=ctx.cache_dir,
                skip_cache=skip_cache,
                validate_only=validate_only,
                token_budget=token_budget,
            )
        )

        output_json({
            "status": "success" if result.success else "partial",
            "message": f"Generated {len(result.apps)} applications",
            **result.to_dict(),
        })

    except Exception as e:
        ctx.logger.error("generation_failed", error=str(e))
        output_json({
            "status": "error",
            "message": f"Generation failed: {e}",
        })


@cli.command()
@click.option(
    "--architecture",
    "architectures",
    multiple=True,
    help="Validate specific architecture (can be repeated)",
)
@click.option(
    "--exclude",
    "excludes",
    multiple=True,
    help="Exclude architectures matching pattern",
)
@click.option(
    "--parallelism",
    type=int,
    default=4,
    help="Concurrent validations",
)
@click.option(
    "--localstack-version",
    default="latest",
    help="LocalStack image tag",
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    help="Per-architecture timeout in seconds",
)
@click.option(
    "--skip-cleanup",
    is_flag=True,
    default=False,
    help="Don't remove containers after validation",
)
@pass_context
def validate(
    ctx: Context,
    architectures: tuple[str, ...],
    excludes: tuple[str, ...],
    parallelism: int,
    localstack_version: str,
    timeout: int,
    skip_cleanup: bool,
) -> None:
    """Run validation pipeline."""
    import asyncio
    from src.runner import run_validations

    ctx.logger.info(
        "validate_started",
        architectures=list(architectures) if architectures else "all",
        parallelism=parallelism,
        localstack_version=localstack_version,
        timeout=timeout,
    )

    if ctx.dry_run:
        output_json({
            "status": "dry_run",
            "message": "Would run validations",
            "architectures": list(architectures) if architectures else "all",
            "parallelism": parallelism,
            "localstack_version": localstack_version,
        })
        return

    try:
        result = asyncio.run(
            run_validations(
                cache_dir=ctx.cache_dir,
                output_dir=ctx.output_dir,
                architectures=list(architectures) if architectures else None,
                excludes=list(excludes) if excludes else None,
                parallelism=parallelism,
                localstack_version=localstack_version,
                timeout=timeout,
                skip_cleanup=skip_cleanup,
            )
        )

        if result.success:
            output_json({
                "status": "success",
                "message": f"Validation completed: {result.run.id}",
                **result.to_dict(),
            })
        else:
            output_json({
                "status": "error",
                "message": "Validation failed",
                "errors": result.errors,
                **result.to_dict(),
            })

    except Exception as e:
        ctx.logger.error("validation_failed", error=str(e))
        output_json({
            "status": "error",
            "message": f"Validation failed: {e}",
        })


@cli.command()
@click.option(
    "--run-id",
    default=None,
    help="Generate report for specific run (default: latest)",
)
@click.option(
    "--create-issues",
    is_flag=True,
    default=False,
    help="Create GitHub issues for failures",
)
@click.option(
    "--github-token",
    envvar="GITHUB_TOKEN",
    default=None,
    help="GitHub API token (or set GITHUB_TOKEN env var)",
)
@click.option(
    "--github-repo",
    envvar="GITHUB_REPOSITORY",
    default=None,
    help="GitHub repository (owner/repo) (or set GITHUB_REPOSITORY env var)",
)
@click.option(
    "--dashboard-url",
    default="",
    help="Base URL for dashboard links in issues",
)
@click.option(
    "--skip-deploy",
    is_flag=True,
    default=False,
    help="Generate but don't deploy to gh-pages",
)
@pass_context
def report(
    ctx: Context,
    run_id: Optional[str],
    create_issues: bool,
    github_token: Optional[str],
    github_repo: Optional[str],
    dashboard_url: str,
    skip_deploy: bool,
) -> None:
    """Generate dashboard report."""
    import json as json_module
    from src.reporter import SiteGenerator, process_results_for_issues
    from src.models import ArchitectureResult, ValidationRun, Architecture, ArchitectureMetadata, ArchitectureSourceType
    from src.utils.cache import ArchitectureCache, AppCache

    ctx.logger.info(
        "report_started",
        run_id=run_id or "latest",
        create_issues=create_issues,
    )

    if ctx.dry_run:
        output_json({
            "status": "dry_run",
            "message": "Would generate report",
            "run_id": run_id or "latest",
            "create_issues": create_issues,
        })
        return

    # Find templates directory (relative to package)
    templates_dir = Path(__file__).parent.parent / "templates"
    if not templates_dir.exists():
        # Fall back to current directory
        templates_dir = Path("templates")

    # Load architectures from cache for enriched dashboard data
    arch_cache = ArchitectureCache(ctx.cache_dir)
    app_cache = AppCache(ctx.cache_dir)
    architectures: dict[str, Architecture] = {}

    for arch_id in arch_cache.list_keys():
        cached = arch_cache.load_architecture(arch_id)
        if cached:
            metadata = None
            meta_dict = cached.get("metadata", {})
            if meta_dict:
                metadata = ArchitectureMetadata.from_dict(meta_dict)

            # Get content_hash from metadata
            content_hash = meta_dict.get("content_hash", "") if meta_dict else ""

            arch = Architecture(
                id=arch_id,
                source_type=ArchitectureSourceType(cached.get("source_type", "template")),
                source_name=cached.get("source_name", "cached"),
                source_url=cached.get("source_url", ""),
                main_tf=cached.get("main_tf", ""),
                variables_tf=cached.get("variables_tf"),
                outputs_tf=cached.get("outputs_tf"),
                metadata=metadata,
                content_hash=content_hash,
            )
            architectures[arch_id] = arch

    # Generate the dashboard
    generator = SiteGenerator(
        templates_dir=templates_dir,
        output_dir=ctx.output_dir,
        base_url="",
    )

    try:
        data_dir = ctx.output_dir / "data"
        index_path = generator.generate(
            data_dir=data_dir,
            architectures=architectures if architectures else None,
            app_cache=app_cache,
        )
        ctx.logger.info("report_generated", output_path=str(index_path))

        issue_stats = {"created": 0, "closed": 0, "skipped": 0}

        # Process issues if requested
        if create_issues:
            # Load latest run results
            latest_file = data_dir / "latest.json"
            if latest_file.exists():
                run_data = json_module.loads(latest_file.read_text())
                run = ValidationRun.from_dict(run_data)

                # Get results as ArchitectureResult objects
                results = []
                for r in run.results:
                    if isinstance(r, ArchitectureResult):
                        results.append(r)
                    elif isinstance(r, dict):
                        results.append(ArchitectureResult.from_dict(r))

                if results:
                    issue_stats = process_results_for_issues(
                        results=results,
                        data_dir=data_dir,
                        github_token=github_token,
                        github_repo=github_repo,
                        dashboard_url=dashboard_url,
                        dry_run=ctx.dry_run,
                    )
                    ctx.logger.info(
                        "issues_processed",
                        created=issue_stats["created"],
                        closed=issue_stats["closed"],
                    )
            else:
                ctx.logger.warning("no_latest_run_for_issues")

        output_json({
            "status": "success",
            "message": "Dashboard generated successfully",
            "output_path": str(index_path),
            "run_id": run_id or "latest",
            "issues": issue_stats if create_issues else None,
        })

        # TODO: Implement gh-pages deployment in Phase 8 (US6)
        if not skip_deploy:
            ctx.logger.info("deployment_skipped", reason="not_implemented")

    except Exception as e:
        ctx.logger.error("report_generation_failed", error=str(e))
        output_json({
            "status": "error",
            "message": f"Failed to generate report: {e}",
        })


def _run_with_fsm(
    ctx: Context,
    skip_mining: bool,
    skip_generation: bool,
    skip_cache: bool,
    create_issues: bool,
    github_token: Optional[str],
    github_repo: Optional[str],
    dashboard_url: str,
    localstack_version: str,
    max_per_source: int,
    incremental: bool = False,
) -> None:
    """Run pipeline using FSM-based processor."""
    import asyncio
    from datetime import datetime
    from pathlib import Path

    from src.processor import ArchitectureProcessor, ProcessorConfig
    from src.reporter import SiteGenerator
    from src.utils.cache import AppCache, ArchitectureCache
    from src.models import Architecture, ArchitectureMetadata, ArchitectureSourceType

    ctx.logger.info(
        "fsm_pipeline_started",
        skip_cache=skip_cache,
        incremental=incremental,
    )

    try:
        # Configure processor
        config = ProcessorConfig(
            cache_dir=ctx.cache_dir,
            max_per_source=max_per_source,
            include_diagrams=True,
            skip_mining=skip_mining,
            skip_generation=skip_generation,
            skip_cache=skip_cache,
            localstack_version=localstack_version,
            incremental=incremental,
        )

        # Run processor
        processor = ArchitectureProcessor(config)
        validation_run = asyncio.run(processor.run())

        ctx.logger.info(
            "fsm_pipeline_completed",
            stats=processor.machine.stats.to_dict(),
            summary=processor.machine.progress_summary(),
        )

        # Generate report
        templates_dir = Path(__file__).parent.parent / "templates"
        if not templates_dir.exists():
            templates_dir = Path("templates")

        # Load architectures for dashboard - from processor first, then cache
        arch_cache = ArchitectureCache(ctx.cache_dir)
        architectures: dict[str, Architecture] = {}

        # First, get architectures from the processor (includes newly discovered)
        for arch_id, arch in processor._architectures.items():
            architectures[arch_id] = arch

        ctx.logger.info(
            "architectures_from_processor",
            count=len(architectures),
            ids=list(architectures.keys())[:10],
        )

        # Then supplement with cached architectures
        for arch_id in arch_cache.list_keys():
            if arch_id in architectures:
                continue  # Already have from processor

            cached = arch_cache.load_architecture(arch_id)
            if cached:
                metadata = None
                meta_dict = cached.get("metadata", {})
                if meta_dict:
                    metadata = ArchitectureMetadata.from_dict(meta_dict)

                content_hash = meta_dict.get("content_hash", "") if meta_dict else ""

                arch = Architecture(
                    id=arch_id,
                    source_type=ArchitectureSourceType(cached.get("source_type", "template")),
                    source_name=cached.get("source_name", "cached"),
                    source_url=cached.get("source_url", ""),
                    main_tf=cached.get("main_tf", ""),
                    variables_tf=cached.get("variables_tf"),
                    outputs_tf=cached.get("outputs_tf"),
                    metadata=metadata,
                    content_hash=content_hash,
                )
                architectures[arch_id] = arch

        ctx.logger.info(
            "total_architectures_for_dashboard",
            count=len(architectures),
        )

        app_cache = AppCache(ctx.cache_dir)

        try:
            generator = SiteGenerator(
                templates_dir=templates_dir,
                output_dir=ctx.output_dir,
                base_url="",
            )

            generator.generate(
                run=validation_run,
                data_dir=ctx.output_dir / "data",
                architectures=architectures if architectures else None,
                app_cache=app_cache,
            )
        except Exception as e:
            ctx.logger.error("dashboard_generation_failed", error=str(e))
            # Create minimal fallback index.html
            index_path = ctx.output_dir / "index.html"
            index_path.write_text(f"""<!DOCTYPE html>
<html><head><title>Dashboard Error</title>
<style>body{{font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:2rem;text-align:center;}}
h1{{color:#f87171;}}pre{{background:#1e293b;padding:1rem;border-radius:0.5rem;text-align:left;overflow:auto;}}</style></head>
<body><h1>Dashboard Generation Failed</h1><pre>{e}</pre></body></html>""")

        # Save registry data for dashboard (cumulative tracking)
        import json as json_module
        registry_data_file = ctx.output_dir / "data" / "registry.json"
        registry_data_file.parent.mkdir(parents=True, exist_ok=True)
        registry_data = {
            "stats": processor.get_registry_stats(),
            "weekly_summary": processor.get_weekly_summary(),
            "growth_data": processor.get_growth_data(days=30),
            "updated_at": datetime.utcnow().isoformat(),
        }
        registry_data_file.write_text(json_module.dumps(registry_data, indent=2, default=str))
        ctx.logger.info("registry_data_saved", path=str(registry_data_file))

        # Also save discovered architectures count for debugging
        ctx.logger.info(
            "architectures_discovered",
            count=len(architectures) if architectures else 0,
            from_cache=len(arch_cache.list_keys()),
            from_processor=len(processor._architectures),
            results=len(validation_run.results) if validation_run.results else 0,
        )

        # Output results
        stats = processor.machine.stats
        registry_stats = processor.get_registry_stats()

        output_json({
            "status": "success" if stats.errors == 0 else "partial",
            "run_id": validation_run.id,
            "statistics": {
                "total": stats.total,
                "passed": stats.passed,
                "partial": stats.partial,
                "failed": stats.failed,
                "errors": stats.errors,
                "skipped": stats.skipped,
                "rate_limits": stats.rate_limits,
                "pass_rate": stats.pass_rate,
            },
            "timing": {
                "started_at": stats.started_at.isoformat() if stats.started_at else None,
                "completed_at": stats.completed_at.isoformat() if stats.completed_at else None,
                "total_seconds": (
                    (stats.completed_at - stats.started_at).total_seconds()
                    if stats.started_at and stats.completed_at
                    else 0
                ),
            },
            "fsm_summary": processor.machine.progress_summary(),
            "registry": {
                "total_architectures": registry_stats.get("total_architectures", 0),
                "tested_architectures": registry_stats.get("tested_architectures", 0),
                "new_this_week": registry_stats.get("new_this_week", 0),
                "services_coverage": registry_stats.get("services_coverage", {}),
            },
            "architectures_discovered": len(processor._architectures),
            "architecture_ids": list(processor._architectures.keys()),
            "results_count": len(validation_run.results) if validation_run.results else 0,
        })

    except Exception as e:
        import traceback
        ctx.logger.error("fsm_pipeline_failed", error=str(e), traceback=traceback.format_exc())
        output_json({
            "status": "error",
            "message": str(e),
        })
        raise


@cli.command()
@click.option(
    "--skip-mining",
    is_flag=True,
    default=False,
    help="Use cached architectures only",
)
@click.option(
    "--skip-generation",
    is_flag=True,
    default=False,
    help="Use cached sample apps only",
)
@click.option(
    "--create-issues",
    is_flag=True,
    default=False,
    help="Create GitHub issues for failures",
)
@click.option(
    "--github-token",
    envvar="GITHUB_TOKEN",
    default=None,
    help="GitHub API token (or set GITHUB_TOKEN env var)",
)
@click.option(
    "--github-repo",
    envvar="GITHUB_REPOSITORY",
    default=None,
    help="GitHub repository (owner/repo) (or set GITHUB_REPOSITORY env var)",
)
@click.option(
    "--dashboard-url",
    default="",
    help="Base URL for dashboard links in issues",
)
@click.option(
    "--parallelism",
    type=int,
    default=4,
    help="Concurrent validations",
)
@click.option(
    "--localstack-version",
    default="latest",
    help="LocalStack image tag",
)
@click.option(
    "--max-per-source",
    type=int,
    default=3,
    help="Maximum architectures per source (default: 3, keeps API calls low)",
)
@click.option(
    "--use-fsm",
    is_flag=True,
    default=False,
    help="Use FSM-based processor (sequential, handles rate limits gracefully)",
)
@click.option(
    "--force-fresh",
    is_flag=True,
    default=False,
    help="Force fresh mining and generation (ignore cache)",
)
@click.option(
    "--incremental",
    is_flag=True,
    default=False,
    help="Incremental mode: only discover and test NEW architectures (skip already-known)",
)
@pass_context
def run(
    ctx: Context,
    skip_mining: bool,
    skip_generation: bool,
    create_issues: bool,
    github_token: Optional[str],
    github_repo: Optional[str],
    dashboard_url: str,
    parallelism: int,
    localstack_version: str,
    max_per_source: int,
    use_fsm: bool,
    force_fresh: bool,
    incremental: bool,
) -> None:
    """Run full pipeline (mine -> generate -> validate -> report)."""
    import asyncio
    from datetime import datetime

    from src.models import StageTiming

    ctx.logger.info(
        "run_started",
        skip_mining=skip_mining,
        skip_generation=skip_generation,
        parallelism=parallelism,
        use_fsm=use_fsm,
    )

    if ctx.dry_run:
        output_json({
            "status": "dry_run",
            "message": "Would run full pipeline",
            "stages": {
                "mine": not skip_mining,
                "generate": not skip_generation,
                "validate": True,
                "report": True,
            },
            "use_fsm": use_fsm,
        })
        return

    # Use FSM-based processor if requested
    if use_fsm:
        _run_with_fsm(
            ctx=ctx,
            skip_mining=skip_mining,
            skip_generation=skip_generation,
            skip_cache=force_fresh,
            create_issues=create_issues,
            github_token=github_token,
            github_repo=github_repo,
            dashboard_url=dashboard_url,
            localstack_version=localstack_version,
            max_per_source=max_per_source,
            incremental=incremental,
        )
        return

    pipeline_start = datetime.utcnow()
    timing = StageTiming()
    errors = []

    try:
        # Stage 1: Mining
        if not skip_mining:
            from src.miner import mine_all

            ctx.logger.info("pipeline_stage", stage="mining")
            mining_start = datetime.utcnow()

            mining_result = asyncio.run(
                mine_all(
                    cache_dir=ctx.cache_dir,
                    include_diagrams=True,
                    max_per_source=max_per_source,
                )
            )

            timing.mining_seconds = (datetime.utcnow() - mining_start).total_seconds()

            if not mining_result.success:
                errors.extend(mining_result.errors)

        # Load cache and model classes
        from src.utils.cache import ArchitectureCache
        from src.models import Architecture, ArchitectureMetadata, ArchitectureSourceType

        arch_cache = ArchitectureCache(ctx.cache_dir)

        # Stage 2: Generation
        if not skip_generation:
            from src.generator import generate_all

            ctx.logger.info("pipeline_stage", stage="generation")
            gen_start = datetime.utcnow()

            # Load architectures
            arch_ids = arch_cache.list_keys()

            arch_list = []
            for arch_id in arch_ids:
                cached = arch_cache.load_architecture(arch_id)
                if cached:
                    metadata = None
                    meta_dict = cached.get("metadata", {})
                    if meta_dict:
                        metadata = ArchitectureMetadata.from_dict(meta_dict)

                    # Get content_hash and source info from metadata
                    content_hash = meta_dict.get("content_hash", "") if meta_dict else ""

                    arch = Architecture(
                        id=arch_id,
                        source_type=ArchitectureSourceType(cached.get("source_type", "template")),
                        source_name=cached.get("source_name", "cached"),
                        source_url=cached.get("source_url", ""),
                        main_tf=cached.get("main_tf", ""),
                        variables_tf=cached.get("variables_tf"),
                        outputs_tf=cached.get("outputs_tf"),
                        metadata=metadata,
                        content_hash=content_hash,
                    )
                    arch_list.append(arch)

            if arch_list:
                gen_result = asyncio.run(
                    generate_all(
                        architectures=arch_list,
                        cache_dir=ctx.cache_dir,
                    )
                )
                if not gen_result.success:
                    errors.extend(gen_result.errors)

            timing.generation_seconds = (datetime.utcnow() - gen_start).total_seconds()

        # Stage 3: Validation
        from src.runner import run_validations

        ctx.logger.info("pipeline_stage", stage="validation")
        validation_start = datetime.utcnow()

        validation_result = asyncio.run(
            run_validations(
                cache_dir=ctx.cache_dir,
                output_dir=ctx.output_dir,
                parallelism=parallelism,
                localstack_version=localstack_version,
            )
        )

        timing.running_seconds = (datetime.utcnow() - validation_start).total_seconds()

        if not validation_result.success:
            errors.extend(validation_result.errors)

        # Stage 4: Reporting
        from src.reporter import SiteGenerator
        from src.utils.cache import AppCache

        ctx.logger.info("pipeline_stage", stage="reporting")
        reporting_start = datetime.utcnow()

        templates_dir = Path(__file__).parent.parent / "templates"
        if not templates_dir.exists():
            templates_dir = Path("templates")

        # Load architectures for enriched dashboard data
        architectures: dict[str, Architecture] = {}
        for arch_id in arch_cache.list_keys():
            cached = arch_cache.load_architecture(arch_id)
            if cached:
                metadata = None
                meta_dict = cached.get("metadata", {})
                if meta_dict:
                    metadata = ArchitectureMetadata.from_dict(meta_dict)

                # Get content_hash from metadata
                content_hash = meta_dict.get("content_hash", "") if meta_dict else ""

                arch = Architecture(
                    id=arch_id,
                    source_type=ArchitectureSourceType(cached.get("source_type", "template")),
                    source_name=cached.get("source_name", "cached"),
                    source_url=cached.get("source_url", ""),
                    main_tf=cached.get("main_tf", ""),
                    variables_tf=cached.get("variables_tf"),
                    outputs_tf=cached.get("outputs_tf"),
                    metadata=metadata,
                    content_hash=content_hash,
                )
                architectures[arch_id] = arch

        app_cache = AppCache(ctx.cache_dir)

        generator = SiteGenerator(
            templates_dir=templates_dir,
            output_dir=ctx.output_dir,
            base_url="",
        )

        generator.generate(
            run=validation_result.run,
            data_dir=ctx.output_dir / "data",
            architectures=architectures if architectures else None,
            app_cache=app_cache,
        )

        timing.reporting_seconds = (datetime.utcnow() - reporting_start).total_seconds()
        timing.total_seconds = (datetime.utcnow() - pipeline_start).total_seconds()

        # Stage 5: Issue Creation (optional)
        issue_stats = {"created": 0, "closed": 0, "skipped": 0}

        if create_issues and validation_result.run:
            from src.reporter import process_results_for_issues
            from src.models import ArchitectureResult

            ctx.logger.info("pipeline_stage", stage="issues")

            # Get results as ArchitectureResult objects
            results = []
            for r in validation_result.run.results:
                if isinstance(r, ArchitectureResult):
                    results.append(r)

            if results:
                issue_stats = process_results_for_issues(
                    results=results,
                    data_dir=ctx.output_dir / "data",
                    github_token=github_token,
                    github_repo=github_repo,
                    dashboard_url=dashboard_url,
                    dry_run=ctx.dry_run,
                )
                ctx.logger.info(
                    "issues_processed",
                    created=issue_stats["created"],
                    closed=issue_stats["closed"],
                )

        # Output results
        output_json({
            "status": "success" if not errors else "partial",
            "message": "Pipeline completed",
            "run_id": validation_result.run.id if validation_result.run else None,
            "timing": timing.to_dict(),
            "statistics": validation_result.run.statistics.to_dict()
                if validation_result.run and validation_result.run.statistics
                else {},
            "issues": issue_stats if create_issues else None,
            "errors": errors,
        })

    except Exception as e:
        ctx.logger.error("pipeline_failed", error=str(e))
        output_json({
            "status": "error",
            "message": f"Pipeline failed: {e}",
            "errors": errors + [str(e)],
        })


@cli.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    help="Output format",
)
@pass_context
def status(ctx: Context, output_format: str) -> None:
    """Show current state."""
    from src.utils.cache import ArchitectureCache, AppCache

    arch_cache = ArchitectureCache(ctx.cache_dir)
    app_cache = AppCache(ctx.cache_dir)

    # Count cached items
    arch_count = len(arch_cache.list_keys())
    app_count = len(app_cache.list_keys())

    # Check for latest run
    runs_dir = ctx.output_dir / "data" / "runs"
    latest_run = None
    if runs_dir.exists():
        run_files = sorted(runs_dir.glob("run-*.json"), reverse=True)
        if run_files:
            import json as json_module
            latest_run = json_module.loads(run_files[0].read_text())

    status_data = {
        "cached_architectures": arch_count,
        "cached_apps": app_count,
        "latest_run": (
            {
                "id": latest_run["id"],
                "status": latest_run.get("status", "unknown"),
                "pass_rate": latest_run.get("statistics", {}).get("pass_rate", 0),
            }
            if latest_run
            else None
        ),
        "cache_size_mb": round(arch_cache.get_size() / (1024 * 1024), 2),
    }

    if output_format == "json":
        output_json(status_data)
    else:
        click.echo("LocalStack Architecture Validator Status")
        click.echo("=" * 40)
        click.echo(f"Cached architectures: {arch_count}")
        click.echo(f"Cached apps: {app_count}")
        click.echo(f"Cache size: {status_data['cache_size_mb']} MB")
        if latest_run:
            click.echo(f"\nLatest run: {latest_run['id']}")
            click.echo(f"  Status: {latest_run.get('status', 'unknown')}")
            stats = latest_run.get("statistics", {})
            if stats:
                click.echo(f"  Pass rate: {stats.get('pass_rate', 0):.1%}")


@cli.command()
@click.option("--architectures", is_flag=True, help="Clean cached architectures")
@click.option("--apps", is_flag=True, help="Clean cached sample apps")
@click.option("--runs", is_flag=True, help="Clean old run results")
@click.option("--all", "clean_all", is_flag=True, help="Clean everything")
@click.option(
    "--retention-days",
    type=int,
    default=90,
    help="Days of run history to keep (default: 90 per FR-052)",
)
@click.option(
    "--max-size-gb",
    type=float,
    default=10.0,
    help="Maximum cache size in GB (default: 10 per FR-052)",
)
@pass_context
def clean(
    ctx: Context,
    architectures: bool,
    apps: bool,
    runs: bool,
    clean_all: bool,
    retention_days: int,
    max_size_gb: float,
) -> None:
    """Clean cache and state with retention policies."""
    import shutil
    from datetime import datetime, timedelta
    from src.utils.cache import ArchitectureCache, AppCache

    if ctx.dry_run:
        output_json({
            "status": "dry_run",
            "message": "Would clean cache",
            "architectures": architectures or clean_all,
            "apps": apps or clean_all,
            "runs": runs or clean_all,
            "retention_days": retention_days,
            "max_size_gb": max_size_gb,
        })
        return

    cleaned = {"architectures": 0, "apps": 0, "runs": 0, "bytes_freed": 0}

    # Clean runs based on retention period
    if runs or clean_all:
        runs_dir = ctx.output_dir / "data" / "runs"
        if runs_dir.exists():
            cutoff = datetime.now() - timedelta(days=retention_days)
            for run_item in runs_dir.iterdir():
                # Handle both directories and JSON files
                try:
                    name = run_item.stem if run_item.is_file() else run_item.name
                    parts = name.split("-")
                    if len(parts) >= 2:
                        date_str = parts[1]
                        run_date = datetime.strptime(date_str, "%Y%m%d")
                        if run_date < cutoff:
                            size = run_item.stat().st_size if run_item.is_file() else sum(
                                f.stat().st_size for f in run_item.rglob("*") if f.is_file()
                            )
                            if run_item.is_dir():
                                shutil.rmtree(run_item)
                            else:
                                run_item.unlink()
                            cleaned["runs"] += 1
                            cleaned["bytes_freed"] += size
                except (ValueError, IndexError, OSError):
                    pass

    # Clean caches
    if architectures or clean_all:
        arch_cache = ArchitectureCache(ctx.cache_dir)
        count = arch_cache.clear()
        cleaned["architectures"] = count

    if apps or clean_all:
        app_cache = AppCache(ctx.cache_dir)
        count = app_cache.clear()
        cleaned["apps"] = count

    # Enforce storage cap
    arch_cache = ArchitectureCache(ctx.cache_dir)
    app_cache = AppCache(ctx.cache_dir)
    total_size = arch_cache.get_size() + app_cache.get_size()
    max_bytes = int(max_size_gb * 1024 * 1024 * 1024)

    if total_size > max_bytes:
        ctx.logger.warning(
            "storage_cap_exceeded",
            current_gb=round(total_size / (1024**3), 2),
            max_gb=max_size_gb,
        )
        # Clear older items until under cap
        # Start with apps, then architectures
        while total_size > max_bytes:
            # Try to evict oldest app first
            evicted = app_cache.evict_oldest()
            if evicted:
                cleaned["apps"] += 1
                total_size = arch_cache.get_size() + app_cache.get_size()
                continue

            # Then try architectures
            evicted = arch_cache.evict_oldest()
            if evicted:
                cleaned["architectures"] += 1
                total_size = arch_cache.get_size() + app_cache.get_size()
                continue

            # Nothing more to evict
            break

    output_json({
        "status": "success",
        "cleaned": cleaned,
        "current_size_mb": round((arch_cache.get_size() + app_cache.get_size()) / (1024 * 1024), 2),
    })


def main() -> None:
    """Main entry point."""
    try:
        cli()
    except Exception as e:
        logger = get_logger("cli")
        logger.error("cli_error", error=str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
