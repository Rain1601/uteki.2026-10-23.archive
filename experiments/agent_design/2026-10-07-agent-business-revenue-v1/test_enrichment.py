"""Saved manual supplement boundaries; no network or model calls."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

from lxml import html

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('enrichment_fixtures', HERE / 'test_build_view.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
builder = fixtures.builder


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.map_path = self.fixture.run / 'business_map.json'
        self.business = builder.read_json(self.map_path)
        self.path = self.fixture.folder / 'supplement.json'
        quote = 'Synthetic Tools documentation </script><script>globalThis.ENRICHMENT_INJECTED=1</script>'
        self.data = {'schema_version': 'official-product-enrichment-v1',
            'binding': {'company_id': self.business['company_id'], 'document_id': self.business['document_id'],
                'period_end': self.business['metadata']['period_end'], 'business_map_sha256': builder.view.sha(self.map_path)},
            'provenance': {'method': 'codex_manual_web_review', 'model_api_calls': 0}, 'entities': [{
                'business_id': self.business['businesses'][1]['id'], 'gaps': [], 'official_links': [{
                    'id': 'doc', 'url': 'https://example.test/tools', 'final_url': 'https://example.test/tools',
                    'title': 'Synthetic documentation', 'role': 'documentation', 'publisher': 'Synthetic Orion',
                    'official_status': 'verified', 'availability': 'readable', 'checked_at': '2026-10-07T13:00:00+08:00',
                    'published_at': None, 'verification': {'publisher_basis': 'Synthetic first-party domain fixture',
                        'product_match': 'Exact synthetic Tools title', 'source_url': 'https://example.test/tools',
                        'locator': 'Overview paragraph', 'exact_quote': quote, 'quote_sha256': builder.text_hash(quote)}}],
                'to_watch': [{'id': 'watch-1', 'question': 'Did the documented support change?', 'why': 'Support affects use.',
                    'source_ids': ['doc'], 'observable_signal': 'A new dated documentation version.', 'status': 'suggested'}]}]}

    def validate(self, data=None):
        builder.write_json(self.path, self.data if data is None else data)
        return builder.safe_enrichment(self.path, self.business, self.map_path)

    def test_cross_scope_hash_and_unknown_node_rejected(self):
        for key in self.data['binding']:
            data = copy.deepcopy(self.data)
            data['binding'][key] = 'different'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'enrichment_map_binding_mismatch'):
                self.validate(data)
        self.data['entities'][0]['business_id'] = 'another-company-node'
        with self.assertRaisesRegex(ValueError, 'enrichment_unknown_or_duplicate_business_id'):
            self.validate()

    def test_unsafe_urls_unbound_quote_and_empty_verification_rejected(self):
        for url in ('http://example.test/tools', 'https://user:secret@example.test/tools', 'javascript:alert(1)', 'https://example.test\\@evil.test', 'https://example.test/\nheader'):
            for key in ('url', 'final_url', 'source_url'):
                data = copy.deepcopy(self.data)
                target = data['entities'][0]['official_links'][0]
                (target['verification'] if key == 'source_url' else target)[key] = url
                with self.subTest(url=url, key=key), self.assertRaises(ValueError):
                    self.validate(data)
        for key, value in [('quote_sha256', 'changed'), ('publisher_basis', '')]:
            data = copy.deepcopy(self.data)
            data['entities'][0]['official_links'][0]['verification'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(data)

    def test_unknown_source_or_active_monitoring_status_rejected(self):
        for key, value in [('source_ids', ['other-entity-link']), ('source_ids', ['doc', 'doc']), ('status', 'monitoring')]:
            data = copy.deepcopy(self.data)
            data['entities'][0]['to_watch'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'enrichment_watch_source_or_status_invalid'):
                self.validate(data)

    def test_unverified_or_unavailable_becomes_gap_without_official_link_or_watch_card(self):
        for key, value in [('official_status', 'unverified'), ('availability', 'unavailable')]:
            data = copy.deepcopy(self.data)
            data['entities'][0]['official_links'][0][key] = value
            with self.subTest(key=key):
                public = self.validate(data)['entities'][0]
                self.assertEqual(public['official_links'], [])
                self.assertEqual(public['to_watch'], [])
                self.assertEqual(len(public['gaps']), 2)

    def test_optional_display_safe_text_node_selection_and_unchanged_map(self):
        original = self.map_path.read_bytes()
        self.validate()
        self.fixture.args.enrichment = self.path
        builder.build(self.fixture.args)
        page = (self.fixture.args.output / 'index.html').read_text()
        self.assertNotIn('<script>globalThis.ENRICHMENT_INJECTED', page)
        self.assertIn('To Watch 为建议，未开启定时监控', page)
        self.assertEqual(self.map_path.read_bytes(), original)
        payload = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])
        self.assertEqual(len(payload['enrichment']['entities'][0]['official_links']), 1)
        js = self.fixture.folder / 'page.js'
        js.write_text(html.fromstring(page).xpath('//script')[0].text)
        harness = self.fixture.folder / 'enrichment.cjs'
        harness.write_text(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class E{constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.events={};this.style={setProperty(k,v){this[k]=v}};this.classList={toggle(){}};this._text='';}set textContent(v){this._text=String(v);this.children=[]}get textContent(){return this._text+this.children.map(c=>c.textContent).join('')}append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes;this._text=''}setAttribute(k,v){this.attributes[k]=v}addEventListener(k,v){this.events[k]=v}querySelector(){return null}}
const els={};const document={getElementById:id=>els[id]||(els[id]=new E('div')),createElement:t=>new E(t),createTextNode:t=>{const e=new E('text');e.textContent=t;return e},querySelectorAll:()=>[]};const context={document,URL,Intl,location:{href:'http://127.0.0.1/index.html'},history:{replaceState(){}}};vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);assert.equal(els['enrichment-summary'].hidden,false);assert(els['enrichment-checked'].textContent.includes('2026-10-07T13:00:00+08:00'));assert.equal(els['enrichment-nodes'].children.length,1);assert(!els['detail'].textContent.includes('To Watch'));els['enrichment-nodes'].children[0].events.click();assert(els['detail'].textContent.includes('To Watch'));assert(els['detail'].textContent.includes('Exact synthetic Tools title'));assert(els['detail'].textContent.includes('globalThis.ENRICHMENT_INJECTED'));assert(!context.ENRICHMENT_INJECTED);const walk=e=>[e,...e.children.flatMap(walk)];assert(walk(els['detail']).some(e=>e.href==='https://example.test/tools'));console.log('Enrichment static DOM passed');
''')
        subprocess.run(['node', '--check', str(js)], check=True, capture_output=True)
        subprocess.run(['node', str(harness), str(js)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
