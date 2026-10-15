"""Real SDK-free runtime journal owner exits before recording its outcome."""
import os
import sys
import time

from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

with Catalog.open(sys.argv[1]) as catalog:
    journal=RuntimeJournal(DataService(catalog),sys.argv[2],dict(kernel='clock_fixture'),
        dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000))
    time.sleep(float(sys.argv[3]) if len(sys.argv)>3 else .03)
    journal.tick()
    os._exit(79)
