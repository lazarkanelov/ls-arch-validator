"""Terraform Registry module extractor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from src.models import SourceType, TemplateSource
from src.miner.sources.base import ExtractionResult, RegistrySourceExtractor
from src.utils.logging import get_logger

logger = get_logger("miner.sources.terraform")

# Terraform Registry API base URL
TERRAFORM_REGISTRY_API = "https://registry.terraform.io/v1"

# Popular AWS modules to mine
AWS_MODULES = [
    ("terraform-aws-modules", "vpc"),
    ("terraform-aws-modules", "ec2-instance"),
    ("terraform-aws-modules", "s3-bucket"),
    ("terraform-aws-modules", "lambda"),
    ("terraform-aws-modules", "rds"),
    ("terraform-aws-modules", "dynamodb-table"),
    ("terraform-aws-modules", "sqs"),
    ("terraform-aws-modules", "sns"),
    ("terraform-aws-modules", "apigateway-v2"),
    ("terraform-aws-modules", "ecs"),
    ("terraform-aws-modules", "eks"),
    ("terraform-aws-modules", "step-functions"),
    ("terraform-aws-modules", "eventbridge"),
    ("terraform-aws-modules", "iam"),
    ("terraform-aws-modules", "acm"),
    ("terraform-aws-modules", "cloudwatch"),
]


class TerraformRegistryExtractor(RegistrySourceExtractor):
    """
    Extractor for Terraform Registry modules.

    Fetches popular AWS modules from the Terraform Registry.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
        modules: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        """
        Initialize Terraform Registry extractor.

        Args:
            cache_dir: Directory for caching modules
            max_templates: Maximum templates to extract
            modules: List of (namespace, name) tuples (defaults to AWS_MODULES)
        """
        super().__init__(
            api_base_url=TERRAFORM_REGISTRY_API,
            cache_dir=cache_dir,
            max_templates=max_templates,
        )
        self.modules = modules or AWS_MODULES

    @property
    def source_name(self) -> str:
        """Source identifier."""
        return "terraform-registry"

    async def extract(self) -> ExtractionResult:
        """
        Extract templates from Terraform Registry.

        Returns:
            ExtractionResult with templates
        """
        self._log_extraction_start()

        result = ExtractionResult()
        template_count = 0

        for namespace, module_name in self.modules:
            if not self._should_continue(template_count):
                break

            try:
                template = await self._process_module(namespace, module_name)
                if template:
                    result.templates.append(template)
                    template_count += 1

            except Exception as e:
                error_msg = f"Error processing {namespace}/{module_name}: {e}"
                result.errors.append(error_msg)
                self.logger.warning("module_error", error=error_msg)

        self._log_extraction_complete(result)
        return result

    async def check_for_updates(self, last_checked: Optional[str] = None) -> bool:
        """
        Check if any modules have updates.

        Args:
            last_checked: ISO timestamp of last check

        Returns:
            True if any module has updates
        """
        # Always return True for simplicity
        # A real implementation would check module versions
        return True

    async def _process_module(
        self,
        namespace: str,
        module_name: str,
    ) -> Optional[TemplateSource]:
        """
        Process a single Terraform module.

        Args:
            namespace: Module namespace
            module_name: Module name

        Returns:
            TemplateSource or None if not available
        """
        # Get module metadata
        module_url = f"{self.api_base_url}/modules/{namespace}/{module_name}/aws"

        try:
            metadata = await self._fetch_json(module_url)
        except Exception as e:
            self.logger.warning(
                "module_fetch_failed",
                namespace=namespace,
                module=module_name,
                error=str(e),
            )
            return None

        # Get latest version
        version = metadata.get("version")
        if not version:
            return None

        # Get download URL
        download_url = await self._get_download_url(namespace, module_name, version)
        if not download_url:
            return None

        # Download module content
        content = await self._download_module(download_url)
        if not content:
            return None

        # Create TemplateSource
        template_id = f"terraform-{namespace}-{module_name}"

        return TemplateSource(
            source_type=SourceType.REGISTRY,
            source_name=self.source_name,
            source_url=f"https://registry.terraform.io/modules/{namespace}/{module_name}/aws",
            template_path="main.tf",
            template_id=template_id,
            raw_content=content,
            version=version,
            metadata={
                "namespace": namespace,
                "module_name": module_name,
                "downloads": metadata.get("downloads"),
                "published_at": metadata.get("published_at"),
            },
        )

    async def _get_download_url(
        self,
        namespace: str,
        module_name: str,
        version: str,
    ) -> Optional[str]:
        """
        Get download URL for module version.

        Args:
            namespace: Module namespace
            module_name: Module name
            version: Module version

        Returns:
            Download URL or None
        """
        url = f"{self.api_base_url}/modules/{namespace}/{module_name}/aws/{version}/download"

        try:
            import httpx

            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url)
                # The API returns a redirect with X-Terraform-Get header
                if "X-Terraform-Get" in response.headers:
                    return response.headers["X-Terraform-Get"]
                return str(response.url)

        except Exception as e:
            self.logger.warning(
                "download_url_failed",
                namespace=namespace,
                module=module_name,
                error=str(e),
            )
            return None

    async def _download_module(self, url: str) -> Optional[str]:
        """
        Download and extract module content.

        Args:
            url: Module download URL

        Returns:
            Main Terraform content or None
        """
        import asyncio
        import tempfile

        try:
            import httpx

            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()

                # Module is typically a tarball
                if url.endswith(".tar.gz") or "tar.gz" in url:
                    return await self._extract_tarball(response.content)
                else:
                    # Might be raw content
                    return response.text

        except Exception as e:
            self.logger.warning("download_failed", url=url, error=str(e))
            return None

    async def _extract_tarball(self, content: bytes) -> Optional[str]:
        """
        Extract main.tf from tarball.

        Args:
            content: Tarball bytes

        Returns:
            Main Terraform content or None
        """
        import io
        import tarfile

        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.endswith("main.tf"):
                        f = tar.extractfile(member)
                        if f:
                            return f.read().decode("utf-8")

        except Exception as e:
            self.logger.warning("tarball_extraction_failed", error=str(e))

        return None
