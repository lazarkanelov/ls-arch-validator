"""Result type for explicit error handling.

This module provides a Result type that forces explicit handling of success
and failure cases, eliminating silent failures throughout the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, NoReturn, TypeVar, Union

T = TypeVar("T")  # Success type
E = TypeVar("E")  # Error type
U = TypeVar("U")  # Mapped type


class ResultError(Exception):
    """Raised when unwrapping a Result fails."""

    pass


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Represents a successful result."""

    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        """Get the success value. Safe to call since this is Ok."""
        return self.value

    def unwrap_or(self, default: T) -> T:
        """Get the success value or a default."""
        return self.value

    def unwrap_or_else(self, fn: Callable[[E], T]) -> T:
        """Get the success value or compute from error."""
        return self.value

    def unwrap_err(self) -> NoReturn:
        """Get the error value. Raises since this is Ok."""
        raise ResultError(f"Called unwrap_err on Ok value: {self.value}")

    def map(self, fn: Callable[[T], U]) -> "Ok[U]":
        """Transform the success value."""
        return Ok(fn(self.value))

    def map_err(self, fn: Callable[[E], U]) -> "Ok[T]":
        """Transform the error value. No-op for Ok."""
        return self

    def and_then(self, fn: Callable[[T], "Result[U, E]"]) -> "Result[U, E]":
        """Chain another Result-returning operation."""
        return fn(self.value)

    def or_else(self, fn: Callable[[E], "Result[T, U]"]) -> "Ok[T]":
        """Chain error recovery. No-op for Ok."""
        return self

    def __repr__(self) -> str:
        return f"Ok({self.value!r})"


@dataclass(frozen=True)
class Err(Generic[E]):
    """Represents an error result."""

    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> NoReturn:
        """Get the success value. Raises since this is Err."""
        raise ResultError(f"Called unwrap on Err value: {self.error}")

    def unwrap_or(self, default: T) -> T:
        """Get the success value or a default."""
        return default

    def unwrap_or_else(self, fn: Callable[[E], T]) -> T:
        """Get the success value or compute from error."""
        return fn(self.error)

    def unwrap_err(self) -> E:
        """Get the error value. Safe to call since this is Err."""
        return self.error

    def map(self, fn: Callable[[T], U]) -> "Err[E]":
        """Transform the success value. No-op for Err."""
        return self

    def map_err(self, fn: Callable[[E], U]) -> "Err[U]":
        """Transform the error value."""
        return Err(fn(self.error))

    def and_then(self, fn: Callable[[T], "Result[U, E]"]) -> "Err[E]":
        """Chain another Result-returning operation. No-op for Err."""
        return self

    def or_else(self, fn: Callable[[E], "Result[T, U]"]) -> "Result[T, U]":
        """Chain error recovery."""
        return fn(self.error)

    def __repr__(self) -> str:
        return f"Err({self.error!r})"


# Type alias for Result
Result = Union[Ok[T], Err[E]]


# Error types for the pipeline
@dataclass(frozen=True)
class GuardError:
    """Error from a pipeline guard check."""

    code: int
    message: str
    details: str = ""

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


@dataclass(frozen=True)
class PipelineError:
    """Error from a pipeline stage."""

    stage: str
    code: int
    message: str
    cause: Exception | None = None

    def __str__(self) -> str:
        if self.cause:
            return f"[{self.stage}] {self.message}: {self.cause}"
        return f"[{self.stage}] {self.message}"


@dataclass(frozen=True)
class DashboardError:
    """Error during dashboard generation."""

    phase: str
    message: str
    cause: Exception | None = None

    def __str__(self) -> str:
        if self.cause:
            return f"Dashboard {self.phase} failed: {self.message} ({self.cause})"
        return f"Dashboard {self.phase} failed: {self.message}"


@dataclass(frozen=True)
class ConfigError:
    """Error in configuration."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"Config error in '{self.field}': {self.message}"


@dataclass(frozen=True)
class CacheError:
    """Error in cache operations."""

    operation: str
    key: str
    message: str
    cause: Exception | None = None

    def __str__(self) -> str:
        if self.cause:
            return f"Cache {self.operation} failed for '{self.key}': {self.message} ({self.cause})"
        return f"Cache {self.operation} failed for '{self.key}': {self.message}"


# Exit codes
class ExitCode:
    """Exit codes for CLI."""

    SUCCESS = 0
    GENERAL_ERROR = 1

    # Guard errors (10-19)
    GUARD_API_KEY = 10
    GUARD_TEMPLATES_DIR = 11
    GUARD_DOCKER = 12
    GUARD_OUTPUT_DIR = 13

    # Stage errors (20-29)
    MINING_FAILED = 20
    GENERATION_FAILED = 21
    VALIDATION_FAILED = 22
    REPORTING_FAILED = 23


def collect_results(results: list[Result[T, E]]) -> Result[list[T], list[E]]:
    """
    Collect a list of Results into a single Result.

    Returns Ok with all values if all are Ok, or Err with all errors if any are Err.
    """
    values = []
    errors = []

    for result in results:
        if result.is_ok():
            values.append(result.unwrap())
        else:
            errors.append(result.unwrap_err())

    if errors:
        return Err(errors)
    return Ok(values)


def first_err(results: list[Result[T, E]]) -> Result[list[T], E]:
    """
    Collect a list of Results, returning the first error if any.

    Returns Ok with all values if all are Ok, or Err with the first error.
    """
    values = []

    for result in results:
        if result.is_err():
            return Err(result.unwrap_err())
        values.append(result.unwrap())

    return Ok(values)
