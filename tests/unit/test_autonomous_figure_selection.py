"""Scripted role-local figure delivery boundaries; no model-quality assertions."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from uteki.agents.data_query.autonomous import AutonomousDataAgent, AutonomousDecision, Requirement
from uteki.agents.data_query.figure_selection import fully_consumed
from uteki.domain.research_data.figure_evidence import FigureReadRequest
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import ArtifactReadProgress, child_pointer, load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import make_scoped_dataset


class FigurePort:
    """Synthetic supplement layered over a real scoped query fixture."""
    def __init__(self, port, *, large=False, corrupt=None):
        self.port, self.large, self.corrupt = port, large, corrupt
        self.figure_bundle_ref = {'path': '/explicit/synthetic-figure-bundle', 'manifest_sha256': 'f'*64}

    def __getattr__(self, name):
        return getattr(self.port, name)

    def scoped(self, scope):
        return FigurePort(self.port.scoped(scope), large=self.large, corrupt=self.corrupt)

    def payload(self, source):
        source_record = self.port._source(source)
        figure = {'figure_id': 'diagram-one', 'source_snapshot_id': source,
            'company_id': source_record['company_id'], 'source_sha256': source_record.get('source_sha256', 'a'*64),
            'image_sha256': 'b'*64, 'transcription_sha256': 'c'*64,
            'figure_bundle_manifest_sha256': 'f'*64,
            'document_source_url': 'https://example.org/filing', 'source_url': 'https://example.org/figure.png',
            'original_image_path': '/explicit/synthetic-figure-bundle/figure.png',
            'original_document_path': '/explicit/synthetic-dataset/filing.html',
            'transcription': {'title': 'Original chart', 'texts': [{'id': 'text-one', 'text': 'Disclosed text',
                'box': [10, 10, 100, 100]}], 'notes': 'x'*11000 if self.large else 'No estimate.'},
            'document_context': [{'block_id': 'b1', 'text': 'Original introduction.'}],
            'source_blocks': [], 'locations': [{'block_id': 'image-one', 'dom_path': '/html/body/img'}],
            'status': 'ocr_grounded', 'bundle_status': 'prepared', 'independent_acceptance': 'pending',
            'coordinate_status': 'ocr_grounded'}
        return {**self.port._source_header(source_record), 'status': 'read', 'material_type': 'figure-evidence-v1',
            'figure': figure, 'figure_bundle_ref': deepcopy(self.figure_bundle_ref)}

    def list_figures(self):
        return {**self.port._header(), 'status': 'complete', 'figure_bundle_ref': deepcopy(self.figure_bundle_ref),
            'figures': [{'figure_id': 'diagram-one', 'source_snapshot_id': source,
                'company_id': self.port._source(source)['company_id']} for source in self.port.scope.source_snapshot_ids],
            'gaps': []}

    def read_figure(self, request):
        request = FigureReadRequest.model_validate(request)
        value = self.payload(request.source_snapshot_id)
        if self.corrupt == 'source':
            value['figure']['source_snapshot_id'] = 'foreign-report'
        if self.corrupt == 'bundle':
            value['figure_bundle_ref']['manifest_sha256'] = 'e'*64
        if self.corrupt == 'identity':
            value['figure']['figure_id'] = 'other-diagram'
        return value


def leaves(value, pointer):
    if isinstance(value, (dict, list)) and value:
        entries = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in entries:
            yield from leaves(child, child_pointer(pointer, key))
    else:
        yield pointer, value


class AutonomousFigureSelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        dataset = self.root/'dataset'; dataset.mkdir()
        make_scoped_dataset(dataset)
        self.base = QueryDataPort(dataset); self.addCleanup(self.base.close)
        self.scope = ExecutionScope(snapshot_id=self.base.snapshot_id, company_ids=('acme', 'other'),
            source_snapshot_ids=('acme-annual', 'other-annual'), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)

    @staticmethod
    def plan(*pairs):
        return {'action': 'plan', 'reason': 'Get source-bound original text and figure evidence.',
            'requirements': [{'requirement_id': rid, 'kind': 'source_evidence', 'source_id': source,
                'description': 'Deliver original source material with its figure supplement.'} for rid, source in pairs]}

    @staticmethod
    def body(rid='main', source='acme-annual'):
        return {'action': 'read_context', 'requirement_ids': [rid],
            'context': {'source_snapshot_id': source, 'block_id': 'b1'}}

    @staticmethod
    def select_body(packet):
        return {'action': 'select_evidence', 'requirement_ids': ['main'], 'reason': 'Retain original text.',
            'delivery': {'blocks': [{'context_id': packet['observation']['evidence_ids'][0], 'block_id': 'b1'}]}}

    @staticmethod
    def figure(rid='main', source='acme-annual'):
        return {'action': 'read_figure', 'requirement_ids': [rid],
            'figure_read': {'source_snapshot_id': source, 'figure_id': 'diagram-one'}}

    @staticmethod
    def select_figure(eid, rid='main'):
        return {'action': 'select_figures', 'requirement_ids': [rid], 'reason': 'Retain relevant original figure.',
            'figure_delivery': {'evidence_ids': [eid]}}

    def run_actions(self, actions, *, large=False, corrupt=None, supplement=True, name='run',
                    request_extra=None):
        planner = ScriptedPlanner(actions)
        port = FigurePort(self.base, large=large, corrupt=corrupt) if supplement else self.base
        output = self.root/name
        request = {'question': 'Retrieve each selected source disclosure and relevant original diagram.',
            'scope': self.scope.model_dump(mode='json'),
            **({'figure_bundle_ref': deepcopy(port.figure_bundle_ref)} if supplement else {})}
        request.update(request_extra or {})
        result = asyncio.run(AutonomousDataAgent(port, planner, purpose='analysis_evidence',
            limits={'max_steps': len(actions), 'max_packet_bytes': 160000, 'observation_bytes': 4000,
                    'page_items': 30}).run(request, output=output))
        return result, planner, output

    def test_explicit_read_select_and_sealed_chain_keep_figures_separate(self):
        def select(packet):
            self.assertIn('figure_catalog', packet)
            eid = packet['observation']['evidence_ids'][0]
            self.assertIn(eid, packet['delivered_figures'])
            return self.select_figure(eid)
        result, planner, output = self.run_actions([self.plan(('main', 'acme-annual')),
            self.body(), self.select_body, self.figure(), select, {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['delivery_schema_version'], 'selected-originals-v5')
        bundle = load_evidence_bundle(output)
        [selected] = bundle['selected_figures']; eid = selected['evidence_id']
        self.assertEqual(bundle['delivered_figures'], [eid])
        self.assertNotIn(eid, bundle['delivered_body'])
        self.assertEqual(result['coverage'][0]['selected_figures'], [selected])
        self.assertEqual(result['source_selection_contract'], bundle['source_selection_contract'])
        [figure] = [item for item in bundle['items'] if item['kind'] == 'figure']
        self.assertEqual(figure['value']['figure']['transcription']['title'], 'Original chart')
        # The consumer receipt follows an actual planner input, not a saved file.
        self.assertEqual(planner.packets[4]['observation']['result'], figure['value'])
        manifest = json.loads((output/'manifest.json').read_text())
        self.assertIn(figure['artifact']['path'], manifest['files'])
        catalog = planner.packets[0]['figure_catalog']['value']
        self.assertNotIn('transcription', json.dumps(catalog))

    def test_preview_and_partial_json_cannot_select_unconsumed_figure(self):
        def select(packet):
            self.assertTrue(packet['observation']['preview_truncated'])
            self.assertEqual(packet['delivered_figures'], [])
            return self.select_figure(packet['observation']['evidence_ids'][0])
        result, _, output = self.run_actions([self.plan(('main', 'acme-annual')),
            self.body(), self.select_body, self.figure(), select, {'action': 'finish'}], large=True)
        self.assertEqual(result['trace'][4]['status'], 'rejected')
        bundle = load_evidence_bundle(output)
        self.assertEqual(bundle['delivered_figures'], [])
        self.assertEqual(bundle['selected_figures'], [])
        self.assertEqual(result['figure_delivery_selection'], {})

    def test_complete_child_and_character_pages_establish_consumption(self):
        payload = FigurePort(self.base.scoped(self.scope), large=True).payload('acme-annual')['figure']
        retained = {}
        def remember(packet):
            retained.update(eid=packet['observation']['evidence_ids'][0],
                            artifact=packet['observation']['result_artifact']['artifact_id'])
            self.assertEqual(packet['delivered_figures'], [])
            return page_actions[0](packet)
        page_actions = []
        for pointer, value in leaves(payload, '/figure'):
            offsets = range(0, len(value), 1000) if isinstance(value, str) and value else [0]
            for offset in offsets:
                def read(packet, pointer=pointer, offset=offset):
                    return {'action': 'read_artifact', 'requirement_ids': ['main'], 'artifact_read': {
                        'artifact_id': retained['artifact'], 'pointer': pointer, 'offset': offset, 'limit': 1000}}
                page_actions.append(read)
        def select(packet):
            self.assertIn(retained['eid'], packet['delivered_figures'])
            return self.select_figure(retained['eid'])
        actions = [self.plan(('main', 'acme-annual')), self.body(), self.select_body, self.figure(),
                   remember, *page_actions[1:], select, {'action': 'finish'}]
        self.assertLessEqual(len(actions), 100)
        result, _, output = self.run_actions(actions, large=True)
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(load_evidence_bundle(output)['delivered_figures'], [retained['eid']])

    def test_bad_source_bundle_or_identity_cannot_store_evidence(self):
        for corrupt in ('source', 'bundle', 'identity'):
            with self.subTest(corrupt=corrupt):
                result, _, output = self.run_actions([self.plan(('main', 'acme-annual')), self.figure()],
                    corrupt=corrupt, name=corrupt)
                self.assertEqual(result['trace'][-1]['status'], 'rejected')
                self.assertEqual(load_evidence_bundle(output)['items'], [])

    def test_invalid_reselection_is_atomic_and_cross_requirement_is_rejected(self):
        captured = {}
        def first(packet):
            captured['eid'] = packet['observation']['evidence_ids'][0]
            return self.select_figure(captured['eid'])
        def foreign(packet):
            captured['prior'] = deepcopy(packet['figure_delivery_selection'])
            return self.select_figure(captured['eid'], 'other')
        def verify(packet):
            self.assertEqual(packet['figure_delivery_selection'], captured['prior'])
            self.assertEqual(packet['observation']['status'], 'rejected')
            return {'action': 'gap', 'requirement_ids': ['other'], 'reason': 'Independent source not retrieved.'}
        result, _, _ = self.run_actions([self.plan(('main', 'acme-annual'), ('other', 'other-annual')),
            self.body(), self.select_body, self.figure(), first, foreign, verify, {'action': 'finish'}])
        self.assertEqual(result['figure_delivery_selection'], captured['prior'])
        self.assertEqual(result['status'], 'partial')

    def test_v5_selected_figure_is_material_and_never_fabricates_text_delivery(self):
        def select(packet):
            return self.select_figure(packet['observation']['evidence_ids'][0])
        result, _, output = self.run_actions([self.plan(('main', 'acme-annual')), self.figure(), select,
                                             {'action': 'finish'}])
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['coverage'][0]['program_check'], 'source_material_delivered')
        self.assertEqual(load_evidence_bundle(output)['delivered_body'], {})
        no_selection, _, output = self.run_actions([self.plan(('main', 'acme-annual')),
            self.body(), self.select_body, self.figure(), {'action': 'finish'}], name='unselected')
        self.assertEqual(no_selection['status'], 'evidence_ready')
        self.assertEqual(load_evidence_bundle(output)['selected_figures'], [])

    def test_no_supplement_preserves_v4_and_unavailable_read_is_explicit(self):
        result, _, output = self.run_actions([self.plan(('main', 'acme-annual')),
            self.body(), self.select_body, {'action': 'finish'}], supplement=False)
        self.assertEqual(result['delivery_schema_version'], 'selected-originals-v4')
        self.assertNotIn('source_selection_contract', result)
        self.assertNotIn('delivered_figures', load_evidence_bundle(output))
        failed, _, _ = self.run_actions([self.plan(('main', 'acme-annual')), self.figure()],
                                       supplement=False, name='no-bundle')
        self.assertEqual(failed['trace'][-1]['status'], 'rejected')

    def test_caller_must_explicitly_pin_the_same_supplement(self):
        for ref in (None, {'path': '/other/bundle', 'manifest_sha256': 'f'*64},
                    {'path': '/explicit/synthetic-figure-bundle', 'manifest_sha256': 'e'*64}):
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, 'Caller figure supplement differs'):
                self.run_actions([self.plan(('main', 'acme-annual'))], request_extra={'figure_bundle_ref': ref})
        ref = {'path': '/explicit/other/../synthetic-figure-bundle', 'manifest_sha256': 'f'*64}
        result, _, _ = self.run_actions([self.plan(('main', 'acme-annual'))],
                                       request_extra={'figure_bundle_ref': ref})
        self.assertEqual(result['request']['figure_bundle_ref'], result['figure_bundle_ref'])

    def test_figure_material_cannot_complete_a_chapter_or_numeric_requirement(self):
        from tests.unit.test_scoped_query_service import year
        def select(packet):
            return self.select_figure(packet['observation']['evidence_ids'][0])
        for requirement in (
            {'requirement_id': 'typed', 'kind': 'read_node', 'source_id': 'acme-annual',
             'node_id': 'business', 'description': 'Read complete business chapter.'},
            {'requirement_id': 'typed', 'kind': 'query', 'description': 'Retrieve original revenue in 2031.',
             'query': {'records': [{'entity_id': 'acme', 'metric_id': 'revenue', 'period': year(2031)}]}}):
            with self.subTest(kind=requirement['kind']):
                initial = self.plan(('main', 'acme-annual'))
                initial['requirements'].append(requirement)
                result, _, output = self.run_actions([initial, self.figure(), select, {'action': 'finish'}],
                    name=requirement['kind'], request_extra={
                        'question': 'Read the complete business chapter, retrieve Acme revenue in 2031, and inspect the figure.'})
                self.assertEqual(result['trace'][-1]['status'], 'rejected')
                typed = next(row for row in result['coverage'] if row['requirement_id'] == 'typed')
                self.assertNotIn(typed['program_check'], {'body_complete', 'satisfied'})
                self.assertEqual(load_evidence_bundle(output)['delivered_body'], {})

    def test_saved_last_read_without_next_role_input_never_counts_as_consumed(self):
        result, _, output = self.run_actions([self.plan(('main', 'acme-annual')), self.figure()])
        bundle = load_evidence_bundle(output)
        self.assertTrue(any(item['kind'] == 'figure' for item in bundle['items']))
        self.assertEqual(bundle['delivered_figures'], [])
        self.assertEqual(bundle['selected_figures'], [])
        self.assertEqual(result['coverage'][0]['program_check'], 'source_material_not_delivered')

    def test_worker_consumption_and_ids_do_not_establish_parent_consumption(self):
        def worker_select(packet):
            return self.select_figure(packet['observation']['evidence_ids'][0])
        port = FigurePort(self.base)
        worker = AutonomousDataAgent(port, ScriptedPlanner([self.figure(), worker_select, {'action': 'finish'}]),
            purpose='analysis_evidence', limits={'max_steps': 3, 'observation_bytes': 4000})
        request = {'question': 'Retrieve the relevant source diagram.', 'scope': self.scope.model_dump(mode='json'),
            'figure_bundle_ref': deepcopy(port.figure_bundle_ref)}
        requirement = Requirement.model_validate(self.plan(('main', 'acme-annual'))['requirements'][0])
        child = asyncio.run(worker._run(request, output=self.root/'worker', fixed_requirements=(requirement,)))
        self.assertEqual(child['role'], 'worker')
        self.assertEqual(child['status'], 'evidence_ready')
        eid = child['figure_delivery_selection']['main'][0]['evidence_id']
        parent, _, output = self.run_actions([self.plan(('main', 'acme-annual')),
            self.select_figure(eid), {'action': 'gap', 'requirement_ids': ['main'],
                                    'reason': 'Parent has not read the figure.'}, {'action': 'finish'}])
        self.assertEqual(parent['trace'][1]['status'], 'rejected')
        self.assertEqual(load_evidence_bundle(output)['delivered_figures'], [])
        self.assertEqual(parent['figure_delivery_selection'], {})

    def test_action_payloads_remain_conditional(self):
        for value in ({'action': 'read_figure', 'requirement_ids': ['main']},
                      {'action': 'select_figures', 'figure_delivery': {'evidence_ids': ['ev-one']}},
                      {'action': 'select_figures', 'requirement_ids': ['main'], 'reason': 'Select',
                       'figure_delivery': {'evidence_ids': []}},
                      {'action': 'finish', 'figure_read': {'source_snapshot_id': 'source', 'figure_id': 'figure'}}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AutonomousDecision.model_validate(value)

    def test_partial_leaf_marks_require_context_and_provenance_too(self):
        progress = ArtifactReadProgress()
        value = {'transcription': {'text': 'ABC'}, 'document_context': ['Context'], 'provenance': 'Source'}
        mark = progress.preview_mark('figure', value, {'transcription': {'text': 'ABC'}})
        progress.apply(mark)
        self.assertFalse(fully_consumed(progress, 'figure', value))
        progress.apply(progress.preview_mark('figure', value, value))
        self.assertTrue(fully_consumed(progress, 'figure', value))


if __name__ == '__main__':
    unittest.main()
