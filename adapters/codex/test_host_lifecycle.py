"""Native-shaped receipts and terminal blocked output must not create resume loops."""
import unittest
import test_process_gate as legacy
from process_gate import Guard

class HostLifecycle(unittest.TestCase):
    setUp=legacy.Workflow.setUp
    event=legacy.Workflow.event
    prompt=legacy.Workflow.prompt
    state=legacy.Workflow.state
    request=legacy.Workflow.request
    start=legacy.Workflow.start
    checks=legacy.Workflow.checks
    tool=legacy.Workflow.tool
    ready=legacy.Workflow.ready

    def lost(self):
        self.g.handle(self.event(tool_name='read_file',tool_input={'path':'a'},tool_use_id='lost'))

    def blocked(self,decision='blocked'):
        self.request('inspect');self.request('think',candidate='调用回执缺失，未完成。')
        self.request('inspect');self.request('verify',results=self.checks())
        return self.request('decide',decision=decision,reason='真实回执缺失，保留未完成状态',unresolved_calls=['lost'])

    def test_blocked_report_can_finish_without_fabricating_a_callback(self):
        self.start();self.lost();self.blocked()
        self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='调用回执缺失，未完成。')), {})
        t=self.state()['turn']
        self.assertEqual(t['closure'],'closed_blocked_unresolved')
        self.assertIn('lost',t['pending'])
        self.assertNotIn('lost',t['evidence'])

    def test_partial_report_does_not_resume_forever(self):
        self.start();self.lost();self.blocked('partial')
        for _ in range(5):
            self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='调用回执缺失，未完成。')), {})
        self.assertEqual(self.state()['turn']['closure'],'closed_partial_unresolved')

    def test_pending_success_cannot_be_declared_ready(self):
        self.start();self.lost()
        self.request('inspect');self.request('think',candidate='已完成。');self.request('inspect')
        self.request('verify',results=self.checks())
        with self.assertRaises(ValueError):self.request('decide',decision='output',reason='错误地当作完成')

    def test_unresolved_calls_need_exact_explicit_acknowledgement(self):
        self.start();self.lost()
        self.request('inspect');self.request('think',candidate='调用回执缺失，未完成。');self.request('inspect')
        self.request('verify',results=self.checks())
        with self.assertRaises(ValueError):self.request('decide',decision='blocked',reason='缺少明确待决集合')

    def test_unknown_native_text_remains_unknown_with_explicit_reason(self):
        self.start();self.tool(result='one\n')
        receipt=self.state()['turn']['evidence']['t1']
        self.assertEqual(receipt['outcome'],'unknown')
        self.assertEqual(receipt['outcome_reason'],'host_status_unavailable')

    def test_json_looking_stdout_cannot_claim_success(self):
        self.start();self.tool(result='{"exit_code":0}')
        self.assertEqual(self.state()['turn']['evidence']['t1']['outcome'],'unknown')

    def test_native_structured_exit_code_alias(self):
        self.start();self.tool(result={'exitCode':7})
        self.assertEqual(self.state()['turn']['evidence']['t1']['outcome'],'failure')

    def test_pending_is_retained_across_real_followup_and_partial_can_close(self):
        self.start();self.lost();self.prompt('现在进展如何？',turn_id='u2')
        self.blocked('partial')
        self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='调用回执缺失，未完成。')), {})
        self.assertIn('lost',self.state()['turn']['pending'])
        self.assertTrue(self.state()['activation']['enabled'])

if __name__=='__main__':unittest.main()
