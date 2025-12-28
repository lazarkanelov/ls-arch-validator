"""Validation runner module."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models import (
    Architecture,
    ArchitectureResult,
    ResultStatus,
    SampleApp,
    StageTiming,
    ValidationRun,
)
from src.runner.container import ContainerConfig, ContainerInfo, ContainerManager
from src.runner.executor import (
    ExecutionContext,
    PytestExecutor,
    PytestOutput,
    TerraformExecutor,
    TerraformOutput,
    execute_validation,
)
from src.runner.orchestrator import (
    OrchestratorConfig,
    ValidationOrchestrator,
    ValidationTask,
    run_validation_pipeline,
)
from src.utils.cache import AppCache, ArchitectureCache
from src.utils.logging import get_logger, set_run_context, set_stage

logger = get_logger("runner")


class RunResult:
    """Result of a complete validation run."""

    def __init__(self) -> None:
        self.run: Optional[ValidationRun] = None
        self.errors: list[str] = []
        self.timings: StageTiming = StageTiming()

    @property
    def success(self) -> bool:
        """Check if run was successful."""
        return self.run is not None and len(self.errors) == 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "run_id": self.run.id if self.run else None,
            "status": self.run.status if self.run else "failed",
            "errors": len(self.errors),
            "timings": self.timings.to_dict() if self.timings else {},
            "statistics": self.run.statistics.to_dict()
            if self.run and self.run.statistics
            else {},
        }


async def run_validations(
    cache_dir: Path,
    output_dir: Path,
    architectures: Optional[list[str]] = None,
    excludes: Optional[list[str]] = None,
    parallelism: int = 4,
    localstack_version: str = "latest",
    timeout: int = 600,
    skip_cleanup: bool = False,
) -> RunResult:
    """
    Run validations for architectures.

    Args:
        cache_dir: Cache directory with architectures and apps
        output_dir: Output directory for results
        architectures: Specific architectures to validate (default: all)
        excludes: Patterns to exclude
        parallelism: Number of concurrent validations
        localstack_version: LocalStack image version
        timeout: Per-architecture timeout
        skip_cleanup: Don't cleanup containers after validation

    Returns:
        RunResult with validation results
    """
    result = RunResult()
    start_time = datetime.utcnow()

    # Set up logging context
    run_id = f"run-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    set_run_context(run_id)
    set_stage("setup")

    logger.info(
        "run_started",
        run_id=run_id,
        parallelism=parallelism,
        localstack_version=localstack_version,
    )

    try:
        # Load architectures
        arch_cache = ArchitectureCache(cache_dir)
        app_cache = AppCache(cache_dir)

        arch_ids = architectures or arch_cache.list_keys()

        # Apply exclusions
        if excludes:
            import fnmatch
            arch_ids = [
                aid for aid in arch_ids
                if not any(fnmatch.fnmatch(aid, pattern) for pattern in excludes)
            ]

        if not arch_ids:
            result.errors.append("No architectures to validate")
            return result

        # Load architecture and app objects
        arch_list = []
        apps_dict = {}

        for arch_id in arch_ids:
            # Load architecture
            cached_arch = arch_cache.load_architecture(arch_id)
            if not cached_arch:
                logger.warning("architecture_not_found", arch_id=arch_id)
                continue

            from src.models import ArchitectureMetadata, ArchitectureSourceType
            metadata = None
            if cached_arch.get("metadata"):
                metadata = ArchitectureMetadata.from_dict(cached_arch["metadata"])

            arch = Architecture(
                id=arch_id,
                source_type=ArchitectureSourceType.TEMPLATE,
                source_name="cached",
                source_url="",
                main_tf=cached_arch.get("main_tf", ""),
                variables_tf=cached_arch.get("variables_tf"),
                outputs_tf=cached_arch.get("outputs_tf"),
                metadata=metadata,
            )
            arch_list.append(arch)

            # Load app
            cached_app = app_cache.load_app(arch.content_hash)
            if cached_app:
                app = SampleApp(
                    architecture_id=arch_id,
                    content_hash=arch.content_hash,
                    source_code=cached_app.get("source_code", {}),
                    test_code=cached_app.get("test_code", {}),
                    requirements=cached_app.get("requirements", []),
                )
                apps_dict[arch_id] = app
            else:
                logger.warning("app_not_found", arch_id=arch_id)

        if not arch_list:
            result.errors.append("No valid architectures found")
            return result

        # Configure orchestrator
        config = OrchestratorConfig(
            parallelism=parallelism,
            timeout_per_arch=timeout,
            localstack_version=localstack_version,
            skip_cleanup=skip_cleanup,
        )

        # Run validations
        set_stage("validation")
        validation_start = datetime.utcnow()

        run = await run_validation_pipeline(
            architectures=arch_list,
            apps=apps_dict,
            config=config,
        )

        result.timings.running_seconds = (
            datetime.utcnow() - validation_start
        ).total_seconds()

        # Save results
        set_stage("reporting")
        reporting_start = datetime.utcnow()

        _save_run_results(run, output_dir)

        result.timings.reporting_seconds = (
            datetime.utcnow() - reporting_start
        ).total_seconds()

        result.run = run

        logger.info(
            "run_completed",
            run_id=run.id,
            total=run.statistics.total if run.statistics else 0,
            passed=run.statistics.passed if run.statistics else 0,
            failed=run.statistics.failed if run.statistics else 0,
        )

    except Exception as e:
        error_msg = f"Validation run failed: {e}"
        result.errors.append(error_msg)
        logger.error("run_failed", error=str(e))

    return result


def _save_run_results(run: ValidationRun, output_dir: Path) -> None:
    """
    Save validation run results.

    Args:
        run: Validation run to save
        output_dir: Output directory
    """
    data_dir = output_dir / "data"
    runs_dir = data_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Save run JSON
    run_file = runs_dir / f"{run.id}.json"
    run_file.write_text(json.dumps(run.to_dict(), indent=2, default=str))

    # Update latest.json
    latest_file = data_dir / "latest.json"
    latest_file.write_text(json.dumps(run.to_dict(), indent=2, default=str))

    logger.debug("results_saved", run_id=run.id, path=str(run_file))


__all__ = [
    # Main function
    "run_validations",
    "RunResult",
    # Container management
    "ContainerManager",
    "ContainerConfig",
    "ContainerInfo",
    # Executors
    "TerraformExecutor",
    "TerraformOutput",
    "PytestExecutor",
    "PytestOutput",
    "ExecutionContext",
    "execute_validation",
    # Orchestrator
    "ValidationOrchestrator",
    "OrchestratorConfig",
    "ValidationTask",
    "run_validation_pipeline",
]
