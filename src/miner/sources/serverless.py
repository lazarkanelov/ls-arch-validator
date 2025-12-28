"""Serverless Framework examples extractor."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.models import SourceType, TemplateSource
from src.miner.sources.base import ExtractionResult, GitHubSourceExtractor
from src.utils.logging import get_logger

logger = get_logger("miner.sources.serverless")

# Serverless examples repository
SERVERLESS_EXAMPLES_REPO = "https://github.com/serverless/examples"


class ServerlessExtractor(GitHubSourceExtractor):
    """
    Extractor for Serverless Framework examples.

    The serverless/examples repository contains many AWS Lambda examples.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
    ) -> None:
        """
        Initialize Serverless extractor.

        Args:
            cache_dir: Directory for caching
            max_templates: Maximum templates to extract
        """
        super().__init__(
            repo_url=SERVERLESS_EXAMPLES_REPO,
            cache_dir=cache_dir,
            max_templates=max_templates,
        )

    @property
    def source_name(self) -> str:
        """Source identifier."""
        return "serverless-examples"

    async def extract(self) -> ExtractionResult:
        """
        Extract templates from Serverless examples repository.

        Returns:
            ExtractionResult with templates
        """
        self._log_extraction_start()

        result = ExtractionResult()

        try:
            # Clone or update repository
            repo_path = await self._clone_or_update_repo()

            # Find serverless.yml files
            template_paths = self._find_serverless_configs(repo_path)
            template_count = 0

            for template_path in template_paths:
                if not self._should_continue(template_count):
                    break

                try:
                    template = await self._process_template(template_path, repo_path)
                    if template:
                        result.templates.append(template)
                        template_count += 1

                except Exception as e:
                    error_msg = f"Error processing {template_path}: {e}"
                    result.errors.append(error_msg)
                    self.logger.warning("template_error", error=error_msg)

        except Exception as e:
            error_msg = f"Error processing repository: {e}"
            result.errors.append(error_msg)
            self.logger.error("repo_error", error=error_msg)

        self._log_extraction_complete(result)
        return result

    async def check_for_updates(self, last_checked: Optional[str] = None) -> bool:
        """Check for updates."""
        return True

    def _find_serverless_configs(self, repo_path: Path) -> list[Path]:
        """
        Find serverless.yml files in repository.

        Args:
            repo_path: Path to repository

        Returns:
            List of serverless.yml paths
        """
        configs = []

        # Find all serverless.yml files
        for config_path in repo_path.glob("**/serverless.yml"):
            # Only include AWS provider configs
            if self._is_aws_serverless(config_path):
                configs.append(config_path)

        # Also check for serverless.yaml
        for config_path in repo_path.glob("**/serverless.yaml"):
            if self._is_aws_serverless(config_path):
                configs.append(config_path)

        return configs

    @staticmethod
    def _is_aws_serverless(config_path: Path) -> bool:
        """
        Check if serverless config is for AWS provider.

        Args:
            config_path: Path to serverless.yml

        Returns:
            True if AWS provider
        """
        try:
            content = config_path.read_text()
            return "provider:" in content and "aws" in content.lower()
        except Exception:
            return False

    async def _process_template(
        self,
        config_path: Path,
        repo_path: Path,
    ) -> Optional[TemplateSource]:
        """
        Process a serverless.yml file.

        Args:
            config_path: Path to serverless.yml
            repo_path: Path to repository root

        Returns:
            TemplateSource or None
        """
        # Read config content
        content = config_path.read_text()

        # Extract example name from path
        example_dir = config_path.parent
        rel_path = example_dir.relative_to(repo_path)
        example_name = str(rel_path).replace("/", "-").replace("\\", "-")

        # Generate template ID
        template_id = f"serverless-{example_name}"

        return TemplateSource(
            source_type=SourceType.GITHUB,
            source_name=self.source_name,
            source_url=f"{self.repo_url}/tree/master/{rel_path}",
            template_path=str(config_path.relative_to(repo_path)),
            template_id=template_id,
            raw_content=content,
            commit_sha=await self._get_latest_commit() if self._repo_path else None,
            metadata={
                "framework": "serverless",
                "example_name": example_name,
            },
        )
