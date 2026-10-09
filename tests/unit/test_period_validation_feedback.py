"""Protocol-owned period repairs preserve caller dates and redact input values."""
from copy import deepcopy
import json
import unittest

from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.agents.data_query.autonomous_model import _decision_validation_hints
from uteki.domain.research_data.query_contract import validate_period_version


class PeriodValidationFeedbackTests(unittest.TestCase):
    def decision(self):
        return {'action': 'plan', 'reason': 'Independent synthetic dates', 'requirements': [{
            'requirement_id': 'synthetic-revenue', 'kind': 'query', 'description': 'Original revenue',
            'query': {'records': [{'entity_id': 'private-entity-value', 'metric_id': 'revenue', 'period': {
                'kind': 'ytd', 'start': '2037-10-01', 'end': '2038-06-30', 'basis': 'calendar'}}]}}]}

    def test_cross_year_calendar_rejection_returns_fixed_source_basis_rule(self):
        value = self.decision()
        hints = _decision_validation_hints(json.dumps(value))
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]['location'], ['requirements', 0, 'query', 'records', 0, 'period'])
        self.assertEqual(hints[0]['rule'], 'explicit_period_basis')
        self.assertIn('period.basis=source', hints[0]['suggestion'])
        self.assertIn('preserve the exact kind/start/end', hints[0]['suggestion'])
        for secret in ('private-entity-value', '2037-10-01', '2038-06-30', 'Original revenue'):
            self.assertNotIn(secret, json.dumps(hints))

    def test_explicit_source_repair_keeps_dates_and_cannot_bypass_old_protocol(self):
        value = self.decision()
        original = deepcopy(value['requirements'][0]['query']['records'][0]['period'])
        value['requirements'][0]['query']['records'][0]['period']['basis'] = 'source'
        decision = AutonomousDecision.model_validate(value)
        period = decision.requirements[0].query.records[0].period
        self.assertEqual((str(period.start), str(period.end), period.kind),
                         (original['start'], original['end'], original['kind']))
        validate_period_version(period, 'research-query-v0.4')
        with self.assertRaises(ValueError):
            validate_period_version(period, 'research-query-v0.3')

    def test_nested_unknown_fields_remain_redacted(self):
        value = self.decision()
        value['requirements'][0]['query']['records'][0]['period'] = {
            'kind': 'quarter', 'start': '2038-01-01', 'end': '2038-03-31',
            'private-rejected-key': 'private-rejected-value'}
        hints = _decision_validation_hints(json.dumps(value))
        self.assertEqual(hints[0]['location'], ['requirements', 0, 'query', 'records', 0, 'period', '<field>'])
        self.assertNotIn('private-rejected', json.dumps(hints))

    def test_source_basis_invalid_dates_still_reject_without_echoing_dates(self):
        value = self.decision()
        value['requirements'][0]['query']['records'][0]['period'].update(
            basis='source', start='2038-02-30', end='2038-01-01')
        hints = _decision_validation_hints(json.dumps(value))
        self.assertTrue(hints)
        self.assertNotIn('2038-02-30', json.dumps(hints))
        self.assertNotIn('private-entity-value', json.dumps(hints))
