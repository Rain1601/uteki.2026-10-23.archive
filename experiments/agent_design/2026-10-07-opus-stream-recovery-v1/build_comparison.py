"""Render a recovery comparison with explicit transport/runtime differences.

This does not alter or relax the earlier model-only comparison protocol.
Both visible arms must be completed runs with already verified SVG pages.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlparse

from lxml import html


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('nonfinite_json_number')
    value = json.loads(path.read_text(), object_pairs_hook=pairs, parse_constant=constant)
    require(isinstance(value, dict), 'json_object_required')
    return value


def local(root, value):
    path = (root / value).resolve()
    require(path.is_relative_to(root) and path.is_file(), 'missing_or_outside_project: ' + str(value))
    return path


def money(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid_cost') from exc
    require(number.is_finite() and number >= 0, 'invalid_cost')
    return number


def build(root, protocol_path, runs, pages, output, workbench_url, review_path=None):
    root = root.resolve()
    protocol_path = local(root, protocol_path)
    protocol = read(protocol_path)
    output = (root / output).resolve()
    require(output.is_relative_to(root), 'output_outside_project')
    parsed = urlparse(workbench_url)
    require(parsed.scheme in ('http', 'https') and bool(parsed.netloc), 'invalid_workbench_url')
    require(protocol.get('calls_max') == 1 and protocol.get('automatic_retries') == 0, 'unexpected_recovery_call_policy')
    require(protocol.get('request_difference_from_failed_opus') == ['stream'], 'unexpected_recovery_request_variables')
    require(protocol.get('configuration_difference') == {'stream': [False, True], 'timeout_seconds': [300, 600]},
            'unexpected_recovery_configuration')
    href = lambda path: quote(os.path.relpath(path, output).replace(os.sep, '/'), safe='/.-_')
    arms, requests, results, result_hashes, raw_packet, source_nodes = {}, {}, {}, {}, None, None
    input_fields = ('company_id', 'document_id', 'period_end', 'source_sha256', 'source_packet_sha256',
                    'skill_sha256', 'output_schema_sha256')
    scope = {}
    for key in ('A', 'B'):
        result_path = local(root, Path(runs[key]) / 'result.json')
        run_dir = result_path.parent
        require(not output.is_relative_to(run_dir), 'cannot_render_into_frozen_run')
        result = results[key] = read(result_path)
        result_hashes[key] = sha(result_path)
        require(result.get('status') == 'candidate' and result.get('validation') == 'passed', key + ':completed_candidate_required')
        if key == 'A':
            scope = {field: result[field] for field in input_fields}
        require(all(result.get(field) == scope[field] for field in input_fields), key + ':controlled_input_mismatch')
        require(all(result.get(field) == value for field, value in protocol['scope'].items()), key + ':recovery_scope_mismatch')
        request_path = local(root, run_dir / 'request.json')
        request = requests[key] = read(request_path)
        require(sha(request_path) == result.get('request_sha256'), key + ':request_hash_mismatch')
        require(request.get('model') == result.get('model'), key + ':requested_model_mismatch')
        if key == 'B':
            require(result['request_sha256'] == protocol['request_sha256'], 'recovery_request_does_not_match_protocol')
            for name, digest in result.get('implementation_sha256', {}).items():
                matches = [value for path, value in protocol['runtime_sha256'].items() if Path(path).name == name]
                require(matches == [digest], 'recovery_runtime_does_not_match_protocol: ' + name)
        for field, filename in (('source_packet_sha256', 'source_packet.json'), ('skill_sha256', 'skill.md')):
            require(sha(local(root, run_dir / filename)) == scope[field], key + ':input_file_changed: ' + filename)
        schema = read(local(root, run_dir / 'output_schema.json'))
        require(hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest() == scope['output_schema_sha256'],
                key + ':schema_changed')
        packet = read(run_dir / 'source_packet.json')
        require(all(packet.get(field) == scope[field] for field in ('company_id', 'document_id', 'period_end', 'source_sha256')),
                key + ':packet_scope_mismatch')
        if raw_packet is None:
            raw_packet = packet
            source = local(root, packet['source_local_path'])
            raw = gzip.decompress(source.read_bytes()) if packet.get('source_encoding') == 'gzip' else source.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == scope['source_sha256'], 'source_hash_mismatch')
            dom = html.fromstring(raw)
            tree = dom.getroottree()
            source_nodes = {tree.getpath(node): node for node in dom.iter()}
        require(packet == raw_packet, 'source_packets_differ')
        artifacts = result.get('artifacts_sha256', {})
        require(all(filename in artifacts for filename in ('business_map.json', 'revenue.json', 'evidence.html')),
                key + ':required_artifact_missing')
        for filename, digest in artifacts.items():
            path = local(root, run_dir / filename)
            require(path.parent == run_dir and sha(path) == digest, key + ':artifact_changed: ' + filename)
        costs = result.get('costs') or {}
        records = costs.get('records') or []
        require(costs.get('requests') == 1 and len(records) == 1, key + ':single_model_call_required')
        call = records[0]
        require(call.get('status') == 'succeeded' and call.get('request_sha256') == result['request_sha256'], key + ':successful_dispatch_required')
        require(call.get('requested_model') == request['model'], key + ':dispatch_model_mismatch')
        require(call.get('stop_reason') == 'end_turn' and call.get('http_status') == 200, key + ':completed_provider_receipt_required')
        config = read(local(root, run_dir / 'configuration.json'))
        timeout = 300 if key == 'A' else 600
        stream = key == 'B'
        for field, value in {'timeout_seconds': timeout, 'max_retries': 0, 'stream': stream}.items():
            require(config['fields'][field]['value'] == value, key + ':configuration_mismatch: ' + field)
        for field, value in {'stream': stream, 'max_tokens': 16000, 'thinking': {'type': 'adaptive'},
                             'output_config': {'effort': 'high'}}.items():
            require(request.get(field) == value, key + ':request_parameter_mismatch: ' + field)
        require(not any(field in request for field in ('temperature', 'top_p', 'top_k', 'seed')), key + ':unexpected_sampling_control')
        page = local(root, pages[key])
        check = read(local(root, page.parent / 'verification.json'))
        require(check.get('trace_id') == result['trace_id'] and check.get('with_svg') is True, key + ':visible_page_not_ready')
        require(check['fingerprints']['html'] == sha(page) and check['fingerprints']['result'] == result_hashes[key], key + ':page_binding_mismatch')
        usage = call.get('raw_usage') or call.get('usage') or {}
        estimated = costs.get('known_estimated_usd') if costs.get('unknown_cost_requests') == 0 else None
        if estimated is not None:
            money(estimated)
        links = {name: href(local(root, run_dir / filename)) for name, filename in (
            ('result', 'result.json'), ('request', 'request.json'), ('packet', 'source_packet.json'),
            ('skill', 'skill.md'), ('configuration', 'configuration.json'), ('business', 'business_map.json'),
            ('revenue', 'revenue.json'), ('evidence', 'evidence.html'))}
        for name, filename in (('response', 'response.txt'), ('response_metadata', 'response_metadata.json')):
            if (run_dir / filename).is_file():
                links[name] = href(run_dir / filename)
        links.update(page=href(page), process=workbench_url.rstrip('/') + '/agent-runs?agent=data&run=' + quote(result['trace_id']))
        arms[key] = {'label': 'Sonnet 5.5' if key == 'A' else 'Opus 5.5 · 恢复后', 'trace_id': result['trace_id'],
            'requested_model': request['model'], 'returned_model': call.get('actual_upstream_model'),
            'status': result['status'], 'validation': result['validation'], 'counts': result.get('counts', {}),
            'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
            'cache_read_input_tokens': usage.get('cache_read_input_tokens'), 'elapsed_seconds': call.get('elapsed_seconds'),
            'estimated_usd': estimated, 'known_estimated_usd': costs.get('known_estimated_usd'),
            'unknown_cost_requests': costs.get('unknown_cost_requests'), 'stop_reason': call.get('stop_reason'),
            'stream': stream, 'timeout_seconds': timeout, 'implementation_sha256': result.get('implementation_sha256', {}),
            'result_sha256': result_hashes[key], 'request_sha256': result['request_sha256'], 'artifact_hashes': artifacts, 'links': links}
    require(arms['A']['trace_id'] != arms['B']['trace_id'], 'cannot_compare_same_trace')
    require(requests['A']['model'] == 'claude-sonnet-5-5' and requests['B']['model'] == 'claude-opus-5-5', 'expected_sonnet_and_opus_models')
    differences = sorted(field for field in requests['A'].keys() | requests['B'].keys()
                         if requests['A'].get(field) != requests['B'].get(field))
    require(differences == ['model', 'stream'], 'requests_differ_beyond_recovery_variables: ' + str(differences))

    prior_result_path = local(root, Path(protocol['prior_run']) / 'result.json')
    prior = read(prior_result_path)
    require(sha(prior_result_path) == protocol['prior_result_sha256'] and prior['trace_id'] == protocol['prior_trace'], 'prior_failure_binding_mismatch')
    require(prior.get('status') == 'failed' and prior['trace_id'] not in (arms['A']['trace_id'], arms['B']['trace_id']), 'prior_failed_attempt_required')
    prior_request_path = local(root, prior_result_path.parent / 'request.json')
    prior_request = read(prior_request_path)
    require(sha(prior_request_path) == prior['request_sha256'], 'prior_request_hash_mismatch')
    require(sorted(k for k in prior_request.keys() | requests['B'].keys() if prior_request.get(k) != requests['B'].get(k)) == ['stream'],
            'recovery_changed_prior_request_beyond_stream')
    console_path = local(root, protocol['prior_provider_reconciliation'])
    console = read(console_path)
    binding = console.get('binding', {})
    require(binding.get('local_trace_id') == prior['trace_id'] and binding.get('result_sha256') == sha(prior_result_path)
            and binding.get('request_sha256') == prior['request_sha256'], 'prior_console_binding_mismatch')
    console_record = console['provider_record']
    require(console_record.get('model') == prior['model'] == requests['B']['model'], 'prior_console_model_mismatch')
    charge = money(console_record['charge_usd'])
    current = arms['B']['estimated_usd']
    cumulative = str(charge + money(current)) if current is not None else None
    attempts = {'prior': {'trace_id': prior['trace_id'], 'local_status': prior['status'],
                         'local_unknown_cost_requests': prior.get('costs', {}).get('unknown_cost_requests'),
                         'provider_reported_charge_usd': str(charge), 'provider_status': console_record.get('status_display'),
                         'channel': console_record.get('channel'), 'result_href': href(prior_result_path), 'console_href': href(console_path)},
                'current_estimated_usd': current, 'opus_two_attempts_indicative_usd': cumulative,
                'basis': 'prior_provider_reported_charge_plus_current_local_estimate_not_invoice',
                'correlation': console.get('correlation', {}), 'original_failed_ledger_changed': False}

    review = None
    if review_path is not None:
        review_path = local(root, review_path)
        raw_review = read(review_path)
        require(isinstance(raw_review.get('summary'), str) and raw_review['summary'].strip(), 'review_summary_required')
        for key in ('A', 'B'):
            expected = {field: arms[key][field] for field in ('trace_id', 'result_sha256', 'request_sha256')}
            expected.update(source_packet_sha256=scope['source_packet_sha256'], skill_sha256=scope['skill_sha256'],
                            business_map_sha256=arms[key]['artifact_hashes']['business_map.json'], revenue_sha256=arms[key]['artifact_hashes']['revenue.json'])
            require(all(raw_review.get('bindings', {}).get(key, {}).get(field) == value for field, value in expected.items()), key + ':review_binding_mismatch')
        blocks = {block['id']: block for block in raw_packet['blocks']}
        source_blocks, checks = {}, []
        require(isinstance(raw_review.get('checks'), list) and raw_review['checks'], 'review_checks_required')
        for check in raw_review['checks']:
            item = {field: check.get(field) for field in ('id', 'label', 'sonnet', 'opus', 'note')}
            require(all(isinstance(value, str) and value.strip() for value in item.values()), 'review_text_required')
            ids = check.get('source_block_ids')
            require(isinstance(ids, list) and len(ids) == len(set(ids)) and all(bid in blocks for bid in ids), 'review_source_outside_packet')
            for bid in ids:
                block = blocks[bid]
                node = source_nodes.get(block['source_dom_path'])
                text = ' '.join(''.join(node.itertext()).split()) if node is not None else None
                require(text == block['text'] and hashlib.sha256(text.encode()).hexdigest() == block['text_sha256'], 'review_source_differs_from_original')
                source_blocks[bid] = {field: block[field] for field in ('id', 'text', 'source_dom_path')}
            checks.append(dict(item, source_block_ids=ids))
        limitations = raw_review.get('limitations', [])
        require(isinstance(limitations, list) and all(isinstance(v, str) for v in limitations), 'review_limitations_invalid')
        review = {'summary': raw_review['summary'], 'checks': checks, 'source_blocks': list(source_blocks.values()),
                  'review_method': raw_review.get('review_method'), 'limitations': limitations,
                  'next_step': raw_review.get('next_step'), 'href': href(review_path)}

    data = {'arms': arms, 'review': review, 'scope': scope, 'attempts': attempts,
            'method': {'request_differences': differences, 'skill_version': '0.3', 'max_tokens': 16000,
                       'thinking': 'adaptive', 'effort': 'high', 'strict_model_only_ab': False,
                       'runtime_version_differs': arms['A']['implementation_sha256'] != arms['B']['implementation_sha256']},
            'links': {'protocol': href(protocol_path), 'source': raw_packet['source_url'],
                      'source_file': href(local(root, raw_packet['source_local_path']))},
            'packet_counts': {'blocks': len(raw_packet['blocks']), 'tables': len(raw_packet.get('tables', []))}}
    output.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).with_name('comparison-template.html').read_text()
    require(template.count('/* DATA */') == 1, 'template_marker_mismatch')
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (output / 'index.html').write_text(template.replace('/* DATA */', serialized))
    verification = {'schema_version': 'recovery-comparison-view-v1', 'protocol_sha256': sha(protocol_path),
        'result_sha256': result_hashes, 'request_differing_fields': differences,
        'source_packet_skill_schema_and_source_verified': True, 'frozen_artifacts_verified': True,
        'prior_failure_and_console_bound': True, 'prior_result_sha256': sha(prior_result_path),
        'provider_console_sha256': sha(console_path), 'review_bound': review is not None,
        'strict_model_only_ab': False, 'view_sha256': sha(output / 'index.html'), 'browser_visual_review': 'not_performed'}
    if review_path is not None:
        verification['review_sha256'] = sha(review_path)
    (output / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    return verification


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('root', 'protocol', 'a-run', 'b-run', 'a-page', 'b-page', 'output', 'workbench-url'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--review')
    args = parser.parse_args()
    print(json.dumps(build(Path(args.root), Path(args.protocol), {'A': Path(args.a_run), 'B': Path(args.b_run)},
                           {'A': Path(args.a_page), 'B': Path(args.b_page)}, Path(args.output), args.workbench_url,
                           Path(args.review) if args.review else None), ensure_ascii=False, indent=2))
