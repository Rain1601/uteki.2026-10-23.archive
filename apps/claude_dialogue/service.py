"""One private, append-only Claude conversation shared by the window and Codex.

The original CLI/session stays frozen. This service adds continuations and
explicit window budget events under the original session lock. No background
sends, provider discovery, tools, hidden retries, or implicit budget increases.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time

from scripts import claude_dialogue as d

DialogueError = d.DialogueError
MAX_TOKENS = 4096
MARGIN_TOKENS = 4096
SETTINGS = {'model':d.MODEL, 'thinking':{'type':'adaptive'}, 'reasoning_effort':'high',
            'max_tokens':MAX_TOKENS, 'timeout_seconds':d.TIMEOUT, 'stream':False, 'max_retries':0}
ADVISOR_PROMPT = Path(__file__).parent/'prompts/advisor-v1.md'
FOCUS_POLICY = Path(__file__).resolve().parents[2]/'docs/COLLABORATION_FOCUS.zh-CN.md'
ERROR_CODES = frozenset({'http_non_success', 'invalid_response', 'invalid_content',
    'credential_in_response', 'incomplete_or_empty_response', 'usage_or_price_unknown',
    'unexpected_returned_model', 'timeout', 'cancelled', 'request_failed', 'interrupted'})


def _money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise DialogueError('invalid_money_value') from None


def _read_json(path):
    return json.loads(d._read(path))


def _mkdir(path):
    if not path.exists():
        path.mkdir(mode=0o700)
    d._private(path, True)


def _checked_request(body, system, history, user):
    if (set(body) != {'model','system','messages','max_tokens','thinking','output_config','stream'}
            or body['model'] != d.MODEL or body['system'] != system
            or body['thinking'] != {'type':'adaptive'} or body['output_config'] != {'effort':'high'}
            or body['stream'] is not False or type(body['max_tokens']) is not int
            or not 1 <= body['max_tokens'] <= 16000
            or body['messages'] != history + [{'role':'user','content':user}]):
        raise DialogueError('dialogue_request_chain_invalid')


def _options(max_tokens=None, continue_after_failed_turn=None):
    maximum = MAX_TOKENS if max_tokens is None else max_tokens
    if type(maximum) is not int or not 1 <= maximum <= 16000:
        raise DialogueError('invalid_max_tokens')
    if continue_after_failed_turn is not None and (
            type(continue_after_failed_turn) is not int or continue_after_failed_turn < 1):
        raise DialogueError('invalid_failed_turn_selection')
    return maximum, continue_after_failed_turn


def _recoverable(entry):
    """Only a complete provider response with known cost can be acknowledged."""
    r = entry['receipt']
    return (r['status']=='failed' and r.get('estimated_usd') is not None
        and bool(r.get('ended_at')) and r.get('dispatch_status')=='sent'
        and r.get('http_status')==200 and r.get('usage_presence')=='reported'
        and r.get('returned_model')==d.MODEL
        and r.get('stop_reason') in {'end_turn','max_tokens','refusal','stop_sequence','tool_use','pause_turn'})


def _failure_context(entry):
    r = entry['receipt']
    return {'role':'user','content':
        'Local dialogue record: the previous attempt failed and is not a completed assistant answer. '
        'Its original request and any visible partial text are retained below for context. '
        'Follow the next user message; do not treat this partial text as verified.\n' +
        json.dumps({'failed_turn':r['turn'],'status':'failed','error_code':r.get('error_code'),
            'stop_reason':r.get('stop_reason'),'original_user_message':entry['user'],
            'visible_partial_answer':entry['answer']},ensure_ascii=False)}


def _compose_system(base, components):
    return base + '\n\n' + '\n\n'.join(
        '[Maintained advisor policy: '+name+']\n'+components[name]['text']
        for name in ('advisor','collaboration_focus'))


def _check_prompt_snapshot(snapshot, base):
    if (set(snapshot) != {'schema_version','base_system_sha256','components','effective_system_sha256'}
            or snapshot['schema_version']!='claude-advisor-system-v1'
            or snapshot['base_system_sha256']!=d._sha(base.encode())
            or not isinstance(snapshot['components'],dict)
            or set(snapshot['components'])!={'advisor','collaboration_focus'}):
        raise DialogueError('system_prompt_snapshot_invalid')
    for component in snapshot['components'].values():
        if (not isinstance(component,dict) or set(component)!={'text','sha256'}
                or not isinstance(component['text'],str) or not component['text'].strip()
                or len(component['text'].encode())>d.MAX_BYTES
                or d._sha(component['text'].encode())!=component['sha256']):
            raise DialogueError('system_prompt_snapshot_invalid')
    effective = _compose_system(base,snapshot['components'])
    if d._sha(effective.encode())!=snapshot['effective_system_sha256']:
        raise DialogueError('system_prompt_snapshot_invalid')
    return effective


class DialogueService:
    def __init__(self, base, *, credentials_root, client_factory=None,
                 advisor_prompt_path=ADVISOR_PROMPT, focus_policy_path=FOCUS_POLICY):
        self.base = Path(base).absolute()
        self.session = self.base/'session'
        self.window = self.base/'window'
        self.credentials_root = Path(credentials_root)
        self.client_factory = client_factory
        self.prompt_paths = {'advisor':Path(advisor_prompt_path),'collaboration_focus':Path(focus_policy_path)}

    def _current_prompt(self, base):
        try:
            components = {}
            for name,path in self.prompt_paths.items():
                text = path.read_text(encoding='utf-8')
                components[name] = {'text':text,'sha256':d._sha(text.encode())}
            snapshot = {'schema_version':'claude-advisor-system-v1',
                'base_system_sha256':d._sha(base.encode()),'components':components,
                'effective_system_sha256':d._sha(_compose_system(base,components).encode())}
            return _check_prompt_snapshot(snapshot,base), snapshot
        except (OSError,ValueError,TypeError,UnicodeError,DialogueError):
            raise DialogueError('advisor_prompt_unavailable') from None

    def _load(self):
        """Called under the old CLI's lock. Never changes a history file."""
        try:
            return self._load_checked()
        except DialogueError:
            raise
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            raise DialogueError('dialogue_integrity_failed') from None

    def _load_checked(self):
        d._private(self.base, True)
        config, system, price, _, initial, session_sha = d._state(self.session)
        if config['model'] != d.MODEL:
            raise DialogueError('unsupported_session_model')
        folders = [(self.session/'turns'/f'{i:04d}', r) for i,r in enumerate(initial,1)]
        parent = self.base/'continuations'
        if parent.exists():
            d._private(parent, True)
            for number,folder in enumerate(sorted(parent.iterdir()),len(initial)+1):
                if folder.name != f'{number:04d}':
                    raise DialogueError('continuation_sequence_invalid')
                folders.append((folder, None))
        history, rows, hashes, base_hashes = [], [], [], []
        blocked = False
        for number,(folder, initial_receipt) in enumerate(folders,1):
            d._private(folder, True)
            recovery = None
            if blocked:
                previous = rows[-1]
                if not _recoverable(previous) or not (folder/'failure-recovery.json').exists():
                    raise DialogueError('continuation_after_failed_turn')
                recovery = _read_json(folder/'failure-recovery.json')
                if (recovery.get('schema_version')!='claude-dialogue-failure-recovery-v1'
                        or recovery.get('event')!='failed_turn_explicitly_acknowledged'
                        or recovery.get('failed_turn')!=previous['receipt']['turn']
                        or recovery.get('failed_receipt_sha256')!=previous['receipt_sha256']
                        or recovery.get('known_estimated_usd')!=previous['receipt']['estimated_usd']
                        or recovery.get('next_turn')!=number
                        or recovery.get('context_policy')!='explicit_failed_user_record_with_visible_partial_v1'):
                    raise DialogueError('failure_recovery_changed')
                history.append(_failure_context(previous))
            elif (folder/'failure-recovery.json').exists():
                raise DialogueError('unexpected_failure_recovery')
            user = d._read(folder/'user.md').decode() if (folder/'user.md').exists() else ''
            authorization = None
            if not (folder/'receipt.json').exists() or not (folder/'receipt.sha256').exists():
                started = _read_json(folder/'started.json') if (folder/'started.json').exists() else {}
                row = {'turn':number, 'status':'interrupted', 'estimated_usd':None,
                       'reserved_usd':started.get('reserved_usd',config['budget_usd']),
                       'started_at':started.get('started_at'), 'error_code':'interrupted'}
                if 'actor' in started:
                    row['actor'] = started['actor']
                answer = d._read(folder/'answer.md').decode() if (folder/'answer.md').exists() else ''
                partial_hashes = {p.name:d._sha(d._read(p)) for p in sorted(folder.iterdir()) if p.is_file()}
                receipt_sha, request = d._sha(d._json(partial_hashes)), None
            else:
                raw_receipt = d._read(folder/'receipt.json')
                receipt_sha = d._sha(raw_receipt)
                if d._read(folder/'receipt.sha256').decode() != receipt_sha:
                    raise DialogueError('turn_receipt_changed')
                row = json.loads(raw_receipt)
                if row.get('turn') != number or row.get('status') not in {'completed','failed'}:
                    raise DialogueError('turn_receipt_invalid')
                for name,field in [('user.md','user_sha256'),('request.json','request_sha256'),
                                   ('answer.md','answer_sha256'),('configuration.json','configuration_sha256')]:
                    if d._sha(d._read(folder/name)) != row[field]:
                        raise DialogueError('turn_artifact_changed')
                if d._read(folder/'request.sha256').decode() != row['request_sha256']:
                    raise DialogueError('turn_artifact_changed')
                answer = d._read(folder/'answer.md').decode()
                request = _read_json(folder/'request.json')
                turn_system = system
                prompt_sha = row.get('system_prompt_snapshot_sha256')
                if prompt_sha is not None:
                    prompt_raw = d._read(folder/'system-prompt.json')
                    if initial_receipt is not None or d._sha(prompt_raw)!=prompt_sha:
                        raise DialogueError('system_prompt_snapshot_changed')
                    turn_system = _check_prompt_snapshot(json.loads(prompt_raw),system)
                elif (folder/'system-prompt.json').exists():
                    raise DialogueError('unexpected_system_prompt_snapshot')
                _checked_request(request,turn_system,history,user)
                snapshot = d.validate_configuration_snapshot(_read_json(folder/'configuration.json'))
                if (snapshot['fingerprints']['system_sha256'] != d._sha(turn_system.encode())
                        or snapshot['fingerprints']['input_sha256'] != d._sha(d._json(request['messages']))):
                    raise DialogueError('turn_configuration_changed')
                if initial_receipt is None:
                    auth_raw = d._read(folder/'authorization.json')
                    authorization = json.loads(auth_raw)
                    if (d._sha(auth_raw) != row['authorization_sha256']
                            or row['parent_session_sha256'] != session_sha
                            or authorization['parent_session_sha256'] != session_sha
                            or authorization['parent_receipt_sha256'] != base_hashes
                            or authorization['prior_calls'] != number-1
                            or (number > len(initial)+1 and authorization.get('parent_continuation_receipt_sha256') != hashes[-1])):
                        raise DialogueError('continuation_authorization_changed')
                    if _read_json(folder/'price.json') != price:
                        raise DialogueError('continuation_price_changed')
                    if authorization.get('system_prompt_snapshot_sha256')!=prompt_sha:
                        raise DialogueError('system_prompt_snapshot_changed')
                    if recovery is not None and (
                            authorization.get('failure_recovery_sha256') != d._sha(d._read(folder/'failure-recovery.json'))
                            or recovery.get('actor') != authorization.get('actor')
                            or recovery.get('expected_revision') != authorization.get('expected_revision')
                            or recovery.get('max_tokens') != request['max_tokens']):
                        raise DialogueError('failure_recovery_changed')
                    if recovery is None and authorization.get('failure_recovery_sha256') is not None:
                        raise DialogueError('unexpected_failure_recovery')
                else:
                    base_hashes.append(receipt_sha)
                cost = row.get('estimated_usd')
                if cost is not None:
                    expected = ('0' if row.get('dispatch_status') == 'not_sent' else
                        d.estimate_anthropic_usage(row.get('raw_usage'),dict(price,cached_input_per_million=price['cache_read_per_million'])))
                    if expected is None or _money(cost) != _money(expected):
                        raise DialogueError('turn_cost_changed')
                if row['status'] == 'completed':
                    if (row.get('stop_reason') != 'end_turn' or not answer.strip() or cost is None
                            or row.get('returned_model') != d.MODEL):
                        raise DialogueError('completed_turn_invalid')
                    history.extend([{'role':'user','content':user},{'role':'assistant','content':answer}])
            blocked = row['status'] != 'completed'
            _money(row['reserved_usd'])
            rows.append({'receipt':row,'request':request,'user':user,'answer':answer,'receipt_sha256':receipt_sha,
                         'authorization':authorization,'recovery':recovery})
            hashes.append(receipt_sha)
        events, event_hashes, cap = [], [], _money(config['budget_usd'])
        if self.window.exists():
            d._private(self.window, True)
            if (self.window/'configuration.json').exists():
                if _read_json(self.window/'configuration.json') != self._window_configuration(config,session_sha):
                    raise DialogueError('window_configuration_changed')
            event_folder = self.window/'events'
            if event_folder.exists():
                d._private(event_folder, True)
                for number,path in enumerate(sorted(event_folder.iterdir()),1):
                    if path.name != f'{number:04d}.json':
                        raise DialogueError('window_event_sequence_invalid')
                    raw = d._read(path)
                    event = json.loads(raw)
                    if (event['event'] != 'budget_authorized' or event['actor'] != 'user'
                            or event['parent_session_sha256'] != session_sha
                            or event['previous_event_sha256'] != (event_hashes[-1] if event_hashes else None)):
                        raise DialogueError('window_event_chain_invalid')
                    cap = _money(event['cumulative_budget_usd'])
                    events.append(event)
                    event_hashes.append(d._sha(raw))
        for index,entry in enumerate(rows):
            authorization = entry['authorization']
            if not authorization or 'expected_revision' not in authorization:
                continue  # Frozen historical runners predate window events.
            event_head = authorization.get('window_event_sha256')
            if event_head is not None and event_head not in event_hashes:
                raise DialogueError('continuation_window_event_missing')
            event_count = event_hashes.index(event_head)+1 if event_head else 0
            revision_inputs = {'session':session_sha,'receipts':hashes[:index],'events':event_hashes[:event_count]}
            if authorization.get('system_prompt_snapshot_sha256') is not None:
                revision_inputs['system_prompt_snapshot_sha256'] = authorization['system_prompt_snapshot_sha256']
            expected_revision = d._sha(d._json(revision_inputs))
            authorized_cap = events[event_count-1]['cumulative_budget_usd'] if event_count else config['budget_usd']
            if (authorization['expected_revision'] != expected_revision
                    or authorization.get('actor') != entry['receipt'].get('actor')
                    or _money(authorization['cumulative_budget_usd']) != _money(authorized_cap)):
                raise DialogueError('continuation_window_authorization_changed')
        spent = sum((_money(r['receipt']['estimated_usd']) for r in rows if r['receipt'].get('estimated_usd') is not None),Decimal(0))
        held = sum((_money(r['receipt']['reserved_usd']) for r in rows if r['receipt'].get('estimated_usd') is None),Decimal(0))
        prompt_error = None
        try:
            effective_system, prompt = self._current_prompt(system)
            prompt_sha = d._sha(d._json(prompt))
        except DialogueError as error:
            effective_system, prompt, prompt_sha = None, None, None
            prompt_error = str(error)
        revision = d._sha(d._json({'session':session_sha,'receipts':hashes,'events':event_hashes,
                                  'system_prompt_snapshot_sha256':prompt_sha}))
        return {'config':config,'system':system,'price':price,'history':history,'rows':rows,'session_sha':session_sha,
                'base_hashes':base_hashes,'events':events,'event_hashes':event_hashes,'revision':revision,
                'effective_system':effective_system,'prompt_snapshot':prompt,'prompt_sha256':prompt_sha,'prompt_error':prompt_error,
                'cap':cap,'spent':spent,'held':held,'remaining':cap-spent-held,'blocked':blocked}

    def _window_configuration(self,config,session_sha):
        return {'schema_version':'claude-dialogue-window-v1','parent_session_sha256':session_sha,
                'original_budget_usd':config['budget_usd'],'price_sha256':config['price_sha256'],
                'settings':SETTINGS,'cost_basis':'frozen_public_price_estimate_not_bill'}

    def _ensure_window(self,state):
        _mkdir(self.window)
        _mkdir(self.window/'events')
        path = self.window/'configuration.json'
        if not path.exists():
            d._write(path,d._json(self._window_configuration(state['config'],state['session_sha'])))

    @staticmethod
    def _expect(state,revision):
        if not isinstance(revision,str) or revision != state['revision']:
            raise DialogueError('revision_conflict')

    @staticmethod
    def _message(message):
        if not isinstance(message,str) or not message.strip() or len(message.encode()) > d.MAX_BYTES:
            raise DialogueError('message_empty_or_too_large')
        return message

    @staticmethod
    def _body(state,message,max_tokens=MAX_TOKENS,continue_after_failed_turn=None):
        history = state['history'][:]
        if continue_after_failed_turn is not None:
            history.append(_failure_context(state['rows'][-1]))
        return {'model':d.MODEL,'system':state['effective_system'],'messages':history+[{'role':'user','content':message}],
                'thinking':{'type':'adaptive'},'output_config':{'effort':'high'},'max_tokens':max_tokens,'stream':False}

    def _reservation(self,state,body):
        raw = d._json(body)
        tokens = len(raw)+MARGIN_TOKENS
        basis = {'method':'full_request_utf8_bytes','framing_margin_tokens':MARGIN_TOKENS,
                 'input_token_reservation':tokens,'output_token_reservation':body['max_tokens']}
        if state['rows']:
            previous = state['rows'][-1]
            request,receipt = previous['request'],previous['receipt']
            usage,presence = d._numeric_usage(receipt.get('raw_usage'))
            if (request and receipt['status']=='completed' and receipt.get('returned_model')==d.MODEL
                    and presence=='reported' and all(body[k]==request[k] for k in body if k!='messages')
                    and body['messages'][:-2]==request['messages']):
                prefix = sum(usage.get(k,0) for k in ('input_tokens','cache_read_input_tokens','cache_creation_input_tokens'))
                if prefix > 0:
                    suffix = len(d._json(body['messages'][-2:]))
                    tokens = prefix+suffix+MARGIN_TOKENS
                    basis.update(method='verified_prefix_reported_tokens_plus_suffix_utf8_bytes',
                        prefix_input_tokens=prefix,suffix_utf8_bytes=suffix,input_token_reservation=tokens,
                        prior_receipt_sha256=previous['receipt_sha256'])
        price = state['price']
        reserved = (Decimal(tokens)*Decimal(str(price['input_per_million'])) +
                    Decimal(body['max_tokens'])*Decimal(str(price['output_per_million'])))/1000000
        return raw,reserved,basis

    def _preflight(self,state,message,max_tokens=MAX_TOKENS,continue_after_failed_turn=None):
        if state['prompt_error']:
            return {'revision':state['revision'],'allowed':False,'reason':state['prompt_error'],
                'reserve_usd':None,'remaining_usd':str(state['remaining']),'cumulative_budget_usd':str(state['cap']),
                'request_bytes':None,'reservation_basis':None,'cost_basis':'frozen_public_price_estimate_not_bill',
                'actual_billed_usd':None}
        if continue_after_failed_turn is not None and (not state['blocked'] or not state['rows']
                or state['rows'][-1]['receipt']['turn']!=continue_after_failed_turn
                or not _recoverable(state['rows'][-1]) or state['held']!=0):
            raise DialogueError('failed_turn_not_recoverable')
        raw,reserved,basis = self._reservation(state,self._body(state,message,max_tokens,continue_after_failed_turn))
        reason = ('previous_turn_failed_or_interrupted' if state['blocked'] and continue_after_failed_turn is None else
                  'request_too_large' if len(raw)>d.MAX_BYTES else
                  'budget_insufficient' if reserved>state['remaining'] else None)
        return {'revision':state['revision'],'allowed':reason is None,'reason':reason,'reserve_usd':str(reserved),
                'remaining_usd':str(state['remaining']),'cumulative_budget_usd':str(state['cap']),
                'request_bytes':len(raw),'reservation_basis':basis,'cost_basis':'frozen_public_price_estimate_not_bill',
                'actual_billed_usd':None}

    def _view(self,state):
        turns,messages = [],[]
        for entry in state['rows']:
            r = entry['receipt']
            actor = r.get('actor','codex')
            if actor not in {'user','codex'}:
                raise DialogueError('invalid_recorded_actor')
            turn = {'number':r['turn'],'actor':actor,'actor_recorded':'actor' in r,
                'status':r['status'],'user':entry['user'],'answer':entry['answer'],
                'started_at':r.get('started_at'),'ended_at':r.get('ended_at'),
                'model':r.get('returned_model') if r.get('returned_model')==d.MODEL else None,
                'estimated_usd':r.get('estimated_usd'),'reserved_usd':r['reserved_usd'],
                'stop_reason':r.get('stop_reason') if r.get('stop_reason') in {'end_turn','max_tokens','refusal','stop_sequence','tool_use','pause_turn'} else None,
                'error_code':r.get('error_code') if r.get('error_code') in ERROR_CODES else 'request_failed' if r.get('error_code') else None,
                'max_tokens':entry['request'].get('max_tokens') if entry['request'] else None,
                'system_prompt_snapshot_sha256':r.get('system_prompt_snapshot_sha256'),
                'continued_after_failed_turn':entry['recovery']['failed_turn'] if entry['recovery'] else None}
            turns.append(turn)
            for role,content in [('user',entry['user']),('assistant',entry['answer'])]:
                if content:
                    messages.append({'turn':r['turn'],'role':role,'actor':actor if role=='user' else 'claude',
                        'initiated_by':actor,'actor_recorded':'actor' in r,'content':content,'status':r['status'],
                        'time':turn['started_at'] if role=='user' else turn['ended_at'],'model':turn['model'],
                        'estimated_usd':turn['estimated_usd'],'stop_reason':turn['stop_reason'],'error_code':turn['error_code']})
        minimum = self._preflight(state,'')
        prompt = state['prompt_snapshot']
        prompt_view = {'status':'unavailable' if state['prompt_error'] else 'ready',
            'schema_version':prompt['schema_version'] if prompt else None,
            'snapshot_sha256':state['prompt_sha256'],
            'effective_system_sha256':prompt['effective_system_sha256'] if prompt else None,
            'component_sha256':{name:item['sha256'] for name,item in prompt['components'].items()} if prompt else {}}
        return {'revision':state['revision'],'model':d.MODEL,'configuration':{**json.loads(d._json(SETTINGS)),
                'advisor_prompt':prompt_view},
                'summary':{'budget_usd':str(state['cap']),'original_budget_usd':state['config']['budget_usd'],
                    'estimated_spent_usd':str(state['spent']),'held_usd':str(state['held']),
                    'remaining_usd':str(state['remaining']),'attempted_turns':len(turns),
                    'completed_turns':sum(t['status']=='completed' for t in turns),'unknown_cost_turns':sum(r['estimated_usd'] is None for r in turns),
                    'blocked':state['blocked'],'send_blocked_reason':minimum['reason'],
                    'minimum_next_turn_reserved_usd':minimum['reserve_usd'],
                    'cost_basis':'frozen_public_price_estimate_not_bill','actual_billed_usd':None},
                'price':state['price'].copy(),'turns':turns,'messages':messages,
                'budget_events':[{'number':i,'actor':'user','at':event['at'],'cumulative_budget_usd':event['cumulative_budget_usd']}
                                 for i,event in enumerate(state['events'],1)]}

    def history(self):
        with d._locked(self.session):
            return self._view(self._load())

    def preflight(self,message,expected_revision,*,max_tokens=None,continue_after_failed_turn=None):
        message = self._message(message)
        maximum, recovery_turn = _options(max_tokens,continue_after_failed_turn)
        with d._locked(self.session):
            state = self._load()
            self._expect(state,expected_revision)
            return self._preflight(state,message,maximum,recovery_turn)

    def set_budget(self,budget_usd,expected_revision,actor='user'):
        if actor != 'user':
            raise DialogueError('budget_requires_explicit_user')
        cap = _money(budget_usd)
        if cap <= 0:
            raise DialogueError('invalid_budget')
        with d._locked(self.session):
            state = self._load()
            self._expect(state,expected_revision)
            if cap < state['spent']+state['held']:
                raise DialogueError('budget_below_committed_cost')
            self._ensure_window(state)
            event = {'schema_version':'claude-dialogue-window-event-v1','event':'budget_authorized','actor':'user',
                'at':d._now(),'parent_session_sha256':state['session_sha'],'expected_revision':expected_revision,
                'previous_event_sha256':state['event_hashes'][-1] if state['event_hashes'] else None,
                'previous_budget_usd':str(state['cap']),'cumulative_budget_usd':str(cap)}
            d._write(self.window/'events'/f'{len(state["events"])+1:04d}.json',d._json(event))
            return self._view(self._load())

    async def send(self,message,expected_revision,actor='user',*,max_tokens=None,continue_after_failed_turn=None):
        message = self._message(message)
        maximum, recovery_turn = _options(max_tokens,continue_after_failed_turn)
        if actor not in {'user','codex'}:
            raise DialogueError('invalid_actor')
        with d._locked(self.session):
            state = self._load()
            self._expect(state,expected_revision)
            check = self._preflight(state,message,maximum,recovery_turn)
            if not check['allowed']:
                raise DialogueError(check['reason'])
            body = self._body(state,message,maximum,recovery_turn)
            raw,reserved,basis = self._reservation(state,body)
            try:
                d.load_provider_key(self.credentials_root,'aihubmix')
                key = os.environ['AIHUBMIX_API_KEY']
                if not key:
                    raise ValueError
            except Exception:
                raise DialogueError('credentials_unavailable') from None
            if key.encode() in raw:
                raise DialogueError('credential_in_request')
            self._ensure_window(state)
            _mkdir(self.base/'continuations')
            number = len(state['rows'])+1
            folder = self.base/'continuations'/f'{number:04d}'
            folder.mkdir(mode=0o700)
            authorization = {'schema_version':'dialogue-continuation-authorization-v1','actor':actor,
                'created_at':d._now(),'additional_calls':1,'prior_calls':number-1,'total_authorized_calls':number,
                'parent_session_sha256':state['session_sha'],'parent_receipt_sha256':state['base_hashes'],
                'parent_continuation_receipt_sha256':state['rows'][-1]['receipt_sha256'] if number>len(state['base_hashes'])+1 else None,
                'expected_revision':expected_revision,'window_event_sha256':state['event_hashes'][-1] if state['event_hashes'] else None,
                'cumulative_budget_usd':str(state['cap']),'prior_estimated_usd':str(state['spent']),
                'reservation_basis':basis,'scope':'One explicit message in the shared local conversation.'}
            authorization['system_prompt_snapshot_sha256'] = state['prompt_sha256']
            d._write(folder/'system-prompt.json',d._json(state['prompt_snapshot']))
            if recovery_turn is not None:
                previous = state['rows'][-1]
                recovery = {'schema_version':'claude-dialogue-failure-recovery-v1',
                    'event':'failed_turn_explicitly_acknowledged','actor':actor,'at':d._now(),
                    'failed_turn':recovery_turn,'failed_receipt_sha256':previous['receipt_sha256'],
                    'known_estimated_usd':previous['receipt']['estimated_usd'],
                    'next_turn':number,'expected_revision':expected_revision,'max_tokens':maximum,
                    'context_policy':'explicit_failed_user_record_with_visible_partial_v1'}
                recovery_raw = d._json(recovery)
                authorization['failure_recovery_sha256'] = d._sha(recovery_raw)
                d._write(folder/'failure-recovery.json',recovery_raw)
            snapshot = d.build_configuration_snapshot(
                {'provider':'aihubmix','api_format':'anthropic_messages','base_url':'https://aihubmix.com',**SETTINGS,'max_tokens':maximum},
                capture_kind='before_dispatch',capture_layer='http_request_before_dispatch',source='http_request',
                statuses={k:'not_sent' for k in ('temperature','top_p','top_k','seed','response_format','tool_choice','parallel_tool_calls')},
                fingerprints={'system_sha256':d._sha(body['system'].encode()),'input_sha256':d._sha(d._json(body['messages'])),
                              'tools_sha256':d._sha(b'[]')})
            receipt = {'schema_version':'claude-dialogue-continuation-v1','turn':number,'actor':actor,'status':'failed',
                'parent_session_sha256':state['session_sha'],'authorization_sha256':d._sha(d._json(authorization)),
                'runner_sha256':d._sha(Path(__file__).read_bytes()),'started_at':d._now(),
                'user_sha256':d._sha(message.encode()),'request_sha256':d._sha(raw),'request_bytes':len(raw),
                'configuration_sha256':d._sha(d._json(snapshot)),'price_sha256':state['config']['price_sha256'],
                'system_prompt_snapshot_sha256':state['prompt_sha256'],
                'reserved_usd':str(reserved),'reservation_basis':basis,'estimated_usd':None,
                'prior_estimated_usd':str(state['spent']),'cumulative_budget_usd':str(state['cap']),
                'actual_billed_usd':None,'cost_basis':'frozen_public_price_estimate_not_bill',
                'dispatch_status':'not_sent','max_retries':0,'raw_usage':None,'usage_presence':'absent',
                'stop_reason':None,'error_code':None}
            for name,data in [('user.md',message.encode()),('started.json',d._json(receipt)),
                    ('authorization.json',d._json(authorization)),('request.json',raw),('request.sha256',d._sha(raw).encode()),
                    ('configuration.json',d._json(snapshot)),('price.json',d._json(state['price']))]:
                d._write(folder/name,data)
            await self._dispatch(folder,raw,key,state,receipt)
            return self._view(self._load())

    async def _dispatch(self,folder,raw,key,state,receipt):
        client,answer,started = None,'',time.monotonic()
        try:
            client = (self.client_factory or d.httpx.AsyncClient)(timeout=d.TIMEOUT,follow_redirects=False,
                trust_env=False,transport=d.httpx.AsyncHTTPTransport(retries=0))
            d._write(folder/'dispatched.json',d._json({'at':d._now(),'request_sha256':d._sha(raw)}))
            receipt['dispatch_status']='sent'
            with d._suppress_transport_logging():
                response = await asyncio.wait_for(client.post(d.ENDPOINT,content=raw,headers={
                    'x-api-key':key,'anthropic-version':'2023-06-01','content-type':'application/json'}),d.TIMEOUT)
            receipt.update(http_status=response.status_code,
                request_id=d._identifier(response.headers.get('request-id') or response.headers.get('x-request-id'),key))
            if response.status_code != 200:
                raise DialogueError('http_non_success')
            payload=response.json()
            if not isinstance(payload,dict):
                raise DialogueError('invalid_response')
            usage,presence = d._numeric_usage(payload.get('usage'))
            receipt.update(raw_usage=usage,usage_presence=presence,
                response_id=d._identifier(payload.get('id'),key),returned_model=d._identifier(payload.get('model'),key),
                stop_reason=d._identifier(payload.get('stop_reason'),key))
            if presence=='reported':
                receipt['estimated_usd']=d.estimate_anthropic_usage(usage,dict(state['price'],cached_input_per_million=state['price']['cache_read_per_million']))
            content=payload.get('content')
            if not isinstance(content,list):
                raise DialogueError('invalid_content')
            visible=''.join(b['text'] for b in content if isinstance(b,dict) and b.get('type')=='text' and isinstance(b.get('text'),str))
            if key in visible:
                raise DialogueError('credential_in_response')
            answer=visible
            if receipt['stop_reason']!='end_turn' or not answer.strip():
                raise DialogueError('incomplete_or_empty_response')
            if receipt['estimated_usd'] is None:
                raise DialogueError('usage_or_price_unknown')
            if receipt['returned_model']!=d.MODEL:
                raise DialogueError('unexpected_returned_model')
            receipt['status']='completed'
        except BaseException as error:
            receipt['error_code']=(str(error) if isinstance(error,DialogueError) and str(error) in ERROR_CODES else
                'timeout' if isinstance(error,(TimeoutError,d.httpx.TimeoutException)) else
                'cancelled' if isinstance(error,asyncio.CancelledError) else 'request_failed')
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    receipt['client_close_error']=True
            if receipt['dispatch_status']=='not_sent':
                receipt['estimated_usd']='0'
            receipt.update(answer_sha256=d._sha(answer.encode()),ended_at=d._now(),elapsed_seconds=time.monotonic()-started,
                cumulative_estimated_usd=str(state['spent']+_money(receipt['estimated_usd'])) if receipt['estimated_usd'] is not None else None)
            d._write(folder/'answer.md',answer.encode())
            raw_receipt=d._json(receipt)
            d._write(folder/'receipt.json',raw_receipt)
            d._write(folder/'receipt.sha256',d._sha(raw_receipt).encode())
