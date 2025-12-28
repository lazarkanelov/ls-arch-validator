"""Structured JSON logging utility with correlation ID support."""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import structlog

# Context variable for correlation ID propagation
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
run_id_var: ContextVar[str] = ContextVar("run_id", default="")
stage_var: ContextVar[str] = ContextVar("stage", default="")


def get_correlation_id() -> str:
    """Get the current correlation ID, generating one if not set."""
    cid = correlation_id_var.get()
    if not cid:
        cid = str(uuid.uuid4())[:8]
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current context."""
    correlation_id_var.set(cid)


def set_run_context(run_id: str, stage: str = "") -> None:
    """Set the run context for logging."""
    run_id_var.set(run_id)
    if stage:
        stage_var.set(stage)


def set_stage(stage: str) -> None:
    """Set the current pipeline stage."""
    stage_var.set(stage)


def add_context_info(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add correlation ID and run context to log events."""
    cid = correlation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid

    run_id = run_id_var.get()
    if run_id:
        event_dict["run_id"] = run_id

    stage = stage_var.get()
    if stage:
        event_dict["stage"] = stage

    return event_dict


def add_timestamp(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add ISO format timestamp to log events."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def configure_logging(
    level: str = "info",
    format_type: str = "json",
    stream: Any = None,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Log level (debug, info, warn, error)
        format_type: Output format ('json' or 'text')
        stream: Output stream (default: sys.stderr)
    """
    if stream is None:
        stream = sys.stderr

    # Map string level to logging constant
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    log_level = level_map.get(level.lower(), logging.INFO)

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=log_level,
    )

    # Build processor chain
    processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        add_timestamp,
        add_context_info,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add appropriate renderer based on format
    if format_type == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.

    Args:
        name: Optional logger name for context

    Returns:
        Configured structlog logger
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger_name=name)
    return logger


class LogContext:
    """Context manager for adding temporary log context."""

    def __init__(self, **kwargs: Any) -> None:
        self.context = kwargs
        self._token: Any = None

    def __enter__(self) -> "LogContext":
        # Store context for the duration
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def log_stage_timing(stage: str, duration_seconds: float) -> None:
    """Log timing information for a pipeline stage."""
    logger = get_logger("timing")
    logger.info(
        "stage_completed",
        stage=stage,
        duration_seconds=round(duration_seconds, 3),
    )


def log_validation_result(
    arch_id: str,
    status: str,
    duration_seconds: float,
    tests_passed: int = 0,
    tests_failed: int = 0,
) -> None:
    """Log a validation result."""
    logger = get_logger("validation")
    logger.info(
        "validation_completed",
        architecture_id=arch_id,
        status=status,
        duration_seconds=round(duration_seconds, 3),
        tests_passed=tests_passed,
        tests_failed=tests_failed,
    )


# Initialize with defaults on import
configure_logging()
