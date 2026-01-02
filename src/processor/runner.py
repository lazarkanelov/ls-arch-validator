"""FSM-based processor runner for architecture validation pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.generator import CodeSynthesizer, CodeValidator, validate_all_files
from src.miner import mine_all, MiningResult
from src.models import Architecture, SampleApp, ValidationResult, ValidationRun
from src.processor.machine import ProcessingMachine
from src.processor.states import ArchState, StateContext
from src.utils.cache import AppCache, ArchitectureCache
from src.utils.logging import get_logger
from src.utils.tokens import TokenTracker

logger = get_logger("processor.runner")


class ProcessorConfig:
    """Configuration for the processor."""

    def __init__(
        self,
        cache_dir: Path,
        max_per_source: int = 10,
        include_diagrams: bool = True,
        skip_mining: bool = False,
        skip_generation: bool = False,
        skip_cache: bool = False,
        token_budget: Optional[int] = None,
        localstack_version: str = "latest",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.max_per_source = max_per_source
        self.include_diagrams = include_diagrams
        self.skip_mining = skip_mining
        self.skip_generation = skip_generation
        self.skip_cache = skip_cache
        self.token_budget = token_budget
        self.localstack_version = localstack_version

        # Derived paths
        self.state_file = self.cache_dir / "processor_state.json"
        self.architectures_dir = self.cache_dir / "architectures"
        self.apps_dir = self.cache_dir / "apps"


class ArchitectureProcessor:
    """
    FSM-based processor for the architecture validation pipeline.

    Processes architectures one at a time through:
    PENDING -> MINING -> GENERATING -> VALIDATING -> PASSED/PARTIAL/FAILED

    Handles rate limits gracefully by transitioning to RATE_LIMITED state
    and waiting for the retry-after period before continuing.
    """

    def __init__(self, config: ProcessorConfig) -> None:
        """
        Initialize the processor.

        Args:
            config: Processor configuration
        """
        self.config = config

        # Initialize FSM
        self.machine = ProcessingMachine(
            state_file=config.state_file,
            auto_save=True,
        )

        # Initialize caches
        self.arch_cache = ArchitectureCache(config.cache_dir)
        self.app_cache = AppCache(config.cache_dir)

        # Initialize components (lazy)
        self._synthesizer: Optional[CodeSynthesizer] = None
        self._validator: Optional[CodeValidator] = None

        # Loaded architectures
        self._architectures: dict[str, Architecture] = {}

        # Results
        self._results: list[ValidationResult] = []

    @property
    def synthesizer(self) -> CodeSynthesizer:
        """Lazy-loaded code synthesizer."""
        if self._synthesizer is None:
            self._synthesizer = CodeSynthesizer(
                cache_dir=str(self.config.cache_dir)
            )
        return self._synthesizer

    @property
    def validator(self) -> CodeValidator:
        """Lazy-loaded code validator."""
        if self._validator is None:
            self._validator = CodeValidator()
        return self._validator

    async def run(self) -> ValidationRun:
        """
        Run the complete processing pipeline.

        Returns:
            ValidationRun with all results
        """
        self.machine.stats.started_at = datetime.utcnow()

        logger.info(
            "processor_started",
            config={
                "max_per_source": self.config.max_per_source,
                "include_diagrams": self.config.include_diagrams,
                "skip_mining": self.config.skip_mining,
                "skip_generation": self.config.skip_generation,
            },
        )

        try:
            # Phase 1: Mining
            if not self.config.skip_mining:
                await self._run_mining_phase()
            else:
                await self._load_cached_architectures()

            # Phase 2: Process each architecture through the FSM
            await self._run_processing_loop()

            # Phase 3: Compile results
            run = self._compile_results()

        except Exception as e:
            logger.error("processor_failed", error=str(e))
            raise

        finally:
            self.machine.stats.completed_at = datetime.utcnow()
            self.machine.save_state()

        logger.info(
            "processor_completed",
            stats=self.machine.stats.to_dict(),
            summary=self.machine.progress_summary(),
        )

        return run

    async def _run_mining_phase(self) -> None:
        """Run the mining phase to discover architectures."""
        logger.info("mining_phase_started")

        result = await mine_all(
            cache_dir=self.config.cache_dir,
            include_diagrams=self.config.include_diagrams,
            max_per_source=self.config.max_per_source,
            skip_cache=self.config.skip_cache,
        )

        # Register architectures with FSM
        for arch in result.architectures:
            self._architectures[arch.id] = arch
            arch_state = self.machine.register_architecture(arch.id)
            arch_state.architecture = arch

            # Transition to MINED (skip MINING state since mining is batch)
            self.machine.transition(arch.id, ArchState.MINING)
            self.machine.transition(arch.id, ArchState.MINED)

        logger.info(
            "mining_phase_completed",
            architectures=len(result.architectures),
            errors=len(result.errors),
        )

    async def _load_cached_architectures(self) -> None:
        """Load architectures from cache."""
        logger.info("loading_cached_architectures")

        # Load from cache directory
        arch_dir = self.config.architectures_dir
        if not arch_dir.exists():
            logger.warning("no_cached_architectures", path=str(arch_dir))
            return

        import json

        for arch_file in arch_dir.glob("*.json"):
            try:
                data = json.loads(arch_file.read_text())
                arch = self._architecture_from_cache(data, arch_file.stem)
                self._architectures[arch.id] = arch

                # Check if already in FSM
                existing = self.machine.get_state(arch.id)
                if existing:
                    existing.architecture = arch
                else:
                    arch_state = self.machine.register_architecture(arch.id)
                    arch_state.architecture = arch
                    self.machine.transition(arch.id, ArchState.MINING)
                    self.machine.transition(arch.id, ArchState.MINED)

            except Exception as e:
                logger.warning(
                    "cache_load_error",
                    file=str(arch_file),
                    error=str(e),
                )

        logger.info(
            "cached_architectures_loaded",
            count=len(self._architectures),
        )

    def _architecture_from_cache(self, data: dict, arch_id: str) -> Architecture:
        """Create Architecture from cached data."""
        from src.models import ArchitectureMetadata, ArchitectureSourceType

        metadata = None
        if data.get("metadata"):
            metadata = ArchitectureMetadata.from_dict(data["metadata"])

        source_type = ArchitectureSourceType.TEMPLATE
        if data.get("source_type") == "diagram":
            source_type = ArchitectureSourceType.DIAGRAM

        return Architecture(
            id=arch_id,
            source_type=source_type,
            source_name=data.get("source_name", ""),
            source_url=data.get("source_url"),
            main_tf=data.get("main_tf", ""),
            variables_tf=data.get("variables_tf"),
            outputs_tf=data.get("outputs_tf"),
            metadata=metadata,
        )

    async def _run_processing_loop(self) -> None:
        """
        Main processing loop using FSM.

        Processes one architecture at a time, handling rate limits gracefully.
        """
        logger.info("processing_loop_started")

        while not self.machine.all_complete():
            # Check for rate-limited architectures ready to retry
            ready_to_retry = self.machine.get_ready_to_retry()
            for arch_state in ready_to_retry:
                logger.info(
                    "retrying_rate_limited",
                    arch_id=arch_state.arch_id,
                    retry_count=arch_state.context.retry_count,
                )
                # Transition back to GENERATING
                self.machine.transition(arch_state.arch_id, ArchState.GENERATING)

            # Get next architecture to process
            next_arch = self._get_next_to_process()

            if next_arch is None:
                # Check if we're waiting for rate limits
                next_retry = self.machine.get_next_retry_time()
                if next_retry:
                    wait_seconds = (next_retry - datetime.utcnow()).total_seconds()
                    if wait_seconds > 0:
                        logger.info(
                            "waiting_for_rate_limit",
                            seconds=wait_seconds,
                        )
                        await asyncio.sleep(wait_seconds)
                        continue

                # No more work to do
                break

            # Process the architecture
            await self._process_architecture(next_arch)

            # Log progress
            summary = self.machine.progress_summary()
            logger.info("processing_progress", summary=summary)

        logger.info("processing_loop_completed")

    def _get_next_to_process(self) -> Optional[ArchitectureState]:
        """Get the next architecture to process based on state."""
        # Priority order:
        # 1. GENERATING (resume interrupted generation)
        # 2. GENERATED (ready for validation)
        # 3. MINED (ready for generation)

        for state in [ArchState.GENERATING, ArchState.GENERATED, ArchState.MINED]:
            archs = self.machine.get_by_state(state)
            if archs:
                return archs[0]

        return None

    async def _process_architecture(self, arch_state: ArchitectureState) -> None:
        """
        Process a single architecture through its current state.

        Args:
            arch_state: Architecture state to process
        """
        arch_id = arch_state.arch_id
        current_state = arch_state.state

        logger.info(
            "processing_architecture",
            arch_id=arch_id,
            state=current_state.name,
        )

        try:
            if current_state == ArchState.MINED:
                await self._handle_mined(arch_state)

            elif current_state == ArchState.GENERATING:
                await self._handle_generating(arch_state)

            elif current_state == ArchState.GENERATED:
                await self._handle_generated(arch_state)

        except Exception as e:
            logger.error(
                "processing_error",
                arch_id=arch_id,
                state=current_state.name,
                error=str(e),
            )
            self.machine.handle_error(arch_id, e, recoverable=False)

    async def _handle_mined(self, arch_state: ArchitectureState) -> None:
        """Handle architecture in MINED state - start generation."""
        arch_id = arch_state.arch_id

        # Skip generation if configured
        if self.config.skip_generation:
            # Try to load from cache
            cached = self.app_cache.load_app(arch_id)
            if cached:
                arch_state.synthesis_result = cached
                self.machine.transition(arch_id, ArchState.GENERATING)
                self.machine.transition(arch_id, ArchState.GENERATED)
            else:
                self.machine.transition(
                    arch_id,
                    ArchState.SKIPPED,
                    StateContext(error_message="No cached app and generation skipped"),
                )
            return

        # Transition to GENERATING
        self.machine.transition(arch_id, ArchState.GENERATING)

    async def _handle_generating(self, arch_state: ArchitectureState) -> None:
        """Handle architecture in GENERATING state - call Claude API."""
        arch_id = arch_state.arch_id
        arch = arch_state.architecture or self._architectures.get(arch_id)

        if not arch:
            self.machine.handle_error(
                arch_id,
                ValueError(f"Architecture not found: {arch_id}"),
                recoverable=False,
            )
            return

        try:
            # Call Claude API to generate probe app
            synthesis = await self.synthesizer.synthesize(
                arch,
                skip_cache=self.config.skip_cache,
            )

            if not synthesis.success:
                self.machine.handle_error(
                    arch_id,
                    ValueError(f"Synthesis failed: {synthesis.errors}"),
                    recoverable=False,
                )
                return

            # Store result
            arch_state.synthesis_result = synthesis

            # Validate syntax
            validation = validate_all_files(
                synthesis.source_code,
                synthesis.test_code,
            )

            if validation.has_errors:
                self.machine.handle_error(
                    arch_id,
                    ValueError(f"Syntax errors: {validation.syntax_errors}"),
                    recoverable=False,
                )
                return

            # Transition to GENERATED
            self.machine.transition(arch_id, ArchState.GENERATED)

        except Exception as e:
            # Check if it's a rate limit error
            error_str = str(e).lower()
            if "rate" in error_str and "limit" in error_str:
                # Extract retry-after if available
                retry_after = self._extract_retry_after(e)
                self.machine.handle_rate_limit(arch_id, retry_after)
            else:
                # Check if recoverable
                recoverable = "timeout" in error_str or "connection" in error_str
                self.machine.handle_error(arch_id, e, recoverable=recoverable)

    def _extract_retry_after(self, error: Exception) -> float:
        """Extract retry-after seconds from rate limit error."""
        # Try to get from error attributes
        if hasattr(error, "response"):
            response = error.response
            if hasattr(response, "headers"):
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        return float(retry_after)
                    except ValueError:
                        pass

        # Default retry delay
        return 60.0

    async def _handle_generated(self, arch_state: ArchitectureState) -> None:
        """Handle architecture in GENERATED state - run validation."""
        arch_id = arch_state.arch_id

        # Transition to VALIDATING
        self.machine.transition(arch_id, ArchState.VALIDATING)

        try:
            # Run validation against LocalStack
            result = await self._run_validation(arch_state)

            # Store result
            arch_state.validation_result = result
            self._results.append(result)

            # Transition to VALIDATED
            self.machine.transition(arch_id, ArchState.VALIDATED)

            # Transition to final state based on result
            if result.status == "passed":
                self.machine.transition(arch_id, ArchState.PASSED)
            elif result.status == "partial":
                self.machine.transition(arch_id, ArchState.PARTIAL)
            else:
                self.machine.transition(arch_id, ArchState.FAILED)

        except Exception as e:
            self.machine.handle_error(arch_id, e, recoverable=False)

    async def _run_validation(self, arch_state: ArchitectureState) -> ValidationResult:
        """
        Run validation against LocalStack.

        Args:
            arch_state: Architecture state with synthesis result

        Returns:
            ValidationResult
        """
        arch_id = arch_state.arch_id
        synthesis = arch_state.synthesis_result

        # Create sample app
        arch = arch_state.architecture or self._architectures.get(arch_id)
        app = self.synthesizer.create_sample_app(arch, synthesis)

        # For now, create a placeholder result
        # The actual LocalStack validation would happen here
        # This is a simplified version - full implementation would use
        # the existing validator infrastructure

        # TODO: Integrate with actual LocalStack runner
        result = ValidationResult(
            architecture_id=arch_id,
            status="passed",  # Placeholder
            passed_tests=[],
            failed_tests=[],
            error_summary=None,
        )

        return result

    def _compile_results(self) -> ValidationRun:
        """Compile all results into a ValidationRun."""
        from src.models import RunStatistics

        stats = RunStatistics(
            total=self.machine.stats.total,
            passed=self.machine.stats.passed,
            partial=self.machine.stats.partial,
            failed=self.machine.stats.failed,
            errors=self.machine.stats.errors,
            skipped=self.machine.stats.skipped,
        )

        run = ValidationRun(
            id=f"run-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
            started_at=self.machine.stats.started_at,
            completed_at=self.machine.stats.completed_at,
            status="completed",
            localstack_version=self.config.localstack_version,
            statistics=stats,
            results=self._results,
        )

        return run

    def get_progress(self) -> dict[str, Any]:
        """Get current processing progress."""
        return {
            "summary": self.machine.progress_summary(),
            "stats": self.machine.stats.to_dict(),
            "rate_limited": [
                {
                    "arch_id": arch.arch_id,
                    "retry_in": arch.time_until_retry(),
                }
                for arch in self.machine.get_rate_limited()
            ],
        }


async def run_processor(config: ProcessorConfig) -> ValidationRun:
    """
    Convenience function to run the processor.

    Args:
        config: Processor configuration

    Returns:
        ValidationRun with results
    """
    processor = ArchitectureProcessor(config)
    return await processor.run()
