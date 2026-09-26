"""Abstract Storage Backend Protocol.

Decouples workspace file operations from local filesystem APIs, enabling
future seamless migration to cloud object stores or sandbox-mounted volumes.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class StorageError(Exception):
    """Base exception for storage backend operations."""
    pass


class StorageSecurityError(StorageError):
    """Raised when an operation attempts path traversal or escapes boundaries."""
    pass


class BaseStorageBackend(ABC):
    """Interface for pluggable workspace storage engines."""

    @abstractmethod
    async def write_file(self, relative_path: str, content: bytes) -> int:
        """Write bytes to a file path relative to the backend root. Returns bytes written."""
        pass

    @abstractmethod
    async def read_file(self, relative_path: str) -> bytes:
        """Read bytes from a file path relative to the backend root."""
        pass

    @abstractmethod
    async def delete_file(self, relative_path: str) -> bool:
        """Delete a file relative to the backend root. Returns True if deleted."""
        pass

    @abstractmethod
    async def file_exists(self, relative_path: str) -> bool:
        """Check if a file exists relative to the backend root."""
        pass

    @abstractmethod
    async def list_files(self, prefix: str = "") -> List[str]:
        """List all normalized file paths relative to prefix."""
        pass

    @abstractmethod
    async def copy_directory(self, src_prefix: str, dst_prefix: str) -> int:
        """
        Recursively copy all files from src_prefix to dst_prefix.
        Returns count of files copied.
        """
        pass

    @abstractmethod
    async def delete_directory(self, prefix: str) -> int:
        """
        Recursively remove a directory and its contents.
        Returns count of files deleted.
        """
        pass

    @abstractmethod
    async def get_file_stats(self, relative_path: str) -> Dict[str, Any]:
        """Return size in bytes, sha256 checksum, and timestamps."""
        pass
