"""Independent synthetic sources for direct extraction's deterministic boundary."""
from copy import deepcopy
import unittest
from uteki.domain.research_data.direct_extraction import DirectExtraction
from uteki.infrastructure.research_data.direct_normalization import normalize_direct_candidates
from uteki.infrastructure.research_data.financial_records import digest


class DirectNormalizationTests(unittest.TestCase):
    def fixture(self, company='company-b', year=2030):
        text = f'{year} Revenue was approximately 1.2 to 1.5 million USD, subject to supply.'
        packet = {'packet_id': f'packet-{company}-{year}', 'company_id': company,
                  'source': {'source_snapshot_id': f'source-{company}-{year}', 'company_id': company,
                             'source_url': 'https://example.org/report', 'source_sha256': digest(text.encode()),
                             'available_at': f'{year}-02-01', 'form': 'EARNINGS_CALL'},
                  'blocks': [{'block_id': 'b1', 'text': text, 'text_hash': digest(text.encode())}],
                  'entity_catalog': [{'entity_id': company, 'label': 'Example business', 'aliases': ['Our business']}],
                  'metric_catalog': {'revenue': {'label': 'Revenue', 'unit': 'USD', 'aliases': ['Sales']}},
                  'period_catalog': [{'period_id': f'p-{year}', 'label': str(year),
                                      'period': {'kind': 'year', 'start': f'{year}-01-01', 'end': f'{year}-12-31'}}],
                  'task': {'company_id': company, 'source_snapshot_ids': [f'source-{company}-{year}'],
                           'knowledge_cutoff': f'{year}-02-02'}}
        record = {'draft_id': 'draft-1', 'kind': 'guidance', 'entity': 'Example business', 'entity_id': company,
                  'metric': 'Revenue', 'metric_id': 'revenue', 'period': str(year), 'period_id': f'p-{year}',
                  'value': '1.2', 'upper': '1.5', 'value_relation': 'range', 'unit': 'USD_millions',
                  'accounting_basis': 'management_guidance', 'summary': 'Revenue outlook subject to supply',
                  'evidence': [{'block_id': 'b1', 'quote': text}],
                  'qualifiers': [{'block_id': 'b1', 'quote': 'subject to supply'}]}
        return packet, {'records': [record], 'relations': [], 'gaps': []}

    def test_scale_range_qualifier_and_immutable_inputs(self):
        packet, extraction = self.fixture(); originals = deepcopy((packet, extraction))
        out = normalize_direct_candidates(extraction, packet)
        self.assertEqual((packet, extraction), originals)
        self.assertEqual(out['validation']['status'], 'source_validated')
        r = out['records'][0]
        self.assertEqual((r['value_decimal'], r['upper_decimal'], r['unit']), ('1200000.0', '1500000.0', 'USD'))
        self.assertEqual(r['value_relation'], 'range'); self.assertEqual(r['value_kind'], 'management_guidance')
        self.assertEqual(out['evidence'][r['qualifier_evidence_ids'][0]]['quote'], 'subject to supply')
        self.assertEqual(out['validation']['semantic_acceptance'], 'not_evaluated')
        self.assertEqual(r['status'], 'candidate')

    def test_second_company_period_and_source_do_not_fall_back(self):
        packet, extraction = self.fixture('company-z', 2022)
        r = normalize_direct_candidates(extraction, packet)['records'][0]
        self.assertEqual(r['entity_id'], 'company-z')
        self.assertEqual(r['source_snapshot_id'], 'source-company-z-2022')
        self.assertEqual(r['period']['end'], '2022-12-31')
        for field, value in [('entity_id', 'company-b'), ('period_id', 'p-2030'), ('period', '2030'), ('metric_id', None)]:
            changed = deepcopy(extraction); changed['records'][0][field] = value
            with self.subTest(field=field):
                out = normalize_direct_candidates(changed, packet)
                self.assertEqual(out['records'], []); self.assertEqual(out['raw_candidates'], changed['records'])

    def test_source_scope_hash_and_cutoff_fail_closed(self):
        packet, extraction = self.fixture()
        for target, key, value in [('source','company_id','other'),('source','available_at','2031-01-01'),
                                   ('task','source_snapshot_ids',['wrong']),('task','company_id','wrong')]:
            changed=deepcopy(packet); changed[target][key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): normalize_direct_candidates(extraction,changed)
        changed=deepcopy(packet);changed['blocks'][0]['text']+='tamper'
        with self.assertRaisesRegex(ValueError,'hash'):normalize_direct_candidates(extraction,changed)
        changed=deepcopy(packet);changed['entity_catalog'][0]['company_id']='another'
        with self.assertRaisesRegex(ValueError,'catalog outside'):normalize_direct_candidates(extraction,changed)

    def test_missing_mapping_unsupported_values_never_enter_records(self):
        packet, extraction = self.fixture()
        for changes in [{'entity_id':None},{'metric_id':'unknown','metric':'New revenue'}, {'period_id':None},
                        {'unit':'EUR_millions'}, {'accounting_basis':None}, {'accounting_basis':'invented'},
                        {'value':'NaN'}, {'upper':'1.0'}, {'value':'999'}, {'unresolved_fields':['definition']},
                        {'evidence':[]}, {'qualifiers':[{'block_id':'missing','quote':'condition'}]}]:
            changed=deepcopy(extraction);changed['records'][0].update(changes)
            with self.subTest(changes=changes):
                out=normalize_direct_candidates(changed,packet)
                self.assertEqual(out['records'],[]);self.assertTrue(out['unresolved'])
                self.assertEqual(out['raw_candidates'],changed['records'])

    def test_repeated_quote_requires_host_occurrence_id(self):
        packet, extraction=self.fixture()
        block=packet['blocks'][0];block['text']='Revenue 1.2 and later Revenue 1.2';block['text_hash']=digest(block['text'].encode())
        r=extraction['records'][0];r.update(value='1.2',upper=None,value_relation='approx',qualifiers=[],evidence=[{'block_id':'b1','quote':'Revenue 1.2'}])
        out=normalize_direct_candidates(extraction,packet);self.assertEqual(out['records'],[])
        issue=next(x for x in out['unresolved'] if x['reason']=='ambiguous_quote')
        self.assertEqual(len(issue['occurrences']),2)
        later=issue['occurrences'][1]
        r['evidence'][0]['occurrence_id']=later['occurrence_id']
        resolved=normalize_direct_candidates(extraction,packet)
        ev=resolved['evidence'][resolved['records'][0]['evidence_ids'][0]]
        self.assertEqual(ev['source_start'],22);self.assertEqual(ev['occurrence_id'],later['occurrence_id'])
        r['evidence'][0]['occurrence_id']='fabricated'
        self.assertEqual(normalize_direct_candidates(extraction,packet)['records'],[])

    def test_relations_link_drafts_and_preserve_unresolved_targets(self):
        packet,extraction=self.fixture()
        extraction['relations']=[{'relation_id':'rel-1','relation_type':'conditional_on','record_ids':['draft-1'],
                                 'description':'Depends on supply','evidence':[{'block_id':'b1','quote':'subject to supply'}]}]
        out=normalize_direct_candidates(extraction,packet)
        self.assertEqual(out['relations'][0]['normalized_record_ids'],[out['records'][0]['record_id']])
        self.assertEqual(out['relations'][0]['status'],'candidate')
        extraction['records'][0]['metric_id']=None
        out=normalize_direct_candidates(extraction,packet)
        self.assertEqual(out['relations'][0]['status'],'unresolved')
        self.assertEqual(out['relations'][0]['record_ids'],['draft-1'])

    def test_numeric_substring_and_analyst_question_do_not_establish_fact(self):
        packet,extraction=self.fixture()
        r=extraction['records'][0];r.update(value='1',upper=None,value_relation='eq')
        self.assertEqual(normalize_direct_candidates(extraction,packet)['records'],[])
        packet['blocks'][0]['speaker_role']='analyst'
        out=normalize_direct_candidates(extraction,packet)
        self.assertIn('analyst_question_as_fact',[x['reason'] for x in out['unresolved']])

    def test_accounting_parenthesis_padding_preserves_raw_and_exact_source(self):
        for company, year, currency, raw in [
                ('company-u', 2024, 'USD', '(1,234.5 )'),
                ('company-t', 2027, 'TWD', '(\u00a0 42.75\t)')]:
            with self.subTest(company=company):
                packet, extraction = self.fixture(company, year)
                text = f'{year} Revenue {raw} {currency} millions.'
                packet['blocks'][0].update(text=text, text_hash=digest(text.encode()))
                packet['metric_catalog']['revenue']['unit'] = currency
                row = extraction['records'][0]
                row.update(value=raw, upper=None, value_relation='eq', unit=currency+'_millions',
                           qualifiers=[], evidence=[{'block_id':'b1','quote':text}])
                before = deepcopy((packet, extraction))
                out = normalize_direct_candidates(extraction, packet)
                self.assertEqual((packet, extraction), before)
                self.assertEqual(len(out['records']), 1)
                expected = '-1234500000.0' if currency == 'USD' else '-42750000.00'
                self.assertEqual(out['records'][0]['value_decimal'], expected)
                self.assertEqual(out['records'][0]['origin']['raw']['value'], raw)
                row['value'] = raw.replace(' ', '').replace('\u00a0', '').replace('\t', '')
                self.assertEqual(normalize_direct_candidates(extraction, packet)['records'], [])

    def test_parenthesis_support_does_not_join_numbers_or_accept_bad_signs(self):
        for raw in ['(1 234)', '(1, 234)', '(1. 2)', '(-12)', '(12\n)', '()']:
            with self.subTest(raw=raw):
                packet, extraction = self.fixture()
                text = f'Revenue {raw}'
                packet['blocks'][0].update(text=text, text_hash=digest(text.encode()))
                extraction['records'][0].update(value=raw, upper=None, value_relation='eq',
                    qualifiers=[], evidence=[{'block_id':'b1','quote':text}])
                out = normalize_direct_candidates(extraction, packet)
                self.assertEqual(out['records'], [])
                self.assertIn('unsupported_numeric_literal', [i['reason'] for i in out['unresolved']])

    def test_contextual_mapping_is_pinned_and_requires_actual_evidence(self):
        packet, extraction = self.fixture('independent-context-company', 2028)
        original = packet['blocks'][0]['text']
        packet['blocks'][0].update(text='Context heading. '+original,
                                  text_hash=digest(('Context heading. '+original).encode()))
        packet['dataset_manifest_sha256'] = digest('independent-dataset')
        binding = {'adapter_id': 'independent-context-v1',
            **{k: packet['source'][k] for k in ('company_id','source_snapshot_id','source_sha256')},
            'dataset_manifest_sha256': packet['dataset_manifest_sha256'],
            'block_hashes': {'b1': packet['blocks'][0]['text_hash']},
            'metric_contexts': {'revenue': [{'block_id':'b1','quote':'Context heading.'}]}}
        packet['source_bound_normalization'] = binding
        out = normalize_direct_candidates(extraction, packet)
        self.assertEqual(out['records'], [])
        self.assertIn('missing_required_mapping_context', [i['reason'] for i in out['unresolved']])
        extraction['records'][0]['evidence'].append({'block_id':'b1','quote':'Context heading.'})
        self.assertEqual(len(normalize_direct_candidates(extraction, packet)['records']), 1)
        for key, value in [('company_id','another'), ('source_snapshot_id','another'),
                           ('source_sha256',digest('other')), ('dataset_manifest_sha256',digest('other')),
                           ('block_hashes',{'b1':digest('other')})]:
            with self.subTest(key=key):
                changed = deepcopy(packet); changed['source_bound_normalization'][key] = value
                with self.assertRaisesRegex(ValueError,'mapping'):
                    normalize_direct_candidates(extraction, changed)
        changed = deepcopy(packet)
        changed['blocks'].append({'block_id':'another-table','text':'Same row label',
                                 'text_hash':digest(b'Same row label')})
        with self.assertRaisesRegex(ValueError,'delivered block hashes'):
            normalize_direct_candidates(extraction, changed)
        changed = deepcopy(packet)
        del changed['source_bound_normalization']['source_snapshot_id']
        with self.assertRaisesRegex(ValueError,'complete binding'):
            normalize_direct_candidates(extraction, changed)
        changed = deepcopy(packet)
        changed['source_bound_normalization']['metric_contexts']['revenue'][0]['block_id'] = {}
        with self.assertRaisesRegex(ValueError,'context is absent'):
            normalize_direct_candidates(extraction, changed)

    def test_schema_rejects_model_offsets_and_non_schema_fields(self):
        packet,extraction=self.fixture()
        extraction['records'][0]['evidence'][0]['source_start']=1
        with self.assertRaises(ValueError):normalize_direct_candidates(extraction,packet)
        packet,extraction=self.fixture()
        self.assertEqual(normalize_direct_candidates(DirectExtraction.model_validate(extraction),packet)['validation']['normalized_records'],1)

    def test_percent_requires_explicit_supported_denominator(self):
        packet, extraction = self.fixture()
        packet['metric_catalog']['margin'] = {'label':'Margin', 'unit':'percent', 'denominator':'revenue'}
        r=extraction['records'][0]
        r.update(metric='Margin',metric_id='margin',value='1.2',upper=None,value_relation='approx',unit='percent')
        self.assertEqual(normalize_direct_candidates(extraction,packet)['records'],[])
        r['denominator']='revenue'
        out=normalize_direct_candidates(extraction,packet)
        self.assertEqual(out['records'][0]['value_decimal'],'1.2')
        self.assertEqual(out['records'][0]['denominator'],'revenue')

    def test_entity_dimensions_come_only_from_explicit_catalog(self):
        packet,extraction=self.fixture()
        r=extraction['records'][0];r['accounting_basis']='reported_dimensioned'
        self.assertEqual(normalize_direct_candidates(extraction,packet)['records'],[])
        packet['entity_catalog'][0]['dimensions']={'segment':'provided-member'}
        out=normalize_direct_candidates(extraction,packet)
        self.assertEqual(out['records'][0]['dimensions'],{'segment':'provided-member'})
        r['accounting_basis']='reported_consolidated'
        self.assertEqual(normalize_direct_candidates(extraction,packet)['records'],[])

    def test_no_records_no_implicit_sample(self):
        packet,_=self.fixture()
        out=normalize_direct_candidates({},packet)
        self.assertEqual(out['records'],[])
        self.assertEqual(out['raw_candidates'],[])
        self.assertEqual(out['validation']['input_records'],0)
