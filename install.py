#!/usr/bin/env python3
"""Check or install TV rules in an explicitly selected AGENTS.md."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

START = '<!-- think-then-verify:start -->'
END = '<!-- think-then-verify:end -->'


def block(source_file):
    source = Path(source_file).expanduser().resolve()
    text = source.read_text(encoding='utf-8')
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('Source must contain one complete TV rule block.')
    a, b = text.index(START), text.index(END) + len(END)
    return text[a:b]


def merged(text, managed):
    if START not in text and END not in text:
        return text + ('\n\n' if text and not text.endswith('\n\n') else '') + managed + '\n'
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('Malformed or duplicate managed markers; original file preserved.')
    a, b = text.index(START), text.index(END) + len(END)
    return text[:a] + managed + text[b:]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('check', 'install'))
    p.add_argument('--agents-file', type=Path, required=True)
    p.add_argument('--source', type=Path, default=Path(__file__).resolve().with_name('AGENTS.md'))
    args = p.parse_args()
    target = args.agents_file.expanduser().absolute()
    if target.is_symlink():
        raise ValueError('Select the resolved AGENTS.md target explicitly; symlink preserved.')
    original = target.read_bytes() if target.exists() else None
    text = original.decode('utf-8') if original is not None else ''
    updated = merged(text, block(args.source)).encode('utf-8')
    current = original == updated
    backup = None
    if args.action == 'install' and not current:
        target.parent.mkdir(parents=True, exist_ok=True)
        if original is not None:
            backup = target.with_name(target.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            shutil.copy2(target, backup)
            backup.chmod(0o600)
        if (target.read_bytes() if target.exists() else None) != original:
            raise ValueError('AGENTS.md changed while preparing update; retry.')
        target.write_bytes(updated)
        current = True
    print(json.dumps({'installed': current, 'agents_file': str(target), 'backup': str(backup) if backup else None,
                      'activation': 'effective only when the host loads this instruction file'}, ensure_ascii=False))
    return 0 if current else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
