import argparse,gzip,hashlib,importlib.util,json,statistics,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
new=load('packet',ROOT/'outputs/submission_v4/skills/repo-context/scripts/context.py');old=load('old',ROOT/'outputs/submission_v3/skills/repo-locator/scripts/locate.py')
rows=list(map(json.loads,Path('/Users/topologyw/Documents/Kaggles/gemma_4/data/tasks.jsonl').read_text().splitlines()));splits=json.loads((ROOT/'outputs/v4_experiments/splits.json').read_text())['assignments'];manifest=json.loads((ROOT/'work/v3_experiments/corpus_manifest.json').read_text());cp={id:r['corpus'] for r in manifest for id in r['ids']}
labels={r['instance_id']:r for phase in ['dev','heldout'] for r in map(json.loads,(ROOT/f'outputs/v3_experiments/localization_{phase}.jsonl').read_text().splitlines()) if r['variant']=='imports'}
training={r['id']:r for r in map(json.loads,(ROOT/'outputs/v4_experiments/round3_train.jsonl').read_text().splitlines()) if r['variant']=='prior'}
def stats(rs):
 eligible=[r for r in rs if r['targets']]
 return {'tasks':len(rs),'eligible':len(eligible),**{f'hit@{k}':sum(bool(set(r['targets'])&set(r['paths'][:k])) for r in eligible)/max(len(eligible),1) for k in [1,3,5,10]},'recall@5':statistics.mean(len(set(r['targets'])&set(r['paths'][:5]))/len(r['targets']) for r in eligible),'median_seconds':statistics.median(r['seconds'] for r in rs),'p95_seconds':sorted(r['seconds'] for r in rs)[int((len(rs)-1)*.95)],'median_output_chars':statistics.median(r['output_chars'] for r in rs),'max_output_chars':max(r['output_chars'] for r in rs)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--split',required=True);a=ap.parse_args();results=[];mismatches=[]
 selected=[r for r in rows if splits[r['instance_id']]==a.split]
 for i,r in enumerate(selected,1):
  with gzip.open(ROOT/'work/v3_experiments/corpus'/cp[r['instance_id']],'rt') as f:files=json.load(f)
  new.word_parts.cache_clear();t=time.monotonic();packet,paths=new.prepare(files,r['problem_statement']);newtime=time.monotonic()-t
  b=labels[r['instance_id']];id=r['instance_id']
  if a.split=='train' and paths[:10]!=training[id]['paths']:mismatches.append({'id':id,'old':training[id]['paths'],'new':paths[:10]})
  # Independently time original tool on same machine and inputs, including indexing.
  t=time.monotonic();baseline=old.rank(files,r['problem_statement'],top=10);oldtime=time.monotonic()-t
  assert [p['path'] for p in baseline['candidates']]==b['predicted_paths'],id
  # v3 CLI normally returns six candidates and caps output at 12000 characters.
  baseline['candidates']=baseline['candidates'][:6]
  while len(json.dumps(baseline,ensure_ascii=False))>12000:
   texts=[c for c in baseline['candidates'] if len(c['excerpt'])>150]
   if not texts:break
   c=max(texts,key=lambda x:len(x['excerpt']));c['excerpt']=c['excerpt'][:max(150,len(c['excerpt'])//2)]+'\n[excerpt shortened]'
  for version,preds,elapsed,obj in [('v3',b['predicted_paths'],oldtime,baseline),('v4',paths[:10],newtime,packet)]:
   results.append({'id':id,'repo':r['repo'],'variant':version,'targets':b['existing_targets'],'paths':preds,'seconds':elapsed,'output_chars':len(json.dumps(obj,ensure_ascii=False))})
  if i%10==0 or i==len(selected):print(a.split,i,'/',len(selected),flush=True)
 out=ROOT/'outputs/v4_experiments';(out/f'final_{a.split}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results))
 summary={'split':a.split,'source_sha256':hashlib.sha256((ROOT/'outputs/submission_v4/skills/repo-context/scripts/context.py').read_bytes()).hexdigest(),'timing_scope':'fresh indexing and ranking on loaded original source, cold word cache; excludes disk scan and process startup','metrics':{v:stats([r for r in results if r['variant']==v]) for v in ['v3','v4']},'parity_mismatches':mismatches}
 (out/f'final_{a.split}_summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
