"""Static symbol and structure extraction service."""

import ast
import re
from typing import List, Optional
from backend.app.analysis.types import SymbolInfo, FileSymbols, IndexedFile
from backend.app.storage.base import BaseStorageBackend


class SymbolExtractor:
    """
    Statically analyzes source code to extract high-level symbols (classes, functions,
    interfaces, types) without executing code or running a heavy compiler.
    """

    @classmethod
    async def extract_file_symbols(
        cls, file_info: IndexedFile, storage: BaseStorageBackend, canonical_prefix: str
    ) -> FileSymbols:
        """Extract symbols for a single file according to its detected language."""
        if file_info.is_binary or file_info.language == "UNKNOWN":
            return FileSymbols(relative_path=file_info.relative_path, symbols_available=False)

        try:
            raw_bytes = await storage.read_file(f"{canonical_prefix}/{file_info.relative_path}")
            source_code = raw_bytes.decode("utf-8")
        except Exception:
            return FileSymbols(relative_path=file_info.relative_path, symbols_available=False)

        if file_info.language == "Python":
            return cls._extract_python_symbols(file_info.relative_path, source_code)
        elif file_info.language in {"TypeScript", "JavaScript"}:
            return cls._extract_js_ts_symbols(file_info.relative_path, source_code)

        return FileSymbols(relative_path=file_info.relative_path, symbols_available=False)

    @classmethod
    def _extract_python_symbols(cls, relative_path: str, code: str) -> FileSymbols:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return FileSymbols(relative_path=relative_path, symbols_available=False)

        symbols: List[SymbolInfo] = []
        imports: List[str] = []
        exports: List[str] = []

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="function",
                        line_number=node.lineno,
                        is_exported=not node.name.startswith("_"),
                    )
                )
                if not node.name.startswith("_"):
                    exports.append(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    SymbolInfo(
                        name=node.name,
                        kind="class",
                        line_number=node.lineno,
                        is_exported=not node.name.startswith("_"),
                    )
                )
                if not node.name.startswith("_"):
                    exports.append(node.name)
                # Inspect methods within class
                for subnode in node.body:
                    if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            SymbolInfo(
                                name=subnode.name,
                                kind="function",
                                line_number=subnode.lineno,
                                is_exported=not subnode.name.startswith("_"),
                            )
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imports.append(f"{mod}.{alias.name}" if mod else alias.name)

        return FileSymbols(
            relative_path=relative_path,
            symbols=symbols,
            imports=sorted(list(set(imports))),
            exports=sorted(list(set(exports))),
            symbols_available=True,
        )

    @classmethod
    def _extract_js_ts_symbols(cls, relative_path: str, code: str) -> FileSymbols:
        symbols: List[SymbolInfo] = []
        imports: List[str] = []
        exports: List[str] = []

        lines = code.splitlines()

        # Regular expressions for JS/TS patterns
        func_pattern = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)")
        class_pattern = re.compile(r"^(?:export\s+)?class\s+([a-zA-Z0-9_$]+)")
        interface_pattern = re.compile(r"^(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)")
        type_pattern = re.compile(r"^(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*=")
        export_const_pattern = re.compile(r"^export\s+(?:const|let|var)\s+([a-zA-Z0-9_$]+)")
        import_pattern = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
                continue

            is_exp = stripped.startswith("export")

            # Function
            m = func_pattern.search(stripped)
            if m:
                name = m.group(1)
                symbols.append(SymbolInfo(name=name, kind="function", line_number=line_idx, is_exported=is_exp))
                if is_exp: exports.append(name)
                continue

            # Class
            m = class_pattern.search(stripped)
            if m:
                name = m.group(1)
                symbols.append(SymbolInfo(name=name, kind="class", line_number=line_idx, is_exported=is_exp))
                if is_exp: exports.append(name)
                continue

            # Interface
            m = interface_pattern.search(stripped)
            if m:
                name = m.group(1)
                symbols.append(SymbolInfo(name=name, kind="interface", line_number=line_idx, is_exported=is_exp))
                if is_exp: exports.append(name)
                continue

            # Type
            m = type_pattern.search(stripped)
            if m:
                name = m.group(1)
                symbols.append(SymbolInfo(name=name, kind="type", line_number=line_idx, is_exported=is_exp))
                if is_exp: exports.append(name)
                continue

            # Exported variable
            m = export_const_pattern.search(stripped)
            if m:
                name = m.group(1)
                symbols.append(SymbolInfo(name=name, kind="variable", line_number=line_idx, is_exported=True))
                exports.append(name)
                continue

            # Imports
            for imp_match in import_pattern.finditer(stripped):
                imp = imp_match.group(1) or imp_match.group(2)
                if imp:
                    imports.append(imp)

        return FileSymbols(
            relative_path=relative_path,
            symbols=symbols,
            imports=sorted(list(set(imports))),
            exports=sorted(list(set(exports))),
            symbols_available=True,
        )
