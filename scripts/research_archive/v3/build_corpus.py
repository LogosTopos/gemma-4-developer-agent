import gzip,json,tarfile,time
from pathlib import Path
src=Path('/Users/topologyw/Documents/Kaggles/gemma_4/data');out=Path(__file__).resolve().parent/'corpus'
rows=list(map(json.loads,(src/'tasks.jsonl').read_text().splitlines()))
# Reuse a single corpus for tasks sharing a declared repo/commit group.
groups={}
for r in rows:groups.setdefault((r['repo'],r['base_commit']),[]).append(r)
manifest=[];started=time.monotonic()
for i,((repo,commit),group) in enumerate(groups.items(),1):
 r=group[0];dst=out/(r['instance_id']+'.json.gz')
 if not dst.exists():
  files={}
  with tarfile.open(src/'snapshots'/(r['instance_id']+'.tgz'),'r|gz') as t:
   for m in t:
    name=m.name.removeprefix('./')
    if m.isfile() and name.endswith('.py') and not any(x in Path(name).parts for x in ['.git','.venv','venv','__pycache__']) and m.size<=2_000_000:
     files[name]=t.extractfile(m).read().decode('utf8','replace')
  with gzip.open(dst,'wt') as f:json.dump(files,f)
 else:
  with gzip.open(dst,'rt') as f:files=json.load(f)
 manifest.append({'ids':[r['instance_id'] for r in group],'repo':repo,'base_commit':commit,'corpus':dst.name,'python_files':len(files)})
 if i%10==0 or i==len(groups):print(i,'/',len(groups),'seconds',round(time.monotonic()-started,1),flush=True)
(out.parent/'corpus_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
