"""FSM machine implementation for architecture processing."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from src.processor.states import (
    ArchitectureState,
    ArchState,
    ProcessingEvent,
    StateContext,
    TransitionError,
)
from src.utils.logging import get_logger

logger = get_logger("processor.machine")


class ProcessingMachine:
    """
    Finite State Machine for processing architectures.

    Manages state transitions, persistence, and event-driven processing.
    """

    MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 60.0  # seconds

    def __init__(
        self,
        state_file: Path,
        auto_save: bool = True,
    ) -> None:
        """
        Initialize the processing machine.

        Args:
            state_file: Path to persist state
            auto_save: Automatically save after each transition
        """
        self.state_file = Path(state_file)
        self.auto_save = auto_save

        # Architecture states indexed by arch_id
        self._states: dict[str, ArchitectureState] = {}

        # Event handlers
        self._handlers: dict[ProcessingEvent, list[Callable]] = {
            event: [] for event in ProcessingEvent
        }

        # Processing statistics
        self.stats = ProcessingStats()

        # Load existing state if available
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from file."""
        if not self.state_file.exists():
            logger.debug("no_existing_state", path=str(self.state_file))
            return

        try:
            data = json.loads(self.state_file.read_text())
            for arch_data in data.get("architectures", []):
                arch_state = ArchitectureState.from_dict(arch_data)
                self._states[arch_state.arch_id] = arch_state

            # Load stats
            if "stats" in data:
                self.stats = ProcessingStats.from_dict(data["stats"])

            logger.info(
                "state_loaded",
                architectures=len(self._states),
                path=str(self.state_file),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("state_load_failed", error=str(e))

    def save_state(self) -> None:
        """Persist current state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "saved_at": datetime.utcnow().isoformat(),
            "architectures": [
                arch.to_dict() for arch in self._states.values()
            ],
            "stats": self.stats.to_dict(),
        }

        self.state_file.write_text(json.dumps(data, indent=2))
        logger.debug("state_saved", path=str(self.state_file))

    def register_architecture(self, arch_id: str) -> ArchitectureState:
        """
        Register a new architecture for processing.

        Args:
            arch_id: Architecture identifier

        Returns:
            ArchitectureState for the architecture
        """
        if arch_id in self._states:
            return self._states[arch_id]

        arch_state = ArchitectureState(arch_id=arch_id)
        self._states[arch_id] = arch_state
        self.stats.total += 1

        if self.auto_save:
            self.save_state()

        logger.debug("architecture_registered", arch_id=arch_id)
        return arch_state

    def get_state(self, arch_id: str) -> Optional[ArchitectureState]:
        """Get state for an architecture."""
        return self._states.get(arch_id)

    def transition(
        self,
        arch_id: str,
        new_state: ArchState,
        context: Optional[StateContext] = None,
    ) -> ArchitectureState:
        """
        Transition an architecture to a new state.

        Args:
            arch_id: Architecture identifier
            new_state: Target state
            context: Optional context for the new state

        Returns:
            Updated ArchitectureState

        Raises:
            KeyError: If arch_id not registered
            TransitionError: If transition is invalid
        """
        if arch_id not in self._states:
            raise KeyError(f"Architecture not registered: {arch_id}")

        arch_state = self._states[arch_id]
        old_state = arch_state.state

        # Perform transition
        arch_state.transition_to(new_state, context)

        # Update stats
        self._update_stats(old_state, new_state)

        if self.auto_save:
            self.save_state()

        logger.info(
            "state_transition",
            arch_id=arch_id,
            from_state=old_state.name,
            to_state=new_state.name,
        )

        return arch_state

    def handle_rate_limit(
        self,
        arch_id: str,
        retry_after_seconds: float,
    ) -> ArchitectureState:
        """
        Handle rate limit for an architecture.

        Args:
            arch_id: Architecture identifier
            retry_after_seconds: Seconds until retry is allowed

        Returns:
            Updated ArchitectureState
        """
        arch_state = self._states.get(arch_id)
        if not arch_state:
            raise KeyError(f"Architecture not registered: {arch_id}")

        retry_at = datetime.utcnow() + timedelta(seconds=retry_after_seconds)
        retry_count = arch_state.context.retry_count + 1

        context = StateContext(
            retry_after=retry_at,
            retry_count=retry_count,
            error_message=f"Rate limited, retry after {retry_after_seconds}s",
            error_type="RateLimitError",
        )

        return self.transition(arch_id, ArchState.RATE_LIMITED, context)

    def handle_error(
        self,
        arch_id: str,
        error: Exception,
        recoverable: bool = False,
    ) -> ArchitectureState:
        """
        Handle an error for an architecture.

        Args:
            arch_id: Architecture identifier
            error: The exception that occurred
            recoverable: Whether the error is recoverable

        Returns:
            Updated ArchitectureState
        """
        arch_state = self._states.get(arch_id)
        if not arch_state:
            raise KeyError(f"Architecture not registered: {arch_id}")

        context = StateContext(
            error_message=str(error),
            error_type=type(error).__name__,
            retry_count=arch_state.context.retry_count,
        )

        # If recoverable and under max retries, go to rate limited
        if recoverable and arch_state.context.retry_count < self.MAX_RETRIES:
            context.retry_after = datetime.utcnow() + timedelta(
                seconds=self.DEFAULT_RETRY_DELAY
            )
            context.retry_count += 1
            return self.transition(arch_id, ArchState.RATE_LIMITED, context)

        # Otherwise, go to error state
        return self.transition(arch_id, ArchState.ERROR, context)

    def _update_stats(self, old_state: ArchState, new_state: ArchState) -> None:
        """Update processing statistics based on transition."""
        if new_state == ArchState.PASSED:
            self.stats.passed += 1
        elif new_state == ArchState.PARTIAL:
            self.stats.partial += 1
        elif new_state == ArchState.FAILED:
            self.stats.failed += 1
        elif new_state == ArchState.ERROR:
            self.stats.errors += 1
        elif new_state == ArchState.SKIPPED:
            self.stats.skipped += 1
        elif new_state == ArchState.RATE_LIMITED:
            self.stats.rate_limits += 1

    def get_pending(self) -> list[ArchitectureState]:
        """Get all architectures in PENDING state."""
        return [
            arch for arch in self._states.values()
            if arch.state == ArchState.PENDING
        ]

    def get_in_progress(self) -> list[ArchitectureState]:
        """Get all architectures in progress (non-terminal, non-pending)."""
        return [
            arch for arch in self._states.values()
            if not arch.state.is_terminal() and arch.state != ArchState.PENDING
        ]

    def get_rate_limited(self) -> list[ArchitectureState]:
        """Get all rate-limited architectures."""
        return [
            arch for arch in self._states.values()
            if arch.state == ArchState.RATE_LIMITED
        ]

    def get_ready_to_retry(self) -> list[ArchitectureState]:
        """Get rate-limited architectures ready to retry."""
        return [
            arch for arch in self._states.values()
            if arch.state == ArchState.RATE_LIMITED and arch.is_ready_to_retry()
        ]

    def get_next_retry_time(self) -> Optional[datetime]:
        """Get the earliest retry time among rate-limited architectures."""
        rate_limited = self.get_rate_limited()
        if not rate_limited:
            return None

        retry_times = [
            arch.context.retry_after
            for arch in rate_limited
            if arch.context.retry_after
        ]

        return min(retry_times) if retry_times else None

    def get_completed(self) -> list[ArchitectureState]:
        """Get all completed (terminal state) architectures."""
        return [
            arch for arch in self._states.values()
            if arch.state.is_terminal()
        ]

    def get_by_state(self, state: ArchState) -> list[ArchitectureState]:
        """Get all architectures in a specific state."""
        return [
            arch for arch in self._states.values()
            if arch.state == state
        ]

    def all_complete(self) -> bool:
        """Check if all architectures are in terminal states."""
        # Empty states means nothing registered yet - not complete
        if not self._states:
            return False
        return all(
            arch.state.is_terminal()
            for arch in self._states.values()
        )

    def progress_summary(self) -> dict[str, int]:
        """Get a summary of architectures by state."""
        summary: dict[str, int] = {}
        for arch in self._states.values():
            state_name = arch.state.name
            summary[state_name] = summary.get(state_name, 0) + 1
        return summary

    def reset_architecture(self, arch_id: str) -> ArchitectureState:
        """Reset an architecture to PENDING state."""
        if arch_id not in self._states:
            raise KeyError(f"Architecture not registered: {arch_id}")

        # Create fresh state
        self._states[arch_id] = ArchitectureState(arch_id=arch_id)

        if self.auto_save:
            self.save_state()

        return self._states[arch_id]

    def reset_all(self) -> None:
        """Reset all architectures to PENDING state."""
        for arch_id in list(self._states.keys()):
            self._states[arch_id] = ArchitectureState(arch_id=arch_id)

        self.stats = ProcessingStats()

        if self.auto_save:
            self.save_state()

    def clear(self) -> None:
        """Clear all state."""
        self._states.clear()
        self.stats = ProcessingStats()

        if self.state_file.exists():
            self.state_file.unlink()


class ProcessingStats:
    """Statistics for processing run."""

    def __init__(self) -> None:
        self.total: int = 0
        self.passed: int = 0
        self.partial: int = 0
        self.failed: int = 0
        self.errors: int = 0
        self.skipped: int = 0
        self.rate_limits: int = 0
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    @property
    def completed(self) -> int:
        """Total completed (passed + partial + failed)."""
        return self.passed + self.partial + self.failed

    @property
    def pass_rate(self) -> float:
        """Pass rate as percentage."""
        if self.completed == 0:
            return 0.0
        return (self.passed / self.completed) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "passed": self.passed,
            "partial": self.partial,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "rate_limits": self.rate_limits,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProcessingStats:
        """Create from dictionary."""
        stats = cls()
        stats.total = data.get("total", 0)
        stats.passed = data.get("passed", 0)
        stats.partial = data.get("partial", 0)
        stats.failed = data.get("failed", 0)
        stats.errors = data.get("errors", 0)
        stats.skipped = data.get("skipped", 0)
        stats.rate_limits = data.get("rate_limits", 0)
        if data.get("started_at"):
            stats.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            stats.completed_at = datetime.fromisoformat(data["completed_at"])
        return stats
