"""Observed acquisition/host-resolution worker; synthetic bytes, no sockets/SDK."""
import json
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

root, invocation_path = Path(sys.argv[1]), Path(sys.argv[2])
mode, phase = sys.argv[3:5]
invocation = json.loads(invocation_path.read_bytes())
plan = invocation.pop('plan')
fixture = runpy.run_path(str(Path(__file__).with_name('html_fixture.py')))
counts = {}


def checkpoint(at):
    counts[at] = counts.get(at,0)+1
    alias = {'snapshot_before_move':('before_publication_move',1),
             'build_before_move':('before_publication_move',2),
             'build_artifact_write_2':('build_artifact_write',2)}
    if at==phase or alias.get(phase)==(at,counts[at]):os._exit(73)
    if phase=='acquisition_main_receipt' and at=='acquisition_receipt_recorded':
        session = Session(catalog,invocation['context_ref'])
        op = next(iter(session.data['operations'].values()))
        if op.get('resource_usage',{}).get('transport_requests')==1:os._exit(73)


def fetch(url, **kwargs):
    if mode!='acquire':raise AssertionError('resolution must not fetch')
    path = root/'fixture-transport.json'
    requests = json.loads(path.read_bytes()) if path.exists() else []
    requests.append(url)
    with path.open('w') as stream:
        json.dump(requests,stream);stream.flush();os.fsync(stream.fileno())
    if phase=='transport_inflight':os._exit(73)
    return fixture['source']() if url==fixture['MAIN_URL'] else b'synthetic image'


with patch('uteki.data_platform.connectors.official.resolve_sec_contact',return_value=('Synthetic test@example.com','synthetic_fixture')):
    with Catalog.open(root) as catalog:
        service = DataService(catalog,acquisition_adapter=OfficialAcquisitionAdapter([plan],settings_root=root,fetch=fetch))
        try:
            if mode=='acquire':
                journal = RuntimeJournal(service,invocation['context_ref'],dict(kernel='acquisition_fixture'),
                    dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000))
                key,_ = journal.tool_key('acquire-one','request_asset_update',dict(request=invocation['request'],state=invocation['state']))
                invocation['request_key'] = key
                result = service.call(**invocation,checkpoint=checkpoint)
            else:
                operation = next(iter(Session(catalog,invocation['context_ref']).data['operations'].values()))
                result = service.resolve_update(invocation['context_ref'],request_key=operation['request_key'],action=mode,checkpoint=checkpoint)
            value = dict(result=result)
        except CatalogError as error:
            value = dict(error=dict(code=error.code,message=str(error)))
        (root/'resolution-result.json').write_text(json.dumps(value))
        print(json.dumps(value))
