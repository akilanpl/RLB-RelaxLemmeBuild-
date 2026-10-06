"""Include project interpreters in the Windows package, without global installs."""
import hashlib
import json
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bundle_windows_toolchains():
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Windows x64 toolchains must be assembled with Windows x64 Python.")
    target = ROOT / "dist" / "toolchains"
    if target.exists():
        shutil.rmtree(target)
    python = target / "python"
    python.mkdir(parents=True)
    source = Path(sys.base_prefix)
    for file in [*source.glob("python*.exe"), *source.glob("python*.dll"), *source.glob("vcruntime*.dll"), source / "LICENSE.txt"]:
        if file.is_file():
            shutil.copy2(file, python / file.name)
    for folder in ("DLLs", "Lib"):
        shutil.copytree(source / folder, python / folder,
                        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests"))
    if not (python / "python.exe").is_file() or not (python / "Lib" / "ensurepip" / "_bundled").is_dir():
        raise RuntimeError("A complete CPython install with ensurepip is required to build the installer.")
    config = json.loads((ROOT / "desktop" / "toolchains.json").read_text())
    name = f'node-v{config["nodeVersion"]}-win-x64.zip'
    cache = ROOT / "build" / "toolchain-cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    expected = config["nodeWindowsX64Sha256"]
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        temporary = archive.with_suffix(".download")
        try:
            with urllib.request.urlopen(f'https://nodejs.org/download/release/v{config["nodeVersion"]}/{name}', timeout=60) as response:
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
                raise RuntimeError("Official Node archive checksum mismatch; refusing to package it.")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(archive) as package:
        prefix = name.removesuffix(".zip") + "/"
        for entry in package.infolist():
            if not entry.filename.startswith(prefix):
                raise RuntimeError("Unexpected Node archive layout.")
            relative = entry.filename[len(prefix):]
            if not relative or entry.is_dir():
                continue
            destination = target / "node" / relative
            if not destination.resolve().is_relative_to((target / "node").resolve()):
                raise RuntimeError("Node archive path escapes the tooling root.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with package.open(entry) as content, destination.open("wb") as output:
                shutil.copyfileobj(content, output)
    for file in ("node.exe", "npm.cmd", "node_modules/npm/bin/npm-cli.js", "LICENSE"):
        if not (target / "node" / file).is_file():
            raise RuntimeError(f"Bundled Node asset missing: {file}")
    print("Bundled private Windows Python and Node/npm project toolchains.")


if __name__ == "__main__":
    bundle_windows_toolchains()
