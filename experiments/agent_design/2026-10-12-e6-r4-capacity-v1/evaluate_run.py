"""Independent, zero-API E6-R4 acceptance. Gold never enters runtime inputs.

Strict loading, original semantics, actual SDK body/projection visibility and
focus are separate gates. Unresolved original context requires human judgment.
"""
import argparse
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

from lxml import html
from uteki.agents.data_query import answer_handoff as handoff
from uteki.agents.data_query import retrieval_cycle as cycle

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v2/evaluation-only/independent_acceptance.py'
PROJECTION_PATH = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v3/evaluation-only/projection_visibility.py'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


# Only protocol/visibility helpers are reused; their historical gold is not read.
protocol = module('e6_r4_sdk_protocol', PROTOCOL_PATH)
projection = module('e6_r4_projection', PROJECTION_PATH)


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(function, *args, **kwargs):
    try:
        return {'verdict': 'pass', 'value': function(*args, **kwargs)}
    except Exception as error:
        return {'verdict': 'fail', 'error_type': type(error).__name__, 'error': str(error)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def local_values(element, name):
    return [''.join(n.itertext()).strip() for n in element.iter()
            if str(n.tag).rsplit(':', 1)[-1].lower() == name.lower()]


def fact_key(value):
    period = value.get('period') or {}
    return (value.get('entity_id'), period.get('kind'), period.get('start'), period.get('end'))


def expected_key(value):
    return fact_key({'entity_id': value['company_id'], 'period': value['period']})


def numeric_coverage(packet, gold):
    """Business acceptance independent of production record validators."""
    facts = packet.get('facts', [])
    records = [f for f in facts if f.get('kind') == 'record']
    required = gold['required']
    checks, matched = [], set()
    for expected in required:
        candidates = [f for f in records if fact_key(f['value']) == expected_key(expected)]
        reasons = []
        if len(candidates) != 1:
            reasons.append(f'Expected one precise annual fact; found {len(candidates)}')
        for fact in candidates:
            value = fact['value']
            wanted = {'metric_id': 'revenue', 'source_snapshot_id': expected['source_snapshot_id'],
                'value_decimal': expected['value_decimal'], 'unit': expected['unit'],
                'dimensions': {}, 'value_kind': 'actual', 'accounting_basis': 'reported_consolidated'}
            reasons += [f'{key} mismatch' for key, val in wanted.items() if value.get(key) != val]
        if not reasons:
            matched.add(candidates[0]['fact_id'])
        checks.append({'company_id': expected['company_id'], 'fiscal_year': expected['fiscal_year'],
            'expected_period': expected['period'], 'fact_ids': [f['fact_id'] for f in candidates],
            'verdict': 'fail' if reasons else 'pass', 'reasons': reasons})
    extra = [f['fact_id'] for f in facts if f.get('kind') not in {'record', 'document', 'source_block'}
             or (f.get('kind') == 'record' and f['fact_id'] not in matched)]
    passed = sum(c['verdict'] == 'pass' for c in checks)
    return {'verdict': 'pass' if passed == len(required) and not extra else 'fail',
        'coverage': f'{passed}/{len(required)}', 'checks': checks,
        'missing': [c for c in checks if c['verdict'] != 'pass'], 'extra_fact_ids': extra,
        'record_fact_count': len(records)}


def original_semantics(packet, gold, dataset):
    """Read raw HTML directly; never use a production amount/calendar adapter."""
    sources = {s['source_snapshot_id']: s for s in read(dataset / 'sources.json')}
    documents = {d['source_snapshot_id']: d for d in packet['source_documents']}
    trees, blocks = {}, {}
    for sid, document in documents.items():
        source = sources[sid]
        require(document['source_sha256'] == source['source_sha256'], 'Delivery source hash mismatch')
        require(document['company_id'] == source['company_id'], 'Delivery issuer mismatch')
        require(document['source_url'] == source['source_url'], 'Delivery source URL mismatch')
        raw = dataset / source['raw_file']
        require(sha(raw) == source['source_sha256'], 'Raw HTML changed')
        trees[sid] = html.fromstring(raw.read_bytes())
        blocks[sid] = {b['block_id']: b for b in map(json.loads,
            (dataset / source['index_folder'] / 'blocks.jsonl').read_text().splitlines())}
        ids = [b['block_id'] for b in document['blocks']]
        require(len(ids) == len(set(ids)), 'Duplicate original block identity')
        for block in document['blocks']:
            original = blocks[sid][block['block_id']]
            require(block['text'] == original['text'] and block['text_hash'] == original['text_hash'],
                    'Selected original block text changed')
            require(block['type'] == original['type'] and block.get('layout_role') == original.get('layout_role'),
                    'Selected original classification changed')
    require(set(documents) <= {r['source_snapshot_id'] for r in gold['required']}, 'Extra source')
    proofs = []
    for expected in gold['required']:
        def proof():
            candidates = [f for f in packet['facts'] if f.get('kind') == 'record'
                          and fact_key(f['value']) == expected_key(expected)]
            require(len(candidates) == 1, 'Missing or duplicate precise original annual fact')
            fact = candidates[0]; value = fact['value']; sid = expected['source_snapshot_id']
            require(value['source_snapshot_id'] == sid, 'Cross-source original claim')
            source = sources[sid]; tree = trees[sid]
            require(source['company_id'] == expected['company_id'], 'Cross-company source')
            require(source['source_sha256'] == expected['source_sha256'] and
                    source['source_url'] == expected['source_url'], 'Frozen original identity mismatch')
            require(source['form'] == '10-K' and source['available_at'] <= packet['scope']['knowledge_cutoff'],
                    'Wrong reporting form or source unavailable at cutoff')
            require(any(p['fiscal_year'] == expected['fiscal_year'] and all(
                p['period'].get(k) == expected['period'][k] for k in ('kind', 'start', 'end'))
                for p in source.get('fiscal_periods', [])), 'Original fiscal-year mapping mismatch')
            context_id = value['origin']['context_ref']
            contexts = tree.xpath('//*[@id=$id]', id=context_id)
            require(len(contexts) == 1, 'Nonunique original context')
            context = contexts[0]
            require(local_values(context, 'identifier') == [expected['company_id'].removeprefix('sec-')],
                    'Original context issuer mismatch')
            require(local_values(context, 'startdate') == [expected['period']['start']] and
                    local_values(context, 'enddate') == [expected['period']['end']], 'Original period mismatch')
            require(not local_values(context, 'explicitmember') and not local_values(context, 'typedmember'),
                    'Dimensioned original context')
            concept = value['origin']['concept']
            require(concept in {'us-gaap:Revenues', 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'},
                    'Original concept is not company revenue')
            inline = []
            for element in tree.xpath('//*[@contextref=$context and @name=$concept]', context=context_id, concept=concept):
                amount = Decimal(''.join(element.itertext()).replace(',', '').strip()) * Decimal(10) ** int(element.get('scale', '0'))
                if element.get('sign') == '-': amount = -amount
                units = tree.xpath('//*[@id=$id]', id=element.get('unitref'))
                path = tree.getroottree().getpath(element)
                references = [r for r in expected['original_references'] if r['fact_dom_path'] == path]
                if (amount == Decimal(expected['value_decimal']) and len(units) == 1
                        and local_values(units[0], 'measure') == ['iso4217:USD'] and references):
                    inline.append({'dom_path': path, 'context_id': context_id, 'value_usd': str(amount),
                        'original_unit': 'iso4217:USD', 'scale': element.get('scale'),
                        'table_block_ids': [r['table_block_id'] for r in references]})
            require(inline, 'No matching independent original amount/date/USD proof')
            require(fact.get('citations'), 'No original citations')
            citations = []
            equivalent_tables = {b for p in inline for b in p['table_block_ids']}
            for citation in fact['citations']:
                require(citation['source_snapshot_id'] == sid, 'Cross-source citation')
                block = blocks[sid][citation['block_id']]
                require(citation['text_hash'] == block['text_hash'] and
                        citation['source_sha256'] == source['source_sha256'], 'Citation hash mismatch')
                require(block['text'][citation['char_start']:citation['char_end']] == citation['quote'],
                        'Original citation slice mismatch')
                require(any(b['block_id'] == block['block_id'] for b in documents[sid]['blocks']),
                        'Full cited original block absent from final delivery')
                require(block['block_id'] in equivalent_tables, 'Citation does not locate an equivalent required original total')
                citations.append({'block_id': block['block_id'], 'quote': citation['quote']})
            return {'fact_id': fact['fact_id'], 'inline_proofs': inline, 'citations': citations}
        proofs.append({'company_id': expected['company_id'], 'fiscal_year': expected['fiscal_year'], **checked(proof)})
    return {'verdict': 'pass' if all(p['verdict'] == 'pass' for p in proofs) else 'fail', 'proofs': proofs,
        'boundary': 'Full exact original blocks and independent raw inline-XBRL semantics; equivalent original occurrences allowed.'}


def semantic_focus(packet, gold):
    checks, manual = [], []
    for document in packet['source_documents']:
        sid = document['source_snapshot_id']; tables = []
        for block in document['blocks']:
            row = {'source_snapshot_id': sid, 'block_id': block['block_id'], 'type': block['type'],
                'text_characters': len(block['text']), 'preview': block['text'][:100]}
            if block.get('layout_role') or block['type'] == 'page_marker':
                row['assessment'] = 'bounded_layout'
            elif block['type'] == 'table':
                covered = [f'{r["company_id"]}/FY{r["fiscal_year"]}' for r in gold['required']
                    if r['source_snapshot_id'] == sid and any(ref['table_block_id'] == block['block_id']
                                                             for ref in r['original_references'])]
                row.update(assessment='necessary_atomic_original_table' if covered else 'manual_review_required',
                           covered_required_facts=covered)
                tables.append(row)
                if not covered: manual.append({**row, 'reason': 'No required annual total; inspect whether original context is necessary'})
            elif block['type'] == 'heading_candidate' or 'in millions' in block['text'].lower():
                row['assessment'] = 'original_supporting_context'
            else:
                row['assessment'] = 'manual_review_required'
                manual.append({**row, 'reason': 'Independent context necessity judgment required'})
            checks.append(row)
        for table in tables:
            own = set(table['covered_required_facts'])
            peers = set().union(*(set(t['covered_required_facts']) for t in tables if t is not table))
            if own and own <= peers:
                manual.append({**table, 'reason': 'Repeated equivalent total table; retain only if independently justified necessary context'})
    return {'verdict': 'manual_review_required' if manual else 'pass', 'checks': checks,
        'manual_review_items': manual, 'policy': gold['focus_standard'],
        'boundary': 'Unresolved context is not automatic acceptance; duplicate tables require independent necessity judgment.'}


def material_pins(base, gold, freeze):
    dataset = base / 'dataset'
    for rel, expected in read(dataset / 'manifest.json')['files'].items():
        path = (dataset / rel).resolve()
        require(path.is_relative_to(dataset.resolve()), 'Dataset reference escapes batch')
        require(sha(path) == expected, 'Dataset artifact hash mismatch: ' + rel)
    for key, path in [('dataset_manifest_sha256', dataset / 'manifest.json'),
                      ('scope_sha256', base / 'scope.json')]:
        require(gold[key] == freeze[key] == sha(path), 'Frozen material binding mismatch: ' + key)
    require(freeze['withheld_standard_sha256'] == sha(base / 'evaluation-only/expected.v1.json'), 'Gold drift')
    require(freeze['preparation_sha256'] == sha(base / 'preparation.v1.json'), 'Preparation receipt drift')
    prepared = read(base / 'preparation.v1.json')
    require(prepared['passed'] and prepared['all_source_bytes_preserved'], 'Material preparation failed')
    for ref in prepared['source_datasets']:
        require(sha(Path(ref['path']) / 'manifest.json') == ref['manifest_sha256'], 'Preparation source dataset drift')
    for ref in prepared['source_original_audits']:
        require(sha(ref['path']) == ref['sha256'], 'Independent original preparation audit drift')
    original = base / 'evaluation-only/root-original-review.v1.json'
    require(sha(original) == freeze['independent_original_review_sha256'], 'Independent original review drift')
    require(read(original)['passed'] and read(original)['expected_sha256'] == sha(base / 'evaluation-only/expected.v1.json'),
            'Independent original review not bound to gold')
    for rel, expected in freeze['implementation'].items():
        require(sha(ROOT / rel) == expected and sha(base / 'implementation-source' / rel) == expected,
                'Frozen implementation drift: ' + rel)
    question = HERE / 'question.v1.json'
    require(sha(question) == gold['question_sha256'], 'Question drift')
    return {'source_count': prepared['counts']['sources'], 'counts': prepared['counts'],
        'question': read(question)['question'], 'independent_original_review': str(original)}


def actual_inputs(query):
    """Bind actual dispatches without confusing a public Skill field with gold.

    The SDK hash/fresh-origin/call-reference gates match the original checker.
    independent_acceptance is a legitimate frozen Skill field. Its bare name is
    not evidence of disclosure of an evaluation artifact or expected answer.
    """
    query_root = query.parent
    packets = {}
    for path in query_root.rglob('turn-*/input.json'):
        value = read(path)
        packets[protocol.digest(json.dumps(value, ensure_ascii=False))] = (path, value)
    inputs, records, errors = [], [], []
    forbidden = ('evaluation-only', 'standard.v1.json', '"value_usd"', '"mandatory"',
        'raw-original-precheck', 'expected.v1.json', 'root-original-review', 'withheld_standard_sha256')
    for path in sorted(query_root.rglob('decision-*-attempt-*.json')):
        def bind():
            record = read(path); packet_sha = record['packet_sha256']
            require(packet_sha in packets, 'SDK model input not bound to saved runtime decision packet')
            input_path, packet = packets[packet_sha]
            require(not any(marker in json.dumps(packet, ensure_ascii=False) for marker in forbidden),
                    'Independent evaluation information leaked')
            require(record.get('plan_origin') == 'model', 'Not a fresh model-controlled decision')
            for ref in record.get('calls', []):
                require(sha(path.parent / ref['path']) == ref['sha256'], 'SDK call reference hash mismatch')
            ends = [ref for ref in record.get('calls', []) if ref['path'].endswith('-end.json')]
            require(ends, 'No actual model adapter call recorded for this decision')
            inputs.append((input_path, packet))
            return {'model_record': protocol.relative(path), 'runtime_input': protocol.relative(input_path),
                'packet_sha256': packet_sha, 'role': record.get('role'), 'status': record.get('status'),
                'calls': record.get('calls', []), 'runtime_review_feedback_present': 'review_feedback' in packet}
        result = checked(bind)
        if result['verdict'] == 'pass': records.append(result['value'])
        else: errors.append({'model_record': protocol.relative(path), **result})
    return inputs, {'verdict': 'pass' if records and not errors else 'fail',
        'checker_version': 'e6-r4-sdk-binding-v2', 'bound_model_decisions': records, 'errors': errors,
        'boundary': 'Saved input hashes and adapter call hashes establish actual SDK dispatch; legitimate Skill field names do not establish private gold leakage. Model comprehension remains unproven.'}


def review_phase(path, base, gold, scope):
    packet = read(path / 'input.json'); result = read(path / 'result.json')
    query = Path(packet['query_ref']['path'])
    require(packet['scope'] == scope, 'Review scope differs from frozen caller scope')
    require(Path(packet['dataset_ref']['path']).resolve() == (base / 'dataset').resolve(), 'Review uses another dataset')
    require(packet['question'] == read(HERE / 'question.v1.json')['question'], 'Review question differs from frozen input')
    manifest = checked(cycle._verify_manifest, path)
    strict = checked(handoff.load_reviewed_data, path, expected_scope=scope,
        expected_review_manifest_sha256=sha(path / 'manifest.json'))
    if strict['verdict'] == 'pass':
        strict['value'] = {'handoff_id': strict['value']['handoff_id'], 'execution_origin': strict['value']['execution_origin']}
    inputs, binding = actual_inputs(query)
    own_inputs = [(p, v) for p, v in inputs if p.resolve().parent.parent == query.resolve()]
    body = protocol.body_exposure(packet, own_inputs)
    if body['verdict'] != 'pass':
        delegated = protocol.body_exposure(packet, inputs)
        if delegated['verdict'] == 'pass':
            body.update(verdict='manual_role_audit_required', delegated_body=delegated,
                        boundary='Worker-only reading cannot automatically be attributed to parent; inspect actual selecting role, without adding a new parent full-reading requirement.')
    visible = projection.visible_projection(packet, query, inputs, binding)
    numeric = numeric_coverage(packet, gold)
    originals = checked(original_semantics, packet, gold, base / 'dataset')
    focused = semantic_focus(packet, gold)
    dual = protocol.reviewer_sdk_inputs(path)
    for row in dual.get('checks', []):
        if row['verdict'] == 'pass':
            request = read(Path(ROOT / row['value']['actual_request']))
            if any(marker in request['model_input'] for marker in
                   ('expected.v1.json', 'root-original-review', 'withheld_standard_sha256')):
                dual['verdict'] = 'fail'
                row.update(verdict='fail', error='Independent gold leaked into reviewer SDK input')
    def audit():
        assessment, eligible = handoff.validate_saved_assessment(path, packet)
        require(assessment == result['assessment'] and eligible, 'Dual assessment is inconsistent or ineligible')
        return {'eligible': eligible, 'status': result['status'], 'source_and_question': True}
    audit_protocol = checked(audit)
    gates = [manifest, strict, binding, body, visible, numeric, focused, dual, audit_protocol]
    original_pass = originals['verdict'] == 'pass' and originals['value']['verdict'] == 'pass'
    passed = original_pass and all(g['verdict'] == 'pass' for g in gates)
    return {'review_path': str(path), 'runtime_status': result['status'], 'sealed_manifest': manifest,
        'strict_load': strict, 'numeric_business_acceptance': numeric, 'original_semantics': originals,
        'semantic_focus': focused, 'actual_sdk_binding': binding, 'actual_full_original_body': body,
        'final_projection_visibility': visible, 'dual_reviewer_sdk_binding': dual, 'dual_review_protocol': audit_protocol,
        'passed': passed, 'content_correct': numeric['verdict'] == 'pass' and original_pass,
        'manual_judgment_pending': focused['manual_review_items'], 'failures': result.get('failures', [])}


def evaluate(base, slot):
    base = base.resolve(); folder = base / slot; run = folder / 'run'
    gold = read(base / 'evaluation-only/expected.v1.json'); freeze = read(base / 'execution-freeze.v1.json')
    material = checked(material_pins, base, gold, freeze)
    config = checked(lambda: require(read(folder / 'runtime-config.json') == freeze['configs'][slot], 'Runtime config drift'))
    before, after = read(folder / 'budget-before.json'), read(folder / 'budget-after.json')
    costs = {'before': before, 'after': after,
        'estimated_increment_usd': str(Decimal(after['estimated_spent_usd']) - Decimal(before['estimated_spent_usd'])),
        'new_requests': after['requests'] - before['requests'], 'ledger': freeze['ledger'],
        'boundary': 'Estimated costs include all failed decisions, audits and repairs; shared historical ledger preserved. Provider billing is unavailable.'}
    costs['settled_within_frozen_limit'] = (after['limit_usd'] == freeze['usd_cap'] and
        after['requests'] <= freeze['request_cap'] and after['unknown_requests'] == 0 and
        after['in_flight_requests'] == 0 and Decimal(after['estimated_spent_usd']) + Decimal(after['held_usd']) <= Decimal(freeze['usd_cap']))
    cycle_result = read(run / 'result.json') if (run / 'result.json').exists() else {'status': 'no_terminal_result'}
    reviews = []
    for path in sorted(run.glob('attempt-*/review-*')):
        if path.is_dir() and (path / 'input.json').is_file() and (path / 'result.json').is_file():
            reviews.append(checked(review_phase, path, base, gold, read(base / 'scope.json')))
    final = cycle_result.get('final_review_ref') or {}
    accepted = [r['value'] for r in reviews if r['verdict'] == 'pass'
        and Path(r['value']['review_path']).resolve() == Path(final.get('path', '/missing')).resolve()]
    capacity = [{'path': str(p), **read(p)} for p in sorted(run.rglob('decision-*-capacity-*.json'))]
    gates = material['verdict'] == config['verdict'] == 'pass'
    passed = (gates and costs['settled_within_frozen_limit'] and cycle_result['status'] == 'reviewed_data_ready'
              and len(accepted) == 1 and accepted[0]['passed'])
    return {'schema': 'e6-r4-independent-run-acceptance-v2', 'slot': slot,
        'checker_version': 'v2', 'checker_correction': 'Removed bare independent_acceptance Skill field from gold-leak markers; original hash/fresh model/call binding and private gold markers preserved. Runtime, input and business standards unchanged.',
        'question': read(HERE / 'question.v1.json')['question'], 'cycle_status': cycle_result['status'],
        'passed': passed, 'material_pins': material, 'runtime_config_binding': config,
        'attempt_reviews': reviews, 'final_review': accepted[0] if len(accepted) == 1 else None,
        'capacity_gates': capacity, 'costs': costs, 'cycle_failures': cycle_result.get('failures', []),
        'evaluator_sha256': sha(Path(__file__)), 'protocol_helper_sha256': sha(PROTOCOL_PATH),
        'projection_helper_sha256': sha(PROJECTION_PATH), 'model_calls': 0,
        'boundary': 'This is independent acceptance, not a new execution. A passing slot does not alone establish stability or capacity-recovery causality.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--slot', choices=['R1', 'R2', 'R3', 'C1'], required=True)
    parser.add_argument('--report', type=Path, help='New exclusive report path; existing reports are preserved')
    args = parser.parse_args(); report = evaluate(args.batch, args.slot)
    target = args.report or args.batch / 'evaluation-only' / (args.slot + '.json')
    with target.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2); handle.write('\n')
    print(json.dumps({'slot': args.slot, 'passed': report['passed'], 'report': str(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
