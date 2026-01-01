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
    get_probe_prompt,
    PROBE_CONFIGS,
)
from src.models import Architecture, SampleApp, ProbeType
from src.utils.cache import AppCache
from src.utils.logging import get_logger
from src.utils.tokens import TokenTracker

logger = get_logger("generator.synthesizer")


@dataclass
class SynthesisResult:
    """Result of synthesizing a single probe application."""

    probe_type: ProbeType = ProbeType.API_PARITY
    probe_name: str = ""
    probed_features: list[str] = field(default_factory=list)
    source_code: dict[str, str] = field(default_factory=dict)
    test_code: dict[str, str] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tokens_used: int = 0

    @property
    def success(self) -> bool:
        """Check if synthesis was successful."""
        return len(self.source_code) > 0 and len(self.errors) == 0


@dataclass
class MultiSynthesisResult:
    """Result of synthesizing multiple probe applications for one architecture."""

    results: list[SynthesisResult] = field(default_factory=list)
    total_tokens: int = 0

    @property
    def success(self) -> bool:
        """Check if at least one probe was synthesized successfully."""
        return any(r.success for r in self.results)

    @property
    def successful_results(self) -> list[SynthesisResult]:
        """Get only successful synthesis results."""
        return [r for r in self.results if r.success]


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
        """Get or create Anthropic client with conservative rate limit settings."""
        if self._client is None:
            import anthropic

            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")

            # Configure client with conservative retry settings
            self._client = anthropic.AsyncAnthropic(
                api_key=self.api_key,
                max_retries=5,  # More retries for rate limits
                timeout=120.0,  # 2 minute timeout per request
            )

        return self._client

    async def synthesize(
        self,
        architecture: Architecture,
        skip_cache: bool = False,
    ) -> SynthesisResult:
        """
        Synthesize a single sample application for an architecture (legacy method).

        Args:
            architecture: Architecture to generate app for
            skip_cache: Skip cache check

        Returns:
            SynthesisResult with generated code
        """
        # Use the multi-app method but return just the first result
        multi_result = await self.synthesize_multiple(
            architecture,
            probe_types=[ProbeType.API_PARITY],
            skip_cache=skip_cache,
        )
        if multi_result.results:
            return multi_result.results[0]
        return SynthesisResult(errors=["No apps generated"])

    async def synthesize_multiple(
        self,
        architecture: Architecture,
        probe_types: Optional[list[ProbeType]] = None,
        skip_cache: bool = False,
    ) -> MultiSynthesisResult:
        """
        Synthesize multiple probe applications for an architecture.

        Args:
            architecture: Architecture to generate apps for
            probe_types: Types of probes to generate (default: API_PARITY and EDGE_CASES)
            skip_cache: Skip cache check

        Returns:
            MultiSynthesisResult with all generated probe apps
        """
        if probe_types is None:
            # Default: generate 2 different probe types
            probe_types = [ProbeType.API_PARITY, ProbeType.EDGE_CASES]

        multi_result = MultiSynthesisResult()

        # Analyze infrastructure once for all probes
        analysis = self.analyzer.analyze(architecture.main_tf)

        for i, probe_type in enumerate(probe_types):
            # Add delay between probe types to avoid rate limiting
            if i > 0:
                import asyncio
                await asyncio.sleep(3.0)  # 3 second delay between probes

            cache_key = f"{architecture.content_hash}_{probe_type.value}"

            # Check cache
            if self.cache and not skip_cache:
                cached = self.cache.load_app(cache_key)
                if cached:
                    logger.debug("using_cached_app", arch_id=architecture.id, probe=probe_type.value)
                    result = SynthesisResult(
                        probe_type=probe_type,
                        probe_name=cached.get("probe_name", ""),
                        probed_features=cached.get("probed_features", []),
                        source_code=cached.get("source_code", {}),
                        test_code=cached.get("test_code", {}),
                        requirements=cached.get("requirements", []),
                    )
                    multi_result.results.append(result)
                    continue

            # Check token budget
            tracker = TokenTracker.get_instance()
            estimated_tokens = 10000  # Approximate tokens per probe

            if not tracker.can_afford(estimated_tokens):
                logger.warning(
                    "token_budget_exhausted",
                    arch_id=architecture.id,
                    probe=probe_type.value,
                    remaining=tracker.remaining,
                )
                result = SynthesisResult(
                    probe_type=probe_type,
                    errors=["Token budget exhausted"],
                )
                multi_result.results.append(result)
                continue

            try:
                result = await self._synthesize_probe(
                    architecture=architecture,
                    analysis=analysis,
                    probe_type=probe_type,
                )

                # Cache result
                if self.cache and result.success:
                    self.cache.save_app(
                        content_hash=cache_key,
                        source_code=result.source_code,
                        test_code=result.test_code,
                        requirements=result.requirements,
                        metadata={
                            "architecture_id": architecture.id,
                            "probe_type": probe_type.value,
                            "probe_name": result.probe_name,
                            "probed_features": result.probed_features,
                            "services": list(analysis.services),
                        },
                    )

                multi_result.results.append(result)
                multi_result.total_tokens += result.tokens_used

                logger.info(
                    "probe_synthesis_completed",
                    arch_id=architecture.id,
                    probe_type=probe_type.value,
                    probe_name=result.probe_name,
                    features=len(result.probed_features),
                    source_files=len(result.source_code),
                    test_files=len(result.test_code),
                    tokens=result.tokens_used,
                )

            except Exception as e:
                error_msg = f"Synthesis failed for {probe_type.value}: {e}"
                result = SynthesisResult(
                    probe_type=probe_type,
                    errors=[error_msg],
                )
                multi_result.results.append(result)
                logger.error(
                    "probe_synthesis_failed",
                    arch_id=architecture.id,
                    probe=probe_type.value,
                    error=str(e),
                )

        logger.info(
            "multi_synthesis_completed",
            arch_id=architecture.id,
            total_probes=len(multi_result.results),
            successful=len(multi_result.successful_results),
            total_tokens=multi_result.total_tokens,
        )

        return multi_result

    async def _synthesize_probe(
        self,
        architecture: Architecture,
        analysis: InfrastructureAnalysis,
        probe_type: ProbeType,
    ) -> SynthesisResult:
        """
        Synthesize a single probe application.

        Args:
            architecture: Source architecture
            analysis: Infrastructure analysis
            probe_type: Type of probe to generate

        Returns:
            SynthesisResult for this probe
        """
        result = SynthesisResult(probe_type=probe_type)

        # Get probe-specific prompt
        probe_prompt = get_probe_prompt(probe_type, analysis, architecture.main_tf)

        # Generate probe source code
        source_result = await self._generate_probe_code(probe_prompt, probe_type)
        result.source_code = source_result.get("files", {})
        result.requirements = source_result.get("requirements", [])
        result.probed_features = source_result.get("probed_features", [])
        result.probe_name = source_result.get("probe_name", f"{probe_type.value.replace('_', ' ').title()} Probe")
        result.tokens_used += source_result.get("tokens", 0)

        if not result.source_code:
            result.errors.append(f"Failed to generate {probe_type.value} probe code")
            return result

        # Generate tests for this probe
        app_code = "\n\n".join(result.source_code.values())
        test_result = await self._generate_tests(analysis, app_code)
        result.test_code = test_result.get("files", {})
        result.requirements.extend(test_result.get("requirements", []))
        result.tokens_used += test_result.get("tokens", 0)

        # Deduplicate requirements
        result.requirements = list(set(result.requirements))

        return result

    async def _generate_probe_code(
        self,
        prompt: str,
        probe_type: ProbeType,
    ) -> dict[str, Any]:
        """
        Generate probe code using Claude with robust retry logic.

        Args:
            prompt: The probe-specific prompt
            probe_type: Type of probe

        Returns:
            Dict with files, requirements, probed_features
        """
        import asyncio

        max_retries = 3
        base_delay = 10  # Start with 10 second delay

        for attempt in range(max_retries):
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

                # Set probe name from config if not in response
                if not result.get("probe_name") and probe_type in PROBE_CONFIGS:
                    result["probe_name"] = PROBE_CONFIGS[probe_type]["name"]

                return result

            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "rate" in error_str.lower()

                if attempt < max_retries - 1 and is_rate_limit:
                    # Exponential backoff for rate limits
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "rate_limit_retry",
                        probe_type=probe_type.value,
                        attempt=attempt + 1,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("probe_generation_failed", probe_type=probe_type.value, error=error_str)
                    return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

        return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

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
        Generate test code using Claude with robust retry logic.

        Args:
            analysis: Infrastructure analysis
            app_code: Generated application code

        Returns:
            Dict with test files and requirements
        """
        import asyncio

        prompt = format_test_prompt(analysis, app_code)
        max_retries = 3
        base_delay = 10

        for attempt in range(max_retries):
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
                error_str = str(e)
                is_rate_limit = "429" in error_str or "rate" in error_str.lower()

                if attempt < max_retries - 1 and is_rate_limit:
                    delay = base_delay * (2 ** attempt)
                    logger.warning("rate_limit_retry_tests", attempt=attempt + 1, delay=delay)
                    await asyncio.sleep(delay)
                else:
                    logger.error("test_generation_failed", error=error_str)
                    return {"files": {}, "requirements": [], "tokens": 0}

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
            app_id=f"{architecture.id}_{result.probe_type.value}",
            probe_type=result.probe_type,
            probe_name=result.probe_name,
            probed_features=result.probed_features,
            source_code=result.source_code,
            test_code=result.test_code,
            requirements=result.requirements,
            compile_status="success" if result.success else "failed",
            compile_errors="; ".join(result.errors) if result.errors else None,
            token_usage=result.tokens_used,
        )

    def create_sample_apps(
        self,
        architecture: Architecture,
        multi_result: MultiSynthesisResult,
    ) -> list[SampleApp]:
        """
        Create multiple SampleApp objects from multi-synthesis result.

        Args:
            architecture: Source architecture
            multi_result: MultiSynthesisResult with all probe results

        Returns:
            List of SampleApp objects
        """
        apps = []
        for result in multi_result.results:
            app = self.create_sample_app(architecture, result)
            apps.append(app)
        return apps
