#!/usr/bin/env python3
"""Read-only inspection of source data; write a separated, reproducible pilot pack."""
import argparse, collections, gzip, hashlib, json, math, re, subprocess, tarfile
from pathlib import Path, PurePosixPath

PILOT = {
 'requests_7315': '明确复现；URL 路径语义；两行修改',
 'requests_7502': '短描述；动态属性与协议检测',
 'requests_6629': '详细根因提示；异常序列化与继承',
 'rich_3471': '描述依赖外链；文本控制字符',
 'rich_3480': '描述依赖外链；自引用与无限循环',
 'rich_3063': '描述依赖外链；转义边界',
 'rich_4006': '描述依赖外链；Unicode 零宽字符',
 'fastapi_15589': '模板噪声；请求头别名与输入验证',
 'fastapi_14786': '描述直接给出修复；适合作为提示上限样本',
 'fastapi_14448': '多文件；装饰器与同步异步调用',
 'fastapi_15661': '新增文件；发布脚本；规格不充分',
 'httpx_3672': '唯一 HTTPX 任务；同步异步多文件协议状态',
}
STOP=set('the a an and or of to in for is are be by with on from as this that it not fix fixes pr pull request description changes test tests code github com please'.split())

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def dump(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def jsonl(p,rows):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
def paths(patch):
 return list(dict.fromkeys(l[6:].split('\t')[0] for l in patch.splitlines() if l.startswith('+++ b/')))
def touched(patch):
 return list(dict.fromkeys(l[6:].split('\t')[0] for l in patch.splitlines() if l.startswith(('+++ b/','--- a/'))))
def toks(s):
 s=re.sub(r'([a-z])([A-Z])',r'\1 \2',s)
 return [w for w in re.findall(r'[a-zA-Z][a-zA-Z0-9]*',s.lower()) if w not in STOP and len(w)>1]
def clean(s):
 s=re.sub(r'<!--.*?-->','',s,flags=re.S);s=re.split(r'## (?:AI Disclaimer|Checklist)',s)[0]
 return s.strip()
def split(repo):
 return 'holdout_requests' if repo=='psf/requests' else 'ood_httpx' if repo=='encode/httpx' else 'dev'
def safe_name(s):
 p=PurePosixPath(s)
 if p.is_absolute() or '..' in p.parts: raise ValueError(s)
 return p.as_posix().removeprefix('./')
def check_patch(root,patch,work):
 p=work/'candidate.patch';p.write_text(patch.rstrip('\n')+'\n')
 r=subprocess.run(['git','apply','--check',str(p)],cwd=root,text=True,capture_output=True)
 return {'ok':r.returncode==0,'stderr':r.stderr.strip()[:1500]}
def retrieve(source,query):
 q=collections.Counter(toks(query)); docs=[]; df=collections.Counter()
 for p,b in source.items():
  if not p.endswith('.py'): continue
  # Deliberate no-label baseline: every Python file in the snapshot is eligible.
  text=b.decode('utf8','replace'); c=collections.Counter(toks(p+' '+text)); df.update(c.keys());docs.append((p,text,c,sum(c.values())))
 avg=sum(d[3] for d in docs)/max(len(docs),1); ranked=[]
 for p,text,c,n in docs:
  score=sum(math.log(1+(len(docs)-df[w]+.5)/(df[w]+.5))*c[w]*2.5/(c[w]+1.5*(.25+.75*n/max(avg,1))) for w in q if c[w])
  score+=sum(2 for w in set(toks(p)) if w in q)
  ranked.append((score,p,text))
 ranked.sort(key=lambda x:(-x[0],x[1])); out=[]
 for score,p,text in ranked[:10]:
  lines=text.splitlines();scores=[len(set(toks(l))&q.keys()) for l in lines]
  # Best 100-line window using only the issue query, never gold patch offsets.
  width=100;sums=[sum(scores[:width])]
  for i in range(1,max(1,len(lines)-width+1)):sums.append(sums[-1]-scores[i-1]+scores[i+width-1])
  start=max(range(len(sums)),key=sums.__getitem__) if sums else 0
  out.append({'path':p,'score':round(score,4),'start_line':start+1,'end_line':min(len(lines),start+width),'text':'\n'.join(lines[start:start+width])})
 return out,len(docs)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--work',type=Path,required=True);a=ap.parse_args()
 src=a.source.resolve();out=a.output.resolve();work=a.work.resolve();work.mkdir(parents=True,exist_ok=True)
 rows=[json.loads(l) for l in (src/'data/tasks.jsonl').read_text().splitlines() if l.strip()]
 assert len({r['instance_id'] for r in rows})==len(rows)
 inventory=[]; labels=[];agents=[];aliases=[];file_rows=[]
 for d in ['snapshots','graphs','embeddings']:
  for p in sorted((src/'data'/d).iterdir()):
   if p.is_file():file_rows.append({'path':str(p.relative_to(src)),'bytes':p.stat().st_size,'sha256':sha(p) if d!='snapshots' else None})
 hashes={r['path']:r['sha256'] for r in file_rows}
 for r in rows:
  id=r['instance_id'];short=r['repo'].split('/')[-1];commit=r['base_commit'];p=r['patch'];ls=p.splitlines(); st=r['problem_statement']; files=paths(p)
  alias={}
  for d,ext in [('graphs','.json'),('embeddings','.npz')]:
   ps=[f'data/{d}/{id}{ext}',f'data/{d}/{short}_{commit}{ext}'];hs=[hashes.get(x) for x in ps]
   alias[d]={'paths':ps,'all_present':all((src/x).is_file() for x in ps),'same_sha256':len(set(hs))==1 and hs[0] is not None}
  aliases.append({'instance_id':id,**alias})
  rec={'instance_id':id,'repo':r['repo'],'base_commit':commit,'split':split(r['repo']),'created_at':r['created_at'],'title':st.splitlines()[0],'statement_chars':len(st),'clean_statement_chars':len(clean(st)),'hints_chars':len(r.get('hints_text','')),'patch_files':files,'test_files':paths(r['test_patch']),'added_lines':sum(l.startswith('+') and not l.startswith('+++') for l in ls),'deleted_lines':sum(l.startswith('-') and not l.startswith('---') for l in ls),'has_html_template':bool(re.search(r'<!--',st)),'has_external_url':bool(re.search(r'https?://',st)),'pilot':id in PILOT,'pilot_reason':PILOT.get(id),'snapshot':str(src/'data/snapshots'/f'{id}.tgz')}
  rec['changed_lines']=rec['added_lines']+rec['deleted_lines'];inventory.append(rec)
  agents.append({k:r[k] for k in ['instance_id','repo','base_commit','problem_statement','hints_text']})
  labels.append({'instance_id':id,'reference_patch':p,'test_patch':r['test_patch'],'reference_paths':files,'test_paths':paths(r['test_patch'])})
 jsonl(out/'agent/tasks_all.jsonl',agents);jsonl(out/'agent/tasks_pilot.jsonl',[r for r in agents if r['instance_id'] in PILOT]);jsonl(out/'evaluator/labels_all.jsonl',labels);jsonl(out/'evaluator/task_inventory.jsonl',inventory)
 for group in ['dev','holdout_requests','ood_httpx']:
  jsonl(out/f'agent/tasks_{group}.jsonl',[r for r in agents if split(r['repo'])==group])
 dump(out/'audit/asset_inventory.json',file_rows);dump(out/'audit/graph_aliases.json',aliases)
 summary={'source':str(src),'tasks_sha256':sha(src/'data/tasks.jsonl'),'tasks':len(rows),'repos':dict(collections.Counter(r['repo'] for r in rows)),'splits':dict(collections.Counter(split(r['repo']) for r in rows)),'unique_repo_commits':len({(r['repo'],r['base_commit']) for r in rows}),'nonempty_hints':sum(bool(r.get('hints_text')) for r in rows),'empty_patches':sum(not r['patch'].strip() for r in rows),'empty_test_patches':sum(not r['test_patch'].strip() for r in rows),'short_clean_statements_under_200':sum(len(clean(r['problem_statement']))<200 for r in rows),'html_templates':sum('<!--' in r['problem_statement'] for r in rows),'asset_counts':dict(collections.Counter(x['path'].split('/')[1] for x in file_rows)),'asset_bytes':{d:sum(x['bytes'] for x in file_rows if x['path'].split('/')[1]==d) for d in ['snapshots','graphs','embeddings']},'all_graph_aliases_identical':all(x['graphs']['same_sha256'] for x in aliases),'all_embedding_aliases_identical':all(x['embeddings']['same_sha256'] for x in aliases)}
 dump(out/'audit/summary.json',summary)
 scans=[];retrieval=[];metrics=[];oracles=[]
 for r in rows:
  id=r['instance_id']
  if id not in PILOT:continue
  print('Scanning',id,flush=True);snap=src/'data/snapshots'/f'{id}.tgz'; needed=set(touched(r['patch'])+touched(r['test_patch'])); source={};gitmeta={};counts=collections.Counter();links=[]
  with tarfile.open(snap,'r|gz') as tf:
   for m in tf:
    n=safe_name(m.name)
    if m.isfile():
     bucket='git' if n.startswith('.git/') else 'working_tree';counts[bucket+'_files']+=1;counts[bucket+'_bytes']+=m.size
     if n in ['.git/HEAD','.git/packed-refs','.git/shallow'] or n.startswith('.git/refs/'):
      if m.size<100000:gitmeta[n]=tf.extractfile(m).read().decode('utf8','replace')
     if not n.startswith('.git/') and (n.endswith('.py') or n in needed or n in ['pyproject.toml','setup.cfg','setup.py','requirements.txt']):source[n]=tf.extractfile(m).read()
    elif m.issym() or m.islnk():links.append({'path':n,'target':m.linkname,'type':'symlink' if m.issym() else 'hardlink'})
  casework=work/id; casework.mkdir(exist_ok=True);checkroot=casework/'patch_check';checkroot.mkdir(exist_ok=True)
  for n,b in source.items():
   if n in needed:
    p=checkroot/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  checks={k:check_patch(checkroot,r[k],casework) for k in ['patch','test_patch']}
  for d in ['.git']:assert not (checkroot/d).exists()
  ranked,ndocs=retrieve(source,clean(r['problem_statement'])); targets=paths(r['patch']); existing=[p for p in targets if p in source]; unseen=[p for p in targets if p not in source]
  met={'instance_id':id,'split':split(r['repo']),'python_candidates':ndocs,'reference_paths':targets,'existing_reference_paths':existing,'new_reference_paths':unseen,'top10_paths':[x['path'] for x in ranked]}
  for k in [1,3,5,10]:
   found=set(met['top10_paths'][:k])&set(existing);met[f'hit_at_{k}']=bool(found) if existing else None;met[f'recall_at_{k}']=len(found)/len(existing) if existing else None
  metrics.append(met); retrieval.append({'instance_id':id,'repo':r['repo'],'problem_statement':r['problem_statement'],'hints_text':r.get('hints_text',''),'retrieval_method':'BM25-like file rank + issue-only best 100-line window; no reference labels','contexts':ranked[:5]})
  context=[]
  for p in targets:
   if p in source:context.append({'path':p,'text':source[p].decode('utf8','replace')})
   else:context.append({'path':p,'text':None,'note':'reference modifies a path absent from base snapshot'})
  oracles.append({'instance_id':id,'label_assisted':True,'use':'oracle localization diagnostic only; never include in normal model evaluation','problem_statement':r['problem_statement'],'contexts':context})
  head=gitmeta.get('.git/HEAD','').strip();resolved=gitmeta.get(head.removeprefix('ref: '),'').strip() if head.startswith('ref: ') else head
  if head.startswith('ref: '):resolved=gitmeta.get('.git/'+head[5:],'').strip()
  scans.append({'instance_id':id,'snapshot_sha256':sha(snap),'compressed_bytes':snap.stat().st_size,**counts,'links':links,'git_metadata':gitmeta,'git_head_resolved':resolved,'task_base_commit':r['base_commit'],'head_matches_task_base_commit':resolved==r['base_commit'],'patch_apply_check':checks,'new_reference_paths':unseen})
  if id in ['requests_7315','rich_3063','fastapi_14786']:
   smoke=casework/'smoke_source';smoke.mkdir(exist_ok=True)
   for n,b in source.items():
    if n.startswith(('src/requests/','rich/','fastapi/','tests/')) or n in ['pyproject.toml','setup.cfg','setup.py']:
     p=smoke/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  dump(out/'audit/pilot_snapshot_checks.json',scans)
 jsonl(out/'agent/pilot_retrieved_contexts.jsonl',retrieval);jsonl(out/'evaluator/oracle_file_contexts.jsonl',oracles);jsonl(out/'evaluator/retrieval_baseline.jsonl',metrics)
 dump(out/'audit/pilot_snapshot_checks.json',scans)
 dump(out/'splits.json',{'policy':'repository-disjoint; public labels available, not a blind test; pilot labels inspected in preparation','dev':[r['instance_id'] for r in rows if split(r['repo'])=='dev'],'holdout_requests':[r['instance_id'] for r in rows if split(r['repo'])=='holdout_requests'],'ood_httpx':[r['instance_id'] for r in rows if split(r['repo'])=='ood_httpx'],'pilot':list(PILOT)})
 print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
