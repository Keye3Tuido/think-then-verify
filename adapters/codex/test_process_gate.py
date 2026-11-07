import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from process_gate import Guard, GATE_ID, atomic_json

class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.project=self.base/'project';self.project.mkdir()
        subprocess.run(['git','init','-q',str(self.project)],check=True)
        self.g=Guard(self.base/'runtime')
        atomic_json(self.g.root/'registry.json',{'schema_version':1,'sessions':{}})
        self.serial=0
    def event(self,name='PreToolUse',**kw):
        return {'hook_event_name':name,'session_id':'s1','cwd':str(self.project),'turn_id':'u1',**kw}
    def prompt(self,p='/tv',**kw):return self.g.handle(self.event('UserPromptSubmit',prompt=p,**kw))
    def state(self):return self.g.state('s1',self.g.registry()['sessions']['s1'])[1]
    def request(self,action,**kw):
        return self.g.request('s1',{'action':action,'turn_id':self.state()['turn']['id'],**kw})
    def start(self):
        self.prompt()
        self.request('rules',rules=[{'id':'R1','desc':'使用中文','kind':'semantic','source':'user'}])
        self.request('inspect')
    def checks(self):return [{'id':'R1','status':'satisfied','reason':'候选正文为中文','evidence':[]}]
    def ready(self,text='测试已完成。'):
        self.request('inspect');self.request('think',candidate=text)
        self.request('inspect');self.request('verify',results=self.checks());self.request('decide',decision='output',reason='适用检查均已通过')
    def tool(self,name='read_file',args=None,result=None,tool_id='t1'):
        args=args or {'path':str(self.project/'a.txt')}
        pre=self.g.handle(self.event(tool_name=name,tool_input=args,tool_use_id=tool_id))
        if pre.get('hookSpecificOutput',{}).get('permissionDecision')!='deny':
            self.g.handle(self.event('PostToolUse',tool_name=name,tool_input=args,tool_use_id=tool_id,tool_response=result or {'exit_code':0}))
        return pre
    def test_default_off_and_other_session(self):
        self.assertEqual(self.g.handle(self.event(tool_name='Bash',tool_input={'command':'touch a'})),{})
        self.prompt();self.assertEqual(self.g.handle(self.event(session_id='other')), {})
    def test_missing_host_turn_id_uses_monotonic_real_user_sequence(self):
        self.prompt(turn_id=None);a=self.state()['turn']['id']
        self.prompt('继续',turn_id=None);b=self.state()['turn']['id']
        self.assertNotEqual(a,b);self.assertTrue(self.state()['activation']['enabled'])
    def test_off_precedes_corrupt_state_registry_and_missing_turn(self):
        self.prompt();p=self.g.state_path('s1',self.g.registry()['sessions']['s1']);p.write_text('broken')
        (self.g.root/'registry.json').write_text('broken')
        self.prompt('/tv off',turn_id=None)
        self.assertEqual(self.g.handle(self.event()),{});self.assertEqual(p.read_text(),'broken')
    def test_real_repeated_prompt_is_a_new_turn_without_ids(self):
        self.prompt(turn_id=None);a=self.state()['turn']['id']
        self.prompt(turn_id=None);self.assertNotEqual(a,self.state()['turn']['id'])
    def test_same_host_event_id_deduplicates_and_conflict_rejects(self):
        self.prompt();a=self.state()['turn']['id'];self.prompt();self.assertEqual(a,self.state()['turn']['id'])
        with self.assertRaises(ValueError):self.prompt('/tv changed')
    def test_cwd_switch_retains_binding(self):
        self.prompt();other=self.base/'other';other.mkdir()
        self.g.handle(self.event(cwd=str(other)))
        self.assertFalse((other/'.tv').exists());self.assertEqual(self.state()['initial_project_root'],str(self.project.resolve()))
    def test_read_only_can_collect_evidence_before_verification(self):
        self.start();pre=self.tool();self.assertNotEqual(pre.get('hookSpecificOutput',{}).get('permissionDecision'),'deny')
        self.assertEqual(self.state()['turn']['evidence']['t1']['outcome'],'success')
    def test_mixed_shell_is_not_a_read(self):
        self.start();out=self.tool('Bash',{'command':'cat a; touch b'})
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'],'deny')
    def test_effect_requires_exact_current_single_use_permit(self):
        self.start();args={'command':'touch a'}
        self.assertEqual(self.tool('Bash',args)['hookSpecificOutput']['permissionDecision'],'deny')
        self.request('permit',tool_name='Bash',tool_input=args,authorization_turn='u1',reason='用户要求创建测试文件',results=self.checks())
        out=self.tool('Bash',{'command':'touch b'},tool_id='other');self.assertEqual(out['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertNotEqual(self.tool('Bash',args)['hookSpecificOutput'].get('permissionDecision'),'deny')
        self.assertEqual(self.tool('Bash',args,tool_id='t2')['hookSpecificOutput']['permissionDecision'],'deny')
    def test_authorization_must_reference_observed_user_event(self):
        self.start()
        with self.assertRaises(ValueError):self.request('permit',tool_name='Bash',tool_input={'command':'touch a'},authorization_turn='invented',reason='授权',results=self.checks())
    def test_failed_and_unknown_results_cannot_be_success_evidence(self):
        self.start();self.tool(result={'exit_code':1})
        self.request('think',candidate='测试通过。')
        bad=self.checks();bad[0].update(evidence=['t1'],kind='observed')
        with self.assertRaises(ValueError):self.request('inspect');self.request('verify',results=bad)
    def test_missing_tool_callback_blocks_closure(self):
        self.start();self.g.handle(self.event(tool_name='read_file',tool_input={'path':'a'},tool_use_id='lost'))
        with self.assertRaises(ValueError):self.ready()
        out=self.g.handle(self.event('Stop',last_assistant_message='测试已完成。'))
        self.assertEqual(out.get('decision'),'block')
    def test_unknown_callback_does_not_create_evidence(self):
        self.start()
        self.g.handle(self.event('PostToolUse',tool_name='read_file',tool_input={'path':'a'},tool_use_id='unknown',tool_response={'exit_code':0}))
        self.assertNotIn('unknown',self.state()['turn']['evidence'])
    def test_stale_turn_request_rejected(self):
        self.start()
        with self.assertRaises(ValueError):self.g.request('s1',{'action':'think','turn_id':'old','candidate':'候选'})
    def test_cannot_skip_think_or_verify(self):
        self.start()
        with self.assertRaises(ValueError):self.request('inspect');self.request('verify',results=self.checks())
        self.request('think',candidate='候选')
        with self.assertRaises(ValueError):self.request('decide',decision='output',reason='完成')
    def test_rules_changed_after_read_invalidate_verification_and_permits(self):
        self.start();self.request('think',candidate='候选')
        self.request('rules',rules=[{'id':'R1','desc':'仅输出英文','kind':'semantic','source':'user'}])
        with self.assertRaises(ValueError):self.request('inspect');self.request('verify',results=self.checks())
    def test_all_rules_and_task_requirements_must_be_checked(self):
        self.start();self.request('requirements',requirements=[{'id':'Q1','desc':'本轮核验','kind':'semantic'}]);self.request('inspect');self.request('think',candidate='候选')
        with self.assertRaises(ValueError):self.request('inspect');self.request('verify',results=self.checks())
    def test_retry_limit_and_blocked_output_are_distinct(self):
        self.start()
        for i in range(4):
            self.request('inspect');self.request('think',candidate='候选')
            checks=self.checks();checks[0]['status']='unknown'
            self.request('inspect');self.request('verify',results=checks)
            if i<3:self.request('decide',decision='retry',reason='补齐证据')
        with self.assertRaises(ValueError):self.request('decide',decision='retry',reason='继续')
        with self.assertRaises(ValueError):self.request('decide',decision='output',reason='完成')
        self.request('decide',decision='blocked',reason='仍缺必要证据')
        out=self.g.handle(self.event('Stop',last_assistant_message='候选'))
        self.assertEqual(out,{});self.assertEqual(self.state()['turn']['closure'],'closed_blocked')
    def test_ready_is_not_delivery_and_stop_requires_actual_candidate_match(self):
        self.start();self.ready();self.assertEqual(self.state()['turn']['output']['status'],'ready')
        self.assertNotIn('delivered',self.state()['turn']['output'])
        out=self.g.handle(self.event('Stop',last_assistant_message='不同正文'))
        self.assertEqual(out.get('decision'),'block')
    def test_verified_stop_closes_without_faking_delivery(self):
        self.start();self.ready()
        self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='测试已完成。')), {})
        self.assertEqual(self.state()['turn']['closure'],'closed_verified')
        self.assertNotIn('delivery_event_id',self.state()['turn']['output'])
    def test_dependent_evidence_invalidates_ready_output(self):
        self.start();self.tool(tool_id='initial',result={'exit_code':0,'stdout':'old'})
        self.request('inspect');self.request('think',candidate='测试已完成。');self.request('inspect')
        rows=self.checks();rows[0]['evidence']=['initial']
        self.request('verify',results=rows);self.request('decide',decision='output',reason='完成')
        self.tool(result={'exit_code':0,'stdout':'changed'})
        self.assertNotEqual(self.state()['turn']['output']['status'],'ready')
        self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='测试已完成。')).get('decision'),'block')
    def test_repeated_stop_never_turns_missing_checks_into_success(self):
        self.start()
        for i in range(3):self.assertEqual(self.g.handle(self.event('Stop',stop_hook_active=True)).get('decision'),'block')
        final=self.g.handle(self.event('Stop',stop_hook_active=True))
        self.assertIs(final.get('continue'),False);self.assertEqual(self.state()['turn']['closure'],'halted_unverified')
    def test_internal_stop_continuation_does_not_reset_turn(self):
        self.start();turn=self.state()['turn']['id']
        out=self.g.handle(self.event('Stop'))
        self.g.handle(self.event('UserPromptSubmit',prompt=out['reason'],turn_id='host-resume'))
        self.assertEqual(self.state()['turn']['id'],turn)
    def test_rules_file_external_change_cannot_reuse_verify(self):
        self.start();self.ready();path=Path(self.state()['state_root'])/'rules.yml'
        data=json.loads(path.read_text());data['rules'][0]['desc']='英文';path.write_text(json.dumps(data))
        self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='测试已完成。')).get('decision'),'block')
    def test_post_callback_mismatch_does_not_claim_observed_success(self):
        self.start();args={'path':'a'}
        self.g.handle(self.event(tool_name='read_file',tool_input=args,tool_use_id='x'))
        self.g.handle(self.event('PostToolUse',tool_name='read_file',tool_input={'path':'b'},tool_use_id='x',tool_response={'exit_code':0}))
        self.assertNotIn('x',self.state()['turn']['evidence']);self.assertIn('x',self.state()['turn']['pending'])

class AdditionalRegressions(unittest.TestCase):
    setUp = Workflow.setUp
    event = Workflow.event
    prompt = Workflow.prompt
    state = Workflow.state
    request = Workflow.request
    start = Workflow.start
    checks = Workflow.checks
    ready = Workflow.ready
    tool = Workflow.tool
    def test_management_json_with_shell_symbols_is_safe_when_canonically_quoted(self):
        import shlex
        command=shlex.join(['python3',str(self.g.root/'process_gate.py'),'--session','s1','--request',json.dumps({'action':'think','candidate':'$HOME; `literal` \'quote\''})])
        self.assertTrue(self.g._management(self.event(tool_name='exec_command',tool_input={'cmd':command}),'s1'))
        self.assertFalse(self.g._management(self.event(tool_name='exec_command',tool_input={'cmd':command+'; touch bad'}),'s1'))
    def test_git_display_helpers_need_a_permit(self):
        self.assertFalse(self.g._read_only(self.event(tool_name='Bash',tool_input={'command':'git diff'})))
    def test_duplicate_callback_is_idempotent_but_conflict_is_rejected(self):
        self.start();args={'path':'a'};self.tool(args=args)
        ev=self.event('PostToolUse',tool_name='read_file',tool_input=args,tool_use_id='t1',tool_response={'exit_code':0})
        before=copy.deepcopy(self.state()['turn']['evidence']);self.g.handle(ev)
        self.assertEqual(before,self.state()['turn']['evidence'])
        ev['tool_response']={'exit_code':1}
        with self.assertRaises(ValueError):self.g.handle(ev)
    def test_replayed_enable_cannot_override_off(self):
        self.prompt();self.prompt('/tv off',turn_id='u2');self.prompt()
        self.assertFalse(self.g.control('s1')['enabled'])
    def test_no_text_at_stop_is_not_delivery_or_verified_closure(self):
        self.start();self.ready()
        self.assertEqual(self.g.handle(self.event('Stop')).get('decision'),'block')
        self.assertEqual(self.state()['turn']['closure'],'open')

class ScopeRegressions(unittest.TestCase):
    setUp = Workflow.setUp
    event = Workflow.event
    prompt = Workflow.prompt
    state = Workflow.state
    request = Workflow.request
    start = Workflow.start
    checks = Workflow.checks
    ready = Workflow.ready
    tool = Workflow.tool
    def test_future_task_outcome_is_not_a_precondition_for_running_its_action(self):
        self.start();self.request('requirements',requirements=[{'id':'Q1','desc':'任务测试通过','kind':'observed'}]);self.request('inspect')
        self.request('permit',tool_name='Bash',tool_input={'command':'touch a'},authorization_turn='u1',goal_ids=['Q1'],reason='执行已授权任务动作',results=self.checks())
        self.assertNotEqual(self.tool('Bash',{'command':'touch a'})['hookSpecificOutput'].get('permissionDecision'),'deny')
    def test_verify_requires_a_new_rules_read_in_verify_phase(self):
        self.start();self.request('think',candidate='候选')
        with self.assertRaises(ValueError):self.request('verify',results=self.checks())

class CoverageRegressions(unittest.TestCase):
    setUp = Workflow.setUp
    event = Workflow.event
    prompt = Workflow.prompt
    state = Workflow.state
    request = Workflow.request
    start = Workflow.start
    checks = Workflow.checks
    ready = Workflow.ready
    tool = Workflow.tool
    def test_untrusted_namespace_cannot_inherit_builtin_read_privileges(self):
        self.assertFalse(self.g._read_only(self.event(tool_name='untrusted__read_file',tool_input={'path':'a'})))
    def test_configured_search_helpers_are_not_implicitly_read_only(self):
        self.assertFalse(self.g._read_only(self.event(tool_name='Bash',tool_input={'command':'rg pattern .'})))
        self.assertTrue(self.g._read_only(self.event(tool_name='Bash',tool_input={'command':'rg --no-config pattern .'})))
    def test_effect_pre_callback_replay_cannot_execute_twice(self):
        self.start();args={'command':'touch a'}
        self.request('permit',tool_name='Bash',tool_input=args,authorization_turn='u1',reason='测试动作',results=self.checks())
        ev=self.event(tool_name='Bash',tool_input=args,tool_use_id='once')
        self.assertNotEqual(self.g.handle(ev)['hookSpecificOutput'].get('permissionDecision'),'deny')
        self.assertEqual(self.g.handle(ev)['hookSpecificOutput'].get('permissionDecision'),'deny')
    def test_old_off_replay_cannot_override_new_enable(self):
        self.prompt();self.prompt('/tv off',turn_id='u2');self.prompt('/tv',turn_id='u3');self.prompt('/tv off',turn_id='u2')
        self.assertTrue(self.g.control('s1')['enabled'])
    def test_internal_continuation_duplicate_does_not_become_a_user_turn(self):
        self.start();turn=self.state()['turn']['id'];out=self.g.handle(self.event('Stop'))
        ev=self.event('UserPromptSubmit',prompt=out['reason'],turn_id='resume')
        self.g.handle(ev);self.g.handle(ev);self.assertEqual(self.state()['turn']['id'],turn)
    def test_path_binding_tamper_is_not_accepted(self):
        self.prompt();r=self.g.registry()['sessions']['s1'];r['state_root']=str(self.base/'escape')
        with self.assertRaises(ValueError):self.g.state_path('s1',r)
    def test_explicit_off_still_works_when_control_record_is_damaged(self):
        self.prompt();self.g.control_path('s1').write_text('broken');self.prompt('/tv off',turn_id=None)
        self.assertFalse(self.g.control('s1')['enabled'])
        preserved=list(self.g.control_path('s1').parent.glob('*.corrupt-*'))
        self.assertTrue(any(p.read_text()=='broken' for p in preserved))

if __name__=='__main__':unittest.main()
