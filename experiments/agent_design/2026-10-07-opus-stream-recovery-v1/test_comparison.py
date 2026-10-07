"""Synthetic offline checks for recovery-view boundaries; no model calls."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lxml import html

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('recovery_view', HERE / 'build_comparison.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='recovery-view-fixture-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'source.html').write_text('<html><body><p>Independent synthetic source.</p></body></html>')
        text = 'Independent synthetic source.'
        self.packet = {'company_id': 'synthetic-river', 'document_id': 'river-report', 'period_end': '2022-04-30',
            'source_local_path': 'source.html', 'source_encoding': 'utf-8', 'source_url': 'https://example.test/filing',
            'source_sha256': builder.sha(self.root / 'source.html'), 'tables': [],
            'blocks': [{'id': 'block-one', 'text': text, 'source_dom_path': '/html/body/p',
                        'text_sha256': builder.hashlib.sha256(text.encode()).hexdigest()}]}
        self.runs = {key: self.root / key for key in ('A', 'B')}
        self.pages = {key: self.root / (key + '-page') / 'index.html' for key in ('A', 'B')}
        self.results, self.requests = {}, {}
        for key in ('A', 'B'):
            run = self.runs[key]
            run.mkdir()
            write(run / 'source_packet.json', self.packet)
            (run / 'skill.md').write_text('Synthetic Skill v0.3 fixture.\n')
            write(run / 'output_schema.json', {'type': 'object'})
            model = 'claude-sonnet-5-5' if key == 'A' else 'claude-opus-5-5'
            request = self.requests[key] = {'model': model, 'stream': key == 'B', 'system': 'Synthetic prompt',
                'messages': [{'role': 'user', 'content': text}], 'max_tokens': 16000,
                'thinking': {'type': 'adaptive'}, 'output_config': {'effort': 'high'}}
            write(run / 'request.json', request)
            write(run / 'configuration.json', {'fields': {field: {'value': value} for field, value in
                  {'stream': key == 'B', 'timeout_seconds': 300 if key == 'A' else 600, 'max_retries': 0}.items()}})
            for name in ('business_map.json', 'revenue.json'):
                write(run / name, {'synthetic': True, 'id': key})
            (run / 'evidence.html').write_text('<p id="e">Synthetic evidence fixture.</p>')
            request_sha = builder.sha(run / 'request.json')
            result = self.results[key] = {field: self.packet[field] for field in ('company_id', 'document_id', 'period_end', 'source_sha256')}
            result.update(source_packet_sha256=builder.sha(run / 'source_packet.json'), skill_sha256=builder.sha(run / 'skill.md'),
                output_schema_sha256=builder.hashlib.sha256(json.dumps({'type': 'object'}, ensure_ascii=False).encode()).hexdigest(),
                model=model, trace_id='fixture-' + key, status='candidate', validation='passed', request_sha256=request_sha,
                artifacts_sha256={name: builder.sha(run / name) for name in ('business_map.json', 'revenue.json', 'evidence.html')},
                implementation_sha256={'product_run.py': ('a' if key == 'A' else 'b') * 64},
                counts={'business_nodes': 2, 'business_relationships': 1, 'revenue_charts': 1},
                costs={'requests': 1, 'unknown_cost_requests': 0, 'known_estimated_usd': '0.1' if key == 'A' else '0.2',
                       'records': [{'requested_model': model, 'actual_upstream_model': model, 'request_sha256': request_sha,
                                    'status': 'succeeded', 'stop_reason': 'end_turn', 'http_status': 200,
                                    'raw_usage': {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 0},
                                    'elapsed_seconds': 1 if key == 'A' else 2}]})
            self.refreeze_arm(key)
        prior = self.root / 'prior'
        prior.mkdir()
        write(prior / 'request.json', {**self.requests['B'], 'stream': False})
        self.prior = {'model': 'claude-opus-5-5', 'trace_id': 'fixture-failed', 'status': 'failed',
                      'request_sha256': builder.sha(prior / 'request.json'), 'costs': {'unknown_cost_requests': 1}}
        write(prior / 'result.json', self.prior)
        self.console = {'binding': {'local_trace_id': self.prior['trace_id'], 'request_sha256': self.prior['request_sha256'],
                                     'result_sha256': builder.sha(prior / 'result.json')},
                        'provider_record': {'model': 'claude-opus-5-5', 'charge_usd': '0.4', 'status_display': '成功', 'channel': 'fixture'},
                        'correlation': {'exact_request_id_match': False}}
        write(self.root / 'console.json', self.console)
        self.protocol = {'calls_max': 1, 'automatic_retries': 0, 'request_difference_from_failed_opus': ['stream'],
                         'configuration_difference': {'stream': [False, True], 'timeout_seconds': [300, 600]},
                         'request_sha256': self.results['B']['request_sha256'],
                         'runtime_sha256': {'src/product_run.py': 'b' * 64},
                         'scope': {field: self.results['A'][field] for field in ('company_id', 'document_id', 'period_end',
                                             'source_packet_sha256', 'skill_sha256', 'output_schema_sha256')},
                         'prior_run': 'prior', 'prior_trace': self.prior['trace_id'],
                         'prior_result_sha256': builder.sha(prior / 'result.json'), 'prior_provider_reconciliation': 'console.json'}
        write(self.root / 'protocol.json', self.protocol)
        self.output = self.root / 'comparison'

    def refreeze_arm(self, key):
        run, result = self.runs[key], self.results[key]
        write(run / 'result.json', result)
        page = self.pages[key]
        page.parent.mkdir(exist_ok=True)
        page.write_text('<html><body><svg>Explicit synthetic page fixture.</svg></body></html>')
        write(page.parent / 'verification.json', {'trace_id': result['trace_id'], 'with_svg': True,
                'fingerprints': {'html': builder.sha(page), 'result': builder.sha(run / 'result.json')}})

    def build(self, review=None):
        return builder.build(self.root, self.root / 'protocol.json', self.runs, self.pages,
                             self.output, 'http://127.0.0.1:8765', review)

    def payload(self):
        page = (self.output / 'index.html').read_text()
        return json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])

    def attach_review(self):
        review = {'summary': 'Fixture review </script><script>globalThis.BAD=1</script>',
                  'checks': [{'id': 'R1', 'label': 'Fixture check', 'sonnet': 'A text', 'opus': 'B text',
                              'note': 'Not a model quality claim.', 'source_block_ids': ['block-one']}],
                  'bindings': {}, 'limitations': ['Synthetic fixture.']}
        for key in ('A', 'B'):
            result = self.results[key]
            review['bindings'][key] = {field: result[field] for field in ('trace_id', 'request_sha256', 'source_packet_sha256', 'skill_sha256')}
            review['bindings'][key].update(result_sha256=builder.sha(self.runs[key] / 'result.json'),
                business_map_sha256=result['artifacts_sha256']['business_map.json'], revenue_sha256=result['artifacts_sha256']['revenue.json'])
        path = self.root / 'review.json'
        write(path, review)
        return path, review

    def test_recovery_keeps_current_and_prior_costs_separate_and_inputs_immutable(self):
        frozen = {path: builder.sha(path) for path in self.root.rglob('*') if path.is_file()}
        verification = self.build()
        data = self.payload()
        self.assertFalse(verification['strict_model_only_ab'])
        self.assertEqual(verification['request_differing_fields'], ['model', 'stream'])
        self.assertEqual(data['arms']['B']['estimated_usd'], '0.2')
        self.assertEqual(data['attempts']['prior']['provider_reported_charge_usd'], '0.4')
        self.assertEqual(data['attempts']['opus_two_attempts_indicative_usd'], '0.6')
        self.assertEqual(data['attempts']['prior']['local_unknown_cost_requests'], 1)
        self.assertFalse(data['attempts']['correlation']['exact_request_id_match'])
        self.assertTrue(data['method']['runtime_version_differs'])
        self.assertIsNone(data['review'])
        self.assertTrue(all(builder.sha(path) == digest for path, digest in frozen.items()))

    def test_incomplete_run_or_missing_visible_svg_cannot_be_presented_as_success(self):
        self.results['B']['status'] = 'failed'
        self.refreeze_arm('B')
        with self.assertRaisesRegex(ValueError, 'completed_candidate_required'):
            self.build()
        self.results['B']['status'] = 'candidate'
        self.refreeze_arm('B')
        check = builder.read(self.pages['B'].parent / 'verification.json')
        check['with_svg'] = False
        write(self.pages['B'].parent / 'verification.json', check)
        with self.assertRaisesRegex(ValueError, 'visible_page_not_ready'):
            self.build()

    def test_prompt_drift_is_rejected_even_with_updated_receipts(self):
        self.requests['B']['system'] = 'Different prompt'
        write(self.runs['B'] / 'request.json', self.requests['B'])
        digest = builder.sha(self.runs['B'] / 'request.json')
        self.results['B']['request_sha256'] = digest
        self.results['B']['costs']['records'][0]['request_sha256'] = digest
        self.refreeze_arm('B')
        self.protocol['request_sha256'] = digest
        write(self.root / 'protocol.json', self.protocol)
        with self.assertRaisesRegex(ValueError, 'requests_differ_beyond_recovery_variables'):
            self.build()

    def test_changed_source_and_misbound_console_record_are_rejected(self):
        self.console['binding']['local_trace_id'] = 'different-failed-run'
        write(self.root / 'console.json', self.console)
        with self.assertRaisesRegex(ValueError, 'prior_console_binding_mismatch'):
            self.build()
        self.console['binding']['local_trace_id'] = self.prior['trace_id']
        write(self.root / 'console.json', self.console)
        (self.root / 'source.html').write_text('changed source')
        with self.assertRaisesRegex(ValueError, 'source_hash_mismatch'):
            self.build()

    def test_review_requires_both_run_hashes_and_exact_source_ids(self):
        path, review = self.attach_review()
        self.build(path)
        self.assertNotIn('<script>globalThis.BAD', (self.output / 'index.html').read_text())
        self.assertEqual(self.payload()['review']['source_blocks'][0]['text'], self.packet['blocks'][0]['text'])
        invalid = copy.deepcopy(review)
        invalid['bindings']['B']['result_sha256'] = 'wrong-run'
        write(path, invalid)
        with self.assertRaisesRegex(ValueError, 'review_binding_mismatch'):
            self.build(path)
        invalid = copy.deepcopy(review)
        invalid['checks'][0]['source_block_ids'] = ['other-company-source']
        write(path, invalid)
        with self.assertRaisesRegex(ValueError, 'review_source_outside_packet'):
            self.build(path)

    @unittest.skipUnless(shutil.which('node'), 'Node required for script execution')
    def test_page_script_metrics_tabs_review_and_cost_labels(self):
        path, _ = self.attach_review()
        self.build(path)
        script = html.fromstring((self.output / 'index.html').read_bytes()).xpath('//script')[0].text
        js = self.root / 'page.js'
        js.write_text(script)
        subprocess.run(['node', '--check', str(js)], check=True, capture_output=True)
        harness = self.root / 'harness.cjs'
        harness.write_text(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class E{constructor(tag){this.tag=tag;this.children=[];this.events={};this.attributes={};this._text=''}set textContent(v){this._text=String(v);this.children=[]}get textContent(){return this._text+this.children.map(c=>c.textContent).join('')}append(...nodes){this.children.push(...nodes)}setAttribute(k,v){this.attributes[k]=v}addEventListener(k,v){this.events[k]=v}}
const els={},document={getElementById:id=>els[id]||(els[id]=new E('div')),createElement:t=>new E(t)};
const context={document,URL,Intl,location:{href:'http://127.0.0.1/comparison/index.html'},history:{replaceState(){}}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
assert(!context.BAD);assert.equal(els.metrics.children.length,2);assert(els.metrics.textContent.includes('非流式 / 300'));assert(els.metrics.textContent.includes('流式 / 600'));assert(els['cost-accounting'].textContent.includes('$0.6'));assert(els['cost-accounting'].textContent.includes('缺少精确请求 ID'));assert.equal(els['prior-links'].children.length,2);assert.equal(els.checks.children.length,1);
const walk=e=>[e,...e.children.flatMap(walk)],frames=walk(els.pair).filter(e=>e.tag==='iframe');assert.equal(frames.length,2);assert(frames.every(e=>e.src.includes('view=business')));els['revenue-tab'].events.click();assert(frames.every(e=>e.src.includes('view=revenue')));assert.equal(els['revenue-tab'].attributes['aria-pressed'],'true');
''')
        subprocess.run(['node', str(harness), str(js)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
