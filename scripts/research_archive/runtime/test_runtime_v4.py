import asyncio,gzip,json,os,subprocess,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
os.environ['OPENAI_API_KEY']='local-replay-only'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
from adk_submission import compile_submission
from adk_eval_core.sandbox.base import AdkSandboxCodeExecutor
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
steps=[('run_command',{'command':CMD}),('edit_file',{'filepath':'fastapi/security/utils.py','old_string':'    return scheme, param\n','new_string':'    return scheme, param.strip()\n'}),('run_command',{'command':CMD}),('get_status',{}),('run_command',{'command':'git diff --check'}),('submit_patch',{})]
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
 parent=ROOT/'work/submission_v4/sandboxes';parent.mkdir(exist_ok=True)
 manager=SubprocessManager(base_dir=parent);sid=manager.start();responses=[]
 try:
  ws=manager.sandboxes[sid]['workspace'];
  with gzip.open(ROOT/'work/v3_experiments/corpus/fastapi_14786.json.gz','rt') as f: source_files=json.load(f)
  for name,content in source_files.items():
   dest=ws/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(content)
  steps[:0]=[('load_skill',{'skill_name':'repo-context'}),('run_skill_script',{'skill_name':'repo-context','file_path':'scripts/context.py','args':{'query':'Strip whitespace from Authorization header credentials in get_authorization_scheme_param','root':str(ws)}})]
  for cmd in [['git','init','-q'],['git','config','user.name','Local Check'],['git','config','user.email','local@localhost'],['git','add','.'],['git','-c','core.hooksPath=/dev/null','commit','-qm','baseline'],['git','tag','_swegemma_baseline']]:subprocess.run(cmd,cwd=ws,check=True,capture_output=True)
  ctx=SwegemmaContext(docker_manager=manager,container_id=sid,problem_statement='Strip whitespace from Authorization header credentials.',repo='fastapi/fastapi',budget=EvaluationBudget(time_minutes=4.5,tool_calls=40,turns=64),harness=HarnessLimits(command_timeout_seconds=60))
  models=setup_gemma_model_registry(api_base=f'http://127.0.0.1:{server.server_port}/v1',api_key='local-replay-only',num_retries=0)
  limits,generation=build_submission_limits()
  executor=AdkSandboxCodeExecutor(sandbox=ctx.sandbox,timeout_seconds=60,budget_check_fn=ctx.check_budget)
  agent=compile_submission(submission_dir=ROOT/'outputs/submission_v4',tool_registry=ctx.create_tools(),model_registry=models,limits=limits,generation_constraints=generation,code_executor=executor,script_timeout=60)
  sessions=InMemorySessionService();session=await sessions.create_session(app_name='v4_replay',user_id='local')
  runner=Runner(app=App(name='v4_replay',root_agent=agent),session_service=sessions);ctx.start_agent_session()
  async with asyncio.timeout(60):
   async for e in runner.run_async(user_id='local',session_id=session.id,new_message=types.Content(role='user',parts=[types.Part(text='Fix the Authorization whitespace behavior in /workspace/fastapi/security/utils.py, verify, and submit.')])):
    if e.content:
     for part in e.content.parts or []:
      if part.function_response:responses.append(part.function_response.model_dump(mode='json'))
  patch=ctx.submitted_patch or '';assert 'param.strip()' in patch and ctx.patch_submitted
  (ROOT/'work/submission_v4/replayed.patch').write_text(patch)
  first=requests[0];assert first.get('reasoning_effort') is None,first.keys()
  assert first.get('max_tokens',first.get('max_completion_tokens'))==8192
  toolnames={t['function']['name'] for t in first['tools']};assert {'read_file','edit_file','write_file','run_command','get_status','submit_patch','load_skill','run_skill_script'}<=toolnames
  # Tool output content is evidence: require observed pre-fix failure and post-fix success.
  tooloutputs=[r['response'].get('result',r['response']) for r in responses]
  (ROOT/'work/submission_v4/debug.json').write_text(json.dumps({'responses':responses,'tooloutputs':tooloutputs},indent=2))
  decoded=[json.loads(x) if isinstance(x,str) else x for x in tooloutputs]
  skill_result=decoded[1]
  packet=json.loads(skill_result['stdout']);assert packet['files'][0]['path']=='fastapi/security/utils.py',packet
  assert len(skill_result['stdout'].strip())<=6000
  assert not skill_result.get('error'),skill_result
  assert not list(ws.glob('.adk_exec_*'))
  decoded=decoded[2:]
  assert decoded[0]['details']['exit_code']==1 and 'AssertionError' in decoded[0]['details']['stderr']
  assert decoded[1]['status']=='ok' and decoded[2]['exit_code']==0 and decoded[2]['stdout'].strip()=='3 assertions passed'
  assert decoded[-1]['files_changed']==1 and decoded[-1]['patch_size']>0
  summary={'status':'passed','kind':'scripted model replay, actual ADK Runner + LiteLlm + swegemma tools + SubprocessManager; not Gemma inference','source_task':'fastapi_14786','workspace_scope':'all original Python source files from snapshot; not official full evaluation','context_output_chars':len(skill_result['stdout'].strip()),'context_seconds':packet['seconds'],'context_replaces_initial_read_file_in_this_scripted_replay':True,'skill_result':skill_result,'local_path_note':'SubprocessManager requires an explicit local root in script args; production defaults to /workspace','llm_requests':len(requests),'tool_responses':responses,'effective_request':{k:first.get(k) for k in ['model','temperature','top_p','max_tokens','max_completion_tokens','reasoning_effort','chat_template_kwargs']},'tools':sorted(toolnames),'patch_bytes':len(patch),'charged_tool_calls':ctx.tool_calls_used,'before_failed_after_passed':True}
  (ROOT/'outputs/submission_v4_runtime_check.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
  print('PASS: actual tool round trips, before-fail/after-pass, patch extraction, skill execution and 8192-token forwarding without reasoning_effort. Mock model only.',flush=True)
 finally:
  manager.stop(sid);server.shutdown();server.server_close()
asyncio.run(main())
