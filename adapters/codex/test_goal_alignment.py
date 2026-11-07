import copy
import json
from pathlib import Path
import unittest
import test_process_gate as legacy
from process_gate import Guard, atomic_json


class GoalAlignment(unittest.TestCase):
    setUp = legacy.Workflow.setUp
    event = legacy.Workflow.event
    prompt = legacy.Workflow.prompt
    state = legacy.Workflow.state
    request = legacy.Workflow.request
    start = legacy.Workflow.start
    checks = legacy.Workflow.checks
    tool = legacy.Workflow.tool
    ready = legacy.Workflow.ready

    def goal(self, goal_id='G1', desc='生成本地报告'):
        self.request('requirements', requirements=[{'id': goal_id, 'desc': desc, 'kind': 'semantic'}])

    def test_new_turn_restores_goal_and_injects_unfinished_work(self):
        self.start();self.goal()
        context=self.prompt('现在进度怎么样？',turn_id='u2')
        current=self.request('inspect')
        self.assertIn('G1',[x['id'] for x in current['requirements']])
        self.assertIn('生成本地报告',context['hookSpecificOutput']['additionalContext'])
        self.assertIn('mainline',current)
        self.assertFalse(current.get('tasks'))

    def test_new_requirements_upsert_without_erasing_other_goal(self):
        self.start();self.goal();self.goal('G2','验证报告')
        self.assertEqual({x['id'] for x in self.request('inspect')['requirements']},{'G1','G2'})

    def test_explicit_turn_requirement_expires_but_goal_survives(self):
        self.start();self.goal()
        self.request('requirements',scope='turn',requirements=[{'id':'TEMP','desc':'本次回答简短','kind':'semantic'}])
        self.prompt('继续',turn_id='u2')
        self.assertEqual([x['id'] for x in self.request('inspect')['requirements']],['G1'])

    def test_recovery_after_new_process_returns_same_goals_and_progress(self):
        self.start();self.goal();self.g=Guard(self.g.root)
        self.assertIn('G1',[x['id'] for x in self.request('inspect')['requirements']])
        self.prompt('继续',turn_id='u2');self.g=Guard(self.g.root)
        self.assertIn('G1',[x['id'] for x in self.request('inspect')['requirements']])

    def test_schema5_migration_preserves_requirements_and_saves_original(self):
        self.start();self.goal()
        path,state=self.g.state('s1',self.g.registry()['sessions']['s1'])
        state['schema_version']=5;state.pop('mainline',None);state.pop('contract_version',None)
        atomic_json(path,state);before=path.read_bytes()
        self.prompt('继续',turn_id='u2')
        self.assertIn('G1',[x['id'] for x in self.request('inspect')['requirements']])
        self.assertEqual(self.state()['contract_version'],'goal-alignment-v1')
        backups=list((path.parent/'history').glob('migration-v5-*.json'))
        self.assertTrue(any(x.read_bytes()==before for x in backups))

    def test_mainline_compare_and_swap_rejects_stale_update(self):
        self.start();self.goal();revision=self.request('inspect')['mainline']['revision']
        self.request('mainline',expected_revision=revision,current_work={'goal_ids':['G1'],'next_step':'核对样本'})
        with self.assertRaises(ValueError):
            self.request('mainline',expected_revision=revision,current_work={'goal_ids':['G1'],'next_step':'覆盖'})

    def test_goal_retirement_needs_real_user_source_and_preserves_history(self):
        self.start();self.goal();revision=self.request('inspect')['mainline']['revision']
        with self.assertRaises(ValueError):
            self.request('mainline',expected_revision=revision,retire_ids=['G1'],source_turn='invented',reason='取消')
        self.prompt('取消生成报告',turn_id='u2')
        self.request('mainline',expected_revision=revision,retire_ids=['G1'],source_turn='u2',reason='用户明确取消报告')
        current=self.request('inspect')
        self.assertFalse(current['requirements'])
        self.assertTrue(current['mainline']['history'])

    def test_output_check_progress_is_available_next_turn(self):
        self.start();self.goal();self.request('inspect');self.request('think',candidate='报告尚未完成。');self.request('inspect')
        self.request('verify',results=self.checks()+[{'id':'G1','status':'unknown','reason':'尚未生成报告','evidence':[]}])
        self.request('decide',decision='partial',reason='如实说明进度')
        self.prompt('继续',turn_id='u2')
        progress=self.request('inspect')['mainline']['progress']
        self.assertEqual(progress['G1']['status'],'unknown')

    def test_same_gap_retry_count_survives_candidate_rewording(self):
        self.start()
        for i in range(3):
            self.request('inspect');self.request('think',candidate='候选'+str(i));self.request('inspect')
            rows=self.checks();rows[0]['status']='unknown';rows[0]['reason']='缺依据'
            self.request('verify',results=rows)
            self.request('decide',decision='retry',reason='自动恢复')
        self.request('inspect');self.request('think',candidate='再改写');self.request('inspect')
        rows=self.checks();rows[0].update(status='unknown',reason='缺依据')
        self.request('verify',results=rows)
        with self.assertRaises(ValueError):self.request('decide',decision='retry',reason='第四次')
        self.request('decide',decision='blocked',reason='如实保留缺口')

    def test_new_successful_relevant_evidence_allows_more_than_three_steps(self):
        self.start()
        for i in range(5):
            self.tool(args={'path':str(self.project/'a.txt')},result={'exit_code':0,'stdout':str(i)},tool_id='e'+str(i))
            self.request('inspect');self.request('think',candidate='第'+str(i)+'步');self.request('inspect')
            rows=self.checks();rows[0]['evidence']=['e'+str(i)]
            self.request('verify',results=rows)
            self.request('decide',decision='retry',reason='有新证据，继续任务')
        self.assertFalse(self.state()['turn'].get('tasks'))

    def test_unrelated_read_keeps_ready_output(self):
        self.start();self.ready()
        self.tool(args={'path':str(self.project/'unrelated.txt')},result={'exit_code':0,'stdout':'unrelated'})
        self.assertEqual(self.state()['turn']['output']['status'],'ready')
        self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='测试已完成。')), {})

    def test_changed_dependency_invalidates_output_but_keeps_unaffected_check(self):
        self.start();self.goal();self.tool(args={'path':str(self.project/'sample.txt')},tool_id='sample')
        self.request('inspect');self.request('think',candidate='样本已读取。');self.request('inspect')
        self.request('verify',results=self.checks()+[{'id':'G1','status':'satisfied','reason':'读取样本','evidence':['sample']}])
        self.request('decide',decision='output',reason='完成')
        self.tool(args={'path':str(self.project/'sample.txt')},result={'exit_code':0,'stdout':'changed'},tool_id='changed')
        current=self.request('inspect')
        self.assertEqual(current['output']['status'],'not_ready')
        self.assertIn('R1',current['valid_checks'])
        self.assertNotIn('G1',current['valid_checks'])
        self.request('inspect')
        self.request('verify',results=[{'id':'G1','status':'satisfied','reason':'重读更新内容','evidence':['changed']}])

    def test_repeated_identical_read_keeps_dependency_check(self):
        self.start();args={'path':str(self.project/'sample.txt')};result={'exit_code':0,'stdout':'same'}
        self.tool(args=args,result=result,tool_id='sample')
        self.request('inspect');self.request('think',candidate='内容已核查。');self.request('inspect')
        rows=self.checks();rows[0]['evidence']=['sample']
        self.request('verify',results=rows);self.request('decide',decision='output',reason='完成')
        self.tool(args=args,result=result,tool_id='repeat')
        self.assertEqual(self.state()['turn']['output']['status'],'ready')

    def test_unknown_effect_invalidates_output_conservatively(self):
        self.start();self.ready();self.request('inspect')
        args={'command':'unknown-effect'}
        self.request('permit',tool_name='Bash',tool_input=args,authorization_turn='u1',reason='测试未知动作的保守失效',results=self.checks())
        self.tool('Bash',args,result={'exit_code':1},tool_id='effect')
        self.assertEqual(self.state()['turn']['output']['status'],'not_ready')

    def test_pending_callback_survives_user_followup(self):
        self.start();args={'path':str(self.project/'a.txt')}
        self.g.handle(self.event(tool_name='read_file',tool_input=args,tool_use_id='pending'))
        self.prompt('现在进度？',turn_id='u2')
        self.g.handle(self.event('PostToolUse',turn_id='u2',tool_name='read_file',tool_input=args,tool_use_id='pending',tool_response={'exit_code':0}))
        current=self.request('inspect')
        self.assertNotIn('pending',current['pending']);self.assertIn('pending',current['evidence'])

    def test_status_reports_contract_and_no_host_execution_claim(self):
        status=self.g.status()
        self.assertEqual(status.get('contract_version'),'goal-alignment-v1')
        self.assertFalse(status['host_execution_verified'])

    def test_goal_change_requires_fresh_inspect_before_effect(self):
        self.start();self.goal();self.request('inspect');self.goal('G2','核对结果')
        with self.assertRaises(ValueError):
            self.request('permit',tool_name='Bash',tool_input={'command':'touch a'},authorization_turn='u1',reason='先回读变更后的主线',results=self.checks())

    def test_reworded_candidate_must_recheck_semantic_output_rules(self):
        self.start();self.ready('中文正文。')
        self.request('think',candidate='English text.')
        self.request('inspect')
        with self.assertRaises(ValueError):self.request('verify',results=[])

    def test_stale_resource_receipt_cannot_prove_current_success(self):
        self.start();self.tool(args={'path':str(self.project/'a.txt')},result={'exit_code':0,'stdout':'old'},tool_id='old')
        self.tool(args={'path':str(self.project/'a.txt')},result={'exit_code':0,'stdout':'new'},tool_id='new')
        self.request('inspect');self.request('think',candidate='内容已核验。');self.request('inspect')
        rows=self.checks();rows[0]['evidence']=['old']
        with self.assertRaises(ValueError):self.request('verify',results=rows)

    def test_rule_upsert_does_not_silently_remove_existing_constraint(self):
        self.start()
        self.request('rules',rules=[{'id':'R2','desc':'禁止发布','source':'user','kind':'semantic'}])
        self.assertEqual({r['id'] for r in self.request('inspect')['rules']},{'R1','R2'})

    def test_stop_candidate_rewording_does_not_reset_same_gap_limit(self):
        self.start()
        for i in range(3):
            self.request('inspect');self.request('think',candidate='候选'+str(i))
            self.assertEqual(self.g.handle(self.event('Stop',last_assistant_message='未核验'+str(i))).get('decision'),'block')
        self.request('think',candidate='再次改写')
        self.assertIs(self.g.handle(self.event('Stop',last_assistant_message='再次未核验')).get('continue'),False)

    def test_unknown_effect_marks_saved_goal_progress_unverified(self):
        self.start();self.goal();self.request('inspect');self.request('think',candidate='已生成报告。');self.request('inspect')
        self.request('verify',results=self.checks()+[{'id':'G1','status':'satisfied','reason':'测试语义条件','evidence':[]}])
        self.request('decide',decision='output',reason='通过')
        self.request('inspect');args={'command':'unknown-effect'}
        self.request('permit',tool_name='Bash',tool_input=args,authorization_turn='u1',goal_ids=['G1'],reason='核查保守失效',results=self.checks())
        self.tool('Bash',args,result={'exit_code':1},tool_id='effect')
        self.assertEqual(self.request('inspect')['mainline']['progress']['G1']['status'],'unknown')

    def test_saving_identical_goal_does_not_reset_mainline_version(self):
        self.start();self.goal();before=self.request('inspect')['mainline']['revision']
        self.goal();self.assertEqual(before,self.request('inspect')['mainline']['revision'])

    def test_effect_with_active_goals_requires_explicit_goal_reference(self):
        self.start();self.goal();self.request('inspect')
        with self.assertRaises(ValueError):
            self.request('permit',tool_name='Bash',tool_input={'command':'touch a'},authorization_turn='u1',reason='缺少动作所属目标',results=self.checks())

    def test_relative_resource_declaration_cannot_skip_invalidation(self):
        self.start()
        with self.assertRaises(ValueError):
            self.request('rules',rules=[{'id':'REL','desc':'核对文件','kind':'semantic','source':'user','resources':['a.txt']}])

    def test_directory_observation_invalidates_dependent_file_check(self):
        self.start();self.tool(args={'path':str(self.project/'a.txt')},tool_id='file')
        self.request('inspect');self.request('think',candidate='文件已核查。');self.request('inspect')
        rows=self.checks();rows[0]['evidence']=['file']
        self.request('verify',results=rows);self.request('decide',decision='output',reason='完成')
        self.tool('list_directory',{'path':str(self.project)},result={'success':True,'entries':[]},tool_id='directory')
        self.assertEqual(self.state()['turn']['output']['status'],'not_ready')
