import argparse,collections,gzip,hashlib,importlib.util,json,statistics,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
nav=load('navigator',ROOT/'outputs/submission_v3/skills/repo-locator/scripts/locate.py')
old=load('baseline',ROOT/'outputs/gemma4_experiment_pack/tools/build_pack.py')
rows=list(map(json.loads,Path('/Users/topologyw/Documents/Kaggles/gemma_4/data/tasks.jsonl').read_text().splitlines()))
manifest=json.loads((ROOT/'work/v3_experiments/corpus_manifest.json').read_text());cp={id:r for r in manifest for id in r['ids']}
def stats(rs):
 eligible=[r for r in rs if r['existing_targets']]
 return {'tasks':len(rs),'eligible_existing_python_targets':len(eligible),'new_or_non_python_only':len(rs)-len(eligible),**{f'hit_at_{k}':sum(r[f'hit_at_{k}'] for r in eligible)/max(1,len(eligible)) for k in [1,3,5,10]},'macro_recall_at_5':statistics.mean(r['recall_at_5'] for r in eligible) if eligible else None,'median_seconds':statistics.median(r['elapsed_seconds'] for r in rs) if rs else None}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--split',choices=['dev','heldout'],required=True);ap.add_argument('--variants',nargs='+',default=['file_baseline','lexical','symbol','imports']);a=ap.parse_args();results=[]
 selected=[r for r in rows if (r['repo'] in ['fastapi/fastapi','Textualize/rich'])==(a.split=='dev')]
 for i,r in enumerate(selected,1):
  with gzip.open(ROOT/'work/v3_experiments/corpus'/cp[r['instance_id']]['corpus'],'rt') as f:files=json.load(f)
  targets=old.paths(r['patch']);existing=[p for p in targets if p in files and p.endswith('.py') and not nav.is_test(p)]
  t=time.monotonic();units=nav.build_units(files);index_seconds=time.monotonic()-t
  for variant in a.variants:
   t=time.monotonic()
   if variant=='file_baseline':
    ranked,_=old.retrieve({p:text.encode() for p,text in files.items()},old.clean(r['problem_statement']));paths=[x['path'] for x in ranked]
   else:
    ranked=nav.rank(files,r['problem_statement'],variant=variant,top=10,units=units);paths=[x['path'] for x in ranked['candidates']]
   elapsed=time.monotonic()-t+(0 if variant=='file_baseline' else index_seconds)
   rec={'instance_id':r['instance_id'],'repo':r['repo'],'variant':variant,'reference_paths':targets,'existing_targets':existing,'predicted_paths':paths,'elapsed_seconds':round(elapsed,4)}
   for k in [1,3,5,10]:
    found=set(existing)&set(paths[:k]);rec[f'hit_at_{k}']=bool(found);rec[f'recall_at_{k}']=len(found)/len(existing) if existing else None
   results.append(rec)
  if i%10==0 or i==len(selected):print(a.split,i,'/',len(selected),flush=True)
 out=ROOT/'outputs/v3_experiments';(out/f'localization_{a.split}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results))
 summary={'split':a.split,'code_sha256':hashlib.sha256((ROOT/'outputs/submission_v3/skills/repo-locator/scripts/locate.py').read_bytes()).hexdigest(),'note':'file baseline is deterministic 9/26 retrieval baseline, not actual v2 model behavior; gold used only for metrics','variants':{v:stats([r for r in results if r['variant']==v]) for v in a.variants},'by_repo':{repo:{v:stats([r for r in results if r['variant']==v and r['repo']==repo]) for v in a.variants} for repo in sorted({r['repo'] for r in results})}}
 (out/f'localization_{a.split}_summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
