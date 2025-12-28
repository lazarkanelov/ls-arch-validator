"""Parallel validation orchestrator."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models import (
    Architecture,
    ArchitectureResult,
    ResultStatus,
    SampleApp,
    ValidationRun,
)
from src.runner.container import ContainerConfig, ContainerManager
from src.runner.executor import ExecutionContext, execute_validation
from src.utils.logging import get_logger, set_stage

logger = get_logger("runner.orchestrator")


@dataclass
class ValidationTask:
    """A single validation task."""

    architecture: Architecture
    app: SampleApp
    timeout: int = 600


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""

    parallelism: int = 4
    timeout_per_arch: int = 600
    localstack_version: str = "latest"
    skip_cleanup: bool = False


class ValidationOrchestrator:
    """
    Orchestrates parallel validation runs.

    Manages multiple LocalStack containers and executes
    validations concurrently using asyncio.Semaphore.
    """

    def __init__(self, config: Optional[OrchestratorConfig] = None) -> None:
        """
        Initialize the orchestrator.

        Args:
            config: Orchestrator configuration
        """
        self.config = config or OrchestratorConfig()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._container_manager: Optional[ContainerManager] = None
        self._results: list[ArchitectureResult] = []

    async def run_validations(
        self,
        tasks: list[ValidationTask],
    ) -> list[ArchitectureResult]:
        """
        Run validations for all tasks.

        Args:
            tasks: List of validation tasks

        Returns:
            List of ArchitectureResult
        """
        set_stage("validation")

        logger.info(
            "orchestrator_started",
            tasks=len(tasks),
            parallelism=self.config.parallelism,
        )

        # Initialize components
        self._semaphore = asyncio.Semaphore(self.config.parallelism)
        self._container_manager = ContainerManager(
            ContainerConfig(
                image=f"localstack/localstack:{self.config.localstack_version}",
            )
        )
        self._results = []

        try:
            # Create tasks
            validation_coroutines = [
                self._run_single_validation(task, idx)
                for idx, task in enumerate(tasks)
            ]

            # Run with graceful degradation
            await asyncio.gather(
                *validation_coroutines,
                return_exceptions=True,
            )

        finally:
            # Cleanup all containers
            if not self.config.skip_cleanup:
                await self._container_manager.cleanup_all()

        logger.info(
            "orchestrator_completed",
            total=len(tasks),
            passed=sum(1 for r in self._results if r.status == ResultStatus.PASSED),
            failed=sum(1 for r in self._results if r.status == ResultStatus.FAILED),
        )

        return self._results

    async def _run_single_validation(
        self,
        task: ValidationTask,
        task_idx: int,
    ) -> None:
        """
        Run a single validation with semaphore control.

        Args:
            task: Validation task
            task_idx: Task index for container naming
        """
        async with self._semaphore:
            instance_id = f"task-{task_idx}"

            try:
                result = await self._execute_task(task, instance_id)
                self._results.append(result)

            except asyncio.TimeoutError:
                logger.warning(
                    "validation_timeout",
                    arch_id=task.architecture.id,
                )
                self._results.append(
                    ArchitectureResult(
                        architecture_id=task.architecture.id,
                        source_type=task.architecture.source_type,
                        status=ResultStatus.TIMEOUT,
                        services=task.architecture.metadata.services
                        if task.architecture.metadata
                        else set(),
                        suggested_issue_title=f"Validation timeout: {task.architecture.id}",
                    )
                )

            except Exception as e:
                logger.error(
                    "validation_error",
                    arch_id=task.architecture.id,
                    error=str(e),
                )
                self._results.append(
                    ArchitectureResult(
                        architecture_id=task.architecture.id,
                        source_type=task.architecture.source_type,
                        status=ResultStatus.FAILED,
                        services=task.architecture.metadata.services
                        if task.architecture.metadata
                        else set(),
                        suggested_issue_title=f"Validation error: {task.architecture.id}",
                    )
                )

            finally:
                # Cleanup container
                if not self.config.skip_cleanup:
                    await self._container_manager.stop_container(instance_id)

    async def _execute_task(
        self,
        task: ValidationTask,
        instance_id: str,
    ) -> ArchitectureResult:
        """
        Execute a single validation task.

        Args:
            task: Validation task
            instance_id: Container instance ID

        Returns:
            ArchitectureResult
        """
        arch = task.architecture
        app = task.app

        logger.info("validation_started", arch_id=arch.id)

        # Start container
        container = await self._container_manager.start_container(instance_id)

        # Create temporary work directory
        with tempfile.TemporaryDirectory() as work_dir:
            ctx = ExecutionContext(
                work_dir=Path(work_dir),
                endpoint_url=container.endpoint_url,
                architecture_id=arch.id,
                timeout=task.timeout,
            )

            # Execute validation with timeout
            infra_result, test_result, logs = await asyncio.wait_for(
                execute_validation(
                    ctx=ctx,
                    main_tf=arch.main_tf,
                    variables_tf=arch.variables_tf,
                    outputs_tf=arch.outputs_tf,
                    test_code=app.test_code,
                ),
                timeout=task.timeout,
            )

            # Get container logs
            logs.localstack_log = await self._container_manager.get_logs(instance_id)

        # Determine status
        status = self._determine_status(infra_result, test_result)

        # Generate issue title if failed
        suggested_title = None
        if status in (ResultStatus.FAILED, ResultStatus.PARTIAL):
            suggested_title = self._generate_issue_title(
                arch, infra_result, test_result
            )

        result = ArchitectureResult(
            architecture_id=arch.id,
            source_type=arch.source_type,
            status=status,
            services=arch.metadata.services if arch.metadata else set(),
            infrastructure=infra_result,
            tests=test_result,
            logs=logs,
            suggested_issue_title=suggested_title,
        )

        logger.info(
            "validation_completed",
            arch_id=arch.id,
            status=status.value,
        )

        return result

    def _determine_status(
        self,
        infra: Optional["InfrastructureResult"],
        tests: Optional["TestResult"],
    ) -> ResultStatus:
        """Determine overall status from results."""
        if infra is None or not infra.passed:
            return ResultStatus.FAILED

        if tests is None:
            return ResultStatus.PASSED

        if tests.failed == 0:
            return ResultStatus.PASSED

        if tests.passed > 0:
            return ResultStatus.PARTIAL

        return ResultStatus.FAILED

    def _generate_issue_title(
        self,
        arch: Architecture,
        infra: Optional["InfrastructureResult"],
        tests: Optional["TestResult"],
    ) -> str:
        """Generate a suggested issue title for failures."""
        if infra and not infra.passed:
            return f"[arch-validator] Infrastructure deployment failed: {arch.id}"

        if tests and tests.failed > 0:
            return f"[arch-validator] Test failures in {arch.id}: {tests.failed} failed"

        return f"[arch-validator] Validation failed: {arch.id}"


async def run_validation_pipeline(
    architectures: list[Architecture],
    apps: dict[str, SampleApp],
    config: Optional[OrchestratorConfig] = None,
) -> ValidationRun:
    """
    Run the complete validation pipeline.

    Args:
        architectures: List of architectures to validate
        apps: Mapping of architecture ID to SampleApp
        config: Orchestrator configuration

    Returns:
        ValidationRun with all results
    """
    config = config or OrchestratorConfig()

    # Create validation run
    run = ValidationRun.create(localstack_version=config.localstack_version)

    # Build tasks
    tasks = []
    for arch in architectures:
        app = apps.get(arch.id)
        if app:
            tasks.append(
                ValidationTask(
                    architecture=arch,
                    app=app,
                    timeout=config.timeout_per_arch,
                )
            )
        else:
            logger.warning("no_app_for_architecture", arch_id=arch.id)

    if not tasks:
        logger.warning("no_validation_tasks")
        run.fail("No valid architectures with apps to validate")
        return run

    # Run orchestrator
    orchestrator = ValidationOrchestrator(config)
    results = await orchestrator.run_validations(tasks)

    # Complete run with results
    run.results = results
    run.complete()

    return run
