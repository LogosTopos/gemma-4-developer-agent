import importlib.util,json,subprocess,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];SCRIPT=ROOT/'outputs/submission_v4/skills/repo-context/scripts/context.py'
s=importlib.util.spec_from_file_location('context',SCRIPT);nav=importlib.util.module_from_spec(s);s.loader.exec_module(nav)
class ContextChecks(unittest.TestCase):
 def test_query_and_full_coverage(self):
  query='Fix header\n## Checklist\n- [x] Tests\nReal details: rare_boundary'
  self.assertIn('rare_boundary',nav.clean_query(query));self.assertNotIn('[x]',nav.clean_query(query))
  text='\n'.join('# padding' for _ in range(240))+'\nrare_boundary = 1\n'
  packet,paths=nav.prepare({'constants.py':text,'other.py':'x=1\n'},query)
  self.assertEqual(paths[0],'constants.py');self.assertIn('rare_boundary',packet['files'][0]['code'])
 def test_async_inline_doc_and_invalid_source(self):
  files={'a.py':'async def parse_header(x):\n    return x.strip()\n','b.py':'def f(): "doc"; return 1\n','invalid.py':'def broken(\n','empty.py':''}
  index=nav.build_index(files);self.assertIn(('parse_header',0,2),index['defs']['a.py']);self.assertGreater(index['significant']['b.py'],0)
  packet,paths=nav.prepare(files,'parse_header strip');self.assertEqual(paths[0],'a.py')
 def test_empty_query_and_deadline(self):
  packet,paths=nav.prepare({'source.py':'x=1'},'');self.assertEqual(paths,[])
  packet,paths=nav.prepare({'source.py':'x=1'},'source',deadline=time.monotonic()-1);self.assertTrue(packet['partial']);self.assertEqual(paths,[])
 def test_cli_readonly_output_and_symlinks(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'work/v4_experiments') as d:
   root=Path(d);outside=root/'ignore.txt';outside.write_text('secret sentinel');(root/'link.py').symlink_to(outside)
   for i in range(8):(root/f'f{i}.py').write_text('def parse_header(x):\n'+''.join('    # parse_header '+('x'*200)+'\n' for _ in range(50))+'    return x\n')
   before={p.name:p.read_bytes() for p in root.iterdir() if not p.is_symlink()}
   res=subprocess.run(['python3','-B',str(SCRIPT),'--root',str(root),'--query','parse_header'],capture_output=True,text=True,check=True);packet=json.loads(res.stdout)
   self.assertLessEqual(len(res.stdout.strip()),6000);self.assertEqual(len(packet['files']),5);self.assertNotIn('link.py',[p['path'] for p in packet['files']]);self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir() if not p.is_symlink()})
if __name__=='__main__':unittest.main(verbosity=2)
