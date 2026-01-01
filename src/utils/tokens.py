"""Token budget tracker for Claude API usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger("tokens")


@dataclass
class TokenUsage:
    """
    Tracks token usage for a single API call.

    Attributes:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cache_read_tokens: Tokens read from cache
        cache_write_tokens: Tokens written to cache
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total": self.total,
        }


@dataclass
class TokenBudget:
    """
    Manages token budget for a pipeline run.

    Attributes:
        budget: Maximum tokens allowed
        used: Tokens consumed so far
        requests: Number of API requests made
        history: Usage history per request
    """

    budget: int = 500000
    used: int = 0
    requests: int = 0
    history: list[TokenUsage] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        """Tokens remaining in budget."""
        return max(0, self.budget - self.used)

    @property
    def exhausted(self) -> bool:
        """Check if budget is exhausted."""
        return self.remaining <= 0

    @property
    def utilization(self) -> float:
        """Budget utilization as a ratio."""
        return self.used / self.budget if self.budget > 0 else 1.0

    def can_afford(self, estimated_tokens: int) -> bool:
        """
        Check if we can afford an operation.

        Args:
            estimated_tokens: Estimated tokens for the operation

        Returns:
            True if operation fits within budget
        """
        return self.remaining >= estimated_tokens

    def record_usage(self, usage: TokenUsage) -> None:
        """
        Record token usage from an API call.

        Args:
            usage: Token usage from the API response
        """
        self.used += usage.total
        self.requests += 1
        self.history.append(usage)

        logger.debug(
            "token_usage",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_used=self.used,
            remaining=self.remaining,
        )

        if self.exhausted:
            logger.warning(
                "token_budget_exhausted",
                budget=self.budget,
                used=self.used,
            )

    def estimate_remaining_capacity(
        self,
        avg_tokens_per_request: Optional[int] = None,
    ) -> int:
        """
        Estimate how many more requests can be made.

        Args:
            avg_tokens_per_request: Average tokens per request (calculated from history if not provided)

        Returns:
            Estimated number of remaining requests
        """
        if avg_tokens_per_request is None:
            if self.requests > 0:
                avg_tokens_per_request = self.used // self.requests
            else:
                avg_tokens_per_request = 5000  # Default estimate

        if avg_tokens_per_request <= 0:
            return 0

        return self.remaining // avg_tokens_per_request

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "budget": self.budget,
            "used": self.used,
            "remaining": self.remaining,
            "requests": self.requests,
            "utilization": round(self.utilization, 4),
            "exhausted": self.exhausted,
        }

    def summary(self) -> str:
        """Get a human-readable summary."""
        return (
            f"Token Budget: {self.used:,}/{self.budget:,} "
            f"({self.utilization:.1%} used, {self.remaining:,} remaining)"
        )


class TokenTracker:
    """
    Singleton tracker for managing token budget across a run.

    Usage:
        tracker = TokenTracker(budget=500000)
        if tracker.can_afford(5000):
            response = await client.messages.create(...)
            tracker.record(response.usage)
    """

    _instance: Optional["TokenTracker"] = None

    def __init__(self, budget: int = 500000) -> None:
        """Initialize the tracker with a budget."""
        self._budget = TokenBudget(budget=budget)

    @classmethod
    def get_instance(cls, budget: Optional[int] = None) -> "TokenTracker":
        """
        Get the singleton instance.

        Args:
            budget: Optional budget to set (only used on first call)

        Returns:
            The singleton TokenTracker instance
        """
        if cls._instance is None:
            cls._instance = cls(budget=budget or 500000)
        return cls._instance

    @classmethod
    def reset(cls, budget: int = 500000) -> "TokenTracker":
        """
        Reset the singleton with a new budget.

        Args:
            budget: New budget to set

        Returns:
            Fresh TokenTracker instance
        """
        cls._instance = cls(budget=budget)
        return cls._instance

    @property
    def budget(self) -> TokenBudget:
        """Get the underlying budget object."""
        return self._budget

    def can_afford(self, estimated_tokens: int) -> bool:
        """Check if we can afford an operation."""
        return self._budget.can_afford(estimated_tokens)

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        """
        Record token usage.

        Args:
            input_tokens: Input tokens used
            output_tokens: Output tokens used
            cache_read_tokens: Cache read tokens (if using prompt caching)
            cache_write_tokens: Cache write tokens (if using prompt caching)
        """
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        self._budget.record_usage(usage)

    def record_from_response(self, usage) -> None:
        """
        Record token usage from an API response.

        Args:
            usage: Usage object or dict from response (e.g., response.usage)
        """
        # Handle both object attributes and dict access
        def get_value(obj, key, default=0):
            if hasattr(obj, key):
                return getattr(obj, key, default) or default
            elif isinstance(obj, dict):
                return obj.get(key, default) or default
            return default

        self.record(
            input_tokens=get_value(usage, "input_tokens"),
            output_tokens=get_value(usage, "output_tokens"),
            cache_read_tokens=get_value(usage, "cache_read_input_tokens"),
            cache_write_tokens=get_value(usage, "cache_creation_input_tokens"),
        )

    @property
    def used(self) -> int:
        """Total tokens used."""
        return self._budget.used

    @property
    def remaining(self) -> int:
        """Tokens remaining."""
        return self._budget.remaining

    @property
    def exhausted(self) -> bool:
        """Check if budget is exhausted."""
        return self._budget.exhausted

    def summary(self) -> str:
        """Get a human-readable summary."""
        return self._budget.summary()

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return self._budget.to_dict()
