"""Deterministic file indexer and language detector.

Extracts file metadata, classifies binary vs text, counts lines, and enforces
configurable ignore policies against build artifacts and caches.
"""

import os
import hashlib
from typing import List, Set, Dict, Tuple
from pathlib import Path
from backend.app.storage.base import BaseStorageBackend
from backend.app.analysis.types import IndexedFile

# Default ignored directories configurable via caller
DEFAULT_IGNORED_DIRS: Set[str] = {
    "node_modules",
    ".next",
    "dist",
    "build",
    "out",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "target",
    ".idea",
    ".vscode",
    ".turbo",
    ".cache",
    ".pytest_cache",
    "coverage",
}

# Known file extension to language mapping
EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".py": "Python",
    ".pyw": "Python",
    ".java": "Java",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".json": "JSON",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
}

BINARY_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".bin", ".dll", ".so", ".dylib", ".class",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".pyd",
}


def is_test_path(relative_path: str) -> bool:
    """Classify whether a file path represents a test suite."""
    p_lower = relative_path.lower()
    return (
        "/test/" in p_lower
        or "/tests/" in p_lower
        or "/__tests__/" in p_lower
        or p_lower.endswith("_test.py")
        or p_lower.endswith(".test.ts")
        or p_lower.endswith(".test.tsx")
        or p_lower.endswith(".test.js")
        or p_lower.endswith(".test.jsx")
        or p_lower.endswith(".spec.ts")
        or p_lower.endswith(".spec.tsx")
        or p_lower.endswith(".spec.js")
        or p_lower.endswith("test.java")
    )


class FileIndexer:
    """Scans and indexes files within an approved workspace storage directory."""

    def __init__(self, ignored_dirs: Set[str] | None = None):
        self.ignored_dirs = set(ignored_dirs or DEFAULT_IGNORED_DIRS)

    def should_ignore_path(self, relative_path: str) -> bool:
        """Check if any directory segment in relative_path matches ignored policies."""
        parts = Path(relative_path.replace("\\", "/")).parts
        for part in parts[:-1]:  # check directory segments only
            if part in self.ignored_dirs:
                return True
        return False

    def detect_language(self, extension: str) -> str:
        """Map file extension to language; returns UNKNOWN if unrecognized."""
        return EXTENSION_LANGUAGE_MAP.get(extension.lower(), "UNKNOWN")

    async def index_workspace(
        self, storage: BaseStorageBackend, canonical_prefix: str
    ) -> List[IndexedFile]:
        """
        Index all valid project files in storage under canonical_prefix.
        Returns sorted list of IndexedFile records.
        """
        all_raw_paths = await storage.list_files(canonical_prefix)
        prefix_len = len(canonical_prefix.rstrip("/\\")) + 1

        indexed: List[IndexedFile] = []

        for full_p in all_raw_paths:
            rel_p = full_p[prefix_len:] if full_p.startswith(canonical_prefix) else full_p
            rel_p = rel_p.replace("\\", "/").lstrip("/")

            if not rel_p or self.should_ignore_path(rel_p):
                continue

            # Read file to calculate line count and sha256
            try:
                content = await storage.read_file(full_p)
            except Exception:
                continue

            size_bytes = len(content)
            sha256 = hashlib.sha256(content).hexdigest()

            _, ext = os.path.splitext(rel_p)
            ext_lower = ext.lower()

            # Classify binary vs text
            is_bin = ext_lower in BINARY_EXTENSIONS or b"\x00" in content[:1024]
            language = self.detect_language(ext_lower)

            line_count = 0
            if not is_bin:
                try:
                    text_str = content.decode("utf-8")
                    line_count = len(text_str.splitlines())
                except UnicodeDecodeError:
                    is_bin = True

            indexed.append(
                IndexedFile(
                    relative_path=rel_p,
                    extension=ext_lower,
                    language=language,
                    size_bytes=size_bytes,
                    line_count=line_count,
                    sha256_hash=sha256,
                    is_binary=is_bin,
                    is_test_file=is_test_path(rel_p),
                )
            )

        indexed.sort(key=lambda f: f.relative_path)
        return indexed
