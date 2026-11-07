import json
import shlex
import unittest
from process_gate import digest, atomic_json
from host_receipts import reconcile
import test_process_gate as legacy


class HostReceipts(unittest.TestCase):
    setUp = legacy.Workflow.setUp
    event = legacy.Workflow.event
    prompt = legacy.Workflow.prompt
    state = legacy.Workflow.state
    request = legacy.Workflow.request
    checks = legacy.Workflow.checks
    start = legacy.Workflow.start

    def fixture(self, code=0):
        self.start()
        command = 'python3 -m unittest -q'
        self.request('permit', tool_name='Bash', tool_input={'command': command},
                     authorization_turn='u1', reason='运行测试', results=self.checks())
        self.g.handle(self.event(tool_name='Bash', tool_input={'command': command}, tool_use_id='run'))
        self.g.handle(self.event('PostToolUse', tool_name='Bash', tool_input={'command': command},
                                 tool_use_id='run', tool_response='{"exit_code":0}'))
        receipt = {'content': [{'type': 'text', 'text': json.dumps({
            'thread': {'id': 's1', 'kind': 'codex', 'hostId': 'local'},
            'turns': [{'id': 'host-u1', 'items': [{'type': 'commandExecution', 'id': 'run',
                'command': shlex.join(['/bin/zsh', '-lc', command]), 'cwd': str(self.project),
                'status': 'completed' if code == 0 else 'failed', 'exitCode': code}]}]})}], 'isError': False}
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['evidence']['lookup'] = {'tool_name': 'mcp__codex_app__read_thread',
            'outcome': 'success', 'response_sha256': digest(receipt)}
        atomic_json(path, state)
        return receipt

    def test_attested_success_and_idempotence(self):
        receipt = self.fixture()
        self.assertEqual(reconcile(self.g, 's1', 'lookup', receipt)['confirmed'], {'run': 'success'})
        self.assertEqual(reconcile(self.g, 's1', 'lookup', receipt)['confirmed'], {})

    def test_real_failure_beats_success_looking_stdout(self):
        receipt = self.fixture(7)
        reconcile(self.g, 's1', 'lookup', receipt)
        self.assertEqual(self.state()['turn']['evidence']['run']['outcome'], 'failure')

    def test_failed_host_status_is_not_success_even_with_zero_exit(self):
        receipt = self.fixture()
        host = json.loads(receipt['content'][0]['text'])
        host['turns'][0]['items'][0]['status'] = 'failed'
        receipt['content'][0]['text'] = json.dumps(host)
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['evidence']['lookup']['response_sha256'] = digest(receipt)
        atomic_json(path, state)
        reconcile(self.g, 's1', 'lookup', receipt)
        self.assertEqual(self.state()['turn']['evidence']['run']['outcome'], 'failure')

    def test_forged_body_rejected(self):
        receipt = self.fixture()
        receipt['content'][0]['text'] += ' '
        with self.assertRaises(ValueError): reconcile(self.g, 's1', 'lookup', receipt)
        self.assertEqual(self.state()['turn']['evidence']['run']['outcome'], 'unknown')

    def test_wrong_session_rejected_even_with_attested_lookup(self):
        receipt = self.fixture()
        host = json.loads(receipt['content'][0]['text']);host['thread']['id'] = 'other'
        receipt['content'][0]['text'] = json.dumps(host)
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['evidence']['lookup']['response_sha256'] = digest(receipt);atomic_json(path, state)
        with self.assertRaises(ValueError): reconcile(self.g, 's1', 'lookup', receipt)

    def replace_host(self, receipt, host):
        receipt['content'][0]['text'] = json.dumps(host)
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['evidence']['lookup']['response_sha256'] = digest(receipt)
        atomic_json(path, state)

    def test_truncated_command_is_skipped_without_losing_other_receipts(self):
        receipt = self.fixture()
        host = json.loads(receipt['content'][0]['text'])
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['pending']['truncated'] = dict(state['turn']['evidence']['run'])
        atomic_json(path, state)
        host['turns'][0]['items'].insert(0, {'type':'commandExecution', 'id':'truncated',
            'command':"/bin/zsh -lc 'unfinished", 'commandTruncated':True,
            'cwd':str(self.project), 'status':'completed', 'exitCode':0})
        self.replace_host(receipt, host)
        result = reconcile(self.g, 's1', 'lookup', receipt)
        self.assertEqual(result['confirmed'], {'run':'success'})
        self.assertIn('truncated', result['pending'])

    def test_failed_mcp_callback_gap_is_closed_from_exact_native_metadata(self):
        receipt = self.fixture()
        host = json.loads(receipt['content'][0]['text'])
        args = {'threadId':'s1', 'maxOutputCharsPerItem':200000}
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['pending']['failed-query'] = {
            'tool_name':'mcp__codex_app__read_thread', 'kind':'effect',
            'action_sha256':digest(['mcp__codex_app__read_thread', args]), 'resources':['*']}
        atomic_json(path, state)
        host['turns'][0]['items'].append({'type':'mcpToolCall','id':'failed-query',
            'server':'codex_app','tool':'read_thread','arguments':args,'status':'failed'})
        self.replace_host(receipt, host)
        self.assertEqual(reconcile(self.g, 's1', 'lookup', receipt)['confirmed']['failed-query'], 'failure')
        self.assertNotIn('failed-query', self.state()['turn']['pending'])

    def test_failed_mcp_with_changed_arguments_cannot_close_pending(self):
        receipt = self.fixture()
        host = json.loads(receipt['content'][0]['text'])
        args = {'threadId':'s1'}
        path, state = self.g.state('s1', self.g.registry()['sessions']['s1'])
        state['turn']['pending']['failed-query'] = {
            'tool_name':'mcp__codex_app__read_thread', 'kind':'effect',
            'action_sha256':digest(['mcp__codex_app__read_thread', args]), 'resources':['*']}
        atomic_json(path, state)
        host['turns'][0]['items'].append({'type':'mcpToolCall','id':'failed-query',
            'server':'codex_app','tool':'read_thread','arguments':{'threadId':'other'},'status':'failed'})
        self.replace_host(receipt, host)
        with self.assertRaises(ValueError):
            reconcile(self.g, 's1', 'lookup', receipt)
        self.assertIn('failed-query', self.state()['turn']['pending'])
        self.assertEqual(self.state()['turn']['evidence']['run']['outcome'], 'unknown')

    def test_completed_mcp_without_result_is_not_invented_success(self):
        receipt = self.fixture()
        host = json.loads(receipt['content'][0]['text'])
        host['turns'][0]['items'][0] = {'type':'mcpToolCall','id':'run',
            'server':'codex_app','tool':'read_thread','arguments':{},'status':'completed'}
        self.replace_host(receipt, host)
        self.assertEqual(reconcile(self.g, 's1', 'lookup', receipt)['confirmed'], {})
        self.assertEqual(self.state()['turn']['evidence']['run']['outcome'], 'unknown')

    def test_management_is_exact_and_session_scoped(self):
        self.start()
        args = ['python3', str(self.g.root/'host_receipts.py'), '--session', 's1',
                '--evidence-id', 'lookup', '--receipt-file', str(self.project/'receipt.json')]
        self.assertTrue(self.g._management(self.event(tool_name='Bash', tool_input={'command':shlex.join(args)}),'s1'))
        self.assertFalse(self.g._management(self.event(tool_name='Bash', tool_input={'command':shlex.join(args)}),'other'))

if __name__ == '__main__': unittest.main()
