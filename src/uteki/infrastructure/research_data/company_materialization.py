"""Immutable, source-bound company datasets; no network, model or issuer defaults.

The generic US GAAP adapter recognizes exact standard tags. Dimensions remain
opaque qualified entities; company-specific segment names are never guessed.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import inspect
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import duckdb
from lxml import html, etree

from uteki.agents.reading.document_reader import DocumentReader
from uteki.domain.research_data.query_contract import (
    DataQuery, QueryResult, ResearchRecord, Period, SOURCE_PERIOD_VERSION, export_query_schema,
)
from uteki.infrastructure.document_sources.sec_index import parse_sec_source
from uteki.infrastructure.document_sources.parsed_package import (
    EXPORT as PARSED_EXPORT, PARSER as HTML_PARSER, build_parsed_package,
)
from uteki.domain.documents import SourceBlock
from uteki.infrastructure.document_sources.earnings import earnings_outline
from uteki.infrastructure.document_sources.company_acquisition import _mime
from uteki.infrastructure.document_sources.sec import normalize_text
from .financial_records import digest, local_name, one_text, parse_number, dom_path_query
from .query_dataset import DDL, contained, save

ADAPTER = 'us-gaap-inline-v1'


def implementation_fingerprint():
    """Invalidate reuse when a parser, normalizer or exported contract changes."""
    paths = {Path(__file__), *(Path(inspect.getfile(obj)) for obj in (
        parse_sec_source, earnings_outline, _mime, normalize_text, parse_number,
        ResearchRecord, save, DocumentReader, build_parsed_package, SourceBlock))}
    return digest({path.name: digest(path.read_bytes()) for path in sorted(paths)})


class MaterializationCancelled(RuntimeError):
    pass


def _check_cancelled(should_stop):
    if should_stop and should_stop():
        raise MaterializationCancelled('materialization_cancelled')
CONCEPTS = {
    'RevenueFromContractWithCustomerExcludingAssessedTax': 'revenue',
    'RevenueFromContractWithCustomerIncludingAssessedTax': 'revenue_including_assessed_tax',
    'Revenues': 'revenue',
    'SalesRevenueNet': 'revenue',
    'OperatingIncomeLoss': 'operating_income',
    'NetIncomeLoss': 'net_income',
    'NetCashProvidedByUsedInOperatingActivities': 'operating_cash_flow',
    'PaymentsToAcquirePropertyPlantAndEquipment': 'capex_cash_payments',
}


def metric_catalog():
    return {m: {'metric_id': m, 'label': m, 'unit': 'USD', 'denominator': None,
                'definition': ('Positive cash payments to acquire PPE; not total investment.' if m == 'capex_cash_payments' else m),
                'definition_version': ADAPTER, 'aggregation': 'no_implicit_sum', 'aliases': [m]}
            for m in sorted(set(CONCEPTS.values()))}


def _period(context):
    if any(local_name(x) == 'instant' for x in context.iter()):
        return Period(kind='instant', start=None, end=one_text(context, 'instant'))
    start, end = date.fromisoformat(one_text(context, 'startdate')), date.fromisoformat(one_text(context, 'enddate'))
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    kind = {3: 'quarter', 6: 'ytd', 9: 'ytd', 12: 'year'}.get(months)
    if kind is None:
        raise ValueError('unsupported_duration')
    try:
        return Period(kind=kind, start=start, end=end)
    except ValueError:
        return Period(kind=kind, start=start, end=end, basis='source')


def _index(raw, doc, folder, *, company_id):
    sid = doc['source_id']
    if doc['mime_type'] in ('text/html', 'application/xhtml+xml'):
        package = build_parsed_package(raw, {
            'company_id': company_id, 'document_id': sid, 'source_snapshot_id': sid,
            'source_url': doc['source_url'], 'raw_sha256': doc.get('content_sha256', doc.get('sha256')),
            'form_type': doc['form'], 'report_period_end': doc.get('period_end'),
            'available_at': doc.get('filed_at') or doc.get('published_at'),
            'parser_version': HTML_PARSER, 'export_version': PARSED_EXPORT,
        }, folder)
        index, blocks, assets = package['index'], package['blocks'], package['assets']
        diagnostics = [{'layer': 'reading', 'reason': 'image_reference_only', 'source_snapshot_id': sid,
                        'asset_id': a['asset_id']} for a in assets]
        diagnostics.extend({'layer': 'indexing', 'reason': d['code'], 'source_snapshot_id': sid,
                            'severity': d['severity'], 'detail': d['message'], 'node_id': d.get('node_id')}
                           for d in index.get('diagnostics', ()))
        DocumentReader(folder)  # Existing reader verifies the compatibility manifest.
        return index, blocks, diagnostics
    elif doc['mime_type'] == 'application/pdf':
        command = shutil.which('pdftotext')
        if command is None:
            raise ValueError('pdf_text_extractor_unavailable')
        # Byte input only; the subprocess has no URLs and no shell interpretation.
        result = subprocess.run([command, '-bbox-layout', '-', '-'], input=raw, capture_output=True, timeout=45, check=True)
        root = etree.fromstring(result.stdout, etree.XMLParser(resolve_entities=False, no_network=True))
        blocks = []
        for page_number, page in enumerate(root.findall('.//{*}page'), 1):
            for element in page.findall('.//{*}block'):
                text = ' '.join(' '.join(w.text or '' for w in line.findall('{*}word')) for line in element.findall('{*}line')).strip()
                if not text:
                    continue
                blocks.append({'block_id': f'block-{len(blocks)+1:06}-{digest(text.encode())[:8]}',
                    'ordinal': len(blocks)+1, 'type': 'paragraph', 'text': text, 'text_hash': digest(text.encode()),
                    'pdf_page': page_number, 'reported_page': None, 'dom_path': None, 'table': None,
                    'bbox': [float(element.get(k)) for k in ('xMin', 'yMin', 'xMax', 'yMax')],
                    'page_size': [float(page.get('width')), float(page.get('height'))], 'style_signature': {},
                    'source_anchor': None, 'asset_id': None, 'layout_role': None})
        if not blocks:
            raise ValueError('pdf_no_extractable_text')
        index = earnings_outline(blocks, sid, digest(raw), sid, doc['form'], 'Source document', parser_version='pdf-bbox-text-v1')
        assets = []
        diagnostics = [{'layer': 'reading', 'reason': 'pdf_images_tables_and_ocr_not_evaluated', 'source_snapshot_id': sid}]
    else:
        raise ValueError('unsupported_source_mime_type')
    if not blocks:
        raise ValueError('no_readable_blocks')
    folder.mkdir(parents=True)
    save(folder/'index.json', index)
    (folder/'blocks.jsonl').write_text(''.join(json.dumps(b, ensure_ascii=False)+'\n' for b in blocks))
    save(folder/'assets.json', {'assets': assets})
    save(folder/'manifest.json', {'status': 'candidate', 'source_snapshot_id': sid, 'source_sha256': digest(raw),
        'artifacts': {name: {'sha256': digest((folder/name).read_bytes())} for name in ('index.json', 'blocks.jsonl', 'assets.json')}})
    DocumentReader(folder)  # Verify the format and stored hashes before publishing.
    return index, blocks, diagnostics


def extract_inline_records(raw, doc, company, index, blocks, artifact):
    if doc['mime_type'] not in ('text/html', 'application/xhtml+xml'):
        return [], {}, [], []
    tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8'))
    by_id = {}
    for element in tree.iter():
        if element.get('id'):
            by_id.setdefault(element.get('id'), []).append(element)
    block_elements = {}
    for block in blocks:
        if block.get('dom_path'):
            found = tree.xpath(dom_path_query(block['dom_path']))
            if len(found) == 1:
                block_elements[found[0]] = block
    records, evidence, gaps, fiscal = [], {}, [], []
    namespace_values = {}
    for element in tree.iter():
        for key, value in element.attrib.items():
            if key.startswith('xmlns:'):
                namespace_values.setdefault(key[6:], set()).add(value)
    namespaces = {key: next(iter(values)) for key, values in namespace_values.items() if len(values) == 1}
    fiscal_years = {e.text_content().strip() for e in tree.iter()
                    if (e.get('name') or '').split(':')[-1] == 'DocumentFiscalYearFocus'
                    and namespaces.get((e.get('name') or '').split(':')[0])
                    and 'xbrl.sec.gov/dei/' in namespaces.get((e.get('name') or '').split(':')[0])}
    fiscal_year = int(next(iter(fiscal_years))) if len(fiscal_years) == 1 and re.fullmatch(r'\d{4}', next(iter(fiscal_years))) else None
    fiscal_focuses = {e.text_content().strip() for e in tree.iter()
                      if (e.get('name') or '').split(':')[-1] == 'DocumentFiscalPeriodFocus'
                      and namespaces.get((e.get('name') or '').split(':')[0])
                      and 'xbrl.sec.gov/dei/' in namespaces.get((e.get('name') or '').split(':')[0])}
    focus = next(iter(fiscal_focuses)) if len(fiscal_focuses) == 1 else None
    fiscal_quarter = int(focus[1]) if focus in ('Q1', 'Q2', 'Q3', 'Q4') else None
    cik = str(company.get('cik', '')).lstrip('0')
    for ordinal, tag in enumerate(tree.iter()):
        if local_name(tag) != 'nonfraction':
            continue
        concept = tag.get('name') or ''
        prefix, _, local = concept.partition(':')
        namespace = namespaces.get(prefix)
        if local not in CONCEPTS or not namespace or not re.fullmatch(r'https?://fasb.org/us-gaap/\d{4}(?:-\d{2}-\d{2})?', namespace):
            gaps.append({'layer': 'normalization', 'reason': 'unmapped_concept', 'source_snapshot_id': doc['source_id'], 'concept': concept})
            continue
        try:
            contexts, units = by_id.get(tag.get('contextref'), []), by_id.get(tag.get('unitref'), [])
            if len(contexts) != 1 or len(units) != 1:
                raise ValueError('ambiguous_context_or_unit')
            context = contexts[0]
            identifier = one_text(context, 'identifier')
            if not cik or not identifier.isdigit() or identifier.lstrip('0') != cik:
                raise ValueError('context_company_mismatch')
            dimensions = {}
            for member in context.iter():
                if local_name(member) == 'typedmember':
                    raise ValueError('unsupported_typed_dimension')
                if local_name(member) == 'explicitmember':
                    axis, value = member.get('dimension'), member.text_content().strip()
                    if not axis or not value or axis in dimensions:
                        raise ValueError('ambiguous_dimensions')
                    dimensions[axis] = value
            period = _period(context)
            if period.kind == 'instant':
                raise ValueError('duration_metric_has_instant_context')
            number = parse_number(tag, units[0])
            block = next((block_elements[a] for a in [tag, *tag.iterancestors()] if a in block_elements), None)
            if block is None or number['raw_value'] not in block['text']:
                raise ValueError('unlocated_fact')
            entity = company['company_id'] if not dimensions else company['company_id']+'-dimensions-'+digest(dimensions)[:16]
            eid = 'ev-'+digest([doc['source_id'], ordinal, concept, tag.get('contextref')])[:24]
            source_evidence = {'evidence_id': eid, 'source_snapshot_id': doc['source_id'], 'source_sha256': digest(raw),
                'index_id': index['index_id'], 'block_id': block['block_id'], 'text_hash': block['text_hash'],
                'quote': number['raw_value'], 'dom_path': block['dom_path'], 'fact_dom_path': tree.getroottree().getpath(tag),
                'fact_id': tag.get('id'), 'concept': concept, 'context_ref': tag.get('contextref'), 'unit_ref': tag.get('unitref'),
                'context_xml': html.tostring(context, encoding='unicode'), 'unit_xml': html.tostring(units[0], encoding='unicode'),
                'number_metadata': number, 'source_url': doc['source_url'], 'context_block_ids': [block['block_id']]}
            row = ResearchRecord(schema_version=SOURCE_PERIOD_VERSION,
                record_id='obs-'+digest([doc['source_id'], ordinal, concept])[:24], record_type='metric',
                entity_id=entity, metric_id=CONCEPTS[local], period=period, value_kind='actual',
                value_decimal=number['value_decimal'], value_relation='eq', unit=number['unit'],
                accounting_basis='reported_dimensioned' if dimensions else 'reported_consolidated', dimensions=dimensions,
                available_at=doc['filed_at'] or doc.get('published_at'), source_snapshot_id=doc['source_id'],
                evidence_ids=(eid,), summary=f'{concept}; reported inline XBRL fact',
                origin={'artifact': artifact, 'record_index': ordinal, 'adapter': ADAPTER, 'concept': concept,
                        'context_ref': tag.get('contextref'), 'raw_dimensions': dimensions, 'entity_identifier': identifier},
                normalization_notes=('Exact standard concept mapping; dimensions are opaque, not interpreted as named segments.',
                                     'Candidate source fact; not independently adopted.')).model_dump(mode='json')
            records.append(row)
            evidence[eid] = source_evidence
            if not dimensions and fiscal_year and str(period.end) == doc.get('period_end'):
                value = None
                if period.kind == 'year' and fiscal_quarter is None:
                    value = {'fiscal_year': fiscal_year, 'period': period.model_dump(mode='json')}
                elif period.kind == 'quarter' and fiscal_quarter:
                    value = {'fiscal_year': fiscal_year, 'fiscal_quarter': fiscal_quarter, 'period': period.model_dump(mode='json')}
                if value and value not in fiscal:
                    fiscal.append(value)
        except (ValueError, KeyError) as error:
            gaps.append({'layer': 'normalization', 'reason': str(error), 'source_snapshot_id': doc['source_id'], 'concept': concept, 'fact_id': tag.get('id')})
    return records, evidence, gaps, fiscal


def _numeric_coverage(record_count, evidence_count, gap_count):
    return {'status': 'candidate_records' if record_count else 'no_supported_records',
        'record_count': record_count, 'evidence_count': evidence_count, 'gap_count': gap_count,
        'adapter': ADAPTER, 'supported_taxonomy': 'US_GAAP', 'supported_currencies': ['USD'],
        'supported_metric_ids': sorted(set(CONCEPTS.values())),
        'period_support': 'complete_month_boundaries_only',
        'counting_basis': 'candidate inline fact occurrences, not unique reviewed financial facts',
        'financial_package_completeness': 'not_evaluated', 'semantic_review': 'not_evaluated',
        'adoption': 'candidate'}


def _source_stages(raw, doc, index, blocks, rows, refs, extraction_gaps):
    tables = [b for b in blocks if b['type'] == 'table']
    html_source = doc['mime_type'] in ('text/html', 'application/xhtml+xml')
    return {'schema_version': 'source-stage-coverage-v1',
        'original': {'status': 'hash_verified', 'byte_count': len(raw), 'source_sha256': digest(raw)},
        'reading': {'status': 'indexed', 'parser_version': index['parser_version'], 'block_count': len(blocks),
                    'block_type_counts': dict(sorted(Counter(b['type'] for b in blocks).items())),
                    'index_diagnostic_count': len(index.get('diagnostics', []))},
        'tables': {'status': 'structure_parsed' if html_source else 'unsupported_pdf_table_structure',
                   'table_node_count': len(tables),
                   'tables_with_cells': sum(bool(b['table'] and b['table']['cells']) for b in tables),
                   'tables_without_cells': sum(not b['table'] or not b['table']['cells'] for b in tables),
                   'cell_count': sum(len(b['table']['cells']) for b in tables if b['table']),
                   'layout_role_counts': dict(sorted(Counter(b['layout_role'] or 'unclassified' for b in tables).items())),
                   'counting_basis': 'HTML table nodes; parent cell text may include nested table text',
                   'financial_table_semantics': 'not_evaluated'},
        'numeric': _numeric_coverage(len(rows), len(refs), len(extraction_gaps))}


def materialize_sources(source_run: dict, workspace: Path, destination: Path, *, should_stop=None) -> dict:
    """Build from verified acquisition bytes; partial sources retain explicit gaps."""
    workspace, destination = Path(workspace).resolve(), Path(destination).resolve()
    _check_cancelled(should_stop)
    if destination.exists():
        raise FileExistsError('immutable dataset already exists')
    company = source_run.get('company')
    if not isinstance(company, dict) or not re.fullmatch(r'sec-\d+', str(company.get('company_id', ''))):
        raise ValueError('explicit SEC company identity required')
    if not str(company.get('cik', '')).isdigit() or int(company['company_id'][4:]) != int(company['cik']):
        raise ValueError('company_id and CIK disagree')
    documents = source_run.get('documents')
    if not isinstance(documents, list):
        raise ValueError('explicit acquisition documents required')
    cutoff = source_run.get('as_of') or source_run.get('scope', {}).get('as_of') or source_run.get('config', {}).get('as_of')
    cutoff = date.fromisoformat(cutoff) if cutoff else None
    if cutoff is None:
        raise ValueError('explicit acquisition as_of required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.materialize-', dir=destination.parent) as temporary:
        work = Path(temporary)/'dataset'; work.mkdir()
        sources, records, evidence, gaps, inputs, seen = [], [], {}, list(source_run.get('gaps', [])), [], set()
        verified_originals, verified_bytes = 0, 0
        for doc in documents:
            _check_cancelled(should_stop)
            sid = doc.get('source_id')
            if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', sid) or sid in seen:
                raise ValueError('missing or duplicate source identity')
            seen.add(sid)
            if 'company_id' in doc and doc['company_id'] != company['company_id']:
                raise ValueError('document company identity mismatch')
            if doc.get('content_sha256') is not None and doc.get('sha256') is not None and doc['content_sha256'] != doc['sha256']:
                raise ValueError('document source hash declarations conflict')
            path = doc.get('path'); expected = doc.get('content_sha256', doc.get('sha256'))
            if not isinstance(path, str) or Path(path).is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', str(expected)):
                raise ValueError('explicit relative source path and SHA256 required')
            raw = contained(workspace, path).read_bytes()
            if digest(raw) != expected:
                raise ValueError('source bytes hash mismatch')
            verified_originals += 1
            verified_bytes += len(raw)
            declared_mime_type = doc['mime_type']
            detected_mime_type = _mime(raw)
            if detected_mime_type in ('text/html', 'application/xhtml+xml', 'application/pdf'):
                doc = {**doc, 'mime_type': detected_mime_type}
            if not isinstance(doc.get('source_url'), str) or not doc['source_url'].startswith(('https://', 'http://')) or not doc.get('form'):
                raise ValueError('explicit source URL and form required')
            available = doc.get('filed_at') or doc.get('published_at')
            if doc.get('status') not in ('downloaded', 'frozen') or doc.get('as_of_eligible') is False or not available:
                gaps.append({'layer': 'materialization', 'source_snapshot_id': sid, 'reason': 'source_not_eligible_or_date_unverified'}); continue
            if date.fromisoformat(available) > cutoff:
                gaps.append({'layer': 'materialization', 'source_snapshot_id': sid, 'reason': 'not_available_at_cutoff'}); continue
            raw_path = 'raw/'+sid+('.pdf' if doc['mime_type']=='application/pdf' else '.html')
            (work/raw_path).parent.mkdir(exist_ok=True); (work/raw_path).write_bytes(raw)
            try:
                index, blocks, index_gaps = _index(raw, doc, work/'indexes'/sid, company_id=company['company_id'])
            except (ValueError, etree.ParserError, subprocess.SubprocessError, OSError) as error:
                gaps.append({'layer': 'indexing', 'source_snapshot_id': sid, 'reason': str(error)[:300]}); continue
            rows, refs, extraction_gaps, fiscal = extract_inline_records(raw, doc, company, index, blocks, raw_path)
            _check_cancelled(should_stop)
            parsed_package = None
            if doc['mime_type'] in ('text/html', 'application/xhtml+xml'):
                package_manifest = json.loads((work/'indexes'/sid/'manifest.json').read_bytes())
                parsed_package = {'export_version': package_manifest['export_version'],
                    'package_id': package_manifest['package_id'], 'manifest_path': 'indexes/'+sid+'/manifest.json',
                    'manifest_sha256': digest((work/'indexes'/sid/'manifest.json').read_bytes()),
                    'source_path': 'indexes/'+sid+'/source.json', 'document_path': 'indexes/'+sid+'/document.html',
                    'status': 'candidate_parsed_material', 'semantic_review': 'not_reviewed'}
            sources.append({'source_snapshot_id': sid, 'company_id': company['company_id'], 'source_url': doc['source_url'],
                'source_sha256': expected, 'document_id': sid, 'index_id': index['index_id'], 'index_folder': 'indexes/'+sid,
                'raw_file': raw_path, 'raw_file_sha256': expected, 'form': doc['form'], 'period_end': doc.get('period_end'),
                'declared_mime_type': declared_mime_type, 'parsed_mime_type': doc['mime_type'],
                'available_at': available, 'status': 'candidate', 'fiscal_periods': fiscal,
                **({'parsed_package': parsed_package} if parsed_package else {}),
                'capabilities': ['read_context', 'literal_search', 'source_bytes'] + (
                    ['html_table_structure', 'parsed_document_package'] if parsed_package else []),
                'stage_coverage': _source_stages(raw, doc, index, blocks, rows, refs, extraction_gaps),
                'image_block_count': sum(b['type']=='image' for b in blocks)})
            records.extend(rows); evidence.update(refs); gaps.extend(index_gaps+extraction_gaps)
            inputs.append({'path': raw_path, 'sha256': expected, 'source_snapshot_id': sid, 'adapter': ADAPTER})
        metrics = metric_catalog()
        save(work/'sources.json', sources); save(work/'records.json', {'rows': records}); save(work/'evidence.json', evidence); save(work/'metrics.json', metrics)
        for name, model in [('query', DataQuery), ('record', ResearchRecord), ('result', QueryResult)]:
            save(work/f'schemas/{name}.schema.json', export_query_schema(model, version=SOURCE_PERIOD_VERSION))
        (work/'schema.sql').write_text(DDL)
        db = duckdb.connect(str(work/'research.duckdb'))
        try:
            db.execute(DDL)
            for s in sources:
                db.execute('INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)', [s[k] for k in ('source_snapshot_id','company_id','form','period_end','available_at')]+[json.dumps(s)])
            for r in records:
                p=r['period']
                db.execute('INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    [r['record_id'],r['entity_id'],r['metric_id'],p['kind'],p['start'],p['end'],r['value_kind'],r['value_decimal'],None,'eq',r['unit'],r['accounting_basis'],r['available_at'],r['source_snapshot_id'],'candidate',json.dumps(r)])
            for eid, ev in evidence.items(): db.execute('INSERT INTO evidence VALUES (?, ?, ?)', [eid,ev['source_snapshot_id'],json.dumps(ev)])
            for mid, metric in metrics.items(): db.execute('INSERT INTO metric_definitions VALUES (?, ?)', [mid,json.dumps(metric)])
            db.execute('CHECKPOINT')
        finally:
            db.close()
        identity={'adapter': ADAPTER, 'inputs': inputs, 'company': company, 'records_sha256': digest(records),
                  'implementation_sha256': implementation_fingerprint(), 'acquisition_sha256': digest(source_run)}
        stage_coverage = {'schema_version': 'materialization-stage-coverage-v1',
            'originals': {'selected_document_count': len(documents), 'hash_verified_document_count': verified_originals,
                          'byte_count': verified_bytes, 'indexed_source_count': len(sources)},
            'reading': {'indexed_source_count': len(sources),
                        'block_count': sum(s['stage_coverage']['reading']['block_count'] for s in sources)},
            'tables': {key: sum(s['stage_coverage']['tables'][key] for s in sources)
                       for key in ('table_node_count', 'tables_with_cells', 'tables_without_cells', 'cell_count')},
            'numeric': _numeric_coverage(len(records), len(evidence), sum(g.get('layer') == 'normalization' for g in gaps))}
        stage_coverage['tables'].update(financial_table_semantics='not_evaluated',
            counting_basis='HTML table nodes, not financial statements or unique facts')
        manifest={'schema_version': SOURCE_PERIOD_VERSION, 'snapshot_id': 'query-'+digest(identity)[:24], 'source_policy_id': 'local-frozen-v1',
            'status': 'candidate' if sources else 'unavailable', 'company': company, 'source_count':len(sources), 'record_count':len(records),
            'evidence_count':len(evidence), 'materialization': identity, 'stage_coverage': stage_coverage,
            'gaps':gaps, 'model_calls':0, 'build_spec':{'inputs':inputs},
            'limits':['Exact US GAAP inline concepts only; USD only; no company-specific taxonomy inference.',
                      'Dimensioned facts retain opaque qualified entity IDs; no implicit consolidation or segment sum.',
                      'PDF text only; images and table semantics not evaluated. No adoption or semantic completeness claim.'],
            'files':{str(p.relative_to(work)):digest(p.read_bytes()) for p in work.rglob('*') if p.is_file()}}
        save(work/'manifest.json',manifest)
        _check_cancelled(should_stop)
        work.rename(destination)
        return manifest
