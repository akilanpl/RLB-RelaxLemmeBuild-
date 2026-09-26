"""Comprehensive test suite for Phase 4 Codebase Intelligence."""

import io
import uuid
import zipfile
import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.main import app
from backend.app.services.workspace_service import WorkspaceService
from backend.app.analysis.service import CodebaseAnalysisService
from backend.app.analysis.indexer import FileIndexer
from backend.app.analysis.detector import TechnologyDetector
from backend.app.analysis.dependencies import DependencyParser
from backend.app.analysis.entry_points import EntryPointDetector
from backend.app.analysis.symbols import SymbolExtractor
from backend.app.analysis.graph import DependencyGraphBuilder
from backend.app.analysis.sanitizer import redact_secrets
from backend.app.analysis.types import AnalysisStatus
from backend.app.storage.local import LocalStorageBackend


def create_test_zip(files: dict[str, str]) -> bytes:
    """Helper to build an in-memory ZIP archive from a mapping of path -> content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_file_indexer_filtering_and_metadata(tmp_path):
    """Verify that indexer ignores build/cache dirs and correctly extracts file metadata."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "test_ws/canonical"

    # Write files including ignored directories
    await storage.write_file(f"{prefix}/src/index.ts", b"export const version = '1.0.0';\n")
    await storage.write_file(f"{prefix}/node_modules/pkg/index.js", b"console.log('ignored');\n")
    await storage.write_file(f"{prefix}/.next/cache/build.json", b"{}\n")
    await storage.write_file(f"{prefix}/__pycache__/app.cpython-312.pyc", b"\x00\x00\x00")
    await storage.write_file(f"{prefix}/README.md", b"# Documentation\nLine 2\n")

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)

    rel_paths = [f.relative_path for f in indexed]
    assert "src/index.ts" in rel_paths
    assert "README.md" in rel_paths
    assert "node_modules/pkg/index.js" not in rel_paths
    assert ".next/cache/build.json" not in rel_paths
    assert "__pycache__/app.cpython-312.pyc" not in rel_paths

    ts_file = next(f for f in indexed if f.relative_path == "src/index.ts")
    assert ts_file.language == "TypeScript"
    assert ts_file.line_count == 1
    assert not ts_file.is_binary
    assert len(ts_file.sha256_hash) == 64


@pytest.mark.asyncio
async def test_technology_and_framework_detection(tmp_path):
    """Verify deterministic technology detection for Next.js, React, and TypeScript."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "next_project/canonical"

    package_json = """{
      "name": "my-next-app",
      "dependencies": {
        "next": "^14.2.0",
        "react": "^18.3.0",
        "react-dom": "^18.3.0"
      },
      "devDependencies": {
        "typescript": "^5.0.0",
        "tailwindcss": "^3.4.0"
      }
    }"""
    await storage.write_file(f"{prefix}/package.json", package_json.encode())
    await storage.write_file(f"{prefix}/tsconfig.json", b"{}")
    await storage.write_file(f"{prefix}/next.config.js", b"module.exports = {};")
    await storage.write_file(f"{prefix}/src/app/page.tsx", b"export default function Page() { return <h1>Home</h1>; }")

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)

    techs = await TechnologyDetector.detect_technologies(indexed, storage, prefix)
    names = {t.name for t in techs}

    assert "TypeScript" in names
    assert "Next.js" in names
    assert "React" in names
    assert "Tailwind CSS" in names

    next_tech = next(t for t in techs if t.name == "Next.js")
    assert next_tech.confidence >= 0.9
    assert len(next_tech.evidence) > 0


@pytest.mark.asyncio
async def test_dependency_parser_separation(tmp_path):
    """Verify static manifest parsing separates production vs development dependencies."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "deps_project/canonical"

    package_json = """{
      "dependencies": {
        "express": "^4.19.2",
        "pg": "^8.11.3"
      },
      "devDependencies": {
        "jest": "^29.7.0"
      }
    }"""
    await storage.write_file(f"{prefix}/package.json", package_json.encode())

    reqs_txt = """
    fastapi==0.110.0
    # Dev comment
    pytest>=8.0.0
    uvicorn[standard]~=0.28.0
    """
    await storage.write_file(f"{prefix}/requirements.txt", reqs_txt.encode())

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)

    deps = await DependencyParser.extract_dependencies(indexed, storage, prefix)
    dep_map = {d.name: d for d in deps}

    assert "express" in dep_map
    assert dep_map["express"].dependency_type == "production"
    assert dep_map["express"].version_spec == "^4.19.2"

    assert "jest" in dep_map
    assert dep_map["jest"].dependency_type == "development"

    assert "fastapi" in dep_map
    assert dep_map["fastapi"].dependency_type == "production"

    assert "pytest" in dep_map
    assert dep_map["pytest"].dependency_type == "development"


@pytest.mark.asyncio
async def test_entry_point_detector(tmp_path):
    """Verify entry point detection identifies Next.js App Router and Python module roots."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "app_project/canonical"

    await storage.write_file(f"{prefix}/src/app/page.tsx", b"export default function Page() {}")
    await storage.write_file(
        f"{prefix}/main.py",
        b"from fastapi import FastAPI\napp = FastAPI()\n\ndef run(): pass\n",
    )

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)

    entry_points = await EntryPointDetector.detect_entry_points(indexed, storage, prefix)
    ep_paths = [e.path for e in entry_points]

    assert "src/app/page.tsx" in ep_paths
    assert "main.py" in ep_paths

    next_ep = next(e for e in entry_points if e.path == "src/app/page.tsx")
    assert next_ep.entry_type == "nextjs_app_router"

    py_ep = next(e for e in entry_points if e.path == "main.py")
    assert py_ep.entry_type == "python_module"


@pytest.mark.asyncio
async def test_symbol_extractor_python_ast(tmp_path):
    """Verify Python AST static symbol extraction without code execution."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "ast_project/canonical"

    py_code = """import os
from sys import argv

class WorkspaceManager:
    def __init__(self, root: str):
        self.root = root

    async def sync_files(self) -> bool:
        return True

def standalone_task(val: int) -> int:
    return val * 2
"""
    await storage.write_file(f"{prefix}/services.py", py_code.encode())

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)
    file_info = indexed[0]

    symbols = await SymbolExtractor.extract_file_symbols(file_info, storage, prefix)
    sym_names = {s.name: s.kind for s in symbols.symbols}

    assert "WorkspaceManager" in sym_names
    assert sym_names["WorkspaceManager"] == "class"
    assert "sync_files" in sym_names
    assert sym_names["sync_files"] == "function"
    assert "standalone_task" in sym_names
    assert sym_names["standalone_task"] == "function"

    assert "os" in symbols.imports
    assert "sys.argv" in symbols.imports


@pytest.mark.asyncio
async def test_symbol_extractor_typescript(tmp_path):
    """Verify TypeScript regex-based static symbol extraction."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "ts_project/canonical"

    ts_code = """import { useState } from 'react';
import { helper } from './utils';

export interface UserProfile {
  id: string;
  name: string;
}

export class AccountService {
  getId() { return '1'; }
}

export function formatName(first: string, last: string) {
  return `${first} ${last}`;
}

export const API_VERSION = 'v1';
"""
    await storage.write_file(f"{prefix}/profile.ts", ts_code.encode())

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)
    file_info = indexed[0]

    symbols = await SymbolExtractor.extract_file_symbols(file_info, storage, prefix)
    sym_names = {s.name: s.kind for s in symbols.symbols}

    assert "UserProfile" in sym_names
    assert sym_names["UserProfile"] == "interface"
    assert "AccountService" in sym_names
    assert sym_names["AccountService"] == "class"
    assert "formatName" in sym_names
    assert sym_names["formatName"] == "function"
    assert "API_VERSION" in sym_names
    assert sym_names["API_VERSION"] == "variable"

    assert "react" in symbols.imports
    assert "./utils" in symbols.imports


@pytest.mark.asyncio
async def test_dependency_graph_builder(tmp_path):
    """Verify static dependency graph connects files through import relationships."""
    storage = LocalStorageBackend(base_directory=str(tmp_path))
    prefix = "graph_project/canonical"

    await storage.write_file(f"{prefix}/src/utils.ts", b"export const add = (a: number, b: number) => a + b;\n")
    await storage.write_file(
        f"{prefix}/src/main.ts",
        b"import { add } from './utils';\nconsole.log(add(1, 2));\n",
    )

    indexer = FileIndexer()
    indexed = await indexer.index_workspace(storage, prefix)

    file_symbols = []
    for f in indexed:
        fs = await SymbolExtractor.extract_file_symbols(f, storage, prefix)
        file_symbols.append(fs)

    graph = DependencyGraphBuilder.build_graph(indexed, file_symbols)

    node_ids = {n.id for n in graph.nodes}
    assert "src/main.ts" in node_ids
    assert "src/utils.ts" in node_ids

    # Edge from main.ts to utils.ts
    matching_edges = [
        e for e in graph.edges if e.source == "src/main.ts" and e.target == "src/utils.ts"
    ]
    assert len(matching_edges) == 1
    assert matching_edges[0].edge_type == "internal_import"


def test_secret_redaction():
    """Verify that potential API keys, passwords, and tokens are scrubbed from outputs."""
    sensitive_text = (
        "Configured with sk-proj-1234567890abcdef1234567890 and "
        "GitHub token ghp_abcdefghijklmnopqrstuvwxyz1234567890 and "
        "password = 'SuperSecretPassword123!'"
    )
    clean = redact_secrets(sensitive_text)
    assert "sk-proj-1234567890abcdef1234567890" not in clean
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in clean
    assert "[REDACTED_API_KEY]" in clean
    assert "[REDACTED_GITHUB_TOKEN]" in clean
    assert "[REDACTED_SECRET]" in clean


@pytest.mark.asyncio
async def test_stale_analysis_status(tmp_path):
    """Verify that modifying workspace snapshot marks analysis as stale."""
    ws_service = WorkspaceService(storage=LocalStorageBackend(base_directory=str(tmp_path)))
    analysis_service = CodebaseAnalysisService(workspace_service=ws_service, storage=ws_service.storage)

    user_id = uuid.uuid4()
    ws = await ws_service.create_workspace(user_id=user_id, name="Stale Test Workspace")

    # Initial analysis
    res1 = await analysis_service.analyze_workspace(ws.id, user_id)
    assert res1.status == AnalysisStatus.COMPLETED

    # Fetch immediately -> COMPLETED
    latest = await analysis_service.get_latest_analysis(ws.id, user_id)
    assert latest.status == AnalysisStatus.COMPLETED

    # Simulate approved workspace modification (snapshot change)
    ws.current_snapshot_hash = "new-snapshot-hash-999"

    # Fetch again -> STALE
    stale_res = await analysis_service.get_latest_analysis(ws.id, user_id)
    assert stale_res.status == AnalysisStatus.STALE


@pytest.mark.asyncio
async def test_analysis_rest_api_lifecycle():
    """Verify REST API endpoints for triggering and retrieving codebase intelligence."""
    transport = ASGITransport(app=app)
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())

    zip_bytes = create_test_zip({
        "package.json": '{"name": "test-project", "dependencies": {"next": "14.0.0", "react": "18.0.0"}}',
        "tsconfig.json": "{}",
        "src/app/page.tsx": "export default function Page() { return <div>App</div>; }",
        "src/lib/math.ts": "export function square(n: number) { return n * n; }",
    })

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Provision workspace with ZIP
        create_resp = await client.post(
            "/api/v1/workspaces",
            data={"name": "Analysis API Test", "environment_mode": "sandboxed"},
            files={"file": ("project.zip", zip_bytes, "application/zip")},
            headers={"x-user-id": user_id},
        )
        assert create_resp.status_code == 201
        ws_id = create_resp.json()["id"]

        # 2. GET /workspaces/{id}/analysis
        get_analysis_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/analysis",
            headers={"x-user-id": user_id},
        )
        assert get_analysis_resp.status_code == 200
        analysis_data = get_analysis_resp.json()
        assert analysis_data["status"] == "completed"
        assert "TypeScript" in analysis_data["primary_languages"]
        assert "Next.js" in analysis_data["frameworks_detected"]
        assert len(analysis_data["indexed_files"]) >= 4

        # 3. GET /workspaces/{id}/analysis/summary
        summary_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/analysis/summary",
            headers={"x-user-id": user_id},
        )
        assert summary_resp.status_code == 200
        summary_data = summary_resp.json()
        assert "architecture_overview" in summary_data
        assert summary_data["total_files"] >= 4

        # 4. GET /workspaces/{id}/analysis/graph
        graph_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/analysis/graph",
            headers={"x-user-id": user_id},
        )
        assert graph_resp.status_code == 200
        graph_data = graph_resp.json()
        assert "nodes" in graph_data
        assert "edges" in graph_data

        # 5. GET /workspaces/{id}/analysis/technologies
        tech_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/analysis/technologies",
            headers={"x-user-id": user_id},
        )
        assert tech_resp.status_code == 200
        tech_list = tech_resp.json()
        tech_names = [t["name"] for t in tech_list]
        assert "Next.js" in tech_names

        # 6. POST /workspaces/{id}/analysis with force=true (re-analysis)
        reanalysis_resp = await client.post(
            f"/api/v1/workspaces/{ws_id}/analysis?force=true",
            headers={"x-user-id": user_id},
        )
        assert reanalysis_resp.status_code == 200
        reanalysis_data = reanalysis_resp.json()
        assert reanalysis_data["analysis_version"] >= 2

        # 7. Security: Access denied for another user (403)
        forbidden_resp = await client.get(
            f"/api/v1/workspaces/{ws_id}/analysis",
            headers={"x-user-id": other_user_id},
        )
        assert forbidden_resp.status_code == 403

        # 8. Not Found: Nonexistent workspace (404)
        not_found_resp = await client.get(
            f"/api/v1/workspaces/{uuid.uuid4()}/analysis",
            headers={"x-user-id": user_id},
        )
        assert not_found_resp.status_code == 404
