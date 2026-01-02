"""FSM state definitions for architecture processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional


class ArchState(Enum):
    """States for architecture processing FSM."""

    # Initial state
    PENDING = auto()

    # Mining phase
    MINING = auto()
    MINED = auto()

    # Generation phase (Claude API)
    GENERATING = auto()
    GENERATED = auto()

    # Rate limit handling
    RATE_LIMITED = auto()

    # Validation phase (LocalStack)
    VALIDATING = auto()
    VALIDATED = auto()

    # Terminal states
    PASSED = auto()
    PARTIAL = auto()
    FAILED = auto()
    ERROR = auto()
    SKIPPED = auto()

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (
            ArchState.PASSED,
            ArchState.PARTIAL,
            ArchState.FAILED,
            ArchState.ERROR,
            ArchState.SKIPPED,
        )

    def is_error(self) -> bool:
        """Check if this is an error state."""
        return self in (ArchState.ERROR, ArchState.FAILED)

    def is_success(self) -> bool:
        """Check if this is a success state."""
        return self in (ArchState.PASSED, ArchState.PARTIAL)


# Valid state transitions
TRANSITIONS: dict[ArchState, set[ArchState]] = {
    ArchState.PENDING: {ArchState.MINING, ArchState.SKIPPED},
    ArchState.MINING: {ArchState.MINED, ArchState.ERROR},
    ArchState.MINED: {ArchState.GENERATING, ArchState.SKIPPED},
    ArchState.GENERATING: {
        ArchState.GENERATED,
        ArchState.RATE_LIMITED,
        ArchState.ERROR,
    },
    ArchState.RATE_LIMITED: {ArchState.GENERATING},  # Retry generation
    ArchState.GENERATED: {ArchState.VALIDATING, ArchState.ERROR},
    ArchState.VALIDATING: {ArchState.VALIDATED, ArchState.ERROR},
    ArchState.VALIDATED: {
        ArchState.PASSED,
        ArchState.PARTIAL,
        ArchState.FAILED,
    },
    # Terminal states have no transitions
    ArchState.PASSED: set(),
    ArchState.PARTIAL: set(),
    ArchState.FAILED: set(),
    ArchState.ERROR: set(),
    ArchState.SKIPPED: set(),
}


class TransitionError(Exception):
    """Invalid state transition."""

    def __init__(self, from_state: ArchState, to_state: ArchState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition: {from_state.name} -> {to_state.name}"
        )


@dataclass
class StateContext:
    """Context data for a state transition."""

    # Timing
    entered_at: datetime = field(default_factory=datetime.utcnow)
    retry_after: Optional[datetime] = None  # For RATE_LIMITED state

    # Error info
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    retry_count: int = 0

    # Result data
    result_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "entered_at": self.entered_at.isoformat(),
            "retry_after": self.retry_after.isoformat() if self.retry_after else None,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "result_data": self.result_data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StateContext:
        """Create from dictionary."""
        return cls(
            entered_at=datetime.fromisoformat(data["entered_at"]),
            retry_after=(
                datetime.fromisoformat(data["retry_after"])
                if data.get("retry_after")
                else None
            ),
            error_message=data.get("error_message"),
            error_type=data.get("error_type"),
            retry_count=data.get("retry_count", 0),
            result_data=data.get("result_data", {}),
        )


@dataclass
class ArchitectureState:
    """Complete state for an architecture in the FSM."""

    arch_id: str
    state: ArchState = ArchState.PENDING
    context: StateContext = field(default_factory=StateContext)

    # History of state transitions
    history: list[tuple[str, str]] = field(default_factory=list)

    # Cached data from processing
    architecture: Optional[Any] = None  # Architecture object
    synthesis_result: Optional[Any] = None  # SynthesisResult from generation
    validation_result: Optional[Any] = None  # ValidationResult from testing

    def can_transition_to(self, new_state: ArchState) -> bool:
        """Check if transition to new_state is valid."""
        return new_state in TRANSITIONS.get(self.state, set())

    def transition_to(
        self,
        new_state: ArchState,
        context: Optional[StateContext] = None,
    ) -> None:
        """
        Transition to a new state.

        Args:
            new_state: Target state
            context: Optional new context for the state

        Raises:
            TransitionError: If transition is invalid
        """
        if not self.can_transition_to(new_state):
            raise TransitionError(self.state, new_state)

        # Record transition in history
        self.history.append((
            self.state.name,
            datetime.utcnow().isoformat(),
        ))

        # Update state
        self.state = new_state
        self.context = context or StateContext()

    def is_ready_to_retry(self) -> bool:
        """Check if rate-limited state is ready to retry."""
        if self.state != ArchState.RATE_LIMITED:
            return False

        if self.context.retry_after is None:
            return True

        return datetime.utcnow() >= self.context.retry_after

    def time_until_retry(self) -> float:
        """Get seconds until retry is allowed (0 if ready now)."""
        if self.state != ArchState.RATE_LIMITED:
            return 0.0

        if self.context.retry_after is None:
            return 0.0

        delta = (self.context.retry_after - datetime.utcnow()).total_seconds()
        return max(0.0, delta)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "arch_id": self.arch_id,
            "state": self.state.name,
            "context": self.context.to_dict(),
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArchitectureState:
        """Create from dictionary."""
        return cls(
            arch_id=data["arch_id"],
            state=ArchState[data["state"]],
            context=StateContext.from_dict(data["context"]),
            history=data.get("history", []),
        )


# Event types that trigger transitions
class ProcessingEvent(Enum):
    """Events that can trigger state transitions."""

    # Mining events
    START_MINING = auto()
    MINING_COMPLETE = auto()
    MINING_FAILED = auto()

    # Generation events
    START_GENERATION = auto()
    GENERATION_COMPLETE = auto()
    GENERATION_FAILED = auto()
    RATE_LIMIT_HIT = auto()
    RATE_LIMIT_CLEARED = auto()

    # Validation events
    START_VALIDATION = auto()
    VALIDATION_COMPLETE = auto()
    VALIDATION_FAILED = auto()

    # Result events
    TESTS_PASSED = auto()
    TESTS_PARTIAL = auto()
    TESTS_FAILED = auto()

    # Control events
    SKIP = auto()
    RESET = auto()
