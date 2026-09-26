"""Deterministic project summary and architectural overview generator."""

import os
from typing import List, Dict, Set
from backend.app.analysis.types import (
    ProjectSummary,
    IndexedFile,
    DetectedTechnology,
    ProjectDependency,
    EntryPoint,
)
from backend.app.analysis.sanitizer import redact_secrets


class SummaryGenerator:
    """Produces structured project summaries without requiring an LLM."""

    @classmethod
    def generate_summary(
        cls,
        indexed_files: List[IndexedFile],
        technologies: List[DetectedTechnology],
        dependencies: List[ProjectDependency],
        entry_points: List[EntryPoint],
    ) -> ProjectSummary:
        """Synthesizes index, framework, and dependency data into a structured summary."""
        total_files = len(indexed_files)
        total_size = sum(f.size_bytes for f in indexed_files)
        total_lines = sum(f.line_count for f in indexed_files)

        # Count language distribution
        lang_counts: Dict[str, int] = {}
        for f in indexed_files:
            lang_counts[f.language] = lang_counts.get(f.language, 0) + 1

        sorted_languages = sorted(
            [l for l in lang_counts.keys() if l != "UNKNOWN"],
            key=lambda l: lang_counts[l],
            reverse=True,
        )

        framework_names = [t.name for t in technologies if t.category in {"framework", "build_tool"}]

        # Top-level directories
        top_dirs: Set[str] = set()
        config_files: List[str] = []

        for f in indexed_files:
            parts = f.relative_path.split("/")
            if len(parts) > 1:
                top_dirs.add(parts[0])
            elif f.extension in {".json", ".toml", ".yml", ".yaml", ".config.js", ".config.ts"}:
                config_files.append(f.relative_path)

        dep_counts: Dict[str, int] = {
            "total": len(dependencies),
            "production": len([d for d in dependencies if d.dependency_type == "production"]),
            "development": len([d for d in dependencies if d.dependency_type == "development"]),
        }

        # Warnings & unsupported areas
        warnings: List[str] = []
        unsupported: List[str] = []

        unknown_count = lang_counts.get("UNKNOWN", 0)
        if unknown_count > 0:
            unsupported.append(f"{unknown_count} files with unrecognized extensions classified as UNKNOWN")

        if total_files == 0:
            warnings.append("Workspace contains no indexed project files.")
        elif not entry_points:
            warnings.append("No standard application entry point could be reliably detected.")

        # Build architecture overview prose deterministically
        arch_lines = [
            f"Project contains {total_files} files ({total_lines} lines of code, {round(total_size / 1024, 1)} KB).",
            f"Primary languages: {', '.join(sorted_languages[:3]) if sorted_languages else 'None detected'}.",
            f"Frameworks & tools: {', '.join(framework_names) if framework_names else 'Generic structure'}.",
            f"Dependencies tracked: {len(dependencies)} across manifests.",
            f"Likely entry points: {', '.join([e.path for e in entry_points]) if entry_points else 'None detected'}.",
        ]
        architecture_overview = redact_secrets("\n".join(arch_lines))

        return ProjectSummary(
            total_files=total_files,
            total_size_bytes=total_size,
            total_lines=total_lines,
            primary_languages=sorted_languages,
            frameworks=framework_names,
            dependency_counts=dep_counts,
            likely_entry_points=[e.path for e in entry_points],
            top_level_directories=sorted(list(top_dirs)),
            config_files=sorted(config_files),
            warnings=warnings,
            unsupported_areas=unsupported,
            architecture_overview=architecture_overview,
        )
