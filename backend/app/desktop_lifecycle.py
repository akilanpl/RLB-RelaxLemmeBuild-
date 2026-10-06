"""Lifecycle controls owned by the packaged Electron parent, not cloud commands."""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import HTTPException


def parent_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    # os.kill(pid, 0) is not a safe existence probe on Windows.
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return ctypes.get_last_error() == 5  # access denied is not process death
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        kernel.CloseHandle(handle)


def install_desktop_lifecycle(app, server):
    existing = app.router.lifespan_context

    async def watch_parent():
        pid = int(os.environ.get("RLB_PARENT_PID", "0"))
        while pid:
            if not parent_alive(pid):
                server.should_exit = True
                return
            await asyncio.sleep(0.5)

    @asynccontextmanager
    async def lifespan(application):
        async with existing(application):
            watcher = asyncio.create_task(watch_parent())
            try:
                yield
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

    app.router.lifespan_context = lifespan

    @app.get("/api/v1/desktop/status", include_in_schema=False)
    async def status():
        worker = getattr(app.state, "worker_task", None)
        if worker is None or worker.done():
            raise HTTPException(status_code=503, detail="Local worker is unavailable.")
        return {"instance_id": os.environ.get("RLB_RUNTIME_INSTANCE_ID", ""), "worker_ready": True}

    @app.post("/api/v1/desktop/shutdown", include_in_schema=False)
    async def shutdown():
        server.should_exit = True
        return {"stopping": True}
