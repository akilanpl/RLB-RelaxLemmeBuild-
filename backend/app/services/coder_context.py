"""Bounded context retrieval for the staging-scoped Coder."""

from typing import Any, Dict

from backend.app.models.coder import CoderContext


def _safe(value: str) -> str:
    from backend.app.analysis.sanitizer import redact_secrets
    return redact_secrets(value)


class CoderContextBuilder:
    def __init__(self, staging_service, workspace_service=None):
        self.staging_service = staging_service
        self.workspace_service = workspace_service or staging_service.workspace_service

    async def build(self, task, staging_id=None) -> Dict[str, Any]:
        staging_id = staging_id or task.active_staging_workspace_id
        if staging_id is None:
            raise RuntimeError("An active staging workspace is required before coding.")
        files = []
        for path in (await self.staging_service.list_staging_files(staging_id, task.user_id))[:100]:
            if path.rsplit("/", 1)[-1].startswith(".env"):
                continue
            try:
                content = await self.staging_service.read_staging_file(
                    staging_id, path, task.user_id
                )
                files.append({"path": path, "content": _safe(content.decode("utf-8")[:20000])})
            except (UnicodeDecodeError, FileNotFoundError):
                files.append({"path": path, "binary": True})
        staging = await self.staging_service.get_staging_workspace(staging_id, task.user_id)
        return CoderContext(
            task_id=task.id, objective=_safe(task.objective),
            snapshot_hash=staging.base_snapshot_hash, files=files[:100],
        ).model_dump(mode="json")
