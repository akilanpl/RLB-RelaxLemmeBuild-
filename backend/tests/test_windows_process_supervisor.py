"""Native Windows containment, including descendants that outlive their parent."""
import asyncio
import os
import subprocess
import sys

import pytest

from backend.app.sandbox.windows_process import SUPERVISOR_CODE, supervised_argv


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object integration")
@pytest.mark.parametrize("cancel", [False, True])
async def test_supervisor_closes_job_and_terminates_descendants(tmp_path, cancel):
    ready = tmp_path / "ready"
    escaped = tmp_path / "escaped"
    child = ("import pathlib,time; "
             f"pathlib.Path({str(ready)!r}).write_text('ready'); "
             "time.sleep(1); "
             f"pathlib.Path({str(escaped)!r}).write_text('escaped')")
    parent = ("import subprocess,sys,time,pathlib; "
              f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
              f"ready=pathlib.Path({str(ready)!r}); "
              "\nwhile not ready.exists(): time.sleep(0.01)\n" +
              ("time.sleep(60)" if cancel else "print('finished', flush=True)"))
    process = await asyncio.create_subprocess_exec(
        *supervised_argv(sys.executable, [sys.executable, "-c", parent]),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        async def wait_ready():
            while not ready.exists():
                if process.returncode is not None:
                    raise AssertionError("Supervisor exited before child startup")
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_ready(), timeout=5)
        if cancel:
            process.kill()
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2)
        if not cancel:
            assert process.returncode == 0, stderr.decode(errors="replace")
            assert stdout.strip() == b"finished"
        await asyncio.sleep(1.1)
        assert not escaped.exists(), "Descendant escaped Job termination"
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=2)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object integration")
async def test_runtime_parent_death_terminates_supervised_command(tmp_path):
    ready = tmp_path / "ready"
    escaped = tmp_path / "escaped"
    command = ("import pathlib,time; "
               f"pathlib.Path({str(ready)!r}).write_text('ready'); "
               "time.sleep(1); "
               f"pathlib.Path({str(escaped)!r}).write_text('escaped')")
    runtime = ("import os,subprocess,sys,time; "
               f"subprocess.Popen([sys.executable,'-c',{SUPERVISOR_CODE!r},"
               f"str(os.getpid()),'exec',sys.executable,'-c',{command!r}]); "
               "time.sleep(60)")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", runtime,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        async def wait_ready():
            while not ready.exists():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(wait_ready(), timeout=5)
        process.kill()
        await asyncio.wait_for(process.communicate(), timeout=2)
        await asyncio.sleep(1.1)
        assert not escaped.exists(), "Project command outlived its runtime"
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=2)
