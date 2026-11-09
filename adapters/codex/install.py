#!/usr/bin/env python3
"""Install the bundled adapter after tests, preserving sessions and host trust."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
FILES=('README.md','install.py','process_gate.py','register_gate.py','simulate.py','test_process_gate.py',
       'test_goal_alignment.py','test_activation_migration.py','test_review_regressions.py',
       'test_host_lifecycle.py','test_bounded_recovery.py','test_joint_flow.py','test_installation.py',
       'delegate_session.py','test_delegated_binding.py','host_receipts.py','test_host_receipts.py')

def install(codex_home):
    home=Path(codex_home).expanduser().resolve()
    runtime=home/'tv'
    # Validate every input before changing any installed file.
    sources={name:(HERE/name).read_bytes() for name in FILES}
    for filename in ('hooks.json','config.toml'):
        path=home/filename
        if path.is_symlink():
            raise ValueError('Refuse symlink configuration: '+str(path))
        if path.exists():
            data=path.read_text()
            if filename.endswith('.json'):
                json.loads(data)
            else:
                __import__('tomllib').loads(data)
    result=subprocess.run([sys.executable,'-m','unittest','test_process_gate','test_goal_alignment',
        'test_activation_migration','test_review_regressions','test_host_lifecycle','test_bounded_recovery','test_delegated_binding','test_host_receipts','-q'],
        cwd=HERE,text=True,capture_output=True)
    if result.returncode:
        raise ValueError('Adapter self-test failed before installation:\n'+result.stdout+result.stderr)
    runtime.mkdir(parents=True,exist_ok=True)
    if runtime.is_symlink():
        raise ValueError('Refuse symlink runtime directory')
    backup=runtime/'install-backups'/hashlib.sha256(b''.join(sources.values())).hexdigest()
    for name,data in sources.items():
        target=runtime/name
        if target.is_symlink():
            raise ValueError('Refuse symlink runtime source: '+str(target))
    for name,data in sources.items():
        target=runtime/name
        if target.exists() and target.read_bytes()!=data:
            backup.mkdir(parents=True,exist_ok=True)
            saved=backup/name
            old=target.read_bytes()
            if saved.exists() and saved.read_bytes()!=old:
                raise ValueError('Backup collision: '+str(saved))
            if not saved.exists():
                saved.write_bytes(old);saved.chmod(0o600)
        # Existing private session/control/registry files are outside FILES.
        fd,temporary=tempfile.mkstemp(prefix='.install-',dir=runtime)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o600)
        os.replace(temporary,target)
    for filename,data in [('hooks.json','{"hooks":{}}\n'),('config.toml','')]:
        path=home/filename
        if not path.exists():
            path.write_text(data,encoding='utf-8');path.chmod(0o600)
    staged=subprocess.run([sys.executable,str(runtime/'register_gate.py'),'--stage-disabled'],
                          capture_output=True,text=True)
    if staged.returncode:
        raise ValueError('Source installed; registration not complete. Backups retained:\n'+staged.stderr)
    return json.loads(staged.stdout)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home',type=Path,default=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))))
    args=parser.parse_args()
    try:
        report=install(args.codex_home)
    except (ValueError,OSError) as error:
        parser.exit(2,str(error)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('Review and enable the four uniquely named TV hooks in the host. Trust was not granted by this installer.')

if __name__=='__main__':main()
