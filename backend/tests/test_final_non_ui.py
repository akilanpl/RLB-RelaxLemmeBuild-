"""Command delivery regressions: persisted lifecycle, bounds, cancellation, and TLS."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4
import pytest
from backend.app.services.testing_service import TestExecutorService as Executor
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.models.test import TestExecution as Execution
from backend.app.sandbox.types import SandboxCommand, SandboxExecutionResult
from backend.app.sandbox.daytona_client import DaytonaRuntimeClient
from datetime import datetime,timezone


@pytest.mark.asyncio
async def test_command_running_and_cancelled_evidence_survives_disconnect():
    repo=InMemoryTestingRepository()
    execution=Execution(id=uuid4(),task_id=uuid4(),agent_run_id=uuid4(),created_at=datetime.now(timezone.utc))
    await repo.add_execution(execution)
    started=asyncio.Event()
    class Sandbox:
        async def execute_command_observed(self,sandbox_id,command,on_output):
            await on_output('stdout','safe output\n')
            started.set()
            await asyncio.Event().wait()
    executor=Executor(repo,Sandbox())
    executor._execution_id=execution.id;executor._task_id=execution.task_id;executor._commands=[]
    pending=asyncio.create_task(executor._execute_command('sandbox',SandboxCommand(cmd='test')))
    await started.wait()
    current=(await repo.list_executions(execution.task_id))[0]
    assert current.command_results[0]['status']=='running'
    pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    current=(await repo.list_executions(execution.task_id))[0]
    assert len(current.command_results)==1
    assert current.command_results[0]['status']=='cancelled'
    assert current.command_results[0]['stdout']=='safe output\n'


@pytest.mark.asyncio
async def test_daytona_live_session_runs_once_captures_streams_and_cleans_up():
    complete=asyncio.Event()
    calls=[]
    class Process:
        async def create_session(self,session): calls.append('create')
        async def execute_session_command(self,session,req):
            calls.append('execute');assert req.run_async
            assert 'sh -c' in req.command
            return SimpleNamespace(cmd_id='command')
        async def get_session_command_logs_async(self,session,command,out,err):
            await out('x'*100000);await err('failure details');complete.set()
        async def get_session_command(self,session,command):
            return SimpleNamespace(exit_code=1 if complete.is_set() else None)
        async def delete_session(self,session): calls.append('delete')
    client=DaytonaRuntimeClient(None,None,'test-only-image')
    client.sandboxes['test']=SimpleNamespace(process=Process())
    chunks=[]
    async def output(stream,value): chunks.append((stream,value))
    result=await client.execute_observed('test','exit 1','/workspace',{},1,output)
    assert result.exit_code==1 and not result.timed_out
    assert len(result.stdout)==64000 and result.stderr=='failure details'
    assert calls==['create','execute','delete']
    assert {stream for stream,_ in chunks}=={'stdout','stderr'}


@pytest.mark.asyncio
async def test_command_result_upsert_is_idempotent():
    repo=InMemoryTestingRepository()
    execution=Execution(id=uuid4(),task_id=uuid4(),agent_run_id=uuid4(),created_at=datetime.now(timezone.utc))
    await repo.add_execution(execution)
    for status in ['running','running','success']:
        await repo.add_command_result(execution.id,{'command_id':'same','status':status})
    assert (await repo.list_executions(execution.task_id))[0].command_results==[{'command_id':'same','status':'success'}]


@pytest.mark.asyncio
async def test_provider_request_respects_worker_output_cap():
    from backend.app.ai.gateway import ProviderGateway, AIRequest
    from backend.app.providers.types import CompletionResponse, ChatMessage, ModelUsage
    class Adapter:
        provider_id = 'test'
        async def generate_completion(self, request, credentials):
            assert request.max_tokens == 64
            return CompletionResponse(id='id',model='test',finish_reason='stop',message=ChatMessage(role='assistant',content='ok'),usage=ModelUsage(prompt_tokens=1,completion_tokens=1,total_tokens=2))
    gateway = ProviderGateway(Adapter(),object(),'test',64)
    await gateway.generate(AIRequest(system_prompt='s',user_prompt='u',max_tokens=1000))
    await gateway.generate(AIRequest(system_prompt='s',user_prompt='u'))


@pytest.mark.asyncio
async def test_daytona_stream_failure_never_passes_and_cleans_up():
    cleaned=[]
    class Process:
        async def create_session(self,session): pass
        async def execute_session_command(self,session,request): return SimpleNamespace(cmd_id='command')
        async def get_session_command_logs_async(self,*args): raise ConnectionError('stream disconnected')
        async def get_session_command(self,*args): return SimpleNamespace(exit_code=0)
        async def delete_session(self,session): cleaned.append(session)
    client=DaytonaRuntimeClient(None,None,'test-only-image')
    client.sandboxes['test']=SimpleNamespace(process=Process())
    async def output(*args): pass
    with pytest.raises(ConnectionError):
        await client.execute_observed('test','echo ok','/workspace',{},1,output)
    assert len(cleaned)==1


def test_hosted_database_custom_ca_keeps_verification(monkeypatch):
    import ssl
    from backend.app.db import session
    from backend.app.core.config import Settings
    captured={}
    monkeypatch.setenv('USE_REAL_DATABASE_IN_TESTS','1')
    monkeypatch.setattr(session,'_engine',None)
    monkeypatch.setattr(session,'_sessionmaker',None)
    monkeypatch.setattr(session,'get_settings',lambda:Settings(_env_file=None,ENVIRONMENT='staging',DATABASE_URL='postgresql://local:local@db.example/test'))
    def create(*args,**kwargs): captured.update(kwargs);return object()
    monkeypatch.setattr(session,'create_async_engine',create)
    monkeypatch.setattr(session,'async_sessionmaker',lambda **kwargs:None)
    session.get_engine()
    context=captured['connect_args']['ssl']
    assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
    assert captured['hide_parameters'] is True
