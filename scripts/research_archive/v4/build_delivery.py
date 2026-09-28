from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
s=(ROOT/'work/v4_experiments/retrieval.py').read_text().split('\ndef code_features')[0]
s=s.replace('import ast,collections,math,re,time','import ast,collections,math,re,time,os,json,argparse\nfrom functools import lru_cache')
a=s.index('def tokens(');b=s.index('def is_test(',a)
s=s[:a]+'''@lru_cache(maxsize=8192)
def word_parts(raw):
 whole=raw.lower().strip('_');parts=re.sub(r'([a-z])([A-Z])',r'\\1 \\2',raw).lower().replace('_',' ').split()
 return tuple(w for w in dict.fromkeys([whole]+parts) if len(w)>1 and w not in STOP)
def tokens(text):
 return [w for raw in re.findall(r'[A-Za-z_][A-Za-z_0-9]*',text) for w in word_parts(raw)]
'''+s[b:]
s=s.replace('def build_index(files):','def build_index(files,deadline=None):').replace('units=[];file_counts={};defs={};edges={};modules=module_map(files)','units=[];file_counts={};defs={};edges={};modules=module_map(files);significant={};limited=False')
s=s.replace('  lines=text.splitlines();file_counts', '  if deadline is not None and time.monotonic()>deadline:limited=True;break\n  lines=text.splitlines();file_counts')
s=s.replace('  edges[path]=imports-{path}', '''  edges[path]=imports-{path}
  omit=set()
  if tree:
   for node in ast.walk(tree):
    if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
     # Do not erase executable statements sharing the docstring line.
     if not lines[node.lineno-1][:node.col_offset].strip() and not lines[node.end_lineno-1][node.end_col_offset:].strip():
      omit.update(range(node.lineno-1,node.end_lineno))
  significant[path]=sum(bool(line.strip()) and not line.lstrip().startswith(('#','from ','import ','__all__')) for i,line in enumerate(lines) if i not in omit)''')
s=s.replace("'paths':{p:set(tokens(p)) for p in files}","'paths':{p:set(tokens(p)) for p in file_counts},'significant':significant,'limited':limited")
s=s.replace("def rank_scores(index,features,config):","CONFIG={'file':.5,'exact':.2,'test_graph':0,'role':True,'prior':True}\ndef rank_scores(index,features,config=CONFIG):")
s=s.replace("return sorted(prod,key=lambda p:(-score[p],p)),score,testseeds",'''q=set(tokens(features['query']))
 for p in score:
  parts=set(Path(p).parts);prior=1.
  if parts&{'scripts','benchmarks','docs'} and not q&{'script','scripts','release','benchmark','docs','documentation'}:prior=.35
  elif parts&{'examples','docs_src'} and not q&{'example','examples','tutorial','tutorials','docs','documentation'}:prior=.65
  if index['significant'][p]<3:prior*=.5
  score[p]*=prior
 return sorted((p for p in prod if score[p]>0),key=lambda p:(-score[p],p)),score,[p for p in testseeds if features['unit'][p]>0]''')
# No deployed graph expansion: remove dead extraction and expansion paths.
a=s.index('def module_map(');b=s.index('def build_index(',a);s=s[:a]+s[b:]
s=s.replace('defs={};edges={};modules=module_map(files);','defs={};')
a=s.index('    elif isinstance(node,ast.ImportFrom):');b=s.index('  omit=set()',a);s=s[:a]+s[b:]
s=s.replace("'defs':defs,'edges':edges,", "'defs':defs,")
a=s.index(" graph=config.get('graph'");b=s.index(" q=set(tokens(features['query']))",a)
s=s[:a]+" testseeds=sorted(tests,key=lambda p:(-features['unit'][p],p))[:2]\n"+s[b:]
(ROOT/'outputs/submission_v4/skills/repo-context/scripts/context.py').write_text(s)
