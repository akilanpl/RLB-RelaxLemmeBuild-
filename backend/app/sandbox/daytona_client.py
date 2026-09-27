"""Bridge the injected Daytona driver contract to the official async SDK."""
import asyncio
import math
import posixpath
from time import monotonic
from types import SimpleNamespace


class DaytonaRuntimeClient:
    def __init__(self, sdk, storage, image: str, params_type=None, resources_type=None):
        self.sdk, self.storage, self.image = sdk, storage, image
        self.params_type, self.resources_type = params_type, resources_type
        self.sandboxes = {}

    async def create(self, labels, resources, network_enabled=False):
        if self.params_type is None:
            from daytona import CreateSandboxFromImageParams, Resources
            self.params_type, self.resources_type = CreateSandboxFromImageParams, Resources
        domains = resources.get('allowed_domains') or []
        params = self.params_type(
            image=self.image, labels=labels,
            resources=self.resources_type(cpu=math.ceil(resources['cpu_cores']),
                memory=math.ceil(resources['memory_mb'] / 1024),
                disk=math.ceil(resources['disk_limit_mb'] / 1024)),
            network_block_all=not network_enabled and not domains,
            domain_allow_list=",".join(domains) if domains else None,
            auto_stop_interval=15, auto_delete_interval=0,
        )
        sandbox = await self.sdk.create(params, timeout=120)
        self.sandboxes[sandbox.id] = sandbox

        async def mkdir(path):
            await sandbox.fs.create_folder(path, '755')
        return SimpleNamespace(id=sandbox.id, mkdir=mkdir)

    async def restore_snapshot(self, handle, root, destination):
        sandbox = self.sandboxes[handle.id]
        prefix = root.rstrip('/') + '/'
        folders = {destination}
        for path in await self.storage.list_files(root):
            if not path.startswith(prefix):
                raise ValueError('Snapshot file escapes workspace prefix.')
            relative = path[len(prefix):]
            if '..' in relative.split('/') or relative.startswith('/'):
                raise ValueError('Snapshot file escapes sandbox.')
            target = posixpath.join(destination, relative)
            parent = posixpath.dirname(target)
            pending = []
            while parent not in folders:
                pending.append(parent)
                parent = posixpath.dirname(parent)
            for folder in reversed(pending):
                await sandbox.fs.create_folder(folder, '755')
                folders.add(folder)
            await sandbox.fs.upload_file(await self.storage.read_file(path), target)

    async def execute(self, sandbox_id, command, cwd, env, timeout):
        sandbox = self.sandboxes[sandbox_id]
        cwd = posixpath.normpath(posixpath.join('/workspace', cwd or ''))
        if cwd != '/workspace' and not cwd.startswith('/workspace/'):
            raise ValueError('Command working directory must stay inside /workspace.')
        started = monotonic()
        try:
            result = await asyncio.wait_for(
                sandbox.process.exec(command, cwd=cwd, env=env, timeout=timeout or 600),
                timeout=(timeout or 600) + 5,
            )
            return SimpleNamespace(exit_code=result.exit_code, stdout=result.result or '',
                stderr='', duration_ms=int((monotonic() - started) * 1000), timed_out=False)
        except TimeoutError:
            return SimpleNamespace(exit_code=-1, stdout='', stderr='Sandbox command timed out.',
                duration_ms=int((monotonic() - started) * 1000), timed_out=True)

    async def stream(self, sandbox_id, command, **kwargs):
        result = await self.execute(sandbox_id, command, **kwargs)
        for line in result.stdout.splitlines(keepends=True):
            yield line

    async def destroy(self, sandbox_id):
        sandbox = self.sandboxes.get(sandbox_id)
        if sandbox is not None:
            await self.sdk.delete(sandbox)
            self.sandboxes.pop(sandbox_id, None)

    async def close(self):
        try:
            for sandbox_id in list(self.sandboxes):
                await self.destroy(sandbox_id)
        finally:
            await self.sdk.close()
