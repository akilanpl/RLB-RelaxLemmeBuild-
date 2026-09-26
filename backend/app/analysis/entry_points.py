"""Static application entry point detector based on framework conventions."""

from typing import List, Set
from backend.app.analysis.types import EntryPoint, IndexedFile
from backend.app.storage.base import BaseStorageBackend


class EntryPointDetector:
    """Detects likely entry points by inspecting file paths and static declarations."""

    @classmethod
    async def detect_entry_points(
        cls,
        indexed_files: List[IndexedFile],
        storage: BaseStorageBackend,
        canonical_prefix: str,
    ) -> List[EntryPoint]:
        path_set: Set[str] = {f.relative_path for f in indexed_files}
        entry_points: List[EntryPoint] = []

        # ---------------------------------------------------------------------
        # Next.js Entry Points
        # ---------------------------------------------------------------------
        next_app_candidates = [
            "src/app/page.tsx", "src/app/page.jsx", "src/app/page.js",
            "app/page.tsx", "app/page.jsx", "app/page.js",
            "src/app/layout.tsx", "app/layout.tsx",
        ]
        for candidate in next_app_candidates:
            if candidate in path_set:
                entry_points.append(
                    EntryPoint(
                        path=candidate,
                        entry_type="nextjs_app_router",
                        confidence=0.98,
                        evidence=[f"Next.js App Router root '{candidate}' detected"],
                    )
                )

        next_pages_candidates = [
            "src/pages/index.tsx", "src/pages/index.jsx", "src/pages/index.js",
            "pages/index.tsx", "pages/index.jsx", "pages/index.js",
        ]
        for candidate in next_pages_candidates:
            if candidate in path_set:
                entry_points.append(
                    EntryPoint(
                        path=candidate,
                        entry_type="nextjs_pages_router",
                        confidence=0.95,
                        evidence=[f"Next.js Pages Router index '{candidate}' detected"],
                    )
                )

        # ---------------------------------------------------------------------
        # Python Entry Points
        # ---------------------------------------------------------------------
        python_candidates = [
            "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
            "src/main.py", "src/app.py", "backend/app/main.py",
        ]
        for candidate in python_candidates:
            if candidate in path_set:
                # Read start of file to check for FastAPI/Flask declarations or __main__
                evidence: List[str] = [f"Standard Python entry point name '{candidate}'"]
                confidence = 0.90

                try:
                    content = await storage.read_file(f"{canonical_prefix}/{candidate}")
                    text = content.decode("utf-8", errors="ignore")
                    if "__main__" in text:
                        evidence.append("Contains '__name__ == \"__main__\"' guard")
                        confidence = 0.98
                    if "FastAPI(" in text:
                        evidence.append("Instantiates FastAPI application instance")
                        confidence = 0.99
                    if "Flask(" in text:
                        evidence.append("Instantiates Flask application instance")
                        confidence = 0.99
                except Exception:
                    pass

                entry_points.append(
                    EntryPoint(
                        path=candidate,
                        entry_type="python_module",
                        confidence=confidence,
                        evidence=evidence,
                    )
                )

        # ---------------------------------------------------------------------
        # Web Root Entry Points
        # ---------------------------------------------------------------------
        if "index.html" in path_set:
            entry_points.append(
                EntryPoint(
                    path="index.html",
                    entry_type="web_root",
                    confidence=0.95,
                    evidence=["HTML root entry document index.html present"],
                )
            )

        return entry_points
