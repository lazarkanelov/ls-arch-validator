"""Sample application generator module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from src.generator.analyzer import InfrastructureAnalysis, TerraformAnalyzer
from src.generator.prompts import format_generation_prompt, format_test_prompt
from src.generator.synthesizer import CodeSynthesizer, SynthesisResult
from src.generator.validator import CodeValidator, ValidationResult, validate_all_files
from src.models import Architecture, SampleApp
from src.utils.cache import AppCache
from src.utils.logging import get_logger
from src.utils.tokens import TokenTracker

logger = get_logger("generator")


class GenerationResult:
    """Result of generating sample applications."""

    def __init__(self) -> None:
        self.apps: list[SampleApp] = []
        self.errors: list[str] = []
        self.skipped: list[str] = []
        self.tokens_used: int = 0

    @property
    def success(self) -> bool:
        """Check if generation was successful."""
        return len(self.apps) > 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "apps_generated": len(self.apps),
            "errors": len(self.errors),
            "skipped": len(self.skipped),
            "tokens_used": self.tokens_used,
        }


async def generate_all(
    architectures: list[Architecture],
    cache_dir: Path,
    skip_cache: bool = False,
    validate_only: bool = False,
    token_budget: Optional[int] = None,
) -> GenerationResult:
    """
    Generate sample applications for all architectures.

    Args:
        architectures: List of architectures to generate apps for
        cache_dir: Directory for caching
        skip_cache: Force regeneration
        validate_only: Only validate, don't save
        token_budget: Maximum tokens to use

    Returns:
        GenerationResult with generated apps
    """
    result = GenerationResult()

    # Initialize token tracker with budget
    if token_budget:
        TokenTracker.reset(budget=token_budget)
    tracker = TokenTracker.get_instance()

    # Initialize synthesizer
    synthesizer = CodeSynthesizer(cache_dir=str(cache_dir))
    validator = CodeValidator()

    logger.info(
        "generation_started",
        architectures=len(architectures),
        token_budget=tracker.budget.budget,
    )

    for arch in architectures:
        # Check token budget
        if tracker.exhausted:
            logger.warning("token_budget_exhausted", remaining=tracker.remaining)
            result.skipped.append(arch.id)
            continue

        try:
            # Generate application
            synthesis = await synthesizer.synthesize(arch, skip_cache=skip_cache)

            if not synthesis.success:
                result.errors.extend(
                    f"{arch.id}: {e}" for e in synthesis.errors
                )
                continue

            result.tokens_used += synthesis.tokens_used

            # Validate generated code
            validation = validate_all_files(
                synthesis.source_code,
                synthesis.test_code,
            )

            if validation.has_errors:
                result.errors.append(
                    f"{arch.id}: Validation failed - {validation.syntax_errors}"
                )
                continue

            if validate_only:
                logger.info("validation_only", arch_id=arch.id, valid=True)
                continue

            # Create SampleApp
            app = synthesizer.create_sample_app(arch, synthesis)
            result.apps.append(app)

            logger.debug(
                "app_generated",
                arch_id=arch.id,
                source_files=len(synthesis.source_code),
                test_files=len(synthesis.test_code),
            )

        except Exception as e:
            error_msg = f"{arch.id}: {e}"
            result.errors.append(error_msg)
            logger.error("generation_failed", arch_id=arch.id, error=str(e))

    logger.info(
        "generation_completed",
        apps=len(result.apps),
        errors=len(result.errors),
        skipped=len(result.skipped),
        tokens_used=result.tokens_used,
    )

    return result


__all__ = [
    # Main function
    "generate_all",
    "GenerationResult",
    # Analyzer
    "TerraformAnalyzer",
    "InfrastructureAnalysis",
    # Synthesizer
    "CodeSynthesizer",
    "SynthesisResult",
    # Validator
    "CodeValidator",
    "ValidationResult",
    "validate_all_files",
    # Prompts
    "format_generation_prompt",
    "format_test_prompt",
]
