"""Generic materialization uses source bytes and issuer contexts, not pilot answers."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources.parsed_package import EXPORT, PARSER, verify_parsed_package
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.query_dataset import build_dataset, save
from uteki.infrastructure.research_data.evidence_packaging import build_evidence_package
from uteki.domain.research_data.query_contract import (
    Period, DataQuery, ResearchRecord, QueryResult, VERSION, SOURCE_PERIOD_VERSION, export_query_schema,
)
from uteki.domain.research_data.period_scope import explicit_periods


def filing(cik='123', start='2024-07-01', end='2025-06-30'):
    return f'''<html xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:dei="http://xbrl.sec.gov/dei/2025" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
    <div style="display:none"><xbrli:context id="c"><xbrli:entity><xbrli:identifier>{cik}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></div>
    <p><ix:nonNumeric name="dei:DocumentFiscalYearFocus">2025</ix:nonNumeric></p>
    <h1>PART I</h1><h2>ITEM 1. BUSINESS</h2><p>Independent source business description.</p>
    <table><tr><td>Revenue</td><td><ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" contextRef="c" unitRef="usd" scale="6" id="rev">120</ix:nonFraction></td></tr>
    <tr><td>Operating income</td><td><ix:nonFraction name="us-gaap:OperatingIncomeLoss" contextRef="c" unitRef="usd" scale="6" id="op">30</ix:nonFraction></td></tr></table>
    <h2>ITEM 1A. RISK FACTORS</h2><p>Demand risk.</p></body></html>'''.encode()


class CompanyMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def run_source(self, raw=None, **changes):
        raw=filing() if raw is None else raw
        (self.root/'source.html').write_bytes(raw)
        doc={'source_id':'issuer-annual','source_url':'https://example.invalid/annual.html','form':'10-K',
             'filed_at':'2025-08-01','period_end':'2025-06-30','content_sha256':digest(raw),'path':'source.html',
             'mime_type':'text/html','status':'frozen',**changes}
        return {'company':{'company_id':'sec-0000000123','cik':'0000000123'},'as_of':'2025-09-01','documents':[doc]}

    def scope(self, manifest):
        return {'snapshot_id':manifest['snapshot_id'],'company_ids':['sec-0000000123'],'source_snapshot_ids':['issuer-annual'],
                'source_policy_id':'local-frozen-v1','knowledge_cutoff':'2025-09-01','include_candidates':True}

    def test_new_dataset_registers_complete_reproducible_package_and_preserves_original(self):
        run = self.run_source()
        original = (self.root/'source.html').read_bytes()
        original_metadata = json.dumps(run, sort_keys=True)
        manifest = materialize_sources(run, self.root, self.root/'dataset')
        materialize_sources(run, self.root, self.root/'elsewhere/replay')
        source, = json.loads((self.root/'dataset/sources.json').read_text())
        ref = source['parsed_package']
        self.assertEqual(ref['export_version'], EXPORT)
        self.assertEqual(ref['semantic_review'], 'not_reviewed')
        self.assertIn('parsed_document_package', source['capabilities'])
        folder = self.root/'dataset'/source['index_folder']
        replay = self.root/'elsewhere/replay'/source['index_folder']
        first = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        second = {p.relative_to(replay).as_posix(): p.read_bytes() for p in replay.rglob('*') if p.is_file()}
        self.assertEqual(first, second)
        self.assertEqual(verify_parsed_package(folder)['files_verified'], 15)
        for name, content in first.items():
            self.assertEqual(manifest['files'][source['index_folder']+'/'+name], digest(content))
        self.assertEqual(ref['manifest_sha256'], digest((folder/'manifest.json').read_bytes()))
        self.assertEqual(self.root/'dataset'/ref['source_path'], folder/'source.json')
        self.assertEqual(self.root/'dataset'/ref['document_path'], folder/'document.html')
        metadata = json.loads((folder/'source.json').read_bytes())
        self.assertEqual((metadata['company_id'], metadata['report_period_end'], metadata['available_at']),
                         ('sec-0000000123', '2025-06-30', '2025-08-01'))
        reader = DocumentReader(folder)
        root = next(n for n in reader.outline()['nodes'] if n['kind']=='document')
        self.assertTrue(reader.search(root['node_id'], 'business description')['hits'])
        self.assertEqual((self.root/'source.html').read_bytes(), original)
        self.assertEqual(json.dumps(run, sort_keys=True), original_metadata)

    def test_report_period_is_required_and_unknown_form_never_gets_a_fallback(self):
        for i, changes in enumerate(({'period_end': None}, {'period_end': ''}, {'form': 'UNSUPPORTED'})):
            with self.subTest(changes=changes):
                destination = self.root/f'missing-{i}'
                manifest = materialize_sources(self.run_source(**changes), self.root, destination)
                self.assertEqual(manifest['source_count'], 0)
                self.assertTrue(any(g['layer']=='indexing' for g in manifest['gaps']))
                self.assertFalse((destination/'indexes/issuer-annual').exists())

    def test_supported_quarter_amendment_and_updates_keep_explicit_scope(self):
        for i, (form, period) in enumerate((('10-Q', '2025-03-31'), ('20-F/A', '2024-12-31'),
                                          ('8-K', None), ('OFFICIAL_UPDATE', None))):
            with self.subTest(form=form):
                raw = b'<html><body><p>Independent report text without tagged numerical facts.</p></body></html>'
                run = self.run_source(raw, form=form, period_end=period, company_id='sec-0000000987')
                run['company'] = {'company_id': 'sec-0000000987', 'cik': '0000000987'}
                destination = self.root/f'supported-{i}'
                manifest = materialize_sources(run, self.root, destination)
                self.assertEqual((manifest['source_count'], manifest['record_count']), (1, 0))
                metadata = json.loads((destination/'indexes/issuer-annual/source.json').read_bytes())
                self.assertEqual((metadata['company_id'], metadata['form_type'], metadata['report_period_end']),
                                 ('sec-0000000987', form, period))

    def test_conflicting_source_metadata_rejected_without_publishing(self):
        for i, changes in enumerate(({'company_id': 'sec-0000000987'}, {'company_id': None},
                                     {'sha256': '0'*64})):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'mismatch|conflict'):
                materialize_sources(self.run_source(**changes), self.root, self.root/f'conflict-{i}')
            self.assertFalse((self.root/f'conflict-{i}').exists())

    def test_fiscal_year_query_has_real_source_quote_and_scaled_values(self):
        manifest=materialize_sources(self.run_source(),self.root,self.root/'dataset')
        self.assertEqual(manifest['record_count'],2)
        self.assertEqual(manifest['schema_version'], SOURCE_PERIOD_VERSION)
        with QueryDataPort(self.root/'dataset') as owner:
            port=owner.scoped(self.scope(manifest)); sources=port.discover_data()['sources']
            periods=explicit_periods('Revenue for FY2025.',fiscal_periods=sources[0]['fiscal_periods'],require_fiscal_mapping=True)
            self.assertEqual(str(periods[0].start),'2024-07-01')
            request={'query_id':'test',**{k:self.scope(manifest)[k] for k in ('snapshot_id','source_policy_id','knowledge_cutoff','include_candidates')},
                     'calculations':[{'formula_id':'operating_margin','entity_id':'sec-0000000123','periods':[periods[0].model_dump(mode='json')]}]}
            result=port.query_data(request)
            self.assertEqual(result['result_schema_version'], SOURCE_PERIOD_VERSION)
            self.assertEqual({r['schema_version'] for r in result['records']}, {SOURCE_PERIOD_VERSION})
            with self.assertRaisesRegex(ValueError, 'record and result schema versions disagree'):
                QueryResult.model_validate({**{k: v for k, v in result.items() if k in QueryResult.model_fields},
                                            'result_schema_version': VERSION})
            self.assertEqual(port.get_schema()['schema_version'], SOURCE_PERIOD_VERSION)
            for name, model in [('query', DataQuery), ('record', ResearchRecord), ('result', QueryResult)]:
                schema = json.loads((self.root/f'dataset/schemas/{name}.schema.json').read_text())
                self.assertEqual(schema, export_query_schema(model, version=SOURCE_PERIOD_VERSION))
                self.assertEqual(schema['$defs']['Period']['properties']['basis']['enum'], ['calendar', 'source'])
            self.assertEqual(result['computed_facts'][0]['display_decimal'],'25.00')
            self.assertEqual({r['value_decimal'] for r in result['records']},{'120000000','30000000'})
            for ev in result['evidence'].values():
                self.assertTrue(ev['fact_dom_path']);self.assertIn('<xbrli:context',ev['context_xml'])
                self.assertEqual(ev['source_sha256'],digest(filing()))
            package=build_evidence_package(port,{'request':{'question':'FY2025 margin','scope':self.scope(manifest)},**result})
            self.assertTrue(package['artifacts'])

    def test_legacy_record_cannot_claim_source_period_capability(self):
        materialize_sources(self.run_source(), self.root, self.root/'dataset')
        row = json.loads((self.root/'dataset/records.json').read_text())['rows'][0]
        self.assertEqual(row['period']['basis'], 'source')
        ResearchRecord.model_validate(row)
        with self.assertRaises(ValueError):
            ResearchRecord.model_validate({**row, 'schema_version': VERSION})

    def test_frozen_xml_label_is_reprocessed_from_xhtml_bytes_without_rewriting_input(self):
        raw = b'<?xml version="1.0"?>\n<!-- exported report -->\n' + filing()
        source_run = self.run_source(raw, mime_type='application/xml')
        original = json.dumps(source_run, sort_keys=True)
        manifest = materialize_sources(source_run, self.root, self.root/'dataset')
        self.assertEqual(manifest['source_count'], 1)
        self.assertEqual(manifest['record_count'], 2)
        source, = json.loads((self.root/'dataset/sources.json').read_text())
        self.assertEqual(source['declared_mime_type'], 'application/xml')
        self.assertIn(source['parsed_mime_type'], ('text/html', 'application/xhtml+xml'))
        self.assertEqual(source['source_sha256'], digest(raw))
        self.assertEqual((self.root/'dataset'/source['raw_file']).read_bytes(), raw)
        self.assertEqual(json.dumps(source_run, sort_keys=True), original)

    def test_explicit_inline_build_adapter_publishes_consistent_new_protocol(self):
        repo = Path(__file__).resolve().parents[2]
        alias = self.root / 'repo-alias'
        alias.symlink_to(repo, target_is_directory=True)
        module_spec = importlib.util.spec_from_file_location(
            'uteki.infrastructure.research_data.query_dataset_alias',
            alias / 'src/uteki/infrastructure/research_data/query_dataset.py')
        aliased_builder = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(aliased_builder)
        for start, end, filed in [('2025-01-01', '2025-12-31', '2026-02-01'),
                                  ('2024-07-01', '2025-06-30', '2025-08-01')]:
            with self.subTest(start=start), tempfile.TemporaryDirectory(dir=repo) as tmp:
                root = Path(tmp)
                raw = filing(start=start, end=end)
                (root/'source.html').write_bytes(raw)
                source_run = {'company': {'company_id': 'sec-0000000123', 'cik': '0000000123'},
                    'as_of': '2026-03-01', 'documents': [{'source_id': 'issuer-annual',
                    'source_url': 'https://example.invalid/annual.html', 'form': '10-K',
                    'filed_at': filed, 'period_end': end, 'content_sha256': digest(raw),
                    'path': 'source.html', 'mime_type': 'text/html', 'status': 'frozen'}]}
                materialize_sources(source_run, root, root/'materialized')
                source = json.loads((root/'materialized/sources.json').read_text())[0]
                def pinned(path):
                    return {'path': str(path.relative_to(repo)), 'sha256': digest(path.read_bytes())}
                source_manifest = root/'source-manifest.json'
                save(source_manifest, {'source_snapshot_id': 'issuer-annual', 'company_id': 'sec-0000000123',
                    'document_id': source['document_id'], 'content_sha256': digest(raw), 'filed_at': filed,
                    'form': '10-K', 'period_end': end})
                index = root/'materialized'/source['index_folder']
                inventory = root/'inventory.json'
                save(inventory, {'sources': [{'source_snapshot_id': 'issuer-annual',
                    'document_id': source['document_id'], 'eligible_for_new_comparison': True,
                    'declared_content_sha256': digest(raw), 'source_manifest': pinned(source_manifest),
                    'raw_file': pinned(root/'source.html'), 'published_or_filed_at': filed, 'period_end': end,
                    'source_url': source['source_url'],
                    'index_files': [pinned(index/name) for name in ('manifest.json', 'index.json', 'blocks.jsonl')]}]})
                spec = root/'spec.json'
                save(spec, {'spec_version': 'query-build-v1', 'source_inventory': pinned(inventory),
                    'sources': [{'source_snapshot_id': 'issuer-annual', 'company_id': 'sec-0000000123',
                                 'entity_ids': ['sec-0000000123'], 'content_sha256': digest(raw)}],
                    'inputs': [{**pinned(root/'source.html'), 'source_snapshot_id': 'issuer-annual',
                                'adapter': 'us-gaap-inline-v1'}]})
                original = digest((root/'source.html').read_bytes())
                manifest = build_dataset(repo, root/'built', spec=spec)
                self.assertEqual(manifest['schema_version'], SOURCE_PERIOD_VERSION)
                self.assertEqual(digest((root/'source.html').read_bytes()), original)
                with self.subTest(repo_path='symlink'):
                    alias_root = alias / root.relative_to(repo)
                    aliased = aliased_builder.build_dataset(
                        alias, alias_root/'built-alias', spec=alias_root/'spec.json')
                    self.assertEqual(aliased['snapshot_id'], manifest['snapshot_id'])
                    self.assertEqual(aliased['adapter_hashes'], manifest['adapter_hashes'])
                    self.assertEqual((root/'built-alias/records.json').read_bytes(),
                                     (root/'built/records.json').read_bytes())
                    self.assertEqual(digest((root/'source.html').read_bytes()), original)
                with QueryDataPort(root/'built') as port:
                    self.assertEqual(port.sources[0]['parsed_mime_type'], 'text/html')
                    self.assertEqual(port.get_schema()['schema_version'], SOURCE_PERIOD_VERSION)
                    self.assertTrue(any(mapping['fiscal_year'] == 2025
                        and mapping['company_id'] == 'sec-0000000123'
                        and mapping['period']['start'] == start
                        and mapping['period']['end'] == end
                        for mapping in port.get_schema()['fiscal_periods']))
                    self.assertFalse(any(gap.get('reason') == "'form'"
                        for gap in manifest['normalization_gaps']))
                    from uteki.infrastructure.research_data.record_locator import resolve_record_locator
                    for item in json.loads((root/'built/evidence.json').read_text()).values():
                        locator = resolve_record_locator(root/'built', item)
                        self.assertGreater(locator['char_end'], locator['char_start'])
                    schema = port.get_schema()['record']
                    self.assertEqual(schema, export_query_schema(ResearchRecord, version=SOURCE_PERIOD_VERSION))
                    result = port.query_data({'query_id': 'inline-build', 'snapshot_id': port.snapshot_id,
                        'knowledge_cutoff': '2026-03-01', 'include_candidates': True,
                        'records': [{'entity_id': 'sec-0000000123', 'metric_id': 'revenue',
                                     'period': {'kind': 'year', 'start': start, 'end': end, 'basis': 'source'}}]})
                    self.assertEqual(result['status'], 'complete')
                    self.assertEqual(result['result_schema_version'], SOURCE_PERIOD_VERSION)
                    self.assertEqual({r['schema_version'] for r in result['records']}, {SOURCE_PERIOD_VERSION})

    def test_wrong_issuer_context_is_gap_and_document_remains_readable(self):
        manifest=materialize_sources(self.run_source(filing(cik='987')),self.root,self.root/'dataset')
        self.assertEqual(manifest['record_count'],0);self.assertEqual(manifest['source_count'],1)
        self.assertTrue(any(x['reason']=='context_company_mismatch' for x in manifest['gaps']))
        with QueryDataPort(self.root/'dataset') as port:
            self.assertEqual(len(port.sources),1)

    def test_dimensions_are_preserved_as_distinct_opaque_entities(self):
        raw = filing().replace(b'</xbrli:entity>', b'<xbrli:segment><xbrldi:explicitMember dimension="issuer:BusinessAxis">issuer:ServicesMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>')
        manifest = materialize_sources(self.run_source(raw), self.root, self.root/'dataset')
        records = json.loads((self.root/'dataset/records.json').read_text())['rows']
        self.assertEqual(manifest['record_count'], 2)
        self.assertTrue(all(r['entity_id'].startswith('sec-0000000123-dimensions-') for r in records))
        self.assertTrue(all(r['dimensions'] == {'issuer:BusinessAxis': 'issuer:ServicesMember'} for r in records))
        self.assertFalse(any(r['entity_id'] == 'sec-0000000123' for r in records))
        with QueryDataPort(self.root/'dataset') as owner:
            schema = owner.scoped(self.scope(manifest)).get_schema()
            child = next(e for e in schema['entities'] if e['entity_id'] == records[0]['entity_id'])
            self.assertEqual(child['reported_dimensions'], [{'issuer:BusinessAxis': 'issuer:ServicesMember'}])

    def test_fiscal_schema_cannot_use_future_or_denied_candidate_source(self):
        manifest = materialize_sources(self.run_source(), self.root, self.root/'dataset')
        with QueryDataPort(self.root/'dataset') as owner:
            scope = self.scope(manifest)
            self.assertTrue(owner.scoped(scope).get_schema()['fiscal_periods'])
            for changes in ({'knowledge_cutoff': '2025-07-01'}, {'include_candidates': False}):
                with self.subTest(changes=changes):
                    self.assertEqual(owner.scoped({**scope, **changes}).get_schema()['fiscal_periods'], [])

    def test_unmapped_concept_and_spoofed_namespace_never_become_facts(self):
        raw = filing().replace(b'us-gaap:OperatingIncomeLoss', b'us-gaap:UnreviewedProfit')
        manifest = materialize_sources(self.run_source(raw), self.root, self.root/'dataset')
        self.assertEqual(manifest['record_count'], 1)
        self.assertTrue(any(g['reason'] == 'unmapped_concept' for g in manifest['gaps']))
        spoofed = filing().replace(b'http://fasb.org/us-gaap/2025', b'https://example.invalid/us-gaap/2025')
        other = materialize_sources(self.run_source(spoofed), self.root, self.root/'spoofed')
        self.assertEqual(other['record_count'], 0)

    def test_another_issuer_and_calendar_dates_remain_independent(self):
        run = self.run_source(filing(cik='987', start='2025-01-01', end='2025-12-31'),
                              filed_at='2026-02-01', period_end='2025-12-31')
        run['company'] = {'company_id': 'sec-0000000987', 'cik': '0000000987'}
        run['as_of'] = '2026-03-01'
        manifest = materialize_sources(run, self.root, self.root/'dataset')
        rows = json.loads((self.root/'dataset/records.json').read_text())['rows']
        self.assertEqual(manifest['record_count'], 2)
        self.assertEqual({r['entity_id'] for r in rows}, {'sec-0000000987'})
        self.assertTrue(all(r['period'] == {'kind':'year', 'start':'2025-01-01', 'end':'2025-12-31'} for r in rows))

    def test_image_reference_does_not_claim_image_content_was_read(self):
        raw = filing().replace(b'</body>', b'<img src="chart.png" alt="Revenue chart"/></body>')
        manifest = materialize_sources(self.run_source(raw), self.root, self.root/'dataset')
        self.assertTrue(any(g['reason'] == 'image_reference_only' for g in manifest['gaps']))
        self.assertEqual(json.loads((self.root/'dataset/sources.json').read_text())[0]['image_block_count'], 1)

    def test_hash_mismatch_fails_without_publishing(self):
        run=self.run_source(content_sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            materialize_sources(run,self.root,self.root/'dataset')
        self.assertFalse((self.root/'dataset').exists())

    def test_date_cutoff_and_unknown_date_are_explicit_gaps(self):
        for changes in ({'filed_at':'2025-10-01'},{'filed_at':None,'status':'frozen_date_unverified'}):
            with self.subTest(changes=changes):
                dest=self.root/('run'+str(len(list(self.root.glob('run*')))))
                manifest=materialize_sources(self.run_source(**changes),self.root,dest)
                self.assertEqual(manifest['source_count'],0);self.assertEqual(manifest['status'],'unavailable')

    def test_document_only_has_no_invented_facts(self):
        run=self.run_source(b'<html><body><h1>Business</h1><p>Products and customers.</p></body></html>')
        manifest=materialize_sources(run,self.root,self.root/'dataset')
        self.assertEqual(manifest['record_count'],0);self.assertEqual(manifest['source_count'],1)
        with QueryDataPort(self.root/'dataset') as port:
            self.assertEqual(port.discover_data(knowledge_cutoff='2025-09-01')['coverage'],[])

    def test_unaccepted_period_leaves_no_orphan_evidence_and_remains_readable(self):
        raw = filing(cik='987', start='2031-01-01', end='2031-12-30')
        run = self.run_source(raw, filed_at='2032-02-01', period_end='2031-12-30')
        run['company'] = {'company_id': 'sec-0000000987', 'cik': '0000000987'}
        run['as_of'] = '2032-03-01'
        manifest = materialize_sources(run, self.root, self.root/'dataset')
        self.assertEqual((manifest['source_count'], manifest['record_count'], manifest['evidence_count']), (1, 0, 0))
        self.assertEqual(json.loads((self.root/'dataset/evidence.json').read_text()), {})
        self.assertEqual(json.loads((self.root/'dataset/records.json').read_text()), {'rows': []})
        self.assertTrue(any(g['layer'] == 'normalization' for g in manifest['gaps']))
        source, = json.loads((self.root/'dataset/sources.json').read_text())
        self.assertEqual(source['fiscal_periods'], [])
        self.assertEqual(source['stage_coverage']['reading']['status'], 'indexed')
        self.assertEqual(source['stage_coverage']['numeric']['status'], 'no_supported_records')
        self.assertEqual(source['stage_coverage']['numeric']['financial_package_completeness'], 'not_evaluated')
        self.assertEqual(source['stage_coverage']['numeric']['period_support'], 'complete_month_boundaries_only')

    def test_stage_counts_match_real_blocks_and_candidate_evidence(self):
        raw = filing().replace(b'<table>', b'<table><tr><td><table>', 1).replace(
            b'</table>', b'</table></td></tr></table>', 1)
        manifest = materialize_sources(self.run_source(raw), self.root, self.root/'dataset')
        source, = json.loads((self.root/'dataset/sources.json').read_text())
        coverage = source['stage_coverage']
        blocks = [json.loads(line) for line in (self.root/'dataset'/source['index_folder']/'blocks.jsonl').read_text().splitlines()]
        self.assertEqual(coverage['original']['source_sha256'], digest(raw))
        self.assertEqual(coverage['reading']['parser_version'], PARSER)
        self.assertEqual(coverage['reading']['block_count'], len(blocks))
        self.assertEqual(coverage['tables']['table_node_count'], 2)
        self.assertEqual(coverage['tables']['tables_with_cells'], 2)
        self.assertEqual(coverage['tables']['tables_without_cells'], 0)
        self.assertEqual(coverage['tables']['cell_count'], 5)
        self.assertEqual(coverage['tables']['financial_table_semantics'], 'not_evaluated')
        self.assertIn('html_table_structure', source['capabilities'])
        aggregate = manifest['stage_coverage']
        self.assertEqual(aggregate['originals']['hash_verified_document_count'], 1)
        self.assertEqual(aggregate['originals']['byte_count'], len(raw))
        self.assertEqual(aggregate['reading']['block_count'], len(blocks))
        for key in ('table_node_count', 'tables_with_cells', 'tables_without_cells', 'cell_count'):
            self.assertEqual(aggregate['tables'][key], coverage['tables'][key])
        self.assertEqual(aggregate['numeric']['record_count'], 2)
        self.assertEqual(aggregate['numeric']['evidence_count'], 2)
        self.assertEqual(aggregate['numeric']['financial_package_completeness'], 'not_evaluated')
        records = json.loads((self.root/'dataset/records.json').read_text())['rows']
        evidence = json.loads((self.root/'dataset/evidence.json').read_text())
        self.assertEqual(set(evidence), {eid for record in records for eid in record['evidence_ids']})

    def test_ifrs_twd_document_is_readable_without_claiming_numeric_support(self):
        raw = filing().replace(b'http://fasb.org/us-gaap/2025', b'https://xbrl.ifrs.org/taxonomy/2031-03-27/ifrs-full')
        raw = raw.replace(b'us-gaap', b'ifrs-full').replace(b'iso4217:USD', b'iso4217:TWD')
        manifest = materialize_sources(self.run_source(raw, form='20-F'), self.root, self.root/'dataset')
        self.assertEqual((manifest['source_count'], manifest['record_count'], manifest['evidence_count']), (1, 0, 0))
        source, = json.loads((self.root/'dataset/sources.json').read_text())
        coverage = source['stage_coverage']
        self.assertEqual(coverage['reading']['status'], 'indexed')
        self.assertEqual(coverage['tables']['tables_with_cells'], 1)
        self.assertEqual(coverage['numeric']['status'], 'no_supported_records')
        self.assertEqual(coverage['numeric']['supported_taxonomy'], 'US_GAAP')
        self.assertEqual(coverage['numeric']['supported_currencies'], ['USD'])
        self.assertEqual(coverage['numeric']['financial_package_completeness'], 'not_evaluated')
        self.assertEqual(coverage['numeric']['semantic_review'], 'not_evaluated')

    def test_missing_fiscal_mapping_is_not_a_calendar_guess(self):
        self.assertEqual(explicit_periods('Revenue for FY2025.', require_fiscal_mapping=True),())
        self.assertEqual(explicit_periods('Revenue for FY2025.')[0].start.isoformat(),'2025-01-01')
        with self.assertRaises(ValueError): Period(kind='year',start='2024-07-01',end='2025-06-30')
        self.assertEqual(Period(kind='year',start='2024-07-01',end='2025-06-30',basis='source').end.isoformat(),'2025-06-30')

    def test_fiscal_quarter_needs_exact_source_mapping(self):
        mapping = [{'fiscal_year':2025, 'fiscal_quarter':1, 'period':{'kind':'quarter', 'start':'2024-07-01', 'end':'2024-09-30', 'basis':'source'}}]
        values = explicit_periods('Revenue FY2025 Q1', fiscal_periods=mapping, require_fiscal_mapping=True)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].start.isoformat(), '2024-07-01')
        self.assertEqual(explicit_periods('Revenue FY2025 Q2', fiscal_periods=mapping, require_fiscal_mapping=True), ())
        self.assertEqual(explicit_periods('Revenue FY2025', fiscal_periods=mapping, require_fiscal_mapping=True), ())

    def test_crosscompany_document_and_traversal_rejected(self):
        for changes in ({'company_id':'sec-999'},{'path':'../outside.html'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                materialize_sources(self.run_source(**changes),self.root,self.root/'dataset')

    def test_unsupported_pdf_is_index_gap_not_success(self):
        manifest=materialize_sources(self.run_source(b'%PDF-invalid',mime_type='application/pdf'),self.root,self.root/'dataset')
        self.assertEqual(manifest['source_count'],0)
        self.assertTrue(any(g['layer']=='indexing' for g in manifest['gaps']))


if __name__=='__main__': unittest.main()
