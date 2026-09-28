import ast,collections,gzip,hashlib,importlib.util,json,math,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
s=importlib.util.spec_from_file_location('r',ROOT/'work/v4_experiments/retrieval.py');nav=importlib.util.module_from_spec(s);s.loader.exec_module(nav)
rows={r['instance_id']:r for r in map(json.loads,Path('/Users/topologyw/Documents/Kaggles/gemma_4/data/tasks.jsonl').read_text().splitlines())}
manifest=json.loads((ROOT/'work/v3_experiments/corpus_manifest.json').read_text());cp={id:r['corpus'] for r in manifest for id in r['ids']}
base={r['instance_id']:r for phase in ['dev','heldout'] for r in map(json.loads,(ROOT/f'outputs/v3_experiments/localization_{phase}.jsonl').read_text().splitlines()) if r['variant']=='imports'}
for i,p in enumerate(sorted((ROOT/'work/v4_experiments/features').glob('*.gz')),1):
 with gzip.open(p,'rt') as f:d=json.load(f)
 if 'code' in d['features']:continue
 id=p.name[:-8]
 with gzip.open(ROOT/'work/v3_experiments/corpus'/cp[id],'rt') as f:files=json.load(f)
 t=time.monotonic();extra=nav.code_features(files,rows[id]['problem_statement']);d['features'].update(extra);d['features']['legacy']=base[id]['predicted_paths'];d['extra_seconds']=time.monotonic()-t;d['legacy_seconds']=base[id]['elapsed_seconds']
 with gzip.open(p,'wt') as f:json.dump(d,f)
 if i%20==0:print(i,flush=True)
