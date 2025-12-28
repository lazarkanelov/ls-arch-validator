"""AWS Quick Starts template extractor."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.models import SourceType, TemplateSource
from src.miner.sources.base import ExtractionResult, GitHubSourceExtractor
from src.utils.logging import get_logger

logger = get_logger("miner.sources.quickstart")

# AWS Quick Start repositories to mine
QUICKSTART_REPOS = [
    "https://github.com/aws-quickstart/quickstart-linux-bastion",
    "https://github.com/aws-quickstart/quickstart-amazon-vpc",
    "https://github.com/aws-quickstart/quickstart-amazon-eks",
    "https://github.com/aws-quickstart/quickstart-amazon-aurora-mysql",
    "https://github.com/aws-quickstart/quickstart-amazon-aurora-postgresql",
    "https://github.com/aws-quickstart/quickstart-amazon-rds",
    "https://github.com/aws-quickstart/quickstart-amazon-redshift",
    "https://github.com/aws-quickstart/quickstart-amazon-elasticache-redis",
]


class QuickStartExtractor(GitHubSourceExtractor):
    """
    Extractor for AWS Quick Start templates.

    AWS Quick Starts are curated CloudFormation templates that deploy
    popular technologies on AWS with best practices.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
        repos: Optional[list[str]] = None,
    ) -> None:
        """
        Initialize Quick Start extractor.

        Args:
            cache_dir: Directory for caching repositories
            max_templates: Maximum templates to extract
            repos: List of repo URLs (defaults to QUICKSTART_REPOS)
        """
        # Use first repo as base URL for parent class
        repos = repos or QUICKSTART_REPOS
        super().__init__(
            repo_url=repos[0],
            cache_dir=cache_dir,
            max_templates=max_templates,
        )
        self.repos = repos

    @property
    def source_name(self) -> str:
        """Source identifier."""
        return "aws-quickstarts"

    async def extract(self) -> ExtractionResult:
        """
        Extract templates from AWS Quick Start repositories.

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
                template_paths = self._find_cloudformation_templates(repo_path)

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
        """
        Check if any Quick Start repos have updates.

        Args:
            last_checked: ISO timestamp of last check

        Returns:
            True if any repo has updates
        """
        # For simplicity, always return True
        # A real implementation would check commit SHAs
        return True

    async def _process_template(
        self,
        template_path: Path,
        repo_path: Path,
        repo_url: str,
    ) -> Optional[TemplateSource]:
        """
        Process a single CloudFormation template.

        Args:
            template_path: Path to template file
            repo_path: Path to repository root
            repo_url: Repository URL

        Returns:
            TemplateSource or None if not valid
        """
        # Skip non-main templates
        if not self._is_main_template(template_path):
            return None

        # Read template content
        content = template_path.read_text()

        # Generate template ID
        repo_name = repo_url.rstrip("/").split("/")[-1]
        rel_path = template_path.relative_to(repo_path)
        template_id = f"{repo_name}_{rel_path.stem}"

        # Create TemplateSource
        return TemplateSource(
            source_type=SourceType.GITHUB,
            source_name=self.source_name,
            source_url=repo_url,
            template_path=str(rel_path),
            template_id=template_id,
            raw_content=content,
            commit_sha=await self._get_latest_commit() if self._repo_path else None,
        )

    @staticmethod
    def _is_main_template(template_path: Path) -> bool:
        """
        Check if template is a main template (not a nested stack).

        Args:
            template_path: Path to template

        Returns:
            True if main template
        """
        path_str = str(template_path).lower()

        # Skip submodules and nested stacks
        skip_patterns = [
            "/submodules/",
            "/ci/",
            "/test/",
            "/tests/",
            "taskcat",
        ]

        if any(pattern in path_str for pattern in skip_patterns):
            return False

        # Look for main template patterns
        main_patterns = [
            "main",
            "master",
            "workload",
            "entrypoint",
        ]

        filename = template_path.stem.lower()
        return any(pattern in filename for pattern in main_patterns)
