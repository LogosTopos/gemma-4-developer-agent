import asyncio,json,os,subprocess,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
os.environ['OPENAI_API_KEY']='local-replay-only'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
from adk_submission import compile_submission
from swegemma.config import build_submission_limits
from swegemma.budget import EvaluationBudget,HarnessLimits
from swegemma.context import SwegemmaContext
from swegemma.sandbox.subprocess import SubprocessManager
from swegemma.models.registry import setup_gemma_model_registry
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'work/pilot/fastapi_14786/smoke_source/fastapi/security/utils.py'
CMD="python3 -c \"import runpy; f=runpy.run_path('fastapi/security/utils.py')['get_authorization_scheme_param']; assert f('Bearer  token ')==('Bearer','token'); assert f('Bearer token')==('Bearer','token'); assert f(None)==('',''); print('3 assertions passed')\""
steps=[('read_file',{'filepath':'fastapi/security/utils.py'}),('run_command',{'command':CMD}),('edit_file',{'filepath':'fastapi/security/utils.py','old_string':'    return scheme, param\n','new_string':'    return scheme, param.strip()\n'}),('run_command',{'command':CMD}),('get_status',{}),('run_command',{'command':'git diff --check'}),('submit_patch',{})]
requests=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));i=len(requests);requests.append(req)
  if i<len(steps):
   name,args=steps[i];msg={'role':'assistant','content':None,'tool_calls':[{'id':f'call_{i}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]};reason='tool_calls'
  else:msg={'role':'assistant','content':'Applied the focused fix and verified the assertions.'};reason='stop'
  body=json.dumps({'id':str(uuid.uuid4()),'object':'chat.completion','created':int(time.time()),'model':req['model'],'choices':[{'index':0,'message':msg,'finish_reason':reason}],'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}).encode()
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
async def main():
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 parent=ROOT/'work/submission_v2/sandboxes';parent.mkdir(exist_ok=True)
 manager=SubprocessManager(base_dir=parent);sid=manager.start();responses=[]
 try:
  ws=manager.sandboxes[sid]['workspace'];manager.copy_to(sid,SOURCE,'/workspace/fastapi/security/utils.py')
  for cmd in [['git','init','-q'],['git','config','user.name','Local Check'],['git','config','user.email','local@localhost'],['git','add','.'],['git','-c','core.hooksPath=/dev/null','commit','-qm','baseline'],['git','tag','_swegemma_baseline']]:subprocess.run(cmd,cwd=ws,check=True,capture_output=True)
  ctx=SwegemmaContext(docker_manager=manager,container_id=sid,problem_statement='Strip whitespace from Authorization header credentials.',repo='fastapi/fastapi',budget=EvaluationBudget(time_minutes=3,tool_calls=24,turns=32),harness=HarnessLimits(command_timeout_seconds=45))
  models=setup_gemma_model_registry(api_base=f'http://127.0.0.1:{server.server_port}/v1',api_key='local-replay-only',num_retries=0)
  limits,generation=build_submission_limits()
  agent=compile_submission(submission_dir=ROOT/'outputs/submission_v2',tool_registry=ctx.create_tools(),model_registry=models,limits=limits,generation_constraints=generation)
  sessions=InMemorySessionService();session=await sessions.create_session(app_name='v2_replay',user_id='local')
  runner=Runner(app=App(name='v2_replay',root_agent=agent),session_service=sessions);ctx.start_agent_session()
  async with asyncio.timeout(60):
   async for e in runner.run_async(user_id='local',session_id=session.id,new_message=types.Content(role='user',parts=[types.Part(text='Fix the Authorization whitespace behavior in /workspace/fastapi/security/utils.py, verify, and submit.')])):
    if e.content:
     for part in e.content.parts or []:
      if part.function_response:responses.append(part.function_response.model_dump(mode='json'))
  patch=ctx.submitted_patch or '';assert 'param.strip()' in patch and ctx.patch_submitted
  (ROOT/'work/submission_v2/replayed.patch').write_text(patch)
  first=requests[0];assert first.get('reasoning_effort')=='low',first.keys()
  assert first.get('max_tokens',first.get('max_completion_tokens'))==3072
  toolnames={t['function']['name'] for t in first['tools']};assert toolnames=={'read_file','edit_file','write_file','run_command','get_status','submit_patch'}
  # Tool output content is evidence: require observed pre-fix failure and post-fix success.
  tooloutputs=[r['response']['result'] for r in responses]
  (ROOT/'work/submission_v2/debug.json').write_text(json.dumps({'responses':responses,'tooloutputs':tooloutputs},indent=2))
  decoded=[json.loads(x) for x in tooloutputs]
  assert decoded[1]['details']['exit_code']==1 and 'AssertionError' in decoded[1]['details']['stderr']
  assert decoded[2]['status']=='ok' and decoded[3]['exit_code']==0 and decoded[3]['stdout'].strip()=='3 assertions passed'
  assert decoded[-1]['files_changed']==1 and decoded[-1]['patch_size']>0
  summary={'status':'passed','kind':'scripted model replay, actual ADK Runner + LiteLlm + swegemma tools + SubprocessManager; not Gemma inference','source_task':'fastapi_14786','workspace_scope':'single original source file; not official full evaluation','llm_requests':len(requests),'tool_responses':responses,'effective_request':{k:first.get(k) for k in ['model','temperature','top_p','max_tokens','max_completion_tokens','reasoning_effort','chat_template_kwargs']},'tools':sorted(toolnames),'patch_bytes':len(patch),'charged_tool_calls':ctx.tool_calls_used,'before_failed_after_passed':True}
  (ROOT/'outputs/submission_v2_runtime_check.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
  print('PASS: actual tool round trips, before-fail/after-pass, patch extraction, low reasoning and 3072-token forwarding. Mock model only.',flush=True)
 finally:
  manager.stop(sid);server.shutdown();server.server_close()
asyncio.run(main())
