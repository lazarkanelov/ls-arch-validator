"""Pipeline guards - precondition checks that fail fast on critical issues.

These guards run before any pipeline work begins, ensuring that all
required resources and configurations are in place. If a guard fails,
the pipeline exits immediately with a clear error message and exit code.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.config.settings import PipelineConfig
from src.models import PipelineStatus
from src.utils.logging import get_logger
from src.utils.result import Err, ExitCode, GuardError, Ok, Result

logger = get_logger("pipeline.guards")


@dataclass
class GuardContext:
    """Context for guard checks."""

    config: PipelineConfig
    require_generation: bool = True
    require_docker: bool = True
    require_templates: bool = True


class PipelineGuards:
    """
    Precondition checks that fail the pipeline immediately on critical issues.

    Each guard returns a Result type - Ok(None) if the check passes,
    Err(GuardError) if it fails. This forces explicit error handling
    and prevents silent failures.
    """

    def __init__(self, context: GuardContext) -> None:
        """
        Initialize guards with context.

        Args:
            context: Guard context with config and requirements
        """
        self.context = context

    def check_all(self) -> Result[None, GuardError]:
        """
        Run all precondition checks.

        Returns:
            Result indicating success or first failure
        """
        logger.info("running_guards")

        # Check API key if generation is required
        if self.context.require_generation:
            result = self.check_api_key()
            if result.is_err():
                return result

        # Check templates directory
        if self.context.require_templates and self.context.config.templates_dir:
            result = self.check_templates_dir(self.context.config.templates_dir)
            if result.is_err():
                return result

        # Check Docker if validation is required
        if self.context.require_docker:
            result = self.check_docker_available()
            if result.is_err():
                return result

        # Check output directory is writable
        if self.context.config.output_dir:
            result = self.check_output_writable(self.context.config.output_dir)
            if result.is_err():
                return result

        logger.info("guards_passed")
        return Ok(None)

    def check_api_key(self) -> Result[None, GuardError]:
        """
        Check that the Anthropic API key is set.

        Returns:
            Ok(None) if API key is present, Err(GuardError) otherwise
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            error = GuardError(
                code=ExitCode.GUARD_API_KEY,
                message="ANTHROPIC_API_KEY environment variable is not set",
                details=(
                    "The Claude API key is required for generating probe applications. "
                    "Set the ANTHROPIC_API_KEY environment variable or add the CLAUDE_API_KEY "
                    "secret to your GitHub repository settings."
                ),
            )
            logger.error(
                "guard_failed",
                guard="api_key",
                code=error.code,
                message=error.message,
            )
            return Err(error)

        # Validate API key format (basic check)
        if not api_key.startswith("sk-"):
            error = GuardError(
                code=ExitCode.GUARD_API_KEY,
                message="ANTHROPIC_API_KEY appears to be invalid",
                details=(
                    "The API key should start with 'sk-'. "
                    "Please verify your API key is correct."
                ),
            )
            logger.error(
                "guard_failed",
                guard="api_key",
                code=error.code,
                message=error.message,
            )
            return Err(error)

        logger.debug("guard_passed", guard="api_key")
        return Ok(None)

    def check_templates_dir(self, path: Path) -> Result[Path, GuardError]:
        """
        Check that the templates directory exists and contains required files.

        Args:
            path: Path to templates directory

        Returns:
            Ok(Path) with resolved path if valid, Err(GuardError) otherwise
        """
        path = Path(path)

        if not path.exists():
            error = GuardError(
                code=ExitCode.GUARD_TEMPLATES_DIR,
                message=f"Templates directory not found: {path}",
                details=(
                    "The templates directory is required for generating the dashboard. "
                    "Ensure the path is correct and the directory exists."
                ),
            )
            logger.error(
                "guard_failed",
                guard="templates_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)

        if not path.is_dir():
            error = GuardError(
                code=ExitCode.GUARD_TEMPLATES_DIR,
                message=f"Templates path is not a directory: {path}",
                details="The templates path must be a directory containing Jinja2 templates.",
            )
            logger.error(
                "guard_failed",
                guard="templates_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)

        # Check for required template files
        index_template = path / "index.html"
        if not index_template.exists():
            error = GuardError(
                code=ExitCode.GUARD_TEMPLATES_DIR,
                message=f"Required template not found: {index_template}",
                details="The templates directory must contain an index.html template.",
            )
            logger.error(
                "guard_failed",
                guard="templates_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)

        logger.debug("guard_passed", guard="templates_dir", path=str(path))
        return Ok(path.resolve())

    def check_docker_available(self) -> Result[None, GuardError]:
        """
        Check that Docker is available and running.

        Returns:
            Ok(None) if Docker is available, Err(GuardError) otherwise
        """
        # Check if docker command exists
        docker_path = shutil.which("docker")
        if docker_path is None:
            error = GuardError(
                code=ExitCode.GUARD_DOCKER,
                message="Docker is not installed or not in PATH",
                details=(
                    "Docker is required for running LocalStack containers. "
                    "Install Docker and ensure it's in your PATH."
                ),
            )
            logger.error(
                "guard_failed",
                guard="docker",
                code=error.code,
            )
            return Err(error)

        # Try to connect to Docker daemon
        try:
            import docker

            client = docker.from_env()
            client.ping()
        except Exception as e:
            error = GuardError(
                code=ExitCode.GUARD_DOCKER,
                message="Cannot connect to Docker daemon",
                details=(
                    f"Docker daemon is not running or not accessible: {e}. "
                    "Start Docker and try again."
                ),
            )
            logger.error(
                "guard_failed",
                guard="docker",
                code=error.code,
                error=str(e),
            )
            return Err(error)

        logger.debug("guard_passed", guard="docker")
        return Ok(None)

    def check_output_writable(self, path: Path) -> Result[None, GuardError]:
        """
        Check that the output directory is writable.

        Args:
            path: Path to output directory

        Returns:
            Ok(None) if directory is writable, Err(GuardError) otherwise
        """
        path = Path(path)

        # Create directory if it doesn't exist
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            error = GuardError(
                code=ExitCode.GUARD_OUTPUT_DIR,
                message=f"Cannot create output directory: {path}",
                details=f"Permission denied: {e}",
            )
            logger.error(
                "guard_failed",
                guard="output_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)
        except OSError as e:
            error = GuardError(
                code=ExitCode.GUARD_OUTPUT_DIR,
                message=f"Cannot create output directory: {path}",
                details=f"OS error: {e}",
            )
            logger.error(
                "guard_failed",
                guard="output_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)

        # Test write access
        test_file = path / ".write_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
        except PermissionError:
            error = GuardError(
                code=ExitCode.GUARD_OUTPUT_DIR,
                message=f"Output directory is not writable: {path}",
                details="Cannot write files to the output directory.",
            )
            logger.error(
                "guard_failed",
                guard="output_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)
        except OSError as e:
            error = GuardError(
                code=ExitCode.GUARD_OUTPUT_DIR,
                message=f"Output directory write test failed: {path}",
                details=f"OS error: {e}",
            )
            logger.error(
                "guard_failed",
                guard="output_dir",
                code=error.code,
                path=str(path),
            )
            return Err(error)

        logger.debug("guard_passed", guard="output_dir", path=str(path))
        return Ok(None)


def run_guards(
    config: PipelineConfig,
    require_generation: bool = True,
    require_docker: bool = True,
    require_templates: bool = True,
) -> Result[None, GuardError]:
    """
    Convenience function to run all guards.

    Args:
        config: Pipeline configuration
        require_generation: Whether code generation is needed (requires API key)
        require_docker: Whether Docker is needed (for validation)
        require_templates: Whether templates directory is needed (for reporting)

    Returns:
        Result indicating success or first guard failure
    """
    context = GuardContext(
        config=config,
        require_generation=require_generation,
        require_docker=require_docker,
        require_templates=require_templates,
    )

    guards = PipelineGuards(context)
    return guards.check_all()


def guard_error_to_status(error: GuardError) -> PipelineStatus:
    """
    Convert a GuardError to a PipelineStatus.

    Args:
        error: Guard error

    Returns:
        Corresponding PipelineStatus
    """
    status_map = {
        ExitCode.GUARD_API_KEY: PipelineStatus.FAILED_GUARD_API_KEY,
        ExitCode.GUARD_TEMPLATES_DIR: PipelineStatus.FAILED_GUARD_TEMPLATES,
        ExitCode.GUARD_DOCKER: PipelineStatus.FAILED_GUARD_DOCKER,
        ExitCode.GUARD_OUTPUT_DIR: PipelineStatus.FAILED_GUARD_OUTPUT,
    }
    return status_map.get(error.code, PipelineStatus.FAILED_GUARD_API_KEY)
