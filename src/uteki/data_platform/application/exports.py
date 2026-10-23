"""Human and tabular views of an existing delivery; no extraction or model call."""
import csv
import io
import json
from pathlib import Path

from ..contracts.common import CatalogError, canonical, digest


def _period(record):
    period = record.get('period') or {}
    return period.get('label') or json.dumps(period,ensure_ascii=False,sort_keys=True)


def _source(item):
    locator = item.get('locator') or {}
    pages = sorted({p['page_number'] for p in locator.get('locations',[]) if 'page_number' in p})
    where = 'PDF physical page '+','.join(map(str,pages)) if pages else locator.get('dom_path','source location unavailable')
    if locator.get('kind')=='document_metadata': where='Registered metadata / '+locator['projection']
    if locator.get('block_id'): where += '; block '+locator['block_id']
    if locator.get('passage_path'): where += '; passage '+locator['passage_path']
    if locator.get('section_path'): where += '; section '+locator['section_path']+f'; blocks [{locator["block_start"]}, {locator["block_end_exclusive"]})'
    if 'row' in locator: where += f'; row {locator["row"]}, column {locator["column"]} (zero-based)'
    asset = item.get('asset_ref') or {}
    version = asset.get('parse_id') or asset.get('build_id','')
    return f'{where}; version {version}; {item.get("source_url") or "source URL unavailable"}'


def render_markdown(delivery):
    lines = ['# Data delivery','',f'Status: {delivery["business_status"]}',
        f'Delivery: {delivery["delivery_id"]}',
        'Semantic sufficiency is independently reviewed; structural validation alone does not establish correctness.','']
    if delivery.get('completion_basis'):
        lines += ['Task completion does not certify that the original source or parsing has no limitations.','']
    for need in delivery['needs']:
        lines += [f'## {need["need_id"]} — {need["status"]}','']
        if need.get('note'): lines += [need['note'],'']
        for gap in need['gaps']: lines += ['Gap: '+gap,'']
        for limitation in need.get('limitations',[]): lines += ['Limitation: '+limitation,'']
        for claim in need.get('source_claims',[]):
            lines += ['Source-backed interpretation (semantic correctness not independently verified): '+claim['statement'],'']
            for proof in claim['support']:
                lines += ['Source quote (exact text match checked):', '',
                          '> '+proof['quote'].replace('\n','\n> '), '',
                          _source(proof), '']
    for coverage in delivery.get('read_coverage',[]):
        ranges = ', '.join(f'[{start}, {end})' for start,end in coverage['ranges']) or 'empty'
        missing = ', '.join(f'[{start}, {end})' for start,end in coverage['missing_ranges']) or 'none'
        lines += ['## Stored section coverage (code-generated)', '',
            f'Section: {coverage["section_path"]}; version: {coverage["asset_ref"]["parse_id"]}; include descendants: {coverage["include_descendants"]}',
            f'Blocks: {coverage["delivered_blocks"]}/{coverage["total_blocks"]}; zero-based ranges [start, end), end excluded: {ranges}.',
            'Cited pages: '+', '.join(f'[{p["block_start"]}, {p["block_end_exclusive"]})' for p in coverage['pages'])+'.',
            f'Missing ranges: {missing}; stored section complete: {coverage["stored_section_complete"]}.',
            'This checks cited stored content coverage, not original PDF parsing quality.', '']
    for index,item in enumerate(delivery.get('metadata',[]),1):
        lines += [f'## Registered metadata {index}','',_source(item),'',
                  'Registration and parser output; not original document text or verified financial facts.','',
                  '```json',json.dumps({k:v for k,v in item.items() if k not in
                      {'result_ref','result_handle','tool_options','capabilities'}},ensure_ascii=False,indent=2),'```','']
    for record in delivery['records']:
        lines += [f'## {record.get("metric") or record.get("concept_id") or record["record_id"]} — {_period(record)}','',
            f'Value: {record["value"]}; unit: {json.dumps(record["unit"],ensure_ascii=False)}',
            f'Source value: {record["raw_value"]}; scale: {record.get("scale")}',
            f'Entity: {record.get("entity_identifier")}; scope: {record.get("entity_scope", "see source evidence")}',
            _source(record),'']
        if record.get('interpretation'): lines += ['Interpretation: '+record['interpretation'],'']
    for calculation in delivery['calculations']:
        lines += [f'## Calculation: {calculation["calc_id"]}','',
            f'{calculation["formula"]} = {calculation["value"]} ({calculation["unit"]})',
            'Comparison basis: '+calculation['comparison_basis'],'']
        for limitation in calculation['limitations']: lines += ['Limitation: '+limitation,'']
    for index,evidence in enumerate(delivery['evidence'],1):
        lines += [f'## Source evidence {index}','',_source(evidence),'']
        content = evidence.get('content') or {}
        if content.get('type')=='passage':
            lines += ['Complete source group; member blocks: '+', '.join(content['member_block_ids']),
                      'Original member text and positions are included in this evidence package.','']
        if content.get('type')=='section_page':
            lines += ['Section page; member blocks: '+', '.join(content['member_block_ids']),
                      'This page alone does not establish complete section coverage. Original members follow in this evidence package.','']
        if content.get('text'): lines += [content['text'],'']
        table = content.get('table')
        if table:
            lines += ['Table cells (row, column, span, source text):','']
            for cell in table.get('cells',[]):
                lines.append(f'- ({cell["row"]}, {cell["column"]}), span {cell["row_span"]}×{cell["column_span"]}: {cell["text"]}')
            lines.append('')
        quality = evidence.get('quality') or {}
        if quality.get('issues'): lines += ['Source issues: '+json.dumps(quality['issues'],ensure_ascii=False),'']
    return '\n'.join(lines).rstrip()+'\n'


def render_csv(delivery):
    output = io.StringIO(newline='')
    fields = ['record_id','metric','raw_value','value','unit','scale','period','entity','entity_scope',
              'asset_ref','locator','source_url','source_object','semantic_verification']
    writer = csv.DictWriter(output,fieldnames=fields);writer.writeheader()
    for record in delivery['records']:
        row = {k:record.get(k) for k in fields}
        row.update(metric=record.get('metric') or record.get('concept_id'),period=_period(record),entity=record.get('entity_identifier'))
        for key,value in row.items():
            if isinstance(value,(dict,list)): row[key] = json.dumps(value,ensure_ascii=False,sort_keys=True)
        writer.writerow(row)
    return output.getvalue()


def render_calculations_csv(delivery):
    """Export code results with operand references, including unresolved limits."""
    output = io.StringIO(newline='')
    fields = ['result_ref', 'calc_id', 'formula', 'value', 'unit', 'operand_refs',
              'comparison_basis', 'period_policy', 'period_basis', 'limitations',
              'semantic_verification']
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for calculation in delivery['calculations']:
        row = {key: calculation.get(key) for key in fields}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                row[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        writer.writerow(row)
    return output.getvalue()


def export_delivery(delivery, directory):
    """Create a new artifact directory. The final manifest is the completion marker."""
    directory = Path(directory)
    if not directory.is_absolute() or not directory.parent.is_dir() or directory.parent.is_symlink():
        raise CatalogError('INVALID_PATH','explicit absolute output with an existing regular parent is required')
    if delivery.get('schema_version')!='uteki-delivery-v1':
        raise CatalogError('INVALID_REQUEST','export requires the existing shared delivery object')
    bodies = {'delivery.json':canonical(delivery), 'delivery.md':render_markdown(delivery).encode('utf-8')}
    if delivery['records']: bodies['records.csv'] = render_csv(delivery).encode('utf-8')
    if delivery['calculations']:
        bodies['calculations.csv'] = render_calculations_csv(delivery).encode('utf-8')
    directory.mkdir(exist_ok=False)
    for name,body in bodies.items():
        with (directory/name).open('xb') as stream:
            stream.write(body)
    manifest = dict(schema='uteki-delivery-export-v1',delivery_id=delivery['delivery_id'],
        business_status=delivery['business_status'],files={name:dict(sha256=digest(body),byte_length=len(body)) for name,body in bodies.items()})
    with (directory/'manifest.json').open('xb') as stream:
        stream.write(canonical(manifest))
    return manifest
