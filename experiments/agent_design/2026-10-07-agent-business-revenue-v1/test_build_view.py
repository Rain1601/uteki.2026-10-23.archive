"""Offline synthetic source -> product materializer -> review-page checks.

No observations, network, model calls, existing company candidates, or browser.
Temporary files are removed after each test.
"""
from __future__ import annotations

from argparse import Namespace
import copy
import html
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from lxml import html as lhtml
from uteki.agents.business_map.product_contract import validate_draft
from uteki.agents.business_map.product_run import materialize, verify_packet
from tests.unit.test_business_revenue_contract import fixture

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('agent_product_view', HERE / 'build_view.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PageTests(unittest.TestCase):
    def test_new_contract_is_not_silently_rendered_as_legacy_confirmed_edges(self):
        path = self.run / 'business_map.json'
        data = builder.read_json(path)
        data['schema_version'] = 'business-map-v0.2'
        data['relationships'][0]['basis'] = 'unknown'
        builder.write_json(path, data)
        with self.assertRaisesRegex(ValueError, 'v2_display_requires_basis_aware_renderer'):
            builder.validate_agent(path, self.run/'source_packet.json', self.run/'skill.md')
        with self.assertRaisesRegex(ValueError, 'v2_display_requires_basis_aware_renderer'):
            builder.view.presentation_edges(data)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.agent-view-test-', dir=ROOT)
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.run = self.folder / 'run'
        self.run.mkdir()
        draft, packet = fixture(company='synthetic-orion', period='2022-09-30', label='FY2022', adjusted=True)
        # Only source text and selected IDs are fixture inputs. Monetary values
        # in artifacts come from the same production source-cell materializer.
        body = ''.join(f'<p id="{b["id"]}">{html.escape(b["text"])}</p>' for b in packet['blocks'][:-1])
        body += '<table id="table-block"><tr><td id="prior-header" colspan="3">prior period</td><td id="header" colspan="3">FY2022</td></tr>'
        for label, cid, amount in [('Tools', 'a', '80'), ('Services', 'b', '30'), ('Adjustment', 'adjustment', '(10)'), ('Total', 'total', '100'), ('Gross subtotal', 'subtotal', '110')]:
            body += f'<tr><td colspan="3">{label}</td><td></td><td id="{cid}">{amount}</td><td></td></tr>'
        raw = ('<html><body>' + body + '</table></body></html>').encode()
        source = self.folder / 'source.html'
        source.write_bytes(raw)
        dom = lhtml.fromstring(raw)
        tree = dom.getroottree()
        norm = lambda n: ' '.join(''.join(n.itertext()).split())
        for i, block in enumerate(packet['blocks'], 1):
            el = dom.get_element_by_id(block['id'])
            block.update(text=norm(el), text_sha256=builder.text_hash(norm(el)), source_dom_path=tree.getpath(el), ordinal=i)
        table = packet['tables'][0]
        el = dom.get_element_by_id('table-block')
        table['source_dom_path'] = tree.getpath(el)
        table['cells'] = []
        for ri, row in enumerate(el):
            ci = 0
            for cell in row:
                span = int(cell.get('colspan', '1'))
                table['cells'].append(dict(id=cell.get('id') or f'blank-{ri}-{ci}', text=norm(cell), text_sha256=builder.text_hash(norm(cell)),
                    source_dom_path=tree.getpath(cell), row_index=ri, column_index=ci, rowspan=1, colspan=span))
                ci += span
        packet.update(source_local_path=str(source.relative_to(ROOT)), source_sha256=builder.view.sha(source), form_type='synthetic')
        verify_packet(packet, ROOT, **{k: packet[k] for k in ('company_id', 'document_id', 'period_end')})
        self.packet = packet
        builder.write_json(self.run / 'source_packet.json', packet)
        (self.run / 'skill.md').write_text('Synthetic offline Skill fixture. Preserve source evidence.\n')
        self.manifest = dict(source_packet_sha256=builder.view.sha(self.run / 'source_packet.json'),
            skill_sha256=builder.view.sha(self.run / 'skill.md'), model='fake/requested-claude')
        draft['businesses'][1]['name'] = 'Tools </script><script>globalThis.INJECTED=1</script>'
        self.draft = draft
        validated = validate_draft(draft, packet)
        materialize(validated, packet, root=ROOT, output=self.run, manifest=self.manifest, trace_id='offline-fixture')
        self.result = dict(**self.manifest, trace_id='offline-fixture', status='candidate', validation='passed', provider='fake-offline',
            costs=dict(requests=1, unknown_cost_requests=0, known_estimated_usd='0.000120', records=[dict(
                actual_upstream_model='fake/returned-claude', reasoning_effort='high', stop_reason='end_turn',
                raw_usage=dict(input_tokens=10, output_tokens=4, cache_read_input_tokens=0), elapsed_seconds=0.2)]))
        self.refresh_receipt()
        # An independently scoped, synthetic reference fixture, never loaded
        # from or used as model output for a real-company candidate.
        self.ref_map = self.folder / 'reference-business.json'
        self.ref_revenue = self.folder / 'reference-revenue.json'
        self.freeze_reference()
        self.args = Namespace(run_dir=self.run, reference_map=self.ref_map, reference_revenue=self.ref_revenue,
            source_packet=None, skill=None, output=self.folder / 'page', reference_page=None, with_svg=False)

    def refresh_receipt(self):
        self.result['artifacts_sha256'] = {name: builder.view.sha(self.run / name) for name in ('business_map.json', 'revenue.json', 'evidence.html')}
        builder.write_json(self.run / 'result.json', self.result)

    def freeze_reference(self):
        evidence = self.folder / 'reference-evidence.html'
        shutil.copyfile(self.run / 'evidence.html', evidence)
        path = str(evidence.relative_to(ROOT))
        ref = builder.read_json(self.run / 'business_map.json')
        ref['metadata']['extraction_method'] = 'codex_source_review'
        for e in ref['evidence'] + list(ref['metadata']['evidence_locators'].values()):
            e['local_path'] = path
        builder.write_json(self.ref_map, ref)
        revenue = builder.read_json(self.run / 'revenue.json')
        for e in revenue['evidence']:
            e['local_path'] = path
        builder.write_json(self.ref_revenue, revenue)

    def build(self):
        builder.build(self.args)
        return (self.args.output / 'index.html').read_text()

    def attach_review(self):
        data = builder.read_json(self.run / 'business_map.json')
        meta = data['metadata']
        binding = {key: data[key] for key in ('company_id', 'document_id')}
        binding.update({key: meta[key] for key in ('period_end', 'trace_id', 'source_sha256', 'source_packet_sha256')})
        binding.update(business_map_sha256=builder.view.sha(self.run / 'business_map.json'),
                       revenue_sha256=builder.view.sha(self.run / 'revenue.json'))
        self.review = dict(verdict='synthetic_review', summary='Synthetic content review </script><script>globalThis.REVIEW_INJECTED=1</script>',
            binding=binding, reference_binding=dict(business_map_sha256=builder.view.sha(self.ref_map),
                revenue_sha256=builder.view.sha(self.ref_revenue)),
            review_method='Offline synthetic review fixture; no model or semantic accuracy claim.',
            checks=[dict(id='CHECK-01', label='Grounded products', status='needs_improvement', reference='Reference <product>',
                actual='Selected product', note='Review note <script>globalThis.NOTE_INJECTED=1</script>', source_block_ids=['business-source'])],
            limitations=['Only a synthetic fixture.'], arbitrary_secret_field='DO_NOT_PUBLISH')
        self.args.review = self.folder / 'review.json'
        builder.write_json(self.args.review, self.review)

    def test_review_rejects_each_mismatched_run_binding_and_changed_reference(self):
        self.attach_review()
        original = copy.deepcopy(self.review)
        for key in original['binding']:
            with self.subTest(key=key):
                review = copy.deepcopy(original)
                review['binding'][key] = 'different-run-or-output'
                builder.write_json(self.args.review, review)
                with self.assertRaisesRegex(ValueError, 'review_run_binding_mismatch'):
                    self.build()
        for key in original['reference_binding']:
            with self.subTest(reference=key):
                review = copy.deepcopy(original)
                review['reference_binding'][key] = 'different-reference'
                builder.write_json(self.args.review, review)
                with self.assertRaisesRegex(ValueError, 'review_reference_binding_mismatch'):
                    self.build()

    def test_review_rejects_unknown_evidence_and_status(self):
        self.attach_review()
        original = copy.deepcopy(self.review)
        for mutation, message in [(dict(source_block_ids=['other-company-block']), 'review_source_block_outside_packet'),
                                  (dict(status='approved'), 'review_check_status_invalid'),
                                  (dict(note=''), 'review_text_required'),
                                  (dict(source_block_ids=['business-source', 'business-source']), 'review_source_block_duplicate')]:
            with self.subTest(message=message):
                review = copy.deepcopy(original)
                review['checks'][0].update(mutation)
                builder.write_json(self.args.review, review)
                with self.assertRaisesRegex(ValueError, message):
                    self.build()

    def test_review_payload_keeps_exact_source_and_whitelisted_text(self):
        self.attach_review()
        page = self.build()
        self.assertNotIn('<script>globalThis.REVIEW_INJECTED', page)
        self.assertNotIn('<script>globalThis.NOTE_INJECTED', page)
        self.assertNotIn('DO_NOT_PUBLISH', page)
        payload = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])
        review = payload['review']
        self.assertEqual(review['summary'], self.review['summary'])
        self.assertEqual(review['source_blocks'][0]['text'], next(b['text'] for b in self.packet['blocks'] if b['id'] == 'business-source'))
        self.assertEqual(review['checks'][0]['status'], 'needs_improvement')
        report = builder.read_json(self.args.output / 'verification.json')
        self.assertEqual(report['fingerprints']['review'], builder.view.sha(self.args.review))

    def test_reference_is_optional_but_a_half_pair_or_dangling_page_is_rejected(self):
        self.args.reference_map = None
        with self.assertRaisesRegex(ValueError, 'reference_map_and_revenue_required_together'):
            self.build()
        self.args.reference_map, self.args.reference_revenue = self.ref_map, None
        with self.assertRaisesRegex(ValueError, 'reference_map_and_revenue_required_together'):
            self.build()
        self.args.reference_map = None
        page = self.build()
        payload = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])
        self.assertIsNone(payload['reference'])
        self.assertIsNone(payload['links']['reference_map'])
        self.assertIsNone(payload['links']['reference_revenue'])
        self.assertEqual(payload['revenue']['charts'][0]['total'], 100)
        dom = lhtml.fromstring(page)
        self.assertFalse(dom.xpath('//*[@id="comparison" or @id="reference-links"]'))
        self.assertNotIn('Codex 参考', ''.join(dom.xpath('//th/text()')))
        verification = builder.read_json(self.args.output / 'verification.json')
        self.assertFalse(verification['reference_attached'])
        self.assertNotIn('reference_map', verification['fingerprints'])
        self.args.reference_page = self.ref_map
        with self.assertRaisesRegex(ValueError, 'reference_page_requires_reference'):
            self.build()

    def test_review_without_reference_only_requires_the_run_and_source_binding(self):
        self.attach_review()
        self.args.reference_map = self.args.reference_revenue = None
        with self.assertRaisesRegex(ValueError, 'review_reference_without_reference'):
            self.build()
        del self.review['reference_binding']
        del self.review['checks'][0]['reference']
        builder.write_json(self.args.review, self.review)
        page = self.build()
        review = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])['review']
        self.assertNotIn('reference_binding', review)
        self.assertNotIn('reference', review['checks'][0])
        self.assertEqual(review['checks'][0]['source_block_ids'], ['business-source'])
        self.review['checks'][0]['source_block_ids'] = ['different-company-block']
        builder.write_json(self.args.review, self.review)
        with self.assertRaisesRegex(ValueError, 'review_source_block_outside_packet'):
            self.build()

    def test_pdf_provenance_links_original_pdf_and_keeps_derived_html_hash_distinct(self):
        self.args.reference_map = self.args.reference_revenue = None
        pdf = self.folder / 'original.pdf'
        pdf.write_bytes(b'%PDF-1.4\nSynthetic provenance fixture, not financial input.\n')
        self.packet.update(source_kind='pdf_derived_selected_html',
                           original_source_path=str(pdf.relative_to(ROOT)),
                           original_source_sha256=builder.view.sha(pdf))
        builder.write_json(self.run / 'source_packet.json', self.packet)
        self.manifest['source_packet_sha256'] = builder.view.sha(self.run / 'source_packet.json')
        self.result['source_packet_sha256'] = self.manifest['source_packet_sha256']
        materialize(validate_draft(self.draft, self.packet), self.packet, root=ROOT, output=self.run,
                    manifest=self.manifest, trace_id='offline-fixture')
        self.refresh_receipt()
        page = self.build()
        payload = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])
        self.assertEqual(payload['provenance']['original_source_sha256'], builder.view.sha(pdf))
        self.assertEqual(payload['provenance']['source_sha256'], self.packet['source_sha256'])
        self.assertNotEqual(payload['provenance']['source_sha256'], payload['provenance']['original_source_sha256'])
        self.assertEqual(payload['links']['original_source'], builder.view.link(pdf, self.args.output))
        self.assertIn('不是 SEC 原生 HTML', payload['provenance']['description'])
        self.assertEqual(builder.read_json(self.args.output / 'verification.json')['fingerprints']['original_pdf'], builder.view.sha(pdf))
        pdf.write_bytes(pdf.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'original_pdf_hash_mismatch'):
            self.build()

    def test_pdf_provenance_missing_original_or_wrong_format_is_rejected(self):
        packet = {**self.packet, 'source_kind': 'pdf_derived_selected_html'}
        with self.assertRaisesRegex(ValueError, 'original_pdf_provenance_required'):
            builder.source_provenance(packet)
        packet.update(original_source_path=packet['source_local_path'], original_source_sha256=packet['source_sha256'])
        with self.assertRaisesRegex(ValueError, 'original_pdf_required'):
            builder.source_provenance(packet)

    def test_pre_svg_page_preserves_negative_adjustment_subtotal_and_safe_text(self):
        page = self.build()
        self.assertNotIn('<script>globalThis.INJECTED', page)
        self.assertIn('\\u003c/script>', page)
        self.assertIn('SVG 尚未提供', page)
        self.assertTrue((self.args.output / 'assets/synthetic-orion.mmd').is_file())
        report = builder.read_json(self.args.output / 'verification.json')
        self.assertEqual((report['nodes'], report['relationships'], report['revenue_charts']), (2, 1, 1))
        data = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])
        self.assertEqual(data['revenue']['charts'][0]['total'], 100)
        self.assertEqual(data['revenue']['charts'][0]['adjustments'][0]['value'], -10)
        self.assertEqual(data['revenue']['charts'][0]['reported_subtotals'][0]['value'], 110)
        self.assertEqual(data['run']['returned_model'], 'fake/returned-claude')
        self.assertEqual(data['map']['metadata']['extraction_method'], 'system_agent')

    def test_real_source_amount_and_chart_subtotal_are_checked(self):
        original = builder.read_json(self.run / 'revenue.json')
        for mutator, error in [(lambda d: d['charts'][0]['parts'][0].update(value=70), 'revenue_amount_differs'),
                               (lambda d: d['charts'][0]['reported_subtotals'][0].update(component_ids=['tools-revenue']), 'chart_subtotal_does_not_reconcile')]:
            with self.subTest(error=error):
                data = copy.deepcopy(original)
                mutator(data)
                builder.write_json(self.run / 'revenue.json', data)
                self.refresh_receipt()
                with self.assertRaisesRegex(ValueError, error):
                    self.build()

    def test_missing_anchor_and_changed_dom_hash_rejected(self):
        evidence = self.run / 'evidence.html'
        original = evidence.read_text()
        evidence.write_text(original.replace('id="business-source"', 'id="moved"'))
        self.refresh_receipt()
        with self.assertRaisesRegex(ValueError, 'evidence_anchor_quote_mismatch'):
            self.build()
        evidence.write_text(original)
        self.refresh_receipt()
        source = ROOT / self.packet['source_local_path']
        source.write_bytes(source.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'):
            self.build()

    def test_reported_subtotal_can_include_signed_adjustment(self):
        source = ROOT / self.packet['source_local_path']
        source.write_text(source.read_text().replace('<td id="subtotal">110</td>', '<td id="subtotal">70</td>'))
        dom = lhtml.fromstring(source.read_bytes())
        tree = dom.getroottree()
        nodes = {tree.getpath(n): n for n in dom.iter()}
        packet = self.packet
        packet['source_sha256'] = builder.view.sha(source)
        for item in packet['blocks'] + packet['tables'][0]['cells']:
            item['text'] = ' '.join(''.join(nodes[item['source_dom_path']].itertext()).split())
            item['text_sha256'] = builder.text_hash(item['text'])
        builder.write_json(self.run / 'source_packet.json', packet)
        self.manifest['source_packet_sha256'] = builder.view.sha(self.run / 'source_packet.json')
        self.result['source_packet_sha256'] = self.manifest['source_packet_sha256']
        self.draft['revenue_charts'][0]['reported_subtotals'][0]['component_ids'] = ['tools-revenue', 'revenue-adjustment']
        materialize(validate_draft(self.draft, packet), packet, root=ROOT, output=self.run,
                    manifest=self.manifest, trace_id='offline-fixture')
        self.freeze_reference()
        self.refresh_receipt()
        self.build()

    def test_failed_run_unbound_outputs_and_wrong_skill_rejected(self):
        self.result['status'] = 'failed'
        self.refresh_receipt()
        with self.assertRaisesRegex(ValueError, 'completed_candidate_run_required'):
            self.build()
        self.result['status'] = 'candidate'
        self.refresh_receipt()
        path = self.run / 'revenue.json'
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'run_output_fingerprint_mismatch'):
            self.build()
        self.refresh_receipt()
        (self.run / 'skill.md').write_text('Changed Skill')
        with self.assertRaisesRegex(ValueError, 'agent_input_fingerprint_mismatch'):
            self.build()

    def test_unknown_cost_is_not_presented_as_zero(self):
        self.result['costs']['unknown_cost_requests'] = 1
        self.result['costs']['known_estimated_usd'] = '0'
        self.refresh_receipt()
        self.build()
        summary = builder.safe_run_summary(self.result, builder.read_json(self.run / 'business_map.json')['metadata'])
        self.assertIsNone(summary['estimated_usd'])
        self.assertEqual(summary['unknown_cost_requests'], 1)

    def test_empty_revenue_keeps_business_and_explicit_gap_with_source_checks(self):
        self.draft['revenue_charts'] = []
        materialize(validate_draft(self.draft, self.packet), self.packet, root=ROOT, output=self.run,
                    manifest=self.manifest, trace_id='offline-fixture')
        self.refresh_receipt()
        page = self.build()
        self.assertIn('未生成完整收入构成，请查看缺口', page)
        report = builder.read_json(self.args.output / 'verification.json')
        self.assertEqual((report['nodes'], report['revenue_charts']), (2, 0))
        path = self.run / 'revenue.json'
        invalid = builder.read_json(path)
        invalid['period_end'] = '2099-01-01'
        builder.write_json(path, invalid)
        self.refresh_receipt()
        with self.assertRaisesRegex(ValueError, 'empty_revenue_scope_mismatch'):
            self.build()

    def test_svg_stage_requires_matching_node_labels_and_rejects_script(self):
        self.build()
        data = builder.read_json(self.run / 'business_map.json')
        _, ids = builder.view.mermaid(data)
        svg = ET.Element('svg', xmlns='http://www.w3.org/2000/svg', viewBox='0 0 200 80')
        for i, node in enumerate(data['businesses']):
            group = ET.SubElement(svg, 'g', {'class': 'node', 'id': f'flowchart-{ids[node["id"]]}-{i}'})
            ET.SubElement(group, 'text').text = node['name']
        for i, edge in enumerate(builder.view.presentation_edges(data)):
            eid = f'L_{ids[edge["source"]]}_{ids[edge["target"]]}_{i}'
            ET.SubElement(svg, 'path', {'class': 'flowchart-link', 'id': eid})
            group = ET.SubElement(svg, 'g', {'class': 'label', 'data-id': eid})
            ET.SubElement(group, 'text').text = edge['label']
        svg_path = self.args.output / 'assets/synthetic-orion.svg'
        svg_path.write_text(ET.tostring(svg, encoding='unicode'))
        self.args.with_svg = True
        self.assertIn('data-node-id="tools"', self.build())
        edge = next(e for e in svg if e.tag == 'path')
        edge.set('id', 'L_N001_N000_0')
        svg_path.write_text(ET.tostring(svg, encoding='unicode'))
        with self.assertRaisesRegex(ValueError, 'unrecognized_svg_edge|svg_relationship_mismatch'):
            self.build()
        edge.set('id', 'L_N000_N001_0')
        ET.SubElement(svg, 'script').text = 'bad()'
        svg_path.write_text(ET.tostring(svg, encoding='unicode'))
        with self.assertRaisesRegex(ValueError, 'active_svg_not_allowed'):
            self.build()

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for script checks')
    def test_script_syntax_and_revenue_dom_without_browser(self):
        self.attach_review()
        page = self.build()
        script = lhtml.fromstring(page).xpath('//script')[0].text
        js = self.folder / 'page.js'
        js.write_text(script)
        subprocess.run(['node', '--check', str(js)], check=True, capture_output=True)
        # A minimal DOM harness exercises tab state, signed bars and displayed
        # table rows. It is not a browser/visual/trackpad acceptance check.
        harness = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class E{constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.events={};this.style={setProperty(k,v){this[k]=v}};this.classList={toggle(){}};this._text='';}set textContent(v){this._text=String(v);this.children=[]}get textContent(){return this._text+this.children.map(c=>c.textContent).join('')}append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes;this._text=''}setAttribute(k,v){this.attributes[k]=v}addEventListener(k,v){this.events[k]=v}querySelector(){return null}}
const els={};const document={getElementById:id=>els[id]||(els[id]=new E('div')),createElement:t=>new E(t),createTextNode:t=>{const e=new E('text');e.textContent=t;return e},querySelectorAll:()=>[]};
const context={document,URL,Intl,location:{href:'http://127.0.0.1/index.html'},history:{replaceState(){}}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
assert(!context.INJECTED);assert(!context.REVIEW_INJECTED);assert(!context.NOTE_INJECTED);assert.equal(els['fit'].disabled,true);assert.equal(els['revenue-panel'].hidden,true);els['revenue-tab'].events.click();assert.equal(els['revenue-panel'].hidden,false);assert.equal(els['business-panel'].hidden,true);
assert.equal(els['review-details'].hidden,false);assert(els['review-summary'].textContent.includes('<script>globalThis.REVIEW_INJECTED=1</script>'));assert.equal(els['review-checks'].children.length,1);assert(els['review-checks'].textContent.includes('Reference <product>'));assert(els['review-checks'].textContent.includes('待改进'));assert(els['review-checks'].textContent.includes('business-source'));assert(els['review-method'].textContent.includes('synthetic review fixture'));
const walk=e=>[e,...e.children.flatMap(walk)];const all=walk(els['revenue-panel']);const body=all.find(e=>e.tag==='tbody');assert.equal(body.children.length,3);assert(body.textContent.includes('-10'));assert(!body.textContent.includes('110'));assert.equal(all.filter(e=>e.tag==='p'&&e.textContent.includes('小计 110')).length,1);const negative=all.filter(e=>e.className==='bar-fill'&&e.style.background==='#ac715f');assert.equal(negative.length,1);assert.equal(negative[0].style.left,'0%');assert(Number.parseFloat(negative[0].style.width)>0);console.log('DOM fixture passed');
'''
        harness_path = self.folder / 'check.cjs'
        harness_path.write_text(harness)
        subprocess.run(['node', str(harness_path), str(js)], check=True, capture_output=True)
        # No-reference pages must execute without ever querying removed
        # comparison containers or manufacturing a reference review column.
        self.args.reference_map = self.args.reference_revenue = None
        del self.review['reference_binding']
        del self.review['checks'][0]['reference']
        builder.write_json(self.args.review, self.review)
        page = self.build()
        js.write_text(lhtml.fromstring(page).xpath('//script')[0].text)
        no_reference_harness = harness.replace(
            "assert(els['review-checks'].textContent.includes('Reference <product>'));",
            "assert(!els['review-checks'].textContent.includes('Reference <product>'));"
            "assert.equal(els['review-checks'].children[0].children.length,3);"
            "assert(!els['comparison']);assert(!els['reference-links']);")
        harness_path.write_text(no_reference_harness)
        subprocess.run(['node', str(harness_path), str(js)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
