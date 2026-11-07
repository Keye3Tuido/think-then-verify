import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
import test_process_gate as legacy
from process_gate import Guard, atomic_json, command_switch

class ActivationMigration(unittest.TestCase):
    setUp = legacy.Workflow.setUp
    event = legacy.Workflow.event
    prompt = legacy.Workflow.prompt
    state = legacy.Workflow.state
    request = legacy.Workflow.request

    def old_state(self, version=3):
        record = self.g.bind(self.g.registry(), 's1', str(self.project), {'event':'fixture'})
        path,state = self.g.state('s1',record)
        state.update(schema_version=version, activation={'enabled':False,'disabled_by_user_event':{'kind':'explicit_user_instruction'}}, turn={'id':'old-user','phase':'Preflight','preflight_status':'blocked','task_ids':{},'missing_capabilities':['old-unavailable-interface'],'output':{'status':'not_started'}}, user_events={'old-user':'legacy-hash'})
        state.pop('mainline',None);state.pop('contract_version',None)
        atomic_json(path,state)
        return path,path.read_bytes()

    def test_nonleading_skill_invocation_enables_and_survives_followup(self):
        self.prompt('再测试tv流程\n[$tv](/Users/user01/.agents/skills/tv/SKILL.md)')
        self.assertTrue((self.g.control('s1') or {}).get('enabled'))
        self.prompt('继续',turn_id='u2')
        self.assertTrue(self.g.control('s1')['enabled'])

    def test_quoted_or_fenced_mentions_do_not_enable(self):
        cases=['讨论 `[$tv](/Users/user01/.agents/skills/tv/SKILL.md)`', '> [$tv](/Users/user01/.agents/skills/tv/SKILL.md)', '示例：\n```text\n[$tv](/Users/user01/.agents/skills/tv/SKILL.md)\n```', '示例：\n~~~text\n[$tv](/Users/user01/.agents/skills/tv/SKILL.md)\n~~~', '    [$tv](/Users/user01/.agents/skills/tv/SKILL.md)']
        for text in cases:
            with self.subTest(text=text):self.assertIsNone(command_switch(text))

    def test_off_precedes_nonleading_invocation(self):
        self.assertIs(command_switch('/tv off\n[$tv](/Users/user01/.agents/skills/tv/SKILL.md)'),False)

    def test_schema3_native_activation_backs_up_and_preserves_legacy_records(self):
        path,before=self.old_state()
        response=self.prompt('[$tv](/Users/user01/.agents/skills/tv/SKILL.md) 重试',turn_id='u2')
        self.assertIn('additionalContext',response['hookSpecificOutput'])
        self.assertEqual(self.state()['schema_version'],6)
        self.assertTrue(self.g.control('s1')['enabled'])
        self.assertEqual(self.state()['user_events']['old-user'],'legacy-hash')
        self.assertEqual((path.parent/'history'/('migration-v3-'+hashlib.sha256(before).hexdigest()+'.json')).read_bytes(),before)
        archived=json.loads((path.parent/'history'/'old-user.json').read_text())
        self.assertEqual(archived['missing_capabilities'],['old-unavailable-interface'])
        self.assertEqual(self.state()['turn']['output']['status'],'not_ready')
        self.assertFalse(self.state()['turn']['permits'])

    def test_schema4_migration_retains_explicit_goals_and_rules(self):
        path,before=self.old_state(4);state=json.loads(before)
        state['turn']['requirements']=[{'id':'G1','desc':'保留未完成报告','kind':'semantic'}]
        atomic_json(path,state)
        rules=path.parent/'rules.yml';atomic_json(rules,{'rules':[{'id':'R1','desc':'禁止发布','kind':'semantic','source':'user'}]});original_rules=rules.read_bytes()
        self.prompt('/tv',turn_id='u2')
        self.assertIn('G1',[r['id'] for r in self.request('inspect')['requirements']])
        self.assertEqual(rules.read_bytes(),original_rules)

    def test_explicit_migration_does_not_enable_session_or_invent_user_event(self):
        path,before=self.old_state()
        result=self.g.migrate('s1')
        self.assertEqual(result['schema_version'],6)
        self.assertFalse(self.state()['activation']['enabled'])
        self.assertIsNone(self.g.control('s1'))
        self.assertEqual(self.state()['user_events'],{'old-user':'legacy-hash'})
        self.assertFalse(self.state()['turn']['pending'])
        once=path.read_bytes();self.g.migrate('s1');self.assertEqual(path.read_bytes(),once)

    def test_unknown_legacy_schema_remains_untouched(self):
        path,before=self.old_state(99)
        with self.assertRaises(ValueError):self.g.migrate('s1')
        self.assertEqual(path.read_bytes(),before)

    def test_migration_maintenance_uses_exact_session_and_arguments(self):
        script=str(self.g.root/'process_gate.py')
        def check(command):return self.g._management(self.event(tool_name='Bash',tool_input={'command':command}),'s1')
        self.assertTrue(check('python3 '+script+' --session s1 --migrate-state'))
        self.assertFalse(check('python3 '+script+' --session s2 --migrate-state'))
        self.assertFalse(check('python3 '+script+' --session s1 --migrate-state extra'))

    def test_malformed_legacy_requirements_are_not_silently_dropped(self):
        path,before=self.old_state();state=json.loads(before);state['turn']['requirements']=[{'id':'bad'}];atomic_json(path,state);before=path.read_bytes()
        with self.assertRaises(ValueError):self.g.migrate('s1')
        self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
