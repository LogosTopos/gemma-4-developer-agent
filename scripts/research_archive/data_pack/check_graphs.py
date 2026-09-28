#!/usr/bin/env python3
import argparse,collections,importlib.util,json,zipfile
from pathlib import Path
import numpy as np

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);a=ap.parse_args();src=a.source.resolve();pack=Path(__file__).resolve().parent.parent
 rows=list(map(json.loads,(pack/'agent/tasks_all.jsonl').read_text().splitlines()));pilots={r['instance_id'] for r in map(json.loads,(pack/'agent/tasks_pilot.jsonl').read_text().splitlines())}
 result=[]
 for r in rows:
  id=r['instance_id'];gpath=src/'data/graphs'/f'{id}.json';epath=src/'data/embeddings'/f'{id}.npz';g=json.loads(gpath.read_text());ns=g['nodes'];ids={n['id'] for n in ns}
  with zipfile.ZipFile(epath) as z:keys={n[:-4] for n in z.namelist() if n.endswith('.npy')}
  x={'instance_id':id,'graph_repo_name':g.get('graph',{}).get('repo_name'),'metadata_matches_task':g.get('graph',{}).get('repo_name')==r['repo'].split('/')[-1]+'_'+r['base_commit'],'nodes':len(ns),'edges':len(g.get('edges',[])),'embedding_keys':len(keys),'graph_nodes_missing_embeddings':len(ids-keys),'extra_embedding_keys':len(keys-ids),'async_definition_nodes':sum(n.get('text','').lstrip().startswith('async def ') for n in ns)}
  if id in pilots:
   with np.load(epath,allow_pickle=False) as z:
    dims=collections.Counter();nonfinite=0;zeros=0
    for k in z.files:
     v=z[k];dims[str(v.shape)]+=1;nonfinite+=int(not np.isfinite(v).all());zeros+=int(not np.any(v))
   x.update(embedding_shapes=dict(dims),nonfinite_vectors=nonfinite,zero_vectors=zeros)
  result.append(x)
 modpath=src/'vendor/src/swegemma-0.2.7/swegemma/graph/embedding_utils.py';sp=importlib.util.spec_from_file_location('graph_embedding_probe',modpath);mod=importlib.util.module_from_spec(sp);sp.loader.exec_module(mod)
 r=next(x for x in rows if x['instance_id']=='requests_7315');ep=str(src/'data/embeddings/requests_7315.npz');probes=[]
 for q in ['preserve leading slashes in request URL','HTTPAdapter','request_url']:
  v=mod.embed(q,r['repo'],embeddings_dir=ep,base_commit=r['base_commit']);probes.append({'query':q,'vector_found':v is not None,'shape':list(v.shape) if v is not None else None})
 (pack/'audit/graph_checks.json').write_text(json.dumps({'tasks':result,'actual_embedding_function_probes':probes},indent=2)+'\n')
 print('tasks',len(result),'metadata_mismatch',sum(not x['metadata_matches_task'] for x in result),'async_nodes',sum(x['async_definition_nodes'] for x in result),'missing_embedding_nodes',sum(x['graph_nodes_missing_embeddings'] for x in result),'probes',probes)
if __name__=='__main__':main()
