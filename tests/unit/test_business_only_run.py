"""Business-only scope and evidence acceptance; all HTTP is a mock transport."""
import copy
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from lxml import html

from uteki.agents.business_map import product_run as run
from uteki.agents.business_map import product_wire
from uteki.agents.business_map.product_contract import (
    BUSINESS_DRAFT_VERSION, BusinessOnlyDraft, validate_draft,
)
from uteki.domain.business_map.models import business_map_from_dict


PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('business_only_cli', PROJECT / 'scripts/run_business_revenue_agent.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def fixture(root, company='cobalt', period='2022-03-31'):
    paragraphs = [
        ('issuer', f'{company} Systems is the reporting company.'),
        ('period', f'The reporting period ends on {period}.'),
        ('section', 'Services is a reportable segment.'),
        ('product', 'The Services segment includes Beacon support software for engineers.'),
        ('layout', '12'),
        ('competition', 'Competition includes rivals; Beacon support software remains our offering.'),
        ('boundary', 'Devices'),
    ]
    source = '<html><body>' + ''.join(f'<p id="{key}">{text}</p>' for key, text in paragraphs) + '</body></html>'
    (root/'source.html').write_text(source)
    raw = (root/'source.html').read_bytes()
    dom = html.fromstring(raw)
    tree = dom.getroottree()
    blocks = []
    for ordinal, (key, _) in enumerate(paragraphs[:-1], 1):
        el = dom.get_element_by_id(key)
        text = ' '.join(''.join(el.itertext()).split())
        blocks.append(dict(id=key, ordinal=ordinal, text=text, text_sha256=run.digest(text.encode()),
            source_dom_path=tree.getpath(el), section_path=['Synthetic report', 'Services'],
            input_role='scope_metadata' if ordinal <= 2 else 'selected_subsection'))
    packet = dict(company_id=company, document_id=f'{company}-{period}', period_end=period,
        source_local_path='source.html', source_url=f'https://example.invalid/{company}/{period}',
        source_sha256=run.digest(raw), blocks=blocks, tables=[],
        extraction_scope=dict(kind='complete_report_subsection', title='Business / Services',
            start_ordinal=3, end_ordinal_inclusive=6, end_boundary_exclusive_ordinal=7,
            end_boundary_exclusive_title='Devices', section_block_ids=['section','product','layout','competition'],
            scope_metadata_block_ids=['issuer','period'], filtered_block_ids=[], financial_analysis=False),
        scope_evidence_block_ids=dict(company=['issuer'], period=['period']))
    manifest = {key: packet[key] for key in ('company_id','document_id','period_end','source_url')}
    manifest['content_sha256'] = packet['source_sha256']
    (root/'source_manifest.json').write_text(json.dumps(manifest))
    packet['source_manifest'] = dict(local_path='source_manifest.json',
                                    sha256=run.digest((root/'source_manifest.json').read_bytes()))
    quotes = {b['id']: b['text'] for b in blocks}
    def node(key, name, kind, block):
        return dict(id=key, name=name, kind=kind, description=quotes[block], evidence_block_ids=[block],
            claim_evidence=[dict(field=field, item_index=None, excerpts=[dict(block_id=block, quote=quotes[block])])
                            for field in ('name', 'description')])
    draft = dict(schema_version=BUSINESS_DRAFT_VERSION, company_id=company, document_id=packet['document_id'],
        period_end=period, source_sha256=packet['source_sha256'], summary='Services subsection only.',
        relationship_absence='unknown', businesses=[node('issuer', f'{company} Systems', 'company', 'issuer'),
            node('services', 'Services', 'reportable_segment', 'section'),
            node('beacon', 'Beacon support software', 'business', 'product')],
        relationships=[dict(source_id='beacon', target_id='services', kind='part_of',
            description='Beacon belongs to Services.', basis='explicit', rationale='The source states inclusion.',
            evidence_block_ids=['product'], excerpts=[dict(block_id='product', quote=quotes['product'])])],
        unknowns=[dict(id='unspecified-ownership', question='What other links exist?',
            reason_unanswered='The selected subsection does not establish other links.', related_business_ids=[])],
        block_disposition=[dict(block_id=b['id'], disposition=('context' if b['ordinal'] <= 2 else
            'layout_noise' if b['id'] == 'layout' else 'used'), reason='Identity context.' if b['ordinal'] <= 2 else
            'Page number only.' if b['id'] == 'layout' else 'Reviewed selected business text.') for b in blocks])
    return packet, draft


class BusinessOnlyRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.packet, self.draft = fixture(self.root)
        self.requests = []
        self.skill = self.root/'SKILL.md'
        self.skill.write_text('---\nname: synthetic-skill\ndescription: Offline test.\n---\nPreserve supported business facts.')
        self.packet_path = self.root/'packet.json'
        self.env = patch.dict(os.environ, {'AIHUBMIX_API_KEY': 'offline-test-key'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def prepare(self, **overrides):
        self.packet_path.write_text(json.dumps(self.packet))
        options = dict(company_id=self.packet.get('company_id'), document_id=self.packet.get('document_id'),
            period_end=self.packet.get('period_end'), model='claude-sonnet-5-5', effort='high',
            max_tokens=3000, timeout_seconds=30, contract_version=BUSINESS_DRAFT_VERSION)
        options.update(overrides)
        prepared = run.prepare(root=self.root, packet_path=self.packet_path, skill_path=self.skill, **options)
        prepared['native']._client_factory = self.client_factory
        return prepared

    def client_factory(self, **kwargs):
        kwargs['transport'] = httpx.MockTransport(self.respond)
        return httpx.AsyncClient(**kwargs)

    def respond(self, request):
        self.requests.append(request)
        return httpx.Response(200, json=dict(id='msg_business_only', model='claude-sonnet-5-5',
            stop_reason='end_turn', usage=dict(input_tokens=180, output_tokens=120),
            content=[dict(type='text', text=json.dumps(self.draft))]))

    def test_nonfinancial_scope_and_schema_are_explicit_for_two_independent_companies(self):
        for company, period in [('cobalt','2022-03-31'), ('quartz','2020-09-30')]:
            self.packet, self.draft = fixture(self.root, company, period)
            prepared = self.prepare()
            run.verify_prepared(prepared)
            value = validate_draft(self.draft, self.packet, expected_version=BUSINESS_DRAFT_VERSION)
            self.assertIsInstance(value, BusinessOnlyDraft)
            self.assertNotIn('revenue_charts', prepared['schema']['properties'])
            self.assertNotIn('RevenueChartDraft', prepared['schema'].get('$defs', {}))
            self.assertEqual(prepared['manifest']['task_type'], 'business_map')
            body = json.loads(prepared['request'])
            self.assertEqual(json.loads(body['messages'][0]['content']), self.packet)
            self.assertIn('block_disposition', body['system'])
            self.assertIn('including competition text', body['system'])
            self.assertNotIn('Set schema_version to business-revenue-draft-v2', body['system'])
        self.assertEqual(self.requests, [])

    async def test_full_mock_execution_emits_only_business_and_evidence_with_real_scope(self):
        result = await run.execute(self.prepare(), root=self.root, output=self.root/'run',
            observation_root=self.root/'observations', budget_limit_usd='1')
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
        self.assertEqual(set(result['artifacts_sha256']), {'business_map.json','evidence.html'})
        self.assertNotIn('revenue_charts', result['counts'])
        self.assertFalse((self.root/'run/revenue.json').exists())
        candidate = json.loads((self.root/'run/business_map.json').read_text())
        self.assertEqual(candidate['schema_version'], 'business-map-v0.2')
        self.assertEqual(candidate['metadata']['extraction_scope'], self.packet['extraction_scope'])
        self.assertEqual(candidate['metadata']['block_disposition'], self.draft['block_disposition'])
        self.assertEqual(candidate['metadata']['disposition_acceptance'], 'self_reported_not_semantic_coverage')
        self.assertEqual(business_map_from_dict(candidate).relationships[0].basis, 'explicit')
        self.assertTrue(all(e['company_id'] == self.packet['company_id'] for e in candidate['evidence']))
        checks = json.loads((self.root/'run/validation.json').read_text())['checks']
        self.assertIn('block_disposition', checks)
        self.assertNotIn('reconciliation', checks)
        self.assertEqual(len(self.requests), 1)

    def test_scope_missing_cross_company_period_source_and_partial_selection_rejected(self):
        original = copy.deepcopy(self.packet)
        changes = [lambda p:p.pop('period_end'), lambda p:p.pop('source_manifest'),
            lambda p:p.pop('scope_evidence_block_ids'), lambda p:p.update(source_sha256='0'*64),
            lambda p:p.update(company_id='other-company'), lambda p:p.update(document_id='other-document'),
            lambda p:p.update(period_end='2024-12-31'),
            lambda p:p['extraction_scope']['section_block_ids'].pop(),
            lambda p:p['extraction_scope']['scope_metadata_block_ids'].append('product'),
            lambda p:p['scope_evidence_block_ids'].update(period=['product']),
            lambda p:p['blocks'][2].update(input_role='scope_metadata')]
        for change in changes:
            self.packet = copy.deepcopy(original)
            change(self.packet)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.prepare()
        self.packet = original
        for key, value in [('company_id','other'), ('document_id','another-filing'), ('period_end','2024-12-31')]:
            with self.subTest(caller=key), self.assertRaisesRegex(ValueError, 'caller_packet_scope_mismatch'):
                self.prepare(**{key:value})
        self.assertEqual(self.requests, [])

    def test_revenue_or_wrong_source_and_unbound_claims_cannot_enter_business_output(self):
        changes = [lambda d:d.update(revenue_charts=[]), lambda d:d.update(source_sha256='0'*64),
            lambda d:d.update(company_id='another-issuer'), lambda d:d.update(document_id='other-filing'),
            lambda d:d.update(period_end='2020-12-31'), lambda d:d.pop('period_end'),
            lambda d:d['businesses'][1]['claim_evidence'].pop(),
            lambda d:d['businesses'][1]['claim_evidence'][0]['excerpts'][0].update(block_id='external-source')]
        for change in changes:
            draft = copy.deepcopy(self.draft)
            change(draft)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_draft(draft, self.packet)

    def test_block_disposition_requires_exact_once_and_no_false_unused_citations(self):
        changes = [lambda d:d['block_disposition'].pop(),
            lambda d:d['block_disposition'].append(copy.deepcopy(d['block_disposition'][0])),
            lambda d:d['block_disposition'][0].update(block_id='external-source'),
            lambda d:d['block_disposition'][3].update(disposition='not_used'),
            lambda d:d['block_disposition'][3].update(disposition='layout_noise')]
        for change in changes:
            draft = copy.deepcopy(self.draft)
            change(draft)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_draft(draft, self.packet)
        # An uncited block may be self-reported as used; this is NOT proof of semantic coverage.
        actual = validate_draft(self.draft, self.packet)
        self.assertEqual(actual.block_disposition[-1].disposition, 'used')

    async def test_unknown_relationship_and_gaps_survive_without_forced_revenue(self):
        relation = self.draft['relationships'][0]
        relation.update(basis='unknown', rationale='No membership claim established.', evidence_block_ids=[], excerpts=[])
        self.draft['unknowns'][0]['related_business_ids'] = ['beacon','services']
        result = await run.execute(self.prepare(), root=self.root, output=self.root/'run',
            observation_root=self.root/'observations', budget_limit_usd='1')
        candidate = json.loads((self.root/'run/business_map.json').read_text())
        self.assertEqual(candidate['relationships'][0]['basis'], 'unknown')
        self.assertEqual(candidate['unknowns'][0]['related_business_ids'], ['beacon','services'])
        self.assertEqual(result['counts']['unknowns'], 1)

    def test_prepared_scope_tampering_and_unsupported_compact_fail_before_call(self):
        for key, value in [('task_type','business_revenue'), ('extraction_scope',{}), ('schema_version','other')]:
            prepared = self.prepare()
            prepared['manifest'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'prepared_business_scope_changed'):
                run.verify_prepared(prepared)
        with self.assertRaisesRegex(ValueError, 'business_draft_requires_full_wire'):
            self.prepare(wire_mode='compact-v1')
        self.assertEqual(self.requests, [])

    def test_explicit_48k_changes_only_output_bound_and_reservation_with_adapter_hash(self):
        original = self.prepare(stream=True, max_tokens=16000)
        recovery = self.prepare(stream=True, max_tokens=48000)
        run.verify_prepared(recovery)
        before, after = json.loads(original['request']), json.loads(recovery['request'])
        self.assertEqual(after.pop('max_tokens'), 48000)
        self.assertEqual(before.pop('max_tokens'), 16000)
        self.assertEqual(after, before)
        self.assertEqual(original['schema'], recovery['schema'])
        self.assertEqual(recovery['manifest']['max_output_tokens_limit'], 48000)
        self.assertEqual(recovery['manifest']['implementation_sha256']['runtime/claude_messages.py'],
            run.digest((PROJECT/'src/uteki/agents/runtime/claude_messages.py').read_bytes()))
        self.assertEqual(Decimal(recovery['manifest']['reserved_estimated_usd']) -
            Decimal(original['manifest']['reserved_estimated_usd']), Decimal('0.320000'))
        with self.assertRaisesRegex(ValueError, 'require stream=true'):
            self.prepare(max_tokens=48000)
        with self.assertRaisesRegex(ValueError, '1..48000'):
            self.prepare(stream=True, max_tokens=48001)
        with self.assertRaisesRegex(ValueError, '1..24000'):
            self.prepare(model='claude-opus-5-5', stream=True, max_tokens=24001)
        run.verify_prepared(self.prepare(model='claude-opus-5-5', stream=True, max_tokens=24000))
        for target in ('native','manifest','implementation'):
            prepared = self.prepare(stream=True, max_tokens=48000)
            if target == 'native': prepared['native'].max_output_tokens_limit = 16000
            elif target == 'manifest': prepared['manifest']['max_output_tokens_limit'] = 16000
            else: prepared['manifest']['implementation_sha256']['runtime/claude_messages.py'] = '0'*64
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'prepared_(output_limit|implementation)_changed'):
                run.verify_prepared(prepared)
        self.assertEqual(self.requests, [])

    def test_business_cli_is_explicit_and_preflight_does_not_call_model(self):
        self.packet_path.write_text(json.dumps(self.packet))
        output = self.root/'preflight.json'
        args = ['business-only','--root',str(self.root),'--packet',str(self.packet_path),'--skill',str(self.skill),
            '--company-id',self.packet['company_id'],'--document-id',self.packet['document_id'],
            '--period-end',self.packet['period_end'],'--model','claude-sonnet-5-5','--effort','high',
            '--max-tokens','3000','--timeout-seconds','30','--contract-version',BUSINESS_DRAFT_VERSION,
            '--preflight-output',str(output)]
        with patch('sys.argv', args), patch('builtins.print'):
            cli.main()
        self.assertEqual(json.loads(output.read_text())['task_type'], 'business_map')
        self.assertNotIn('revenue_charts', json.loads(output.with_suffix('.output-schema.json').read_text())['properties'])
        self.assertEqual(self.requests, [])

    def test_existing_v2_full_system_and_compact_request_retain_frozen_bytes(self):
        frozen = PROJECT/'experiments/agent_design/2026-10-07-microsoft-business-revenue-v1/run-01'
        packet = json.loads((frozen/'source_packet.json').read_text())
        raw = (frozen/'request.json').read_bytes()
        old = json.loads(raw)
        prepared = run.prepare(root=PROJECT, packet_path=frozen/'source_packet.json',
            skill_path=frozen/'skill.md', model='claude-sonnet-5-5', effort='high',
            max_tokens=16000, timeout_seconds=600, stream=True,
            contract_version='business-revenue-draft-v2', wire_mode=product_wire.COMPACT,
            **{key:packet[key] for key in ('company_id','document_id','period_end')})
        self.assertEqual(prepared['request'], raw)
        self.assertEqual(prepared['schema'], json.loads((frozen/'output_schema.json').read_text()))
        # The frozen run used compact because this packet exceeds the full-mode
        # byte cap. Check its unchanged full system without relaxing that cap.
        self.assertEqual(run.system_prompt(prepared['skill'], json.dumps(prepared['schema'], ensure_ascii=False),
            'business-revenue-draft-v2', product_wire.FULL), old['system'].removesuffix(product_wire.INSTRUCTIONS))
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()

    async def test_preflight_reservation_matches_actual_native_bytes_and_meter(self):
        # Nested JSON, quotes, Unicode and newlines expose accidental re-encoding.
        self.skill.write_text('遵循 "原始引用"。\nKeep exact \\ paths and quoted "labels".')
        prepared = self.prepare()
        raw = prepared['request']
        pricing = prepared['manifest']['pricing_snapshot']
        expected = ((Decimal(len(raw) + 16000) * Decimal(pricing['input_per_million'])
                     + Decimal(prepared['kwargs']['model_settings'].max_tokens)
                     * Decimal(pricing['output_per_million'])) / Decimal(1000000))
        self.assertEqual(Decimal(prepared['manifest']['reserved_estimated_usd']), expected)
        self.assertIn(b'output_schema', raw)
        await run.execute(prepared, root=self.root, output=self.root/'byte-meter',
            observation_root=self.root/'observations', budget_limit_usd='1')
        start = json.loads(next((self.root/'byte-meter/model-calls').glob('*-start.json')).read_text())
        self.assertEqual(Decimal(start['reserved_usd']), expected)
        self.assertEqual(start['request_sha256'], run.digest(raw))
        self.assertEqual(start['request_bytes'], len(raw))
        self.assertEqual(self.requests[0].content, raw)
