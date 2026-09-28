import argparse,gzip,hashlib,importlib.util,json,statistics,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(path):
 s=importlib.util.spec_from_file_location('retrieval',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
nav=load(ROOT/'work/v4_experiments/retrieval.py')
rows=list(map(json.loads,Path('/Users/topologyw/Documents/Kaggles/gemma_4/data/tasks.jsonl').read_text().splitlines()))
split=json.loads((ROOT/'outputs/v4_experiments/splits.json').read_text())['assignments']
manifest=json.loads((ROOT/'work/v3_experiments/corpus_manifest.json').read_text());cp={i:r['corpus'] for r in manifest for i in r['ids']}
old={r['instance_id']:r for phase in ['dev','heldout'] for r in map(json.loads,(ROOT/f'outputs/v3_experiments/localization_{phase}.jsonl').read_text().splitlines()) if r['variant']=='imports'}
CONFIGS={'coverage':{'file':0,'exact':0,'test_graph':0},'fusion':{'file':.5,'exact':0,'test_graph':0},'exact':{'file':.5,'exact':.2,'test_graph':0},'role':{'file':.5,'exact':.2,'test_graph':0,'role':True},'test_graph':{'file':.5,'exact':.2,'test_graph':.15,'role':True},'graph':{'file':.5,'exact':.2,'test_graph':.15,'graph':.25,'role':True},'file_heavy':{'file':1,'exact':.2,'test_graph':.15,'graph':.25,'role':True},'graph_heavy':{'file':.5,'exact':.2,'test_graph':.15,'graph':.5,'role':True}}
def stats(rs):
 elig=[r for r in rs if r['targets']]
 return {'tasks':len(rs),'eligible':len(elig),**{f'hit@{k}':sum(bool(set(r['targets'])&set(r['paths'][:k])) for r in elig)/max(len(elig),1) for k in [1,3,5,10]},'recall@5':statistics.mean(len(set(r['targets'])&set(r['paths'][:5]))/len(r['targets']) for r in elig),'median_seconds':statistics.median(r['seconds'] for r in rs),'p95_seconds':sorted(r['seconds'] for r in rs)[int((len(rs)-1)*.95)]}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--split',default='train');ap.add_argument('--round',default='round1');ap.add_argument('--config');a=ap.parse_args();configs=json.loads(Path(a.config).read_text()) if a.config else CONFIGS
 out=ROOT/'outputs/v4_experiments';cache=ROOT/'work/v4_experiments/features';cache.mkdir(exist_ok=True);results=[]
 selected=[r for r in rows if split[r['instance_id']]==a.split]
 for i,r in enumerate(selected,1):
  id=r['instance_id'];p=cache/(id+'.json.gz')
  if p.exists():
   with gzip.open(p,'rt') as f:d=json.load(f)
  else:
   with gzip.open(ROOT/'work/v3_experiments/corpus'/cp[id],'rt') as f:files=json.load(f)
   start=time.monotonic();index=nav.build_index(files);features=nav.retrieve_features(index,r['problem_statement']);seconds=time.monotonic()-start
   d={'index':{'files':{p:None for p in files},'edges':{p:sorted(v) for p,v in index['edges'].items()}},'features':features,'seconds':seconds}
   with gzip.open(p,'wt') as f:json.dump(d,f)
  b=old[id];results.append({'id':id,'repo':r['repo'],'variant':'v3','targets':b['existing_targets'],'paths':b['predicted_paths'],'seconds':b['elapsed_seconds']})
  for name,config in configs.items():
   start=time.monotonic();paths,_,_=nav.rank_scores(d['index'],d['features'],config);elapsed=d['seconds']+time.monotonic()-start+(d.get('extra_seconds',0) if any(config.get(x) for x in ['code','prior','diverse']) else 0)+(d.get('legacy_seconds',0) if config.get('legacy') else 0)
   results.append({'id':id,'repo':r['repo'],'variant':name,'targets':b['existing_targets'],'paths':paths[:10],'seconds':elapsed})
  if i%10==0 or i==len(selected):print(a.split,i,'/',len(selected),flush=True)
 (out/f'{a.round}_{a.split}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results))
 summary={'configs':configs,'metrics':{v:stats([r for r in results if r['variant']==v]) for v in ['v3']+list(configs)},'by_repo':{repo:{v:stats([r for r in results if r['variant']==v and r['repo']==repo]) for v in ['v3']+list(configs)} for repo in sorted({r['repo'] for r in results})}}
 (out/f'{a.round}_{a.split}_summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary['metrics'],indent=2),flush=True)
if __name__=='__main__':main()
