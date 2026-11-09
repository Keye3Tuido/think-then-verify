"""Installation must work without a particular agent or hook runtime."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
class InstallTests(unittest.TestCase):
    def call(self,*args):
        return subprocess.run([sys.executable,str(HERE/'install.py'),*map(str,args)],capture_output=True,text=True)
    def test_generic_file_preserved_and_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'AGENTS.md'; target.write_text('USER RULE\n')
            args=['install','--agents-file',target]
            self.assertEqual(self.call(*args).returncode,0)
            first=target.read_bytes(); self.assertTrue(first.startswith(b'USER RULE\n'))
            self.assertEqual(self.call(*args).returncode,0)
            self.assertEqual(first,target.read_bytes())
            self.assertEqual(self.call('check','--agents-file',target).returncode,0)
            self.assertFalse((Path(tmp)/'hooks.json').exists())
    def test_check_readonly_missing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'AGENTS.md'
            self.assertNotEqual(self.call('check','--agents-file',target).returncode,0)
            self.assertFalse(target.exists())
    def test_malformed_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'AGENTS.md'; target.write_text('<!-- think-then-verify:start -->\nUSER')
            self.assertNotEqual(self.call('install','--agents-file',target).returncode,0)
            self.assertEqual(target.read_text(),'<!-- think-then-verify:start -->\nUSER')
    def test_document_is_standalone_and_copied_without_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'AGENTS.md'
            result=self.call('install','--agents-file',target)
            self.assertEqual(result.returncode,0,result.stderr)
            canonical=(HERE/'AGENTS.md').read_text()
            self.assertEqual(target.read_text().strip(),canonical.strip())
            self.assertNotIn('SKILL.md',canonical)
            self.assertNotIn('@TV_SKILL@',canonical)
            self.assertNotIn('/tv off',canonical)
            self.assertNotIn('/tv`',canonical)
            self.assertFalse((HERE/'adapters').exists())
    def test_changed_rules_are_replaced_without_losing_other_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'AGENTS.md'
            original='BEFORE\n<!-- think-then-verify:start -->\nOLD RULE\n<!-- think-then-verify:end -->\nAFTER\n'
            target.write_text(original)
            self.assertNotEqual(self.call('check','--agents-file',target).returncode,0)
            result=self.call('install','--agents-file',target)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(target.read_text().startswith('BEFORE\n'))
            self.assertTrue(target.read_text().endswith('\nAFTER\n'))
            self.assertEqual(len(list(target.parent.glob('AGENTS.md.backup-*'))),1)
            self.assertEqual(next(target.parent.glob('AGENTS.md.backup-*')).read_text(),original)
    def test_bad_source_preserves_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'AGENTS.md'; target.write_text('USER RULE\n')
            source=Path(tmp)/'broken.md'; source.write_text('<!-- think-then-verify:start -->\nINCOMPLETE')
            result=self.call('install','--agents-file',target,'--source',source)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(target.read_text(),'USER RULE\n')
if __name__=='__main__': unittest.main()
