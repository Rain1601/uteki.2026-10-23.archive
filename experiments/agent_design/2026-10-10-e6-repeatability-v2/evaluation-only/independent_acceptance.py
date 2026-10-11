"""Read-only E6-V2 original-content acceptance, including terminal failures. Zero API.

Neither gold nor this assessment enters a runtime packet. Semantic ambiguity is
reported for Codex review, never converted into automatic content acceptance.
"""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re

from lxml import html
from uteki.agents.data_query import answer_handoff as handoff, retrieval_cycle as cycle
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/e6-repeatability-20261010-r2'
STANDARD = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v1/evaluation-only/standard.v1.json'


def read(path):
    return json.loads(Path(path).read_bytes())


def relative(path):
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def checked(function, *args, **kwargs):
    try:
        return {'verdict': 'pass', 'value': function(*args, **kwargs)}
    except Exception as error:
        return {'verdict': 'fail', 'error_type': type(error).__name__, 'error': str(error)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def local_values(element, name):
    return [node.text for node in element.iter() if str(node.tag).rsplit(':', 1)[-1] == name]


def raw_original(packet):
    """Each required fact is independently checked, so missing facts remain visible."""
    standard = read(STANDARD)
    dataset = Path(packet['dataset_ref']['path'])
    sources = {source['source_snapshot_id']: source for source in read(dataset / 'sources.json')}
    docs = {document['source_snapshot_id']: document for document in packet['source_documents']}
    trees, original_blocks = {}, {}
    proofs = []
    for mandatory in standard['mandatory']:
        def proof():
            candidates = [fact for fact in packet['facts'] if fact.get('kind') == 'record'
                          and fact['value']['entity_id'] == mandatory['company_id']
                          and all(fact['value']['period'][k] == mandatory['period'][k] for k in ('kind', 'start', 'end'))]
            require(len(candidates) == 1, f'Expected one precise annual fact; found {len(candidates)}')
            fact = candidates[0]
            value = fact['value']
            sid = value['source_snapshot_id']
            require(sid == mandatory['source_snapshot_id'], 'Wrong report source')
            require(value['metric_id'] == 'revenue', 'Wrong metric')
            require(value['value_decimal'] == mandatory['value_usd'], 'Wrong annual revenue')
            require(value['unit'] == 'USD' and value['dimensions'] == {}, 'Wrong currency or segment dimensions')
            require(value['accounting_basis'] == 'reported_consolidated', 'Not reported company consolidated revenue')
            require(value['value_kind'] == 'actual', 'Not a reported actual fact')
            source = sources[sid]
            require(source['company_id'] == mandatory['company_id'], 'Cross-company metadata')
            require(source['available_at'] <= packet['scope']['knowledge_cutoff'], 'Beyond available cutoff')
            require(source['form'] == '10-K', 'Wrong filing form')
            fiscal = [f for f in source.get('fiscal_periods', []) if f['fiscal_year'] == mandatory['fiscal_year']
                      and all(f['period'].get(k) == mandatory['period'][k] for k in ('kind', 'start', 'end'))]
            require(fiscal, 'Fiscal-year label does not match frozen original period metadata')
            raw = dataset / source['raw_file']
            require(digest(raw.read_bytes()) == source['source_sha256'], 'Raw original hash drift')
            if sid not in trees:
                trees[sid] = html.fromstring(raw.read_bytes())
                blocks = dataset / source['index_folder'] / 'blocks.jsonl'
                original_blocks[sid] = {block['block_id']: block for block in
                    (json.loads(line) for line in blocks.read_text().splitlines())}
            tree = trees[sid]
            context_id = value['origin']['context_ref']
            contexts = tree.xpath('//*[@id=$id]', id=context_id)
            require(len(contexts) == 1, 'Missing unique original XBRL context')
            context = contexts[0]
            require(local_values(context, 'identifier') == [mandatory['company_id'][4:]], 'Wrong original issuer context')
            require(local_values(context, 'startdate') == [mandatory['period']['start']], 'Wrong original start date')
            require(local_values(context, 'enddate') == [mandatory['period']['end']], 'Wrong original end date')
            require(not local_values(context, 'explicitmember'), 'Original fact is dimensioned')
            matches = []
            for element in tree.xpath('//*[@contextref=$context and @name=$concept]',
                    context=context_id, concept=value['origin']['concept']):
                amount = Decimal(''.join(element.itertext()).replace(',', '').strip()) * Decimal(10) ** int(element.get('scale', '0'))
                if element.get('sign') == '-':
                    amount = -amount
                unit = tree.xpath('//*[@id=$id]', id=element.get('unitref'))
                if amount == Decimal(mandatory['value_usd']) and len(unit) == 1 and local_values(unit[0], 'measure') == ['iso4217:USD']:
                    matches.append({'dom_path': tree.getroottree().getpath(element), 'context_ref': context_id,
                        'raw_text': ''.join(element.itertext()), 'scale': element.get('scale'), 'normalized_usd': str(amount)})
            require(matches, 'No matching original USD inline-XBRL amount')
            require(fact['citations'], 'No exact original citation')
            citations = []
            for citation in fact['citations']:
                require(citation['source_snapshot_id'] == sid, 'Cross-source citation')
                block = original_blocks[sid][citation['block_id']]
                require(citation['text_hash'] == block['text_hash'], 'Citation block hash drift')
                require(citation['source_sha256'] == source['source_sha256'], 'Citation source hash drift')
                require(block['text'][citation['char_start']:citation['char_end']] == citation['quote'], 'Citation slice mismatch')
                delivered = [b for b in docs[sid]['blocks'] if b['block_id'] == block['block_id']]
                require(len(delivered) == 1 and delivered[0]['text'] == block['text'], 'Full original citation block absent or altered')
                citations.append({'block_id': block['block_id'], 'quote': citation['quote'], 'dom_path': block.get('dom_path')})
            return {'fact_id': fact['fact_id'], 'source_snapshot_id': sid,
                'company_id': mandatory['company_id'], 'fiscal_year': mandatory['fiscal_year'],
                'period': mandatory['period'], 'original_unit': mandatory['original_unit'],
                'raw_original_sha256': source['source_sha256'], 'inline_proofs': matches, 'citations': citations}
        item = checked(proof)
        proofs.append({'requirement_id': mandatory['requirement_id'], **item})
    allowed_sources = {m['source_snapshot_id'] for m in standard['mandatory']}
    extra_sources = sorted(set(docs) - allowed_sources)
    record_facts = [f for f in packet['facts'] if f.get('kind') == 'record']
    extra_facts = [f['fact_id'] for f in packet['facts'] if f.get('kind') not in {'record', 'document', 'source_block'}
                   or (f.get('kind') == 'record' and not any(
                       f['value']['entity_id'] == m['company_id'] and all(
                           f['value']['period'].get(k) == m['period'][k] for k in ('kind', 'start', 'end'))
                       for m in standard['mandatory']))]
    passed = sum(p['verdict'] == 'pass' for p in proofs)
    return {'mandatory_coverage': f'{passed}/4', 'proofs': proofs, 'extra_sources': extra_sources,
        'extra_facts': extra_facts, 'record_fact_count': len(record_facts),
        'verdict': 'pass' if passed == 4 and not extra_sources and not extra_facts and len(record_facts) == 4 else 'fail',
        'temporal_limit': standard['temporal_boundary']}


def focus(packet):
    """Original task semantics; no preferred statement type or block-ID whitelist."""
    checks, ambiguity = [], []
    mandatory = read(STANDARD)['mandatory']
    for document in packet['source_documents']:
        sid = document['source_snapshot_id']
        tables = []
        for block in document['blocks']:
            text = block['text']
            item = {'source_snapshot_id': sid, 'block_id': block['block_id'], 'type': block['type'],
                    'layout_role': block.get('layout_role'), 'header_preview': text[:30], 'text_characters': len(text)}
            # Parser-frozen layout precedes type. A header rendered as a table is not a business table.
            if block.get('layout_role') or block['type'] == 'page_marker':
                item.update(assessment='bounded_layout', reason='Frozen parser layout; disclosed overhead, no optional coverage credit')
            elif block['type'] == 'table':
                contribution = []
                normalized = re.sub(r'[\s,]', '', text)
                for m in mandatory:
                    if m['source_snapshot_id'] != sid:
                        continue
                    # Format with integral million values without accidentally stripping significant zeros.
                    millions = format(Decimal(m['value_usd']) / Decimal(1000000), 'f').split('.')[0]
                    if millions in normalized and str(m['fiscal_year']) in text and re.search(r'revenue', text, re.I):
                        contribution.append(m['requirement_id'])
                numeric_citations = [f['fact_id'] for f in packet['facts'] if f.get('kind') == 'record'
                                     and any(c['source_snapshot_id'] == sid and c['block_id'] == block['block_id'] for c in f['citations'])]
                item.update(assessment='atomic_financial_table', covered_required_facts=contribution,
                            cited_fact_ids=numeric_citations, reason='Whole atomic table keeps structural columns/rows; exact numeric scope checked separately')
                tables.append(item)
                if not contribution:
                    ambiguity.append({'block_id': block['block_id'], 'reason': 'No required annual total recognized; inspect evidential need in original'})
            elif block['type'] == 'heading_candidate' or 'in millions' in text.lower() or text.strip() in {'Alphabet Inc.', 'Microsoft Corporation'}:
                item.update(assessment='supporting_context', reason='Original heading, unit caption or issuer context')
            else:
                item.update(assessment='manual_review_required', reason='Context necessity requires independent original reading')
                ambiguity.append({'block_id': block['block_id'], 'reason': item['reason']})
            checks.append(item)
        for table in tables:
            peers = [t for t in tables if t is not table]
            covered_elsewhere = set().union(*(set(t['covered_required_facts']) for t in peers)) if peers else set()
            own = set(table['covered_required_facts'])
            if own and own <= covered_elsewhere:
                ambiguity.append({'block_id': table['block_id'], 'reason': 'Equivalent annual facts duplicated across atomic tables; Codex must assess stated evidential need'})
    return {'verdict': 'manual_review_required' if ambiguity else 'pass', 'checks': checks,
        'manual_review_items': ambiguity, 'block_count': len(checks),
        'policy': 'Equivalent originals accepted. Complementary tables can be necessary. Duplicate equivalent tables fail only after no evidential need is independently established; optional evidence cannot offset omissions.'}


def sdk_bound_inputs(query_root):
    packets = {}
    for path in query_root.rglob('turn-*/input.json'):
        packet = read(path)
        packets[digest(json.dumps(packet, ensure_ascii=False))] = (path, packet)
    actual, records, errors = [], [], []
    forbidden = ('evaluation-only', 'standard.v1.json', 'independent_acceptance', '"value_usd"', '"mandatory"', 'raw-original-precheck')
    for path in sorted(query_root.rglob('decision-*-attempt-*.json')):
        def bind():
            record = read(path)
            sha = record['packet_sha256']
            require(sha in packets, 'SDK model input not bound to saved runtime decision packet')
            input_path, packet = packets[sha]
            content = json.dumps(packet, ensure_ascii=False)
            require(not any(marker in content for marker in forbidden), 'Independent evaluation information leaked')
            require(record.get('plan_origin') == 'model', 'Not a fresh model-controlled decision')
            for ref in record.get('calls', []):
                call = path.parent / ref['path']
                require(digest(call.read_bytes()) == ref['sha256'], 'SDK call reference hash mismatch')
            dispatch_ends = [path.parent / ref['path'] for ref in record.get('calls', []) if ref['path'].endswith('-end.json')]
            require(dispatch_ends, 'No actual model adapter call recorded for this decision')
            actual.append((input_path, packet))
            return {'model_record': relative(path), 'runtime_input': relative(input_path),
                    'packet_sha256': sha, 'role': record.get('role'), 'status': record.get('status'),
                    'calls': record.get('calls', []), 'runtime_review_feedback_present': 'review_feedback' in packet}
        result = checked(bind)
        if result['verdict'] == 'fail':
            errors.append({'model_record': relative(path), **result})
        else:
            records.append(result['value'])
    return actual, {'verdict': 'pass' if records and not errors else 'fail',
                    'bound_model_decisions': records, 'errors': errors,
                    'boundary': 'Saved packet hash is computed immediately before Runner.run; bound call references prove SDK adapter invocation, not model comprehension.'}


def body_exposure(packet, inputs):
    rows = []
    for document in packet['source_documents']:
        for block in document['blocks']:
            matches = [relative(path) for path, model_packet in inputs if any(
                item.get('source_snapshot_id') == document['source_snapshot_id'] and item.get('block_id') == block['block_id']
                and item.get('text') == block['text'] for item in model_packet.get('retained_body', {}).get('items', []))]
            rows.append({'source_snapshot_id': document['source_snapshot_id'], 'block_id': block['block_id'],
                         'exact_full_original_text_in_sdk_input': bool(matches), 'first_input': matches[0] if matches else None})
    return {'verdict': 'pass' if rows and all(r['exact_full_original_text_in_sdk_input'] for r in rows) else 'fail', 'checks': rows}


def reviewer_sdk_inputs(review):
    rows = []
    for role in ('model', 'question-model'):
        root = review / role
        for path in sorted(root.glob('review-*-attempt-*.json')):
            def bind():
                record = read(path)
                request = root / record['request']['path']
                require(digest(request.read_bytes()) == record['request']['sha256'], 'Review SDK request reference mismatch')
                value = read(request)
                require(digest(json.dumps(value['packet'], ensure_ascii=False)) == value['packet_sha256'], 'Review packet hash mismatch')
                require(json.loads(value['model_input']) == value['packet'], 'Actual reviewer input differs from packet')
                require(digest(value['model_input']) == value['model_input_sha256'], 'Actual reviewer input hash mismatch')
                require(not any(marker in value['model_input'] for marker in
                    ('evaluation-only', 'standard.v1.json', 'independent_acceptance', '"value_usd"', '"mandatory"')),
                    'Independent gold leaked into review SDK input')
                ends = []
                for ref in record.get('calls', []):
                    call = root / ref['path']
                    require(digest(call.read_bytes()) == ref['sha256'], 'Reviewer call reference mismatch')
                    if ref['path'].endswith('-end.json'):
                        ends.append(ref['path'])
                require(ends, 'No reviewer adapter invocation')
                return {'role': role, 'model_record': relative(path), 'actual_request': relative(request),
                        'packet_sha256': value['packet_sha256'], 'status': record['status'], 'calls': ends}
            rows.append({'role': role, **checked(bind)})
    return {'verdict': 'pass' if rows and all(r['verdict'] == 'pass' for r in rows)
            and {r['role'] for r in rows} == {'model', 'question-model'} else 'fail', 'checks': rows}


def review_phase(path):
    checked_manifest = checked(cycle._verify_manifest, path)
    packet = read(path / 'input.json')
    result = read(path / 'result.json')
    query = Path(packet['query_ref']['path'])
    inputs, binding = sdk_bound_inputs(query.parent)
    def review_protocol():
        assessment, eligible = handoff.validate_saved_assessment(path, packet)
        require(assessment == result['assessment'], 'Saved combined assessment mismatch')
        return {'eligible': eligible, 'status': result['status'], 'source_and_question_assessments_present':
            (path / 'source-response.json').exists() and (path / 'question-response.json').exists(),
            'question_protocol_repair_attempted': result.get('question_protocol_repair_attempted', False),
            'source_protocol_repair_attempted': result.get('source_protocol_repair_attempted', False)}
    strict = checked(handoff.load_reviewed_data, path, expected_scope=packet['scope'],
        expected_review_manifest_sha256=digest((path / 'manifest.json').read_bytes()))
    if strict['verdict'] == 'pass':
        strict['value'] = {'handoff_id': strict['value']['handoff_id'], 'analysis_called': False}
    content = raw_original(packet)
    focused = focus(packet)
    body = body_exposure(packet, inputs)
    protocol = checked(review_protocol)
    reviewer_binding = reviewer_sdk_inputs(path)
    content_pass = content['verdict'] == 'pass' and body['verdict'] == 'pass' and binding['verdict'] == 'pass'
    usable = content_pass and focused['verdict'] == 'pass' and strict['verdict'] == 'pass' and checked_manifest['verdict'] == 'pass' and reviewer_binding['verdict'] == 'pass'
    return {'review': relative(path), 'runtime_review_status': result['status'], 'runtime_failures': result.get('failures', []),
        'sealed_review_manifest': checked_manifest, 'raw_original': content, 'semantic_focus': focused,
        'actual_sdk_input_binding_and_gold_isolation': binding, 'full_body_exposure': body,
        'dual_review_protocol': protocol, 'reviewer_sdk_binding_and_gold_isolation': reviewer_binding, 'strict_load': strict,
        'content_effect': 'pass' if content_pass and focused['verdict'] == 'pass' else
            ('manual_review_required' if content_pass and focused['verdict'] == 'manual_review_required' else 'fail'),
        'usable_delivery': usable}


def recoveries(run, result):
    def select(pattern, predicate):
        return [{'path': relative(p), **read(p)} for p in sorted(run.rglob(pattern)) if predicate(read(p))]
    rejected = select('turn-*/receipt.json', lambda r: r.get('status') in {'rejected', 'failed', 'error'})
    decision = select('decision-*-attempt-*.json', lambda r: r.get('attempt', 1) > 1 or r.get('retry') or r.get('status') != 'decision_returned')
    reviews = select('review-*-attempt-*.json', lambda r: r.get('attempt', 1) > 1 or r.get('retry') or r.get('status') != 'json_returned')
    failed_calls = select('calls/*-end.json', lambda r: r.get('status') != 'succeeded')
    protocol_inputs = [relative(p) for p in sorted(run.rglob('*repair-input.json'))]
    protocol_flags = [{'review': relative(p.parent), 'question': read(p).get('question_protocol_repair_attempted', False),
                       'source': read(p).get('source_protocol_repair_attempted', False)}
                      for p in sorted(run.glob('attempt-*/review-*/result.json')) if
                      read(p).get('question_protocol_repair_attempted') or read(p).get('source_protocol_repair_attempted')]
    counts = [len(a.get('reviews', [])) for a in result.get('attempts', [])]
    no_recovery = len(result.get('attempts', [])) == 1 and counts == [1] and not any(
        (rejected, decision, reviews, failed_calls, protocol_inputs, protocol_flags))
    return {'rejected_tool_actions': rejected, 'decision_format_or_network_repair': decision,
        'review_format_or_network_repair': reviews, 'failed_provider_calls': failed_calls,
        'protocol_repair_inputs': protocol_inputs, 'protocol_repair_flags': protocol_flags,
        'retrieval_attempt_count': len(result.get('attempts', [])), 'review_counts_by_retrieval': counts,
        'mechanical_no_recovery': no_recovery}


def audit_run(run, slot_id):
    if not (run / 'manifest.json').exists():
        return {'slot_id': slot_id, 'status': 'not_sealed', 'acceptance_api_calls': 0}
    before = {relative(p): digest(p.read_bytes()) for p in run.rglob('*') if p.is_file()}
    result = read(run / 'result.json')
    phases = []
    for path in sorted(run.glob('attempt-*/review-*')):
        if (path / 'manifest.json').exists():
            assessment = checked(review_phase, path)
            phases.append({'review': relative(path), **assessment})
    # Preserve query-only failures, including incomplete numeric delivery/explicit gaps.
    queries = []
    for path in sorted(run.glob('attempt-*/data-query/query')):
        if (path / 'result.json').exists():
            q = read(path / 'result.json')
            inputs, binding = sdk_bound_inputs(path.parent)
            config = read(run / 'config.json')
            def partial_original():
                packet = handoff.prepare_review_packet(path, config['request']['dataset'],
                    expected_scope=config['request']['scope'], max_packet_bytes=config['max_review_packet_bytes'],
                    source_delivery=config.get('source_delivery', 'query_evidence_v1'),
                    source_review_policy=config.get('source_review_policy', handoff._SOURCE_REVIEW_POLICY),
                    question_review_policy=config.get('question_review_policy'))
                return {'raw_original': raw_original(packet), 'semantic_focus': focus(packet),
                        'full_body_exposure': body_exposure(packet, inputs)}
            queries.append({'query': relative(path), 'status': q['status'], 'stop_reason': q.get('stop_reason'),
                'coverage': q.get('coverage'), 'gaps': q.get('gaps'), 'query_sdk_inputs': binding,
                'independent_partial_output': checked(partial_original),
                'selected_record_ids': q.get('evidence_bundle', {}).get('selected_record_ids'),
                'sealed_query_manifest': checked(cycle._verify_manifest, path)})
    final_ref = result.get('final_review_ref')
    final = next((p for p in phases if final_ref and str(ROOT / p['review']) == final_ref['path']), None)
    first = phases[0] if phases else None
    recovery = recoveries(run, result)
    def phase_pass(phase):
        return bool(phase and phase['verdict'] == 'pass' and phase['value']['usable_delivery'])
    calls = [read(p) for p in run.rglob('calls/*-end.json')]
    unique = {c['call_id']: c for c in calls}
    after = {relative(p): digest(p.read_bytes()) for p in run.rglob('*') if p.is_file()}
    run_manifest = checked(cycle._verify_manifest, run)
    intact = before == after and run_manifest['verdict'] == 'pass'
    final_ref_matches = bool(final_ref and (Path(final_ref['path']) / 'manifest.json').exists()
                             and digest((Path(final_ref['path']) / 'manifest.json').read_bytes()) == final_ref['manifest_sha256'])
    return {'schema_version': 'e6-v2-independent-acceptance-v1', 'slot_id': slot_id,
        'run': relative(run), 'runtime_status': result['status'], 'acceptance_api_calls': 0,
        'standard_sha256': digest(STANDARD.read_bytes()), 'sealed_run_manifest': run_manifest,
        'sealed_run_manifest_sha256': digest((run / 'manifest.json').read_bytes()),
        'first_draft': first, 'final_draft': final, 'all_drafts': phases, 'query_attempts_including_failures': queries,
        'recovery_events': recovery, 'first_draft_usable_delivery': phase_pass(first),
        'final_review_reference_matches': final_ref_matches,
        'final_usable_delivery': intact and final_ref_matches and result['status'] == 'reviewed_data_ready' and phase_pass(final),
        'no_recovery_first_pass': intact and final_ref_matches and result['status'] == 'reviewed_data_ready' and phase_pass(first) and recovery['mechanical_no_recovery'],
        'api_call_count': len(unique), 'known_estimated_usd': str(sum((Decimal(c['estimated_usd']) for c in unique.values() if c.get('estimated_usd') is not None), Decimal(0))),
        'unknown_cost_call_ids': [c['call_id'] for c in unique.values() if c.get('estimated_usd') is None],
        'api_calls_by_stage': dict(Counter(c['stage'] for c in unique.values())),
        'run_files_unchanged': before == after,
        'effect_priority': 'Content effect first, qualified success second, cost descriptive only. Manual items require independent Codex resolution before an acceptance rate is published.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', help='RN-SN; default all nine frozen slots')
    parser.add_argument('--run', type=Path, help='Read-only historical verification; cannot impersonate a V2 matrix slot')
    parser.add_argument('--report', type=Path, required=True, help='New evaluation output, refuses overwrite')
    args = parser.parse_args()
    def safe_audit(path, slot):
        result = checked(audit_run, path, slot)
        if result['verdict'] == 'pass':
            return result['value']
        return {'slot_id': slot, 'run': relative(path), 'status': 'independent_audit_error',
                'assessment_api_calls': 0, 'error_type': result['error_type'], 'error': result['error'],
                'final_usable_delivery': False, 'no_recovery_first_pass': False}
    if args.run:
        rows = [safe_audit(args.run.resolve(), 'historical-helper-check')]
    else:
        require(not args.slot or re.fullmatch(r'R[123]-S[123]', args.slot), 'Unknown frozen slot')
        slots = [(f'R{r}-S{s}', OUTPUT / f'R{r}' / f'S{s}' / 'run-r1') for r in range(1, 4) for s in range(1, 4)]
        rows = [safe_audit(path, slot) for slot, path in slots if not args.slot or slot == args.slot]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as file:
        json.dump({'schema_version': 'e6-v2-independent-acceptance-batch-v1', 'assessment_api_calls': 0,
            'standard_sha256': digest(STANDARD.read_bytes()), 'runs': rows}, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps([{'slot': r['slot_id'], 'status': r.get('runtime_status', r.get('status')),
        'first': r.get('first_draft_usable_delivery'), 'final': r.get('final_usable_delivery'),
        'no_recovery': r.get('no_recovery_first_pass')} for r in rows], ensure_ascii=False))


if __name__ == '__main__':
    main()
