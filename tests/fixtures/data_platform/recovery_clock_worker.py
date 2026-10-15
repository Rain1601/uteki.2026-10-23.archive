"""Interrupt a real recovery host before it confirms the original worker."""
import os
import sys
import time

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

def checkpoint(phase):
    if sys.argv[3]=='terminal' and phase==sys.argv[4]:
        time.sleep(.2)
        os._exit(79)
    if phase=='host_recovery_started':
        if sys.argv[3]=='timeout':time.sleep(20)
        os._exit(79)

with Catalog.open(sys.argv[1]) as catalog:
    journal=RuntimeJournal(DataService(catalog),sys.argv[2],dict(kernel='clock_fixture'),
        dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000),
        recover=sys.argv[3]!='terminal',checkpoint=checkpoint)
    if sys.argv[3]=='terminal':
        journal.finish(dict(kind='failed',status='failed',error='original failure',native_success=False,
            delivery=None,clarification=None,committed_delivery=None,committed_clarification=None,
            profile=dict(kernel='clock_fixture'),native_events=[],tool_events=[],mode='offline',
            real_model_calls=0,gateway_cost_usd=None))
raise AssertionError('recovery checkpoint was not reached')
