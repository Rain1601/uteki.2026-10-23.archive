"""Reconcile accepted tool results/effects without dispatching another tool."""
from copy import deepcopy

from ..contracts.common import CatalogError, utc_now
from ..retrieval.content import HtmlReader
from ..retrieval.index import DerivedIndex


def recover_operation(service, session, request_key, fingerprint, request, *, checkpoint=None):
    checkpoint = checkpoint or (lambda phase: None)
    operation = next((o for o in session.data['operations'].values() if o['request_key']==request_key),None)
    if operation is None:
        raise CatalogError('RECOVERY_REQUIRED','no original accepted operation; recovery cannot execute a new request')
    if operation['fingerprint'] != fingerprint:
        raise CatalogError('IDEMPOTENCY_CONFLICT','recovery request differs from original operation')
    if operation['status']=='closed':
        raise CatalogError('INVALID_STATE','operation was explicitly abandoned; it has no original response to recover')
    if operation['status']=='completed':
        return deepcopy(operation['response'])
    intent = operation.get('response_intent')
    if intent is None:
        effect = operation.get('effect_intent')
        if operation['tool']!='request_asset_update' or not isinstance(effect,dict):
            raise CatalogError('RECOVERY_REQUIRED','no durable response or supported effect intent; no tool was repeated')
        if request.action=='process' and effect.get('kind')=='index_head':
            index = DerivedIndex(service.catalog,HtmlReader(service.catalog,request.process.asset_ref))
            index.confirm_head(effect['target'])
            response = deepcopy(effect['response'])
            kind = 'verified_existing_index'
        elif request.action=='acquire' and effect.get('kind')=='official_acquisition':
            from ..connectors.recovery import confirm_acquisition
            from .tools import ToolExecution
            result = confirm_acquisition(service.catalog,session.data['context'],operation,request,checkpoint=checkpoint)
            executor = ToolExecution(service.catalog,session,operation['tool'],request)
            executor.operation = operation['operation_id']
            response = executor.response([result],issues=[dict(code='ACQUISITION_PARTIAL',message=g) for g in result['gaps']])
            kind = 'verified_existing_acquisition'
        else:
            raise CatalogError('RECOVERY_REQUIRED','no supported effect intent; no tool was repeated')
        checkpoint('tool_effect_reconciled')
        lower = operation['elapsed_lower_bound']
        response['resource_usage'] = dict(elapsed_ms=None,elapsed_lower_bound_ms=round(lower*1000,3),
            execution_time_uncertain=True,**operation.get('resource_usage',dict(external_calls=0,model_calls=0,cost_usd='0')))
        response['recovery'] = dict(kind=kind,execution_time_uncertain=True)
        session.data['execution_time_uncertain'] = dict(operation_id=operation['operation_id'],
            reason='process exited without a complete measured tool response',elapsed_lower_bound=lower)
        operation.setdefault('recovery_events',[]).append(dict(kind=kind,at=utc_now(),target=effect['target']))
        service._register_response(session,operation['operation_id'],operation['tool'],request,response)
        session.prepare_response(operation['operation_id'],response,lower)
        checkpoint('tool_response_prepared')
        intent = operation['response_intent']
    result = session.complete(operation['operation_id'],intent['response'],intent['elapsed_seconds'])
    checkpoint('response_committed')
    return result
