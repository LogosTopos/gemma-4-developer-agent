#!/usr/bin/env python3
"""Local reference sanity checks, NOT competition resolution-rate evaluation."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from materialize import materialize,DEFAULT_SOURCE

FASTAPI_TEST='''import runpy
f=runpy.run_path("fastapi/security/utils.py")["get_authorization_scheme_param"]
for header,expected in [("Bearer  token ",("Bearer","token")),("Bearer token",("Bearer","token")),(None,("","")),("",("",""))]:
    actual=f(header)
    assert actual==expected,(header,actual,expected)
print("4 inline assertions passed")
'''
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source-root',type=Path,default=DEFAULT_SOURCE);ap.add_argument('--work',type=Path,required=True);a=ap.parse_args()
 pack=Path(__file__).resolve().parent.parent;work=a.work.resolve();work.mkdir(parents=True,exist_ok=True)
 labels={r['instance_id']:r for r in map(json.loads,(pack/'evaluator/labels_all.jsonl').read_text().splitlines())}
 result=[]
 for id,target in [('requests_7315','tests/test_adapters.py'),('rich_3063','tests/test_markup.py'),('fastapi_14786',None)]:
  case=work/id;info=materialize(a.source_root,id,case)
  env={**os.environ,'PYTHONPATH':str(case/'src') if id.startswith('requests') else str(case),'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONNOUSERSITE':'1'}
  label=labels[id]
  if target:
   tp=work/f'{id}.test.patch';tp.write_text(label['test_patch'].rstrip('\n')+'\n');subprocess.run(['git','apply',str(tp)],cwd=case,check=True,capture_output=True)
   cmd=[sys.executable,'-m','pytest','--noconftest','-c',os.devnull,'-o','addopts=','--rootdir',str(case),'-p','no:cacheprovider',target,'-q']
  else:cmd=[sys.executable,'-c',FASTAPI_TEST]
  entry={'instance_id':id,'materialization':info,'kind':'public test_patch target file; without repository conftest/plugins' if target else '4 direct function assertions; not the full public test_patch','command':cmd,'python':sys.version}
  for phase in ['before','after']:
   if phase=='after':
    pp=work/f'{id}.reference.patch';pp.write_text(label['reference_patch'].rstrip('\n')+'\n');subprocess.run(['git','apply',str(pp)],cwd=case,check=True,capture_output=True)
   try:
    p=subprocess.run(cmd,cwd=case,env=env,text=True,capture_output=True,timeout=60)
    log=p.stdout+p.stderr;entry[phase]={'exit_code':p.returncode,'output':log[-16000:]}
   except subprocess.TimeoutExpired:entry[phase]={'exit_code':None,'output':'timeout after 60s'}
  entry['fail_to_pass_observed']=entry['before']['exit_code']==1 and entry['after']['exit_code']==0
  result.append(entry);print(id,entry['before']['exit_code'],'->',entry['after']['exit_code'],flush=True)
 p=pack/'audit/smoke_results.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 if not all(r['fail_to_pass_observed'] for r in result):raise SystemExit(1)
if __name__=='__main__':main()
