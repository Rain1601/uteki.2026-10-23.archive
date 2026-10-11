"""Caller-declared date ranges, independent of issuer coverage and model calls."""
from copy import deepcopy
import unittest

from uteki.domain.research_data.period_scope import PERIOD_SCOPE_VERSION, explicit_periods, validate_plan_periods
from uteki.domain.research_data.query_contract import Period, validate_period_version
from uteki.domain.research_data.task_plan import QueryPlan


class TypedDatePeriodTests(unittest.TestCase):
    def periods(self, text, **kwargs):
        return explicit_periods(text, require_fiscal_mapping=True, **kwargs)

    def test_quarter_and_cross_year_cumulative_keep_distinct_starts(self):
        for text in (
            'Revenue: quarter from 2034-02-01 to 2034-04-30; ytd from 2033-11-01 to 2034-04-30.',
            '收入：单季度 2034-02-01 至 2034-04-30；累计期间 2033-11-01 至 2034-04-30。',
        ):
            with self.subTest(text=text):
                values = self.periods(text)
                self.assertEqual([p.model_dump(mode='json') for p in values], [
                    {'kind': 'quarter', 'start': '2034-02-01', 'end': '2034-04-30', 'basis': 'source'},
                    {'kind': 'ytd', 'start': '2033-11-01', 'end': '2034-04-30', 'basis': 'source'}])
                for p in values:
                    validate_period_version(p, 'research-query-v0.4')

    def test_calendar_ranges_keep_calendar_basis_and_duplicates_collapse(self):
        values = self.periods('quarter 2036-01-01 to 2036-03-31; ytd 2036-01-01 to 2036-09-30; '
                              'quarter 2036-01-01 to 2036-03-31; year 2036-01-01 to 2036-12-31')
        self.assertEqual([p.kind for p in values], ['quarter', 'ytd', 'year'])
        self.assertTrue(all(p.basis == 'calendar' for p in values))

    def test_missing_kind_invalid_dates_relative_and_untyped_ranges_reject(self):
        for text in (
            'Revenue from 2034-02-01 to 2034-04-30',
            'quarter from 2034-02-30 to 2034-04-30',
            'ytd from 2034-11-01 to 2034-04-30',
            'quarter from 2034-02-01 to 2034-04-30T12:00:00',
            'quarter from 2034-02-01 to 2034-04-30.5',
            'quarter from 2034-02-01 to 2034-04-30abc',
            'quarter from 2034-02-01 to 2034-04-30 12:00:00',
            'quarter from 2034-02-01 to 2034-04-30; latest revenue',
            'quarter from 2034-02-01 to 2034-04-30; FY2034 YTD',
            'quarter from 2034-02-01 to 2034-04-30; 2033-2034 revenue',
        ):
            with self.subTest(text=text):
                self.assertEqual(self.periods(text), ())

    def test_cutoff_is_separate_and_conflicting_cutoff_rejects(self):
        question = 'information cutoff: 2035-06-01, ytd from 2034-08-01 to 2035-04-30'
        values = self.periods(question, knowledge_cutoff='2035-06-01')
        self.assertEqual(len(values), 1)
        self.assertEqual(str(values[0].start), '2034-08-01')
        self.assertEqual(self.periods(question, knowledge_cutoff='2035-06-02'), ())

    def test_coverage_cannot_replace_dates_and_fiscal_labels_still_need_mapping(self):
        text = 'quarter 2034-02-01 to 2034-04-30'
        mapping = [{'fiscal_year': 2034, 'fiscal_quarter': 2,
                    'period': {'kind': 'quarter', 'start': '2034-04-01', 'end': '2034-06-30'}}]
        self.assertEqual(self.periods(text, fiscal_periods=mapping), self.periods(text))
        self.assertEqual(self.periods(text + '; FY2034 Q1', fiscal_periods=mapping), ())
        self.assertEqual(self.periods('FY2034 Q2 (' + text + ')', fiscal_periods=mapping), ())
        self.assertEqual(self.periods(text + '; 2034 Q2'), ())
        self.assertEqual(self.periods(text + '; for 2034'), ())

    def test_wrong_start_kind_and_period_cannot_pass_query_grounding(self):
        allowed = self.periods('ytd 2033-11-01 to 2034-04-30')
        for period in (
            {'kind': 'quarter', 'start': '2034-02-01', 'end': '2034-04-30', 'basis': 'source'},
            {'kind': 'ytd', 'start': '2033-08-01', 'end': '2034-04-30', 'basis': 'source'},
            {'kind': 'ytd', 'start': '2032-11-01', 'end': '2033-04-30', 'basis': 'source'},
        ):
            plan = QueryPlan(records=[{'entity_id': 'independent-issuer', 'metric_id': 'revenue', 'period': period}])
            with self.subTest(period=period), self.assertRaises(ValueError):
                validate_plan_periods(plan, allowed)

    def test_declared_exact_dates_cannot_bypass_dataset_protocol(self):
        p, = self.periods('quarter 2034-02-05 to 2034-05-06')
        self.assertEqual(p, Period(kind='quarter', start='2034-02-05', end='2034-05-06', basis='source'))
        validate_period_version(p, 'research-query-v0.5')
        for version in ('research-query-v0.3', 'research-query-v0.4'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_period_version(p, version)

    def fiscal_mapping(self, *, year=2047, quarter=None, period=None, source='synthetic-report-a'):
        return {'source_snapshot_id': source, 'fiscal_year': year, 'fiscal_quarter': quarter,
                'period': period or {'kind': 'year', 'start': '2033-05-01',
                                    'end': '2034-04-30', 'basis': 'source'}}

    def test_fiscal_year_followed_by_ordinary_q_words_is_not_a_quarter(self):
        period = {'kind': 'year', 'start': '2031-01-01', 'end': '2031-12-31'}
        mapping = [self.fiscal_mapping(year=2031, period=period)]
        for word in ('quality', 'question', 'Quick'):
            for prefix in ('', 'year 2031-01-01 to 2031-12-31; '):
                text = prefix + 'FY2031 ' + word + ' review: report revenue'
                with self.subTest(text=text):
                    self.assertEqual(self.periods(text, fiscal_periods=mapping), (Period(**period),))
        for suffix in ('Q5', 'Q0', 'Q99', 'Q', 'Q 5', '第5季度'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.periods('FY2031 ' + suffix, fiscal_periods=mapping), ())
        # Ordinary words cannot supply a missing/conflicting fiscal mapping.
        self.assertEqual(self.periods('FY2031 quality review'), ())
        conflicting = self.fiscal_mapping(year=2031, period={**period, 'start': '2031-02-01', 'basis':'source'})
        self.assertEqual(self.periods('FY2031 question', fiscal_periods=[*mapping, conflicting]), ())

    def test_natural_chinese_prefixes_recognize_exact_ranges_and_redundant_fiscal_labels(self):
        mapping = [self.fiscal_mapping()]
        expected = (Period(kind='year', start='2033-05-01', end='2034-04-30', basis='source'),)
        for text in (
            '请提供全年2033-05-01至2034-04-30的收入，比较该FY2047期间的版本。',
            '请提供全年 2033-05-01 至 2034-04-30，解释2047财年的重列。',
            'year from 2033-05-01 to 2034-04-30; FY2047 revenue.',
            'FY2047 (year 2033-05-01 to 2034-04-30)',
        ):
            with self.subTest(text=text):
                self.assertEqual(self.periods(text, fiscal_periods=mapping), expected)
        for text, kind, start in (
            ('请提供单季度2034-02-01至2034-04-30的收入', 'quarter', '2034-02-01'),
            ('请提供累计期间2033-11-01至2034-04-30的收入', 'ytd', '2033-11-01'),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.periods(text), (Period(kind=kind, start=start,
                                                           end='2034-04-30', basis='source'),))

    def test_redundant_fiscal_quarter_labels_use_source_mapping_in_both_languages(self):
        period = {'kind': 'quarter', 'start': '2034-02-01', 'end': '2034-04-30', 'basis': 'source'}
        mapping = [self.fiscal_mapping(quarter=2, period=period)]
        for label in ('FY2047 Q2', '该FY2047Q2期间', '2047财年第二季度', '2047财年第2季度'):
            with self.subTest(label=label):
                self.assertEqual(self.periods('请提供单季度2034-02-01至2034-04-30；' + label,
                                             fiscal_periods=mapping), (Period(**period),))

    def test_fiscal_mapping_is_unique_across_sources_and_never_supplied_by_coverage(self):
        text = 'year 2033-05-01 to 2034-04-30; FY2047'
        first = self.fiscal_mapping()
        same = self.fiscal_mapping(source='synthetic-report-b')
        self.assertEqual(self.periods(text, fiscal_periods=[first, same]),
                         (Period.model_validate(first['period']),))
        conflicting = deepcopy(same)
        conflicting['period']['start'] = '2033-04-01'
        for mapping in ([], [self.fiscal_mapping(year=2048)], [first, conflicting]):
            with self.subTest(mapping=mapping):
                self.assertEqual(self.periods(text, fiscal_periods=mapping), ())
        # The legacy non-mapping mode must not silently interpret a mixed label as calendar FY.
        self.assertEqual(explicit_periods(text, require_fiscal_mapping=False), ())

    def test_fiscal_mapping_requires_exact_start_end_kind_and_basis(self):
        text = 'year 2033-05-01 to 2034-04-30; FY2047'
        for changed in (
            {'start': '2033-04-01'}, {'end': '2034-05-31'}, {'kind': 'ytd'},
        ):
            mapping = self.fiscal_mapping()
            mapping['period'].update(changed)
            with self.subTest(changed=changed):
                self.assertEqual(self.periods(text, fiscal_periods=[mapping]), ())
        calendar = {'kind': 'year', 'start': '2034-01-01', 'end': '2034-12-31'}
        text = 'year 2034-01-01 to 2034-12-31; FY2047'
        self.assertEqual(self.periods(text, fiscal_periods=[self.fiscal_mapping(period=calendar)]),
                         (Period(**calendar),))
        self.assertEqual(self.periods(text, fiscal_periods=[self.fiscal_mapping(
            period={**calendar, 'basis': 'source'})]), ())
        self.assertEqual(self.periods(text, fiscal_periods=[self.fiscal_mapping(
            period={**calendar, 'basis': 'calendar'}), self.fiscal_mapping(
                period={**calendar, 'basis': 'source'}, source='synthetic-report-b')]), ())

    def test_multiple_exact_ranges_allow_only_mapped_labels_already_in_the_question(self):
        second = {'kind': 'quarter', 'start': '2034-02-01', 'end': '2034-04-30', 'basis': 'source'}
        mapping = [self.fiscal_mapping(), self.fiscal_mapping(quarter=4, period=second)]
        text = 'year 2033-05-01 to 2034-04-30; quarter 2034-02-01 to 2034-04-30'
        expected = (Period.model_validate(mapping[0]['period']), Period(**second))
        self.assertEqual(self.periods(text + '; FY2047; FY2047 Q4', fiscal_periods=mapping), expected)
        self.assertEqual(self.periods(text + '; 2047财年；2047财年第四季度', fiscal_periods=mapping), expected)
        for suffix in ('; FY2048', '; FY2047 Q3', '; 2034 Q2', '; for 2034'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.periods(text + suffix, fiscal_periods=mapping), ())
        outside = self.fiscal_mapping(year=2048)
        outside['period'] = {'kind': 'year', 'start': '2034-05-01', 'end': '2035-04-30', 'basis': 'source'}
        self.assertEqual(self.periods(text + '; FY2048', fiscal_periods=[*mapping, outside]), ())

    def test_ascii_identifier_boundaries_and_malformed_fiscal_or_date_suffixes_still_reject(self):
        mapping = [self.fiscal_mapping()]
        for text in ('myyear 2033-05-01 to 2034-04-30', '_quarter 2034-02-01 to 2034-04-30',
                     'identifierFY2047', 'identifier_FY2047', '1FY2047'):
            with self.subTest(text=text):
                self.assertEqual(self.periods(text, fiscal_periods=mapping), ())
        for suffix in ('FY2047.5', 'FY20470', 'FY2047Q5', '该FY2047Q2.5', '2047财年第五季度',
                       'FY2047garbage'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.periods('请提供全年2033-05-01至2034-04-30；' + suffix,
                                             fiscal_periods=mapping), ())
                self.assertEqual(self.periods(suffix, fiscal_periods=mapping), ())
        for suffix in ('abc', 'T12:00:00', '.5', ' 12:00:00', '_suffix'):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.periods('请提供全年2033-05-01至2034-04-30' + suffix,
                                             fiscal_periods=mapping), ())
        self.assertEqual(PERIOD_SCOPE_VERSION, 'explicit-periods-v6-bound-availability-cutoff')
