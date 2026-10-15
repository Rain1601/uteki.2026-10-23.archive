"""Abrupt completion/closure worker. Only synthetic data and the shared runtime."""
import json
import os
from pathlib import Path
import sys

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

root=Path(sys.argv[1]);mode,phase=sys.argv[2:4]
value=json.loads((root/'completion-fixture.json').read_text())


def checkpoint(point):
    if point==phase:os._exit(74)


with Catalog.open(root) as catalog:
    service=DataService(catalog)
    try:
        if mode=='close':
            result=service.close_run(value['context'],request_key='host-close',reason='original native history unavailable',checkpoint=checkpoint)
        else:
            journal=RuntimeJournal(service,value['context'],value['profile'],value['limits'],recover=mode=='recover')
            if journal.cached is not None:result=journal.cached
            else:
                journal.checkpoint=checkpoint
                if phase.startswith('model_'):
                    key=journal.prepare_model(dict(input='synthetic'))
                    journal.record_model(key,dict(output='synthetic'),complete=True)
                if phase=='native_tool_prepared':
                    journal.tool_key('original-tool','find_assets',dict(request=dict(filters={}),state=value['state']))
                if phase=='tool_response_prepared':
                    args=dict(request=dict(filters={}),state=value['state'])
                    key,_=journal.tool_key('original-tool','find_assets',args)
                    service.find_assets(value['context'],**args,request_key=key,checkpoint=checkpoint)
                if phase=='readonly_accepted':
                    args=dict(request=dict(filters={}),state=value['state'])
                    key,_=journal.tool_key('original-tool','find_assets',args)
                    from uteki.data_platform.application.session import Session
                    from unittest.mock import patch
                    original=Session.accept
                    def accepted(session,**kwargs):
                        original(session,**kwargs)
                        checkpoint('readonly_accepted')
                    with patch.object(Session,'accept',accepted):
                        service.find_assets(value['context'],**args,request_key=key)
                result=journal.finish(dict(kind='failed',status='failed',error='original synthetic failure',native_success=False,
                    delivery=None,clarification=None,committed_delivery=None,committed_clarification=None,
                    profile=value['profile'],native_events=[],tool_events=[],mode='offline',real_model_calls=0,gateway_cost_usd=None))
        report=dict(result=result)
    except CatalogError as error:
        report=dict(error=dict(code=error.code,message=str(error)))
        if hasattr(error,'diagnostic'):report['error']['diagnostic']=error.diagnostic
    (root/'completion-result.json').write_text(json.dumps(report))
