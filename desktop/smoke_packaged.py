"""Exercise real packaged assets; uses no app test mode or live provider secrets.

Run after build:all. --resources validates an Electron package's resources folder.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.sandbox.windows_process import supervised_argv


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(base, path, method="GET", body=None, token=True):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-RLB-Local-Token"] = "smoke-local-token"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers, method=method), timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def wait_runtime(base, process):
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Frozen runtime exited before readiness.")
        try:
            status, result = request(base, "/api/v1/desktop/status")
            if status == 200 and result == {"instance_id": "smoke-instance", "worker_ready": True}:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Frozen runtime readiness timed out.")


def verify(resources=None):
    if resources:
        resources = Path(resources).resolve()
        backend = resources / "backend"
        frontend = resources / "frontend" / "standalone"
        wrapper = resources / "frontend-entry.js"
        electron = resources.parent / "RLB.exe" if sys.platform == "win32" else resources.parent / "MacOS" / "RLB"
        static = frontend / ".next" / "static"
    else:
        backend = ROOT / "dist" / "rlb-runtime"
        frontend = ROOT / "frontend" / ".next" / "standalone"
        wrapper = ROOT / "desktop" / "frontend-entry.js"
        electron = ROOT / "desktop" / "node_modules" / "electron" / "dist" / ("electron.exe" if sys.platform == "win32" else "Electron.app/Contents/MacOS/Electron")
        static = ROOT / "frontend" / ".next" / "static"
        shutil.copytree(static, frontend / ".next" / "static", dirs_exist_ok=True)
        shutil.copytree(ROOT / "frontend" / "public", frontend / "public", dirs_exist_ok=True)
    binary = backend / ("rlb-runtime.exe" if sys.platform == "win32" else "rlb-runtime")
    if any(frontend.rglob(".env*")):
        raise RuntimeError("Development environment files were included in the release.")
    with tempfile.TemporaryDirectory(prefix="rlb-package-smoke-") as temporary:
        directory = Path(temporary)
        project = directory / "project"
        project.mkdir()
        (project / "app.py").write_text("answer = 1\n")
        base = f"http://127.0.0.1:{free_port()}"
        env = {key: value for key, value in os.environ.items() if key in {"PATH", "HOME", "SystemRoot", "SYSTEMROOT", "COMSPEC", "WINDIR", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG"}}
        env.update(ENVIRONMENT="desktop", PORT=base.rsplit(":", 1)[1], LOCAL_DATA_DIR=str(directory / "data"),
                   RLB_ENV_FILE="", RLB_LOCAL_API_TOKEN="smoke-local-token", RLB_RUNTIME_INSTANCE_ID="smoke-instance",
                   RLB_PARENT_PID=str(os.getpid()), RLB_LOCAL_OWNER_ID=str(uuid4()), DEBUG="false",
                   CREDENTIAL_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"s" * 32).decode())
        for attempt in range(2):
            with (directory / "sidecar.log").open("a+") as log:
                process = subprocess.Popen([str(binary)], cwd=directory, env=env, stdout=log, stderr=log)
                try:
                    wait_runtime(base, process)
                    assert request(base, "/api/v1/workspaces", token=False)[0] == 401
                    assert request(base, "/api/v1/desktop/shutdown", "POST", token=False)[0] == 401
                    if attempt == 0:
                        status, workspace = request(base, "/api/v1/workspaces/local", "POST", {"name": "Real smoke project", "path": str(project)})
                        assert status == 201, (status, workspace)
                        status, credential = request(base, "/api/v1/providers/credentials", "PUT", {"provider_name": "Groq", "api_key": "dummy-smoke-key"})
                        assert status == 200, (status, credential)
                        status, worker = request(base, "/api/v1/providers/workers", "PUT", {"provider_id": "groq", "model_name": "configured-model"})
                        assert status == 200, (status, worker)
                    else:
                        assert request(base, "/api/v1/workspaces")[1][0]["id"] == workspace["id"]
                        assert request(base, "/api/v1/providers/workers")[1][0]["id"] == worker["id"]
                        assert request(base, "/api/v1/providers/credentials")[1][0]["id"] == credential["id"]
                    assert b"dummy-smoke-key" not in (directory / "data" / "rlb.sqlite3").read_bytes()
                    assert (project / "app.py").read_text() == "answer = 1\n"
                    assert request(base, "/api/v1/desktop/shutdown", "POST")[0] == 200
                    assert process.wait(timeout=15) == 0
                except BaseException:
                    log.seek(0)
                    print(log.read(), file=sys.stderr)
                    raise
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
        # A killed Electron parent must not leave an independent runtime behind.
        orphan_log = directory / "parent-loss.log"
        launcher = """import json,os,subprocess,sys,time,urllib.request
with open(sys.argv[2], 'w') as log:
    env = dict(os.environ, RLB_PARENT_PID=str(os.getpid()))
    child = subprocess.Popen([sys.argv[1]], env=env, stdout=log, stderr=log)
    for _ in range(120):
        if child.poll() is not None: raise RuntimeError('runtime exited before parent-loss test')
        try:
            req = urllib.request.Request(sys.argv[3]+'/api/v1/desktop/status', headers={'X-RLB-Local-Token':'smoke-local-token'})
            with urllib.request.urlopen(req, timeout=1) as response:
                if response.status == 200: break
        except OSError: time.sleep(.25)
    else: raise RuntimeError('parent-loss test readiness timed out')
"""
        subprocess.run([sys.executable, "-c", launcher, str(binary), str(orphan_log), base],
                       cwd=directory, env=env, check=True, timeout=45)
        for _ in range(80):
            if "Finished server process" in orphan_log.read_text():
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Runtime did not shut down after its parent exited.")
        frontend_base = f"http://127.0.0.1:{free_port()}"
        env.update(PORT=frontend_base.rsplit(":", 1)[1], HOSTNAME="127.0.0.1", ELECTRON_RUN_AS_NODE="1", RLB_DESKTOP_FRONTEND_TOKEN="smoke-nonce")
        with (directory / "frontend.log").open("w+") as log:
            process = subprocess.Popen([str(electron), str(wrapper), str(frontend / "server.js")], cwd=frontend, env=env, stdout=log, stderr=log)
            try:
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError("Packaged frontend exited before readiness.")
                    try:
                        req = urllib.request.Request(frontend_base + "/api/desktop-ready", headers={"X-RLB-Desktop-Nonce": "smoke-nonce"})
                        with urllib.request.urlopen(req, timeout=2) as response:
                            assert response.status == 200
                            break
                    except OSError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Packaged frontend readiness timed out.")
                try:
                    urllib.request.urlopen(frontend_base + "/api/desktop-ready", timeout=2)
                    raise AssertionError("Missing readiness nonce was accepted.")
                except urllib.error.HTTPError as error:
                    assert error.code == 404
                with urllib.request.urlopen(frontend_base + "/device-setup", timeout=3) as response:
                    assert b"Pair this device" in response.read()
                for asset in ("/monaco/vs/loader.js", "/monaco/vs/editor/editor.main.js", "/monaco/vs/editor/editor.worker.js"):
                    with urllib.request.urlopen(frontend_base + asset, timeout=3) as response:
                        assert response.status == 200
                file = next(static.rglob("*.js"))
                with urllib.request.urlopen(frontend_base + "/_next/static/" + file.relative_to(static).as_posix(), timeout=3) as response:
                    assert response.status == 200
            except BaseException:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                process.terminate()
                process.wait(timeout=10)
        if sys.platform == "win32":
            tooling = Path(resources) / "toolchains" if resources else ROOT / "dist" / "toolchains"
            python = tooling / "python" / "python.exe"
            # No global interpreter or npm lookup is allowed in this check.
            clean_env = {key: value for key, value in env.items() if key in {"SystemRoot", "SYSTEMROOT", "COMSPEC", "WINDIR", "PATHEXT", "TEMP", "TMP"}}
            tool_home = directory / "tool-home"
            tool_home.mkdir()
            clean_env.update(HOME=str(tool_home), USERPROFILE=str(tool_home))
            clean_env["PATH"] = str(tooling / "node")
            setup = [str(python), "-m", "venv", str(directory / "venv")]
            subprocess.run(supervised_argv(str(python), setup), env=clean_env, check=True, timeout=60)
            subprocess.run([str(directory / "venv" / "Scripts" / "python.exe"), "-m", "pip", "--version"], env=clean_env, check=True)
            subprocess.run([str(tooling / "node" / "node.exe"), "--version"], env=clean_env, check=True)
            subprocess.run([str(tooling / "node" / "node.exe"), str(tooling / "node" / "node_modules" / "npm" / "bin" / "npm-cli.js"), "--version"], env=clean_env, check=True)
    print("PASS: packaged sidecar auth/readiness/shutdown/parent-loss cleanup, real registration, encrypted provider/project restart persistence, packaged frontend/nonce/static assets" + (", private Python/Node toolchains" if sys.platform == "win32" else " (macOS; not Windows validation)"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources")
    verify(parser.parse_args().resources)
