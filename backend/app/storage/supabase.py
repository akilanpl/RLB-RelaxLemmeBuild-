"""Supabase Storage implementation of the existing storage contract."""

from typing import Any, Dict, List
from urllib.parse import quote
import hashlib

from backend.app.storage.base import BaseStorageBackend, StorageError


class SupabaseStorageBackend(BaseStorageBackend):
    def __init__(self, client: Any, bucket: str = "workspace-artifacts"):
        self.client = client
        self.bucket = bucket

    def _path(self, path: str) -> str:
        clean = path.replace("\\", "/").lstrip("/")
        if ".." in clean.split("/"):
            raise StorageError("Storage path escapes bucket.")
        return clean

    async def write_file(self, relative_path: str, content: bytes) -> int:
        path = self._path(relative_path)
        await self.client.upload(self.bucket, path, content, upsert=True)
        return len(content)

    async def read_file(self, relative_path: str) -> bytes:
        return await self.client.download(self.bucket, self._path(relative_path))

    async def delete_file(self, relative_path: str) -> bool:
        await self.client.remove(self.bucket, [self._path(relative_path)])
        return True

    async def file_exists(self, relative_path: str) -> bool:
        try:
            await self.read_file(relative_path)
            return True
        except Exception:
            return False

    async def list_files(self, prefix: str = "") -> List[str]:
        return await self.client.list(self.bucket, self._path(prefix))

    async def copy_directory(self, src_prefix: str, dst_prefix: str) -> int:
        count = 0
        for path in await self.list_files(src_prefix):
            relative = path[len(self._path(src_prefix)):].lstrip("/")
            await self.write_file(f"{dst_prefix}/{relative}", await self.read_file(path))
            count += 1
        return count

    async def delete_directory(self, prefix: str) -> int:
        paths = await self.list_files(prefix)
        if paths:
            await self.client.remove(self.bucket, paths)
        return len(paths)

    async def get_file_stats(self, relative_path: str) -> Dict[str, Any]:
        content = await self.read_file(relative_path)
        return {"size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
