"""Real process exits during synthetic acquisition; never opens a network socket."""
import json
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
from uteki.data_platform.service import DataService

root,invocation_path,phase=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
invocation=json.loads(invocation_path.read_bytes())
plan=invocation.pop('plan')
fixture=runpy.run_path(str(Path(__file__).with_name('html_fixture.py')))
requests=[]

def fetch(url,**kwargs):
    assert url in {fixture['MAIN_URL'],fixture['IMAGE_URL']}
    requests.append(url)
    with (root/'fixture-transport.json').open('w') as stream:
        json.dump(requests,stream);stream.flush();os.fsync(stream.fileno())
    return fixture['source']() if url==fixture['MAIN_URL'] else b'synthetic image'

def checkpoint(at):
    if at==phase or phase=='acquisition_main_receipt' and at=='acquisition_receipt_recorded' and len(requests)==1:
        os._exit(73)

with patch('uteki.data_platform.connectors.official.resolve_sec_contact',return_value=('Synthetic test@example.com','synthetic_fixture')):
    with Catalog.open(root) as catalog:
        service=DataService(catalog,acquisition_adapter=OfficialAcquisitionAdapter([plan],settings_root=root,fetch=fetch))
        result=service.call(**invocation,checkpoint=checkpoint)
print(json.dumps(result))
