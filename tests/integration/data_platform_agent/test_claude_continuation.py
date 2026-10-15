"""Native resume must consume original results, never cancel stubs or new effects."""
import os
from pathlib import Path
import runpy
import unittest

FIXTURE=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))
run_scenario=FIXTURE['run_scenario']
outputs=FIXTURE['outputs']


class ClaudeContinuationTests(unittest.TestCase):
    def scenario(self, phase, **kwargs):
        directory=os.environ.get('UTEKI_CLAUDE_RESUME_EVIDENCE_DIR')
        if directory:
            directory=Path(directory)/kwargs.get('history_fault',
                'wire-fault' if kwargs.get('wire_fault') else
                'limit-'+str(kwargs['limits']['max_model_requests']) if kwargs.get('limits') else 'normal')
            directory.mkdir(parents=True,exist_ok=True)
        report=run_scenario('success',evidence_directory=directory,
            options=dict(stop_phase=phase,recover_after_exit=True,observe_exit=True,**kwargs))
        self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
        self.assertEqual(report['recovery']['process_cleanup']['after'],[])
        return report

    def test_completed_native_tool_results_resume_without_duplicate_requests_or_effects(self):
        for position in (1,3,5,7):
            with self.subTest(position=position):
                report=self.scenario('claude_post_tool@'+str(position))
                result=report['result']
                self.assertEqual(result['status'],'completed',result['error'])
                self.assertTrue(result['native_success'])
                self.assertEqual(len(report['requests']),8)
                self.assertEqual(report['ledger']['request_stages'],{'responded':8})
                old=report['before_recovery']['native_execution']
                self.assertEqual(result['runtime']['native_session_id'],old['native_session_id'])
                self.assertEqual(len(report['journal']['execution_segments']),1)
                resumed=outputs(report['requests'][position]['messages'])
                for identity,call in old['tool_calls'].items():
                    self.assertEqual(report['journal']['tool_calls'][identity],call)
                    self.assertIn(call['output'],resumed)
                self.assertEqual(len(report['operations']),8)
                self.assertEqual(result['delivery']['delivery']['usage']['model_calls'],8)
                self.assertTrue(any(e['type']=='observed_tool_result' for e in result['tool_events']))

    def test_incomplete_native_history_and_unknown_response_never_send_again(self):
        for phase in ('native_tool_prepared','native_tool_response_committed',
                      'model_response_committed','model_response_received'):
            with self.subTest(phase=phase):
                report=self.scenario(phase)
                self.assertEqual(report['result']['kind'],'recovery_required',report['result'])
                self.assertEqual(len(report['requests']),1)
                self.assertFalse(report['result']['native_success'])
                if phase=='model_response_received':
                    self.assertEqual(report['ledger']['request_stages'],{'outcome_unknown':1})

    def test_missing_or_modified_native_history_cannot_start_a_new_model_request(self):
        for fault in ('missing','tool_output','assistant'):
            with self.subTest(fault=fault):
                report=self.scenario('claude_post_tool',history_fault=fault)
                self.assertEqual(report['result']['kind'],'recovery_required',report['result'])
                self.assertEqual(len(report['requests']),1)
                self.assertEqual(report['result']['runtime']['native_session_id'],
                                 report['before_recovery']['native_execution']['native_session_id'])
                self.assertFalse(report['journal'].get('execution_segments'))

    def test_recovery_keeps_original_root_request_limit(self):
        report=self.scenario('claude_post_tool@3',limits=FIXTURE['F']['runtime_limits'](max_model_requests=3))
        self.assertEqual(report['result']['status'],'partial',report['result']['error'])
        self.assertEqual(report['result']['delivery']['delivery']['stop_reason'],'model_budget')
        self.assertEqual(len(report['requests']),3)
        self.assertEqual(report['result']['delivery']['delivery']['usage']['model_calls'],3)

    def test_added_assistant_text_at_native_request_boundary_is_not_accepted_as_a_separator(self):
        report=self.scenario('claude_post_tool',wire_fault=True)
        self.assertEqual(report['result']['kind'],'recovery_required')
        self.assertEqual(len(report['requests']),1)
        rejected=[e for e in report['journal']['events'] if e['type']=='claude_resume_request_rejected']
        self.assertEqual(len(rejected),1)
        self.assertIn('assistant context differs',rejected[0]['reason'])
        self.assertEqual(len(report['claude_audit_objects']),1)
