"""A shared business binding, not a model loop or SDK session implementation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import uuid

from pydantic import ValidationError, create_model

from ..contracts.common import CatalogError, Contract, canonical, project
from ..contracts.query import TOOLS
from ..contracts.run import ClarifyRequest, DeliveryNeed, DeliveryRequest, ResultRef, TaskProgress, TaskState, result_handle


# SDK 仅暴露这些共享业务工具；描述和参数封装共同约束请求与任务状态的提交。
DESCRIPTIONS = {
    'find_assets': 'Find published materials within the caller identity, source and time boundaries.',
    'get_asset_schema': 'Inspect one exact material version and its actual available capabilities.',
    'search_asset': 'Locate text, outlines or source concepts within one exact material version. Responses are byte-bounded pages; follow next_cursor. On ITEM_TOO_LARGE, increase max_bytes at that cursor or start a narrower search/read_evidence for the indicated target. Never treat a page or snippet as the full source.',
    'read_evidence': 'Read source evidence and necessary context at exact frozen locations.',
    'query_records': 'Read source records or calculate using explicit compatible operands and units.',
    'request_asset_update': 'Request explicitly permitted acquisition or processing; errors are not completion.',
    'deliver': 'Finish only with previously displayed result references and explicit gaps for every need.',
    'clarify': 'Ask one focused question about unresolved needs and stop until the caller explicitly answers.',
}
# 模型交付不接受自由 note；原文说明只能经 source_claims 的逐字摘录提交。
DeliveryNeedInput = project('DeliveryNeedInput', DeliveryNeed,
    ('need_id', 'status', 'result_refs', 'gaps', 'limitations', 'source_claims'))
DeliveryInput = project('DeliveryInput', DeliveryRequest, ('conflicts', 'stop_reason'),
    needs=(tuple[DeliveryNeedInput, ...], ...))
ENVELOPES = {name: create_model(name.title().replace('_','')+'Call', __base__=Contract,
    request=(request, ...), state=(TaskState, ...))
    for name, request in (dict(TOOLS) | {'deliver': DeliveryInput,'clarify':ClarifyRequest}).items()}
for name in DESCRIPTIONS:
    if name == 'deliver':
        DESCRIPTIONS[name] = ('Finish with request.needs covering every planned need exactly once, using observed result handles. '
            'Explicitly judge supported/partial/unresolved and gaps; put disclosed source qualifications in limitations, not missing-work gaps. The host derives task state from these declarations. '
            'Do not send state or note. '
            'Source claims require source_claims[{statement,support:[{result_ref,quote}]}] with exact observed source text; metadata is not source support. Quote matching does not certify semantic interpretation.')
    elif name == 'clarify':
        DESCRIPTIONS[name] += (' Set state.next_action to clarify. Every plan need must appear exactly once in '
            'state.satisfied or state.gaps. Supply plan_update until a nonempty plan is committed; '
            'an error response reports current_task_state, not an assumed successful update.')
    else:
        DESCRIPTIONS[name] += (' state is a progress delta: reason plus initial/new add_needs and optional changed satisfied/gaps only. '
            'The host preserves omitted needs and owns plan versions and next_action. '
            'New needs stay unresolved until explicitly supported; deliver still requires a judgment for every need.')


# 递归提取严格匹配 ResultRef 结构的引用，使用规范字节便于集合去重与可见性校验。
def references(value):
    found = set()
    if isinstance(value, dict):
        if set(value) == {'run_id', 'operation_id', 'kind', 'item_id'}:
            found.add(canonical(ResultRef.model_validate(value).model_dump(mode='json')))
        else:
            for item in value.values():
                found.update(references(item))
    elif isinstance(value, (tuple, list)):
        for item in value:
            found.update(references(item))
    return found


# 连接 SDK 工具回调与 DataService：统一校验、串行调用和结果可见性，不实现模型循环。
class ToolBinding:
    # 固定本次上下文快照，并分别记录已返回结果、模型输入中已观察结果及业务终态。
    def __init__(self, service, context_ref, *, journal=None):
        self.service, self.context_ref = service, context_ref
        snapshot = service.inspect_context(context_ref)
        self.document_mode = bool(snapshot['context']['request'].get('documents'))
        self.envelopes = ENVELOPES
        if snapshot['context']['request'].get('documents'):
            from .document_contracts import document_envelopes
            self.envelopes = document_envelopes(ENVELOPES)
        self.context = snapshot['context'] | {'task_state':{k:snapshot[k] for k in
            ('plan','plan_history','state','inherited_state','turns','wall_seconds','no_progress_turns')}}
        if self.context['request'].get('documents'):
            self.context['request']['documents'].pop('data_root', None)  # Host path is not a model-selected input.
        self.lock = asyncio.Lock()
        self.events = []
        self.returned = []
        self.visible = set()
        self.delivery = None
        self.clarification = None
        self.terminal_requested = False
        self.journal = journal

    def tool_schema(self, name):
        """Project state and references at the SDK boundary; canonical service contracts stay unchanged."""
        schema = self.envelopes[name].model_json_schema()
        definitions = schema.get('$defs', {})
        if name not in {'deliver', 'clarify'}:
            progress = TaskProgress.model_json_schema()
            definitions.update(progress.pop('$defs', {}))
            definitions['TaskProgress'] = progress
            schema['$defs'] = definitions
            schema['properties']['state'] = {'$ref':'#/$defs/TaskProgress'}
        if 'ResultRef' in definitions:
            definitions['ResultRef'] = dict(type='object',additionalProperties=False,
                properties=dict(handle=dict(type='string',pattern='^rr_[0-9a-f]{16}$',
                    description='Copy result_handle from observed metadata/evidence/record/calculation. Metadata is not source content. Never construct IDs.')),
                required=['handle'],title='ObservedResultHandle')
        if name == 'deliver':
            schema['properties'].pop('state')
            schema['required'].remove('state')
        # Do not advertise unreachable legacy state/version definitions.
        reachable = set()
        def visit(value):
            if isinstance(value,dict):
                ref = value.get('$ref','')
                if ref.startswith('#/$defs/'):
                    key = ref.removeprefix('#/$defs/')
                    if key not in reachable:
                        reachable.add(key)
                        visit(definitions[key])
                for key,child in value.items():
                    if key != '$defs':visit(child)
            elif isinstance(value,list):
                for child in value:visit(child)
        visit(schema)
        schema['$defs'] = {key:value for key,value in definitions.items() if key in reachable}
        return schema

    def tool_description(self, name):
        if self.document_mode and name == 'deliver':
            # Document section pages carry code-generated coverage; HTML assets have no such projection.
            return DESCRIPTIONS[name].replace('Do not send state or note. ',
                'Do not send state or note. Cite all page handles; code generates pagination coverage. ')
        return DESCRIPTIONS[name]

    def _expand_handles(self, value):
        # Rebuild solely from SDK-observed refs. Merely registered or returned
        # results cannot be referenced, and handles never repair malformed refs.
        known = {}
        for encoded in self.visible:
            ref = json.loads(encoded); handle = result_handle(ref)
            if handle in known and known[handle] != ref:
                raise CatalogError('RESULT_REF_INVALID','ambiguous result handle; no reference was selected')
            known[handle] = ref
        def visit(item, path):
            if isinstance(item, dict):
                if 'handle' in item:
                    if set(item) != {'handle'} or not isinstance(item['handle'],str) or item['handle'] not in known:
                        raise CatalogError('RESULT_REF_INVALID',path+': handle is malformed or not observed in this SDK run')
                    return deepcopy(known[item['handle']])
                return {key:visit(child,path+'.'+key) for key,child in item.items()}
            if isinstance(item,list):
                return [visit(child,f'{path}[{i}]') for i,child in enumerate(item)]
            return item
        return visit(value,'$')

    def _delivery_state(self, request):
        """Copy caller judgments once; do not infer whether the evidence is sufficient."""
        proposal = DeliveryRequest.model_validate_json(canonical(request))
        satisfied, gaps = [], []
        for need in proposal.needs:
            value = dict(need_id=need.need_id,result_refs=[r.model_dump(mode='json') for r in need.result_refs])
            if need.status == 'supported':
                satisfied.append(value)
            else:
                if not need.gaps:
                    raise CatalogError('INVALID_REQUEST','request.needs: partial/unresolved need requires explicit gaps')
                gaps.append(value | dict(missing=need.gaps[0]))
        return dict(satisfied=satisfied,gaps=gaps,next_action='deliver',
                    reason='Submit the caller-declared delivery needs and gaps')

    def _progress_state(self, name, value):
        """Merge declared deltas without inventing satisfaction or fixing legacy calls."""
        progress = TaskProgress.model_validate_json(canonical(value))
        snapshot = self.service.inspect_context(self.context_ref)
        plan = snapshot['plan']
        needs = deepcopy(plan['needs'])
        ids = {n['need_id'] for n in needs}
        added = [n.model_dump(mode='json') for n in progress.add_needs]
        new_ids = [n['need_id'] for n in added]
        if len(new_ids) != len(set(new_ids)) or ids.intersection(new_ids):
            raise CatalogError('INVALID_REQUEST','add_needs must contain unique NEW need IDs; existing needs cannot be repeated or rewritten')
        needs += added
        if not needs:
            raise CatalogError('INVALID_REQUEST','first business call requires nonempty state.add_needs')
        prior = snapshot.get('state') or {}
        states = {n['need_id']:('satisfied',deepcopy(n)) for n in prior.get('satisfied',[])}
        states.update({n['need_id']:('gaps',deepcopy(n)) for n in prior.get('gaps',[])})
        for n in added:
            states[n['need_id']] = ('gaps',dict(need_id=n['need_id'],missing='Not yet assessed',result_refs=[]))
        updates = [('satisfied',n.model_dump(mode='json')) for n in progress.satisfied]
        updates += [('gaps',n.model_dump(mode='json')) for n in progress.gaps]
        changed = [n['need_id'] for _,n in updates]
        if len(changed)!=len(set(changed)) or set(changed)-{n['need_id'] for n in needs}:
            raise CatalogError('INVALID_REQUEST','progress updates must name existing needs once; no duplicate or unknown need IDs')
        states.update({n['need_id']:(kind,n) for kind,n in updates})
        result = dict(next_action=name,reason=progress.reason,
            satisfied=[states[n['need_id']][1] for n in needs if states[n['need_id']][0]=='satisfied'],
            gaps=[states[n['need_id']][1] for n in needs if states[n['need_id']][0]=='gaps'])
        if added:
            result['plan_update'] = dict(base_version=plan['version'],needs=needs)
        return result

    # 仅经业务层提交的交付或澄清结果，才构成可结束运行的控制结果。
    @property
    def terminal(self):
        return self.delivery or self.clarification

    # 结果必须原样越过可观察的 SDK 边界才算可引用；处理器返回不等于模型已收到。
    def observe(self, output, *, boundary):
        """Only acknowledge an unmodified emitted result at an observed SDK boundary.

        This proves message inclusion, not comprehension. Truncated or replaced
        output cannot promote handler-only evidence to a deliverable result.
        """
        if not isinstance(output, str):
            return
        try:
            value = json.loads(output)
        except (ValueError, TypeError):
            return
        if value not in self.returned:
            return
        self.visible.update(references(value))
        event = dict(type='observed_tool_result', boundary=boundary, output=deepcopy(value))
        self.events.append(event)
        if self.journal is not None:
            self.journal.observe(references(value), event)

    # 同一绑定串行执行工具；先识别可重放调用，再校验参数、引用和业务状态。
    async def invoke(self, name, arguments, *, call_id=None):
        async with self.lock:
            key = None
            try:
                if self.journal is not None:
                    raw = json.loads(arguments) if isinstance(arguments,str) else arguments
                    key, replay = self.journal.tool_key(call_id, name, raw)
                    if replay is not None:
                        self.returned.append(deepcopy(replay))
                        return canonical(replay).decode()
                    self.journal.guard_action()
                if self.terminal is not None:
                    raise CatalogError('INVALID_STATE', 'terminal control result already committed')
                raw = json.loads(arguments) if isinstance(arguments,str) else deepcopy(arguments)
                if not isinstance(raw,dict):
                    raise ValueError('tool arguments must be an object')
                raw = self._expand_handles(raw)
                if name == 'deliver' and 'state' not in raw:
                    raw['state'] = self._delivery_state(raw['request'])
                elif name != 'clarify' and name != 'deliver' and isinstance(raw.get('state'),dict):
                    # Old persisted/full-state clients keep their strict contract.
                    if not {'plan_update','next_action'}.intersection(raw['state']):
                        raw['state'] = self._progress_state(name,raw['state'])
                envelope = self.envelopes[name].model_validate_json(canonical(raw))
                values = envelope.model_dump(mode='json')
                # 禁止引用未进入本次模型上下文的结果，避免凭空引用或借用其他运行的证据。
                if not references(values) <= self.visible:
                    raise CatalogError('RESULT_REF_INVALID', 'reference was not observed in this SDK run')
                key = key or 'sdk:'+uuid.uuid4().hex
                # 终态也走 DataService 校验和持久化；普通工具则继续通过统一 call 入口执行。
                if name in {'deliver','clarify'}:
                    response = getattr(self.service,name)(self.context_ref, **values, request_key=key,
                        checkpoint=self.journal.checkpoint if self.journal is not None else None)
                    if name=='deliver':self.delivery = deepcopy(response)
                    else:self.clarification = deepcopy(response)
                    if self.journal is not None:
                        self.journal.stop('validated_'+name)
                else:
                    response = self.service.call(self.context_ref, name, **values, request_key=key,
                        should_cancel=self.journal.stopped.is_set if self.journal is not None else None,
                        checkpoint=self.journal.checkpoint if self.journal is not None else None)
            except (ValidationError, ValueError, KeyError) as error:
                if isinstance(error, CatalogError) and error.code in {'RECOVERY_REQUIRED', 'CATALOG_INCONSISTENT'}:
                    raise
                response = dict(status='error', error=dict(code=error.code if isinstance(error, CatalogError) else 'INVALID_REQUEST', message=str(error)), items=[])
            # 错误返回附带真实已提交计划，防止模型把被拒绝的状态更新当作已生效。
            if response.get('status') == 'error':
                # Report committed state only. Do not fill/correct model arguments
                # or claim that a preflight failure saved its proposed plan.
                snapshot = self.service.inspect_context(self.context_ref)
                response = deepcopy(response)
                response['error']['current_task_state'] = dict(plan=snapshot['plan'],state=snapshot['state'],
                    operation_accepted=response.get('operation_id') in snapshot['operations'])
            self.returned.append(deepcopy(response))
            self.events.append(dict(type='tool_handler_return', tool=name, output=deepcopy(response)))
            if self.journal is not None and key is not None:
                self.journal.record_tool(call_id, response)
            return canonical(response).decode()

    # 原生 SDK 成功且存在已验证终态才算成功；失败时仍保留已提交结果供恢复核对。
    def outcome(self, *, native_success, events, profile, error=None, error_code=None):
        success = native_success and self.terminal is not None
        return dict(kind=self.terminal['kind'] if success else 'recovery_required' if error_code in {'RECOVERY_REQUIRED','CATALOG_INCONSISTENT'} else 'failed',
            status=('needs_clarification' if self.clarification else self.delivery['delivery'].get('business_status','completed')) if success else 'failed',
            native_success=native_success,
            error=None if success else error or 'NO_VALIDATED_DELIVERY',
            delivery=deepcopy(self.delivery) if success else None,
            committed_delivery=deepcopy(self.delivery) if not success else None,
            clarification=deepcopy(self.clarification) if success else None,
            committed_clarification=deepcopy(self.clarification) if not success else None,
            profile=profile.metadata(), native_events=events, tool_events=deepcopy(self.events),
            mode='offline', real_model_calls=0, gateway_cost_usd=None)
