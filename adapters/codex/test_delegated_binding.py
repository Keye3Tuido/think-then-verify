"""A delegated TV session inherits real authorization without a new user prompt."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_process_gate as legacy
from process_gate import digest


class DelegatedBinding(unittest.TestCase):
    setUp = legacy.Workflow.setUp
    event = legacy.Workflow.event
    prompt = legacy.Workflow.prompt
    state = legacy.Workflow.state
    request = legacy.Workflow.request
    start = legacy.Workflow.start
    checks = legacy.Workflow.checks
    tool = legacy.Workflow.tool

    def lookup(self, tool_name='mcp__codex_app__read_thread'):
        self.start()
        self.child = self.base / 'child'
        self.child.mkdir()
        self.receipt = {'content': [{'type': 'text', 'text': json.dumps({
            'schemaVersion': 1,
            'thread': {'id': 'child-session', 'kind': 'codex', 'hostId': 'local',
                       'cwd': str(self.child), 'status': {'type': 'idle'}},
            'turns': [{'id': 'child-native-turn', 'status': 'completed', 'items': []}]
        })}], 'isError': False}
        args = {'threadId': 'child-session', 'hostId': 'local', 'turnLimit': 1}
        self.request('permit', tool_name=tool_name, tool_input=args,
                     authorization_turn='u1', reason='User requests TV in the child conversation',
                     results=self.checks())
        self.tool(tool_name, args, self.receipt, 'host-lookup')
        return {'authorization_turn': 'u1', 'child_session': 'child-session',
                'evidence_id': 'host-lookup', 'host_receipt': self.receipt,
                'reason': 'User explicitly requests an isolated child using TV'}

    def run_binding(self, request):
        result = subprocess.run([
            sys.executable, str(Path(__file__).with_name('delegate_session.py')),
            '--runtime', str(self.g.root), '--parent-session', 's1',
            '--request', json.dumps(request)
        ], text=True, capture_output=True)
        return result

    def test_verified_host_identity_binds_without_child_user_prompt(self):
        result = self.run_binding(self.lookup())
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.g.registry()['sessions']['child-session']
        state = self.g.state('child-session', record)[1]
        self.assertTrue(state['activation']['enabled'])
        self.assertEqual(state['turn']['id'], 'child-native-turn')
        source = state['activation']['activated_by_delegation']
        self.assertEqual(source['parent_session'], 's1')
        self.assertEqual(source['parent_user_turn'], 'u1')
        self.assertEqual(source['identity_receipt_sha256'], digest(self.receipt))
        self.assertNotIn('activated_by_user_event', state['activation'])
        # The existing native gate must consume the binding without a new Hook.
        event = self.event(session_id='child-session', cwd=str(self.child),
                           turn_id='child-native-turn', tool_name='Bash',
                           tool_input={'command': 'touch business'}, tool_use_id='no-permit')
        self.assertEqual(self.g.handle(event)['hookSpecificOutput']['permissionDecision'], 'deny')
        self.g.request('child-session', {'action': 'rules', 'turn_id': 'child-native-turn',
                                        'rules': [{'id': 'CHILD', 'desc': 'Isolated only', 'kind': 'semantic'}]})
        context = self.g.request('child-session', {'action': 'inspect'})
        self.assertIn('R1', {row['id'] for row in context['rules']})
        self.g.request('child-session', {'action': 'permit', 'turn_id': 'child-native-turn',
            'tool_name': 'Bash', 'tool_input': {'command': 'touch business'},
            'authorization_turn': 'child-native-turn', 'reason': 'Inherited user task',
            'results': [{'id': row['id'], 'status': 'satisfied', 'reason': 'Within child scope', 'evidence': []} for row in context['rules']]})
        event['tool_use_id'] = 'permitted'
        self.assertNotEqual(self.g.handle(event)['hookSpecificOutput'].get('permissionDecision'), 'deny')

    def test_forged_receipt_does_not_bind(self):
        request = self.lookup()
        request['host_receipt'] = copy.deepcopy(self.receipt)
        request['host_receipt']['content'][0]['text'] += ' '
        self.assertNotEqual(self.run_binding(request).returncode, 0)
        self.assertNotIn('child-session', self.g.registry()['sessions'])

    def test_unknown_user_source_does_not_bind(self):
        request = self.lookup()
        request['authorization_turn'] = 'invented'
        self.assertNotEqual(self.run_binding(request).returncode, 0)
        self.assertNotIn('child-session', self.g.registry()['sessions'])

    def test_other_child_identity_does_not_bind(self):
        request = self.lookup()
        request['child_session'] = 'some-other-chat'
        self.assertNotEqual(self.run_binding(request).returncode, 0)
        self.assertNotIn('some-other-chat', self.g.registry()['sessions'])

    def test_arbitrary_tool_json_is_not_host_identity(self):
        request = self.lookup('untrusted__read_thread')
        self.assertNotEqual(self.run_binding(request).returncode, 0)

    def test_disabled_child_is_never_reenabled_by_delegation(self):
        request = self.lookup()
        self.g.handle(self.event('UserPromptSubmit', session_id='child-session',
                                cwd=str(self.child), prompt='/tv off', turn_id='off-turn'))
        self.assertNotEqual(self.run_binding(request).returncode, 0)
        self.assertFalse(self.g.control('child-session')['enabled'])

    def test_repeat_is_idempotent_and_preserves_child_state(self):
        request = self.lookup()
        self.assertEqual(self.run_binding(request).returncode, 0)
        path = self.g.state_path('child-session', self.g.registry()['sessions']['child-session'])
        before = path.read_bytes()
        self.assertEqual(self.run_binding(request).returncode, 0)
        self.assertEqual(before, path.read_bytes())

    def test_parent_off_cannot_delegate(self):
        request = self.lookup()
        self.prompt('/tv off', turn_id='u2')
        self.assertNotEqual(self.run_binding(request).returncode, 0)
        self.assertNotIn('child-session', self.g.registry()['sessions'])

    def test_current_scope_explanation_is_required(self):
        request = self.lookup()
        request['reason'] = ''
        self.assertNotEqual(self.run_binding(request).returncode, 0)


if __name__ == '__main__':
    unittest.main()
