"""Task persistence ports and PostgreSQL/Supabase adapters.

The in-memory adapters are deliberately named test doubles.  Production code
uses the SQLAlchemy adapter whenever a database session factory is configured.
"""

from datetime import datetime, timezone
import asyncio
import json
from typing import Any, Dict, List, Optional, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models.task import (
    AgentRunRecord, AgentStateRecord, ApprovalRecord, TaskRecord, TransitionRecord,
)
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.planner import PersistedPlan
from backend.app.models.workspace import Workspace
from backend.app.workflow.states import WorkflowState


class TaskRepository(Protocol):
    async def create(self, task: TaskRecord) -> TaskRecord: ...
    async def get(self, task_id: UUID) -> Optional[TaskRecord]: ...
    async def list_for_workspace(self, workspace_id: UUID) -> List[TaskRecord]: ...
    async def history(self, task_id: UUID) -> List[TransitionRecord]: ...
    async def transition(self, task_id: UUID, target: WorkflowState, transition: TransitionRecord,
                         expected_version: Optional[int]) -> Optional[TaskRecord]: ...
    async def add_approval(self, approval: ApprovalRecord) -> ApprovalRecord: ...
    async def approve_and_transition(self, approval: ApprovalRecord, target: WorkflowState,
                                     transition: TransitionRecord, expected_version: Optional[int]) -> Optional[TaskRecord]: ...
    async def add_run(self, run: AgentRunRecord) -> AgentRunRecord: ...
    async def update_run(self, run: AgentRunRecord) -> AgentRunRecord: ...
    async def list_runs(self, task_id: UUID) -> List[AgentRunRecord]: ...
    async def get_run(self, run_id: UUID) -> Optional[AgentRunRecord]: ...
    async def add_state(self, state: AgentStateRecord) -> AgentStateRecord: ...
    async def add_plan(self, plan: PersistedPlan) -> PersistedPlan: ...
    async def list_plans(self, task_id: UUID) -> List[PersistedPlan]: ...
    async def add_message(self, task_id: UUID, sender_type: str, content: str, metadata: Dict[str, Any]) -> None: ...
    async def set_active_staging(self, task_id: UUID, staging_id: Optional[UUID]) -> Optional[TaskRecord]: ...
    async def set_worker_override(self, task_id: UUID, role: str, worker_id: Optional[str]) -> Optional[TaskRecord]: ...


class WorkspaceRepository(Protocol):
    async def get(self, workspace_id: UUID) -> Optional[Workspace]: ...


class InMemoryWorkspaceRepository:
    """Explicit test double for workspace lookup."""
    def __init__(self, workspaces: Optional[Dict[UUID, Workspace]] = None):
        self.workspaces = workspaces if workspaces is not None else {}

    async def get(self, workspace_id: UUID) -> Optional[Workspace]:
        return self.workspaces.get(workspace_id)


class InMemoryTaskRepository:
    """Explicit test double retaining the old process-local behavior."""
    def __init__(self):
        self.tasks: Dict[UUID, TaskRecord] = {}
        self.histories: Dict[UUID, List[TransitionRecord]] = {}
        self.approvals: Dict[UUID, List[ApprovalRecord]] = {}
        self.runs: Dict[UUID, AgentRunRecord] = {}
        self.states: Dict[UUID, List[AgentStateRecord]] = {}
        self.plans: Dict[UUID, List[PersistedPlan]] = {}
        self.messages: Dict[UUID, List[Dict[str, Any]]] = {}
        self.ai_calls = {}
        self.provider_calls = {}
        self._lock = asyncio.Lock()

    async def reserve_ai_call(self, task_id, limit):
        async with self._lock:
            count = self.ai_calls.get(task_id, 0)
            if count >= limit:
                return False
            self.ai_calls[task_id] = count + 1
            return True

    async def record_provider_call(self, task_id, evidence):
        self.provider_calls.setdefault(task_id, []).append(evidence)

    async def create(self, task):
        from backend.app.core.config import get_settings
        from backend.app.services.task_service import TaskRateLimitError
        from datetime import timedelta
        recent = sum(t.user_id == task.user_id and t.created_at > task.created_at - timedelta(hours=1)
                     for t in self.tasks.values())
        if recent >= get_settings().MAX_TASKS_PER_USER_PER_HOUR:
            raise TaskRateLimitError('Task submission limit reached. Retry later.')
        self.tasks[task.id] = task
        self.histories[task.id] = []
        self.messages[task.id] = [{"sender_type": "user", "content": task.objective, "metadata": {"task_id": str(task.id)}}]
        return task
    async def get(self, task_id): return self.tasks.get(task_id)
    async def list_for_workspace(self, workspace_id):
        return sorted((task for task in self.tasks.values() if task.workspace_id == workspace_id),
                      key=lambda task: task.updated_at, reverse=True)
    async def history(self, task_id): return list(self.histories.get(task_id, []))
    async def transition(self, task_id, target, transition, expected_version):
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task or (expected_version is not None and task.version != expected_version): return None
            self.tasks[task_id] = task.model_copy(update={"status": target, "version": task.version + 1,
                                                           "updated_at": transition.timestamp, "approved_snapshot_hash": transition.metadata.get("snapshot", task.approved_snapshot_hash)})
            self.histories.setdefault(task_id, []).append(transition)
            return self.tasks[task_id]
    async def add_approval(self, approval): self.approvals.setdefault(approval.task_id, []).append(approval); return approval
    async def approve_and_transition(self, approval, target, transition, expected_version):
        async with self._lock:
            task = self.tasks.get(approval.task_id)
            if not task or (expected_version is not None and task.version != expected_version):
                return None
            self.approvals.setdefault(approval.task_id, []).append(approval)
            self.tasks[approval.task_id] = task.model_copy(update={"status": target, "version": task.version + 1, "updated_at": transition.timestamp,
                "approved_snapshot_hash": transition.metadata.get("snapshot", task.approved_snapshot_hash),
                "approved_proposal_id": UUID(transition.metadata["proposal_id"]) if transition.metadata.get("proposal_id") else task.approved_proposal_id})
            self.histories.setdefault(approval.task_id, []).append(transition)
            return self.tasks[approval.task_id]
    async def add_run(self, run): self.runs[run.id] = run; return run
    async def update_run(self, run): self.runs[run.id] = run; return run
    async def list_runs(self, task_id): return [r for r in self.runs.values() if r.task_id == task_id]
    async def get_run(self, run_id): return self.runs.get(run_id)
    async def add_state(self, state): self.states.setdefault(state.task_id, []).append(state); return state
    async def add_plan(self, plan): self.plans.setdefault(plan.task_id, []).append(plan); return plan
    async def list_plans(self, task_id): return list(self.plans.get(task_id, []))
    async def add_message(self, task_id, sender_type, content, metadata):
        self.messages.setdefault(task_id, []).append({"sender_type": sender_type, "content": content, "metadata": metadata})

    async def set_active_staging(self, task_id, staging_id):
        task = self.tasks.get(task_id)
        if task is None:
            return None
        self.tasks[task_id] = task.model_copy(update={"active_staging_workspace_id": staging_id})
        return self.tasks[task_id]

    async def set_worker_override(self, task_id, role, worker_id):
        task = self.tasks.get(task_id)
        if task is None:
            return None
        overrides = dict(task.worker_overrides or {})
        if worker_id is None:
            overrides.pop(role, None)
        else:
            overrides[role] = worker_id
        self.tasks[task_id] = task.model_copy(update={"worker_overrides": overrides})
        return self.tasks[task_id]


def _dt(value: Any) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _json_map(value: Any) -> Dict[str, str]:
    if not value:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        return {str(key): str(item) for key, item in dict(parsed).items()}
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return {}


class PostgresWorkspaceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]): self.sessions = sessions

    async def get(self, workspace_id: UUID) -> Optional[Workspace]:
        async with self.sessions() as s:
            row = (await s.execute(text("SELECT * FROM workspaces WHERE id=:id"), {"id": workspace_id})).mappings().first()
            if not row: return None
            return Workspace(id=row["id"], user_id=row["user_id"], name=row["name"], slug=row["slug"],
                description=row["description"], environment_mode=row["environment_mode"], status=row["status"],
                canonical_root_path=row["canonical_root_path"], file_count=row["file_count"],
                total_size_bytes=row["total_size_bytes"], current_snapshot_hash=row["current_snapshot_hash"],
                git_remote_url=row["git_remote_url"], is_archived=row["is_archived"],
                created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]))


class PostgresTaskRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]): self.sessions = sessions

    @staticmethod
    def _task(row) -> TaskRecord:
        return TaskRecord(id=row["id"], workspace_id=row["workspace_id"], conversation_id=row["conversation_id"],
            user_id=row["user_id"], title=row["title"], objective=row["objective"], user_prompt=row["user_prompt"],
            status=WorkflowState(row["status"]), version=row["version"], approved_snapshot_hash=row["approved_snapshot_hash"],
            approved_proposal_id=row.get("approved_proposal_id"),
            active_loadout_id=row.get("active_loadout_id"),
            worker_overrides=_json_map(row.get("worker_overrides")),
            active_staging_workspace_id=row.get("active_staging_workspace_id"),
            created_at=_dt(row["created_at"]), updated_at=_dt(row["updated_at"]))

    async def reserve_ai_call(self, task_id, limit):
        async with self.sessions.begin() as session:
            result = await session.execute(text("""UPDATE tasks SET ai_call_count=ai_call_count+1
                WHERE id=:id AND ai_call_count < :limit RETURNING ai_call_count"""),
                {'id': task_id, 'limit': limit})
            return result.scalar() is not None

    async def record_provider_call(self, task_id, evidence):
        async with self.sessions.begin() as session:
            await session.execute(text("""INSERT INTO provider_calls (task_id, evidence)
                VALUES (:task, CAST(:evidence AS jsonb))"""),
                {'task': task_id, 'evidence': json.dumps(evidence)})

    async def create(self, task):
        async with self.sessions.begin() as s:
            from backend.app.core.config import get_settings
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                            {'key': 'rlb-submit-' + str(task.user_id)})
            count = (await s.execute(text("""SELECT count(*) FROM tasks
                WHERE user_id=:user AND created_at > now() - interval '1 hour'"""),
                {'user': task.user_id})).scalar_one()
            if count >= get_settings().MAX_TASKS_PER_USER_PER_HOUR:
                from backend.app.services.task_service import TaskRateLimitError
                raise TaskRateLimitError('Task submission limit reached. Retry later.')
            loadout = (await s.execute(text(
                "SELECT active_loadout_id FROM workspace_settings WHERE workspace_id=:workspace_id"
            ), {"workspace_id": task.workspace_id})).scalar()
            if loadout is None:
                loadout = (await s.execute(text(
                    """
                    SELECT id FROM loadouts
                    WHERE user_id=:user_id OR is_system_preset=TRUE
                    ORDER BY CASE WHEN user_id=:user_id THEN 0 ELSE 1 END, created_at
                    LIMIT 1
                    """
                ), {"user_id": task.user_id})).scalar()
            if loadout is None:
                raise RuntimeError("No loadout available for task creation. Configure a loadout first.")
            await s.execute(text("""INSERT INTO conversations (id,workspace_id,title)
                VALUES (:id,:workspace_id,:title) ON CONFLICT (id) DO NOTHING"""),
                {"id": task.conversation_id, "workspace_id": task.workspace_id, "title": task.title})
            await s.execute(text("""INSERT INTO tasks
                (id,workspace_id,conversation_id,user_id,title,objective,user_prompt,status,version,approved_snapshot_hash,active_loadout_id,created_at,updated_at)
                VALUES (:id,:workspace_id,:conversation_id,:user_id,:title,:objective,:user_prompt,:status,:version,:snapshot,:loadout,:created_at,:updated_at)"""),
                {"id":task.id,"workspace_id":task.workspace_id,"conversation_id":task.conversation_id,"user_id":task.user_id,
                 "title":task.title,"objective":task.objective,"user_prompt":task.user_prompt,"status":task.status.value,
                 "version":task.version,"snapshot":task.approved_snapshot_hash,"loadout":loadout,
                 "created_at":task.created_at,"updated_at":task.updated_at})
            await s.execute(text("""INSERT INTO messages
                (id,conversation_id,sender_type,content,metadata,created_at)
                VALUES (:id,:conversation_id,'user',:content,:metadata,:created_at)"""), {
                "id": uuid4(), "conversation_id": task.conversation_id,
                "content": task.objective, "metadata": json.dumps({"task_id": str(task.id)}),
                "created_at": task.created_at,
            })
        return task.model_copy(update={"active_loadout_id": loadout})

    async def list_for_workspace(self, workspace_id):
        async with self.sessions() as session:
            rows = (await session.execute(text(
                "SELECT * FROM tasks WHERE workspace_id=:workspace_id ORDER BY updated_at DESC"
            ), {"workspace_id": workspace_id})).mappings().all()
            return [self._task(row) for row in rows]

    async def get(self, task_id):
        async with self.sessions() as s:
            row = (await s.execute(text("""SELECT t.*, w.user_id FROM tasks t JOIN workspaces w ON w.id=t.workspace_id
                WHERE t.id=:id"""), {"id":task_id})).mappings().first()
            return self._task(row) if row else None

    async def history(self, task_id):
        async with self.sessions() as s:
            rows = (await s.execute(text("SELECT log_line FROM execution_logs WHERE task_id=:id AND source='system' AND stream='workflow' ORDER BY logged_at"), {"id":task_id})).scalars()
            return [TransitionRecord.model_validate(json.loads(value)) for value in rows]

    async def transition(self, task_id, target, transition, expected_version):
        async with self.sessions.begin() as s:
            params = {"id":task_id, "target":target.value, "version":transition.task_version_after,
                      "updated_at":transition.timestamp, "expected":expected_version}
            predicate = " AND version=:expected" if expected_version is not None else ""
            result = await s.execute(text(f"""UPDATE tasks SET status=:target, version=:version, updated_at=:updated_at
                WHERE id=:id{predicate} RETURNING *"""), params)
            row = result.mappings().first()
            if not row: return None
            await s.execute(text("""INSERT INTO execution_logs (id,task_id,source,stream,log_line,logged_at)
                VALUES (:id,:task_id,'system','workflow',:line,:logged_at)"""),
                {"id":uuid4(),"task_id":task_id,"line":json.dumps(transition.model_dump(mode="json")),
                 "logged_at":transition.timestamp})
            return self._task(row)

    async def add_approval(self, approval):
        async with self.sessions.begin() as s:
            await s.execute(text("""INSERT INTO approvals (id,task_id,gate_type,status,user_feedback,reviewed_by,created_at)
                VALUES (:id,:task_id,:gate,:status,:feedback,:user_id,:created_at)"""),
                {"id":approval.id,"task_id":approval.task_id,"gate":approval.approval_type,"status":approval.status,
                 "feedback":approval.feedback,"user_id":approval.user_id,"created_at":approval.timestamp})
        return approval

    async def approve_and_transition(self, approval, target, transition, expected_version):
        async with self.sessions.begin() as s:
            result = await s.execute(text("""UPDATE tasks SET status=:target, version=version+1,
                approved_proposal_id=COALESCE(CAST(:proposal AS uuid),approved_proposal_id),
                updated_at=:updated_at WHERE id=:id AND version=:expected RETURNING *"""), {
                "target": target.value, "updated_at": transition.timestamp, "proposal": transition.metadata.get("proposal_id"),
                "id": approval.task_id, "expected": expected_version,
            })
            row = result.mappings().first()
            if not row:
                return None
            await s.execute(text("""INSERT INTO approvals
                (id,task_id,gate_type,status,user_feedback,reviewed_by,created_at,resolved_at)
                VALUES (:id,:task_id,:gate,:status,:feedback,:user_id,:created_at,:resolved_at)"""), {
                "id": approval.id, "task_id": approval.task_id, "gate": approval.approval_type,
                "status": approval.status, "feedback": approval.feedback,
                "user_id": approval.user_id, "created_at": approval.timestamp,
                "resolved_at": approval.timestamp,
            })
            await s.execute(text("""INSERT INTO execution_logs
                (id,task_id,source,stream,log_line,logged_at)
                VALUES (:id,:task_id,'system','workflow',:line,:logged_at)"""), {
                "id": uuid4(), "task_id": approval.task_id,
                "line": json.dumps(transition.model_dump(mode="json")),
                "logged_at": transition.timestamp,
            })
            return self._task(row)

    async def set_active_staging(self, task_id, staging_id):
        async with self.sessions.begin() as session:
            row = (await session.execute(text("""
                UPDATE tasks SET active_staging_workspace_id=:staging_id, updated_at=NOW()
                WHERE id=:id RETURNING *
            """), {"id": task_id, "staging_id": staging_id})).mappings().first()
            return self._task(row) if row else None

    async def set_worker_override(self, task_id, role, worker_id):
        async with self.sessions.begin() as session:
            current = (await session.execute(
                text("SELECT worker_overrides FROM tasks WHERE id=:id"), {"id": task_id}
            )).scalar()
            overrides = _json_map(current)
            if worker_id is None:
                overrides.pop(role, None)
            else:
                overrides[role] = worker_id
            row = (await session.execute(text("""
                UPDATE tasks SET worker_overrides=CAST(:overrides AS jsonb), updated_at=NOW()
                WHERE id=:id RETURNING *
            """), {"id": task_id, "overrides": json.dumps(overrides)})).mappings().first()
            return self._task(row) if row else None

    async def add_run(self, run):
        async with self.sessions.begin() as s:
            await s.execute(text("""INSERT INTO agent_runs
                (id, task_id, agent_role, loadout_id, worker_id, provider_id, model_name,
                 execution_status, started_at, completed_at, fallback_used, fallback_reason,
                 prompt_tokens, completion_tokens, error_message)
                VALUES (:id,:task_id,:role,:loadout,:worker,:provider,:model,:status,
                        :started,:completed,:fallback,:fallback_reason,:prompt_tokens,
                        :completion_tokens,:error_message)"""), {
                "id": run.id, "task_id": run.task_id, "role": run.agent_role.value,
                "loadout": run.loadout_id, "worker": run.worker_id, "provider": run.provider_id,
                "model": run.model_name, "status": run.status.value,
                "started": run.started_at, "completed": run.completed_at,
                "fallback": run.fallback_used, "fallback_reason": run.fallback_reason,
                "prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens,
                "error_message": run.metadata.get("error_message"),
            })
            await s.execute(text("""INSERT INTO execution_logs
                (id,task_id,source,stream,log_line,logged_at)
                VALUES (:id,:task_id,'agent','event',:line,:logged_at)"""), {
                "id": uuid4(), "task_id": run.task_id,
                "line": json.dumps({"event": "agent_run_created", "run_id": str(run.id), "role": run.agent_role.value}),
                "logged_at": run.started_at or datetime.now(timezone.utc),
            })
        return run

    @staticmethod
    def _run(row):
        return AgentRunRecord(
            id=row["id"], task_id=row["task_id"], agent_role=AgentRole(row["agent_role"]),
            loadout_id=row["loadout_id"], worker_id=row["worker_id"], provider_id=row["provider_id"],
            model_name=row["model_name"], status=ExecutionStatus(row["execution_status"]),
            started_at=_dt(row["started_at"]) if row["started_at"] else None,
            completed_at=_dt(row["completed_at"]) if row["completed_at"] else None,
            fallback_used=row["fallback_used"], fallback_reason=row["fallback_reason"],
            prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"],
            metadata={"error_message": row["error_message"]} if row["error_message"] else {},
        )

    async def update_run(self, run):
        async with self.sessions.begin() as s:
            await s.execute(text("""UPDATE agent_runs SET execution_status=:status, worker_id=:worker, provider_id=:provider, model_name=:model,
                started_at=:started, completed_at=:completed, fallback_used=:fallback,
                fallback_reason=:fallback_reason, prompt_tokens=:prompt_tokens,
                completion_tokens=:completion_tokens, error_message=:error_message
                WHERE id=:id"""), {
                "id": run.id, "worker": run.worker_id, "provider": run.provider_id, "model": run.model_name,
                "status": run.status.value, "started": run.started_at,
                "completed": run.completed_at, "fallback": run.fallback_used,
                "fallback_reason": run.fallback_reason, "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "error_message": run.metadata.get("error_message"),
            })
            await s.execute(text("""INSERT INTO execution_logs
                (id,task_id,source,stream,log_line,logged_at)
                VALUES (:id,:task_id,'agent','event',:line,:logged_at)"""), {
                "id": uuid4(), "task_id": run.task_id,
                "line": json.dumps({"event": "agent_run_status", "run_id": str(run.id), "status": run.status.value}),
                "logged_at": run.completed_at or run.started_at or datetime.now(timezone.utc),
            })
        return run

    async def list_runs(self, task_id):
        async with self.sessions() as s:
            rows = (await s.execute(text("SELECT * FROM agent_runs WHERE task_id=:id ORDER BY started_at, id"), {"id": task_id})).mappings().all()
            return [self._run(row) for row in rows]

    async def get_run(self, run_id):
        async with self.sessions() as s:
            row = (await s.execute(text("SELECT * FROM agent_runs WHERE id=:id"), {"id": run_id})).mappings().first()
            return self._run(row) if row else None
    async def add_state(self, state):
        async with self.sessions.begin() as s:
            if state.checkpoint_seq <= 1:
                max_seq = await s.execute(text("""SELECT COALESCE(MAX(checkpoint_seq), 0)
                    FROM agent_states WHERE task_id=:task_id AND agent_role=:role"""),
                    {"task_id": state.task_id, "role": state.agent_role.value})
                state = state.model_copy(update={"checkpoint_seq": int(max_seq.scalar()) + 1})
            await s.execute(text("""INSERT INTO agent_states (id,task_id,agent_role,state_payload,checkpoint_seq,created_at)
                VALUES (:id,:task_id,:role,:payload,:seq,:created_at)"""),
                {"id":state.id,"task_id":state.task_id,"role":state.agent_role.value,
                 "payload":json.dumps(state.state_payload),"seq":state.checkpoint_seq,"created_at":state.created_at})
        return state

    async def add_plan(self, plan):
        data = plan.plan.model_dump(mode="json")
        title = data["objective"][:200]
        summary = data["understanding"]
        async with self.sessions.begin() as s:
            await s.execute(text("""INSERT INTO plans
                (id,task_id,agent_run_id,title,summary,steps,affected_files,
                 revision_number,structured_plan,source_snapshot_hash,status,created_at)
                VALUES (:id,:task_id,:run,:title,:summary,:steps,:files,:revision,
                        :structured,:snapshot,:status,:created)"""), {
                "id": plan.id, "task_id": plan.task_id, "run": plan.agent_run_id,
                "title": title, "summary": summary,
                "steps": json.dumps(data["implementation_steps"]),
                "files": json.dumps(data["affected_files"]),
                "revision": plan.revision_number, "structured": json.dumps(data),
                "snapshot": plan.source_snapshot_hash, "status": plan.status,
                "created": datetime.fromisoformat(plan.created_at.replace("Z", "+00:00")),
            })
        return plan

    async def list_plans(self, task_id):
        async with self.sessions() as s:
            rows = (await s.execute(text(
                "SELECT * FROM plans WHERE task_id=:task_id ORDER BY revision_number"
            ), {"task_id": task_id})).mappings().all()
            return [PersistedPlan(
                id=row["id"], task_id=row["task_id"], agent_run_id=row["agent_run_id"],
                revision_number=row["revision_number"],
                plan=row["structured_plan"], source_snapshot_hash=row["source_snapshot_hash"],
                status=row["status"], created_at=row["created_at"].isoformat(),
            ) for row in rows]

    async def add_message(self, task_id, sender_type, content, metadata):
        async with self.sessions.begin() as s:
            conversation_id = (await s.execute(
                text("SELECT conversation_id FROM tasks WHERE id=:task_id"), {"task_id": task_id}
            )).scalar_one()
            await s.execute(text("""INSERT INTO messages
                (id,conversation_id,sender_type,content,metadata)
                VALUES (:id,:conversation_id,:sender_type,:content,:metadata)"""), {
                "id": uuid4(), "conversation_id": conversation_id,
                "sender_type": sender_type, "content": content,
                "metadata": json.dumps(metadata),
            })
