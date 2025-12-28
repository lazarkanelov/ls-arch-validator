"""File-based caching utility with content hashing."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger("cache")


def get_cache_key(content: str, version: str = "1.0") -> str:
    """
    Generate a cache key from content and version.

    Args:
        content: Content to hash
        version: Version string to include in hash

    Returns:
        16-character hex hash
    """
    combined = f"{content}{version}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def get_content_hash(content: str) -> str:
    """
    Generate a SHA256 hash of content.

    Args:
        content: Content to hash

    Returns:
        Full SHA256 hex digest
    """
    return hashlib.sha256(content.encode()).hexdigest()


class FileCache:
    """
    File-based cache for storing and retrieving cached data.

    Supports both raw content and JSON-serializable objects.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        """
        Initialize the cache.

        Args:
            cache_dir: Base directory for cache storage
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str, subdir: str = "") -> Path:
        """Get the file path for a cache key."""
        if subdir:
            path = self.cache_dir / subdir / key
        else:
            path = self.cache_dir / key
        return path

    def exists(self, key: str, subdir: str = "") -> bool:
        """Check if a cache entry exists."""
        path = self._get_path(key, subdir)
        return path.exists()

    def get(self, key: str, subdir: str = "") -> Optional[str]:
        """
        Get raw content from cache.

        Args:
            key: Cache key
            subdir: Optional subdirectory

        Returns:
            Cached content or None if not found
        """
        path = self._get_path(key, subdir)
        if not path.exists():
            return None

        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("cache_read_error", key=key, error=str(e))
            return None

    def set(self, key: str, content: str, subdir: str = "") -> None:
        """
        Store raw content in cache.

        Args:
            key: Cache key
            content: Content to cache
            subdir: Optional subdirectory
        """
        path = self._get_path(key, subdir)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            path.write_text(content, encoding="utf-8")
            logger.debug("cache_write", key=key, size=len(content))
        except Exception as e:
            logger.error("cache_write_error", key=key, error=str(e))
            raise

    def get_json(self, key: str, subdir: str = "") -> Optional[dict[str, Any]]:
        """
        Get JSON data from cache.

        Args:
            key: Cache key
            subdir: Optional subdirectory

        Returns:
            Parsed JSON data or None if not found
        """
        content = self.get(key, subdir)
        if content is None:
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("cache_json_error", key=key, error=str(e))
            return None

    def set_json(self, key: str, data: dict[str, Any], subdir: str = "") -> None:
        """
        Store JSON data in cache.

        Args:
            key: Cache key
            data: Data to serialize and cache
            subdir: Optional subdirectory
        """
        content = json.dumps(data, indent=2, default=str)
        self.set(key, content, subdir)

    def delete(self, key: str, subdir: str = "") -> bool:
        """
        Delete a cache entry.

        Args:
            key: Cache key
            subdir: Optional subdirectory

        Returns:
            True if deleted, False if not found
        """
        path = self._get_path(key, subdir)
        if path.exists():
            try:
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                else:
                    path.unlink()
                logger.debug("cache_delete", key=key)
                return True
            except Exception as e:
                logger.error("cache_delete_error", key=key, error=str(e))
                return False
        return False

    def list_keys(self, subdir: str = "", pattern: str = "*") -> list[str]:
        """
        List cache keys in a subdirectory.

        Args:
            subdir: Optional subdirectory
            pattern: Glob pattern for filtering

        Returns:
            List of cache keys
        """
        search_dir = self.cache_dir / subdir if subdir else self.cache_dir
        if not search_dir.exists():
            return []

        return [p.name for p in search_dir.glob(pattern)]

    def get_size(self) -> int:
        """
        Get total cache size in bytes.

        Returns:
            Total size of all cached files
        """
        total = 0
        for path in self.cache_dir.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total

    def clear(self, subdir: str = "") -> int:
        """
        Clear cache entries.

        Args:
            subdir: Optional subdirectory to clear (empty = clear all)

        Returns:
            Number of entries deleted
        """
        import shutil

        target = self.cache_dir / subdir if subdir else self.cache_dir
        if not target.exists():
            return 0

        count = 0
        if subdir:
            # Clear subdirectory contents
            for path in target.iterdir():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    count += 1
                except Exception as e:
                    logger.warning("cache_clear_error", path=str(path), error=str(e))
        else:
            # Clear all subdirectories
            for path in target.iterdir():
                if path.is_dir():
                    try:
                        shutil.rmtree(path)
                        count += 1
                    except Exception as e:
                        logger.warning("cache_clear_error", path=str(path), error=str(e))

        logger.info("cache_cleared", subdir=subdir, count=count)
        return count


class ArchitectureCache(FileCache):
    """Specialized cache for architecture data."""

    def __init__(self, cache_dir: str | Path) -> None:
        super().__init__(Path(cache_dir) / "architectures")

    def save_architecture(
        self,
        arch_id: str,
        main_tf: str,
        variables_tf: Optional[str] = None,
        outputs_tf: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Save architecture files to cache.

        Args:
            arch_id: Architecture identifier
            main_tf: Main Terraform content
            variables_tf: Optional variables.tf content
            outputs_tf: Optional outputs.tf content
            metadata: Optional metadata dict

        Returns:
            Content hash
        """
        # Create directory for this architecture
        arch_dir = self.cache_dir / arch_id
        arch_dir.mkdir(parents=True, exist_ok=True)

        # Write files
        (arch_dir / "main.tf").write_text(main_tf, encoding="utf-8")

        if variables_tf:
            (arch_dir / "variables.tf").write_text(variables_tf, encoding="utf-8")

        if outputs_tf:
            (arch_dir / "outputs.tf").write_text(outputs_tf, encoding="utf-8")

        content_hash = get_content_hash(main_tf)

        if metadata:
            metadata["content_hash"] = content_hash
            (arch_dir / "metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )

        logger.debug("architecture_cached", arch_id=arch_id, content_hash=content_hash)
        return content_hash

    def load_architecture(self, arch_id: str) -> Optional[dict]:
        """
        Load architecture files from cache.

        Args:
            arch_id: Architecture identifier

        Returns:
            Dict with main_tf, variables_tf, outputs_tf, metadata
        """
        arch_dir = self.cache_dir / arch_id
        if not arch_dir.exists():
            return None

        main_tf_path = arch_dir / "main.tf"
        if not main_tf_path.exists():
            return None

        result: dict[str, Any] = {
            "main_tf": main_tf_path.read_text(encoding="utf-8"),
            "variables_tf": None,
            "outputs_tf": None,
            "metadata": None,
        }

        variables_path = arch_dir / "variables.tf"
        if variables_path.exists():
            result["variables_tf"] = variables_path.read_text(encoding="utf-8")

        outputs_path = arch_dir / "outputs.tf"
        if outputs_path.exists():
            result["outputs_tf"] = outputs_path.read_text(encoding="utf-8")

        metadata_path = arch_dir / "metadata.json"
        if metadata_path.exists():
            result["metadata"] = json.loads(metadata_path.read_text(encoding="utf-8"))

        return result

    def evict_oldest(self) -> bool:
        """
        Evict the oldest architecture from cache.

        Returns:
            True if an entry was evicted
        """
        import shutil

        oldest_path = None
        oldest_time = None

        for path in self.cache_dir.iterdir():
            if path.is_dir():
                try:
                    mtime = path.stat().st_mtime
                    if oldest_time is None or mtime < oldest_time:
                        oldest_time = mtime
                        oldest_path = path
                except OSError:
                    continue

        if oldest_path:
            try:
                shutil.rmtree(oldest_path)
                logger.debug("architecture_evicted", arch_id=oldest_path.name)
                return True
            except OSError as e:
                logger.warning("eviction_failed", path=str(oldest_path), error=str(e))

        return False


class AppCache(FileCache):
    """Specialized cache for generated sample apps."""

    def __init__(self, cache_dir: str | Path) -> None:
        super().__init__(Path(cache_dir) / "apps")

    def get_app_path(self, content_hash: str) -> Path:
        """Get the path for a cached app."""
        return self.cache_dir / content_hash

    def app_exists(self, content_hash: str) -> bool:
        """Check if an app is cached."""
        app_path = self.get_app_path(content_hash)
        return (app_path / "metadata.json").exists()

    def save_app(
        self,
        content_hash: str,
        source_code: dict[str, str],
        test_code: dict[str, str],
        requirements: list[str],
        metadata: dict,
    ) -> None:
        """
        Save generated app to cache.

        Args:
            content_hash: Content hash for cache key
            source_code: Source files mapping
            test_code: Test files mapping
            requirements: Python requirements
            metadata: Generation metadata
        """
        app_dir = self.get_app_path(content_hash)
        src_dir = app_dir / "src"
        tests_dir = app_dir / "tests"

        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        # Write source files
        for filename, content in source_code.items():
            file_path = src_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        # Write test files
        for filename, content in test_code.items():
            file_path = tests_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        # Write requirements
        (app_dir / "requirements.txt").write_text(
            "\n".join(requirements), encoding="utf-8"
        )

        # Write metadata
        (app_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        logger.debug("app_cached", content_hash=content_hash)

    def load_app(self, content_hash: str) -> Optional[dict]:
        """
        Load app from cache.

        Returns:
            Dict with source_code, test_code, requirements, metadata
        """
        app_dir = self.get_app_path(content_hash)
        if not self.app_exists(content_hash):
            return None

        result: dict[str, Any] = {
            "source_code": {},
            "test_code": {},
            "requirements": [],
            "metadata": {},
        }

        # Load source files
        src_dir = app_dir / "src"
        if src_dir.exists():
            for path in src_dir.rglob("*.py"):
                rel_path = path.relative_to(src_dir)
                result["source_code"][str(rel_path)] = path.read_text(encoding="utf-8")

        # Load test files
        tests_dir = app_dir / "tests"
        if tests_dir.exists():
            for path in tests_dir.rglob("*.py"):
                rel_path = path.relative_to(tests_dir)
                result["test_code"][str(rel_path)] = path.read_text(encoding="utf-8")

        # Load requirements
        req_path = app_dir / "requirements.txt"
        if req_path.exists():
            result["requirements"] = [
                line.strip()
                for line in req_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        # Load metadata
        meta_path = app_dir / "metadata.json"
        if meta_path.exists():
            result["metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))

        return result

    def evict_oldest(self) -> bool:
        """
        Evict the oldest app from cache.

        Returns:
            True if an entry was evicted
        """
        import shutil

        oldest_path = None
        oldest_time = None

        for path in self.cache_dir.iterdir():
            if path.is_dir():
                try:
                    mtime = path.stat().st_mtime
                    if oldest_time is None or mtime < oldest_time:
                        oldest_time = mtime
                        oldest_path = path
                except OSError:
                    continue

        if oldest_path:
            try:
                shutil.rmtree(oldest_path)
                logger.debug("app_evicted", content_hash=oldest_path.name)
                return True
            except OSError as e:
                logger.warning("eviction_failed", path=str(oldest_path), error=str(e))

        return False
