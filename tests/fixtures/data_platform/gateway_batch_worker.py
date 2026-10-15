"""Controlled process exits for persistent batch and business-root binding."""
import json
import os
from pathlib import Path
import sys

from uteki.data_platform.application.gateway_batch import create_gateway_batch
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

root,spec_path,mode,phase=sys.argv[1:]
spec=json.loads(Path(spec_path).read_text())


def checkpoint(current):
    if current==phase:os._exit(87)


with Catalog.open(Path(root)) as catalog:
    bindings=create_gateway_batch(catalog,**spec,recover=True,checkpoint=checkpoint if mode=='batch' else None)
    if mode!='batch':
        scope=spec['scopes'][0]
        journal=RuntimeJournal(DataService(catalog),scope['context_ref'],scope['profile'],scope['limits'],
            gateway_binding=bindings[scope['scope_id']],checkpoint=checkpoint)
        if mode=='request':
            journal.budget.prepare_request('interrupted-physical-request',dict(context_ref=journal.context_ref),
                reserve_usd='.8',scope_id=scope['scope_id'])
            journal.budget.begin_request('interrupted-physical-request')
            checkpoint('physical_request_dispatched')
