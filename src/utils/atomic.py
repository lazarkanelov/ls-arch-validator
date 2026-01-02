"""Atomic file operations to prevent data corruption.

This module provides context managers for writing files atomically,
ensuring that partial writes don't leave corrupted files.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from src.utils.logging import get_logger

logger = get_logger("utils.atomic")


class AtomicWriteError(Exception):
    """Raised when an atomic write operation fails."""

    pass


@contextmanager
def atomic_write(
    path: Path,
    mode: str = "w",
    encoding: str = "utf-8",
) -> Generator[Any, None, None]:
    """
    Context manager for atomic file writes.

    Writes to a temporary file first, then atomically renames to the target path.
    If any error occurs, the temp file is cleaned up and the original is untouched.

    Args:
        path: Target file path
        mode: File mode ('w' for text, 'wb' for binary)
        encoding: Text encoding (ignored for binary mode)

    Yields:
        File handle for writing

    Raises:
        AtomicWriteError: If the atomic write fails

    Example:
        with atomic_write(Path("config.json")) as f:
            json.dump(data, f)
        # File is now atomically updated
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory for atomic rename
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )

    temp_path = Path(temp_path)
    success = False

    try:
        # Close the file descriptor, we'll open with proper mode
        os.close(fd)

        if "b" in mode:
            with open(temp_path, mode) as f:
                yield f
        else:
            with open(temp_path, mode, encoding=encoding) as f:
                yield f

        # Atomic rename (works on POSIX, on Windows requires temp file on same volume)
        temp_path.replace(path)
        success = True

        logger.debug("atomic_write_success", path=str(path))

    except Exception as e:
        logger.error("atomic_write_failed", path=str(path), error=str(e))
        raise AtomicWriteError(f"Failed to atomically write {path}: {e}") from e

    finally:
        if not success and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Atomically write text content to a file.

    Args:
        path: Target file path
        content: Text content to write
        encoding: Text encoding
    """
    with atomic_write(path, encoding=encoding) as f:
        f.write(content)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """
    Atomically write binary content to a file.

    Args:
        path: Target file path
        content: Binary content to write
    """
    with atomic_write(path, mode="wb") as f:
        f.write(content)


def atomic_write_json(
    path: Path,
    data: Any,
    indent: int = 2,
    default: Any = str,
    encoding: str = "utf-8",
) -> None:
    """
    Atomically write JSON data to a file.

    Args:
        path: Target file path
        data: Data to serialize as JSON
        indent: JSON indentation level
        default: Default function for non-serializable objects
        encoding: Text encoding
    """
    with atomic_write(path, encoding=encoding) as f:
        json.dump(data, f, indent=indent, default=default)


@contextmanager
def atomic_directory_write(
    base_path: Path,
    dir_name: str,
) -> Generator[Path, None, None]:
    """
    Context manager for atomic directory creation.

    Creates a temporary directory, yields it for writing, then atomically
    renames to the target path.

    Args:
        base_path: Parent directory
        dir_name: Target directory name

    Yields:
        Temporary directory path for writing

    Note:
        Atomic rename of directories is only guaranteed if source and target
        are on the same filesystem.
    """
    import shutil

    base_path = Path(base_path)
    base_path.mkdir(parents=True, exist_ok=True)

    target_path = base_path / dir_name
    temp_path = base_path / f".{dir_name}.tmp.{os.getpid()}"

    success = False

    try:
        # Create temp directory
        temp_path.mkdir(parents=True, exist_ok=True)

        yield temp_path

        # Remove existing target if present
        if target_path.exists():
            shutil.rmtree(target_path)

        # Atomic rename
        temp_path.rename(target_path)
        success = True

        logger.debug("atomic_dir_write_success", path=str(target_path))

    except Exception as e:
        logger.error("atomic_dir_write_failed", path=str(target_path), error=str(e))
        raise AtomicWriteError(f"Failed to atomically write directory {target_path}: {e}") from e

    finally:
        if not success and temp_path.exists():
            try:
                shutil.rmtree(temp_path)
            except OSError:
                pass


class AtomicFileWriter:
    """
    Class-based atomic file writer for more complex operations.

    Allows writing to multiple files atomically - either all succeed or none.
    """

    def __init__(self, base_path: Path) -> None:
        """
        Initialize the atomic writer.

        Args:
            base_path: Base directory for all writes
        """
        self.base_path = Path(base_path)
        self._pending_writes: list[tuple[Path, str | bytes, bool]] = []
        self._temp_files: list[Path] = []

    def add_text(self, relative_path: str, content: str) -> None:
        """
        Queue a text file for atomic write.

        Args:
            relative_path: Path relative to base_path
            content: Text content to write
        """
        target = self.base_path / relative_path
        self._pending_writes.append((target, content, False))

    def add_bytes(self, relative_path: str, content: bytes) -> None:
        """
        Queue a binary file for atomic write.

        Args:
            relative_path: Path relative to base_path
            content: Binary content to write
        """
        target = self.base_path / relative_path
        self._pending_writes.append((target, content, True))

    def add_json(self, relative_path: str, data: Any) -> None:
        """
        Queue a JSON file for atomic write.

        Args:
            relative_path: Path relative to base_path
            data: Data to serialize as JSON
        """
        content = json.dumps(data, indent=2, default=str)
        self.add_text(relative_path, content)

    def commit(self) -> None:
        """
        Atomically commit all pending writes.

        All files are written to temp files first, then renamed atomically.
        If any write fails, all temp files are cleaned up.
        """
        self._temp_files = []

        try:
            # Phase 1: Write all to temp files
            for target, content, is_binary in self._pending_writes:
                target.parent.mkdir(parents=True, exist_ok=True)

                fd, temp_path = tempfile.mkstemp(
                    dir=target.parent,
                    prefix=f".{target.name}.",
                    suffix=".tmp",
                )

                temp_path = Path(temp_path)
                self._temp_files.append((temp_path, target))

                os.close(fd)

                if is_binary:
                    temp_path.write_bytes(content)
                else:
                    temp_path.write_text(content)

            # Phase 2: Rename all temp files atomically
            for temp_path, target in self._temp_files:
                temp_path.replace(target)

            logger.debug("atomic_batch_commit_success", file_count=len(self._pending_writes))

        except Exception as e:
            # Cleanup all temp files
            for temp_path, _ in self._temp_files:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

            raise AtomicWriteError(f"Batch atomic write failed: {e}") from e

        finally:
            self._pending_writes = []
            self._temp_files = []

    def __enter__(self) -> "AtomicFileWriter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            # Clean up any temp files on exception
            for temp_path, _ in self._temp_files:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
