"""Static dependency manifest parser for JavaScript, TypeScript, and Python."""

import re
import json
from typing import List, Set
from backend.app.analysis.types import ProjectDependency, IndexedFile
from backend.app.storage.base import BaseStorageBackend


class DependencyParser:
    """Parses project manifests without executing code or resolving remote repositories."""

    @classmethod
    async def extract_dependencies(
        cls,
        indexed_files: List[IndexedFile],
        storage: BaseStorageBackend,
        canonical_prefix: str,
    ) -> List[ProjectDependency]:
        """Inspect manifests present in indexed files and extract typed dependencies."""
        path_set: Set[str] = {f.relative_path for f in indexed_files}
        deps: List[ProjectDependency] = []

        # 1. Parse package.json files
        for p in path_set:
            if p == "package.json" or p.endswith("/package.json"):
                pkg_deps = await cls._parse_package_json(storage, f"{canonical_prefix}/{p}", p)
                deps.extend(pkg_deps)

        # 2. Parse requirements.txt files
        for p in path_set:
            if p == "requirements.txt" or p.endswith("/requirements.txt"):
                req_deps = await cls._parse_requirements_txt(storage, f"{canonical_prefix}/{p}", p)
                deps.extend(req_deps)

        # 3. Parse pyproject.toml
        if "pyproject.toml" in path_set:
            toml_deps = await cls._parse_pyproject_toml(storage, f"{canonical_prefix}/pyproject.toml", "pyproject.toml")
            deps.extend(toml_deps)

        return deps

    @classmethod
    async def _parse_package_json(
        cls, storage: BaseStorageBackend, full_path: str, rel_path: str
    ) -> List[ProjectDependency]:
        try:
            raw = await storage.read_file(full_path)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return []

        results: List[ProjectDependency] = []

        prod = data.get("dependencies", {})
        if isinstance(prod, dict):
            for name, ver in prod.items():
                results.append(
                    ProjectDependency(
                        name=str(name),
                        version_spec=str(ver),
                        dependency_type="production",
                        manifest_source=rel_path,
                    )
                )

        dev = data.get("devDependencies", {})
        if isinstance(dev, dict):
            for name, ver in dev.items():
                results.append(
                    ProjectDependency(
                        name=str(name),
                        version_spec=str(ver),
                        dependency_type="development",
                        manifest_source=rel_path,
                    )
                )

        return results

    @classmethod
    async def _parse_requirements_txt(
        cls, storage: BaseStorageBackend, full_path: str, rel_path: str
    ) -> List[ProjectDependency]:
        try:
            raw = await storage.read_file(full_path)
            lines = raw.decode("utf-8").splitlines()
        except Exception:
            return []

        DEV_PACKAGES = {
            "pytest", "pytest-asyncio", "pytest-cov", "pytest-mock",
            "mypy", "black", "flake8", "ruff", "pylint", "tox",
            "coverage", "isort", "autopep8", "pre-commit",
        }

        results: List[ProjectDependency] = []
        is_dev_file = "dev" in rel_path.lower() or "test" in rel_path.lower()

        for line in lines:
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#") or cleaned.startswith("-"):
                continue

            # Match package name and optional specifier (e.g. fastapi>=0.100.0, flask==2.0)
            match = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*([~=><!^].*)?$", cleaned)
            if match:
                pkg_name = match.group(1)
                ver_spec = match.group(2).strip() if match.group(2) else None
                dep_type = "development" if (is_dev_file or pkg_name.lower() in DEV_PACKAGES) else "production"
                results.append(
                    ProjectDependency(
                        name=pkg_name,
                        version_spec=ver_spec,
                        dependency_type=dep_type,
                        manifest_source=rel_path,
                    )
                )

        return results

    @classmethod
    async def _parse_pyproject_toml(
        cls, storage: BaseStorageBackend, full_path: str, rel_path: str
    ) -> List[ProjectDependency]:
        try:
            raw = await storage.read_file(full_path)
            text = raw.decode("utf-8")
        except Exception:
            return []

        results: List[ProjectDependency] = []
        current_section = ""

        for line in text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            if line_str.startswith("[") and line_str.endswith("]"):
                current_section = line_str.strip("[]")
                continue

            # Standard PEP 621 dependencies or Poetry dependencies
            if "dependencies" in current_section:
                is_dev = "dev" in current_section or "group.dev" in current_section
                # Poetry format: fastapi = "^0.100.0"
                eq_match = re.match(r'^([a-zA-Z0-9_\-\.]+)\s*=\s*["\']([^"\']+)["\']', line_str)
                if eq_match:
                    results.append(
                        ProjectDependency(
                            name=eq_match.group(1),
                            version_spec=eq_match.group(2),
                            dependency_type="development" if is_dev else "production",
                            manifest_source=rel_path,
                        )
                    )
                else:
                    # PEP 621 format: "fastapi>=0.100.0",
                    pep_match = re.match(r'^["\']([a-zA-Z0-9_\-\.]+)\s*([~=><!^][^"\']*)?["\']', line_str)
                    if pep_match:
                        results.append(
                            ProjectDependency(
                                name=pep_match.group(1),
                                version_spec=pep_match.group(2).strip() if pep_match.group(2) else None,
                                dependency_type="development" if is_dev else "production",
                                manifest_source=rel_path,
                            )
                        )

        return results
