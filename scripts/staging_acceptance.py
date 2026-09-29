"""Explicit opt-in staging checks. Outputs only check names/status, never secrets.

Run the API separately in staging mode, then:
RLB_STAGING_APPROVED=1 ENVIRONMENT=staging DEBUG=false python -m scripts.staging_acceptance
This creates and removes two disposable Auth users/workspaces. No production use.
"""
import asyncio
import io
import json
import os
import secrets
import zipfile
from pathlib import Path
from uuid import UUID, uuid4
import httpx
from dotenv import dotenv_values
from sqlalchemy import text
from backend.app.core.config import get_settings
from backend.app.db.session import get_engine


async def main():
    settings = get_settings()
    if settings.ENVIRONMENT != 'staging' or os.environ.get('RLB_STAGING_APPROVED') != '1':
        raise RuntimeError('Explicit staging-only opt-in required.')
    base = os.environ.get('RLB_STAGING_API_URL','http://127.0.0.1:8001').rstrip('/')
    frontend = dotenv_values('frontend/.env.local')
    if frontend.get('NEXT_PUBLIC_SUPABASE_URL','').rstrip('/') != settings.SUPABASE_URL:
        raise RuntimeError('Frontend and staging Supabase projects must match.')
    public_key = frontend.get('NEXT_PUBLIC_SUPABASE_ANON_KEY') or frontend.get('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY')
    if not public_key: raise RuntimeError('Staging public Auth key required.')
    admin = {'apikey':settings.SUPABASE_SERVICE_ROLE_KEY,'Authorization':'Bearer '+settings.SUPABASE_SERVICE_ROLE_KEY}
    users, workspaces, report = [], [], {}
    engine = get_engine()
    def check(name, condition):
        report[name] = 'passed' if condition else 'failed'
        print(name,report[name],flush=True)
        if not condition: raise RuntimeError(name)
    async with httpx.AsyncClient(timeout=30) as client:
        async def auth(method,path,headers=admin,**kwargs):
            return await client.request(method,settings.SUPABASE_URL+'/auth/v1'+path,headers=headers,**kwargs)
        try:
            config=await auth('GET','/settings',headers={'apikey':public_key})
            check('auth_settings',config.status_code==200)
            report['public_signup'] = 'requires_email_confirmation' if not config.json().get('mailer_autoconfirm') else 'not_exercised'
            for _ in range(2):
                email=f'rlb-acceptance-{uuid4().hex}@example.com'; password=secrets.token_urlsafe(32)
                created=await auth('POST','/admin/users',json={'email':email,'password':password,'email_confirm':True})
                check('admin_provision_user_'+str(len(users)+1),created.status_code in (200,201))
                user={'id':created.json()['id']};users.append(user)
                login=await auth('POST','/token?grant_type=password',headers={'apikey':public_key},json={'email':email,'password':password})
                check('password_login_'+str(len(users)),login.status_code==200)
                refreshed=await auth('POST','/token?grant_type=refresh_token',headers={'apikey':public_key},json={'refresh_token':login.json()['refresh_token']})
                check('session_refresh_'+str(len(users)),refreshed.status_code==200)
                user['headers']={'Authorization':'Bearer '+refreshed.json()['access_token']}
                result=await client.post(base+'/api/v1/workspaces',headers=user['headers'],data={'name':'Disposable acceptance'})
                check('api_workspace_'+str(len(users)),result.status_code==201)
                workspace=result.json();workspaces.append(workspace)
                archive=io.BytesIO()
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('app.py','def add(a,b): return a+b\n')
                    z.writestr('tests/test_app.py','from app import add\ndef test_add(): assert add(2,3)==5\n')
                result=await client.post(base+f"/api/v1/workspaces/{workspace['id']}/import/zip",headers=user['headers'],files={'file':('fixture.zip',archive.getvalue(),'application/zip')})
                check('zip_storage_import_'+str(len(users)),result.status_code==200)
                workspace.update(result.json())
                result=await client.post(base+'/api/v1/tasks',headers=user['headers'],json={'workspace_id':workspace['id'],'title':'Acceptance','objective':'Add subtract(a,b), preserve add.'})
                check('durable_task_create_'+str(len(users)),result.status_code==201)
                user['task']=result.json()
            gate = os.environ.get('RLB_STAGING_RESTART_GATE')
            if gate:
                Path(gate+'.ready').write_text('ready')
                async with asyncio.timeout(120):
                    while not Path(gate+'.continue').exists(): await asyncio.sleep(.5)
                response = await client.get(base+'/api/v1/tasks/'+users[0]['task']['id'], headers=users[0]['headers'])
                check('api_restart_state_and_session',response.status_code==200 and response.json()['id']==users[0]['task']['id'])
            a,b=users
            for suffix in ['', '/events','/history','/agent-runs','/plans','/test-plans','/test-executions','/code-proposals','/permissions']:
                result=await client.get(base+'/api/v1/tasks/'+a['task']['id']+suffix,headers=b['headers'])
                check('cross_user_task'+(suffix or '/record'),result.status_code in (403,404))
            for suffix in ['', '/files','/files/content?path=app.py','/analysis']:
                result=await client.get(base+'/api/v1/workspaces/'+workspaces[0]['id']+suffix,headers=b['headers'])
                check('cross_user_workspace'+(suffix or '/record'),result.status_code in (403,404))
            result=await client.post(base+'/api/v1/tasks/'+a['task']['id']+'/approvals',headers=b['headers'],json={'approval_type':'plan','status':'approved'})
            check('cross_user_approval',result.status_code in (403,404))
            for resource in ['workspaces','tasks','task_events','files','agent_runs','test_executions','code_proposals','loadouts','credentials']:
                response=await client.get(settings.SUPABASE_URL+'/rest/v1/'+resource,headers={'apikey':public_key,**b['headers']},params={'select':'*','limit':'100'})
                if response.status_code==200:
                    rows=response.json()
                    check('rls_'+resource,all(str(a['id']) not in json.dumps(row) and str(workspaces[0]['id']) not in json.dumps(row) and str(a['task']['id']) not in json.dumps(row) for row in rows))
                else: check('rls_'+resource,response.status_code in (401,403))
            artifact=workspaces[0]['canonical_root_path']+'/app.py'
            response=await client.get(settings.SUPABASE_URL+'/storage/v1/object/authenticated/'+settings.SUPABASE_STORAGE_BUCKET+'/'+artifact,headers={'apikey':public_key,**b['headers']})
            check('private_artifact_isolation',response.status_code in (400,401,403,404))
            # Real pgmq claim/heartbeat/duplicate fence/reclaim on an isolated queue.
            from backend.app.services.supabase_queue_client import SupabaseQueueClient
            queue_name='rlb_acceptance_'+uuid4().hex
            first,second=SupabaseQueueClient(engine,1),SupabaseQueueClient(engine,1)
            async with engine.begin() as conn: await conn.execute(text('SELECT pgmq.create(:name)'),{'name':queue_name})
            try:
                payload={'task_id':a['task']['id'],'task_version':1}
                await first.send(queue_name,payload);delivery=await first.claim(queue_name,'initial')
                await first.extend(queue_name,delivery['receipt'],1)
                await first.send(queue_name,payload)
                check('queue_duplicate_fenced',await second.claim(queue_name,'duplicate') is None)
                await first.close()
                # A competing read may defer the original by five seconds. Drain
                # the duplicate and wait for the original visibility deadline.
                recovered = None
                async with asyncio.timeout(20):
                    while recovered is None:
                        candidate = await second.claim(queue_name,'restarted')
                        if candidate and candidate['receipt'] == delivery['receipt']:
                            recovered = candidate
                        elif candidate:
                            await second.ack(queue_name,candidate['receipt'])
                        else:
                            await asyncio.sleep(.25)
                check('queue_restart_reclaim',recovered['attempts']==2)
                await second.ack(queue_name,recovered['receipt']);check('queue_ack',True)
            finally:
                await first.close();await second.close()
                async with engine.begin() as conn: await conn.execute(text('SELECT pgmq.drop_queue(:name)'),{'name':queue_name})
            for user in users:
                result=await auth('POST','/logout',headers={'apikey':public_key,**user['headers']})
                check('logout_'+str(users.index(user)+1),result.status_code in (200,204))
            report['api_deployment']='local HTTP process with real staging Auth/Postgres/Queue/Storage; not Railway'
        except Exception as exc:
            report['failure_type']=type(exc).__name__
            print('ACCEPTANCE_STOPPED',type(exc).__name__,flush=True)
        finally:
            # Cleanup only IDs created by this run; preserve existing staging users/data.
            from backend.app.storage.supabase import SupabaseStorageBackend
            from backend.app.storage.supabase_client import SupabaseStorageClient
            storage=SupabaseStorageBackend(SupabaseStorageClient(settings.SUPABASE_URL,settings.SUPABASE_SERVICE_ROLE_KEY),settings.SUPABASE_STORAGE_BUCKET)
            for workspace in workspaces:
                try:
                    await storage.delete_directory('workspaces/'+workspace['id'])
                    async with engine.begin() as conn:
                        await conn.execute(text('DELETE FROM workspaces WHERE id=:id'),{'id':UUID(workspace['id'])})
                except Exception as exc: report['cleanup_workspace_error']=type(exc).__name__
            for user in users:
                try:
                    async with engine.begin() as conn:
                        await conn.execute(text('DELETE FROM users WHERE id=:id'),{'id':UUID(user['id'])})
                    response=await auth('DELETE','/admin/users/'+user['id'])
                    if response.status_code not in (200,204): report['cleanup_auth_error']='HTTP_'+str(response.status_code)
                except Exception as exc: report['cleanup_user_error']=type(exc).__name__
            await engine.dispose()
            Path('/tmp/rlb-staging-acceptance-report.json').write_text(json.dumps(report,indent=2))
            print('REPORT','/tmp/rlb-staging-acceptance-report.json',flush=True)
    return not any(value=='failed' for value in report.values()) and 'failure_type' not in report and not any(key.startswith('cleanup_') for key in report)

if __name__=='__main__':
    raise SystemExit(0 if asyncio.run(main()) else 1)
