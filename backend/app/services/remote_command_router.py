"""Translate authorized device commands into existing workflow operations."""

import mimetypes
from uuid import UUID

from backend.app.models.task import ActorType
from backend.app.services.device_control import CommandType
from backend.app.services.task_service import TaskNotFoundError
from backend.app.services.task_artifacts import (
    MAX_ARTIFACT_BYTES,
    safe_artifact_name,
    safe_relative_path,
)
from backend.app.workflow.states import WorkflowState


class RemoteCommandRouter:
    def __init__(self, runtime):
        self.runtime = runtime

    async def __call__(self, command: dict) -> dict:
        user_id = UUID(str(command["user_id"]))
        command_type = CommandType(command["command_type"])
        payload = command.get("payload") or {}
        task_id = UUID(str(command["task_id"])) if command.get("task_id") else None

        if command_type in {CommandType.REVIEW_TASK, CommandType.PLAN_DECISION, CommandType.CODE_DECISION}:
            if task_id is None:
                raise ValueError("A task is required for review.")
            task = await self.runtime.workflow.get_task(task_id, user_id)
            if command_type == CommandType.REVIEW_TASK:
                connection = self.runtime.device_connection
                if connection is None:
                    raise RuntimeError("Artifact connection is unavailable.")
                import json
                bundle = {
                    "task": task.model_dump(mode="json"),
                    "plans": [p.model_dump(mode="json") for p in await self.runtime.workflow.list_plans(task.id, user_id)],
                    "proposals": [p.model_dump(mode="json") for p in await self.runtime.agents.coder.proposals.list_by_task(task.id)],
                    "test_plans": [p.model_dump(mode="json") for p in await self.runtime.testing.list_plans(task.id)],
                    "test_executions": [e.model_dump(mode="json") for e in await self.runtime.testing.list_executions(task.id)],
                }
                report = await self.runtime.agents.reviewer.repository.get_by_task(task.id)
                bundle["review"] = report.model_dump(mode="json") if report else None
                artifact = await connection.upload_task_artifact(
                    task.id, task.workspace_id, f"review-{task.version}.json",
                    json.dumps(bundle).encode(), "application/json",
                )
                return {"task_id": str(task.id), "artifact": artifact, "version": task.version}
            if task.version != payload.get("expected_version"):
                raise ValueError("Task changed after review; load its current evidence.")
            decision = payload.get("status")
            if decision not in {"approved", "rejected", "revision_requested"}:
                raise ValueError("Invalid approval decision.")
            feedback = str(payload.get("feedback") or "").strip() or None
            if decision == "revision_requested" and not feedback:
                raise ValueError("Revision feedback is required.")
            if command_type == CommandType.PLAN_DECISION:
                plans = await self.runtime.workflow.list_plans(task.id, user_id)
                if task.status != WorkflowState.PLAN_REVIEW or not plans or str(plans[-1].id) != str(payload.get("plan_id")):
                    raise ValueError("Plan is not the current approval gate.")
                await self.runtime.workflow.record_approval(
                    task.id, user_id, "plan", decision, feedback, defer_setup=True,
                )
            else:
                proposal_id = UUID(str(payload["proposal_id"]))
                proposal = await self.runtime.agents.coder.proposals.get(proposal_id)
                if proposal is None or proposal.task_id != task.id or task.status != WorkflowState.CODE_REVIEW:
                    raise ValueError("Proposal is not the current approval gate.")
                if decision == "approved":
                    await self.runtime.agents.coder.request_promotion(proposal.id, user_id)
                elif decision == "revision_requested":
                    await self.runtime.agents.coder.request_revision(proposal.id, user_id, feedback)
                else:
                    await self.runtime.agents.coder.reject(proposal.id, user_id)
            if decision in {"approved", "revision_requested"}:
                await self.runtime.queue.enqueue(task.id, user_id)
            return {"task_id": str(task.id), "decision": decision}

        if command_type == CommandType.START_TASK:
            workspace_id = UUID(str(payload["workspace_id"]))
            workspace = await self.runtime.workflow.workspace_service.get_workspace(workspace_id, user_id)
            if workspace.local_path:
                workspace = await self.runtime.workflow.workspace_service.refresh_local_workspace(
                    workspace.id, user_id
                )
            task = await self.runtime.workflow.create_task(
                workspace, user_id, str(payload.get("title") or "Remote task"),
                str(payload["objective"]),
            )
            await self.runtime.queue.enqueue(task.id, user_id)
            return {"task_id": str(task.id), "workflow_state": task.status.value}

        if command_type == CommandType.PROMPT:
            if task_id is None:
                raise ValueError("A task is required for a remote prompt.")
            task = await self.runtime.workflow.get_task(task_id, user_id)
            if task.status in {WorkflowState.PLAN_REVIEW, WorkflowState.CODE_REVIEW}:
                raise ValueError("A human approval is required at the current workflow gate.")
            if task.status not in {
                WorkflowState.READY, WorkflowState.ANALYZING, WorkflowState.PLANNING,
                WorkflowState.CODING, WorkflowState.REPAIRING,
            }:
                raise ValueError("Remote prompts are not supported at the current workflow stage.")
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt or len(prompt) > 4000:
                raise ValueError("Prompt must contain 1–4000 characters.")
            await self.runtime.queue.add_prompt(task.id, user_id, prompt)
            await self.runtime.queue.enqueue(task.id, user_id)
            return {"accepted": True, "task_id": str(task.id), "workflow_state": task.status.value}

        if command_type in {CommandType.PAUSE_TASK, CommandType.RESUME_TASK, CommandType.STOP_TASK}:
            if task_id is None:
                raise ValueError("A task is required for this control command.")
            task = await self.runtime.workflow.get_task(task_id, user_id)
            if task.status in {WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.FAILED}:
                raise ValueError("Task is already terminal and cannot be controlled.")
            if command_type == CommandType.PAUSE_TASK:
                await self.runtime.queue.pause_task(task.id, user_id)
                return {"runtime_state": "paused", "task_id": str(task.id)}
            if command_type == CommandType.RESUME_TASK:
                await self.runtime.queue.resume_task(task.id, user_id)
                await self.runtime.queue.enqueue(task.id, user_id)
                return {"runtime_state": "running", "task_id": str(task.id)}
            await self.runtime.queue.resume_task(task.id, user_id)
            await self.runtime.workflow.transition(
                task.id, WorkflowState.CANCELLED, ActorType.USER, user_id,
                "Stopped by remote device command", expected_version=task.version,
            )
            return {"workflow_state": "cancelled", "task_id": str(task.id)}

        if command_type == CommandType.REQUEST_ARTIFACT_UPLOAD:
            if task_id is None:
                raise ValueError("A task is required for an artifact upload.")
            connection = getattr(self.runtime, "device_connection", None)
            if connection is None:
                raise RuntimeError("Cloud artifact connection is unavailable.")
            task = await self.runtime.workflow.get_task(task_id, user_id)
            workspace = await self.runtime.workflow.workspace_service.get_workspace(task.workspace_id, user_id)
            relative_path = safe_relative_path(str(payload.get("relative_path", "")))
            root = workspace.canonical_root_path
            if task.active_staging_workspace_id:
                staging = await self.runtime.staging._load_staging(task.active_staging_workspace_id)
                expected = f"workspaces/{task.workspace_id}/staging/{task.active_staging_workspace_id}"
                if (staging is None or staging.task_id != task.id or staging.workspace_id != task.workspace_id
                        or staging.staging_root_path != expected):
                    raise ValueError("Task staging workspace is unavailable or mismatched.")
                root = expected
            elif (root != f"workspaces/{task.workspace_id}/canonical"
                  and not root.startswith(f"workspaces/{task.workspace_id}/snapshots/")):
                raise ValueError("Task workspace root is outside the expected artifact layout.")
            storage_path = f"{root}/{relative_path}"
            storage = self.runtime.workflow.workspace_service.storage
            stats = await storage.get_file_stats(storage_path)
            size = int(stats.get("size_bytes", 0))
            if size < 1 or size > MAX_ARTIFACT_BYTES:
                raise ValueError("Artifact must be between 1 byte and 25 MiB.")
            content = await storage.read_file(storage_path)
            if len(content) != size:
                raise ValueError("Artifact changed while it was being synchronized.")
            filename = safe_artifact_name(relative_path.rsplit("/", 1)[-1])
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            metadata = await connection.upload_task_artifact(
                task.id, workspace.id, filename, content, content_type,
            )
            return {"artifact": metadata, "task_id": str(task.id)}

        if command_type == CommandType.DOWNLOAD_ARTIFACT_TO_PC:
            if task_id is None:
                raise ValueError("A task is required for an artifact download.")
            connection = getattr(self.runtime, "device_connection", None)
            if connection is None:
                raise RuntimeError("Cloud artifact connection is unavailable.")
            try:
                artifact_id = UUID(str(payload["artifact_id"]))
            except (KeyError, ValueError) as exc:
                raise ValueError("A valid artifact_id is required.") from exc
            task = await self.runtime.workflow.get_task(task_id, user_id)
            name, content_type, content = await connection.download_task_artifact(task.id, artifact_id)
            filename = safe_artifact_name(name)
            if not content or len(content) > MAX_ARTIFACT_BYTES:
                raise ValueError("Downloaded artifact is empty or exceeds the 25 MiB limit.")
            relative_path = f"device-artifacts/{task.id}/{artifact_id}/{filename}"
            await self.runtime.workflow.workspace_service.storage.write_file(relative_path, content)
            return {
                "task_id": str(task.id), "artifact_id": str(artifact_id),
                "name": filename, "content_type": content_type,
                "size_bytes": len(content), "relative_path": relative_path,
            }
        raise ValueError("Unsupported remote command.")
