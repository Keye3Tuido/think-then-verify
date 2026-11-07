"""Fresh-install and repeat-install tests never touch the actual host configuration."""
import importlib.util
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
import tomllib
from unittest.mock import patch
import install

class Installation(unittest.TestCase):
    def test_fresh_and_repeated_install_preserve_session_and_foreign_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'codex';home.mkdir()
            hooks=home/'hooks.json'
            hooks.write_text(json.dumps({'hooks':{'Stop':[{'hooks':[{'command':'foreign','statusMessage':'foreign'}]}]}}))
            identity=str(hooks)+':stop:0:0'
            (home/'config.toml').write_text('[hooks.state.'+json.dumps(identity)+']\nenabled = true\ntrusted_hash = "preserve"\n')
            runtime=home/'tv';runtime.mkdir()
            (runtime/'registry.json').write_text('PRIVATE_SESSION_SENTINEL')
            first=install.install(home);second=install.install(home)
            self.assertEqual(first['script_sha256'],second['script_sha256'])
            self.assertEqual((runtime/'registry.json').read_text(),'PRIVATE_SESSION_SENTINEL')
            for name in install.FILES:self.assertTrue((runtime/name).is_file(),name)
            self.assertEqual((runtime/'README.md').read_bytes(), (install.HERE/'README.md').read_bytes())
            check=subprocess.run([__import__('sys').executable,'-c','import install, simulate, test_installation'],cwd=runtime,capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stderr)
            entries=[h for groups in json.loads(hooks.read_text())['hooks'].values() for g in groups for h in g['hooks']]
            self.assertEqual(len(entries),5)
            states=tomllib.loads((home/'config.toml').read_text())['hooks']['state']
            self.assertEqual(states[identity],{'enabled':True,'trusted_hash':'preserve'})
            self.assertTrue(all(not v['enabled'] for k,v in states.items() if k!=identity))
            self.assertTrue(all('trusted_hash' not in v for k,v in states.items() if k!=identity))

    def test_missing_host_configuration_is_created_without_granting_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'fresh'
            report=install.install(home)
            self.assertFalse(report['production_enabled'])
            self.assertEqual(len(json.loads((home/'hooks.json').read_text())['hooks']),4)

    def test_invalid_configuration_is_rejected_before_runtime_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);(home/'hooks.json').write_text('broken')
            with self.assertRaises(ValueError):install.install(home)
            self.assertFalse((home/'tv').exists())

if __name__=='__main__':unittest.main()
