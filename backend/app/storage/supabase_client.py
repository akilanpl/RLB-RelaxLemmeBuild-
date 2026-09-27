"""Supabase Storage HTTP client; service credentials stay server-side."""
from urllib.parse import quote
import httpx
from backend.app.storage.base import StorageError


class SupabaseStorageClient:
    def __init__(self, url: str, service_key: str, transport=None):
        self.url = url.rstrip('/') + '/storage/v1'
        self.headers = {'apikey': service_key, 'Authorization': 'Bearer ' + service_key}
        self.transport = transport

    async def _request(self, method, path, **kwargs):
        async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
            response = await client.request(method, self.url + path, headers=self.headers, **kwargs)
        if response.status_code == 404:
            raise FileNotFoundError('Workspace artifact not found.')
        if response.is_error:
            raise StorageError(f'Supabase Storage request failed ({response.status_code}).')
        return response

    async def upload(self, bucket, path, content, upsert=True):
        async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
            response = await client.post(
                self.url + '/object/' + quote(bucket, safe='') + '/' + quote(path, safe='/'),
                headers={**self.headers, 'x-upsert': str(upsert).lower(),
                         'Content-Type': 'application/octet-stream'}, content=content)
        if response.is_error:
            raise StorageError(f'Supabase Storage upload failed ({response.status_code}).')

    async def download(self, bucket, path):
        return (await self._request('GET', '/object/authenticated/' + quote(bucket, safe='') + '/' + quote(path, safe='/'))).content

    async def remove(self, bucket, paths):
        for offset in range(0, len(paths), 100):
            await self._request('DELETE', '/object/' + quote(bucket, safe=''), json={'prefixes': paths[offset:offset + 100]})

    async def list(self, bucket, prefix):
        result = []
        folders = [prefix.rstrip('/')]
        while folders:
            folder = folders.pop()
            offset = 0
            while True:
                response = await self._request('POST', '/object/list/' + quote(bucket, safe=''),
                    json={'prefix': folder, 'limit': 100, 'offset': offset,
                          'sortBy': {'column': 'name', 'order': 'asc'}})
                rows = response.json()
                if not isinstance(rows, list):
                    raise StorageError('Invalid Supabase Storage listing response.')
                for row in rows:
                    name = row['name']
                    if name in {'.', '..'} or '/' in name or '\\' in name:
                        raise StorageError('Invalid artifact name in storage listing.')
                    path = f'{folder}/{name}' if folder else name
                    if row.get('id') is None:
                        folders.append(path)
                    else:
                        result.append(path)
                if len(rows) < 100:
                    break
                offset += len(rows)
        return sorted(result)
