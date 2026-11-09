#!/usr/bin/env python3
"""Persistent TV workflow with exact-action permits and post-turn auditing."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import secrets
import subprocess
import sys
import tempfile

GATE_ID = "think-then-verify-process-gate"
VERSION = "0.7.1"
CONTRACT_VERSION = "goal-alignment-v1"
ROOT = Path(__file__).resolve().parent



def internal_context(event_name, text):
    return {"hookSpecificOutput": {"hookEventName": event_name,
            "additionalContext": "TV 内部状态，静默记录，不播报条件、进度或统计。" + text}}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".tv-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".tv-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def safe_key(session):
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session):
        return session
    return hashlib.sha256(session.encode()).hexdigest()


def project_root(cwd):
    result = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True, timeout=3)
    return str(Path(result.stdout.strip() if result.returncode == 0 else cwd).resolve(strict=True))


def command_switch(prompt):
    if not isinstance(prompt, str):
        return None
    command = prompt.strip()
    if re.match(r"^/tv\s+(?:off|关闭)(?:\s|$)", command, re.I):
        return False
    if re.fullmatch(r"(?:关闭\s*TV\s*流程|停止使用\s*Think-Then-Verify)[。！.!]?", command.partition('\n')[0], re.I):
        return False
    if re.match(r"^/tv(?:\s|$)", command):
        return True
    # Invocation lines may follow the request; quoted/code examples are not calls.
    fence = None
    for line in prompt.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, suffix = marker.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not suffix.strip():
                fence = None
            continue
        if fence is None and re.match(r"^ {0,3}\[\$tv\]\((?:/[^\n)]*/tv/SKILL\.md)\)(?:\s|$)", line):
            return True
    return None


class Guard:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / "registry.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def state_path(self, session, record):
        initial = Path(record["initial_project_root"])
        if not initial.is_absolute() or not initial.is_dir():
            raise ValueError("initial project unavailable")
        expected = initial / ".tv" / safe_key(session)
        if record["state_root"] != str(expected) or expected.resolve() != expected:
            raise ValueError("session binding mismatch")
        return expected / "state.yml"

    def state(self, session, record):
        path = self.state_path(session, record)
        value = json.loads(path.read_text())  # JSON is a valid YAML representation.
        if value.get("conv_id") != session or value.get("state_root") != str(path.parent):
            raise ValueError("state identity mismatch")
        if value.get("initial_project_root") != record["initial_project_root"]:
            raise ValueError("project binding mismatch")
        if not isinstance(value.get("activation", {}).get("enabled"), bool):
            raise ValueError("activation state unknown")
        return path, value

    def bind(self, registry, session, initial, source):
        if session in registry['sessions']:
            return registry['sessions'][session]
        initial = str(Path(initial).resolve(strict=True))
        record = {'initial_project_root': initial,
                  'state_root': str(Path(initial) / '.tv' / safe_key(session))}
        path = self.state_path(session, record)
        if path.exists():
            raise ValueError('Unregistered state exists; diagnose before recovery')
        atomic_json(path, {'schema_version': 6, 'conv_id': session, **record,
                          'activation': {'enabled': True, 'activated_by_user_event': source},
                          'user_events': {}, 'sequence': 0, 'turn': {},
                          'contract_version': CONTRACT_VERSION,
                          'mainline': {'revision': 0, 'goals': {}, 'progress': {}, 'current_work': {}, 'history': []}})
        registry['sessions'][session] = record
        atomic_json(self.root / 'registry.json', registry)
        return record

    def control_path(self, session):
        return self.root / "controls" / (safe_key(session) + ".json")

    def control(self, session):
        path = self.control_path(session)
        if not path.exists():
            return None
        value = json.loads(path.read_text())
        if (value.get("conv_id") != session or not isinstance(value.get("enabled"), bool)
                or not isinstance(value.get("seen", {}), dict) or not isinstance(value.get("source", {}), dict)):
            raise ValueError("invalid control record")
        return value

    def replayed_control(self, control, event):
        turn = event.get("turn_id")
        if not control or not isinstance(turn, str) or not turn:
            return False
        seen = dict(control.get("seen", {}))
        source = control.get("source", {})
        if source.get("turn_id"):
            seen.setdefault(source["turn_id"], source.get("prompt_sha256"))
        if turn not in seen:
            return False
        if seen[turn] != digest(event.get("prompt")):
            raise ValueError("conflicting control event")
        return True

    def save_control(self, session, enabled, source, previous=None):
        seen = dict((previous or {}).get("seen", {}))
        old_source = (previous or {}).get("source", {})
        if old_source.get("turn_id"):
            seen.setdefault(old_source["turn_id"], old_source.get("prompt_sha256"))
        turn = source.get("turn_id")
        if isinstance(turn, str) and turn:
            seen[turn] = source["prompt_sha256"]
        atomic_json(self.control_path(session), {"conv_id": session, "enabled": enabled,
                                               "source": source, "seen": seen})

    def disable(self, session, event):
        # This durable control path precedes optional registry/state recovery.
        try:
            previous = self.control(session)
        except (ValueError, OSError, TypeError):
            previous = None
            damaged = self.control_path(session)
            if damaged.exists():
                saved = damaged.with_name(damaged.name + '.corrupt-' + secrets.token_hex(6))
                saved.write_bytes(damaged.read_bytes())
                saved.chmod(0o600)
        if self.replayed_control(previous, event):
            return {}
        source = {"event": "UserPromptSubmit", "turn_id": event.get("turn_id"),
                  "prompt_sha256": digest(event.get("prompt")), "at": now()}
        self.save_control(session, False, source, previous)
        try:
            record = self.registry()["sessions"].get(session)
            if record:
                path, state = self.state(session, record)
                state["activation"].update(enabled=False, disabled_by_user_event=source)
                state.setdefault("hook", {}).update(lifecycle="disabled", production_enabled=False)
                turn = event.get("turn_id")
                if isinstance(turn, str) and turn:
                    state.setdefault("user_events", {})[turn] = source["prompt_sha256"]
                atomic_json(path, state)
        except (ValueError, OSError, KeyError, TypeError):
            # Preserve damaged evidence. The independent off record is authoritative.
            return {}  # The durable off record is sufficient; recover internally later.
        return {}

    def registry(self):
        path = self.root / 'registry.json'
        if not path.exists():
            return {'schema_version': 1, 'sessions': {}}
        value = json.loads(path.read_text())
        if value.get('schema_version') != 1 or not isinstance(value.get('sessions'), dict):
            raise ValueError('Invalid registry; preserve it for recovery')
        return value

    def _rules(self, state):
        path = Path(state['state_root']) / 'rules.yml'
        if not path.exists():
            return [], None
        if path.is_symlink():
            raise ValueError('Rules must be a regular bound file')
        data = path.read_bytes()
        value = json.loads(data)
        self._criteria(value['rules'])
        return value['rules'], hashlib.sha256(data).hexdigest()

    def _criteria(self, rows):
        if not isinstance(rows, list):
            raise ValueError('Criteria must be a list')
        ids = []
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or not row['id'].strip() or not str(row.get('desc', '')).strip()
                    or row.get('kind') not in ('semantic', 'observed')
                    or row.get('applies_to', 'both') not in ('action', 'output', 'both')):
                raise ValueError('Each criterion needs id, desc and semantic/observed kind')
            if not isinstance(row.get('resources', []), list) or any(not isinstance(x, str) or not x or (x != '*' and not Path(x).is_absolute()) for x in row.get('resources', [])):
                raise ValueError('Criterion resources must be absolute paths or *')
            ids.append(row['id'])
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate criterion id')
        return rows

    def _mainline_sha(self, state):
        return digest({
            k: state['mainline'][k] for k in ('revision', 'goals', 'current_work')})

    def _upgrade(self, state, path):
        if state.get('schema_version') == 6:
            if state.get('contract_version') != CONTRACT_VERSION or not isinstance(state.get('mainline'), dict):
                raise ValueError('Invalid goal-alignment state; preserve and diagnose')
            return
        version = state.get('schema_version')
        if version not in (3, 4, 5):
            raise ValueError('Unsupported legacy state; preserve and migrate explicitly')
        previous = state.get('turn', {})
        goals = {r['id']: {**r, 'source_turn': previous.get('id'), 'status': 'active'}
                 for r in self._criteria(previous.get('requirements', []))}
        original = path.read_bytes()
        backup = path.parent / 'history' / (f'migration-v{version}-' + hashlib.sha256(original).hexdigest() + '.json')
        if not backup.exists():
            atomic_text(backup, original.decode('utf-8'))
        state['mainline'] = {'revision': 1 if goals else 0, 'goals': goals, 'progress': {},
                             'current_work': {}, 'history': []}
        state.update(schema_version=6, contract_version=CONTRACT_VERSION)
        state.setdefault('sequence', 0)
        state.setdefault('user_events', {})
        if version in (3, 4):
            # The old preflight model has no reusable permits or output checks.
            # _begin archives the full legacy turn and preserves unresolved calls.
            self._begin(state, previous.get('id'))
        elif previous.get('id'):
            previous.update(tasks={}, temporary_requirements=[], check_cache={})
            self._sync_requirements(state)
            self._invalidate(state, 'migrated from schema 5; recheck current goal and rules')

    def migrate(self, session):
        """Migrate a bound state without manufacturing user activation or receipts."""
        with self.locked():
            record = self.registry()['sessions'].get(session)
            if record is None:
                raise ValueError('No bound session to migrate')
            path, state = self.state(session, record)
            version = state.get('schema_version')
            self._upgrade(state, path)
            if state.get('schema_version') != version:
                atomic_json(path, state)
            return {'schema_version': state['schema_version'], 'previous_schema_version': version,
                    'activation_unchanged': True, 'user_events_unchanged': True}

    def _sync_requirements(self, state):
        t = state['turn']
        persistent = [r for r in state['mainline']['goals'].values() if r.get('status') == 'active']
        t['requirements'] = persistent + t.get('temporary_requirements', [])
        self._criteria(t['requirements'])

    def _begin(self, state, turn):
        previous = state.get('turn', {})
        if previous.get('id'):
            history = Path(state['state_root']) / 'history' / (safe_key(previous['id']) + '.json')
            if history.exists() and json.loads(history.read_text()) != previous:
                history = history.with_name(safe_key(previous['id']) + '-' + digest(previous) + '.json')
            atomic_json(history, previous)
        state['turn'] = {'id': turn, 'phase': 'Think', 'iteration': 1, 'tasks': {},
                         'requirements': [], 'temporary_requirements': [],
                         'evidence': previous.get('evidence', {}), 'pending': previous.get('pending', {}),
                         'resource_versions': previous.get('resource_versions', {}), 'permits': [],
                         'check_cache': {}, 'attempts': [], 'output': {'status': 'not_ready'},
                         'closure': 'open', 'epoch': 0}
        self._sync_requirements(state)

    def _invalidate(self, state, reason, affected=None, keep_candidate=False):
        turn = state['turn']
        if turn.get('candidate') or turn.get('verification'):
            turn['attempts'].append({'candidate': turn.get('candidate'), 'verification': turn.get('verification'),
                                     'decision': turn.get('decision'), 'invalidated': reason})
        for name in ('candidate', 'verification', 'decision'):
            if name != 'candidate' or not keep_candidate:
                turn.pop(name, None)
        turn.update(phase='Verify' if keep_candidate and turn.get('candidate') else 'Think', output={'status': 'not_ready'}, closure='open')
        turn['epoch'] += 1
        if affected is None:
            turn['check_cache'] = {}
            turn['permits'] = []
        else:
            for key in affected:
                turn.get('check_cache', {}).pop(key, None)
            turn['permits'] = [p for p in turn['permits'] if self._permit_valid(state, p)]
        stale_progress = list(state['mainline']['progress']) if affected is None else affected
        for key in stale_progress:
            if key in state['mainline']['progress']:
                state['mainline']['progress'][key] = {'status': 'unknown', 'reason': reason, 'evidence': []}

    def _refresh(self, state):
        self._sync_requirements(state)
        _, sha = self._rules(state)
        turn = state['turn']
        if turn.get('rules_sha256') != sha:
            self._invalidate(state, 'rules changed')
            turn['rules_sha256'] = sha
            turn.pop('rules_read', None)

    def _resources(self, event):
        """Only known file reads have narrow resources; unknown behavior stays broad."""
        data = event.get('tool_input', {})
        values = []
        for key in ('path', 'file_path', 'filename', 'paths'):
            value = data.get(key)
            if isinstance(value, str): values.append(value)
            elif isinstance(value, list): values.extend(x for x in value if isinstance(x, str))
        command = data.get('command', data.get('cmd'))
        args = self._shell_args(command) if command else []
        if args and args[0] in ('cat', 'head', 'tail', 'stat', 'wc', 'nl', 'diff'):
            values.extend(x for x in args[1:] if not x.startswith('-') and not x.isdigit())
        base = Path(event.get('cwd') or '.')
        return sorted({str((base / x).resolve()) for x in values}) or ['*']

    def _dependencies(self, state, row=None, criterion=None):
        t = state['turn']; resources = set((criterion or {}).get('resources', []))
        for key in (row or {}).get('evidence', []):
            resources.update(t['evidence'][key].get('resources', ['*']))
        return {key: t.get('resource_versions', {}).get(key) for key in sorted(resources)}

    def _valid_cache(self, state):
        t = state['turn'];criteria = {r['id']: r for r in self._criteria(self._rules(state)[0] + t['requirements'])}
        cache = t.setdefault('check_cache', {})
        for key, item in list(cache.items()):
            criterion = criteria.get(key)
            if (criterion is None or item['criterion_sha256'] != digest(criterion)
                    or item['dependencies'] != self._dependencies(state, item['row'], criterion)
                    or (criterion.get('applies_to', 'both') != 'action'
                        and item.get('candidate_sha256') != t.get('candidate', {}).get('sha256'))):
                del cache[key]
        return cache

    def _snapshot(self, state):
        t = state['turn']; candidate = t.get('candidate', {})
        resources = set(candidate.get('resources', []))
        evidence_ids = set(candidate.get('evidence', []))
        for item in self._valid_cache(state).values():
            resources.update(item['dependencies']);evidence_ids.update(item['row'].get('evidence', []))
        return digest({'turn': t['id'], 'mainline': self._mainline_sha(state),
                       'rules': t.get('rules_sha256'), 'requirements': t['requirements'],
                       'candidate': candidate,
                       'evidence': {key: t['evidence'].get(key) for key in sorted(evidence_ids)},
                       'resources': {key: t.get('resource_versions', {}).get(key) for key in sorted(resources)}})

    def _read_current(self, state):
        t = state['turn'];_,sha = self._rules(state)
        if not sha or t.get('rules_read') != sha or t.get('mainline_read') != self._mainline_sha(state):
            raise ValueError('Read current mainline and complete rules with inspect first')

    def _checks(self, state, results, action=False):
        self._read_current(state)
        rules, _ = self._rules(state);t = state['turn']
        criteria = self._criteria(rules + t['requirements'])
        if action:
            criteria = [r for r in rules if r.get('applies_to', 'both') != 'output'] + [r for r in t['requirements'] if r.get('applies_to', 'output') != 'output']
        if not isinstance(results, list) or len(results) != len(criteria):
            raise ValueError('Every applicable rule and requirement needs one result')
        if not all(isinstance(row, dict) for row in results):
            raise ValueError('Invalid result')
        checked = {row.get('id'): row for row in results}
        if len(checked) != len(results) or set(checked) != {row['id'] for row in criteria}:
            raise ValueError('Missing, duplicate or unknown check id')
        for criterion in criteria:
            row = checked[criterion['id']]
            if row.get('status') not in ('satisfied', 'violated', 'unknown', 'not_applicable') or not str(row.get('reason', '')).strip():
                raise ValueError('A result needs explicit status and reason')
            evidence = row.get('evidence', [])
            if not isinstance(evidence, list) or any(x not in t['evidence'] for x in evidence):
                raise ValueError('Unknown tool evidence reference')
            if row['status'] == 'satisfied':
                if criterion['kind'] == 'observed' and not evidence:
                    raise ValueError('An observed fact needs actual tool evidence')
                if any(t['evidence'][x]['outcome'] != 'success' for x in evidence):
                    raise ValueError('Failed or unknown results cannot prove a successful action')
                for key in evidence:
                    observed = t['evidence'][key]
                    if any(t.get('resource_versions', {}).get(resource) != observed.get('resource_version')
                           for resource in observed.get('resources', [])):
                        raise ValueError('Stale resource receipt cannot prove the current condition')
        return all(x['status'] in ('satisfied', 'not_applicable') for x in results)

    def _gap_key(self, state):
        t = state['turn']; rows = t.get('verification', {}).get('results', [])
        successes = {digest([e['action_sha256'], e['response_sha256']])
                     for row in rows for key in row.get('evidence', [])
                     if (e := t['evidence'][key])['outcome'] == 'success'}
        return digest({'goals': [{k:v for k,v in r.items() if k not in ('source_turn', 'retired_by')} for r in t['requirements']], 'rules': t.get('rules_sha256'),
                       'unmet': sorted((r['id'], r['status']) for r in rows if r['status'] not in ('satisfied', 'not_applicable')),
                       'successes': sorted(successes), 'pending': sorted(t['pending'])})

    def _permit_valid(self, state, permit):
        t = state['turn']
        return (permit['mainline_sha256'] == self._mainline_sha(state)
                and permit['rules_sha256'] == t.get('rules_sha256')
                and permit['requirements_sha256'] == digest(t['requirements'])
                and all(t.get('resource_versions', {}).get(key) == val for key, val in permit['dependencies'].items()))

    def _update_mainline(self, state, request):
        main = state['mainline'];t = state['turn']
        if request.get('expected_revision') != main['revision']:
            raise ValueError('Stale or missing mainline revision')
        before = digest(main)
        updates = request.get('goals', [])
        self._criteria(updates)
        retire = request.get('retire_ids', [])
        if not isinstance(retire, list) or any(key not in main['goals'] for key in retire):
            raise ValueError('Unknown goal retirement')
        if updates or retire:
            if request.get('source_turn') not in state['user_events'] or not str(request.get('reason', '')).strip():
                raise ValueError('Goal changes need real user source and scope reason')
            main['history'].append({'revision': main['revision'], 'goals': main['goals'].copy(),
                                    'source_turn': request['source_turn'], 'reason': request['reason']})
            for row in updates:
                main['goals'][row['id']] = {**row, 'source_turn': request['source_turn'], 'status': 'active'}
            for key in retire:
                main['goals'][key] = {**main['goals'][key], 'status': 'retired', 'retired_by': request['source_turn']}
        if 'current_work' in request:
            work = request['current_work']
            if not isinstance(work, dict) or not isinstance(work.get('goal_ids'), list):
                raise ValueError('Current work needs goal_ids')
            if any(key not in main['goals'] or main['goals'][key]['status'] != 'active' for key in work['goal_ids']):
                raise ValueError('Current work must reference active goals')
            main['current_work'] = work
        if digest(main) != before:
            main['revision'] += 1
            self._sync_requirements(state)
            self._invalidate(state, 'mainline updated')
        return {'mainline_saved': True, 'revision': main['revision']}

    def request(self, session, request):
        with self.locked():
            record = self.registry()['sessions'].get(session)
            if not record:
                raise ValueError('No bound session; only a real user /tv event may create one')
            path, state = self.state(session, record)
            control = self.control(session)
            if (control and not control['enabled']) or not state['activation']['enabled']:
                raise ValueError('TV is explicitly off')
            self._upgrade(state, path)
            t = state.get('turn', {})
            if not t.get('id'):
                raise ValueError('Await a real user turn; do not invent one')
            if request.get('turn_id') != t['id'] and not (request.get('action') == 'inspect' and 'turn_id' not in request):
                raise ValueError('Stale or missing turn id')
            self._refresh(state)
            self._reconcile_denials(state)
            action = request.get('action')
            if action == 'inspect':
                rules, sha = self._rules(state)
                t.update(rules_read=sha, rules_read_phase=t['phase'], mainline_read=self._mainline_sha(state))
                answer = {'session_id': session, 'state_root': state['state_root'], 'turn_id': t['id'],
                          'contract_version': CONTRACT_VERSION, 'mainline': state['mainline'],
                          'phase': t['phase'], 'rules': rules, 'requirements': t['requirements'],
                          'rules_sha256': sha, 'evidence': t['evidence'], 'pending': t['pending'],
                          'output': t['output'], 'tasks': {},
                          'valid_checks': {key: item['row'] for key,item in self._valid_cache(state).items()}}
            elif action == 'mainline':
                answer = self._update_mainline(state, request)
            elif action == 'rules':
                updates = self._criteria(request.get('rules'))
                existing = {r['id']:r for r in self._rules(state)[0]}
                remove = request.get('remove_ids', [])
                if not isinstance(remove, list) or any(key not in existing for key in remove):
                    raise ValueError('Unknown rule removal')
                if remove and (request.get('source_turn') not in state['user_events'] or not str(request.get('reason', '')).strip()):
                    raise ValueError('Rule removal needs a real user source and reason')
                for row in updates: existing[row['id']] = row
                for key in remove: existing.pop(key)
                rules = self._criteria(list(existing.values()))
                self._criteria(rules + t['requirements'])
                atomic_json(Path(state['state_root']) / 'rules.yml', {'rules': rules})
                self._refresh(state)
                answer = {'rules_saved': True, 'rules_sha256': t['rules_sha256']}
            elif action == 'requirements':
                rows = self._criteria(request.get('requirements'))
                before_requirements = digest(t['requirements'])
                if request.get('scope', 'task') == 'turn':
                    t['temporary_requirements'] = rows
                elif request.get('scope', 'task') == 'task':
                    changed = False
                    for row in rows:
                        old = state['mainline']['goals'].get(row['id'])
                        if old and old.get('status') == 'active' and {k:v for k,v in old.items() if k not in ('source_turn','status')} == row:
                            continue
                        state['mainline']['history'].append({'revision': state['mainline']['revision'],
                            'goal_id': row['id'], 'previous': old, 'source_turn': t['id']})
                        state['mainline']['goals'][row['id']] = {**row, 'source_turn': t['id'], 'status': 'active'}
                        changed = True
                    if changed: state['mainline']['revision'] += 1
                else:
                    raise ValueError('Requirement scope must be task or turn')
                self._sync_requirements(state)
                self._criteria(self._rules(state)[0] + t['requirements'])
                if digest(t['requirements']) != before_requirements:
                    self._invalidate(state, 'requirements updated')
                answer = {'requirements_saved': True, 'mainline_revision': state['mainline']['revision']}
            elif action == 'think':
                if not isinstance(request.get('candidate'), str) or not request['candidate'].strip():
                    raise ValueError('A nonempty output candidate is required')
                self._read_current(state)
                if t['phase'] != 'Think':
                    self._invalidate(state, 'candidate revised', affected=[])
                if not isinstance(request.get('resources', []), list) or any(not isinstance(x,str) or not x or (x != '*' and not Path(x).is_absolute()) for x in request.get('resources', [])):
                    raise ValueError('Candidate resources must be absolute paths or *')
                text = request['candidate']
                candidate_sha = hashlib.sha256(text.encode()).hexdigest()
                t['check_cache'] = {key:item for key,item in t.get('check_cache', {}).items()
                                    if item.get('candidate_sha256') == candidate_sha or item.get('action_only')}
                refs = request.get('evidence', [])
                if not isinstance(refs, list) or any(key not in t['evidence'] for key in refs):
                    raise ValueError('Unknown candidate evidence')
                t['candidate'] = {'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                                  'resources': request.get('resources', []), 'evidence': refs}
                t['phase'] = 'Verify'
                answer = {'candidate_sha256': t['candidate']['sha256']}
            elif action == 'verify':
                if t['phase'] != 'Verify' or not t.get('candidate') or t.get('rules_read_phase') != 'Verify':
                    raise ValueError('Inspect current rules after preparing the output candidate')
                rows = request.get('results')
                if not isinstance(rows, list) or any(not isinstance(row,dict) for row in rows) or len({r.get('id') for r in rows}) != len(rows):
                    raise ValueError('Results must have unique ids')
                combined = {key: item['row'] for key,item in self._valid_cache(state).items()}
                combined.update({row.get('id'): row for row in rows})
                results = list(combined.values())
                passed = self._checks(state, results)
                criteria = {r['id']: r for r in self._rules(state)[0] + t['requirements']}
                t['check_cache'] = {row['id']: {'row': row, 'criterion_sha256': digest(criteria[row['id']]),
                                    'dependencies': self._dependencies(state, row, criteria[row['id']]),
                                    'candidate_sha256': t['candidate']['sha256'],
                                    'action_only': criteria[row['id']].get('applies_to', 'both') == 'action'} for row in results}
                for row in results:
                    if row['id'] in state['mainline']['goals']:
                        state['mainline']['progress'][row['id']] = {**row, 'checked_in_turn': t['id']}
                t['verification'] = {'results': results, 'passed': passed, 'snapshot': self._snapshot(state)}
                t['phase'] = 'Decide'
                answer = {'verification_complete': True, 'passed': passed}
            elif action == 'decide':
                v = t.get('verification', {})
                if t['phase'] != 'Decide' or v.get('snapshot') != self._snapshot(state):
                    raise ValueError('Decide needs current verification')
                decision = request.get('decision')
                if decision not in ('retry', 'output', 'blocked', 'partial', 'clarification') or not str(request.get('reason', '')).strip():
                    raise ValueError('Decide needs a supported outcome and reason')
                unresolved = sorted(t['pending'])
                acknowledged = request.get('unresolved_calls', [])
                if (not isinstance(acknowledged, list)
                        or any(not isinstance(x, str) for x in acknowledged)
                        or len(set(acknowledged)) != len(acknowledged)):
                    raise ValueError('Unresolved calls must be an explicit unique list')
                if decision == 'output' and (not v['passed'] or unresolved):
                    raise ValueError('Failed, unknown or pending calls cannot produce a success output')
                if unresolved and decision != 'retry':
                    if decision not in ('blocked', 'partial', 'clarification') or sorted(acknowledged) != unresolved:
                        raise ValueError('Non-success output must acknowledge the exact unresolved calls')
                elif acknowledged:
                    raise ValueError('Acknowledged unresolved calls do not match current pending calls')
                if decision == 'retry':
                    key = self._gap_key(state)
                    counts = state.setdefault('retry_gaps', {})
                    if counts.get(key, 0) >= 3:
                        raise ValueError('Same gap had three recovery attempts without progress; report unresolved conditions')
                    counts[key] = counts.get(key, 0) + 1
                    t['iteration'] += 1
                    self._invalidate(state, 'Decide requested correction', affected=[])
                else:
                    t['phase'] = 'Output'
                    t['output'] = {'status': 'ready', 'type': decision, 'snapshot': v['snapshot'],
                                   'candidate_sha256': t['candidate']['sha256'],
                                   'unresolved_calls': unresolved}
                    t['decision'] = {'decision': decision, 'reason': request['reason'], 'snapshot': v['snapshot']}
                answer = {'phase': t['phase'], 'output': t['output']}
            elif action == 'permit':
                if not self._checks(state, request.get('results'), action=True):
                    raise ValueError('Action checks are not satisfied')
                if request.get('authorization_turn') not in state.get('user_events', {}) or not str(request.get('reason', '')).strip():
                    raise ValueError('Action authorization needs a real user turn and scope explanation')
                if not isinstance(request.get('tool_name'), str) or not isinstance(request.get('tool_input'), dict):
                    raise ValueError('Permit needs exact tool name and complete input')
                goal_ids = request.get('goal_ids', [])
                if t['requirements'] and not goal_ids:
                    raise ValueError('Explicit goal_ids are required for an action with active goals')
                if not isinstance(goal_ids,list) or any(key not in {r['id'] for r in t['requirements']} for key in goal_ids):
                    raise ValueError('Unknown action goal')
                dependencies = {}
                criteria = {r['id']:r for r in self._rules(state)[0] + t['requirements']}
                for row in request['results']:
                    dependencies.update(self._dependencies(state, row, criteria[row['id']]))
                permit = {'action_sha256': digest([request['tool_name'], request['tool_input']]),
                          'mainline_sha256': self._mainline_sha(state), 'goal_ids': goal_ids,
                          'rules_sha256': t['rules_sha256'], 'requirements_sha256': digest(t['requirements']),
                          'authorization_turn': request['authorization_turn'], 'reason': request['reason'],
                          'checks': request['results'], 'dependencies': dependencies, 'turn_id': t['id']}
                t['permits'].append(permit)
                answer = {'permit_sha256': digest(permit)}
            else:
                raise ValueError('Unsupported adapter action')
            atomic_json(path, state)
            return answer

    def _shell_args(self, command):
        if not isinstance(command, str):
            return []
        try:
            args = shlex.split(command)
        except ValueError:
            return []
        return args if shlex.join(args) == command.strip() else []

    def _management(self, event, session):
        name = event.get('tool_name', '')
        if name.startswith('functions.'):
            name = name[len('functions.'):]
        if '.' in name or '__' in name:
            return False
        if name not in ('Bash', 'bash', 'exec_command', 'shell', 'run_shell_command'):
            return False
        command = event.get('tool_input', {}).get('command', event.get('tool_input', {}).get('cmd', ''))
        args = self._shell_args(command)
        if len(args) < 3 or not re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(args[0]).name):
            return False
        doc_workflow = Path.home() / '.agent-docs/scripts/doc-workflow.py'
        if Path(args[1]).resolve() == doc_workflow.resolve():
            # Repair controls only inspect or record verified documentation. They
            # must remain available before business output can be accepted.
            return ((len(args) == 5 and args[2:4] == ['inspect', '--project']
                     and Path(args[4]).is_absolute())
                    or (len(args) == 9 and args[2:4] == ['complete', '--project']
                        and Path(args[4]).is_absolute() and args[5] == '--source'
                        and re.fullmatch(r'[0-9a-f]{64}', args[6]) is not None
                        and args[7] == '--reason' and bool(args[8].strip())))
        if Path(args[1]).resolve() == self.root / 'host_receipts.py':
            return (len(args) == 8 and args[2:5] == ['--session', session, '--evidence-id']
                    and args[6] == '--receipt-file' and bool(args[5])
                    and Path(args[7]).is_absolute())
        if Path(args[1]).resolve() != self.root / 'process_gate.py':
            return False
        return (args[2:] == ['--status'] or args[2:] == ['--session', session, '--migrate-state']
                or (len(args) == 6 and args[2:5] == ['--session', session, '--request']))

    def _read_only(self, event):
        name = event.get('tool_name', '')
        if name.startswith('functions.'):
            name = name[len('functions.'):]
        if '.' in name or '__' in name:
            return False
        if name in ('read_file', 'view_file', 'view_image', 'list_directory', 'list_files', 'search_files', 'search_code', 'get_file_info'):
            return True
        if name not in ('Bash', 'bash', 'exec_command', 'shell', 'run_shell_command'):
            return False
        command = event.get('tool_input', {}).get('command', event.get('tool_input', {}).get('cmd', ''))
        args = self._shell_args(command)
        if not args:
            return False
        if args[0] in ('cat', 'head', 'tail', 'ls', 'pwd', 'stat', 'wc', 'nl', 'diff'):
            return True
        if args[0] in ('rg', 'grep'):
            if args[0] == 'rg' and '--no-config' not in args[1:]:
                return False
            return not any(x.startswith(('--pre', '--hostname-bin')) for x in args[1:])
        # Git display commands can execute configured helpers. Treat them as effects
        # unless a host adapter supplies a separately verified safe invocation.
        return False

    def _context(self, event, state):
        turn = state['turn']
        rules, _ = self._rules(state)
        context = {'contract_version': CONTRACT_VERSION, 'goals': turn['requirements'],
                   'constraints': rules, 'progress': state['mainline']['progress'],
                   'current_work': state['mainline']['current_work'], 'pending': list(turn['pending'])}
        text = ('保持主线与核心约束；局部结果不代表整体完成。规则冲突时如实报告不能完成。'
                '先 inspect 回读当前记录，按需使用 mainline/requirements/permit/think/verify/decide；'
                '条件与进度静默处理，答复只保留有用信息。'
                f' 会话={state["conv_id"]}；回合={turn["id"]}；适配器={self.root / "process_gate.py"}。'
                '当前记录=' + json.dumps(context, ensure_ascii=False))
        return internal_context(event, text)

    def _pre(self, event, state):
        t = state['turn']
        tool_id = event.get('tool_use_id')
        action = digest([event.get('tool_name'), event.get('tool_input')])
        if not isinstance(tool_id, str) or not tool_id:
            return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                           'permissionDecisionReason': 'TV 无法关联工具回执；先修复宿主工具调用标识。'}}
        if tool_id in t['pending']:
            if t['pending'][tool_id]['action_sha256'] == action:
                if t['pending'][tool_id]['kind'] == 'effect':
                    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                   'permissionDecisionReason': '该动作许可已经消耗，等待原调用回执；不要重复副作用。'}}
                return self._context('PreToolUse', state)
            raise ValueError('Conflicting tool invocation id')
        if tool_id in t['evidence']:
            raise ValueError('Completed tool id cannot be reused')
        observation = self._read_only(event)
        permit = next((p for p in t['permits'] if p['action_sha256'] == action
                       and p['turn_id'] == t['id'] and self._permit_valid(state, p)), None)
        if not observation and permit is None:
            out = self._context('PreToolUse', state)
            out['hookSpecificOutput'].update(permissionDecision='deny',
                                            permissionDecisionReason='TV 尚无与当前规则、用户授权及完整参数匹配的一次性动作许可；静默补齐检查后重试。')
            return out
        if permit:
            t['permits'].remove(permit)
        t['pending'][tool_id] = {'action_sha256': action, 'tool_name': event.get('tool_name'),
                                'kind': 'observation' if observation else 'effect',
                                'permit': digest(permit) if permit else None, 'resources': self._resources(event),
                                'origin_turn': t['id'], 'started_at': now(),
                                'policy_journal': self._denial_journal(event)}
        return self._context('PreToolUse', state)


    def _denial_journal(self, event):
        """Locate the documented project's policy journal; absence is not denial."""
        data = event.get('tool_input') or {}
        target = event.get('cwd')
        for key in ('workdir', 'cwd', 'file_path', 'path'):
            value = data.get(key)
            if isinstance(value, str) and Path(value).is_absolute():
                target = value
                break
        if not isinstance(target, str):
            return None
        path = Path(target).resolve()
        if not path.is_dir():
            path = path.parent
        try:
            root = Path(project_root(str(path)))
            owner = next((p for p in (root, *root.parents) if (p / '.agent-docs/_index.md').is_file()), None)
            if owner is None:
                return None
            result = subprocess.run(['git', '-C', str(owner), 'rev-parse', '--git-path',
                                     'agent-docs-workflow/observations.jsonl'],
                                    capture_output=True, text=True, timeout=3, check=True)
            journal = Path(result.stdout.strip())
            return str(journal if journal.is_absolute() else owner / journal)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def _reconcile_denials(self, state):
        """Only a matching policy decision can settle an unexecuted invocation."""
        t = state['turn']
        journals = {}
        for pending in t['pending'].values():
            path = pending.get('policy_journal')
            if not path or path in journals:
                continue
            try:
                source = Path(path)
                if source.is_symlink():
                    continue
                with source.open('rb') as stream:
                    size = stream.seek(0, 2)
                    offset = max(0, size - 1024 * 1024)
                    stream.seek(offset)
                    data = stream.read()
                lines = data.splitlines()
                if offset:
                    lines = lines[1:]
                rows = []
                for line in lines:
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict):
                            rows.append(row)
                    except (ValueError, UnicodeError):
                        continue
                journals[path] = rows
            except OSError:
                continue
        settled = []
        for tool_id, pending in list(t['pending'].items()):
            for row in journals.get(pending.get('policy_journal'), []):
                if (row.get('gate_id') != 'agent-doc-system-silent-workflow'
                        or row.get('event') != 'PreToolUse' or row.get('decision') != 'deny'
                        or row.get('session_id') != state['conv_id']
                        or row.get('tool_use_id') != tool_id
                        or row.get('action_sha256') != pending['action_sha256']):
                    continue
                try:
                    observed = datetime.datetime.fromisoformat(row['at'])
                    started = datetime.datetime.fromisoformat(pending['started_at'])
                    if observed < started:
                        continue
                except (ValueError, TypeError, KeyError):
                    continue
                t['evidence'][tool_id] = {**pending, 'outcome': 'denied',
                    'outcome_reason': row['gate_id'], 'receipt_kind': 'policy_denial',
                    'response_sha256': digest(row), 'resource_version': None, 'at': row['at']}
                del t['pending'][tool_id]
                settled.append(tool_id)
                break
        if settled and t.get('candidate'):
            self._invalidate(state, 'matching policy denial settled; recheck unresolved calls', affected=[])
        return settled

    def _outcome(self, response):
        # Native shell callbacks may contain stdout alone. Text, including JSON
        # printed by a command, is not authenticated process status.
        if not isinstance(response, dict):
            return 'unknown', 'host_status_unavailable'
        codes = [response[k] for k in ('exit_code', 'exitCode') if type(response.get(k)) is int]
        failed = (response.get('isError') is True or bool(response.get('error'))
                  or response.get('success') is False or any(code != 0 for code in codes))
        if failed:
            return 'failure', 'host_status'
        if codes or response.get('isError') is False or response.get('success') is True:
            return 'success', 'host_status'
        return 'unknown', 'host_status_unavailable'

    def _post(self, event, state):
        t = state['turn'];tool_id = event.get('tool_use_id')
        action = digest([event.get('tool_name'), event.get('tool_input')])
        if tool_id in t['evidence']:
            old = t['evidence'][tool_id]
            if old['action_sha256'] != action or old['response_sha256'] != digest(event.get('tool_response')):
                raise ValueError('Conflicting repeated tool result')
            return {}
        pending = t['pending'].get(tool_id)
        if not pending or pending['action_sha256'] != action:
            t.setdefault('unmatched_callbacks', []).append({'tool_use_id': tool_id, 'event_sha256': digest(event)})
            return self._context('PostToolUse', state)
        response = event.get('tool_response')
        outcome, outcome_reason = self._outcome(response)
        del t['pending'][tool_id]
        resources = pending.get('resources', ['*'])
        versions = t.setdefault('resource_versions', {})
        value = digest([outcome, response])
        changed = {key for key in resources if versions.get(key) != value}
        if pending['kind'] == 'effect':
            changed = {'*'}  # Arbitrary tools/shell can write beyond declared paths.
        cache = self._valid_cache(state).copy()
        candidate_resources = set(t.get('candidate', {}).get('resources', []))
        for ref in t.get('candidate', {}).get('evidence', []):
            candidate_resources.update(t['evidence'][ref].get('resources', ['*']))
        affected = {key for key,item in cache.items()
                    if changed and ('*' in changed or '*' in item['dependencies'] or changed.intersection(item['dependencies']))}
        candidate_changed = bool(changed and ('*' in changed or '*' in candidate_resources or changed.intersection(candidate_resources)))
        # Directory observations and nested paths overlap file dependencies.
        known = set(versions) | candidate_resources
        for item in cache.values(): known.update(item['dependencies'])
        for permit in t['permits']: known.update(permit['dependencies'])
        if changed and '*' not in changed:
            related = {key for key in known if key != '*' and any(
                key == resource or key.startswith(resource.rstrip('/') + '/')
                or resource.startswith(key.rstrip('/') + '/') for resource in changed)}
            changed.update(related)
            affected.update(key for key,item in cache.items() if changed.intersection(item['dependencies']))
            candidate_changed = candidate_changed or bool(changed.intersection(candidate_resources))
        for key in set(resources) | changed:
            versions[key] = value
        if changed:
            versions['*'] = value
        if '*' in changed:
            # Unknown effects may also change every resource already under observation.
            for key in versions: versions[key] = value
        t['evidence'][tool_id] = {**pending, 'outcome': outcome, 'outcome_reason': outcome_reason, 'response_sha256': digest(response), 'resource_version': value, 'at': now()}
        if affected or candidate_changed:
            self._invalidate(state, 'dependent tool result changed; refresh affected checks', affected=None if '*' in changed else affected, keep_candidate='*' not in changed)
        else:
            t['permits'] = [p for p in t['permits'] if self._permit_valid(state, p)]
        return self._context('PostToolUse', state)

    def _stop(self, event, state):
        t = state['turn'];out = t['output'];v = t.get('verification', {})
        terminal = {'continue': False, 'stopReason': 'TV 收尾核验未通过且恢复次数已耗尽；本回合按未核验终止，保留缺口，不能记录成功。'}
        # A native turn has one recovery budget, independent of mutable gap
        # hashes, candidate wording, new reads and newly missing callbacks.
        if t.get('stop_recovery_halted'):
            t['closure'] = 'halted_unverified'
            return terminal
        text = event.get('last_assistant_message')
        matching = isinstance(text, str) and hashlib.sha256(text.encode()).hexdigest() == out.get('candidate_sha256')
        unresolved = sorted(t['pending'])
        terminal_unresolved = (out.get('type') in ('blocked', 'partial', 'clarification')
                               and unresolved == out.get('unresolved_calls', []))
        valid = (out.get('status') in ('ready', 'observed') and (not unresolved or terminal_unresolved) and matching
                 and v.get('snapshot') == self._snapshot(state) and out.get('snapshot') == v.get('snapshot'))
        if valid:
            t['closure'] = ('closed_verified' if out['type'] == 'output' else
                            'closed_' + out['type'] + ('_unresolved' if unresolved else ''))
            out.update(status='observed', observed_text_sha256=hashlib.sha256(text.encode()).hexdigest())
            return {}
        token = (digest({'pending': unresolved, 'rules': t.get('rules_sha256'),
                         'goals': self._mainline_sha(state)}) if unresolved else self._gap_key(state))
        gaps = state.setdefault('stop_gaps', {})
        gaps[token] = gaps.get(token, 0) + 1
        t['stop_recovery_attempts'] = t.get('stop_recovery_attempts', 0) + 1
        if t['stop_recovery_attempts'] > 3:
            t['stop_recovery_halted'] = True
            t['closure'] = 'halted_unverified'
            return {'continue': False, 'stopReason': 'TV 收尾核验未通过且重复恢复没有进展；本回合按未核验终止，保留缺口，不能记录成功。'}
        reason = (f'TV_RESUME_{secrets.token_hex(8)}：静默补齐当前回合 {t["id"]} 的规则读取、实际工具回执、'
                  '主线、适用约束、输出核验与候选正文；当前收尾未通过。保留原回合，不重复业务副作用。'
                  '正文已显示的事实不能撤销；发现错误应明确纠正。')
        state.setdefault('continuations', {})[digest(reason)] = t['id']
        return {'decision': 'block', 'reason': reason}

    def handle(self, event):
        name, session = event.get('hook_event_name'), event.get('session_id')
        if not isinstance(session, str) or not session:
            raise ValueError('Missing trusted host session ID')
        with self.locked():
            prompt = event.get('prompt')
            # Host-injected Hook envelopes are recovery input, never a new
            # human authorization or an activation/deactivation command.
            hook_resume = (name == 'UserPromptSubmit' and isinstance(prompt, str)
                           and re.fullmatch(r'(?:\s*<hook_prompt\b[^>]*>.*?</hook_prompt>\s*)+',
                                            prompt, re.S) is not None)
            switch = command_switch(prompt) if name == 'UserPromptSubmit' and not hook_resume else None
            if switch is False:
                return self.disable(session, event)
            control = self.control(session)
            if switch is True and self.replayed_control(control, event):
                return {}
            if control and not control['enabled'] and switch is not True:
                return {}
            registry = self.registry();record = registry['sessions'].get(session)
            if record is None and switch is not True:
                return {}
            if record is None:
                record = self.bind(registry, session, project_root(event['cwd']), {'event': name})
            path, state = self.state(session, record)
            self._upgrade(state, path)
            if name == 'UserPromptSubmit':
                prompt = event.get('prompt')
                if hook_resume or digest(prompt) in state.get('continuations', {}):
                    atomic_json(path, state)
                    return self._context(name, state)
                host_turn = event.get('turn_id')
                if isinstance(host_turn, str) and host_turn and host_turn in state.get('user_events', {}):
                    old = state['user_events'][host_turn]
                    old_hash = old.get('prompt_sha256') if isinstance(old, dict) else old
                    if old_hash != digest(prompt):
                        raise ValueError('Conflicting real user event')
                    return {}
                state['sequence'] = state.get('sequence', 0) + 1
                turn = host_turn if isinstance(host_turn, str) and host_turn else 'user-' + str(state['sequence'])
                if switch is True:
                    source = {'event': name, 'turn_id': host_turn, 'prompt_sha256': digest(prompt), 'at': now()}
                    self.save_control(session, True, source, control)
                    state['activation'].update(enabled=True, activated_by_user_event=source)
                if not state['activation']['enabled']:
                    return {}
                self._begin(state, turn)
                state.setdefault('user_events', {})[turn] = {'prompt_sha256': digest(prompt), 'at': now()}
            elif not state['activation']['enabled']:
                return {}
            if state.get('schema_version') != 6 or not state.get('turn', {}).get('id'):
                return internal_context(name, 'TV 旧状态需在下一条真实用户消息时迁移；诊断和关闭入口保留。')
            if self._management(event, session):
                return {}
            self._refresh(state)
            self._reconcile_denials(state)
            if name == 'PreToolUse':out = self._pre(event, state)
            elif name == 'PostToolUse':out = self._post(event, state)
            elif name == 'Stop':out = self._stop(event, state)
            else:out = self._context(name, state) if name == 'UserPromptSubmit' else {}
            atomic_json(path, state)
            return out

    def status(self):
        with self.locked():
            try:
                registry = self.registry()
                sessions = {key: {'state_root': row.get('state_root')} for key, row in registry['sessions'].items()}
                error = None
            except (ValueError, OSError, KeyError, TypeError) as exc:
                sessions = {};error = type(exc).__name__
            native = []
            try:
                import tomllib
                hooks_path = self.root.parent / 'hooks.json'
                config = json.loads(hooks_path.read_text())
                settings = tomllib.loads((self.root.parent / 'config.toml').read_text()).get('hooks', {}).get('state', {})
                current = hashlib.sha256((self.root / 'process_gate.py').read_bytes()).hexdigest()
                for event, groups in config.get('hooks', {}).items():
                    for gi, group in enumerate(groups):
                        for hi, entry in enumerate(group.get('hooks', [])):
                            if not str(entry.get('statusMessage', '')).startswith(GATE_ID + '/'):
                                continue
                            key = re.sub(r'(?<!^)(?=[A-Z])', '_', event).lower()
                            host = settings.get(f'{hooks_path}:{key}:{gi}:{hi}', {})
                            native.append({'event': event, 'name': entry['statusMessage'], 'enabled': host.get('enabled'),
                                           'trust_record_present': bool(host.get('trusted_hash')),
                                           'command_matches_current_implementation': current in entry.get('command', '')})
            except (ValueError, OSError, KeyError, TypeError):
                pass
            return {'gate_id': GATE_ID, 'adapter_version': VERSION, 'implementation_status': 'goal_alignment_kernel', 'contract_version': CONTRACT_VERSION,
                    'guarantee_scope': 'persistent_goal_alignment_and_exact_actions_with_dependency_aware_output_audit',
                    'events': ['UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop'],
                    'native_entries': native, 'host_execution_verified': False,
                    'note': 'Enabled flags and trust records do not prove current command trust or native dispatch; verify actual callbacks separately.',
                    'delivery_receipt_supported': False, 'pre_display_interception_supported': False,
                    'sessions': sessions, 'state_error': error}


def main():
    if sys.argv[1:] == ['--status']:
        print(json.dumps(Guard().status(), ensure_ascii=False));return
    if len(sys.argv) == 4 and sys.argv[1] == '--session' and sys.argv[3] == '--migrate-state':
        try:
            print(json.dumps(Guard().migrate(sys.argv[2]), ensure_ascii=False))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr);raise SystemExit(2)
        return
    if len(sys.argv) == 5 and sys.argv[1] == '--session' and sys.argv[3] == '--request':
        try:
            print(json.dumps(Guard().request(sys.argv[2], json.loads(sys.argv[4])), ensure_ascii=False))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr);raise SystemExit(2)
        return
    if len(sys.argv) != 1:
        raise SystemExit('Use --status, --session ID --request JSON, --session ID --migrate-state, or provide a native hook event on stdin')
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):raise ValueError('Invalid hook event')
    except Exception:
        print(GATE_ID + ': invalid hook input', file=sys.stderr);raise SystemExit(2)
    try:
        output = Guard().handle(event)
    except Exception as exc:
        name = event.get('hook_event_name', 'PreToolUse')
        output = internal_context(name, GATE_ID + ': state requires recovery (' + type(exc).__name__ + '); preserve evidence, diagnose or explicitly disable.')
        # Fail closed only for a session with a durable enabled intent; never globally lock tools.
        try:
            control = Guard().control(event.get('session_id', ''))
        except Exception:
            control = None
        if (control and control['enabled'] and name == 'PreToolUse'
                and not Guard()._management(event, event.get('session_id')) and not Guard()._read_only(event)):
            output['hookSpecificOutput'].update(permissionDecision='deny', permissionDecisionReason='TV 当前会话状态异常，先诊断或显式关闭。')
        elif control and control['enabled'] and name == 'Stop':
            output = {'continue': False, 'stopReason': 'TV 状态损坏，按未核验终止并保留记录；关闭与诊断入口仍可用。'}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':main()
