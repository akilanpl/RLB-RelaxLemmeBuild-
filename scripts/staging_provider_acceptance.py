"""Opt-in real planner/coder/promotion/test-architect checks; never fake sandbox success.

Requires RLB_STAGING_APPROVED=1, ENVIRONMENT=staging and an explicit API model ID
in RLB_STAGING_MODEL. Uses an existing encrypted Gemini credential, with disposable
worker/loadout/workspace records; leaves existing configuration unchanged.
"""
import asyncio
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import text
from backend.app.core.config import get_settings
from backend.app.db.session import get_engine
from backend.app.services.runtime import build_runtime
from backend.app.models.agent import AgentRole, ExecutionStatus
from backend.app.models.task import ActorType
from backend.app.models.provider import Worker, Loadout, AgentWorkerMapping
from backend.app.workflow.states import WorkflowState as State
from backend.app.services.testing_service import TestArchitectService
from backend.app.services.planner_context import PlannerContextBuilder


async def main():
    if get_settings().ENVIRONMENT != 'staging' or os.environ.get('RLB_STAGING_APPROVED') != '1':
        raise RuntimeError('Explicit staging-only opt-in required.')
    model = os.environ['RLB_STAGING_MODEL']
    runtime = build_runtime('api')
    await runtime.start()
    resolver, workflow = runtime.agents.resolver, runtime.workflow
    engine = get_engine()
    owner = next(user for user, provider in resolver.credentials if provider == 'gemini')
    now = datetime.now(timezone.utc)
    worker_id, loadout_id = 'acceptance-'+uuid4().hex, uuid4()
    workspace = None
    report = {}
    def passed(name):
        report[name]='passed';print(name,'passed',flush=True)
    try:
        worker=Worker(id=worker_id,provider_id='gemini',model_name=model,context_window_tokens=32000,max_output_tokens=4096,created_at=now)
        loadout=Loadout(id=loadout_id,user_id=owner,name='Disposable acceptance',mappings={role:AgentWorkerMapping(primary_worker_id=worker_id) for role in [AgentRole.PLANNER,AgentRole.CODER,AgentRole.TEST_ARCHITECT,AgentRole.REVIEWER]},created_at=now,updated_at=now)
        await resolver.repository.save_worker(worker.model_dump())
        await resolver.repository.save_loadout(loadout.model_dump())
        workspace=await runtime.workspace.create_workspace(owner,'Disposable provider acceptance')
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('app.py','def add(a,b): return a+b\n')
            z.writestr('tests/test_app.py','from app import add\ndef test_add(): assert add(2,3)==5\n')
        workspace=await runtime.workspace.import_project_into_empty_workspace(workspace.id,owner,zip_bytes=archive.getvalue())
        await resolver.repository.switch_loadout(owner,workspace.id,loadout_id)
        await resolver.hydrate()
        task=await workflow.create_task(workspace,owner,'Staging provider acceptance','Add subtract(a,b) to app.py. Preserve add. Keep changes tiny and dependency-free. Return strict JSON without markdown fences.')
        await runtime.analysis.analyze_workspace(workspace.id,owner)
        await workflow.transition(task.id,State.PLANNING,ActorType.SYSTEM,None,'Acceptance planning')
        plan=await runtime.agents.planner.execute(task.id,owner)
        passed('real_planner')
        await workflow.transition(task.id,State.PLAN_REVIEW,ActorType.SYSTEM,None,'Plan ready')
        results=await asyncio.gather(*[workflow.record_approval(task.id,owner,'plan','approved',None,defer_setup=True) for _ in range(2)],return_exceptions=True)
        assert sum(not isinstance(result,BaseException) for result in results)==1
        passed('concurrent_plan_approval')
        task=await workflow.get_task(task.id,owner)
        await workflow._attach_plan_staging(task,owner)
        await workflow.transition(task.id,State.CODING,ActorType.SYSTEM,None,'Staging ready')
        proposal=await runtime.agents.coder.execute(task.id,owner)
        passed('real_coder')
        await workflow.transition(task.id,State.CODE_REVIEW,ActorType.SYSTEM,None,'Code review')
        await runtime.agents.coder.request_promotion(proposal.id,owner)
        await runtime.agents.coder.approve_and_apply(proposal.id,owner,already_approved=True)
        passed('immutable_cloud_promotion')
        task=await workflow.get_task(task.id,owner)
        resolved=resolver.resolve(owner,workspace.id,task.id,AgentRole.TEST_ARCHITECT.value)
        run=await workflow.create_agent_run(task.id,owner,AgentRole.TEST_ARCHITECT,**resolved.run_metadata())
        context=await PlannerContextBuilder(runtime.workspace).build(task)
        context['approved_plans']=[plan.model_dump(mode='json')]
        test_plan=await TestArchitectService(runtime.testing,resolved.gateway).create_plan(task.id,run.id,task.objective,context=context)
        assert test_plan.test_cases
        await workflow.update_agent_run(run.id,ExecutionStatus.SUCCESS)
        passed('real_test_architect')
        report['sandbox_execution']='blocked_missing_trusted_image'
        report['repair_and_reviewer']='not_run_without_real_test_evidence'
        async with engine.connect() as conn:
            rows=(await conn.execute(text('SELECT evidence FROM provider_calls WHERE task_id=:id'),{'id':task.id})).mappings().all()
            report['provider_attempts']=len(rows)
            report['token_accounting']=all(row['evidence'].get('prompt_tokens') is not None and row['evidence'].get('completion_tokens') is not None for row in rows)
    except Exception as exc:
        report['failure_type']=type(exc).__name__
        chain=[]
        current=exc
        while current:
            chain.append(type(current).__name__)
            if getattr(current,'response',None) is not None:
                report['provider_http_status']=current.response.status_code
                print('PROVIDER_HTTP_STATUS',current.response.status_code,flush=True)
            if hasattr(current,'errors'):
                report['validation_errors']=[{'type':item['type'],'loc':item['loc']} for item in current.errors(include_input=False)]
            current=current.__cause__
        report['error_chain']=chain
        print('ERROR_CHAIN',chain,flush=True)
        print('PROVIDER_ACCEPTANCE_STOPPED',type(exc).__name__,flush=True)
    finally:
        if workspace:
            try:
                await runtime.workspace.storage.delete_directory('workspaces/'+str(workspace.id))
                async with engine.begin() as conn:
                    await conn.execute(text('DELETE FROM workspaces WHERE id=:id'),{'id':workspace.id})
            except Exception as exc: report['cleanup_error']=type(exc).__name__
        async with engine.begin() as conn:
            await conn.execute(text('DELETE FROM loadouts WHERE id=:id'),{'id':loadout_id})
            await conn.execute(text('DELETE FROM workers WHERE id=:id'),{'id':worker_id})
        await runtime.close();await engine.dispose()
        Path('/tmp/rlb-provider-acceptance-report.json').write_text(json.dumps(report,indent=2))
        print('REPORT /tmp/rlb-provider-acceptance-report.json',flush=True)
    return 'failure_type' not in report and 'cleanup_error' not in report

if __name__=='__main__':
    raise SystemExit(0 if asyncio.run(main()) else 1)
