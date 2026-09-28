#!/usr/bin/env python3
"""Check pack integrity and separation; does not execute repository code."""
import json
from pathlib import Path

def main():
 p=Path(__file__).resolve().parent.parent
 read=lambda path:[json.loads(x) for x in (p/path).read_text().splitlines() if x.strip()]
 agents=read('agent/tasks_all.jsonl');labels=read('evaluator/labels_all.jsonl');pilot=read('agent/tasks_pilot.jsonl');contexts=read('agent/pilot_retrieved_contexts.jsonl')
 allowed={'instance_id','repo','base_commit','problem_statement','hints_text'}
 assert all(set(r)==allowed for r in agents)
 assert len(agents)==129 and len({r['instance_id'] for r in agents})==129
 assert {r['instance_id'] for r in agents}=={r['instance_id'] for r in labels}
 assert len(pilot)==12 and {r['instance_id'] for r in pilot}=={r['instance_id'] for r in contexts}
 splits=json.loads((p/'splits.json').read_text());groups=[set(splits[k]) for k in ['dev','holdout_requests','ood_httpx']]
 assert sum(map(len,groups))==129 and set.union(*groups)=={r['instance_id'] for r in agents}
 assert all(not groups[i]&groups[j] for i in range(3) for j in range(i))
 for key in ['dev','holdout_requests','ood_httpx']:
  assert {r['instance_id'] for r in read(f'agent/tasks_{key}.jsonl')}==set(splits[key])
 repo={r['instance_id']:r['repo'] for r in agents}
 repo_groups=[{repo[id] for id in group} for group in groups]
 assert all(not repo_groups[i]&repo_groups[j] for i in range(3) for j in range(i))
 assert all(set(r)=={'instance_id','repo','problem_statement','hints_text','retrieval_method','contexts'} for r in contexts)
 checks=json.loads((p/'audit/pilot_snapshot_checks.json').read_text());assert len(checks)==12
 assert all(r['patch_apply_check']['patch']['ok'] and r['patch_apply_check']['test_patch']['ok'] for r in checks)
 smoke=json.loads((p/'audit/smoke_results.json').read_text());assert len(smoke)==3 and all(r['fail_to_pass_observed'] for r in smoke)
 print('PASS: 129 inputs/labels, 12 pilot/context pairs, disjoint repository splits, 24 apply checks, 3 local fail-to-pass checks. No model score inferred.')
if __name__=='__main__':main()
