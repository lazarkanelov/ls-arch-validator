"""Terraform and pytest execution."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.models import InfrastructureResult, LogBundle, TestResult
from src.utils.logging import get_logger

logger = get_logger("runner.executor")

# Execution timeouts
TERRAFORM_INIT_TIMEOUT = 120  # seconds
TERRAFORM_APPLY_TIMEOUT = 300  # seconds
PYTEST_TIMEOUT = 300  # seconds


@dataclass
class ExecutionContext:
    """Context for executing validation."""

    work_dir: Path
    endpoint_url: str
    architecture_id: str
    timeout: int = 600


@dataclass
class TerraformOutput:
    """Output from Terraform execution."""

    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    logs: str = ""


@dataclass
class PytestOutput:
    """Output from pytest execution."""

    success: bool
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    logs: str = ""


class TerraformExecutor:
    """
    Executes Terraform commands against LocalStack.

    Uses tflocal for LocalStack-aware Terraform execution.
    """

    def __init__(self, use_tflocal: bool = True) -> None:
        """
        Initialize the executor.

        Args:
            use_tflocal: Use tflocal instead of terraform
        """
        self.tf_command = "tflocal" if use_tflocal else "terraform"

    async def init(self, ctx: ExecutionContext) -> TerraformOutput:
        """
        Run terraform init.

        Args:
            ctx: Execution context

        Returns:
            TerraformOutput with result
        """
        logger.debug("terraform_init", arch_id=ctx.architecture_id)

        env = self._get_env(ctx)

        try:
            process = await asyncio.create_subprocess_exec(
                self.tf_command, "init", "-no-color",
                cwd=str(ctx.work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TERRAFORM_INIT_TIMEOUT,
            )

            logs = stdout.decode() + stderr.decode()

            if process.returncode != 0:
                return TerraformOutput(
                    success=False,
                    error_message=f"terraform init failed: {stderr.decode()}",
                    logs=logs,
                )

            return TerraformOutput(success=True, logs=logs)

        except asyncio.TimeoutError:
            return TerraformOutput(
                success=False,
                error_message="terraform init timed out",
            )
        except Exception as e:
            return TerraformOutput(
                success=False,
                error_message=f"terraform init error: {e}",
            )

    async def apply(self, ctx: ExecutionContext) -> TerraformOutput:
        """
        Run terraform apply.

        Args:
            ctx: Execution context

        Returns:
            TerraformOutput with result
        """
        logger.debug("terraform_apply", arch_id=ctx.architecture_id)

        env = self._get_env(ctx)

        try:
            process = await asyncio.create_subprocess_exec(
                self.tf_command, "apply", "-auto-approve", "-no-color",
                cwd=str(ctx.work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TERRAFORM_APPLY_TIMEOUT,
            )

            logs = stdout.decode() + stderr.decode()

            if process.returncode != 0:
                return TerraformOutput(
                    success=False,
                    error_message=f"terraform apply failed: {stderr.decode()}",
                    logs=logs,
                )

            # Get outputs
            outputs = await self._get_outputs(ctx, env)

            return TerraformOutput(
                success=True,
                outputs=outputs,
                logs=logs,
            )

        except asyncio.TimeoutError:
            return TerraformOutput(
                success=False,
                error_message="terraform apply timed out",
            )
        except Exception as e:
            return TerraformOutput(
                success=False,
                error_message=f"terraform apply error: {e}",
            )

    async def destroy(self, ctx: ExecutionContext) -> TerraformOutput:
        """
        Run terraform destroy.

        Args:
            ctx: Execution context

        Returns:
            TerraformOutput with result
        """
        logger.debug("terraform_destroy", arch_id=ctx.architecture_id)

        env = self._get_env(ctx)

        try:
            process = await asyncio.create_subprocess_exec(
                self.tf_command, "destroy", "-auto-approve", "-no-color",
                cwd=str(ctx.work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TERRAFORM_APPLY_TIMEOUT,
            )

            return TerraformOutput(
                success=process.returncode == 0,
                logs=stdout.decode() + stderr.decode(),
            )

        except Exception as e:
            return TerraformOutput(
                success=False,
                error_message=f"terraform destroy error: {e}",
            )

    async def _get_outputs(
        self,
        ctx: ExecutionContext,
        env: dict[str, str],
    ) -> dict[str, Any]:
        """Get Terraform outputs."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.tf_command, "output", "-json",
                cwd=str(ctx.work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await process.communicate()

            if process.returncode == 0:
                return json.loads(stdout.decode())

        except Exception:
            pass

        return {}

    def _get_env(self, ctx: ExecutionContext) -> dict[str, str]:
        """Get environment variables for Terraform."""
        import os

        env = os.environ.copy()
        env.update({
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
            "LOCALSTACK_HOSTNAME": "localhost",
            "AWS_ENDPOINT_URL": ctx.endpoint_url,
        })
        return env


class PytestExecutor:
    """Executes pytest tests against LocalStack infrastructure."""

    def __init__(self) -> None:
        """Initialize the executor."""
        pass

    async def run(
        self,
        ctx: ExecutionContext,
        test_dir: Path,
        terraform_outputs: dict[str, Any],
    ) -> PytestOutput:
        """
        Run pytest tests.

        Args:
            ctx: Execution context
            test_dir: Directory containing tests
            terraform_outputs: Outputs from Terraform

        Returns:
            PytestOutput with results
        """
        logger.debug("pytest_run", arch_id=ctx.architecture_id)

        # Create temporary file for JSON results
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            result_file = Path(f.name)

        env = self._get_env(ctx, terraform_outputs)

        try:
            process = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest",
                str(test_dir),
                "-v",
                "--tb=short",
                f"--json-report-file={result_file}",
                "--json-report",
                cwd=str(ctx.work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=PYTEST_TIMEOUT,
            )

            logs = stdout.decode() + stderr.decode()

            # Parse JSON report
            if result_file.exists():
                try:
                    report = json.loads(result_file.read_text())
                    return self._parse_report(report, logs)
                except json.JSONDecodeError:
                    pass

            # Fall back to parsing exit code
            return PytestOutput(
                success=process.returncode == 0,
                logs=logs,
            )

        except asyncio.TimeoutError:
            return PytestOutput(
                success=False,
                logs="pytest timed out",
            )
        except Exception as e:
            return PytestOutput(
                success=False,
                logs=f"pytest error: {e}",
            )
        finally:
            result_file.unlink(missing_ok=True)

    def _parse_report(self, report: dict, logs: str) -> PytestOutput:
        """Parse pytest JSON report."""
        summary = report.get("summary", {})

        failures = []
        for test in report.get("tests", []):
            if test.get("outcome") == "failed":
                failures.append({
                    "test_name": test.get("nodeid", "unknown"),
                    "message": test.get("call", {}).get("longrepr", ""),
                })

        return PytestOutput(
            success=summary.get("failed", 0) == 0 and summary.get("error", 0) == 0,
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            skipped=summary.get("skipped", 0),
            errors=summary.get("error", 0),
            failures=failures,
            logs=logs,
        )

    def _get_env(
        self,
        ctx: ExecutionContext,
        terraform_outputs: dict[str, Any],
    ) -> dict[str, str]:
        """Get environment variables for pytest."""
        import os

        env = os.environ.copy()
        env.update({
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_ENDPOINT_URL": ctx.endpoint_url,
            "LOCALSTACK_ENDPOINT": ctx.endpoint_url,
        })

        # Add Terraform outputs as environment variables
        for key, value in terraform_outputs.items():
            if isinstance(value, dict) and "value" in value:
                env[f"TF_OUTPUT_{key.upper()}"] = str(value["value"])
            else:
                env[f"TF_OUTPUT_{key.upper()}"] = str(value)

        return env


async def execute_validation(
    ctx: ExecutionContext,
    main_tf: str,
    variables_tf: Optional[str],
    outputs_tf: Optional[str],
    test_code: dict[str, str],
) -> tuple[InfrastructureResult, Optional[TestResult], LogBundle]:
    """
    Execute a complete validation (Terraform + tests).

    Args:
        ctx: Execution context
        main_tf: Main Terraform content
        variables_tf: Variables file content
        outputs_tf: Outputs file content
        test_code: Test file contents

    Returns:
        Tuple of (InfrastructureResult, TestResult, LogBundle)
    """
    terraform_executor = TerraformExecutor()
    pytest_executor = PytestExecutor()

    # Set up work directory
    tf_dir = ctx.work_dir / "terraform"
    test_dir = ctx.work_dir / "tests"
    tf_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # Write Terraform files
    (tf_dir / "main.tf").write_text(main_tf)
    if variables_tf:
        (tf_dir / "variables.tf").write_text(variables_tf)
    if outputs_tf:
        (tf_dir / "outputs.tf").write_text(outputs_tf)

    # Write test files
    for filename, content in test_code.items():
        file_path = test_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    # Create execution context for Terraform
    tf_ctx = ExecutionContext(
        work_dir=tf_dir,
        endpoint_url=ctx.endpoint_url,
        architecture_id=ctx.architecture_id,
        timeout=ctx.timeout,
    )

    logs = LogBundle()

    # Run Terraform init
    init_result = await terraform_executor.init(tf_ctx)
    logs.terraform_log = init_result.logs

    if not init_result.success:
        return (
            InfrastructureResult(
                passed=False,
                error_message=init_result.error_message,
            ),
            None,
            logs,
        )

    # Run Terraform apply
    apply_result = await terraform_executor.apply(tf_ctx)
    logs.terraform_log += "\n" + apply_result.logs

    if not apply_result.success:
        return (
            InfrastructureResult(
                passed=False,
                error_message=apply_result.error_message,
            ),
            None,
            logs,
        )

    infra_result = InfrastructureResult(
        passed=True,
        outputs=apply_result.outputs,
    )

    # Run tests
    test_result = None
    if test_code:
        pytest_output = await pytest_executor.run(
            tf_ctx,
            test_dir,
            apply_result.outputs,
        )

        logs.test_output = pytest_output.logs

        from src.models import TestFailure
        test_result = TestResult(
            passed=pytest_output.passed,
            failed=pytest_output.failed,
            skipped=pytest_output.skipped,
            failures=[
                TestFailure(
                    test_name=f.get("test_name", "unknown"),
                    error_message=f.get("message", ""),
                )
                for f in pytest_output.failures
            ],
        )

    # Cleanup - destroy Terraform resources
    await terraform_executor.destroy(tf_ctx)

    return infra_result, test_result, logs
