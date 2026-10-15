"""Real CLI compaction is an ordinary metered request, never a free side call."""
import base64
import json
from pathlib import Path
import runpy
import unittest

N=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))


class NativeAuxiliaryTests(unittest.TestCase):
    def run_compaction(self, **options):
        report=N['run_scenario']('success',options=dict(first_input_tokens=195000,
            compact_response=True,limits=N['F']['runtime_limits'](max_model_requests=2),**options))
        self.assertEqual(report['exit_code'],0,report['stderr'][-2000:])
        self.assertEqual(len(report['requests']),2)
        self.assertFalse(N['compaction_request'](report['requests'][0]))
        self.assertTrue(N['compaction_request'](report['requests'][1]))
        self.assertEqual(report['ledger']['request_stages'],{'responded':2})
        self.assertEqual(report['process_cleanup']['before'],[])
        response_ids=[]
        for saved,request in zip(report['ledger_requests'],report['requests']):
            self.assertEqual(json.loads(base64.b64decode(saved['request']['request']['body_base64'])),request)
            self.assertTrue(saved['response_event']['response']['complete'])
            response=base64.b64decode(saved['response_event']['response']['body_base64'])
            starts=[json.loads(line[5:]) for line in response.splitlines()
                if line.startswith(b'data:') and json.loads(line[5:]).get('type')=='message_start']
            self.assertEqual(len(starts),1)
            response_ids.append(starts[0]['message']['id'])
        self.assertEqual(len(set(response_ids)),2,'fixture summary is a distinct model response')
        return report

    def test_successful_native_compaction_shares_root_limit_and_blocks_next_request(self):
        report=self.run_compaction()
        events=[e['data'] for e in report['result']['native_events'] if e['type']=='SystemMessage']
        self.assertTrue(any(e['subtype']=='compact_boundary' for e in events),[e['subtype'] for e in events])
        self.assertEqual(report['result']['status'],'partial',report['result']['error'])
        self.assertEqual(report['ledger']['stop_reason'],'model_budget')
        self.assertEqual({o['tool'] for o in report['operations'].values()},{'find_assets','deliver'})

    def test_cancel_at_compaction_response_retains_it_and_stops_native_followup(self):
        report=self.run_compaction(cancel_phase='model_response_received@2',repeat_cancel=True)
        self.assertEqual(report['result']['status'],'cancelled',report['result']['error'])
        self.assertEqual(report['ledger']['stop_reason'],'cancelled')
        self.assertEqual({o['tool'] for o in report['operations'].values()},{'find_assets','deliver'})


if __name__=='__main__':unittest.main()
