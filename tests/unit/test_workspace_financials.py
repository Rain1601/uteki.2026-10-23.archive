"""Scope, precision and provenance acceptance for financial presentation."""
from copy import deepcopy
from decimal import Decimal
import unittest

from apps.review_workbench.data.workspace_financials import build_dataset_table, build_financial_table


def make_run(company='cedar', run_id='run-one', value='12345678901234567890.12345678901234567890'):
    source_id = company + '-source'
    period = {'kind': 'year', 'start': '2031-12-28', 'end': '2032-12-25', 'basis': 'source'}
    record = {'record_id': 'local-record', 'record_type': 'metric', 'entity_id': 'local-entity',
              'metric_id': 'revenue', 'source_snapshot_id': source_id, 'period': period,
              'value_decimal': value, 'upper_decimal': None, 'value_relation': 'eq',
              'unit': 'USD', 'currency': 'USD', 'value_scale': '1',
              'accounting_basis': 'reported_consolidated', 'dimensions': {},
              'value_kind': 'actual', 'status': 'candidate', 'evidence_ids': ['local-evidence'],
              'qualifier_evidence_ids': ['local-qualifier'], 'question_evidence_ids': [],
              'origin': {'draft_id': 'draft-one', 'raw': {'value': value, 'unit': 'USD'}}}
    refs = {identity: {'evidence_id': identity, 'source_snapshot_id': source_id,
                      'source_sha256': 'a' * 64, 'block_id': 'local-block', 'quote': company + ' evidence',
                      'source_start': 0, 'source_end': len(company + ' evidence'),
                      'number_metadata': {'value_decimal': value}}
            for identity in ('local-evidence', 'local-qualifier')}
    return {'id': run_id, 'company_id': company, 'source_snapshot_id': source_id,
            'source_sha256': 'a' * 64, 'manifest_sha256': 'b' * 64,
            'dataset': {'id': company + '-dataset', 'manifest_sha256': 'c' * 64},
            'artifacts': {'packet.json': {'metric_catalog': {'revenue': {
                'metric_id': 'revenue', 'label': 'Reported revenue', 'definition_version': 'synthetic-v1'}}},
                'normalized.json': {'records': [record], 'evidence': refs, 'unresolved': []},
                'extraction.json': {'records': [], 'gaps': []}, 'result.json': {'status': 'completed'}},
            'review': {'run_id': run_id, 'company_id': company, 'source_snapshot_id': source_id,
                       'source_sha256': 'a' * 64, 'facts': [{'record_id': 'local-record',
                           'verdict': 'value_scope_matched', 'rationale': 'Synthetic source checked.'}]}}


def record(run):
    return run['artifacts']['normalized.json']['records'][0]


def candidates(table):
    return [item for row in table['rows'] for cell in row['cells'].values() for item in cell['candidates']]


class WorkspaceFinancialTests(unittest.TestCase):
    def test_empty_selection_and_failed_normalization_have_no_candidate_fallback(self):
        self.assertEqual(build_financial_table([])['rows'], [])
        run = make_run()
        run['artifacts']['extraction.json']['records'] = [{'value': '999', 'metric': 'A raw draft'}]
        del run['artifacts']['normalized.json']
        run['artifacts']['result.json']['status'] = 'failed'
        table = build_financial_table([run])
        self.assertEqual(table['rows'], [])
        self.assertEqual(table['gaps'][0]['reason'], 'normalized_artifact_missing')
        self.assertEqual(table['gaps'][0]['run_status'], 'failed')

    def test_same_local_ids_in_two_companies_preserve_separate_rows_and_evidence(self):
        table = build_financial_table([make_run(), make_run('harbor')])
        self.assertEqual(len(table['rows']), 2)
        self.assertEqual({row['scope']['company_id'] for row in table['rows']}, {'cedar', 'harbor'})
        self.assertEqual(len({c['id'] for c in candidates(table)}), 2)
        for item in candidates(table):
            self.assertEqual(item['evidence_refs'][0]['quote'], item['company_id'] + ' evidence')

    def test_scope_dimensions_currency_unit_scale_basis_and_definition_are_not_merged(self):
        original = make_run()
        changes = [('entity_id', 'segment'), ('currency', 'TWD'), ('unit', 'USD_millions'),
                   ('value_scale', '1000000'), ('accounting_basis', 'non_gaap'),
                   ('dimensions', {'region': 'overseas'}), ('value_kind', 'guidance'),
                   ('denominator', 'share')]
        runs = [original]
        for number, (key, value) in enumerate(changes):
            run = make_run(run_id='variant-' + str(number))
            record(run)[key] = value
            runs.append(run)
        definition_variant = make_run(run_id='definition-variant')
        definition_variant['artifacts']['packet.json']['metric_catalog']['revenue']['definition_version'] = 'synthetic-v2'
        runs.append(definition_variant)
        table = build_financial_table(runs)
        self.assertEqual(len(table['rows']), len(runs))
        self.assertTrue(all(row['label'] == 'Reported revenue' for row in table['rows']))
        self.assertEqual(table['counts']['conflict_cells'], 0)

    def test_exact_periods_instant_duration_and_basis_are_distinct(self):
        runs = [make_run(run_id='one'), make_run(run_id='two'), make_run(run_id='three'), make_run(run_id='four')]
        record(runs[1])['period']['start'] = '2032-01-01'
        record(runs[2])['period'] = {'kind': 'instant', 'start': None, 'end': '2032-12-25', 'basis': 'source'}
        record(runs[3])['period']['basis'] = 'calendar'
        table = build_financial_table(runs)
        self.assertEqual(len(table['periods']), 4)
        self.assertEqual(len(table['rows']), 1)
        self.assertTrue(any(p['start'] == '2031-12-28' for p in table['periods']))
        self.assertTrue(any(p['kind'] == 'instant' and p['start'] is None for p in table['periods']))
        self.assertEqual(len(table['rows'][0]['cells']), 4)

    def test_exact_decimal_no_sum_no_latest_and_independent_review(self):
        run = make_run()
        old = deepcopy(run)
        newer = make_run(run_id='newer-run', value='99999999999999999999.00000000000000000001')
        newer['review'] = None
        table = build_financial_table([run, newer])
        cell = next(iter(table['rows'][0]['cells'].values()))
        self.assertEqual(cell['status'], 'conflict')
        self.assertEqual(cell['conflict_reasons'], ['different_value'])
        self.assertEqual([c['value'] for c in cell['candidates']], [record(run)['value_decimal'], record(newer)['value_decimal']])
        first = cell['candidates'][0]
        self.assertEqual(first['display_value'], '12,345,678,901,234,567,890.1234567890123456789')
        self.assertEqual(first['review_status'], 'value_scope_matched')
        self.assertEqual(first['record_status'], 'candidate')
        self.assertEqual(first['record'], first['raw'])
        self.assertEqual(first['qualifier_refs'][0]['evidence_id'], 'local-qualifier')
        self.assertEqual(table['counts']['unreviewed_candidates'], 1)
        first['raw']['origin']['raw']['value'] = 'changed view copy'
        first['evidence_refs'][0]['quote'] = 'changed view copy'
        self.assertEqual(run, old)

    def test_equal_values_are_multiple_not_deduplicated_or_conflicted(self):
        table = build_financial_table([make_run(value='1.000'), make_run(run_id='two', value=Decimal('1.00'))])
        cell = next(iter(table['rows'][0]['cells'].values()))
        self.assertEqual(cell['status'], 'multiple')
        self.assertFalse(cell['conflict'])
        self.assertEqual([c['display_value'] for c in cell['candidates']], ['1', '1'])
        self.assertEqual([c['value'] for c in cell['candidates']], ['1.000', '1.00'])

    def test_display_groups_digits_without_rounding_or_mutating_original_precision(self):
        value = '-123456789012345678901234567890.123456789012345678901234567890000'
        upper = '-1000.000000000000'
        run = make_run(value=value)
        record(run)['upper_decimal'] = upper
        record(run)['value_relation'] = 'approx'
        candidate = candidates(build_financial_table([run]))[0]
        self.assertEqual(candidate['display_value'],
                         '≈ -123,456,789,012,345,678,901,234,567,890.12345678901234567890123456789 – -1,000')
        displayed_lower = candidate['display_value'].removeprefix('≈ ').split(' – ')[0].replace(',', '')
        self.assertEqual(Decimal(displayed_lower), Decimal(value))
        self.assertEqual(candidate['value'], value)
        self.assertEqual(candidate['upper'], upper)
        self.assertEqual(candidate['raw']['value_decimal'], value)
        self.assertEqual(candidate['record']['upper_decimal'], upper)
        for number, display in [('1000000.000000000000', '1,000,000'),
                                ('-2500.120000000000', '-2,500.12'),
                                ('0.00000000000000000000000001', '0.00000000000000000000000001')]:
            with self.subTest(number=number):
                item = candidates(build_financial_table([make_run(value=number)]))[0]
                self.assertEqual(item['display_value'], display)
                self.assertEqual(item['value'], number)

    def test_range_relation_and_review_disagreement_are_visible(self):
        a, b = make_run(value='10'), make_run(run_id='two', value='10')
        record(a)['upper_decimal'] = '20'
        record(b)['upper_decimal'] = '30'
        record(b)['value_relation'] = 'gte'
        b['review']['facts'][0]['verdict'] = 'needs_evidence'
        table = build_financial_table([a, b])
        cell = next(iter(table['rows'][0]['cells'].values()))
        self.assertEqual(set(cell['conflict_reasons']), {'different_upper', 'different_value_relation', 'different_review_verdicts'})
        self.assertEqual(cell['candidates'][1]['display_value'], '≥ 10 – 30')

    def test_review_binds_company_source_hash_and_record_and_never_adopts(self):
        for key, bad in [('company_id', 'harbor'), ('source_snapshot_id', 'foreign-source'),
                         ('source_sha256', 'd' * 64), ('run_id', 'foreign-run')]:
            run = make_run()
            run['review'][key] = bad
            with self.subTest(key=key):
                table = build_financial_table([run])
                self.assertIsNone(candidates(table)[0]['review'])
                self.assertEqual(candidates(table)[0]['review_status'], 'not_reviewed')
                self.assertEqual(candidates(table)[0]['record_status'], 'candidate')
                self.assertEqual(table['gaps'][0]['reason'], 'review_binding_mismatch')
        run = make_run()
        run['review']['facts'].append(deepcopy(run['review']['facts'][0]))
        table = build_financial_table([run])
        self.assertEqual(table['gaps'][0]['reason'], 'ambiguous_record_review')

    def test_missing_period_and_cell_are_explicit(self):
        a, b = make_run(), make_run(run_id='two')
        record(b)['period'] = None
        record(b)['metric_id'] = 'cash'
        record(b)['value_decimal'] = None
        table = build_financial_table([a, b])
        self.assertEqual(len(table['periods']), 2)
        self.assertEqual(table['counts']['missing_cells'], 2)
        self.assertEqual({g['reason'] for g in table['gaps']}, {'unresolved_period', 'unresolved_value'})
        self.assertEqual(next(c for c in candidates(table) if c['run_id'] == 'two')['value'], None)

    def test_floats_nonfinite_values_missing_scope_and_foreign_evidence_rejected(self):
        for value in (1.2, True, 'NaN', 'Infinity', 'not-a-number'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_financial_table([make_run(value=value)])
        for key in ('id', 'company_id', 'source_snapshot_id', 'source_sha256'):
            run = make_run()
            run[key] = ''
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_financial_table([run])
        for key in ('source_snapshot_id', 'source_sha256'):
            run = make_run()
            run['artifacts']['normalized.json']['evidence']['local-evidence'][key] = 'foreign'
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_financial_table([run])
        run = make_run()
        record(run)['source_snapshot_id'] = 'foreign'
        with self.assertRaises(ValueError):
            build_financial_table([run])
        with self.assertRaises(ValueError):
            build_financial_table([make_run(), make_run()])

    def test_dataset_mode_is_source_bound_independent_and_not_reviewed(self):
        first, second = make_run(), make_run(run_id='two')
        record(second)['source_snapshot_id'] = 'other-source'
        record(second)['value_decimal'] = '999'
        data = {'id': 'cedar-dataset', 'manifest_sha256': 'b' * 64, 'company': {'company_id': 'cedar'},
                'sources': [{'company_id': 'cedar', 'source_snapshot_id': 'cedar-source', 'source_sha256': 'a' * 64},
                            {'company_id': 'cedar', 'source_snapshot_id': 'other-source', 'source_sha256': 'd' * 64}],
                'records': [record(first), record(second)],
                'metrics': first['artifacts']['packet.json']['metric_catalog'],
                'evidence': first['artifacts']['normalized.json']['evidence'],
                'gaps': [{'source_snapshot_id': 'other-source', 'reason': 'unrelated'}]}
        table = build_dataset_table(data, 'cedar-source')
        self.assertEqual(table['counts']['records'], 1)
        candidate = candidates(table)[0]
        self.assertIsNone(candidate['run_id'])
        self.assertEqual(candidate['origin_kind'], 'dataset')
        self.assertEqual(candidate['review_status'], 'not_reviewed')
        self.assertEqual(table['gaps'], [])
        for source in (None, '', 'unknown-source'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                build_dataset_table(data, source)


if __name__ == '__main__':
    unittest.main()
