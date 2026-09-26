"""Local filesystem storage backend implementation with strict path containment."""

import os
import shutil
import hashlib
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from backend.app.storage.base import BaseStorageBackend, StorageSecurityError, StorageError


class LocalStorageBackend(BaseStorageBackend):
    """
    Local filesystem storage engine with jail protection.
    Every operation is strictly quarantined within base_directory.
    """

    def __init__(self, base_directory: str | Path):
        self.base_path = Path(base_directory).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, relative_path: str) -> Path:
        """
        Validate and resolve a relative path against the jail root.
        Throws StorageSecurityError if path traversal is detected.
        """
        # Normalize and remove leading slashes or Windows drives
        clean_rel = os.path.normpath(relative_path).lstrip("/\\")
        
        # Check for explicit traversal components
        parts = Path(clean_rel).parts
        if ".." in parts:
            raise StorageSecurityError(f"Path traversal detected in path: '{relative_path}'")

        target = (self.base_path / clean_rel).resolve()
        
        try:
            # Check commonpath containment
            common = os.path.commonpath([str(self.base_path), str(target)])
            if common != str(self.base_path):
                raise StorageSecurityError(f"Target path '{relative_path}' escapes storage root '{self.base_path}'")
        except ValueError:
            raise StorageSecurityError(f"Target path '{relative_path}' is on a different drive or invalid")

        return target

    async def write_file(self, relative_path: str, content: bytes) -> int:
        target = self._resolve_safe_path(relative_path)

        def _write():
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as f:
                return f.write(content)

        return await asyncio.to_thread(_write)

    async def read_file(self, relative_path: str) -> bytes:
        target = self._resolve_safe_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: '{relative_path}'")

        def _read():
            with open(target, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read)

    async def delete_file(self, relative_path: str) -> bool:
        target = self._resolve_safe_path(relative_path)
        if not target.exists():
            return False

        def _delete():
            if target.is_file():
                target.unlink()
                return True
            return False

        return await asyncio.to_thread(_delete)

    async def file_exists(self, relative_path: str) -> bool:
        target = self._resolve_safe_path(relative_path)
        return await asyncio.to_thread(target.is_file)

    async def list_files(self, prefix: str = "") -> List[str]:
        target_dir = self._resolve_safe_path(prefix)
        if not target_dir.exists():
            return []

        def _list():
            file_list: List[str] = []
            if target_dir.is_file():
                return [str(target_dir.relative_to(self.base_path)).replace("\\", "/")]

            for root, _, files in os.walk(target_dir):
                for f in files:
                    full_p = Path(root) / f
                    rel_p = str(full_p.relative_to(self.base_path)).replace("\\", "/")
                    file_list.append(rel_p)
            file_list.sort()
            return file_list

        return await asyncio.to_thread(_list)

    async def copy_directory(self, src_prefix: str, dst_prefix: str) -> int:
        src = self._resolve_safe_path(src_prefix)
        dst = self._resolve_safe_path(dst_prefix)

        if not src.exists() or not src.is_dir():
            return 0

        def _copy():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            # Count copied files
            count = 0
            for _, _, files in os.walk(dst):
                count += len(files)
            return count

        return await asyncio.to_thread(_copy)

    async def delete_directory(self, prefix: str) -> int:
        target = self._resolve_safe_path(prefix)
        if not target.exists():
            return 0

        def _rm():
            count = 0
            if target.is_dir():
                for _, _, files in os.walk(target):
                    count += len(files)
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
                count = 1
            return count

        return await asyncio.to_thread(_rm)

    async def get_file_stats(self, relative_path: str) -> Dict[str, Any]:
        target = self._resolve_safe_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"File not found: '{relative_path}'")

        def _stats():
            stat_res = target.stat()
            hasher = hashlib.sha256()
            with open(target, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return {
                "size_bytes": stat_res.st_size,
                "sha256": hasher.hexdigest(),
                "mtime": stat_res.st_mtime,
            }

        return await asyncio.to_thread(_stats)
