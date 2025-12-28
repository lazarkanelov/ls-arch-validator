"""Architecture diagram scrapers for AWS and Azure Architecture Centers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.models import SourceType, TemplateSource
from src.miner.sources.base import ExtractionResult, SourceExtractor
from src.utils.logging import get_logger

logger = get_logger("miner.sources.diagrams")

# Architecture Center URLs
AWS_ARCHITECTURE_CENTER = "https://aws.amazon.com/architecture/"
AZURE_ARCHITECTURE_CENTER = "https://learn.microsoft.com/en-us/azure/architecture/"


@dataclass
class DiagramInfo:
    """Information about a discovered architecture diagram."""

    title: str
    description: str
    image_url: str
    page_url: str
    source: str  # "aws" or "azure"
    category: str
    services: list[str]


class AWSArchitectureCenterScraper(SourceExtractor):
    """
    Scraper for AWS Architecture Center diagrams.

    Discovers architecture diagrams from AWS Architecture Center
    and extracts diagram images for parsing.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
    ) -> None:
        """
        Initialize AWS Architecture Center scraper.

        Args:
            cache_dir: Directory for caching
            max_templates: Maximum diagrams to extract
        """
        super().__init__(cache_dir, max_templates)
        self.base_url = AWS_ARCHITECTURE_CENTER

    @property
    def source_name(self) -> str:
        """Source identifier."""
        return "aws-architecture-center"

    @property
    def source_type(self) -> SourceType:
        """Source type."""
        return SourceType.WEB

    async def extract(self) -> ExtractionResult:
        """
        Extract architecture diagrams from AWS Architecture Center.

        Returns:
            ExtractionResult with diagram info as templates
        """
        self._log_extraction_start()

        result = ExtractionResult()

        try:
            # Fetch architecture center page
            diagrams = await self._discover_diagrams()

            for diagram in diagrams:
                if not self._should_continue(len(result.templates)):
                    break

                try:
                    template = await self._process_diagram(diagram)
                    if template:
                        result.templates.append(template)

                except Exception as e:
                    error_msg = f"Error processing diagram {diagram.title}: {e}"
                    result.errors.append(error_msg)
                    self.logger.warning("diagram_error", error=error_msg)

        except Exception as e:
            error_msg = f"Error scraping AWS Architecture Center: {e}"
            result.errors.append(error_msg)
            self.logger.error("scraping_error", error=error_msg)

        self._log_extraction_complete(result)
        return result

    async def check_for_updates(self, last_checked: Optional[str] = None) -> bool:
        """Check for updates (always True for web sources)."""
        return True

    async def _discover_diagrams(self) -> list[DiagramInfo]:
        """
        Discover architecture diagrams from AWS Architecture Center.

        Returns:
            List of diagram information
        """
        import httpx
        from bs4 import BeautifulSoup

        diagrams = []

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.base_url, timeout=30.0)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "lxml")

                # Find reference architecture cards
                # AWS uses specific CSS classes for architecture cards
                cards = soup.select(".m-card, .lb-card, .awsm-card")

                for card in cards:
                    try:
                        # Extract diagram info
                        title_elem = card.select_one("h3, .m-card-title, .lb-title")
                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)

                        # Get link
                        link = card.select_one("a")
                        if not link or not link.get("href"):
                            continue

                        page_url = link["href"]
                        if not page_url.startswith("http"):
                            page_url = f"https://aws.amazon.com{page_url}"

                        # Get description
                        desc_elem = card.select_one("p, .m-card-description")
                        description = desc_elem.get_text(strip=True) if desc_elem else ""

                        # Get image
                        img = card.select_one("img")
                        image_url = img.get("src", "") if img else ""

                        diagrams.append(
                            DiagramInfo(
                                title=title,
                                description=description,
                                image_url=image_url,
                                page_url=page_url,
                                source="aws",
                                category=self._extract_category(page_url),
                                services=self._extract_services_from_text(
                                    f"{title} {description}"
                                ),
                            )
                        )

                    except Exception as e:
                        self.logger.warning("card_parse_error", error=str(e))

        except Exception as e:
            self.logger.error("discover_error", error=str(e))

        return diagrams

    async def _process_diagram(self, diagram: DiagramInfo) -> Optional[TemplateSource]:
        """
        Process a discovered diagram.

        Args:
            diagram: Diagram information

        Returns:
            TemplateSource with diagram metadata
        """
        # Create a template ID from the title
        template_id = f"aws-diagram-{self._slugify(diagram.title)}"

        # Download the diagram image if available
        image_content = None
        if diagram.image_url:
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(diagram.image_url, timeout=30.0)
                    if response.status_code == 200:
                        image_content = response.content

            except Exception as e:
                self.logger.warning(
                    "image_download_error",
                    url=diagram.image_url,
                    error=str(e),
                )

        return TemplateSource(
            source_type=SourceType.WEB,
            source_name=self.source_name,
            source_url=diagram.page_url,
            template_path=diagram.image_url,
            template_id=template_id,
            raw_content="",  # Diagrams don't have text content
            metadata={
                "title": diagram.title,
                "description": diagram.description,
                "category": diagram.category,
                "services": diagram.services,
                "is_diagram": True,
                "image_url": diagram.image_url,
            },
        )

    @staticmethod
    def _extract_category(url: str) -> str:
        """Extract category from URL."""
        parts = url.split("/")
        for i, part in enumerate(parts):
            if part == "architecture" and i + 1 < len(parts):
                return parts[i + 1]
        return "general"

    @staticmethod
    def _extract_services_from_text(text: str) -> list[str]:
        """Extract AWS service names from text."""
        text_lower = text.lower()
        services = []

        # Common AWS services to look for
        service_keywords = [
            ("lambda", "lambda"),
            ("s3", "s3"),
            ("dynamodb", "dynamodb"),
            ("api gateway", "apigateway"),
            ("apigateway", "apigateway"),
            ("sqs", "sqs"),
            ("sns", "sns"),
            ("ec2", "ec2"),
            ("ecs", "ecs"),
            ("eks", "eks"),
            ("rds", "rds"),
            ("aurora", "aurora"),
            ("elasticache", "elasticache"),
            ("cloudfront", "cloudfront"),
            ("route53", "route53"),
            ("cognito", "cognito"),
            ("step functions", "stepfunctions"),
            ("eventbridge", "eventbridge"),
            ("kinesis", "kinesis"),
            ("redshift", "redshift"),
            ("glue", "glue"),
            ("athena", "athena"),
        ]

        for keyword, service in service_keywords:
            if keyword in text_lower:
                services.append(service)

        return list(set(services))

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to URL-safe slug."""
        import re

        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = text.strip("-")
        return text[:50]


class AzureArchitectureCenterScraper(SourceExtractor):
    """
    Scraper for Azure Architecture Center diagrams.

    Discovers architecture diagrams from Azure Architecture Center.
    These will be mapped to AWS equivalents for LocalStack validation.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_templates: Optional[int] = None,
    ) -> None:
        """
        Initialize Azure Architecture Center scraper.

        Args:
            cache_dir: Directory for caching
            max_templates: Maximum diagrams to extract
        """
        super().__init__(cache_dir, max_templates)
        self.base_url = AZURE_ARCHITECTURE_CENTER

    @property
    def source_name(self) -> str:
        """Source identifier."""
        return "azure-architecture-center"

    @property
    def source_type(self) -> SourceType:
        """Source type."""
        return SourceType.WEB

    async def extract(self) -> ExtractionResult:
        """
        Extract architecture diagrams from Azure Architecture Center.

        Returns:
            ExtractionResult with diagram info
        """
        self._log_extraction_start()

        result = ExtractionResult()

        try:
            # Fetch architecture center page
            diagrams = await self._discover_diagrams()

            for diagram in diagrams:
                if not self._should_continue(len(result.templates)):
                    break

                try:
                    template = await self._process_diagram(diagram)
                    if template:
                        result.templates.append(template)

                except Exception as e:
                    error_msg = f"Error processing diagram {diagram.title}: {e}"
                    result.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Error scraping Azure Architecture Center: {e}"
            result.errors.append(error_msg)
            self.logger.error("scraping_error", error=error_msg)

        self._log_extraction_complete(result)
        return result

    async def check_for_updates(self, last_checked: Optional[str] = None) -> bool:
        """Check for updates."""
        return True

    async def _discover_diagrams(self) -> list[DiagramInfo]:
        """
        Discover architecture diagrams from Azure Architecture Center.

        Returns:
            List of diagram information
        """
        import httpx
        from bs4 import BeautifulSoup

        diagrams = []

        # Azure Architecture Center has reference architectures at specific paths
        reference_paths = [
            "reference-architectures/",
            "example-scenario/",
            "solution-ideas/",
        ]

        try:
            async with httpx.AsyncClient() as client:
                for path in reference_paths:
                    url = f"{self.base_url}{path}"

                    try:
                        response = await client.get(url, timeout=30.0)
                        if response.status_code != 200:
                            continue

                        soup = BeautifulSoup(response.text, "lxml")

                        # Find architecture cards
                        cards = soup.select("article, .card, [data-bi-area='body']")

                        for card in cards:
                            try:
                                title_elem = card.select_one("h2, h3, .title")
                                if not title_elem:
                                    continue

                                title = title_elem.get_text(strip=True)

                                link = card.select_one("a")
                                if not link or not link.get("href"):
                                    continue

                                page_url = link["href"]
                                if not page_url.startswith("http"):
                                    page_url = f"https://learn.microsoft.com{page_url}"

                                desc_elem = card.select_one("p, .description")
                                description = (
                                    desc_elem.get_text(strip=True) if desc_elem else ""
                                )

                                img = card.select_one("img")
                                image_url = img.get("src", "") if img else ""

                                diagrams.append(
                                    DiagramInfo(
                                        title=title,
                                        description=description,
                                        image_url=image_url,
                                        page_url=page_url,
                                        source="azure",
                                        category=path.rstrip("/"),
                                        services=self._extract_azure_services(
                                            f"{title} {description}"
                                        ),
                                    )
                                )

                            except Exception as e:
                                self.logger.warning("card_parse_error", error=str(e))

                    except Exception as e:
                        self.logger.warning(
                            "path_fetch_error",
                            path=path,
                            error=str(e),
                        )

        except Exception as e:
            self.logger.error("discover_error", error=str(e))

        return diagrams

    async def _process_diagram(self, diagram: DiagramInfo) -> Optional[TemplateSource]:
        """
        Process a discovered Azure diagram.

        Args:
            diagram: Diagram information

        Returns:
            TemplateSource with diagram metadata
        """
        template_id = f"azure-diagram-{self._slugify(diagram.title)}"

        return TemplateSource(
            source_type=SourceType.WEB,
            source_name=self.source_name,
            source_url=diagram.page_url,
            template_path=diagram.image_url,
            template_id=template_id,
            raw_content="",
            metadata={
                "title": diagram.title,
                "description": diagram.description,
                "category": diagram.category,
                "azure_services": diagram.services,
                "is_diagram": True,
                "requires_mapping": True,  # Flag that this needs Azure -> AWS mapping
                "image_url": diagram.image_url,
            },
        )

    @staticmethod
    def _extract_azure_services(text: str) -> list[str]:
        """Extract Azure service names from text."""
        text_lower = text.lower()
        services = []

        azure_keywords = [
            ("azure functions", "azure-functions"),
            ("blob storage", "blob-storage"),
            ("cosmos db", "cosmos-db"),
            ("api management", "api-management"),
            ("service bus", "service-bus"),
            ("event hubs", "event-hubs"),
            ("azure sql", "azure-sql"),
            ("virtual machines", "virtual-machines"),
            ("app service", "app-service"),
            ("aks", "aks"),
            ("azure kubernetes", "aks"),
            ("redis cache", "redis-cache"),
            ("cdn", "cdn"),
            ("azure ad", "azure-ad"),
            ("logic apps", "logic-apps"),
            ("event grid", "event-grid"),
            ("azure synapse", "synapse"),
        ]

        for keyword, service in azure_keywords:
            if keyword in text_lower:
                services.append(service)

        return list(set(services))

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to URL-safe slug."""
        import re

        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = text.strip("-")
        return text[:50]
