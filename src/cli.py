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
                if cached.get("metadata"):
                    metadata = ArchitectureMetadata.from_dict(cached["metadata"])

                arch = Architecture(
                    id=arch_id,
                    source_type=ArchitectureSourceType.TEMPLATE,
                    source_name="cached",
                    source_url="",
                    main_tf=cached.get("main_tf", ""),
                    variables_tf=cached.get("variables_tf"),
                    outputs_tf=cached.get("outputs_tf"),
                    metadata=metadata,
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

    # TODO: Implement validation logic in Phase 6 (US2)
    output_json({
        "status": "not_implemented",
        "message": "Validation will be implemented in Phase 6",
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
    skip_deploy: bool,
) -> None:
    """Generate dashboard report."""
    from src.reporter import SiteGenerator

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

    # Generate the dashboard
    generator = SiteGenerator(
        templates_dir=templates_dir,
        output_dir=ctx.output_dir,
        base_url="",
    )

    try:
        index_path = generator.generate(data_dir=ctx.output_dir / "data")
        ctx.logger.info("report_generated", output_path=str(index_path))

        output_json({
            "status": "success",
            "message": "Dashboard generated successfully",
            "output_path": str(index_path),
            "run_id": run_id or "latest",
        })

        # TODO: Implement issue creation in Phase 7 (US5)
        if create_issues:
            ctx.logger.warning("issue_creation_not_implemented")

        # TODO: Implement gh-pages deployment in Phase 8 (US6)
        if not skip_deploy:
            ctx.logger.info("deployment_skipped", reason="not_implemented")

    except Exception as e:
        ctx.logger.error("report_generation_failed", error=str(e))
        output_json({
            "status": "error",
            "message": f"Failed to generate report: {e}",
        })


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
@pass_context
def run(
    ctx: Context,
    skip_mining: bool,
    skip_generation: bool,
    create_issues: bool,
    parallelism: int,
    localstack_version: str,
) -> None:
    """Run full pipeline (mine -> generate -> validate -> report)."""
    ctx.logger.info(
        "run_started",
        skip_mining=skip_mining,
        skip_generation=skip_generation,
        parallelism=parallelism,
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
        })
        return

    # TODO: Implement full pipeline in Phase 6 (US2)
    output_json({
        "status": "not_implemented",
        "message": "Full pipeline will be implemented in Phase 6",
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
@click.option("--runs", is_flag=True, help="Clean old run results (keeps last 7 days)")
@click.option("--all", "clean_all", is_flag=True, help="Clean everything")
@pass_context
def clean(
    ctx: Context,
    architectures: bool,
    apps: bool,
    runs: bool,
    clean_all: bool,
) -> None:
    """Clean cache and state."""
    from src.utils.cache import ArchitectureCache, AppCache

    if ctx.dry_run:
        output_json({
            "status": "dry_run",
            "message": "Would clean cache",
            "architectures": architectures or clean_all,
            "apps": apps or clean_all,
            "runs": runs or clean_all,
        })
        return

    cleaned = {"architectures": 0, "apps": 0, "runs": 0}

    if architectures or clean_all:
        arch_cache = ArchitectureCache(ctx.cache_dir)
        cleaned["architectures"] = arch_cache.clear()

    if apps or clean_all:
        app_cache = AppCache(ctx.cache_dir)
        cleaned["apps"] = app_cache.clear()

    if runs or clean_all:
        runs_dir = ctx.output_dir / "data" / "runs"
        if runs_dir.exists():
            import shutil
            from datetime import datetime, timedelta

            cutoff = datetime.now() - timedelta(days=7)
            for run_dir in runs_dir.iterdir():
                if run_dir.is_dir():
                    # Parse run date from name
                    try:
                        parts = run_dir.name.split("-")
                        if len(parts) >= 2:
                            date_str = parts[1]
                            run_date = datetime.strptime(date_str, "%Y%m%d")
                            if run_date < cutoff:
                                shutil.rmtree(run_dir)
                                cleaned["runs"] += 1
                    except (ValueError, IndexError):
                        pass

    output_json({
        "status": "success",
        "cleaned": cleaned,
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
