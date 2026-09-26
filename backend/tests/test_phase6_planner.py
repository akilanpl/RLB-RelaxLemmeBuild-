import json
from uuid import uuid4

import pytest

from backend.app.ai.gateway import AIGateway, AIRequest, AIResponse
from backend.app.analysis.repository import InMemoryAnalysisRepository
from backend.app.analysis.types import CodebaseAnalysisResult, DependencyGraph
from backend.app.models.planner import ImplementationPlan
from backend.app.models.task import ActorType
from backend.app.models.workspace import Workspace
from backend.app.services.planner_service import PlannerService, PlannerExecutionError
from backend.app.services.task_service import WorkflowEngine
from backend.app.workflow.states import WorkflowState
from datetime import datetime, timezone


class MockGateway(AIGateway):
    def __init__(self, content: str):
        self.content = content

    def validate_configuration(self):
        return None

    async def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(content=self.content, model="mock")


class MockContext:
    async def build(self, task):
        return {"task": {"objective": task.objective}, "relevant_source": []}


def plan_json():
    return json.dumps({
        "objective": "Add dark mode",
        "understanding": "The UI needs a theme toggle.",
        "implementation_steps": [{
            "order": 1,
            "description": "Add theme state",
            "rationale": "Persist the selected theme.",
            "candidate_files": ["src/theme.ts"],
        }],
        "affected_files": ["src/theme.ts"],
        "dependencies": [],
        "risks": ["Theme contrast"],
        "assumptions": [],
        "expected_behavior": "Users can toggle dark mode.",
        "unresolved_questions": [],
    })


@pytest.mark.asyncio
async def test_planner_persists_structured_plan_and_enters_review():
    user_id = uuid4()
    workspace = Workspace(
        id=uuid4(), user_id=user_id, name="App", slug="app",
        canonical_root_path="workspaces/app/canonical",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    engine = WorkflowEngine()
    task = await engine.create_task(workspace, user_id, "Dark mode", "Add dark mode")
    task = await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "test setup", expected_version=task.version)
    service = PlannerService(MockGateway(plan_json()), MockContext())
    import backend.app.services.planner_service as planner_module
    original = planner_module.workflow_engine
    planner_module.workflow_engine = engine
    try:
        result = await service.execute(task.id, user_id)
        assert isinstance(result.plan, ImplementationPlan)
        assert (await engine.get_task(task.id, user_id)).status.value == "planning"
        assert len(await engine.list_plans(task.id, user_id)) == 1
    finally:
        planner_module.workflow_engine = original


@pytest.mark.asyncio
async def test_planner_rejects_malformed_structured_output():
    user_id = uuid4()
    workspace = Workspace(
        id=uuid4(), user_id=user_id, name="App", slug="app",
        canonical_root_path="workspaces/app/canonical",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    engine = WorkflowEngine()
    task = await engine.create_task(workspace, user_id, "Dark mode", "Add dark mode")
    task = await engine.transition(task.id, WorkflowState.PLANNING, ActorType.SYSTEM, None, "test setup", expected_version=task.version)
    service = PlannerService(MockGateway("{}"), MockContext())
    import backend.app.services.planner_service as planner_module
    original = planner_module.workflow_engine
    planner_module.workflow_engine = engine
    try:
        with pytest.raises(PlannerExecutionError):
            await service.execute(task.id, user_id)
    finally:
        planner_module.workflow_engine = original


@pytest.mark.asyncio
async def test_analysis_repository_round_trips_persistent_contract():
    repository = InMemoryAnalysisRepository()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)
    analysis = CodebaseAnalysisResult(
        id=uuid4(),
        workspace_id=workspace_id,
        summary="summary",
        architecture_overview="overview",
        dependency_graph=DependencyGraph(),
        started_at=now,
        completed_at=now,
        created_at=now,
        indexed_files=[],
    )
    await repository.save(analysis)
    assert (await repository.get_latest(workspace_id)).id == analysis.id
