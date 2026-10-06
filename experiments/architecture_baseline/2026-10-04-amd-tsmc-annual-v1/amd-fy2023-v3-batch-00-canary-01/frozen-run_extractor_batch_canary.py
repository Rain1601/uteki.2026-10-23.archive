"""One explicit table batch from a frozen model-selected source scope."""
import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from run_extractor_protocol_revision import prepare_revision
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.direct_extraction import run_direct_extraction
from uteki.infrastructure.research_data.financial_records import digest


def table_batch_catalog(packet, parent_ref):
    blocks = packet['blocks']
    ordinals = [b.get('ordinal') for b in blocks]
    if any(type(value) is not int or value < 1 for value in ordinals) or len(set(ordinals)) != len(ordinals):
        raise ValueError('unique positive source ordinals required')
    if len({b['block_id'] for b in blocks}) != len(blocks):
        raise ValueError('unique source blocks required')
    blocks = sorted(blocks, key=lambda block: block['ordinal'])
    tables = [b for b in blocks if b['type'] == 'table']
    if not tables:
        raise ValueError('selected parent contains no source table')
    batches = []
    for index, table in enumerate(tables):
        selected = [b for b in blocks if b['block_id'] == table['block_id'] or
                    (b['type'] != 'table' and abs(b['ordinal']-table['ordinal']) <= 2)]
        batches.append({'batch_index': index, 'table_block_id': table['block_id'], 'table_ordinal': table['ordinal'],
                        'block_ids': [b['block_id'] for b in selected],
                        'source_text_characters': sum(len(b['text']) for b in selected),
                        'full_blocks_json_bytes': len(json.dumps(selected, ensure_ascii=False).encode())})
    covered = {bid for batch in batches for bid in batch['block_ids']}
    catalog = {'schema_version': 'source-table-batches-v1', 'parent_run_ref': parent_ref,
        'company_id': packet['company_id'], 'source_snapshot_id': packet['source']['source_snapshot_id'],
        'source_sha256': packet['source']['source_sha256'], 'parent_packet_id': packet['packet_id'],
        'selection_rule': 'Tables in source ordinal order; each table plus non-table blocks within two original ordinals, only from frozen parent scope.',
        'parent_selected_block_count': len(blocks), 'source_document_block_count': packet['coverage']['document_block_count'],
        'batches': batches, 'unassigned_parent_block_ids': [b['block_id'] for b in blocks if b['block_id'] not in covered],
        'limits': ['Neighbor rule does not prove that every needed caption or note is present.',
                   'Unassigned prose and unselected document blocks are not completed by table batches.',
                   'One batch is partial source coverage, never whole core-package acceptance.']}
    return {**catalog, 'catalog_id': 'table-batches-'+digest(catalog)[:24]}


def select_batch(catalog, index):
    if type(index) is not int or not 0 <= index < len(catalog['batches']):
        raise ValueError('explicit available batch index required')
    return deepcopy(catalog['batches'][index])


async def run(args):
    job, feedback = prepare_revision(args.dataset, args.parent, args.prompt)
    parent_packet = json.loads((args.parent/'packet.json').read_text())
    catalog = table_batch_catalog(parent_packet, feedback['parent_run_ref'])
    batch = select_batch(catalog, args.batch_index)
    job['block_ids'] = batch['block_ids']
    job['task'] = ('Extract the reported financial observations established in this explicitly selected single table batch '
        'and its delivered nearby source context. Follow the supplied catalogs and source wording. This is one partial '
        'batch, not the full annual financial package. Do not extract from undelivered tables or treat out-of-batch '
        'metrics as absent from the filing. Preserve annual comparatives or instant balances actually present. '
        'Missing header/unit context remains a gap; other batches remain pending.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'batch-catalog.json', catalog)
    catalog_ref = {'path': str(output/'batch-catalog.json'), 'sha256': digest((output/'batch-catalog.json').read_bytes()),
                   'catalog_id': catalog['catalog_id']}
    coverage = {'schema_version': 'batch-canary-coverage-v1', 'batch_catalog_ref': catalog_ref,
        'selected_batch_index': args.batch_index, 'selected_block_ids': batch['block_ids'],
        'pending_batch_indexes': [b['batch_index'] for b in catalog['batches'] if b['batch_index'] != args.batch_index],
        'unassigned_parent_block_ids': catalog['unassigned_parent_block_ids'], 'core_package_complete': False,
        'semantic_acceptance': 'not_evaluated'}
    write_new(output/'coverage.json', coverage)
    feedback['batch_scope'] = coverage
    feedback['instructions'] = [
        'The program diagnostics refer to the parent draft, not corrected financial values.',
        'Re-read only the selected table and delivered context. Return a complete extraction for this batch only.',
        'Use supported accounting_basis tokens, preserve exact numeric punctuation and exact source evidence.',
        'Preserve source wording. Missing catalog mappings stay unresolved; never guess aliases, currencies or IDs.',
        'Other batches and unassigned prose remain pending. This is not whole-document or core-package completion.']
    write_new(output/'protocol-feedback.json', feedback)
    feedback_ref = {'path': str(output/'protocol-feedback.json'), 'sha256': digest((output/'protocol-feedback.json').read_bytes())}
    job['revision_feedback'] = {**feedback, 'review_sha256': feedback_ref['sha256'], 'review_ref': feedback_ref}
    job['batch_scope'] = coverage
    config = json.loads(args.model_config.read_text())
    config = {**config, 'model': config['extractor_model'], 'reasoning_effort': config['extractor_reasoning_effort']}
    write_new(output/'model-config.input.json', config)
    write_new(output/'batch-job.json', job)
    for name in ('run_extractor_batch_canary.py', 'run_extractor_protocol_revision.py'):
        (output/('frozen-'+name)).write_bytes((Path(__file__).parent/name).read_bytes())
    try:
        result = await run_direct_extraction(args.dataset, job, output/'extraction-01', strategy='direct',
                                             model_config=config, credentials_root=args.credentials_root)
        print(json.dumps({'batch_index': args.batch_index, 'total_batches': len(catalog['batches']),
            'core_package_complete': False, **{key: result.get(key) for key in
             ('status', 'raw_record_count', 'normalized_record_count', 'unresolved_count', 'dataset')}}, ensure_ascii=False), flush=True)
    finally:
        write_new(output/'manifest.json', {'files': {str(path.relative_to(output)): digest(path.read_bytes())
            for path in output.rglob('*') if path.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('dataset', 'parent', 'model-config', 'credentials-root', 'prompt', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--batch-index', type=int, required=True)
    asyncio.run(run(parser.parse_args()))
