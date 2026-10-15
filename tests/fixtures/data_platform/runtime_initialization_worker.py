"""Exit a real initialization owner; no SDK or remote transport is started."""
import os
import sys
from unittest.mock import patch

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

LIMITS=dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)
target=sys.argv[3]
save=Session.save
def saved(session):
    result=save(session)
    native=session.data.get('native_execution',{})
    # These two durable boundaries also exist in the pre-fix installed package.
    if target=='native_initialization_saved' and native.get('phase')=='initializing':os._exit(79)
    if target=='root_initialization_saved' and session.data.get('root_budget'):os._exit(79)
    return result

def checkpoint(phase):
    if target=='failure:'+phase:raise OSError('synthetic initialization write failure')
    if phase==target:os._exit(79)

with Catalog.open(sys.argv[1]) as catalog,patch.object(Session,'save',saved):
    RuntimeJournal(DataService(catalog),sys.argv[2],dict(kernel='clock_fixture'),LIMITS,
        recover=len(sys.argv)>4 and sys.argv[4]=='recover',checkpoint=checkpoint)
raise AssertionError('requested initialization boundary was not reached')
