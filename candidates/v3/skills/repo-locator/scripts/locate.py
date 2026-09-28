"""Read-only lexical/symbol navigation over the current Python working tree.

No task database, labels, network, imports of repository code, or reference patches.
"""
import argparse
import ast
import collections
import json
import math
import os
from pathlib import Path
import re
import time

STOP = set('a an the and or of to in for is are be by with on from as this that it not fix fixes pr pull request description changes test tests code github com please should would could have has had was were been using use used add added new now when then than can will must also all any if else return def class self none true false str int bool typing import'.split())
SKIP = {'.git','.hg','.svn','.venv','venv','env','__pycache__','node_modules','build','dist','.tox','.mypy_cache','.pytest_cache'}

def clean_query(text):
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.split(r'(?im)^##\s+(?:AI Disclaimer|Checklist)\b', text)[0]
    return re.sub(r'https?://\S+', ' ', text)[:16000]

def tokens(text):
    result = []
    for raw in re.findall(r'[A-Za-z_][A-Za-z_0-9]*', text):
        whole = raw.lower().strip('_')
        parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', raw).lower().replace('_',' ').split()
        for word in dict.fromkeys([whole] + parts):
            if len(word)>1 and word not in STOP:
                result.append(word)
    return result

def is_test(path):
    p = Path(path)
    return any(x in {'test','tests','testing'} for x in p.parts) or p.name.startswith('test_') or p.name.endswith('_test.py') or p.name=='conftest.py'

def build_units(files):
    units=[]
    for path,text in sorted(files.items()):
        lines=text.splitlines()
        try: tree=ast.parse(text)
        except (SyntaxError,ValueError,RecursionError): tree=None
        ranges=[]
        if tree:
            for node in ast.walk(tree):
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    start=max(0,node.lineno-1);end=min(len(lines),getattr(node,'end_lineno',start+80) or start+80)
                    # Large classes do not crowd out their method-level units.
                    if isinstance(node,ast.ClassDef):end=min(end,start+30)
                    ranges.append((node.name,start,min(end,start+180)))
        ranges.append(('<module>',0,min(len(lines),100)))
        for name,start,end in ranges:
            # Bound text per symbol; the returned snippet uses the strongest query match.
            code='\n'.join(lines[start:end]);terms=collections.Counter(tokens(code))
            units.append({'path':path,'symbol':name,'start':start,'end':end,'terms':terms,'n':sum(terms.values()),'text':code})
    return units

def rank(files,query,variant='imports',top=8,units=None):
    query=clean_query(query);q=collections.Counter(tokens(query));title=query.splitlines()[0] if query.splitlines() else query
    ids={s.lower().strip('_') for s in re.findall(r'[A-Za-z_][A-Za-z_0-9]*',query) if ('_' in s or any(c.isupper() for c in s[1:]))}
    ids.update(s.lower() for s in re.findall(r'`([A-Za-z_][A-Za-z_0-9]*)`',query))
    titlewords=set(tokens(title));units=build_units(files) if units is None else units;df=collections.Counter()
    for u in units:df.update(u['terms'].keys())
    avg=sum(u['n'] for u in units)/max(len(units),1)
    byfile={};test_ranks={}
    for u in units:
        n=u['n'];c=u['terms']
        score=sum(math.log(1+(len(units)-df[w]+.5)/(df[w]+.5))*c[w]*2.2/(c[w]+1.2*(.25+.75*n/max(avg,1)))*(1.5 if w in titlewords else 1) for w in q if c[w])
        if variant!='lexical':
            symbol=u['symbol'].lower();matches=set(tokens(symbol))&q.keys()
            score+=sum(3.0 for _ in matches)
            if symbol in ids:score+=22.0
            elif symbol in titlewords:score+=9.0
            score+=sum(2.0 for w in set(tokens(u['path'])) if w in q)
        if is_test(u['path']):target=test_ranks
        else:target=byfile
        if u['path'] not in target or score>target[u['path']][0]:target[u['path']]=(score,u)
    if variant=='imports':
        # Only imports from existing tests; no withheld test_patch is available.
        modules={p[:-3].replace('/','.'):p for p in files if not is_test(p)}
        for p in list(modules):
            if p.startswith('src.'):modules[p[4:]]=modules[p]
        top_tests=sorted(test_ranks.values(),key=lambda x:(-x[0],x[1]['path']))[:3]
        for score,u in top_tests:
            for mod in set(re.findall(r'(?m)^from\s+([\w.]+)\s+import',files[u['path']])):
                path=modules.get(mod)
                if path in byfile:
                    old,unit=byfile[path];byfile[path]=(old+score*.12,unit)
    ranked=sorted(byfile.values(),key=lambda x:(-x[0],x[1]['path']))
    def compact(score,u):
        lines=files[u['path']].splitlines();start=u['start'];end=min(len(lines),start+28)
        # Show a window around the strongest query match, not just the declaration.
        best=max(range(u['start'],max(u['start']+1,u['end'])),key=lambda i:len(set(tokens(lines[i] if i<len(lines) else ''))&q.keys()))
        if best>=end:start=max(u['start'],best-7);end=min(len(lines),start+28)
        return {'path':u['path'],'symbol':u['symbol'],'definition_line':u['start']+1,'start_line':start+1,'end_line':end,'score':round(score,3),'excerpt':'\n'.join(f'{i+1}: {lines[i]}' for i in range(start,end))[:2200]}
    return {'candidates':[compact(s,u) for s,u in ranked[:top]],'related_tests':[{'path':u['path'],'symbol':u['symbol'],'line':u['start']+1} for s,u in sorted(test_ranks.values(),key=lambda x:(-x[0],x[1]['path']))[:3]],'python_files':len(files),'symbols_indexed':len(units)}

def read_workspace(root,seconds=20):
    root=root.resolve();start=time.monotonic();files={};limited=False;total=0
    for base,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and not (Path(base)/d).is_symlink())
        for name in sorted(names):
            if not name.endswith('.py') or name.startswith('.adk_exec_'):continue
            if time.monotonic()-start>seconds or len(files)>=10000 or total>50_000_000:limited=True;return files,limited
            p=Path(base)/name
            try:
                if p.is_symlink() or not p.resolve().is_relative_to(root) or p.stat().st_size>2_000_000:continue
                content=p.read_text(encoding='utf8',errors='replace');files[p.relative_to(root).as_posix()]=content;total+=len(content)
            except OSError:continue
    return files,limited

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--query',required=True);parser.add_argument('--top',type=int,default=6);parser.add_argument('--root',default='/workspace');args=parser.parse_args()
    root=Path(args.root)
    if not root.is_dir():print(json.dumps({'error':'workspace not found','root':str(root)}));return
    start=time.monotonic();files,limited=read_workspace(root)
    result=rank(files,args.query,variant='imports',top=max(1,min(args.top,10)))
    result.update(scan_limited=limited,elapsed_seconds=round(time.monotonic()-start,3),note='Candidates are hypotheses from current source, not verified edit targets.')
    # Deterministic output cap, preserving every candidate's path and line numbers.
    while len(json.dumps(result,ensure_ascii=False))>12000:
        texts=[c for c in result['candidates'] if len(c.get('excerpt',''))>150]
        if not texts:break
        c=max(texts,key=lambda x:len(x['excerpt']));c['excerpt']=c['excerpt'][:max(150,len(c['excerpt'])//2)]+'\n[excerpt shortened]'
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
