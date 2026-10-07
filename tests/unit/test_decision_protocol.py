"""Contract and host checks over independent synthetic sources; no model evaluation."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from typing import get_args
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from uteki.agents.data_query.autonomous import AutonomousDataAgent, AutonomousDecision, AUTONOMOUS_PROMPT
from uteki.agents.data_query.autonomous_model import _decision_validation_hints
from uteki.agents.data_query.decision_protocol import ACTION_RULES
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.query_service import QueryDataPort, ScopedQueryDataPort
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, plan
from tests.unit.test_scoped_query_service import make_scoped_dataset


class DecisionProtocolTests(unittest.TestCase):
    def test_registered_actions_and_schema_requirements_are_exposed_to_model(self):
        self.assertEqual(set(ACTION_RULES), set(get_args(AutonomousDecision.model_fields['action'].annotation)))
        schema = AutonomousDecision.model_json_schema()
        def required_for(action):
            return {field for row in schema['allOf']
                    if action in row['if']['properties']['action']['enum']
                    for field in row['then']['required']}
        self.assertEqual(required_for('plan'), {'requirements', 'reason'})
        self.assertEqual(required_for('read_context'), {'context', 'requirement_ids'})
        self.assertEqual(required_for('gap'), {'requirement_ids', 'reason'})
        self.assertEqual(required_for('read_artifact'), {'artifact_read'})
        self.assertTrue(schema['properties']['requirement_ids']['uniqueItems'])
        self.assertIn('read_context | context | requirement_ids (nonempty)', AUTONOMOUS_PROMPT)

    def test_missing_reason_refs_and_invalid_ids_rejected_with_safe_feedback(self):
        decision = {'action': 'outline_source', 'outline': {'source_snapshot_id': 'other-annual'}}
        invalid = [decision, {**decision, 'requirement_ids': []},
                   {**decision, 'requirement_ids': ['business', 'business']},
                   {**decision, 'requirement_ids': [' ']},
                   {key: value for key, value in plan('business').items() if key != 'reason'}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AutonomousDecision.model_validate(value)
        hint = _decision_validation_hints(json.dumps(decision))[0]
        self.assertEqual(hint['rule'], 'action_requires_requirements')
        self.assertNotIn('other-annual', json.dumps(hint))
        self.assertEqual(AutonomousDecision.model_validate(
            {**decision, 'requirement_ids': ['business']}).requirement_ids, ('business',))

    def test_artifact_reads_remain_valid_without_refs_and_respect_page_limit(self):
        value = {'action': 'read_artifact', 'artifact_read': {
            'artifact_id': 'art-synthetic', 'pointer': '/blocks/0/text', 'limit': 1000, 'offset': 1000}}
        self.assertEqual(AutonomousDecision.model_validate(value).artifact_read.offset, 1000)
        for limit in (0, 1100):
            with self.subTest(limit=limit), self.assertRaises(ValidationError):
                AutonomousDecision.model_validate({**value, 'artifact_read': {**value['artifact_read'], 'limit': limit}})

    def test_invalid_actions_never_read_source_and_corrected_action_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / 'dataset'
            dataset.mkdir()
            make_scoped_dataset(dataset)
            with QueryDataPort(dataset) as port:
                scope = ExecutionScope(snapshot_id=port.snapshot_id, company_ids=('acme',),
                    source_snapshot_ids=('acme-annual',), source_policy_id='local-frozen-v1',
                    knowledge_cutoff='2032-05-01', include_candidates=True)
                read = {'action': 'read_context', 'context': {
                    'source_snapshot_id': 'acme-annual', 'block_id': 'b1'}}
                actions = [plan('business'), deepcopy(read),
                           {**read, 'requirement_ids': ['unknown']},
                           {**read, 'requirement_ids': ['business']}, {'action': 'finish'}]
                calls = []
                original = ScopedQueryDataPort.read_context
                def recording(instance, **kwargs):
                    calls.append(kwargs)
                    return original(instance, **kwargs)
                planner = ScriptedPlanner(actions)
                with patch.object(ScopedQueryDataPort, 'read_context', recording):
                    result = asyncio.run(AutonomousDataAgent(port, planner, limits={'max_steps': 5}).run(
                        {'question': 'Read the selected source business.', 'scope': scope.model_dump(mode='json')},
                        output=root/'run'))
                self.assertEqual([row['status'] for row in result['trace'][1:4]],
                                 ['rejected', 'rejected', 'tool_returned'])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['source_snapshot_id'], 'acme-annual')
                self.assertEqual(result['status'], 'evidence_ready')


if __name__ == '__main__':
    unittest.main()
