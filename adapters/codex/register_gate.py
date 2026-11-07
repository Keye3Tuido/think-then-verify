#!/usr/bin/env python3
"""Stage four disabled TV workflow mappings; the host controls trust and enablement."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tomllib

from process_gate import CONTRACT_VERSION, GATE_ID, ROOT, VERSION, Guard, atomic_json, now

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
HOOK_LABELS = {event: GATE_ID + "/" + event for event in EVENTS}


def event_key(event):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def handler():
    script = ROOT / "process_gate.py"
    source = script.read_bytes()
    checksum = hashlib.sha256(source).hexdigest()
    pin = ROOT / 'versions' / checksum / script.name
    pin.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if pin.exists():
        if hashlib.sha256(pin.read_bytes()).hexdigest() != checksum:
            raise ValueError('Existing pinned TV implementation checksum mismatch')
    else:
        fd = os.open(pin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source);stream.flush();os.fsync(stream.fileno())
    loader = ("import pathlib,hashlib,sys\n"
              f"p=pathlib.Path({str(pin)!r})\n"
              "try:\n"
              " b=p.read_bytes()\n"
              f" if hashlib.sha256(b).hexdigest() != {checksum!r}: raise ValueError('TV hook checksum mismatch')\n"
              f" logical={str(script)!r}\n"
              " exec(compile(b,logical,'exec'),{'__name__':'__main__','__file__':logical})\n"
              "except BaseException as error:\n"
              f" print({GATE_ID!r}+': hook failed ('+('implementation checksum mismatch' if str(error)=='TV hook checksum mismatch' else type(error).__name__)+')',file=sys.stderr)\n"
              " sys.exit(2)\n")
    return {"type": "command", "command": shlex.join([sys.executable, "-c", loader]),
            "timeout": 5}, checksum


def owned(item):
    return item.get('statusMessage') == GATE_ID or (GATE_ID in item.get('command', '') and 'process_gate.py' in item.get('command', ''))


def locations(config, path):
    return [str(path) + ':' + event_key(event) + f':{gi}:{hi}'
            for event, groups in config.get('hooks', {}).items()
            for gi, group in enumerate(groups) for hi, item in enumerate(group.get('hooks', []))
            if owned(item)]


def merged(config):
    value = json.loads(json.dumps(config))
    hooks = value.setdefault('hooks', {})
    entry, checksum = handler()
    for event, groups in list(hooks.items()):
        if event in EVENTS:
            continue
        for gi in range(len(groups) - 1, -1, -1):
            items = groups[gi].get('hooks', [])
            kept = [h for h in items if not owned(h)]
            if len(items) == len(kept):
                continue
            if kept:
                if any(not owned(h) and hi != kept.index(h) for hi, h in enumerate(items)):
                    raise ValueError('legacy removal would shift another handler')
                groups[gi]['hooks'] = kept
            else:
                if gi != len(groups) - 1:
                    raise ValueError('legacy removal would shift another group')
                groups.pop()
        if not groups:
            del hooks[event]
    for event in EVENTS:
        named_entry = {**entry, 'statusMessage': HOOK_LABELS[event]}
        existing = [(group, hi) for group in hooks.get(event, [])
                    for hi, item in enumerate(group.get('hooks', [])) if owned(item)]
        if len(existing) > 1:
            raise ValueError('duplicate TV handlers; configuration preserved')
        if existing:
            group, hi = existing[0]
            group['hooks'][hi] = dict(named_entry)
            continue
        group = {'hooks': [dict(named_entry)]}
        if event in ('PreToolUse', 'PostToolUse'):
            group['matcher'] = '.*'
        hooks.setdefault(event, []).append(group)
    labels = [h.get('statusMessage') for groups in hooks.values()
              for group in groups for h in group.get('hooks', [])]
    for label in HOOK_LABELS.values():
        if labels.count(label) != 1:
            raise ValueError('duplicate TV hook name: ' + label)
    return value, checksum


def table_header(line):
    if not line.lstrip().startswith('['):
        return None
    try:
        return tomllib.loads(line)
    except tomllib.TOMLDecodeError:
        return None


def disabled_config(text, ids):
    # Edit only TV enabled fields; preserve unrelated values and all trust hashes.
    expected = tomllib.loads(text)
    for identity in ids:
        expected.setdefault('hooks', {}).setdefault('state', {}).setdefault(identity, {})['enabled'] = False
    for identity in sorted(set(ids)):
        header = '[hooks.state.' + json.dumps(identity) + ']'
        lines = text.splitlines(keepends=True)
        starts = [i for i, line in enumerate(lines)
                  if identity in (table_header(line) or {}).get('hooks', {}).get('state', {})]
        if not starts:
            text = text.rstrip('\n') + '\n\n' + header + '\nenabled = false\n'
            continue
        start = starts[0]
        end = next((i for i in range(start + 1, len(lines)) if table_header(lines[i]) is not None), len(lines))
        indices = []
        for i in range(start + 1, end):
            try:
                if 'enabled' in tomllib.loads(lines[i]):
                    indices.append(i)
            except tomllib.TOMLDecodeError:
                continue
        if indices:
            lines[indices[0]] = 'enabled = false\n'
        else:
            lines.insert(start + 1, 'enabled = false\n')
        text = ''.join(lines)
    parsed = tomllib.loads(text)
    if parsed != expected:
        raise ValueError('native disable edit changed unrelated policy or trust')
    return text


def backup(path):
    data = path.read_bytes()
    target = ROOT / (path.name + '.before-tv-' + hashlib.sha256(data).hexdigest()[:12])
    if target.exists() and target.read_bytes() != data:
        raise ValueError('backup collision')
    if not target.exists():
        # Exclusive create with private permissions, including for config secrets.
        import os
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
    return data


def stage_disabled():
    hooks_path, native_path = ROOT.parent / 'hooks.json', ROOT.parent / 'config.toml'
    with Guard(ROOT).locked():
        before = hooks_path.read_bytes()
        original = json.loads(before)
        updated, checksum = merged(original)
        native_before = native_path.read_bytes()
        ids = locations(original, hooks_path) + locations(updated, hooks_path)
        native_after = disabled_config(native_before.decode(), ids)
        backup(hooks_path)
        backup(native_path)
        if hooks_path.read_bytes() != before or native_path.read_bytes() != native_before:
            raise ValueError('native configuration changed during staging')
        # Native disabled state must exist before any command pin/registration changes.
        from process_gate import atomic_text
        atomic_text(native_path, native_after)
        if hooks_path.read_bytes() != before or native_path.read_text() != native_after:
            raise ValueError('native configuration changed during staging')
        atomic_json(hooks_path, updated)
        report = {'gate_id': GATE_ID, 'adapter_version': VERSION, 'contract_version': CONTRACT_VERSION, 'events': list(EVENTS), 'names': HOOK_LABELS,
                  'script_sha256': checksum, 'registered_at': now(), 'lifecycle': 'disabled',
                  'production_enabled': False, 'host_trust': 'pending_host_review',
                  'host_execution_verified': False, 'kernel_implemented': True,
                  'guarantee_scope': 'persistent_goal_alignment_and_exact_actions_with_dependency_aware_output_audit'}
        atomic_json(ROOT / 'registration.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    if sys.argv[1:] != ['--stage-disabled']:
        raise SystemExit('TV direct activation refused: use --stage-disabled, then review current commands and enable in the host')
    stage_disabled()


if __name__ == '__main__':
    main()
