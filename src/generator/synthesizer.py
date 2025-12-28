"""Code synthesizer using Claude API."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.generator.analyzer import InfrastructureAnalysis, TerraformAnalyzer
from src.generator.prompts import (
    SYSTEM_PROMPT,
    format_generation_prompt,
    format_test_prompt,
)
from src.models import Architecture, SampleApp
from src.utils.cache import AppCache
from src.utils.logging import get_logger
from src.utils.tokens import TokenTracker

logger = get_logger("generator.synthesizer")


@dataclass
class SynthesisResult:
    """Result of synthesizing a sample application."""

    source_code: dict[str, str] = field(default_factory=dict)
    test_code: dict[str, str] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tokens_used: int = 0

    @property
    def success(self) -> bool:
        """Check if synthesis was successful."""
        return len(self.source_code) > 0 and len(self.errors) == 0


class CodeSynthesizer:
    """
    Synthesizes Python sample applications using Claude API.

    Generates source code and tests that exercise the infrastructure
    defined in Terraform configurations.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        cache_dir: Optional[str] = None,
    ) -> None:
        """
        Initialize the synthesizer.

        Args:
            api_key: Anthropic API key
            model: Claude model to use
            cache_dir: Directory for caching generated apps
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.cache = AppCache(cache_dir) if cache_dir else None
        self.analyzer = TerraformAnalyzer()
        self._client = None

    async def _get_client(self):
        """Get or create Anthropic client."""
        if self._client is None:
            import anthropic

            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")

            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)

        return self._client

    async def synthesize(
        self,
        architecture: Architecture,
        skip_cache: bool = False,
    ) -> SynthesisResult:
        """
        Synthesize a sample application for an architecture.

        Args:
            architecture: Architecture to generate app for
            skip_cache: Skip cache check

        Returns:
            SynthesisResult with generated code
        """
        result = SynthesisResult()

        # Check cache
        if self.cache and not skip_cache:
            cached = self.cache.load_app(architecture.content_hash)
            if cached:
                logger.debug("using_cached_app", arch_id=architecture.id)
                return SynthesisResult(
                    source_code=cached.get("source_code", {}),
                    test_code=cached.get("test_code", {}),
                    requirements=cached.get("requirements", []),
                )

        # Check token budget
        tracker = TokenTracker.get_instance()
        estimated_tokens = 8000  # Approximate tokens for generation

        if not tracker.can_afford(estimated_tokens):
            logger.warning(
                "token_budget_exhausted",
                arch_id=architecture.id,
                remaining=tracker.remaining,
            )
            result.errors.append("Token budget exhausted")
            return result

        try:
            # Analyze infrastructure
            analysis = self.analyzer.analyze(architecture.main_tf)

            # Generate source code
            source_result = await self._generate_source_code(
                analysis,
                architecture.main_tf,
            )
            result.source_code = source_result.get("files", {})
            result.requirements = source_result.get("requirements", [])
            result.tokens_used += source_result.get("tokens", 0)

            if not result.source_code:
                result.errors.append("Failed to generate source code")
                return result

            # Generate tests
            app_code = result.source_code.get("src/app.py", "")
            test_result = await self._generate_tests(analysis, app_code)
            result.test_code = test_result.get("files", {})
            result.requirements.extend(test_result.get("requirements", []))
            result.tokens_used += test_result.get("tokens", 0)

            # Deduplicate requirements
            result.requirements = list(set(result.requirements))

            # Cache result
            if self.cache and result.success:
                self.cache.save_app(
                    content_hash=architecture.content_hash,
                    source_code=result.source_code,
                    test_code=result.test_code,
                    requirements=result.requirements,
                    metadata={
                        "architecture_id": architecture.id,
                        "services": list(analysis.services),
                    },
                )

            logger.info(
                "synthesis_completed",
                arch_id=architecture.id,
                source_files=len(result.source_code),
                test_files=len(result.test_code),
                tokens=result.tokens_used,
            )

        except Exception as e:
            error_msg = f"Synthesis failed: {e}"
            result.errors.append(error_msg)
            logger.error("synthesis_failed", arch_id=architecture.id, error=str(e))

        return result

    async def _generate_source_code(
        self,
        analysis: InfrastructureAnalysis,
        terraform_content: str,
    ) -> dict[str, Any]:
        """
        Generate source code using Claude.

        Args:
            analysis: Infrastructure analysis
            terraform_content: Terraform HCL content

        Returns:
            Dict with files and requirements
        """
        prompt = format_generation_prompt(analysis, terraform_content)

        try:
            client = await self._get_client()

            response = await client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Track token usage
            tracker = TokenTracker.get_instance()
            tracker.record_from_response(response.usage)

            # Parse response
            content = response.content[0].text
            result = self._parse_json_response(content)
            result["tokens"] = response.usage.input_tokens + response.usage.output_tokens

            return result

        except Exception as e:
            logger.error("source_generation_failed", error=str(e))
            return {"files": {}, "requirements": [], "tokens": 0}

    async def _generate_tests(
        self,
        analysis: InfrastructureAnalysis,
        app_code: str,
    ) -> dict[str, Any]:
        """
        Generate test code using Claude.

        Args:
            analysis: Infrastructure analysis
            app_code: Generated application code

        Returns:
            Dict with test files and requirements
        """
        prompt = format_test_prompt(analysis, app_code)

        try:
            client = await self._get_client()

            response = await client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Track token usage
            tracker = TokenTracker.get_instance()
            tracker.record_from_response(response.usage)

            # Parse response
            content = response.content[0].text
            result = self._parse_json_response(content)
            result["tokens"] = response.usage.input_tokens + response.usage.output_tokens

            return result

        except Exception as e:
            logger.error("test_generation_failed", error=str(e))
            return {"files": {}, "requirements": [], "tokens": 0}

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """
        Parse JSON from Claude's response.

        Args:
            content: Response text

        Returns:
            Parsed JSON or empty dict
        """
        # Try to extract JSON from markdown code block
        json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_str = content

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("json_parse_failed", content=content[:200])
            return {"files": {}, "requirements": []}

    def create_sample_app(
        self,
        architecture: Architecture,
        result: SynthesisResult,
    ) -> SampleApp:
        """
        Create a SampleApp object from synthesis result.

        Args:
            architecture: Source architecture
            result: Synthesis result

        Returns:
            SampleApp object
        """
        return SampleApp(
            architecture_id=architecture.id,
            content_hash=architecture.content_hash,
            source_code=result.source_code,
            test_code=result.test_code,
            requirements=result.requirements,
        )
