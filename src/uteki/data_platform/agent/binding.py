"""A shared business binding, not a model loop or SDK session implementation."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import uuid

from pydantic import ValidationError, create_model

from ..contracts.common import CatalogError, Contract, canonical
from ..contracts.query import TOOLS
from ..contracts.run import DeliveryRequest, ResultRef, TaskState


DESCRIPTIONS = {
    'find_assets': 'Find published materials within the caller identity, source and time boundaries.',
    'get_asset_schema': 'Inspect one exact material version and its actual available capabilities.',
    'search_asset': 'Locate text, outlines or source concepts within one exact material version.',
    'read_evidence': 'Read source evidence and necessary context at exact frozen locations.',
    'query_records': 'Read source records or calculate using explicit compatible operands and units.',
    'request_asset_update': 'Request explicitly permitted acquisition or processing; errors are not completion.',
    'deliver': 'Finish only with previously displayed result references and explicit gaps for every need.',
}
ENVELOPES = {name: create_model(name.title().replace('_','')+'Call', __base__=Contract,
    request=(request, ...), state=(TaskState, ...))
    for name, request in (dict(TOOLS) | {'deliver': DeliveryRequest}).items()}


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


class ToolBinding:
    def __init__(self, service, context_ref):
        self.service, self.context_ref = service, context_ref
        self.context = service.inspect_context(context_ref)['context']
        self.lock = asyncio.Lock()
        self.events = []
        self.returned = []
        self.visible = set()
        self.delivery = None
        self.terminal_requested = False

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
        self.events.append(dict(type='observed_tool_result', boundary=boundary, output=deepcopy(value)))

    async def invoke(self, name, arguments):
        async with self.lock:
            try:
                if self.delivery is not None:
                    raise CatalogError('INVALID_STATE', 'delivery already committed')
                envelope = ENVELOPES[name].model_validate_json(arguments if isinstance(arguments, str) else canonical(arguments))
                values = envelope.model_dump(mode='json')
                if not references(values) <= self.visible:
                    raise CatalogError('RESULT_REF_INVALID', 'reference was not observed in this SDK run')
                key = 'sdk:'+uuid.uuid4().hex
                if name == 'deliver':
                    response = self.service.deliver(self.context_ref, **values, request_key=key)
                    self.delivery = deepcopy(response)
                else:
                    response = self.service.call(self.context_ref, name, **values, request_key=key)
            except (ValidationError, ValueError, KeyError) as error:
                if isinstance(error, CatalogError) and error.code in {'RECOVERY_REQUIRED', 'CATALOG_INCONSISTENT'}:
                    raise
                response = dict(status='error', error=dict(code=error.code if isinstance(error, CatalogError) else 'INVALID_REQUEST', message=str(error)), items=[])
            self.returned.append(deepcopy(response))
            self.events.append(dict(type='tool_handler_return', tool=name, output=deepcopy(response)))
            return canonical(response).decode()

    def outcome(self, *, native_success, events, profile, error=None):
        success = native_success and self.delivery is not None
        return dict(status='completed' if success else 'failed',
            error=None if success else error or 'NO_VALIDATED_DELIVERY',
            delivery=deepcopy(self.delivery) if success else None,
            committed_delivery=deepcopy(self.delivery) if not success else None,
            profile=profile.metadata(), native_events=events, tool_events=deepcopy(self.events),
            mode='offline', real_model_calls=0, gateway_cost_usd=None)
