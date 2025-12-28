"""Abstract base class for template source extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.models import SourceType, TemplateSource
from src.utils.logging import get_logger

logger = get_logger("miner.sources.base")


@dataclass
class ExtractionResult:
    """Result of extracting templates from a source."""

    templates: list[TemplateSource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if extraction was successful (at least one template)."""
        return len(self.templates) > 0

    @property
    def template_count(self) -> int:
        """Number of templates extracted."""
        return len(self.templates)


class SourceExtractor(ABC):
    """
    Abstract base class for template source extractors.

    Each source extractor is responsible for:
    1. Discovering templates from a specific source (GitHub, registry, etc.)
    2. Extracting the template content and metadata
    3. Converting to a common TemplateSource format
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
    ) -> None:
        """
        Initialize the extractor.

        Args:
            cache_dir: Directory for caching extracted templates
            max_templates: Maximum number of templates to extract
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.max_templates = max_templates
        self.logger = get_logger(f"miner.sources.{self.source_name}")

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source."""
        ...

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Type of source (GitHub, Registry, etc.)."""
        ...

    @abstractmethod
    async def extract(self) -> ExtractionResult:
        """
        Extract templates from this source.

        Returns:
            ExtractionResult containing templates and any errors
        """
        ...

    @abstractmethod
    async def check_for_updates(self, last_checked: Optional[str] = None) -> bool:
        """
        Check if source has new templates since last check.

        Args:
            last_checked: ISO timestamp of last check

        Returns:
            True if there are updates
        """
        ...

    def _should_continue(self, current_count: int) -> bool:
        """Check if extraction should continue based on max_templates."""
        if self.max_templates is None:
            return True
        return current_count < self.max_templates

    def _log_extraction_start(self) -> None:
        """Log start of extraction."""
        self.logger.info(
            "extraction_started",
            source=self.source_name,
            max_templates=self.max_templates,
        )

    def _log_extraction_complete(self, result: ExtractionResult) -> None:
        """Log completion of extraction."""
        self.logger.info(
            "extraction_completed",
            source=self.source_name,
            templates=result.template_count,
            errors=len(result.errors),
        )


class GitHubSourceExtractor(SourceExtractor):
    """
    Base class for extractors that work with GitHub repositories.

    Provides common functionality for cloning repos and finding templates.
    """

    def __init__(
        self,
        repo_url: str,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
        branch: str = "main",
    ) -> None:
        """
        Initialize GitHub source extractor.

        Args:
            repo_url: GitHub repository URL
            cache_dir: Directory for caching
            max_templates: Maximum templates to extract
            branch: Git branch to use
        """
        super().__init__(cache_dir, max_templates)
        self.repo_url = repo_url
        self.branch = branch
        self._repo_path: Optional[Path] = None

    @property
    def source_type(self) -> SourceType:
        """GitHub sources are always SourceType.GITHUB."""
        return SourceType.GITHUB

    async def _clone_or_update_repo(self) -> Path:
        """
        Clone repository or update if already cloned.

        Returns:
            Path to local repository
        """
        import asyncio

        if self.cache_dir is None:
            raise ValueError("cache_dir must be set for GitHub sources")

        # Extract repo name from URL
        repo_name = self.repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        repo_path = self.cache_dir / "repos" / repo_name

        if repo_path.exists():
            # Update existing repo
            self.logger.debug("updating_repo", path=str(repo_path))
            process = await asyncio.create_subprocess_exec(
                "git", "pull", "--ff-only",
                cwd=str(repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
        else:
            # Clone new repo
            self.logger.debug("cloning_repo", url=self.repo_url, path=str(repo_path))
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            process = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", "-b", self.branch,
                self.repo_url, str(repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"Failed to clone repo: {stderr.decode()}")

        self._repo_path = repo_path
        return repo_path

    async def _get_latest_commit(self) -> str:
        """Get the latest commit SHA."""
        import asyncio

        if self._repo_path is None:
            raise RuntimeError("Repository not cloned")

        process = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            cwd=str(self._repo_path),
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        return stdout.decode().strip()

    def _find_cloudformation_templates(self, repo_path: Path) -> list[Path]:
        """
        Find CloudFormation templates in repository.

        Args:
            repo_path: Path to repository

        Returns:
            List of template file paths
        """
        templates = []

        # Common patterns for CloudFormation templates
        patterns = [
            "**/*.template",
            "**/*.yaml",
            "**/*.yml",
            "**/*.json",
        ]

        for pattern in patterns:
            for path in repo_path.glob(pattern):
                if self._is_cloudformation_template(path):
                    templates.append(path)

        return templates

    def _find_terraform_templates(self, repo_path: Path) -> list[Path]:
        """
        Find Terraform templates in repository.

        Args:
            repo_path: Path to repository

        Returns:
            List of main.tf file paths
        """
        templates = []

        for main_tf in repo_path.glob("**/main.tf"):
            # Skip nested modules for now
            if "modules/" not in str(main_tf):
                templates.append(main_tf)

        return templates

    @staticmethod
    def _is_cloudformation_template(path: Path) -> bool:
        """Check if file is a CloudFormation template."""
        try:
            content = path.read_text()
            # Look for CloudFormation markers
            markers = [
                "AWSTemplateFormatVersion",
                "Resources:",
                '"Resources"',
                "Transform:",
            ]
            return any(marker in content for marker in markers)
        except Exception:
            return False

    @staticmethod
    def _is_terraform_template(path: Path) -> bool:
        """Check if file is a Terraform template."""
        try:
            content = path.read_text()
            # Look for Terraform markers
            markers = [
                "resource ",
                "provider ",
                "terraform {",
            ]
            return any(marker in content for marker in markers)
        except Exception:
            return False


class RegistrySourceExtractor(SourceExtractor):
    """Base class for extractors that work with registries (Terraform, npm, etc.)."""

    def __init__(
        self,
        api_base_url: str,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
    ) -> None:
        """
        Initialize registry source extractor.

        Args:
            api_base_url: Base URL for registry API
            cache_dir: Directory for caching
            max_templates: Maximum templates to extract
        """
        super().__init__(cache_dir, max_templates)
        self.api_base_url = api_base_url.rstrip("/")

    @property
    def source_type(self) -> SourceType:
        """Registry sources are always SourceType.REGISTRY."""
        return SourceType.REGISTRY

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        """
        Fetch JSON from URL.

        Args:
            url: URL to fetch

        Returns:
            Parsed JSON response
        """
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
