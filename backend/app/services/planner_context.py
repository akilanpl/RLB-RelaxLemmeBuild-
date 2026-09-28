"""Deterministic, bounded context retrieval for the Planner."""

from typing import Any, Dict, List
from uuid import UUID
from backend.app.analysis.service import CodebaseAnalysisService
from backend.app.models.task import TaskRecord
from backend.app.services.workspace_service import WorkspaceService


def _safe(value: str) -> str:
    from backend.app.analysis.sanitizer import redact_secrets
    return redact_secrets(value)


class PlannerContextBuilder:
    def __init__(self, workspace_service=None, analysis_service=None):
        self.workspace_service = workspace_service or WorkspaceService()
        self.analysis_service = analysis_service or CodebaseAnalysisService(
            workspace_service=self.workspace_service
        )

    async def build(self, task: TaskRecord) -> Dict[str, Any]:
        analysis = await self.analysis_service.get_latest_analysis(task.workspace_id, task.user_id)
        if not analysis:
            analysis = await self.analysis_service.analyze_workspace(task.workspace_id, task.user_id)
        keywords = set((task.title + " " + task.objective).lower().split())
        scored = []
        for file in analysis.indexed_files:
            path = file.relative_path.lower()
            score = sum(2 for word in keywords if len(word) > 2 and word in path)
            if file.relative_path in {entry.path for entry in analysis.entry_points}:
                score += 3
            if score:
                scored.append((score, file.relative_path))
        selected = [path for _, path in sorted(scored, reverse=True)[:8]]
        source: List[Dict[str, str]] = []
        for path in selected:
            if path.rsplit("/", 1)[-1].startswith(".env"):
                continue
            try:
                content = await self.workspace_service.read_workspace_file(
                    task.workspace_id, path, task.user_id
                )
                source.append({"path": path, "content": _safe(content.decode("utf-8")[:12000])})
            except (UnicodeDecodeError, FileNotFoundError):
                continue
        return {
            "task": {"title": _safe(task.title), "objective": _safe(task.objective)},
            "codebase": {
                "summary": analysis.summary,
                "languages": analysis.primary_languages,
                "frameworks": analysis.frameworks_detected,
                "technologies": [item.model_dump() for item in analysis.technologies],
                "dependencies": [item.model_dump() for item in analysis.dependencies],
                "entry_points": [item.model_dump() for item in analysis.entry_points],
                "dependency_graph": analysis.dependency_graph.model_dump(),
            },
            "relevant_source": source[:8],
        }
