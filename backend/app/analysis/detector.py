"""Deterministic framework, runtime, and technology detector."""

import json
from typing import List, Dict, Set, Any
from backend.app.analysis.types import DetectedTechnology, IndexedFile
from backend.app.storage.base import BaseStorageBackend


class TechnologyDetector:
    """
    Infers frameworks, libraries, and language stacks using manifest inspection
    and explicit configuration evidence with confidence scoring.
    """

    @classmethod
    async def detect_technologies(
        cls,
        indexed_files: List[IndexedFile],
        storage: BaseStorageBackend,
        canonical_prefix: str,
    ) -> List[DetectedTechnology]:
        """Inspect manifests and configuration files to build evidence-backed technology records."""
        path_set: Set[str] = {f.relative_path for f in indexed_files}
        technologies: List[DetectedTechnology] = []

        # Read manifest contents if present
        package_json_data = await cls._load_json(storage, canonical_prefix, path_set, "package.json")
        requirements_txt_str = await cls._load_text(storage, canonical_prefix, path_set, "requirements.txt")
        pyproject_toml_str = await cls._load_text(storage, canonical_prefix, path_set, "pyproject.toml")

        # ---------------------------------------------------------------------
        # JavaScript / TypeScript Ecosystem
        # ---------------------------------------------------------------------
        if "tsconfig.json" in path_set:
            technologies.append(
                DetectedTechnology(
                    name="TypeScript",
                    category="language",
                    confidence=1.0,
                    evidence=["tsconfig.json present in project root"],
                )
            )

        if package_json_data:
            all_deps = {
                **package_json_data.get("dependencies", {}),
                **package_json_data.get("devDependencies", {}),
            }

            # Next.js
            next_evidence: List[str] = []
            if "next" in all_deps:
                next_evidence.append(f"package.json dependency 'next' ({all_deps['next']})")
            for p in path_set:
                if p.startswith("next.config."):
                    next_evidence.append(f"Configuration file '{p}'")
            if next_evidence:
                technologies.append(
                    DetectedTechnology(
                        name="Next.js",
                        category="framework",
                        confidence=0.98 if len(next_evidence) > 1 else 0.90,
                        evidence=next_evidence,
                    )
                )

            # React
            if "react" in all_deps:
                technologies.append(
                    DetectedTechnology(
                        name="React",
                        category="framework",
                        confidence=0.99,
                        evidence=[f"package.json dependency 'react' ({all_deps['react']})"],
                    )
                )

            # Vite
            vite_evidence: List[str] = []
            if "vite" in all_deps:
                vite_evidence.append(f"package.json dependency 'vite' ({all_deps['vite']})")
            for p in path_set:
                if p.startswith("vite.config."):
                    vite_evidence.append(f"Configuration file '{p}'")
            if vite_evidence:
                technologies.append(
                    DetectedTechnology(
                        name="Vite",
                        category="build_tool",
                        confidence=0.95,
                        evidence=vite_evidence,
                    )
                )

            # Tailwind CSS
            tailwind_evidence: List[str] = []
            if "tailwindcss" in all_deps:
                tailwind_evidence.append(f"package.json dependency 'tailwindcss' ({all_deps['tailwindcss']})")
            for p in path_set:
                if p.startswith("tailwind.config."):
                    tailwind_evidence.append(f"Configuration file '{p}'")
            if tailwind_evidence:
                technologies.append(
                    DetectedTechnology(
                        name="Tailwind CSS",
                        category="framework",
                        confidence=0.98,
                        evidence=tailwind_evidence,
                    )
                )

            # Supabase
            if "@supabase/supabase-js" in all_deps:
                technologies.append(
                    DetectedTechnology(
                        name="Supabase",
                        category="library",
                        confidence=0.95,
                        evidence=[f"package.json dependency '@supabase/supabase-js' ({all_deps['@supabase/supabase-js']})"],
                    )
                )

        if "angular.json" in path_set:
            technologies.append(
                DetectedTechnology(
                    name="Angular",
                    category="framework",
                    confidence=0.99,
                    evidence=["angular.json present in project root"],
                )
            )

        # ---------------------------------------------------------------------
        # Python Ecosystem
        # ---------------------------------------------------------------------
        python_evidence: List[str] = []
        if any(f.extension in {".py", ".pyw"} for f in indexed_files):
            python_evidence.append("Python source files present")
        if "pyproject.toml" in path_set:
            python_evidence.append("pyproject.toml present")
        if "requirements.txt" in path_set:
            python_evidence.append("requirements.txt present")
        if "setup.py" in path_set:
            python_evidence.append("setup.py present")

        if python_evidence:
            technologies.append(
                DetectedTechnology(
                    name="Python",
                    category="language",
                    confidence=0.99,
                    evidence=python_evidence,
                )
            )

        # Python framework inspection
        py_all_text = (requirements_txt_str or "") + "\n" + (pyproject_toml_str or "")
        py_lower = py_all_text.lower()

        if "fastapi" in py_lower:
            technologies.append(
                DetectedTechnology(
                    name="FastAPI",
                    category="framework",
                    confidence=0.95,
                    evidence=["FastAPI declared in requirements.txt or pyproject.toml"],
                )
            )

        if "django" in py_lower or "manage.py" in path_set:
            dj_evidence: List[str] = []
            if "manage.py" in path_set:
                dj_evidence.append("manage.py entry point present")
            if "django" in py_lower:
                dj_evidence.append("Django declared in dependency manifest")
            technologies.append(
                DetectedTechnology(
                    name="Django",
                    category="framework",
                    confidence=0.95,
                    evidence=dj_evidence,
                )
            )

        if "flask" in py_lower:
            technologies.append(
                DetectedTechnology(
                    name="Flask",
                    category="framework",
                    confidence=0.90,
                    evidence=["Flask declared in dependency manifest"],
                )
            )

        # ---------------------------------------------------------------------
        # Java Ecosystem
        # ---------------------------------------------------------------------
        if "pom.xml" in path_set:
            technologies.append(
                DetectedTechnology(
                    name="Maven / Java",
                    category="build_tool",
                    confidence=0.98,
                    evidence=["pom.xml Maven configuration present"],
                )
            )

        if "build.gradle" in path_set or "build.gradle.kts" in path_set:
            technologies.append(
                DetectedTechnology(
                    name="Gradle / Java",
                    category="build_tool",
                    confidence=0.98,
                    evidence=["build.gradle configuration present"],
                )
            )

        return technologies

    @classmethod
    async def _load_json(
        cls, storage: BaseStorageBackend, prefix: str, paths: Set[str], filename: str
    ) -> Dict[str, Any] | None:
        if filename not in paths:
            return None
        try:
            content = await storage.read_file(f"{prefix}/{filename}")
            return json.loads(content.decode("utf-8"))
        except Exception:
            return None

    @classmethod
    async def _load_text(
        cls, storage: BaseStorageBackend, prefix: str, paths: Set[str], filename: str
    ) -> str | None:
        if filename not in paths:
            return None
        try:
            content = await storage.read_file(f"{prefix}/{filename}")
            return content.decode("utf-8")
        except Exception:
            return None
