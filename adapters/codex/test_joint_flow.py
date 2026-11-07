"""End-to-end host simulation using real Git and both production event handlers."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from process_gate import Guard, atomic_json
import register_gate

DOC_ROOT=Path(os.environ.get('TV_DOC_SYSTEM', str(Path.home()/'.agent-docs')))

def load_doc():
    p=DOC_ROOT/'scripts/doc-workflow.py'
    spec=importlib.util.spec_from_file_location('doc_joint_workflow',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

class JointFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.project=self.base/'project';self.project.mkdir()
        self.git('init','-q');self.git('config','user.name','Isolated simulator')
        self.git('config','user.email','simulation@example.invalid')
        self.write('.agent-docs/_index.md','---\nschema_version: 7\nproject_config:\n  initial_bootstrap_done: false\n---\n')
        self.write('.agent-docs/doc-library/main-module.md','---\nschema_version: 7\n---\n\n## 定位\n\n读取 src.txt 并返回文本。\n')
        self.write('src.txt','one\n');self.git('add','.');self.git('commit','-qm','base')
        self.doc=load_doc();self.g=getattr(self, 'guard_factory', Guard)(self.base/'runtime')
        self.g.handle(self.event('UserPromptSubmit',prompt='/tv 验证隔离流程'))
        self.req('rules',rules=[{'id':'LOCAL','desc':'只操作隔离项目并如实报告','kind':'semantic','source':'u1'}])
        self.req('requirements',requirements=[{'id':'FLOW','desc':'隔离流程验证','kind':'observed'}])
        self.req('inspect');self.serial=0

    def write(self,path,text):
        p=self.project/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    def git(self,*args):
        return subprocess.run(['git','-C',str(self.project),*args],check=True,capture_output=True,text=True).stdout.strip()
    def event(self,name,**kw):
        return dict(hook_event_name=name,session_id='joint',turn_id='u1',cwd=str(self.project),**kw)
    def req(self,action,**kw):
        return self.g.request('joint',dict(action=action,turn_id=self.state()['turn']['id'],**kw))
    def state(self):
        return self.g.state('joint',self.g.registry()['sessions']['joint'])[1]
    def rows(self):return [{'id':'LOCAL','status':'satisfied','reason':'隔离项目','evidence':[]}]
    def sync(self):
        source=self.doc.inspect(self.project)['source']
        self.doc.complete(self.project,source,'仿真核验：实际读取 src.txt，职责与文档对应。')
    def dispatch(self,argv,raw=False):
        self.serial+=1;call='call-'+str(self.serial);command=shlex.join(argv)
        data=dict(tool_name='Bash',tool_input={'command':command},tool_use_id=call)
        self.req('inspect');self.req('permit',tool_name='Bash',tool_input={'command':command},
            authorization_turn='u1',goal_ids=['FLOW'],reason='执行隔离仿真动作',results=self.rows())
        tv=self.g.handle(self.event('PreToolUse',**data))
        self.assertNotEqual(tv.get('hookSpecificOutput',{}).get('permissionDecision'),'deny')
        before=self.doc.hook(self.event('PreToolUse',**data))
        if before.get('hookSpecificOutput',{}).get('permissionDecision')=='deny':
            return call,None,before
        p=subprocess.run(argv,cwd=self.project,capture_output=True,text=True)
        response=p.stdout if raw else {'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
        self.g.handle(self.event('PostToolUse',tool_response=response,**data))
        after=self.doc.hook(self.event('PostToolUse',tool_response=response,**data))
        return call,p,after
    def finish(self,text,evidence=None,unresolved=None):
        self.req('inspect');self.req('think',candidate=text);self.req('inspect')
        rows=self.rows()+[{'id':'FLOW','status':'satisfied' if evidence else 'unknown',
            'reason':'实际工具回执' if evidence else '宿主缺少可靠执行状态',
            'evidence':[evidence] if evidence else []}]
        self.req('verify',results=rows)
        self.req('decide',decision='output' if evidence else 'partial',
            reason='成功依据齐全' if evidence else '如实说明未完成部分',
            unresolved_calls=unresolved or [])
        return self.g.handle(self.event('Stop',last_assistant_message=text))
    def cli(self,action,*args):
        return subprocess.run([sys.executable,str(DOC_ROOT/'scripts/doc-commit-review.py'),
            action,'--project',str(self.project),*args],capture_output=True,text=True)

    def test_document_denial_is_settled_from_matching_policy_receipt(self):
        call,p,denial=self.dispatch(['cat','src.txt'])
        self.assertIsNone(p);self.assertEqual(denial['hookSpecificOutput']['permissionDecision'],'deny')
        state=self.req('inspect')
        self.assertNotIn(call,state['pending'])
        self.assertEqual(state['evidence'][call]['outcome'],'denied')
        self.assertEqual(state['evidence'][call]['receipt_kind'],'policy_denial')
        self.assertEqual(self.finish('首次读取被文档检查拒绝，等待核验。'),{})

    def test_complete_read_write_review_commit_and_both_stops(self):
        call,p,_=self.dispatch(['cat','src.txt']);self.assertIsNone(p)
        self.req('inspect');self.sync()
        _,p,_=self.dispatch(['cat','src.txt']);self.assertEqual(p.stdout,'one\n')
        failed,p,after=self.dispatch([sys.executable,'-c',
            "from pathlib import Path; Path('src.txt').write_text('two\\n'); raise SystemExit(7)"])
        self.assertEqual(p.returncode,7)
        self.assertEqual((self.project/'src.txt').read_text(),'two\n')
        self.assertIn('additionalContext',after['hookSpecificOutput'])
        self.assertEqual(self.state()['turn']['evidence'][failed]['outcome'],'failure')
        self.assertEqual(self.doc.hook(self.event('Stop'))['decision'],'block')
        self.doc.inspect(self.project)
        self.write('.agent-docs/doc-library/main-module.md',
            '---\nschema_version: 7\n---\n\n## 定位\n\n读取 src.txt 并返回文本。\n\n## 业务逻辑\n\n返回文件当前保存的完整文本。\n')
        self.sync();self.assertEqual(self.doc.hook(self.event('Stop')), {})
        self.assertEqual(self.cli('install').returncode,0)
        self.git('add','.');self.sync()
        report=self.cli('prepare');self.assertEqual(report.returncode,0,report.stderr)
        review=json.loads(report.stdout);self.assertIn('业务逻辑',Path(review['report']).read_text())
        before=self.git('rev-parse','HEAD')
        _,p,_=self.dispatch(['git','commit','-qm','must be refused'])
        self.assertNotEqual(p.returncode,0);self.assertEqual(self.git('rev-parse','HEAD'),before)
        # This is the simulator's human actor, scoped to its temporary Git repository.
        approved=self.cli('approve','--digest',review['digest'],'--reason','SIMULATED_HUMAN_REVIEW: inspected exact temporary report')
        self.assertEqual(approved.returncode,0,approved.stderr)
        receipt,p,_=self.dispatch(['git','commit','-qm','isolated reviewed commit'])
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotEqual(self.git('rev-parse','HEAD'),before)
        self.sync()
        self.assertEqual(self.doc.hook(self.event('Stop')), {})
        self.assertEqual(self.finish('隔离流程验证通过。',evidence=receipt),{})
        self.assertEqual(self.state()['turn']['closure'],'closed_verified')
        self.assertFalse(self.state()['turn']['pending'])

    def test_native_raw_text_is_unknown_and_can_report_partial_without_loop(self):
        self.sync();call,p,_=self.dispatch(['cat','src.txt'],raw=True)
        self.assertEqual(p.returncode,0)
        self.assertEqual(self.state()['turn']['evidence'][call]['outcome'],'unknown')
        self.assertEqual(self.finish('已读取文本；宿主没有执行状态，验证保留未知。'), {})
        self.assertEqual(self.state()['turn']['closure'],'closed_partial')

    def test_joint_registration_is_idempotent_unique_and_preserves_foreign_policy(self):
        foreign={'hooks':{'Stop':[{'hooks':[{'command':'foreign','statusMessage':'foreign'}]}]}}
        runtime=self.base/'registration';runtime.mkdir()
        runtime.joinpath('process_gate.py').write_bytes(Path(register_gate.__file__).with_name('process_gate.py').read_bytes())
        with patch('register_gate.ROOT',runtime):
            first,_=register_gate.merged(self.doc.registration(foreign))
            second,_=register_gate.merged(self.doc.registration(first))
        self.assertEqual(first,second)
        names=[h.get('statusMessage') for groups in first['hooks'].values() for g in groups for h in g['hooks']]
        self.assertEqual(len(names),8);self.assertEqual(len(set(names)),8)
        self.assertEqual(first['hooks']['Stop'][0],foreign['hooks']['Stop'][0])

    def test_denial_with_wrong_call_parameters_is_not_a_tool_receipt(self):
        call,p,_=self.dispatch(['cat','src.txt'])
        journal=self.doc.state_path(self.project).with_name('observations.jsonl')
        rows=[json.loads(line) for line in journal.read_text().splitlines()]
        rows[-1]['action_sha256']='wrong'
        journal.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        current=self.req('inspect');self.assertIn(call,current['pending'])
        self.assertNotIn(call,current['evidence'])
        self.assertEqual(self.finish('调用未执行且无可核实回执，保持未完成。',unresolved=[call]),{})

    def test_denial_from_another_session_cannot_settle_current_call(self):
        call,p,_=self.dispatch(['cat','src.txt'])
        journal=self.doc.state_path(self.project).with_name('observations.jsonl')
        rows=[json.loads(line) for line in journal.read_text().splitlines()]
        rows[-1]['session_id']='other'
        journal.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        current=self.req('inspect');self.assertIn(call,current['pending'])
        self.assertEqual(self.finish('其他会话记录不能作为本次调用依据。',unresolved=[call]),{})

    def test_policy_receipt_is_idempotent_and_does_not_authorize_replay(self):
        call,p,_=self.dispatch(['cat','src.txt'])
        first=self.req('inspect')['evidence'][call]
        second=self.req('inspect')['evidence'][call];self.assertEqual(first,second)
        with self.assertRaises(ValueError):
            self.g.handle(self.event('PreToolUse',tool_name='Bash',tool_input={'command':'cat src.txt'},tool_use_id=call))

class SubprocessGuard:
    """Run exact pinned commands and management CLI in fresh processes."""
    def __init__(self, root):
        import shutil
        self.root=Path(root);self.root.mkdir(parents=True)
        shutil.copy2(Path(register_gate.__file__).with_name('process_gate.py'),self.root/'process_gate.py')
        with patch('register_gate.ROOT',self.root):
            self.config,_=register_gate.merged({'hooks':{}})
        self.delegate=Guard(self.root)
    def handle(self,event):
        command=self.config['hooks'][event['hook_event_name']][0]['hooks'][0]['command']
        r=subprocess.run(shlex.split(command),input=json.dumps(event),text=True,capture_output=True,timeout=15)
        if r.returncode:raise RuntimeError(r.stderr)
        return json.loads(r.stdout)
    def request(self,session,request):
        r=subprocess.run([sys.executable,str(self.root/'process_gate.py'),'--session',session,
            '--request',json.dumps(request)],text=True,capture_output=True,timeout=15)
        if r.returncode:raise ValueError(r.stderr)
        return json.loads(r.stdout)
    def registry(self):return self.delegate.registry()
    def state(self,*args):return self.delegate.state(*args)

class NativeProtocolJoint(unittest.TestCase):
    guard_factory=SubprocessGuard
    setUp=JointFlow.setUp
    write=JointFlow.write
    git=JointFlow.git
    event=JointFlow.event
    req=JointFlow.req
    state=JointFlow.state
    rows=JointFlow.rows
    sync=JointFlow.sync
    dispatch=JointFlow.dispatch
    finish=JointFlow.finish
    cli=JointFlow.cli

    def test_full_workflow_through_exact_pinned_hook_commands(self):
        JointFlow.test_complete_read_write_review_commit_and_both_stops(self)

if __name__=='__main__':unittest.main()
