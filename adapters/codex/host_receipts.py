#!/usr/bin/env python3
"""Reconcile native shell status using an attested host transcript lookup."""
import argparse
import json
from pathlib import Path
import shlex

from process_gate import Guard, atomic_json, digest, now


def reconcile(guard, session, evidence_id, receipt):
    with guard.locked():
        record = guard.registry()['sessions'].get(session)
        if not record:
            raise ValueError('Session is not bound')
        path, state = guard.state(session, record)
        turn = state['turn']
        lookup = turn['evidence'].get(evidence_id, {})
        if (lookup.get('tool_name') != 'mcp__codex_app__read_thread'
                or lookup.get('outcome') != 'success'
                or not isinstance(receipt, dict) or receipt.get('isError') is True
                or lookup.get('response_sha256') != digest(receipt)):
            raise ValueError('Exact successful native read_thread receipt required')
        content = receipt.get('content', [])
        if len(content) != 1 or content[0].get('type') != 'text':
            raise ValueError('Invalid host transcript receipt')
        host = json.loads(content[0]['text'])
        thread = host.get('thread', {})
        if (thread.get('id') != session or thread.get('kind') != 'codex'
                or thread.get('hostId') != 'local'):
            raise ValueError('Receipt must describe this local session')
        updates = {}
        for host_turn in host.get('turns', []):
            for item in host_turn.get('items', []):
                call = item.get('id')
                old = turn['evidence'].get(call) or turn['pending'].get(call)
                if not old or old.get('host_confirmation'):
                    continue
                if item.get('type') == 'mcpToolCall':
                    # A native failed call is authoritative even when no PostToolUse ran.
                    # 'completed' alone cannot prove the tool's business result succeeded.
                    if item.get('status') != 'failed':
                        continue
                    tool = 'mcp__' + str(item.get('server', '')) + '__' + str(item.get('tool', ''))
                    arguments = item.get('arguments')
                    if (old.get('tool_name') != tool or not isinstance(arguments, dict)
                            or old['action_sha256'] != digest([tool, arguments])):
                        raise ValueError('Host MCP call differs from original native invocation')
                    if old.get('outcome') in (None, 'unknown'):
                        updates[call] = (old, item)
                    continue
                if (item.get('type') != 'commandExecution'
                        or item.get('status') not in ('completed', 'failed')
                        or type(item.get('exitCode')) is not int):
                    continue
                # Native metadata owns status; stdout and printed JSON never do.
                if item.get('commandTruncated'):
                    continue
                try:
                    args = shlex.split(item.get('command', ''))
                except ValueError:
                    continue  # Incomplete metadata remains unknown; other calls can reconcile.
                if len(args) != 3 or args[0] not in ('/bin/zsh', '/bin/bash', '/bin/sh') or args[1] != '-lc':
                    continue
                command = args[2]
                if old.get('tool_name') != 'Bash' or old['action_sha256'] != digest(['Bash', {'command': command}]):
                    raise ValueError('Host command differs from original native invocation')
                if not isinstance(item.get('cwd'), str) or not Path(item['cwd']).is_absolute():
                    raise ValueError('Host execution working directory is missing')
                if old.get('outcome') not in (None, 'unknown'):
                    continue
                updates[call] = (old, item)
        if updates:
            version = digest([evidence_id, digest(receipt), sorted(updates)])
            for call, (old, item) in updates.items():
                turn['evidence'][call] = {**old,
                    'outcome': 'success' if item['status'] == 'completed' and item.get('exitCode') == 0 else 'failure',
                    'response_sha256': old.get('response_sha256', digest(item)),
                    'outcome_reason': 'attested_host_execution',
                    'host_confirmation': {'lookup': evidence_id, 'receipt_sha256': digest(receipt),
                        'host_turn': next(t['id'] for t in host['turns'] if item in t.get('items', [])),
                        'exit_code': item.get('exitCode'), 'cwd': item.get('cwd'), 'at': now()},
                    'resource_version': version}
                turn['pending'].pop(call, None)
            # A new authoritative observation invalidates dependent claims, never goals.
            for key in turn.setdefault('resource_versions', {}):
                turn['resource_versions'][key] = version
            for call in updates:
                for key in turn['evidence'][call].get('resources', ['*']):
                    turn['resource_versions'][key] = version
            turn['resource_versions']['*'] = version
            guard._invalidate(state, 'host execution status reconciled; verify current claims')
            atomic_json(path, state)
        return {'confirmed': {call: turn['evidence'][call]['outcome'] for call in updates},
                'pending': list(turn['pending'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--session', required=True)
    parser.add_argument('--evidence-id', required=True)
    parser.add_argument('--receipt-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = reconcile(Guard(args.runtime), args.session, args.evidence_id,
                           json.loads(args.receipt_file.read_text()))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, type(error).__name__ + ': ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
