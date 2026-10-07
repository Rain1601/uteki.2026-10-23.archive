"""Index existing actual artifacts, separating schema validity from quality."""
import hashlib
import json
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def file(path):
    path = ROOT / path
    return {'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def load(path):
    return json.loads((ROOT / path).read_text())


def validate(value, schema, label):
    error = next(jsonschema.Draft202012Validator(schema).iter_errors(value), None)
    if error:
        raise ValueError(f'{label}: schema {error.validator} at {list(error.path)}')


def main():
    entries = []
    package = str(HERE.relative_to(ROOT)) + '/msft/dataset/indexes/msft-2025-10k'
    for name in ('source', 'blocks', 'toc', 'anchors', 'assets', 'index'):
        extension = 'jsonl' if name == 'blocks' else 'json'
        artifact = f'{package}/{name}.{extension}'
        schema = f'{package}/schemas/{name}.schema.json'
        if extension == 'jsonl':
            value = [json.loads(line) for line in (ROOT / artifact).read_text().splitlines()]
        else:
            value = load(artifact)
        for item in value if extension == 'jsonl' else [value]:
            validate(item, load(schema), artifact)
        entries.append({'kind': 'parsed_' + name, 'artifact': file(artifact), 'schema': file(schema),
                        'origin': 'system_parser_from_real_frozen_10k',
                        'schema_check': 'passed', 'semantic_quality': 'not_evaluated_by_this_catalog',
                        'consumer': file('src/uteki/agents/reading/document_reader.py')})
    examples = [
        ('financial_candidates',
         'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/amd-fy2023-cash-flow-batch-v3/extraction-01/normalized.json',
         'src/uteki/domain/research_data/query_contract.py',
         'src/uteki/infrastructure/research_data/direct_normalization.py',
         'Historical real model extraction; six selected fact requirements have candidates; whole-report coverage not claimed.'),
        ('filing_brief',
         'experiments/agent_design/2026-10-07-filing-brief-v1/run-04/revision/brief.json',
         'experiments/agent_design/2026-10-07-filing-brief-v1/run-04/revision/schema.json',
         'src/uteki/agents/filing_brief/consume.py',
         'Real model revision of one complete selected subsection; final content review not completed in run-04.'),
        ('business_draft',
         'experiments/agent_design/2026-10-07-microsoft-agent-independent-v1/self-review-01/revision/draft.json',
         'experiments/agent_design/2026-10-07-microsoft-agent-independent-v1/self-review-01/revision/output_schema.json',
         'src/uteki/presentation/business_map_view.py',
         'Historical real model candidate; content review found missing objects and insufficient claims; not accepted.'),
        ('source_mention_inventory',
         'experiments/agent_design/2026-10-07-business-coverage-v1/run-05/inventory/inventory.json',
         'experiments/agent_design/2026-10-07-business-coverage-v1/run-05/inventory/output_schema.json',
         'src/uteki/agents/business_map/coverage_contract.py',
         'Real model source inventory plus bounded model repair; 148 mentions and 103 block dispositions. Exact locations do not establish semantic completeness.'),
    ]
    for kind, artifact, schema, consumer, limitation in examples:
        value = load(artifact)
        if schema.endswith('.json'):
            validate(value, load(schema), artifact)
            status = 'passed'
        else:
            from uteki.domain.research_data.query_contract import ResearchRecord
            for row in value['records']:
                ResearchRecord.model_validate(row)
            status = 'each_normalized_record_typed_contract_passed'
        entries.append({'kind': kind, 'artifact': file(artifact), 'schema': file(schema),
                        'consumer': file(consumer), 'origin': 'system_agent_real_model_run',
                        'schema_check': status, 'quality_limitation': limitation})
    with (HERE / 'artifact-samples.json').open('x') as stream:
        json.dump({'schema_version': 'real-artifact-sample-index-v1', 'model_calls': 0,
                   'purpose': 'TODO05 actual examples, contracts and consumers; not an end-to-end acceptance score.',
                   'entries': entries}, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'artifacts': len(entries), 'checks': 'passed', 'new_model_calls': 0}))


if __name__ == '__main__':
    main()
