"""Offline preparation provenance and meaningful grading checks, no provider calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/'experiments/model_comparison/2026-10-07-reproducibility-pilot-v1'
spec = importlib.util.spec_from_file_location('pilot_evaluator', FOLDER/'evaluate.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class ReproducibilityPilotTests(unittest.TestCase):
    def answer(self, task='cashflow-facts'):
        folder = FOLDER/'tasks'/task
        reference = json.loads((folder/'reference-review.json').read_text())
        claim = ('表格提供精确金额，管理层说明采用四舍五入的十亿美元。' if task=='cashflow-facts' else
                 '经营现金流同比变化：-1898 USD millions；变化率：-53.24%；公式：(1667-3565)/3565*100。')
        return {'facts': deepcopy(reference['expected_records']),
                'analysis': [{'claim': claim, 'block_ids': ['block-000686-a6e8806b']}],
                'gaps': ['节选无法判断未来现金流持续性。','节选无法解释所有项目变化的完整商业原因。']}

    def check_answer(self, answer, task='cashflow-facts', finish='stop'):
        return evaluator.evaluate(FOLDER/'tasks'/task, json.dumps(answer,ensure_ascii=False), finish_reason=finish)

    def test_source_pins_and_counterbalanced_eight_unique_calls(self):
        report = evaluator.preparation.verify_benchmark(FOLDER)
        self.assertEqual(report['calls_planned'], 8)
        plan = json.loads((FOLDER/'plan.json').read_text())
        self.assertEqual(len({case['id'] for case in plan['call_order']}),8)
        self.assertEqual([case['profile_id'].split('-')[0] for case in plan['call_order']],
                         ['sonnet55','deepseek','deepseek','sonnet55','deepseek','sonnet55','sonnet55','deepseek'])
        for task in plan['tasks']:
            for profile in plan['profiles']:
                cases=[case for case in plan['call_order'] if case['task_id']==task['id'] and case['profile_id']==profile['id']]
                self.assertEqual([case['repeat'] for case in cases],[1,2])
        self.assertEqual(plan['limits']['aggregate_estimated_budget_usd'],'1.50')
        self.assertEqual(plan['limits']['automatic_retries'],0)

    def test_expected_answers_pass_program_checks_but_never_complete_blind_review(self):
        for task in ('cashflow-facts','cashflow-change'):
            result=self.check_answer(self.answer(task),task)
            self.assertTrue(result['automated_pass'],result)
            self.assertEqual(result['blind_qualitative_review'],'not_performed')
            self.assertEqual(result['overall_task_pass'],'pending_blind_review')

    def test_wrong_amount_duplicate_missing_and_truncation_fail(self):
        answer=self.answer()
        answer['facts'][0]['value'] += 1
        self.assertFalse(self.check_answer(answer)['automated_pass'])
        answer=self.answer()
        answer['facts'][-1]=deepcopy(answer['facts'][0])
        result=self.check_answer(answer)
        self.assertTrue(result['facts']['duplicates'])
        self.assertTrue(result['facts']['missing'])
        self.assertFalse(result['automated_pass'])
        self.assertFalse(self.check_answer(self.answer(),finish='length')['automated_pass'])

    def test_order_and_numeric_representation_normalize_without_hiding_value_changes(self):
        first=self.answer()
        second=deepcopy(first)
        second['facts'].reverse()
        second['gaps'].reverse()
        second['facts'][0]['value']=str(second['facts'][0]['value'])+'.0'
        a=self.check_answer(first); b=self.check_answer(second)
        self.assertTrue(b['automated_pass'])
        self.assertNotEqual(a['fingerprints']['raw_sha256'],b['fingerprints']['raw_sha256'])
        self.assertEqual(a['fingerprints']['order_normalized_sha256'],b['fingerprints']['order_normalized_sha256'])
        self.assertEqual(a['fingerprints']['fact_values_sha256'],b['fingerprints']['fact_values_sha256'])
        second['facts'][0]['value']='0'
        c=self.check_answer(second)
        self.assertNotEqual(a['fingerprints']['fact_values_sha256'],c['fingerprints']['fact_values_sha256'])
        self.assertFalse(c['automated_pass'])

    def test_quote_and_explicit_change_calculations_are_checked(self):
        answer=self.answer('cashflow-change')
        answer['analysis'][0]['claim']=answer['analysis'][0]['claim'].replace('-53.24%','+53.24%')
        result=self.check_answer(answer,'cashflow-change')
        self.assertFalse(result['change_numbers']['percent_matches'])
        self.assertFalse(result['automated_pass'])
        answer=self.answer()
        answer['facts'][0]['quote']='A fabricated quote.'
        result=self.check_answer(answer)
        self.assertIn('quote_not_in_block',result['contract']['errors'])
        self.assertFalse(result['automated_pass'])

    def test_only_packet_and_shared_system_enter_model_input(self):
        helper=evaluator.preparation.frozen_helpers()
        systems=[]
        for task in ('cashflow-facts','cashflow-change'):
            packet,messages,_=helper.load_prepared(FOLDER/'tasks'/task/'prepared')
            systems.append(messages[0]['content'])
            self.assertEqual(json.loads(messages[1]['content']),packet)
            self.assertEqual(len(messages),2)
            serialized=json.dumps(messages)
            for forbidden in ('expected_records','qualitative_checks','preregistered-rubric','blind_review','reference-review.json'):
                self.assertNotIn(forbidden,serialized)
        self.assertEqual(systems[0],systems[1])

    def test_repeat_aggregate_keeps_pending_distinct_and_checks_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            for filename in ('plan.json','source-verification.json'):
                shutil.copyfile(FOLDER/filename,folder/filename)
            for name in ('tasks','profiles'):
                shutil.copytree(FOLDER/name,folder/name)
            plan=json.loads((folder/'plan.json').read_text())
            cases=[case for case in plan['call_order'] if case['task_id']=='cashflow-facts' and case['profile_id'].startswith('sonnet55')]
            profile=next(profile for profile in plan['profiles'] if profile['id']==cases[0]['profile_id'])
            task=next(task for task in plan['tasks'] if task['id']=='cashflow-facts')
            for case in cases:
                output=folder/case['output_path']
                (output/'01-model').mkdir(parents=True)
                answer=self.answer()
                if case['repeat']==2:
                    answer['facts'].reverse()
                (output/'01-model/visible-output.txt').write_text(json.dumps(answer,ensure_ascii=False))
                call={'profile_sha256':profile['sha256'],'provider':profile['provider'],'requested_model':profile['model'],
                      'input':task,'status':'received','finish_reason':'stop','elapsed_seconds':1.5,'estimated_usd':'0.01'}
                (output/'summary.json').write_text(json.dumps({'status':'completed','arms':[call]}))
            aggregate=evaluator.evaluate_benchmark(folder)
            group=next(group for group in aggregate['repeat_comparisons'] if group['task_id']==task['id'] and group['profile_id']==profile['id'])
            self.assertEqual(group['recorded_trials'],2)
            self.assertEqual(group['automated_pass_count'],2)
            self.assertTrue(group['fact_value_agreement'])
            self.assertTrue(group['order_normalized_agreement'])
            self.assertFalse(group['exact_output_agreement'])
            self.assertEqual(sum(trial['status']=='not_recorded' for trial in aggregate['trials']),6)
            for pending in aggregate['repeat_comparisons'][1:]:
                self.assertIsNone(pending['fact_value_agreement'])
            path=folder/cases[1]['output_path']/'summary.json'
            bad=json.loads(path.read_text());bad['arms'][0]['profile_sha256']='bad';path.write_text(json.dumps(bad))
            aggregate=evaluator.evaluate_benchmark(folder)
            group=next(group for group in aggregate['repeat_comparisons'] if group['task_id']==task['id'] and group['profile_id']==profile['id'])
            self.assertFalse(group['both_repeats_available_and_contract_valid'])
            self.assertIsNone(group['fact_value_agreement'])
            self.assertEqual(group['automated_pass_count'],1)


if __name__=='__main__':
    unittest.main()
