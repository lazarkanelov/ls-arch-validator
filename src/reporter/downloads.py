"""Download file generation for generated apps."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Optional

from src.utils.cache import AppCache
from src.utils.logging import get_logger

logger = get_logger("reporter.downloads")

# Maximum file size for preview (50KB)
MAX_PREVIEW_SIZE = 50000


class AppDownloadGenerator:
    """Generates downloadable zip files and JSON for generated apps."""

    def __init__(self, app_cache: AppCache, output_dir: Path) -> None:
        """
        Initialize the generator.

        Args:
            app_cache: Cache containing generated apps
            output_dir: Base output directory (e.g., docs/)
        """
        self.app_cache = app_cache
        self.output_dir = output_dir
        self.apps_dir = output_dir / "data" / "apps"

    def generate_zip(
        self,
        content_hash: str,
        terraform_content: Optional[str] = None,
        variables_content: Optional[str] = None,
        outputs_content: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Generate a zip file for a cached app.

        Args:
            content_hash: Content hash of the app
            terraform_content: Optional Terraform main.tf content to include
            variables_content: Optional variables.tf content
            outputs_content: Optional outputs.tf content

        Returns:
            Path to generated zip file, or None if app not found
        """
        app_data = self.app_cache.load_app(content_hash)
        if not app_data:
            logger.warning("app_not_found", content_hash=content_hash)
            return None

        self.apps_dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.apps_dir / f"{content_hash}.zip"

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Add Terraform files if provided
                if terraform_content:
                    zf.writestr("terraform/main.tf", terraform_content)
                if variables_content:
                    zf.writestr("terraform/variables.tf", variables_content)
                if outputs_content:
                    zf.writestr("terraform/outputs.tf", outputs_content)

                # Add source files
                for filename, content in app_data.get("source_code", {}).items():
                    zf.writestr(f"app/src/{filename}", content)

                # Add test files
                for filename, content in app_data.get("test_code", {}).items():
                    zf.writestr(f"app/tests/{filename}", content)

                # Add requirements
                requirements = app_data.get("requirements", [])
                if requirements:
                    zf.writestr("app/requirements.txt", "\n".join(requirements))

                # Add metadata
                metadata = app_data.get("metadata", {})
                if metadata:
                    zf.writestr(
                        "metadata.json",
                        json.dumps(metadata, indent=2, default=str),
                    )

            logger.debug("zip_generated", path=str(zip_path))
            return zip_path

        except Exception as e:
            logger.error("zip_generation_failed", content_hash=content_hash, error=str(e))
            return None

    def generate_code_json(
        self,
        content_hash: str,
        terraform_content: Optional[str] = None,
        variables_content: Optional[str] = None,
        outputs_content: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Generate JSON file with code for lazy loading in dashboard.

        Args:
            content_hash: Content hash of the app
            terraform_content: Optional Terraform main.tf content
            variables_content: Optional variables.tf content
            outputs_content: Optional outputs.tf content

        Returns:
            Path to generated JSON file, or None if app not found
        """
        app_data = self.app_cache.load_app(content_hash)
        if not app_data:
            logger.warning("app_not_found_for_json", content_hash=content_hash)
            return None

        json_dir = self.apps_dir / content_hash
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path = json_dir / "code.json"

        try:
            # Truncate large files for preview
            def truncate(content: str) -> str:
                if len(content) > MAX_PREVIEW_SIZE:
                    return content[:MAX_PREVIEW_SIZE] + "\n\n... [truncated, download ZIP for full file]"
                return content

            preview_data = {
                "terraform": {
                    "main_tf": truncate(terraform_content) if terraform_content else None,
                    "variables_tf": truncate(variables_content) if variables_content else None,
                    "outputs_tf": truncate(outputs_content) if outputs_content else None,
                },
                "source_code": {
                    k: truncate(v)
                    for k, v in app_data.get("source_code", {}).items()
                },
                "test_code": {
                    k: truncate(v)
                    for k, v in app_data.get("test_code", {}).items()
                },
                "requirements": app_data.get("requirements", []),
                "truncated": any(
                    len(v) > MAX_PREVIEW_SIZE
                    for v in list(app_data.get("source_code", {}).values())
                    + list(app_data.get("test_code", {}).values())
                    + ([terraform_content] if terraform_content else [])
                ),
            }

            json_path.write_text(json.dumps(preview_data, indent=2))
            logger.debug("code_json_generated", path=str(json_path))
            return json_path

        except Exception as e:
            logger.error("json_generation_failed", content_hash=content_hash, error=str(e))
            return None

    def generate_for_architectures(
        self,
        architectures: dict,
    ) -> dict[str, str]:
        """
        Generate zips and JSON for all architectures.

        Args:
            architectures: Dict of architecture_id -> Architecture objects

        Returns:
            Dict of content_hash -> download URL
        """
        download_urls = {}

        for arch_id, arch in architectures.items():
            if not arch.content_hash:
                continue

            # Generate zip
            zip_path = self.generate_zip(
                arch.content_hash,
                terraform_content=arch.terraform_content,
                variables_content=arch.variables_content,
                outputs_content=arch.outputs_content,
            )

            if zip_path:
                download_urls[arch.content_hash] = f"data/apps/{arch.content_hash}.zip"

                # Also generate JSON for lazy loading
                self.generate_code_json(
                    arch.content_hash,
                    terraform_content=arch.terraform_content,
                    variables_content=arch.variables_content,
                    outputs_content=arch.outputs_content,
                )

        logger.info("downloads_generated", count=len(download_urls))
        return download_urls
