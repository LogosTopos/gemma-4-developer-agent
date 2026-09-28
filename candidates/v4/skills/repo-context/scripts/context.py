"""Deterministic repository retrieval; no model, labels, network or source execution."""
import ast,collections,math,re,time,os,json,argparse
from functools import lru_cache
from pathlib import Path
STOP=set('a an the and or of to in for is are be by with on from as this that it not fix fixes fixed pr pull request description changes change test tests code github com please should would could have has had was were been using use used add added new now when then than can will must also all any if else return def class self none true false str int bool typing import bug feature checklist type'.split())
def clean_query(text):
 text=re.sub(r'<!--.*?-->',' ',text,flags=re.S)
 text=re.sub(r'https?://\S+',' ',text)
 # Remove individual template lines, retaining prose after a checklist.
 text='\n'.join(line for line in text.splitlines() if not re.match(r'^\s*(?:[-*]\s*\[[ xX]\]|#{1,6}\s*(?:Checklist|Type of changes|AI Disclaimer)\b)',line))
 return text[:16000]
@lru_cache(maxsize=8192)
def word_parts(raw):
 whole=raw.lower().strip('_');parts=re.sub(r'([a-z])([A-Z])',r'\1 \2',raw).lower().replace('_',' ').split()
 return tuple(w for w in dict.fromkeys([whole]+parts) if len(w)>1 and w not in STOP)
def tokens(text):
 return [w for raw in re.findall(r'[A-Za-z_][A-Za-z_0-9]*',text) for w in word_parts(raw)]
def is_test(path):
 p=Path(path);return any(x in {'test','tests','testing'} for x in p.parts) or p.name.startswith('test_') or p.name.endswith('_test.py') or p.name=='conftest.py'
def build_index(files,deadline=None):
 units=[];file_counts={};defs={};significant={};limited=False
 for path,text in sorted(files.items()):
  if deadline is not None and time.monotonic()>deadline:limited=True;break
  lines=text.splitlines();file_counts[path]=collections.Counter(tokens(text));ranges=[];defs[path]=[];imports=set()
  try:tree=ast.parse(text)
  except (SyntaxError,ValueError,RecursionError):tree=None
  if tree:
   for node in ast.walk(tree):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
     start=node.lineno-1;end=getattr(node,'end_lineno',start+80) or start+80;defs[path].append((node.name,start,end))
     ranges.append((node.name,start,min(end,start+(30 if isinstance(node,ast.ClassDef) else 180))))
  omit=set()
  if tree:
   for node in ast.walk(tree):
    if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
     # Do not erase executable statements sharing the docstring line.
     if not lines[node.lineno-1][:node.col_offset].strip() and not lines[node.end_lineno-1][node.end_col_offset:].strip():
      omit.update(range(node.lineno-1,node.end_lineno))
  significant[path]=sum(bool(line.strip()) and not line.lstrip().startswith(('#','from ','import ','__all__')) for i,line in enumerate(lines) if i not in omit)
  # All module-level constants and function tails are covered; no 100-line blind spot.
  ranges += [('<window>',i,min(len(lines),i+80)) for i in range(0,max(len(lines),1),60)]
  for name,start,end in ranges:
   c=collections.Counter(tokens('\n'.join(lines[start:end])));units.append((path,name,start,end,c,sum(c.values())))
 df=collections.Counter();posts=collections.defaultdict(list)
 for i,u in enumerate(units):
  for w,n in u[4].items():df[w]+=1;posts[w].append((i,n))
 fdf=collections.Counter()
 for c in file_counts.values():fdf.update(c.keys())
 return {'units':units,'df':df,'posts':posts,'avg':sum(u[5] for u in units)/max(len(units),1),'files':file_counts,'fdf':fdf,'favg':sum(sum(c.values()) for c in file_counts.values())/max(len(files),1),'defs':defs,'paths':{p:set(tokens(p)) for p in file_counts},'significant':significant,'limited':limited}
def retrieve_features(index,query):
 query=clean_query(query);q=set(tokens(query));title=next((s.strip() for s in query.splitlines() if s.strip()),'');tw=set(tokens(title))
 ids={s.lower().strip('_') for s in re.findall(r'[A-Za-z_][A-Za-z_0-9]*',query) if '_' in s or any(c.isupper() for c in s[1:])};ids.update(s.lower() for s in re.findall(r'`([A-Za-z_][A-Za-z_0-9]*)`',query))
 units=index['units'];scores=collections.defaultdict(float);N=len(units)
 for w in sorted(q):
  for i,count in index['posts'].get(w,[]):
   scores[i]+=math.log(1+(N-index['df'][w]+.5)/(index['df'][w]+.5))*count*2.2/(count+1.2*(.25+.75*units[i][5]/max(index['avg'],1)))*(1.5 if w in tw else 1)
 best={};unit_scores={}
 for i,u in enumerate(units):
  p,name,start,end,_,_=u;s=scores[i]+3*len(set(tokens(name))&q)+2*len(index['paths'][p]&q)
  if name.lower() in ids:s+=22
  elif name.lower() in tw:s+=9
  if p not in best or s>unit_scores[p]:best[p]=i;unit_scores[p]=s
 file_scores={};exact={};role={};fN=len(index['files'])
 for p,c in index['files'].items():
  length=sum(c.values());file_scores[p]=sum(math.log(1+(fN-index['fdf'][w]+.5)/(index['fdf'][w]+.5))*c[w]*2.2/(c[w]+1.2*(.25+.75*length/max(index['favg'],1)))*(1.5 if w in tw else 1) for w in q if c[w])
  names={name.lower() for name,_,_ in index['defs'][p]}
  exact[p]=len(names&ids)*2+len(index['paths'][p]&q)*.2
  for pathstring in re.findall(r'[\w./-]+\.py',query):
   if p==pathstring or p.endswith('/'+pathstring):exact[p]+=12
  # A modest preference for implementation over examples/tooling, unless requested.
  auxiliary=bool(set(Path(p).parts)&{'examples','docs_src','docs','scripts','benchmarks'})
  wanted=bool(q&{'example','examples','documentation','docs','tutorial','tutorials','script','scripts','release','benchmark'})
  role[p]=.8 if auxiliary and not wanted else 1.
 return {'unit':unit_scores,'file':file_scores,'exact':exact,'role':role,'best':best,'query':query}
CONFIG={'file':.5,'exact':.2,'test_graph':0,'role':True,'prior':True}
def rank_scores(index,features,config=CONFIG):
 prod=[p for p in index['files'] if not is_test(p)];tests=[p for p in index['files'] if is_test(p)]
 def rankmap(scores,paths):return {p:i+1 for i,p in enumerate(sorted(paths,key=lambda p:(-scores.get(p,0),p))) if scores.get(p,0)>0}
 ur=rankmap(features['unit'],prod);fr=rankmap(features['file'],prod);er=rankmap(features['exact'],prod)
 k=config.get('rrf_k',10);fw=config.get('file',.5);ew=config.get('exact',.2)
 score={p:1/(k+ur[p]) if p in ur else 0 for p in prod}
 for p in prod:
  score[p]+=fw/(k+fr[p]) if p in fr else 0
  score[p]+=ew/(k+er[p]) if p in er else 0
  if config.get('role'):score[p]*=features['role'][p]
 testseeds=sorted(tests,key=lambda p:(-features['unit'][p],p))[:2]
 q=set(tokens(features['query']))
 for p in score:
  parts=set(Path(p).parts);prior=1.
  if parts&{'scripts','benchmarks','docs'} and not q&{'script','scripts','release','benchmark','docs','documentation'}:prior=.35
  elif parts&{'examples','docs_src'} and not q&{'example','examples','tutorial','tutorials','docs','documentation'}:prior=.65
  if index['significant'][p]<3:prior*=.5
  score[p]*=prior
 return sorted((p for p in prod if score[p]>0),key=lambda p:(-score[p],p)),score,[p for p in testseeds if features['unit'][p]>0]

SKIP={'.git','.hg','.svn','.venv','venv','env','__pycache__','node_modules','build','dist','.tox'}
def read_workspace(root,deadline):
 root=Path(root).resolve();files={};size=0;limited=False
 for base,dirs,names in os.walk(root,followlinks=False):
  dirs[:]=sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and not (Path(base)/d).is_symlink())
  for name in sorted(names):
   if not name.endswith('.py') or name.startswith('.adk_exec_'):continue
   if time.monotonic()>deadline or len(files)>=6000 or size>12_000_000:return files,True
   p=Path(base)/name
   try:
    if p.is_symlink() or p.stat().st_size>2_000_000:limited=True;continue
    text=p.read_text(encoding='utf8',errors='replace');files[p.relative_to(root).as_posix()]=text;size+=len(text)
   except OSError:limited=True
 return files,limited

def make_packet(files,index,features,paths,testpaths):
 q=set(tokens(features['query']));items=[]
 for p in paths[:5]:
  lines=files[p].splitlines();u=index['units'][features['best'][p]];start,end=u[2],u[3]
  best=max(range(start,max(start+1,end)),key=lambda i:len(set(tokens(lines[i] if i<len(lines) else ''))&q),default=start)
  lo=max(start,best-4);hi=min(len(lines),lo+16)
  text='\n'.join(f'{i+1}: {lines[i]}' for i in range(lo,hi))
  item={'path':p,'line':lo+1,'code':text[:900]+('\n[excerpt cut; read_file for remaining lines]' if len(text)>900 else '')}
  if u[1]!='<window>':item['symbol']=u[1]
  items.append(item)
 result={'files':items,'tests':testpaths[:2],'partial':index['limited']}
 # Bound model-visible context; retain candidate identities and line numbers.
 while len(json.dumps(result,ensure_ascii=False))>6000:
  candidate=max(items,key=lambda x:len(x['code']),default=None)
  if not candidate or len(candidate['code'])<100:break
  candidate['code']=candidate['code'][:max(80,len(candidate['code'])//2)]+'\n[excerpt cut]'
 return result

def prepare(files,query,deadline=None):
 index=build_index(files,deadline);features=retrieve_features(index,query);paths,_,tests=rank_scores(index,features)
 return make_packet(files,index,features,paths,tests),paths

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--query',required=True);parser.add_argument('--root',default='/workspace');a=parser.parse_args();start=time.monotonic()
 try:
  files,limited=read_workspace(a.root,start+3)
  packet,_=prepare(files,a.query,deadline=start+8);packet['partial']|=limited
  if not files:packet['note']='No readable Python source found. Inspect the supplied repository tree.'
 except (OSError,ValueError,RecursionError) as exc:
  packet={'files':[],'tests':[],'partial':True,'note':'Source scan incomplete: '+type(exc).__name__}
 packet['seconds']=round(time.monotonic()-start,3)
 print(json.dumps(packet,ensure_ascii=False))
if __name__=='__main__':main()
