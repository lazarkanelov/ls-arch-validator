"""AWS Solutions Library template extractor."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.models import SourceType, TemplateSource
from src.miner.sources.base import ExtractionResult, GitHubSourceExtractor
from src.utils.logging import get_logger

logger = get_logger("miner.sources.solutions")

# AWS Solutions Library repositories
SOLUTIONS_REPOS = [
    "https://github.com/aws-solutions/serverless-image-handler",
    "https://github.com/aws-solutions/aws-waf-security-automations",
    "https://github.com/aws-solutions/document-understanding-solution",
    "https://github.com/aws-solutions/real-time-analytics-spark-streaming",
    "https://github.com/aws-solutions/centralized-logging-with-opensearch",
    "https://github.com/aws-solutions/aws-instance-scheduler",
    "https://github.com/aws-solutions/aws-limit-monitor",
]


class AWSSolutionsExtractor(GitHubSourceExtractor):
    """
    Extractor for AWS Solutions Library templates.

    AWS Solutions are reference implementations for common use cases.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
        repos: Optional[list[str]] = None,
    ) -> None:
        """
        Initialize AWS Solutions extractor.

        Args:
            cache_dir: Directory for caching repositories
            max_templates: Maximum templates to extract
            repos: List of repo URLs (defaults to SOLUTIONS_REPOS)
        """
        repos = repos or SOLUTIONS_REPOS
        super().__init__(
            repo_url=repos[0],
            cache_dir=cache_dir,
            max_templates=max_templates,
        )
        self.repos = repos

    @property
    def source_name(self) -> str:
        """Source identifier."""
        return "aws-solutions"

    async def extract(self) -> ExtractionResult:
        """
        Extract templates from AWS Solutions repositories.

        Returns:
            ExtractionResult with templates
        """
        self._log_extraction_start()

        result = ExtractionResult()
        template_count = 0

        for repo_url in self.repos:
            if not self._should_continue(template_count):
                break

            try:
                # Update repo URL for this iteration
                self.repo_url = repo_url

                # Clone or update repository
                repo_path = await self._clone_or_update_repo()

                # Find CloudFormation templates
                template_paths = self._find_solution_templates(repo_path)

                for template_path in template_paths:
                    if not self._should_continue(template_count):
                        break

                    try:
                        template = await self._process_template(
                            template_path,
                            repo_path,
                            repo_url,
                        )
                        if template:
                            result.templates.append(template)
                            template_count += 1

                    except Exception as e:
                        error_msg = f"Error processing {template_path}: {e}"
                        result.errors.append(error_msg)
                        self.logger.warning("template_error", error=error_msg)

            except Exception as e:
                error_msg = f"Error processing repo {repo_url}: {e}"
                result.errors.append(error_msg)
                self.logger.warning("repo_error", error=error_msg)

        self._log_extraction_complete(result)
        return result

    async def check_for_updates(self, last_checked: Optional[str] = None) -> bool:
        """Check for updates."""
        return True

    def _find_solution_templates(self, repo_path: Path) -> list[Path]:
        """
        Find CloudFormation templates in AWS Solutions repo.

        Args:
            repo_path: Path to repository

        Returns:
            List of template paths
        """
        templates = []

        # AWS Solutions typically have templates in source/infrastructure or deployment
        search_dirs = [
            repo_path / "source" / "infrastructure",
            repo_path / "deployment",
            repo_path / "template",
            repo_path / "templates",
        ]

        for search_dir in search_dirs:
            if search_dir.exists():
                for template_path in search_dir.glob("**/*.template"):
                    templates.append(template_path)
                for template_path in search_dir.glob("**/*.yaml"):
                    if self._is_cloudformation_template(template_path):
                        templates.append(template_path)
                for template_path in search_dir.glob("**/*.json"):
                    if self._is_cloudformation_template(template_path):
                        templates.append(template_path)

        return templates

    async def _process_template(
        self,
        template_path: Path,
        repo_path: Path,
        repo_url: str,
    ) -> Optional[TemplateSource]:
        """
        Process a single template.

        Args:
            template_path: Path to template file
            repo_path: Path to repository root
            repo_url: Repository URL

        Returns:
            TemplateSource or None
        """
        # Read template content
        content = template_path.read_text()

        # Generate template ID
        repo_name = repo_url.rstrip("/").split("/")[-1]
        rel_path = template_path.relative_to(repo_path)
        template_id = f"solution-{repo_name}-{rel_path.stem}"

        return TemplateSource(
            source_type=SourceType.GITHUB,
            source_name=self.source_name,
            source_url=repo_url,
            template_path=str(rel_path),
            template_id=template_id,
            raw_content=content,
            commit_sha=await self._get_latest_commit() if self._repo_path else None,
        )
