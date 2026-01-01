"""Content-addressable storage for dashboard data.

Inspired by Git's object model:
- Immutable objects stored by SHA256 hash
- Lightweight index with refs only
- Deduplication of identical content
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger("reporter.storage")


class ObjectStore:
    """Git-style content-addressable storage for dashboard objects.

    Objects are stored by their content hash (SHA256), ensuring:
    - Deduplication: identical content stored once
    - Immutability: objects never change once created
    - Verifiability: hash proves content integrity
    """

    HASH_LENGTH = 16  # Use first 16 chars of SHA256 for brevity

    def __init__(self, base_dir: Path) -> None:
        """Initialize the object store.

        Args:
            base_dir: Base directory for data storage (e.g., docs/data)
        """
        self.base_dir = Path(base_dir)
        self.objects_dir = self.base_dir / "objects"
        self.runs_dir = self.base_dir / "runs"
        self.results_dir = self.base_dir / "results"

    def _compute_hash(self, content: dict) -> str:
        """Compute deterministic hash of JSON content."""
        # Sort keys for deterministic serialization
        content_json = json.dumps(content, sort_keys=True, ensure_ascii=False)
        full_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
        return full_hash[: self.HASH_LENGTH]

    def put_object(self, obj_type: str, content: dict) -> str:
        """Store object by content hash.

        Args:
            obj_type: Object type ("arch", "tf", "app")
            content: Object content as dictionary

        Returns:
            Content hash (16 chars)
        """
        content_hash = self._compute_hash(content)
        path = self.objects_dir / obj_type / f"{content_hash}.json"

        # Immutable: never overwrite existing objects
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.debug(
                "object_stored",
                obj_type=obj_type,
                hash=content_hash,
                size=path.stat().st_size,
            )

        return content_hash

    def get_object(self, obj_type: str, content_hash: str) -> Optional[dict]:
        """Retrieve object by hash.

        Args:
            obj_type: Object type ("arch", "tf", "app")
            content_hash: Object hash

        Returns:
            Object content or None if not found
        """
        path = self.objects_dir / obj_type / f"{content_hash}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def object_exists(self, obj_type: str, content_hash: str) -> bool:
        """Check if object exists."""
        path = self.objects_dir / obj_type / f"{content_hash}.json"
        return path.exists()

    def put_architecture(
        self,
        arch_id: str,
        services: list[str],
        source_info: Optional[dict] = None,
    ) -> str:
        """Store architecture metadata.

        Args:
            arch_id: Architecture identifier
            services: List of AWS services used
            source_info: Source information (origin, URL, etc.)

        Returns:
            Content hash
        """
        content = {
            "arch_id": arch_id,
            "services": sorted(services),  # Sort for determinism
            "source_info": source_info,
        }
        return self.put_object("arch", content)

    def put_terraform(
        self,
        main_tf: str,
        variables_tf: Optional[str] = None,
        outputs_tf: Optional[str] = None,
    ) -> str:
        """Store Terraform code.

        Args:
            main_tf: main.tf content
            variables_tf: variables.tf content
            outputs_tf: outputs.tf content

        Returns:
            Content hash
        """
        content = {
            "main_tf": main_tf,
            "variables_tf": variables_tf,
            "outputs_tf": outputs_tf,
        }
        return self.put_object("tf", content)

    def put_app(
        self,
        probe_type: str,
        probe_name: str,
        probed_features: list[str],
        source_files: dict[str, str],
        test_files: dict[str, str],
        requirements: list[str],
    ) -> str:
        """Store generated probe application.

        Args:
            probe_type: Type of probe (api_parity, edge_cases, etc.)
            probe_name: Human-readable probe name
            probed_features: List of features being probed
            source_files: Dict of filename -> content
            test_files: Dict of filename -> content
            requirements: List of pip requirements

        Returns:
            Content hash
        """
        content = {
            "probe_type": probe_type,
            "probe_name": probe_name,
            "probed_features": sorted(probed_features),
            "source_files": source_files,
            "test_files": test_files,
            "requirements": sorted(requirements),
        }
        return self.put_object("app", content)

    def put_result(
        self,
        run_id: str,
        arch_hash: str,
        status: str,
        error_summary: Optional[str] = None,
        infrastructure_error: Optional[str] = None,
        test_results: Optional[list[dict]] = None,
        logs_url: Optional[str] = None,
    ) -> Path:
        """Store per-architecture test result.

        Args:
            run_id: Run identifier
            arch_hash: Architecture content hash
            status: Test status (passed, partial, failed)
            error_summary: Brief error description
            infrastructure_error: Infrastructure-level error
            test_results: List of individual test results
            logs_url: URL to detailed logs

        Returns:
            Path to saved result file
        """
        content = {
            "run_id": run_id,
            "arch_hash": arch_hash,
            "status": status,
            "error_summary": error_summary,
            "infrastructure_error": infrastructure_error,
            "test_results": test_results or [],
            "logs_url": logs_url,
        }

        result_dir = self.results_dir / run_id
        result_dir.mkdir(parents=True, exist_ok=True)
        path = result_dir / f"{arch_hash}.json"
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return path

    def put_run(
        self,
        run_id: str,
        started_at: datetime,
        completed_at: Optional[datetime],
        status: str,
        localstack_version: str,
        statistics: dict,
        architecture_refs: list[str],
    ) -> Path:
        """Store run manifest.

        Args:
            run_id: Run identifier
            started_at: Run start time
            completed_at: Run completion time
            status: Run status
            localstack_version: LocalStack version used
            statistics: Run statistics
            architecture_refs: List of architecture hashes

        Returns:
            Path to saved run file
        """
        content = {
            "id": run_id,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at else None,
            "status": status,
            "localstack_version": localstack_version,
            "statistics": statistics,
            "architecture_refs": architecture_refs,
        }

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{run_id}.json"
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return path

    def list_objects(self, obj_type: str) -> list[str]:
        """List all object hashes of a given type."""
        obj_dir = self.objects_dir / obj_type
        if not obj_dir.exists():
            return []
        return [p.stem for p in obj_dir.glob("*.json")]

    def list_runs(self) -> list[str]:
        """List all run IDs."""
        if not self.runs_dir.exists():
            return []
        return [p.stem for p in self.runs_dir.glob("*.json")]

    def get_stats(self) -> dict:
        """Get storage statistics."""
        stats = {
            "object_counts": {},
            "total_size_bytes": 0,
        }

        for obj_type in ["arch", "tf", "app"]:
            obj_dir = self.objects_dir / obj_type
            if obj_dir.exists():
                files = list(obj_dir.glob("*.json"))
                stats["object_counts"][obj_type] = len(files)
                stats["total_size_bytes"] += sum(f.stat().st_size for f in files)

        return stats


class IndexBuilder:
    """Builds the lightweight index.json for dashboard consumption."""

    def __init__(self, store: ObjectStore) -> None:
        """Initialize the index builder.

        Args:
            store: ObjectStore instance for storing objects
        """
        self.store = store

    def build_index(
        self,
        run_id: str,
        statistics: dict,
        results: list[dict],
        service_coverage: list[dict],
        recent_runs: Optional[list[dict]] = None,
    ) -> dict:
        """Build lightweight index.json.

        Args:
            run_id: Current run identifier
            statistics: Aggregated statistics
            results: List of architecture results with refs
            service_coverage: Service coverage summary
            recent_runs: List of recent run summaries

        Returns:
            Index data structure ready for JSON serialization
        """
        return {
            "version": "2.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "latest_run": run_id,
            "statistics": statistics,
            "service_summary": [
                {"name": s["name"], "pass_rate": s.get("pass_rate", 0)}
                for s in service_coverage[:10]  # Top 10 services
            ],
            "recent_runs": recent_runs or [],
            "results": results,
        }

    def build_result_ref(
        self,
        arch_id: str,
        services: list[str],
        source_info: Optional[dict],
        terraform_code: Optional[dict],
        generated_apps: list[dict],
        status: str,
        error_summary: Optional[str] = None,
        test_failures: Optional[list[str]] = None,
    ) -> dict:
        """Build a result entry with object refs.

        Stores objects and returns refs for the index.

        Args:
            arch_id: Architecture identifier
            services: List of AWS services
            source_info: Architecture source information
            terraform_code: Terraform code dict (main_tf, variables_tf, outputs_tf)
            generated_apps: List of generated probe apps
            status: Test status
            error_summary: Error summary if failed
            test_failures: List of failed test names

        Returns:
            Result entry with object hashes instead of embedded content
        """
        # Store architecture metadata
        arch_hash = self.store.put_architecture(
            arch_id=arch_id,
            services=services,
            source_info=source_info,
        )

        # Store Terraform code
        tf_hash = None
        if terraform_code:
            tf_hash = self.store.put_terraform(
                main_tf=terraform_code.get("main_tf", ""),
                variables_tf=terraform_code.get("variables_tf"),
                outputs_tf=terraform_code.get("outputs_tf"),
            )

        # Store generated apps
        app_hashes = []
        for app in generated_apps:
            app_hash = self.store.put_app(
                probe_type=app.get("probe_type", "api_parity"),
                probe_name=app.get("probe_name", ""),
                probed_features=app.get("probed_features", []),
                source_files=app.get("source_files", {}),
                test_files=app.get("test_files", {}),
                requirements=app.get("requirements", []),
            )
            app_hashes.append(app_hash)

        return {
            "arch_hash": arch_hash,
            "arch_id": arch_id,
            "status": status,
            "services": services,
            "tf_hash": tf_hash,
            "app_hashes": app_hashes,
            "error_summary": error_summary,
            "test_failures": test_failures,
        }

    def save_index(self, index_data: dict) -> Path:
        """Save index.json to disk.

        Args:
            index_data: Index data from build_index()

        Returns:
            Path to saved index file
        """
        path = self.store.base_dir / "index.json"
        path.write_text(json.dumps(index_data, indent=2), encoding="utf-8")

        logger.info(
            "index_saved",
            path=str(path),
            size=path.stat().st_size,
            result_count=len(index_data.get("results", [])),
        )

        return path


def migrate_from_latest_json(old_path: Path, store: ObjectStore) -> dict:
    """Migrate monolithic latest.json to CAS format.

    Args:
        old_path: Path to old latest.json
        store: ObjectStore for new format

    Returns:
        New index.json data
    """
    logger.info("migration_started", source=str(old_path))

    old_data = json.loads(old_path.read_text(encoding="utf-8"))
    builder = IndexBuilder(store)

    # Build results with refs
    results = []
    for item in old_data.get("results", []):
        # Handle both failure and passing format
        result_ref = builder.build_result_ref(
            arch_id=item.get("architecture_id", ""),
            services=item.get("services", []),
            source_info=item.get("source_info"),
            terraform_code=item.get("terraform_code"),
            generated_apps=item.get("generated_apps", []),
            status=item.get("status", "unknown"),
            error_summary=item.get("error_summary"),
            test_failures=item.get("test_failures"),
        )
        results.append(result_ref)

    # Build index
    index_data = builder.build_index(
        run_id=old_data.get("id", "migrated"),
        statistics=old_data.get("statistics", {}),
        results=results,
        service_coverage=old_data.get("service_coverage", []),
        recent_runs=[],
    )

    # Save index
    builder.save_index(index_data)

    logger.info(
        "migration_completed",
        objects_created=store.get_stats()["object_counts"],
        results_count=len(results),
    )

    return index_data
