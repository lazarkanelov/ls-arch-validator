"""Centralized configuration for the validation pipeline.

All configuration values that were previously hardcoded are now centralized here.
Configuration can be loaded from YAML files and validated at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from src.utils.result import ConfigError, Err, Ok, Result


# Cache version - increment when cache format changes
CACHE_VERSION = "2.0"


@dataclass
class TimeoutConfig:
    """Timeout settings for various operations."""

    # LocalStack
    localstack_start: int = 120

    # Terraform
    terraform_init: int = 60
    terraform_apply: int = 300
    terraform_destroy: int = 120

    # Testing
    test_execution: int = 180
    per_architecture: int = 600

    # Diagrams
    diagram_scrape: int = 60
    diagram_parse: int = 30

    # Mining
    git_clone: int = 120
    template_conversion: int = 60

    # API calls
    generation_request: int = 120
    vision_request: int = 60


@dataclass
class RetryConfig:
    """Retry and backoff settings."""

    max_attempts: int = 3
    backoff_factor: float = 2.0
    max_backoff: float = 60.0
    rate_limit_base_delay: float = 35.0


@dataclass
class ContainerConfig:
    """Docker container resource limits."""

    mem_limit: str = "2g"
    memswap_limit: str = "2g"
    cpu_period: int = 100000
    cpu_quota: int = 100000
    pids_limit: int = 256


@dataclass
class LocalStackConfig:
    """LocalStack-specific settings."""

    image: str = "localstack/localstack:latest"
    base_port: int = 4566
    endpoint_template: str = "http://{host}:{port}"
    services: str = "lambda,s3,dynamodb,sqs,sns,apigateway,events,stepfunctions"
    debug: bool = False
    lambda_executor: str = "docker"


@dataclass
class StorageConfig:
    """Storage and retention settings."""

    retention_days: int = 90
    max_storage_gb: float = 10.0
    cache_version: str = CACHE_VERSION


@dataclass
class LoggingConfig:
    """Logging settings."""

    level: str = "info"
    format: str = "json"


@dataclass
class PipelineConfig:
    """
    Complete pipeline configuration.

    This is the single source of truth for all configuration values.
    Previously hardcoded values are now here with documented defaults.
    """

    # Execution settings
    parallelism: int = 4
    token_budget: int = 500000

    # Sub-configurations
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    container: ContainerConfig = field(default_factory=ContainerConfig)
    localstack: LocalStackConfig = field(default_factory=LocalStackConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Paths (set at runtime)
    config_dir: Optional[Path] = None
    cache_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    templates_dir: Optional[Path] = None

    # Behavior flags
    require_api_key_for_generation: bool = True
    fail_on_empty_results: bool = True

    @classmethod
    def from_yaml(cls, path: Path) -> Result["PipelineConfig", ConfigError]:
        """
        Load configuration from a YAML file.

        Args:
            path: Path to YAML configuration file

        Returns:
            Result with loaded config or error
        """
        path = Path(path)

        if not path.exists():
            return Err(ConfigError(
                field="path",
                message=f"Configuration file not found: {path}",
            ))

        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            return Err(ConfigError(
                field="yaml",
                message=f"Failed to parse YAML: {e}",
            ))
        except Exception as e:
            return Err(ConfigError(
                field="file",
                message=f"Failed to read config file: {e}",
            ))

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Result["PipelineConfig", ConfigError]:
        """
        Create configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            Result with loaded config or error
        """
        try:
            # Parse sub-configurations
            timeouts_data = data.get("timeouts", {})
            timeouts = TimeoutConfig(
                localstack_start=timeouts_data.get("localstack_start", 120),
                terraform_init=timeouts_data.get("terraform_init", 60),
                terraform_apply=timeouts_data.get("terraform_apply", 300),
                terraform_destroy=timeouts_data.get("terraform_destroy", 120),
                test_execution=timeouts_data.get("test_execution", 180),
                per_architecture=timeouts_data.get("per_architecture", 600),
                diagram_scrape=timeouts_data.get("diagram_scrape", 60),
                diagram_parse=timeouts_data.get("diagram_parse", 30),
                git_clone=timeouts_data.get("git_clone", 120),
                template_conversion=timeouts_data.get("template_conversion", 60),
                generation_request=timeouts_data.get("generation_request", 120),
                vision_request=timeouts_data.get("vision_request", 60),
            )

            retry_data = data.get("retries", data.get("retry", {}))
            retry = RetryConfig(
                max_attempts=retry_data.get("max_attempts", 3),
                backoff_factor=float(retry_data.get("backoff_factor", 2.0)),
                max_backoff=float(retry_data.get("max_backoff", 60.0)),
                rate_limit_base_delay=float(retry_data.get("rate_limit_base_delay", 35.0)),
            )

            container_data = data.get("container_limits", {})
            container = ContainerConfig(
                mem_limit=container_data.get("mem_limit", "2g"),
                memswap_limit=container_data.get("memswap_limit", "2g"),
                cpu_period=container_data.get("cpu_period", 100000),
                cpu_quota=container_data.get("cpu_quota", 100000),
                pids_limit=container_data.get("pids_limit", 256),
            )

            localstack_data = data.get("localstack", {})
            localstack = LocalStackConfig(
                image=localstack_data.get("image", "localstack/localstack:latest"),
                base_port=localstack_data.get("base_port", 4566),
                endpoint_template=localstack_data.get("endpoint_template", "http://{host}:{port}"),
                services=localstack_data.get("services", "lambda,s3,dynamodb,sqs,sns,apigateway,events,stepfunctions"),
                debug=localstack_data.get("debug", False),
                lambda_executor=localstack_data.get("lambda_executor", "docker"),
            )

            storage = StorageConfig(
                retention_days=data.get("retention_days", 90),
                max_storage_gb=float(data.get("max_storage_gb", 10.0)),
                cache_version=data.get("cache_version", CACHE_VERSION),
            )

            logging_data = data.get("logging", {})
            logging_config = LoggingConfig(
                level=logging_data.get("level", "info"),
                format=logging_data.get("format", "json"),
            )

            config = cls(
                parallelism=data.get("parallelism", 4),
                token_budget=data.get("token_budget", 500000),
                timeouts=timeouts,
                retry=retry,
                container=container,
                localstack=localstack,
                storage=storage,
                logging=logging_config,
                require_api_key_for_generation=data.get("require_api_key_for_generation", True),
                fail_on_empty_results=data.get("fail_on_empty_results", True),
            )

            return Ok(config)

        except Exception as e:
            return Err(ConfigError(
                field="unknown",
                message=f"Failed to parse configuration: {e}",
            ))

    def validate(self) -> Result[None, ConfigError]:
        """
        Validate configuration values.

        Returns:
            Result indicating success or validation error
        """
        # Validate parallelism
        if self.parallelism < 1:
            return Err(ConfigError(
                field="parallelism",
                message=f"Must be at least 1, got {self.parallelism}",
            ))
        if self.parallelism > 16:
            return Err(ConfigError(
                field="parallelism",
                message=f"Must be at most 16, got {self.parallelism}",
            ))

        # Validate token budget
        if self.token_budget < 1000:
            return Err(ConfigError(
                field="token_budget",
                message=f"Must be at least 1000, got {self.token_budget}",
            ))

        # Validate timeouts are positive
        for name, value in [
            ("localstack_start", self.timeouts.localstack_start),
            ("terraform_apply", self.timeouts.terraform_apply),
            ("test_execution", self.timeouts.test_execution),
            ("per_architecture", self.timeouts.per_architecture),
        ]:
            if value < 1:
                return Err(ConfigError(
                    field=f"timeouts.{name}",
                    message=f"Must be positive, got {value}",
                ))

        # Validate retry settings
        if self.retry.max_attempts < 1:
            return Err(ConfigError(
                field="retry.max_attempts",
                message=f"Must be at least 1, got {self.retry.max_attempts}",
            ))
        if self.retry.backoff_factor < 1.0:
            return Err(ConfigError(
                field="retry.backoff_factor",
                message=f"Must be at least 1.0, got {self.retry.backoff_factor}",
            ))

        # Validate storage
        if self.storage.retention_days < 1:
            return Err(ConfigError(
                field="storage.retention_days",
                message=f"Must be at least 1, got {self.storage.retention_days}",
            ))
        if self.storage.max_storage_gb < 0.1:
            return Err(ConfigError(
                field="storage.max_storage_gb",
                message=f"Must be at least 0.1, got {self.storage.max_storage_gb}",
            ))

        return Ok(None)

    def get_localstack_endpoint(self, host: str = "localhost", port: int = None) -> str:
        """
        Get the LocalStack endpoint URL.

        Args:
            host: Host name
            port: Port number (uses base_port if not specified)

        Returns:
            Formatted endpoint URL
        """
        if port is None:
            port = self.localstack.base_port
        return self.localstack.endpoint_template.format(host=host, port=port)

    def with_paths(
        self,
        config_dir: Path = None,
        cache_dir: Path = None,
        output_dir: Path = None,
        templates_dir: Path = None,
    ) -> "PipelineConfig":
        """
        Return a new config with updated paths.

        Args:
            config_dir: Configuration directory
            cache_dir: Cache directory
            output_dir: Output directory
            templates_dir: Templates directory

        Returns:
            New PipelineConfig with updated paths
        """
        return PipelineConfig(
            parallelism=self.parallelism,
            token_budget=self.token_budget,
            timeouts=self.timeouts,
            retry=self.retry,
            container=self.container,
            localstack=self.localstack,
            storage=self.storage,
            logging=self.logging,
            config_dir=config_dir or self.config_dir,
            cache_dir=cache_dir or self.cache_dir,
            output_dir=output_dir or self.output_dir,
            templates_dir=templates_dir or self.templates_dir,
            require_api_key_for_generation=self.require_api_key_for_generation,
            fail_on_empty_results=self.fail_on_empty_results,
        )


def load_config(config_dir: Path = None) -> Result[PipelineConfig, ConfigError]:
    """
    Load configuration from the standard location.

    Loads from config/defaults.yaml, then overlays config/timeouts.yaml if present.

    Args:
        config_dir: Configuration directory (defaults to ./config)

    Returns:
        Result with loaded config or error
    """
    if config_dir is None:
        config_dir = Path("./config")

    config_dir = Path(config_dir)

    # Load defaults
    defaults_path = config_dir / "defaults.yaml"
    if defaults_path.exists():
        result = PipelineConfig.from_yaml(defaults_path)
        if result.is_err():
            return result
        config = result.unwrap()
    else:
        # Use defaults if no config file
        config = PipelineConfig()

    # Overlay timeouts if present
    timeouts_path = config_dir / "timeouts.yaml"
    if timeouts_path.exists():
        try:
            with open(timeouts_path) as f:
                timeouts_data = yaml.safe_load(f) or {}

            # Update timeouts from overlay
            if "timeouts" in timeouts_data:
                td = timeouts_data["timeouts"]
                config.timeouts = TimeoutConfig(
                    localstack_start=td.get("localstack_start", config.timeouts.localstack_start),
                    terraform_init=td.get("terraform_init", config.timeouts.terraform_init),
                    terraform_apply=td.get("terraform_apply", config.timeouts.terraform_apply),
                    terraform_destroy=td.get("terraform_destroy", config.timeouts.terraform_destroy),
                    test_execution=td.get("test_execution", config.timeouts.test_execution),
                    per_architecture=td.get("per_architecture", config.timeouts.per_architecture),
                    diagram_scrape=td.get("diagram_scrape", config.timeouts.diagram_scrape),
                    diagram_parse=td.get("diagram_parse", config.timeouts.diagram_parse),
                    git_clone=td.get("git_clone", config.timeouts.git_clone),
                    template_conversion=td.get("template_conversion", config.timeouts.template_conversion),
                    generation_request=td.get("generation_request", config.timeouts.generation_request),
                    vision_request=td.get("vision_request", config.timeouts.vision_request),
                )

            # Update retry settings if present
            if "retries" in timeouts_data:
                rd = timeouts_data["retries"]
                config.retry = RetryConfig(
                    max_attempts=rd.get("max_attempts", config.retry.max_attempts),
                    backoff_factor=float(rd.get("backoff_factor", config.retry.backoff_factor)),
                    max_backoff=float(rd.get("max_backoff", config.retry.max_backoff)),
                    rate_limit_base_delay=config.retry.rate_limit_base_delay,
                )

        except Exception as e:
            return Err(ConfigError(
                field="timeouts_overlay",
                message=f"Failed to load timeouts overlay: {e}",
            ))

    # Validate final config
    validation_result = config.validate()
    if validation_result.is_err():
        return Err(validation_result.unwrap_err())

    return Ok(config)


def get_env_api_key() -> Optional[str]:
    """Get the Anthropic API key from environment."""
    return os.environ.get("ANTHROPIC_API_KEY")


def get_env_github_token() -> Optional[str]:
    """Get the GitHub token from environment."""
    return os.environ.get("GITHUB_TOKEN")
