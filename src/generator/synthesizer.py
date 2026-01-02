"""Code synthesizer using Claude API.

Implements best practices from Anthropic documentation:
- Prompt caching for system prompts (90% cost reduction)
- Proper rate limit handling with retry-after header
- Temperature control for deterministic code output
- Structured error handling with specific exception types
- Token budget management

References:
- https://platform.claude.com/docs/en/api/rate-limits
- https://www.anthropic.com/news/prompt-caching
- https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic
from anthropic import APIError, APIConnectionError, RateLimitError, APIStatusError

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

# Best practice: Use lower temperature for code generation (deterministic output)
CODE_GENERATION_TEMPERATURE = 0.3

# Best practice: Minimum tokens for prompt caching (1024 required)
MIN_CACHE_TOKENS = 1024

# Rate limit aware settings
# Tier 1 limits: 8,000 OTPM (output tokens per minute) for Sonnet 4.x
# Set max_tokens below the rate limit to avoid immediate 429s
# Most code responses are 1000-3000 tokens, 4096 is a safe upper bound
MAX_OUTPUT_TOKENS = 4096

# Minimum delay between API calls to stay under rate limits
# At 4096 max tokens, we can do ~2 requests per minute under 8,000 OTPM
MIN_REQUEST_DELAY_SECONDS = 5.0


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

                # Rate limit protection: delay between API calls
                # Tier 1 has 8,000 OTPM, so we need ~30s between 4K token requests
                await asyncio.sleep(MIN_REQUEST_DELAY_SECONDS)

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
        Generate probe code using Claude with best practices.

        Implements:
        - Prompt caching for system prompt (90% cost reduction)
        - Temperature control (0.3 for deterministic code)
        - Proper rate limit handling using retry-after header
        - Specific exception handling for different error types
        - Token usage tracking with cache metrics

        Args:
            prompt: The probe-specific prompt
            probe_type: Type of probe

        Returns:
            Dict with files, requirements, probed_features
        """
        import asyncio

        max_retries = 5  # Best practice: more retries for production
        default_retry_delay = 10  # Default if no retry-after header

        for attempt in range(max_retries):
            try:
                client = await self._get_client()

                # Best practice: Use prompt caching for system prompt
                # This reduces cost by up to 90% and latency by 85%
                # The system prompt is cached and reused across requests
                response = await client.messages.create(
                    model=self.model,
                    max_tokens=MAX_OUTPUT_TOKENS,  # Stay under OTPM rate limit
                    temperature=CODE_GENERATION_TEMPERATURE,  # Lower for deterministic code
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"}  # 5-minute cache
                        }
                    ],
                    messages=[{"role": "user", "content": prompt}],
                )

                # Track token usage including cache metrics
                tracker = TokenTracker.get_instance()
                tracker.record_from_response(response.usage)

                # Log cache performance for optimization
                cache_read = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
                cache_create = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
                input_tokens = response.usage.input_tokens

                logger.info(
                    "api_call_completed",
                    probe_type=probe_type.value,
                    input_tokens=input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_read_tokens=cache_read,
                    cache_create_tokens=cache_create,
                    cache_hit_rate=f"{(cache_read / (cache_read + input_tokens + cache_create) * 100):.1f}%" if (cache_read + input_tokens + cache_create) > 0 else "0%",
                )

                # Parse response
                content = response.content[0].text

                # Debug: Log response format
                logger.info(
                    "claude_response_received",
                    content_length=len(content),
                    content_preview=content[:300].replace('\n', '\\n'),
                    has_file_headers="### FILE:" in content or "## FILE:" in content,
                    has_metadata="METADATA" in content,
                    has_json_block="```json" in content,
                )

                result = self._parse_json_response(content)
                result["tokens"] = input_tokens + response.usage.output_tokens
                result["cache_read_tokens"] = cache_read
                result["cache_create_tokens"] = cache_create

                # Log parsing result
                logger.info(
                    "parsing_result",
                    files_count=len(result.get("files", {})),
                    file_names=list(result.get("files", {}).keys())[:5],
                    requirements_count=len(result.get("requirements", [])),
                )

                # Set probe name from config if not in response
                if not result.get("probe_name") and probe_type in PROBE_CONFIGS:
                    result["probe_name"] = PROBE_CONFIGS[probe_type]["name"]

                return result

            except RateLimitError as e:
                # Best practice: Use retry-after header from response
                retry_after = self._get_retry_after(e)
                delay = retry_after if retry_after else default_retry_delay * (2 ** attempt)

                if attempt < max_retries - 1:
                    logger.warning(
                        "rate_limit_hit",
                        probe_type=probe_type.value,
                        attempt=attempt + 1,
                        retry_after=retry_after,
                        delay=delay,
                        message=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "rate_limit_exhausted",
                        probe_type=probe_type.value,
                        attempts=max_retries,
                        error=str(e),
                    )
                    return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

            except APIConnectionError as e:
                # Network/connection errors - retry with backoff
                delay = default_retry_delay * (2 ** attempt)
                if attempt < max_retries - 1:
                    logger.warning(
                        "connection_error_retry",
                        probe_type=probe_type.value,
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("connection_error_exhausted", probe_type=probe_type.value, error=str(e))
                    return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

            except APIStatusError as e:
                # API errors (4xx, 5xx) - check if retryable
                if e.status_code >= 500 and attempt < max_retries - 1:
                    # Server errors are retryable
                    delay = default_retry_delay * (2 ** attempt)
                    logger.warning(
                        "server_error_retry",
                        probe_type=probe_type.value,
                        status_code=e.status_code,
                        attempt=attempt + 1,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    # Client errors (4xx) or exhausted retries
                    logger.error(
                        "api_error",
                        probe_type=probe_type.value,
                        status_code=e.status_code,
                        error=str(e),
                    )
                    return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

            except Exception as e:
                # Unexpected errors - log and fail
                logger.error(
                    "unexpected_error",
                    probe_type=probe_type.value,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

        return {"files": {}, "requirements": [], "probed_features": [], "tokens": 0}

    def _get_retry_after(self, error: RateLimitError) -> Optional[float]:
        """
        Extract retry-after value from rate limit error response.

        Best practice: Use the retry-after header provided by Anthropic
        instead of arbitrary delays.

        Args:
            error: The rate limit error

        Returns:
            Seconds to wait, or None if not available
        """
        try:
            # Try to get from response headers
            if hasattr(error, 'response') and error.response:
                headers = getattr(error.response, 'headers', {})
                retry_after = headers.get('retry-after')
                if retry_after:
                    return float(retry_after)

            # Try to parse from error message
            error_str = str(error)
            import re
            match = re.search(r'retry.after[:\s]+(\d+(?:\.\d+)?)', error_str, re.IGNORECASE)
            if match:
                return float(match.group(1))
        except Exception:
            pass

        return None

    async def _generate_source_code(
        self,
        analysis: InfrastructureAnalysis,
        terraform_content: str,
    ) -> dict[str, Any]:
        """
        Generate source code using Claude with best practices.

        Args:
            analysis: Infrastructure analysis
            terraform_content: Terraform HCL content

        Returns:
            Dict with files and requirements
        """
        prompt = format_generation_prompt(analysis, terraform_content)

        try:
            client = await self._get_client()

            # Best practice: prompt caching + temperature control
            response = await client.messages.create(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,  # Stay under OTPM rate limit
                temperature=CODE_GENERATION_TEMPERATURE,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
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

        except RateLimitError as e:
            logger.error("source_generation_rate_limited", error=str(e))
            return {"files": {}, "requirements": [], "tokens": 0}
        except APIError as e:
            logger.error("source_generation_api_error", error=str(e))
            return {"files": {}, "requirements": [], "tokens": 0}
        except Exception as e:
            logger.error("source_generation_failed", error=str(e))
            return {"files": {}, "requirements": [], "tokens": 0}

    async def _generate_tests(
        self,
        analysis: InfrastructureAnalysis,
        app_code: str,
    ) -> dict[str, Any]:
        """
        Generate test code using Claude with best practices.

        Args:
            analysis: Infrastructure analysis
            app_code: Generated application code

        Returns:
            Dict with test files and requirements
        """
        import asyncio

        prompt = format_test_prompt(analysis, app_code)
        max_retries = 5
        default_retry_delay = 10

        for attempt in range(max_retries):
            try:
                client = await self._get_client()

                # Best practice: prompt caching + temperature control
                response = await client.messages.create(
                    model=self.model,
                    max_tokens=MAX_OUTPUT_TOKENS,  # Stay under OTPM rate limit
                    temperature=CODE_GENERATION_TEMPERATURE,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ],
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

            except RateLimitError as e:
                # Best practice: Use retry-after header
                retry_after = self._get_retry_after(e)
                delay = retry_after if retry_after else default_retry_delay * (2 ** attempt)

                if attempt < max_retries - 1:
                    logger.warning(
                        "test_generation_rate_limited",
                        attempt=attempt + 1,
                        retry_after=retry_after,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("test_generation_rate_limit_exhausted", error=str(e))
                    return {"files": {}, "requirements": [], "tokens": 0}

            except APIConnectionError as e:
                delay = default_retry_delay * (2 ** attempt)
                if attempt < max_retries - 1:
                    logger.warning("test_generation_connection_error", attempt=attempt + 1, delay=delay)
                    await asyncio.sleep(delay)
                else:
                    logger.error("test_generation_connection_exhausted", error=str(e))
                    return {"files": {}, "requirements": [], "tokens": 0}

            except APIStatusError as e:
                if e.status_code >= 500 and attempt < max_retries - 1:
                    delay = default_retry_delay * (2 ** attempt)
                    logger.warning("test_generation_server_error", status_code=e.status_code, attempt=attempt + 1)
                    await asyncio.sleep(delay)
                else:
                    logger.error("test_generation_api_error", status_code=e.status_code, error=str(e))
                    return {"files": {}, "requirements": [], "tokens": 0}

            except Exception as e:
                logger.error("test_generation_unexpected_error", error_type=type(e).__name__, error=str(e))
                return {"files": {}, "requirements": [], "tokens": 0}

        return {"files": {}, "requirements": [], "tokens": 0}

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """
        Parse response from Claude with robust multi-strategy extraction.

        Tries multiple parsing strategies in order:
        1. New markdown format with ### FILE: headers
        2. JSON with "files" dict (direct or in code block)
        3. Embedded code extraction from JSON strings
        4. Plain Python code blocks with filename comments
        5. Any Python code blocks (auto-generate names)

        Args:
            content: Response text from Claude

        Returns:
            Parsed response with files, requirements, probed_features
        """
        files: dict[str, str] = {}
        metadata: dict[str, Any] = {}

        # Strategy 1: New markdown format with ### FILE: headers
        files = self._extract_markdown_files(content)
        if files:
            metadata = self._extract_metadata(content)
            logger.info("parse_strategy_1_markdown", file_count=len(files))
            return self._build_result(files, metadata)

        # Strategy 2: JSON with "files" dict
        files, metadata = self._extract_json_files(content)
        if files:
            logger.info("parse_strategy_2_json", file_count=len(files))
            return self._build_result(files, metadata)

        # Strategy 3: Extract code from embedded JSON strings
        files = self._extract_embedded_code_from_json(content)
        if files:
            metadata = self._extract_metadata(content)
            logger.info("parse_strategy_3_embedded", file_count=len(files))
            return self._build_result(files, metadata)

        # Strategy 4: Code blocks with filename comments
        files = self._extract_code_blocks_with_filenames(content)
        if files:
            logger.info("parse_strategy_4_comments", file_count=len(files))
            return self._build_result(files, {})

        # Strategy 5: Any Python code blocks (last resort)
        files = self._extract_any_code_blocks(content)
        if files:
            logger.info("parse_strategy_5_any_blocks", file_count=len(files))
            return self._build_result(files, {})

        logger.warning(
            "all_parse_strategies_failed",
            content_length=len(content),
            content_sample=content[:200].replace('\n', '\\n'),
        )
        return {"files": {}, "requirements": [], "probed_features": []}

    def _build_result(
        self,
        files: dict[str, str],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Build standardized result dict."""
        return {
            "files": files,
            "requirements": metadata.get("requirements", ["boto3", "pytest"]),
            "probed_features": metadata.get("probed_features", []),
            "probe_name": metadata.get("probe_name", ""),
            "tested_features": metadata.get("tested_features", []),
        }

    def _extract_markdown_files(self, content: str) -> dict[str, str]:
        """
        Extract files from markdown format with FILE: headers.

        Supports multiple header formats:
        - ### FILE: path/to/file.py
        - ## FILE: path/to/file.py
        - **FILE:** path/to/file.py
        - `path/to/file.py`:

        Args:
            content: Response text with markdown file blocks

        Returns:
            Dict of filename to code content
        """
        files = {}

        # Pattern 1: ### FILE: or ## FILE: format
        pattern1 = r"#{1,4}\s*FILE:\s*[`'\"]?([^\s`'\"]+)[`'\"]?\s*\n```(?:python|py)?\s*\n(.*?)```"
        for match in re.finditer(pattern1, content, re.DOTALL | re.IGNORECASE):
            filename = match.group(1).strip()
            code = match.group(2).strip()
            if filename and code:
                files[filename] = code

        if files:
            return files

        # Pattern 2: **filename** or `filename` followed by code block
        pattern2 = r"(?:\*\*|`)([^\s*`]+\.py)(?:\*\*|`)[:\s]*\n```(?:python|py)?\s*\n(.*?)```"
        for match in re.finditer(pattern2, content, re.DOTALL):
            filename = match.group(1).strip()
            code = match.group(2).strip()
            if filename and code:
                files[filename] = code

        if files:
            return files

        # Pattern 3: Filename on its own line before code block
        pattern3 = r"^([a-zA-Z_][a-zA-Z0-9_/]*\.py)\s*$\n```(?:python|py)?\s*\n(.*?)```"
        for match in re.finditer(pattern3, content, re.DOTALL | re.MULTILINE):
            filename = match.group(1).strip()
            code = match.group(2).strip()
            if filename and code:
                files[filename] = code

        return files

    def _extract_metadata(self, content: str) -> dict[str, Any]:
        """
        Extract metadata from response (requirements, probed_features, etc.).

        Looks for:
        - ### METADATA section with JSON
        - "requirements" array anywhere in JSON
        - pip install comments in code

        Args:
            content: Response text

        Returns:
            Metadata dict with requirements and probed_features
        """
        metadata: dict[str, Any] = {}

        # Try METADATA section first
        pattern = r"#{1,4}\s*METADATA\s*\n```json\s*\n(.*?)```"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                metadata = json.loads(match.group(1))
                return metadata
            except json.JSONDecodeError:
                pass

        # Try to find requirements array in any JSON block
        json_pattern = r"```json\s*\n(.*?)```"
        for match in re.finditer(json_pattern, content, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict):
                    if "requirements" in data:
                        metadata["requirements"] = data["requirements"]
                    if "probed_features" in data:
                        metadata["probed_features"] = data["probed_features"]
                    if "probe_name" in data:
                        metadata["probe_name"] = data["probe_name"]
            except json.JSONDecodeError:
                continue

        # Extract requirements from pip install comments
        if "requirements" not in metadata:
            pip_pattern = r"#\s*pip install\s+(.+)"
            pip_matches = re.findall(pip_pattern, content)
            if pip_matches:
                requirements = []
                for match in pip_matches:
                    requirements.extend(match.split())
                metadata["requirements"] = requirements

        return metadata

    def _extract_json_files(self, content: str) -> tuple[dict[str, str], dict[str, Any]]:
        """
        Extract files from JSON format with "files" dict.

        Args:
            content: Response text

        Returns:
            Tuple of (files dict, metadata dict)
        """
        # Try JSON in code block first
        json_pattern = r"```json\s*\n(.*?)```"
        for match in re.finditer(json_pattern, content, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "files" in data:
                    files = data["files"]
                    if isinstance(files, dict) and files:
                        metadata = {
                            k: v for k, v in data.items()
                            if k in ("requirements", "probed_features", "probe_name")
                        }
                        return files, metadata
            except json.JSONDecodeError:
                continue

        # Try raw JSON (without code block)
        try:
            # Find JSON object in content
            json_match = re.search(r'\{[^{}]*"files"\s*:\s*\{.*?\}\s*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                if "files" in data:
                    files = data["files"]
                    metadata = {
                        k: v for k, v in data.items()
                        if k in ("requirements", "probed_features", "probe_name")
                    }
                    return files, metadata
        except json.JSONDecodeError:
            pass

        return {}, {}

    def _extract_embedded_code_from_json(self, content: str) -> dict[str, str]:
        """
        Extract code embedded as strings within JSON.

        Handles cases where Claude outputs JSON like:
        {"files": {"src/main.py": "def foo():\\n    pass"}}

        The code is escaped as JSON string and needs to be unescaped.

        Args:
            content: Response text

        Returns:
            Dict of filename to code content
        """
        files = {}

        # Find all JSON blocks
        json_pattern = r"```json\s*\n(.*?)```"
        for match in re.finditer(json_pattern, content, re.DOTALL):
            json_str = match.group(1)

            # Try to parse as JSON first
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and "files" in data:
                    for filename, code in data["files"].items():
                        if isinstance(code, str) and code.strip():
                            # Code is already unescaped by json.loads
                            files[filename] = code
                    if files:
                        return files
            except json.JSONDecodeError:
                pass

            # If JSON parsing failed, try regex extraction from the raw string
            # Pattern to find "filename.py": "code..."
            file_pattern = r'"([^"]+\.py)"\s*:\s*"((?:[^"\\]|\\.)*)\"'
            for file_match in re.finditer(file_pattern, json_str):
                filename = file_match.group(1)
                code = file_match.group(2)
                # Unescape the code
                try:
                    code = code.encode().decode('unicode_escape')
                except Exception:
                    code = code.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                if code.strip():
                    files[filename] = code.strip()

        return files

    def _extract_code_blocks_with_filenames(self, content: str) -> dict[str, str]:
        """
        Extract Python code blocks that have filename indicators.

        Looks for:
        - # filename.py at the start of the code
        - # File: filename.py comment
        - '''filename.py''' docstring

        Args:
            content: Response text with code blocks

        Returns:
            Dict of filename to code content
        """
        files = {}

        # Find all Python code blocks
        pattern = r"```(?:python|py)\s*\n(.*?)```"
        for i, match in enumerate(re.finditer(pattern, content, re.DOTALL)):
            code = match.group(1).strip()
            if not code:
                continue

            filename = None

            # Try to extract filename from first line comment
            first_line = code.split('\n')[0].strip()

            # Pattern: # filename.py or # src/filename.py
            if first_line.startswith('#'):
                name_match = re.match(r'#\s*(?:File:\s*)?([a-zA-Z_][a-zA-Z0-9_/]*\.py)', first_line, re.IGNORECASE)
                if name_match:
                    filename = name_match.group(1)
                    # Remove the filename comment from code
                    code = '\n'.join(code.split('\n')[1:]).strip()

            # Pattern: """filename.py""" or '''filename.py'''
            if not filename:
                doc_match = re.match(r'["\']{{3}}([a-zA-Z_][a-zA-Z0-9_/]*\.py)["\']{{3}}', first_line)
                if doc_match:
                    filename = doc_match.group(1)

            # If we found a filename, add it
            if filename and code:
                files[filename] = code
            elif code and len(code) > 50:  # Only add substantial code blocks
                # Generate filename based on content
                if "test_" in code or "def test" in code or "@pytest" in code:
                    filename = f"tests/test_generated_{i}.py"
                elif "class " in code and "Probe" in code:
                    filename = f"src/probes/probe_{i}.py"
                elif "def " in code:
                    filename = f"src/generated_{i}.py"
                else:
                    filename = f"src/code_{i}.py"
                files[filename] = code

        return files

    def _extract_any_code_blocks(self, content: str) -> dict[str, str]:
        """
        Extract any Python code blocks as last resort.

        Args:
            content: Response text with code blocks

        Returns:
            Dict of filename to code content
        """
        files = {}

        # Find ALL code blocks (python, py, or unspecified)
        pattern = r"```(?:python|py)?\s*\n(.*?)```"
        blocks = re.findall(pattern, content, re.DOTALL)

        src_count = 0
        test_count = 0

        for code in blocks:
            code = code.strip()
            if not code or len(code) < 30:
                continue

            # Skip JSON blocks
            if code.startswith('{') or code.startswith('['):
                continue

            # Determine if it's a test or source file
            is_test = any(x in code for x in ["test_", "def test", "@pytest", "import pytest", "TestCase"])

            if is_test:
                filename = f"tests/test_probe_{test_count}.py"
                test_count += 1
            else:
                filename = f"src/probes/probe_{src_count}.py"
                src_count += 1

            files[filename] = code

        return files

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
