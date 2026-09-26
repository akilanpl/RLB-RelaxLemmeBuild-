"""Static Dependency Graph Builder."""

import os
from typing import List, Dict, Set
from backend.app.analysis.types import (
    DependencyGraph,
    DependencyGraphNode,
    DependencyGraphEdge,
    FileSymbols,
    IndexedFile,
)


class DependencyGraphBuilder:
    """Builds static import and dependency relationships across workspace files."""

    @classmethod
    def build_graph(
        cls,
        indexed_files: List[IndexedFile],
        file_symbols: List[FileSymbols],
    ) -> DependencyGraph:
        """Construct graph nodes and directed edges between files and packages."""
        known_files: Set[str] = {f.relative_path for f in indexed_files}
        nodes_dict: Dict[str, DependencyGraphNode] = {}
        edges: List[DependencyGraphEdge] = []

        # Add file nodes
        for f in indexed_files:
            nodes_dict[f.relative_path] = DependencyGraphNode(
                id=f.relative_path,
                node_type="file",
            )

        # Process imports from each file's symbol analysis
        for fs in file_symbols:
            source_file = fs.relative_path
            src_dir = os.path.dirname(source_file)

            for import_target in fs.imports:
                resolved_target = cls._resolve_internal_import(src_dir, import_target, known_files)

                if resolved_target:
                    # Internal file dependency
                    edges.append(
                        DependencyGraphEdge(
                            source=source_file,
                            target=resolved_target,
                            edge_type="internal_import",
                        )
                    )
                else:
                    # External package dependency
                    pkg_name = import_target.split("/")[0] if not import_target.startswith("@") else "/".join(import_target.split("/")[:2])
                    if pkg_name not in nodes_dict:
                        nodes_dict[pkg_name] = DependencyGraphNode(
                            id=pkg_name,
                            node_type="package",
                        )
                    edges.append(
                        DependencyGraphEdge(
                            source=source_file,
                            target=pkg_name,
                            edge_type="external_dependency",
                        )
                    )

        # Deduplicate edges
        unique_edges: List[DependencyGraphEdge] = []
        seen_edges: Set[tuple] = set()
        for edge in edges:
            edge_key = (edge.source, edge.target, edge.edge_type)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                unique_edges.append(edge)

        return DependencyGraph(
            nodes=list(nodes_dict.values()),
            edges=unique_edges,
        )

    @classmethod
    def _resolve_internal_import(
        cls, src_dir: str, import_str: str, known_files: Set[str]
    ) -> str | None:
        """Attempt to resolve a relative import path to a known internal file."""
        if not (import_str.startswith("./") or import_str.startswith("../")):
            # Check if it directly matches a known file path (e.g. backend/app/main)
            for ext in ["", ".ts", ".tsx", ".js", ".jsx", ".py"]:
                candidate = f"{import_str}{ext}"
                if candidate in known_files:
                    return candidate
            return None

        # Resolve relative path against src_dir
        base = os.path.normpath(os.path.join(src_dir, import_str)).replace("\\", "/")

        # Try various standard extensions
        candidates = [
            base,
            f"{base}.ts",
            f"{base}.tsx",
            f"{base}.js",
            f"{base}.jsx",
            f"{base}.py",
            f"{base}/index.ts",
            f"{base}/index.tsx",
            f"{base}/index.js",
        ]

        for cand in candidates:
            if cand in known_files:
                return cand

        return None
