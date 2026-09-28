"""Deterministic repository retrieval; no model, labels, network or source execution."""
import ast,collections,math,re,time
from pathlib import Path
STOP=set('a an the and or of to in for is are be by with on from as this that it not fix fixes fixed pr pull request description changes change test tests code github com please should would could have has had was were been using use used add added new now when then than can will must also all any if else return def class self none true false str int bool typing import bug feature checklist type'.split())
def clean_query(text):
 text=re.sub(r'<!--.*?-->',' ',text,flags=re.S)
 text=re.sub(r'https?://\S+',' ',text)
 # Remove individual template lines, retaining prose after a checklist.
 text='\n'.join(line for line in text.splitlines() if not re.match(r'^\s*(?:[-*]\s*\[[ xX]\]|#{1,6}\s*(?:Checklist|Type of changes|AI Disclaimer)\b)',line))
 return text[:16000]
def tokens(text):
 out=[]
 for raw in re.findall(r'[A-Za-z_][A-Za-z_0-9]*',text):
  whole=raw.lower().strip('_');parts=re.sub(r'([a-z])([A-Z])',r'\1 \2',raw).lower().replace('_',' ').split()
  for word in dict.fromkeys([whole]+parts):
   if len(word)>1 and word not in STOP:out.append(word)
 return out
def is_test(path):
 p=Path(path);return any(x in {'test','tests','testing'} for x in p.parts) or p.name.startswith('test_') or p.name.endswith('_test.py') or p.name=='conftest.py'
def module_map(files):
 result={}
 for p in files:
  m=p[:-3].replace('/','.');m=m.removeprefix('src.');result[m]=p
  if m.endswith('.__init__'):result[m[:-9]]=p
 return result
def build_index(files):
 units=[];file_counts={};defs={};edges={};modules=module_map(files)
 for path,text in sorted(files.items()):
  lines=text.splitlines();file_counts[path]=collections.Counter(tokens(text));ranges=[];defs[path]=[];imports=set()
  try:tree=ast.parse(text)
  except (SyntaxError,ValueError,RecursionError):tree=None
  if tree:
   for node in ast.walk(tree):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
     start=node.lineno-1;end=getattr(node,'end_lineno',start+80) or start+80;defs[path].append((node.name,start,end))
     ranges.append((node.name,start,min(end,start+(30 if isinstance(node,ast.ClassDef) else 180))))
    elif isinstance(node,ast.ImportFrom):
     package=path[:-3].replace('/','.').removeprefix('src.').split('.')[:-1]
     if node.level:base='.'.join(package[:len(package)-node.level+1]+([node.module] if node.module else []))
     else:base=node.module or ''
     if base in modules:imports.add(modules[base])
     for a in node.names:
      if (base+'.'+a.name) in modules:imports.add(modules[base+'.'+a.name])
    elif isinstance(node,ast.Import):
     for a in node.names:
      if a.name in modules:imports.add(modules[a.name])
  edges[path]=imports-{path}
  # All module-level constants and function tails are covered; no 100-line blind spot.
  ranges += [('<window>',i,min(len(lines),i+80)) for i in range(0,max(len(lines),1),60)]
  for name,start,end in ranges:
   c=collections.Counter(tokens('\n'.join(lines[start:end])));units.append((path,name,start,end,c,sum(c.values())))
 df=collections.Counter();posts=collections.defaultdict(list)
 for i,u in enumerate(units):
  for w,n in u[4].items():df[w]+=1;posts[w].append((i,n))
 fdf=collections.Counter()
 for c in file_counts.values():fdf.update(c.keys())
 return {'units':units,'df':df,'posts':posts,'avg':sum(u[5] for u in units)/max(len(units),1),'files':file_counts,'fdf':fdf,'favg':sum(sum(c.values()) for c in file_counts.values())/max(len(files),1),'defs':defs,'edges':edges,'paths':{p:set(tokens(p)) for p in files}}
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
def rank_scores(index,features,config):
 prod=[p for p in index['files'] if not is_test(p)];tests=[p for p in index['files'] if is_test(p)]
 def rankmap(scores,paths):return {p:i+1 for i,p in enumerate(sorted(paths,key=lambda p:(-scores.get(p,0),p))) if scores.get(p,0)>0}
 ur=rankmap(features['unit'],prod);fr=rankmap(features['file'],prod);er=rankmap(features['exact'],prod)
 k=config.get('rrf_k',10);fw=config.get('file',.5);ew=config.get('exact',.2)
 score={p:1/(k+ur[p]) if p in ur else 0 for p in prod}
 for p in prod:
  score[p]+=fw/(k+fr[p]) if p in fr else 0
  score[p]+=ew/(k+er[p]) if p in er else 0
  if config.get('role'):score[p]*=features['role'][p]
 graph=config.get('graph',0);seeds=sorted(score,key=lambda p:(-score[p],p))[:3];testseeds=sorted(tests,key=lambda p:(-features['unit'][p],p))[:3]
 base=score.copy()
 for p in testseeds:
  weight=config.get('test_graph',.15)*max(base.values(),default=0)
  for target in index['edges'][p]:
   if target in score:score[target]+=weight/max(1,math.sqrt(len(index['edges'][p])))
 for p in seeds:
  for target in index['edges'][p]:
   if target in score:score[target]+=graph*base[p]/max(1,math.sqrt(len(index['edges'][p])))
 return sorted(prod,key=lambda p:(-score[p],p)),score,testseeds

def code_features(files,query):
 counts={};df=collections.Counter();signatures={};priors={};q=set(tokens(clean_query(query)))
 for p,text in files.items():
  lines=text.splitlines();omit=set()
  try:
   tree=ast.parse(text)
   for node in ast.walk(tree):
    if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):omit.update(range(node.lineno-1,node.end_lineno))
  except (SyntaxError,ValueError,RecursionError):pass
  code='\n'.join(line for i,line in enumerate(lines) if i not in omit)
  c=collections.Counter(tokens(code));counts[p]=c;df.update(c.keys())
  signatures[p]=sorted(set(re.sub(r'\s+','',line) for line in code.splitlines() if line.strip()))
  parts=set(Path(p).parts);prior=1.
  if parts&{'scripts','benchmarks','docs'} and not q&{'script','scripts','release','benchmark','docs','documentation'}:prior=.35
  elif parts&{'examples','docs_src'} and not q&{'example','examples','tutorial','tutorials','docs','documentation'}:prior=.65
  # Facades containing only imports are useful context, rarely the implementation.
  significant=[l.strip() for l in code.splitlines() if l.strip() and not l.lstrip().startswith(('#','from ','import ','__all__'))]
  if len(significant)<3:prior*=.5
  priors[p]=prior
 avg=sum(sum(c.values()) for c in counts.values())/max(len(counts),1)
 scores={p:sum(math.log(1+(len(counts)-df[w]+.5)/(df[w]+.5))*c[w]*2.2/(c[w]+1.2*(.25+.75*sum(c.values())/max(avg,1))) for w in q if c[w]) for p,c in counts.items()}
 return {'code':scores,'signatures':signatures,'prior':priors}

_original_rank=rank_scores
def rank_scores(index,features,config):
 paths,scores,testseeds=_original_rank(index,features,config)
 k=config.get('rrf_k',10)
 if config.get('legacy'):
  for i,p in enumerate(features['legacy']):
   if p in scores:scores[p]+=config['legacy']/(k+i+1)
 if config.get('code'):
  ranked=sorted((p for p in scores if features['code'][p]>0),key=lambda p:(-features['code'][p],p))
  for i,p in enumerate(ranked):scores[p]+=config['code']/(k+i+1)
 if config.get('prior'):
  for p in scores:scores[p]*=features['prior'][p]
 ranked=sorted(scores,key=lambda p:(-scores[p],p))
 if config.get('diverse'):
  selected=[];remaining=ranked[:40]
  while remaining and len(selected)<10:
   def adjusted(p):
    penalty=1.
    a=set(features['signatures'][p])
    for prev in selected:
     if Path(prev).parent!=Path(p).parent:continue
     b=set(features['signatures'][prev]);sim=len(a&b)/max(len(a|b),1)
     if sim>.8:penalty=min(penalty,.55)
    return scores[p]*penalty
   p=max(remaining,key=lambda p:(adjusted(p),-ranked.index(p)));selected.append(p);remaining.remove(p)
  ranked=selected+remaining+ranked[40:]
 return ranked,scores,testseeds
