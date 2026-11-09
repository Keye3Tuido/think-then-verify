#!/usr/bin/env python3
"""Run isolated TV and optional document-system simulations with auditable reports."""
import argparse
import datetime
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent

def run(report_dir, doc_system=None):
    report_dir=Path(report_dir).resolve()
    report_dir.mkdir(parents=True,exist_ok=True)
    suites=[
        ('tv', [sys.executable,'-m','unittest','test_process_gate','test_goal_alignment',
                'test_activation_migration','test_review_regressions','test_host_lifecycle',
                'test_bounded_recovery','test_installation','test_delegated_binding','test_host_receipts','-v'])]
    if doc_system is not None:
        root=Path(doc_system).expanduser().resolve()
        for script in ('selftest.py','doc-lint-consistency.py','doc-workflow.py'):
            if not (root/'scripts'/script).is_file():
                raise ValueError('Invalid document package: '+str(root))
        suites.extend([
            ('documents',[sys.executable,str(root/'scripts/selftest.py')]),
            ('document_consistency',[sys.executable,str(root/'scripts/doc-lint-consistency.py'),str(root)]),
            ('joint',[sys.executable,'-m','unittest','test_joint_flow','-v'])])
    environment=dict(os.environ)
    if doc_system is not None:
        environment['TV_DOC_SYSTEM']=str(root)
    results=[]
    for name,command in suites:
        result=subprocess.run(command,cwd=HERE,env=environment,text=True,capture_output=True)
        log=report_dir/(name+'.log')
        log.write_text(result.stdout+result.stderr,encoding='utf-8')
        results.append({'suite':name,'exit_code':result.returncode,'passed':result.returncode==0,'log':str(log)})
        print(name+': '+('PASS' if result.returncode==0 else 'FAIL'),flush=True)
    report={'kind':'isolated_simulation','adapter_version':__import__('process_gate').VERSION,
            'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'passed':all(r['passed'] for r in results),'results':results,
            'native_host_activation_verified':False,
            'scope':'Temporary Git repositories and isolated runtime/configuration; no production approvals or remote writes.'}
    (report_dir/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doc-system',type=Path,help='Package root for full document and joint simulation')
    parser.add_argument('--report-dir',type=Path,help='Preserve logs; otherwise use a new temporary directory')
    args=parser.parse_args()
    target=args.report_dir or Path(tempfile.mkdtemp(prefix='tv-simulation-'))
    try:
        report=run(target,args.doc_system)
    except (ValueError,OSError) as error:
        parser.exit(2,str(error)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
