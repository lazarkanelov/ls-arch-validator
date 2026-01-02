"""Architecture registry for tracking discovered architectures over time.

This module provides cumulative tracking of architectures:
- Stores all discovered architectures permanently
- Tracks test history for each architecture
- Supports incremental discovery (only add new)
- Provides growth metrics over time
"""

from src.registry.tracker import (
    ArchitectureRegistry,
    ArchitectureRecord,
    TestRecord,
    RegistryStats,
)

__all__ = [
    "ArchitectureRegistry",
    "ArchitectureRecord",
    "TestRecord",
    "RegistryStats",
]
