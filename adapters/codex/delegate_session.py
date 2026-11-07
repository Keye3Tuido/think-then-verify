#!/usr/bin/env python3
"""Silently bind an authorized child using an attested native session lookup."""
import argparse
import json
from pathlib import Path
import sys

from process_gate import Guard, atomic_json, digest, now


def bind_delegated(guard, parent_session, request):
    with guard.locked():
        registry = guard.registry()
        parent_record = registry['sessions'].get(parent_session)
        if not parent_record:
            raise ValueError('Parent TV session is not bound')
        _, parent = guard.state(parent_session, parent_record)
        control = guard.control(parent_session)
        if not parent['activation']['enabled'] or (control and not control['enabled']):
            raise ValueError('Parent TV is off')
        source_turn = request.get('authorization_turn')
        if (source_turn != parent.get('turn', {}).get('id')
                or source_turn not in parent.get('user_events', {})
                or not str(request.get('reason', '')).strip()):
            raise ValueError('Current observed user authorization and scope are required')
        # An inherited child cannot grant new sessions without a direct user event.
        author = parent['user_events'][source_turn]
        if isinstance(author, dict) and author.get('kind') == 'delegated_authorization':
            raise ValueError('A new child requires direct user authorization')
        evidence_id = request.get('evidence_id')
        evidence = parent['turn'].get('evidence', {}).get(evidence_id, {})
        receipt = request.get('host_receipt')
        if (evidence.get('tool_name') != 'mcp__codex_app__read_thread'
                or evidence.get('outcome') != 'success'
                or not isinstance(receipt, dict)
                or evidence.get('response_sha256') != digest(receipt)
                or receipt.get('isError') is True):
            raise ValueError('Need the exact successful native host session lookup receipt')
        content = receipt.get('content')
        if not isinstance(content, list) or len(content) != 1 or content[0].get('type') != 'text':
            raise ValueError('Unexpected host identity receipt')
        host = json.loads(content[0]['text'])
        thread = host.get('thread', {})
        child = request.get('child_session')
        turns = host.get('turns', [])
        if (not isinstance(child, str) or not child or child == parent_session
                or thread.get('id') != child or thread.get('kind') != 'codex'
                or thread.get('hostId') != 'local'
                or thread.get('status', {}).get('type') != 'idle'
                or not turns or not isinstance(turns[0].get('id'), str)
                or not turns[0]['id']):
            raise ValueError('Need a matching idle local child and its real host turn')
        cwd = thread.get('cwd')
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise ValueError('Host did not provide an absolute child workspace')
        root = str(Path(cwd).resolve(strict=True))
        if not Path(root).is_dir():
            raise ValueError('Child workspace must be a directory')
        child_control = guard.control(child)
        if child_control and not child_control['enabled']:
            raise ValueError('Child explicitly disabled TV; delegation cannot override off')
        existing = registry['sessions'].get(child)
        if existing:
            _, state = guard.state(child, existing)
            source = state['activation'].get('activated_by_delegation', {})
            if (state['activation']['enabled'] and source.get('parent_session') == parent_session
                    and source.get('identity_receipt_sha256') == digest(receipt)
                    and existing['initial_project_root'] == root):
                return {'bound': True, 'reused': True, 'session_id': child,
                        'state_root': existing['state_root'], 'turn_id': state['turn']['id']}
            raise ValueError('Existing child binding is preserved; inspect before changing it')
        rules, _ = guard._rules(parent)
        guard._criteria(rules)
        source = {'kind': 'delegated_authorization', 'parent_session': parent_session,
                  'parent_user_turn': source_turn, 'parent_user_event': author,
                  'identity_tool_call': evidence_id, 'identity_receipt_sha256': digest(receipt),
                  'child_native_turn': turns[0]['id'], 'scope': request['reason'], 'at': now()}
        record = guard.bind(registry, child, root, source)
        path, state = guard.state(child, record)
        state['activation'] = {'enabled': True, 'activated_by_delegation': source}
        guard._begin(state, turns[0]['id'])
        # The legacy field indexes authorization sources. This typed entry is an
        # attested inherited grant, never a claim that the child received a user prompt.
        state['user_events'][turns[0]['id']] = source
        atomic_json(Path(state['state_root']) / 'rules.yml', {'rules': rules})
        atomic_json(path, state)
        guard.save_control(child, True, source)
        return {'bound': True, 'reused': False, 'session_id': child,
                'state_root': record['state_root'], 'turn_id': state['turn']['id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--parent-session', required=True)
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    try:
        request = json.loads(args.request)
        if not isinstance(request, dict):
            raise ValueError('Request must be an object')
        answer = bind_delegated(Guard(args.runtime), args.parent_session, request)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, type(error).__name__ + ': ' + str(error) + '\n')
    print(json.dumps(answer, ensure_ascii=False))


if __name__ == '__main__':
    main()
