import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/'outputs/submission_v3/skills/repo-locator/scripts/locate.py'
spec=importlib.util.spec_from_file_location('locator',SCRIPT);nav=importlib.util.module_from_spec(spec);spec.loader.exec_module(nav)
class LocatorChecks(unittest.TestCase):
 def test_async_and_duplicate_locations(self):
  files={'a.py':'async def parse_header(value):\n    return value.strip()\n','b.py':'class Other:\n    def parse_header(self, value):\n        return value\n'}
  units=nav.build_units(files)
  self.assertEqual([(u['path'],u['start']+1) for u in units if u['symbol']=='parse_header'],[('a.py',1),('b.py',2)])
  result=nav.rank(files,'`parse_header` strip header whitespace')
  self.assertEqual(result['candidates'][0]['path'],'a.py')
 def test_no_execution_and_invalid_source(self):
  files={'bad.py':'def invalid(\n','empty.py':'','safe.py':'raise RuntimeError("MUST NOT EXECUTE")\ndef parse_header(value):\n    return value\n'}
  result=nav.rank(files,'parse_header')
  self.assertEqual(result['candidates'][0]['path'],'safe.py')
 def test_tests_are_separate_and_import_boost_works(self):
  files={'src/pkg/codec.py':'def transform(x):\n    return x\n','tests/test_codec.py':'from pkg.codec import transform\ndef test_quoted_header():\n    assert transform("header")\n'}
  result=nav.rank(files,'quoted header')
  self.assertEqual(result['candidates'][0]['path'],'src/pkg/codec.py')
  self.assertEqual(result['related_tests'][0]['path'],'tests/test_codec.py')
 def test_cli_readonly_ignores_symlinks_and_caps_output(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'work/v3_experiments') as d:
   root=Path(d);outside=root/'ignored.txt';outside.write_text('private sentinel')
   (root/'external.py').symlink_to(outside)
   for i in range(10):(root/f'file{i}.py').write_text('def quoted_header(value):\n'+''.join('    # header quote '+('x'*100)+'\n' for j in range(40))+'    return value\n')
   before={p.name:p.read_bytes() for p in root.iterdir() if not p.is_symlink()}
   result=subprocess.run(['python3','-B',str(SCRIPT),'--root',str(root),'--query','quoted_header quote header','--top','10'],capture_output=True,text=True,check=True)
   data=json.loads(result.stdout)
   self.assertLessEqual(len(result.stdout.strip()),12000)
   self.assertEqual(data['python_files'],10)
   self.assertEqual(len(data['candidates']),10)
   self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir() if not p.is_symlink()})
   files,limited=nav.read_workspace(root,seconds=-1)
   self.assertEqual(files,{});self.assertTrue(limited)
if __name__=='__main__':unittest.main(verbosity=2)
