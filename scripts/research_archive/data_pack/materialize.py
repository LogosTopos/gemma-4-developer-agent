#!/usr/bin/env python3
"""Create an answer-free repository workspace from a local competition snapshot."""
import argparse,json,os,subprocess,tarfile
from pathlib import Path,PurePosixPath

DEFAULT_SOURCE=Path('/Users/topologyw/Documents/Kaggles/gemma_4')
def materialize(source,task_id,destination):
 pack=Path(__file__).resolve().parent.parent
 tasks={r['instance_id']:r for r in map(json.loads,(pack/'agent/tasks_all.jsonl').read_text().splitlines())}
 if task_id not in tasks:raise ValueError('Unknown task id')
 destination=destination.resolve()
 if destination.exists():raise ValueError('Destination must not exist; existing work is never overwritten')
 archive=source/'data/snapshots'/f'{task_id}.tgz'
 destination.mkdir(parents=True)
 count=0;skipped_git=0
 with tarfile.open(archive,'r|gz') as tf:
  for m in tf:
   p=PurePosixPath(m.name)
   if p.is_absolute() or '..' in p.parts:raise ValueError(f'Unsafe member: {m.name}')
   if '.git' in p.parts:skipped_git+=1;continue
   if m.issym() or m.islnk():
    target=(destination/p.parent/m.linkname) if m.issym() else (destination/m.linkname)
    if not target.resolve().is_relative_to(destination) or '.git' in target.parts:raise ValueError(f'Unsafe link: {m.name}')
   if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):raise ValueError(f'Unsupported tar member: {m.name}')
   tf.extract(m,destination,filter='data');count+=1
 # A fresh baseline avoids exposing archived history and captures new files in diffs.
 env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_TERMINAL_PROMPT':'0'}
 cmds=[['git','init','-q'],['git','config','user.name','Experiment Baseline'],['git','config','user.email','experiment@localhost'],['git','config','core.hooksPath',os.devnull],['git','add','-A'],['git','commit','-qm','snapshot baseline','--allow-empty']]
 for cmd in cmds:subprocess.run(cmd,cwd=destination,env=env,check=True,capture_output=True)
 return {'instance_id':task_id,'workspace':str(destination),'snapshot':str(archive),'members_extracted':count,'git_members_removed':skipped_git,'baseline_policy':'archive working tree, fresh git history; no gold patch or hidden test patch','declared_base_commit':tasks[task_id]['base_commit']}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source-root',type=Path,default=DEFAULT_SOURCE);ap.add_argument('--task-id',required=True);ap.add_argument('--destination',type=Path,required=True);a=ap.parse_args()
 print(json.dumps(materialize(a.source_root,a.task_id,a.destination),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
