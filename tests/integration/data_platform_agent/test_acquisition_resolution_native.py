"""Original SDK tool interruption followed by host-only local resolution."""
import json
import os
from pathlib import Path
import runpy
import sys
import unittest

from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.application.run_budget import RunBudget

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))


class NativeAcquisitionResolutionTests(unittest.TestCase):
    def evidence(self, name, report):
        folder=os.environ.get('UTEKI_ACQUISITION_RESOLUTION_EVIDENCE_DIR')
        if folder:
            target=Path(folder);target.mkdir(parents=True,exist_ok=True)
            (target/(name+'.json')).write_text(json.dumps(report,indent=2)+'\n')

    def test_openai_acquisition_resolution_keeps_one_model_request_and_same_operation(self):
        for action,phase in [('continue_local','acquisition_received'),('close','before_snapshot_freeze')]:
            with self.subTest(action=action):
                case=F['acquisition_case']();case.catalog.close()
                try:
                    with (case.root/'sdk-exit.log').open('w') as log:
                        worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                            str(case.root),case.context,str(ROOT/'config/data_platform'),phase,'acquisition'],
                            cwd=case.root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
                        observed=worker.wait(timeout=40)
                    self.assertEqual(observed['returncode'],79,(case.root/'sdk-exit.log').read_text())
                    with Catalog.open(case.root) as catalog:
                        worker.record(catalog,case.context)
                        before=Session(catalog,case.context).data
                    resolved=F['resolve_acquisition_worker'](case.root,case.context,action)
                    self.assertIn('result',resolved['result'],resolved)
                    result=resolved['result']['result']
                    self.assertEqual(result['status'],'ok' if action=='continue_local' else 'error')
                    with Catalog.open(case.root) as catalog:
                        after=Session(catalog,case.context).data
                        native=after['native_execution']
                        ledger=RunBudget.open_existing(case.root/native['ledger_path'],'0',root_run_id=after['context']['root_run_id'])
                        self.assertEqual(ledger.inspect_root()['request_stages'],{'responded':1})
                        self.assertEqual(after['turns'],before['turns'])
                        self.assertEqual(set(after['operations']),set(before['operations']))
                        self.assertEqual(native['native_session_id'],before['native_execution']['native_session_id'])
                    self.assertEqual(len(json.loads((case.root/'fixture-native-acquisition-requests.json').read_text())),2)
                    self.assertFalse((case.root/'fixture-transport.json').exists())
                    self.evidence('openai-'+action,dict(resolved=resolved,original_exit=observed,
                        model_requests=1,transport_requests=2,real_model_calls=0,operations=after['operations']))
                finally:case.doCleanups()

    def test_claude_acquisition_resolution_does_not_invent_native_tool_history(self):
        native=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))
        for action,phase in [('continue_local','acquisition_received'),('close','before_snapshot_freeze')]:
            with self.subTest(action=action):
                report=native['run_scenario']('acquisition',options=dict(stop_phase=phase,observe_exit=True,host_resolution=action))
                self.evidence('claude-'+action,report)
                self.assertEqual(report['exit_code'],79,report['stderr'])
                self.assertIn('result',report['host_resolution']['result'],report['host_resolution'])
                result=report['host_resolution']['result']['result']
                self.assertEqual(result['status'],'ok' if action=='continue_local' else 'error')
                self.assertEqual(len(report['requests']),1)
                self.assertEqual(len(report['acquisition_requests']),2)
                self.assertEqual(report['ledger']['request_stages'],{'responded':1})
                self.assertEqual(report['journal']['native_session_id'],report['before_recovery']['native_execution']['native_session_id'])
                self.assertTrue(all(c['output'] is None for c in report['journal']['tool_calls'].values()))
                self.assertTrue(all(o['status']=='completed' for o in report['operations'].values()))
                self.assertEqual(report['process_cleanup']['after'],[])
                self.assertEqual(report['host_resolution']['process_cleanup']['after'],[])


if __name__=='__main__':unittest.main()
