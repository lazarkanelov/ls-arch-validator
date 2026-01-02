"""FSM-based architecture processing module.

This module provides a Finite State Machine (FSM) approach to processing
architectures through the validation pipeline. Instead of relying on
timeouts and arbitrary delays, each architecture transitions through
well-defined states:

    PENDING -> MINING -> MINED -> GENERATING -> GENERATED -> VALIDATING -> VALIDATED
                                      |
                                      v
                                RATE_LIMITED (waits for retry-after, then back to GENERATING)

Terminal states: PASSED, PARTIAL, FAILED, ERROR, SKIPPED

Benefits:
- Explicit state transitions with validation
- Graceful rate limit handling without arbitrary delays
- Persistent state for resumability
- Clear observability into processing progress
- Event-driven, not polling-based
"""

from src.processor.machine import ProcessingMachine, ProcessingStats
from src.processor.runner import (
    ArchitectureProcessor,
    ProcessorConfig,
    run_processor,
)
from src.processor.states import (
    ArchitectureState,
    ArchState,
    ProcessingEvent,
    StateContext,
    TransitionError,
    TRANSITIONS,
)

__all__ = [
    # States
    "ArchState",
    "ArchitectureState",
    "StateContext",
    "ProcessingEvent",
    "TransitionError",
    "TRANSITIONS",
    # Machine
    "ProcessingMachine",
    "ProcessingStats",
    # Runner
    "ArchitectureProcessor",
    "ProcessorConfig",
    "run_processor",
]
