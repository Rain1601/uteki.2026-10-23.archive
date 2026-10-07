"""General evidence rules use synthetic issuers; no production-company repairs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from tests.unit.test_business_revenue_contract import fixture
from uteki.agents.business_map.product_contract import (
    DRAFT_VERSION, ProductDraft, ProductDraftV2, validate_draft,
)
from uteki.agents.business_map.product_run import materialize
from uteki.domain.business_map.models import business_map_from_dict


def evidence_fixture(company='orion', period='2025-06-30'):
    data, packet = fixture(company, period)
    data.update(schema_version=DRAFT_VERSION, relationship_absence='unknown')
    quote = packet['blocks'][0]['text']
    for business in data['businesses']:
        business['claim_evidence'] = [dict(field=f, item_index=None,
            excerpts=[dict(block_id='business-source', quote=quote)]) for f in ('name', 'description')]
    data['businesses'][1]['products_services'] = ['Tools']
    data['businesses'][1]['claim_evidence'].append(dict(field='products_services', item_index=0,
        excerpts=[dict(block_id='business-source', quote='tools')]))
    data['relationships'][0].update(basis='explicit', rationale='The source names this supplier and its tools.',
        excerpts=[dict(block_id='business-source', quote=quote)])
    return data, packet


class GeneralBusinessRulesTests(unittest.TestCase):
    def test_two_independent_issuers_use_identical_rules(self):
        for company, period in [('orion', '2025-06-30'), ('lyra', '2021-09-30')]:
            data, packet = evidence_fixture(company, period)
            actual = validate_draft(data, packet, expected_version=DRAFT_VERSION)
            self.assertIsInstance(actual, ProductDraftV2)
            self.assertEqual(actual.relationships[0].basis, 'explicit')
            self.assertEqual(actual.relationship_absence, 'unknown')

    def test_missing_claims_and_unbound_new_statements_are_rejected(self):
        mutations = [lambda d: d['businesses'][0].pop('claim_evidence'),
                     lambda d: d['businesses'][1]['products_services'].append('Uncited support'),
                     lambda d: d['businesses'][1].update(customers=['Manufacturers']),
                     lambda d: d['businesses'][1]['claim_evidence'].append(
                         copy.deepcopy(d['businesses'][1]['claim_evidence'][0]))]
        for mutate in mutations:
            data, packet = evidence_fixture()
            mutate(data)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_draft(data, packet)

    def test_source_quotes_must_exist_and_cannot_borrow_another_source_block(self):
        for field, value, error in [('quote', 'unmentioned chip sales', 'quote_not_in_source'),
                                    ('block_id', 'another-issuer-block', 'evidence_outside_packet')]:
            data, packet = evidence_fixture()
            data['businesses'][0]['claim_evidence'][0]['excerpts'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, error):
                validate_draft(data, packet)
        data, packet = evidence_fixture()
        data['businesses'][0]['claim_evidence'][0]['excerpts'] = [dict(block_id='unit', quote='millions')]
        with self.assertRaisesRegex(ValueError, 'not_in_node_evidence'):
            validate_draft(data, packet)

    def test_missing_cross_company_document_and_period_scope_never_fall_back(self):
        for key in ('company_id', 'document_id', 'period_end'):
            data, packet = evidence_fixture()
            for target in ('output', 'packet'):
                altered = copy.deepcopy(data if target == 'output' else packet)
                altered.pop(key)
                with self.subTest(key=key, target=target), self.assertRaises(ValueError):
                    validate_draft(altered if target == 'output' else data,
                                   packet if target == 'output' else altered)
            data[key] = {'company_id': 'other-issuer', 'document_id': 'other-filing', 'period_end': '2020-12-31'}[key]
            with self.assertRaisesRegex(ValueError, 'scope_mismatch'):
                validate_draft(data, packet)

    def test_relationship_basis_explanation_and_excerpt_required(self):
        for key in ('basis', 'rationale', 'excerpts'):
            data, packet = evidence_fixture()
            data['relationships'][0].pop(key)
            with self.subTest(key=key), self.assertRaises(ValidationError):
                validate_draft(data, packet)
        data, packet = evidence_fixture()
        relation = data['relationships'][0]
        relation.update(basis='derived', rationale='The source describes delivery; ownership is an inference.')
        self.assertEqual(validate_draft(data, packet).relationships[0].basis, 'derived')
        relation.update(evidence_block_ids=[], excerpts=[])
        with self.assertRaisesRegex(ValueError, 'relationship_evidence_required'):
            validate_draft(data, packet)

    def test_unknown_edge_requires_gap_and_missing_edge_never_means_independent(self):
        data, packet = evidence_fixture()
        data['relationships'][0].update(basis='unknown', rationale='The grouping is not established.',
                                        evidence_block_ids=[], excerpts=[])
        with self.assertRaisesRegex(ValueError, 'unknown_relationship_requires_gap'):
            validate_draft(data, packet)
        data['unknowns'].append(dict(id='membership', question='Where does this offering belong?',
            reason_unanswered='Selected source does not establish membership.', related_business_ids=['root', 'tools']))
        self.assertEqual(validate_draft(data, packet).relationships[0].basis, 'unknown')
        data['relationships'] = []
        self.assertEqual(validate_draft(data, packet).relationship_absence, 'unknown')
        data['relationship_absence'] = 'independent'
        with self.assertRaises(ValidationError):
            validate_draft(data, packet)

    def test_legacy_frozen_schema_and_output_remain_readable_without_upgrading_basis(self):
        frozen = Path('experiments/agent_design/2026-10-07-agent-business-revenue-v1/run-01')
        self.assertEqual(json.loads((frozen/'output_schema.json').read_text()), ProductDraft.model_json_schema())
        draft = json.loads((frozen/'draft.json').read_text())
        packet = json.loads((frozen/'source_packet.json').read_text())
        self.assertIs(type(validate_draft(draft, packet)), ProductDraft)
        with self.assertRaisesRegex(ValueError, 'contract_version_mismatch'):
            validate_draft(draft, packet, expected_version=DRAFT_VERSION)
        parsed = business_map_from_dict(json.loads((frozen/'business_map.json').read_text()))
        self.assertTrue(all(r.basis is None for r in parsed.relationships))
        self.assertNotIn('relationship_absence', parsed.to_dict())
        self.assertTrue(all('basis' not in r for r in parsed.to_dict()['relationships']))
        bad = json.loads((frozen/'business_map.json').read_text())
        for version in ('business-map-v999', '', 'business-map-v0.2-typo'):
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'unsupported_business_map_schema_version'):
                business_map_from_dict(bad)

    def test_v2_materialization_and_domain_reader_preserve_annotations_and_reject_scope_forgery(self):
        data, packet = evidence_fixture()
        for ordinal, block in enumerate(packet['blocks'], 1):
            block['ordinal'] = ordinal
        for table in packet['tables']:
            for cell in table['cells']:
                import hashlib
                cell['text_sha256'] = hashlib.sha256(cell['text'].encode()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root/'run'
            output.mkdir()
            materialize(validate_draft(data, packet), packet, root=root, output=output,
                        manifest=dict(source_packet_sha256='packet', skill_sha256='skill', model='offline'), trace_id='offline')
            product = json.loads((output/'business_map.json').read_text())
        parsed = business_map_from_dict(product)
        self.assertEqual(parsed.relationships[0].basis, 'explicit')
        self.assertEqual(parsed.relationship_absence, 'unknown')
        self.assertEqual(parsed.businesses[1].claim_evidence[-1].excerpts[0].quote, 'tools')
        for key in ('company_id', 'document_id'):
            bad = copy.deepcopy(product)
            bad['evidence'][0][key] = 'other-source'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'evidence_scope_mismatch'):
                business_map_from_dict(bad)
        bad = copy.deepcopy(product)
        bad['relationships'][0].pop('basis')
        with self.assertRaisesRegex(ValueError, 'basis_and_rationale_required'):
            business_map_from_dict(bad)
        bad = copy.deepcopy(product)
        bad['businesses'][0]['claim_evidence'] = []
        with self.assertRaisesRegex(ValueError, 'claim_coverage_mismatch'):
            business_map_from_dict(bad)


if __name__ == '__main__':
    unittest.main()
