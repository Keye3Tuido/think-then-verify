import copy
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import process_gate
import register_gate

class Registration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.runtime=self.base/'tv';self.runtime.mkdir()
        shutil.copy2(process_gate.__file__,self.runtime/'process_gate.py')
    def test_four_unique_names_idempotence_and_foreign_positions(self):
        original={'hooks':{'PreToolUse':[{'hooks':[{'command':'foreign','statusMessage':'another-policy'}]}]}}
        saved=copy.deepcopy(original)
        with patch('register_gate.ROOT',self.runtime):
            first,_=register_gate.merged(original);second,_=register_gate.merged(first)
        self.assertEqual(first,second);self.assertEqual(original,saved)
        self.assertEqual(first['hooks']['PreToolUse'][0],saved['hooks']['PreToolUse'][0])
        labels=[h['statusMessage'] for groups in first['hooks'].values() for g in groups for h in g['hooks'] if register_gate.owned(h)]
        self.assertEqual(len(labels),4);self.assertEqual(set(labels),{process_gate.GATE_ID+'/'+x for x in ('UserPromptSubmit','PreToolUse','PostToolUse','Stop')})
    def test_conflicting_name_does_not_modify_config(self):
        original={'hooks':{'Stop':[{'hooks':[{'command':'foreign','statusMessage':process_gate.GATE_ID+'/PreToolUse'}]}]}}
        saved=copy.deepcopy(original)
        with patch('register_gate.ROOT',self.runtime):
            with self.assertRaises(ValueError):register_gate.merged(original)
        self.assertEqual(original,saved)
    def test_registration_disables_own_entries_without_granting_trust(self):
        hooks=self.base/'hooks.json';hooks.write_text(json.dumps({'hooks':{'PreToolUse':[{'hooks':[{'command':'foreign'}]}]}}))
        identity=f'{hooks}:pre_tool_use:0:0'
        config=self.base/'config.toml';config.write_text('[hooks.state.'+json.dumps(identity)+']\nenabled = true\ntrusted_hash = "keep"\n')
        with patch('register_gate.ROOT',self.runtime):register_gate.stage_disabled()
        states=tomllib.loads(config.read_text())['hooks']['state']
        self.assertEqual(states[identity],{'enabled':True,'trusted_hash':'keep'})
        self.assertEqual(len(states),5)
        self.assertTrue(all(v=={'enabled':False} for k,v in states.items() if k!=identity))
    def test_exact_pinned_commands_cover_native_event_protocol(self):
        project=self.base/'project';project.mkdir();subprocess.run(['git','init','-q',str(project)],check=True)
        with patch('register_gate.ROOT',self.runtime):config,_=register_gate.merged({'hooks':{}})
        entries={e:g[0]['hooks'][0] for e,g in config['hooks'].items()}
        def call(event,**more):
            r=subprocess.run(shlex.split(entries[event]['command']),input=json.dumps({'hook_event_name':event,'cwd':str(project),'session_id':'probe','turn_id':'u1',**more}),text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
        self.assertIn('additionalContext',call('UserPromptSubmit',prompt='/tv')['hookSpecificOutput'])
        self.assertIn('additionalContext',call('PreToolUse',tool_name='read_file',tool_input={'path':'a'},tool_use_id='t1')['hookSpecificOutput'])
        self.assertIn('additionalContext',call('PostToolUse',tool_name='read_file',tool_input={'path':'a'},tool_use_id='t1',tool_response={'exit_code':0})['hookSpecificOutput'])
        self.assertEqual(call('Stop',last_assistant_message='未经核验的正文').get('decision'),'block')
        self.assertEqual(call('UserPromptSubmit',prompt='/tv off',turn_id='u2'),{})
        self.assertEqual(call('Stop'),{})
    def test_pin_integrity_and_immutable_source(self):
        with patch('register_gate.ROOT',self.runtime):entry,checksum=register_gate.handler()
        payload=json.dumps({'hook_event_name':'PreToolUse','session_id':'unknown'})
        def run():return subprocess.run(shlex.split(entry['command']),input=payload,text=True,capture_output=True)
        self.assertEqual(run().returncode,0)
        script=self.runtime/'process_gate.py';script.write_text(script.read_text()+'\n# source updated\n')
        self.assertEqual(run().returncode,0)
        pin=self.runtime/'versions'/checksum/'process_gate.py';pin.write_text(pin.read_text()+'\n# tampered\n')
        self.assertEqual(run().returncode,2)
    def test_semantic_toml_header_preserves_foreign_trust(self):
        key='/tmp/hooks.json:pre_tool_use:1:0'
        text="[hooks.state.'"+key+"']\nenabled = true\ntrusted_hash = \"keep\"\n"
        updated=register_gate.disabled_config(text,[key])
        self.assertEqual(tomllib.loads(updated)['hooks']['state'][key],{'enabled':False,'trusted_hash':'keep'})
    def test_default_registration_never_enables(self):
        with patch.object(sys,'argv',['register_gate.py']):
            with self.assertRaises(SystemExit):register_gate.main()

if __name__=='__main__':unittest.main()
