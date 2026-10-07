"""Model-visible schema and runtime must agree; no provider calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator
from pydantic import ValidationError
from tests.unit.test_business_only_run import fixture
from uteki.agents.business_map.product_contract import (
    BUSINESS_DRAFT_V2_VERSION, BusinessOnlyDraftV2, validate_draft,
)
from uteki.agents.business_map import product_run as run


class KindRoleContractTests(unittest.TestCase):
    def test_all_pairs_schema_and_runtime_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, raw = fixture(Path(tmp))
            raw['schema_version'] = BUSINESS_DRAFT_V2_VERSION
            schema = BusinessOnlyDraftV2.model_json_schema()
            validator = Draft202012Validator(schema)
            for kind in ('company', 'reportable_segment', 'business', 'offering_group'):
                for role in (None, 'market', 'application_platform', 'offering_group', 'invalid'):
                    value = copy.deepcopy(raw)
                    value['businesses'][2].update(kind=kind, role=role)
                    expected = role is None or (kind == 'business' and role in ('market', 'application_platform')) or (kind == 'offering_group' and role == 'offering_group')
                    with self.subTest(kind=kind, role=role):
                        self.assertEqual(validator.is_valid(value), expected)
                        if expected:
                            BusinessOnlyDraftV2.model_validate(value)
                        else:
                            with self.assertRaises(ValidationError):
                                BusinessOnlyDraftV2.model_validate(value)
            # Omission retains the optional role without inventing a classification.
            BusinessOnlyDraftV2.model_validate(raw)
            self.assertTrue(validator.is_valid(raw))

    def test_prepared_schema_scope_and_materialization(self):
        for company, period in [('cobalt', '2022-03-31'), ('orion', '2024-12-31')]:
            with self.subTest(company=company), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                packet, raw = fixture(root, company=company, period=period)
                raw['schema_version'] = BUSINESS_DRAFT_V2_VERSION
                draft = validate_draft(raw, packet, expected_version=BUSINESS_DRAFT_V2_VERSION)
                self.assertEqual(draft.company_id, company)
                (root/'packet.json').write_text(json.dumps(packet))
                (root/'skill.md').write_text('Keep source-backed facts.')
                prepared = run.prepare(root=root, packet_path=root/'packet.json', skill_path=root/'skill.md',
                    company_id=company, document_id=packet['document_id'], period_end=period,
                    model='claude-sonnet-5-5', effort='high', max_tokens=16000, timeout_seconds=30,
                    contract_version=BUSINESS_DRAFT_V2_VERSION, thinking_type='between_tools')
                self.assertEqual(json.loads(prepared['request'])['thinking'], {'type':'between_tools'})
                run.verify_prepared(prepared)
                self.assertIn('CompanyNode', prepared['kwargs']['system_instructions'])
                self.assertEqual(prepared['schema'], BusinessOnlyDraftV2.model_json_schema())
                bad = copy.deepcopy(raw)
                bad['company_id'] = 'another-company'
                with self.assertRaises(ValueError):
                    validate_draft(bad, packet)
                bad = copy.deepcopy(raw)
                bad['businesses'][2]['evidence_block_ids'] = ['missing-source']
                with self.assertRaises(ValueError):
                    validate_draft(bad, packet)


class V2ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_delivery_preserves_business_only_boundary(self):
        from tests.unit.test_business_only_run import BusinessOnlyRunTests
        helper = BusinessOnlyRunTests()
        helper.setUp()
        try:
            helper.draft['schema_version'] = BUSINESS_DRAFT_V2_VERSION
            prepared = helper.prepare(contract_version=BUSINESS_DRAFT_V2_VERSION)
            result = await run.execute(prepared, root=helper.root, output=helper.root/'run',
                observation_root=helper.root/'observations', budget_limit_usd='1')
            self.assertEqual(result['status'], 'candidate')
            self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
            self.assertEqual(set(result['artifacts_sha256']), {'business_map.json', 'evidence.html'})
            self.assertEqual(len(helper.requests), 1)
        finally:
            helper.doCleanups()
