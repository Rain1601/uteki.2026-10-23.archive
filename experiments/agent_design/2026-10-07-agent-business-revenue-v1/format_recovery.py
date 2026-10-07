"""Explicit, byte-preserving recovery of one outer JSON fence. No model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from uteki.agents.business_map import product_run
from uteki.agents.business_map.product_contract import ProductDraft, validate_draft
from uteki.agents.runtime.strict_json import StrictJSONError, parse_json_object

VERSION = 'single-outer-json-fence-v1'
PREFIX, SUFFIX = b'```json\n', b'```'
COPIES = {'source_packet.json': 'source_packet.json', 'skill.md': 'skill.md',
          'request.json': 'request.json', 'output_schema.json': 'output_schema.json',
          'configuration.json': 'configuration.json', 'response.txt': 'response.txt',
          'response_metadata.json': 'response_metadata.json',
          'source-result.json': 'result.json', 'source-manifest.json': 'manifest.json'}
OUTPUTS = ('business_map.json', 'revenue.json', 'evidence.html')
VALIDATION = {'status': 'passed_after_format_recovery',
    'source_execution_status': 'failed', 'source_error': 'StrictJSONError', 'semantic_acceptance': 'not_evaluated',
    'checks': ['exact_source_and_receipt_binding', 'one_outer_json_fence_only', 'inner_byte_equality',
               'strict_json_on_inner_bytes', 'full_product_contract', 'scope_source_dom_period_currency_unit_amounts_and_reconciliation']}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return parse_json_object(path.read_text())


def local(root, path):
    result = (root / path).resolve()
    require(result.is_relative_to(root) and result.is_file(), 'recovery_file_missing_or_outside_root')
    return result


def unwrap(raw):
    """Remove exactly the opening fence line and closing backticks, nothing else."""
    require(raw.startswith(PREFIX) and raw.endswith(b'\n' + SUFFIX), 'single_outer_json_fence_required')
    inner = raw[len(PREFIX):-len(SUFFIX)]
    require(b'```' not in inner, 'multiple_or_nested_fences_rejected')
    parse_json_object(inner.decode('utf-8'))
    require(PREFIX + inner + SUFFIX == raw, 'recovery_changed_inner_bytes')
    return inner


def source_context(root, source_run):
    result_path = local(root, source_run / 'result.json')
    source_run = result_path.parent
    result = read(result_path)
    require(result.get('status') == 'failed' and result.get('stop_reason') == 'StrictJSONError', 'strict_json_failure_source_required')
    manifest_path = local(root, source_run / 'manifest.json')
    manifest = read(manifest_path)
    for key in ('company_id', 'document_id', 'period_end', 'model', 'trace_id', 'source_sha256',
                'source_packet_sha256', 'skill_sha256', 'output_schema_sha256', 'request_sha256'):
        require(result.get(key) and result.get(key) == manifest.get(key), 'source_manifest_binding_mismatch: ' + key)
    raw = local(root, source_run / 'response.txt').read_bytes()
    try:
        parse_json_object(raw.decode('utf-8'))
    except StrictJSONError:
        pass
    else:
        raise ValueError('source_already_passes_strict_json')
    inner = unwrap(raw)
    packet_path = local(root, source_run / 'source_packet.json')
    skill_path = local(root, source_run / 'skill.md')
    request_path = local(root, source_run / 'request.json')
    for key, path in (('source_packet_sha256', packet_path), ('skill_sha256', skill_path), ('request_sha256', request_path)):
        require(sha(path.read_bytes()) == result[key], 'source_input_hash_mismatch: ' + key)
    schema = read(local(root, source_run / 'output_schema.json'))
    require(sha(json.dumps(schema, ensure_ascii=False).encode()) == result['output_schema_sha256']
            and schema == ProductDraft.model_json_schema(), 'source_schema_mismatch')
    request = read(request_path)
    require(request.get('model') == result['model'], 'source_request_model_mismatch')
    costs = result.get('costs', {})
    require(costs.get('requests') == 1 and len(costs.get('records', [])) == 1, 'single_source_call_required')
    call = costs['records'][0]
    receipt = read(local(root, source_run / 'response_metadata.json'))
    for key, value in {'request_sha256': result['request_sha256'], 'http_status': 200, 'stop_reason': 'end_turn',
                       'stream_complete': True, 'visible_text_secret_redacted': False}.items():
        require(call.get(key) == receipt.get(key) == value, 'complete_unredacted_source_receipt_required: ' + key)
    require(call.get('status') == 'succeeded' and call.get('response_id') == receipt.get('response_id')
            and bool(receipt.get('response_id')) and call.get('raw_usage') == receipt.get('raw_usage'), 'source_response_receipt_mismatch')
    packet = read(packet_path)
    product_run.verify_packet(packet, root, **{key: result[key] for key in ('company_id', 'document_id', 'period_end')})
    draft = validate_draft(parse_json_object(inner.decode('utf-8')), packet)
    binding = {'source_run': str(source_run.relative_to(root)), 'trace_id': result['trace_id'],
               'source_result_sha256': sha(result_path.read_bytes()), 'source_manifest_sha256': sha(manifest_path.read_bytes()),
               'raw_response_sha256': sha(raw), 'normalized_response_sha256': sha(inner),
               'request_sha256': result['request_sha256'], 'source_status': 'failed', 'source_stop_reason': 'StrictJSONError'}
    return dict(source_run=source_run, result=result, packet=packet, draft=draft, raw=raw, inner=inner, binding=binding)


def recovery_metadata(context):
    return {'extraction_method': 'system_agent_format_recovery', 'format_recovery_version': VERSION,
            'format_recovery_source': context['binding']}


def materialize(context, root, output):
    counts = product_run.materialize(context['draft'], context['packet'], root=root, output=output,
                                    manifest=context['result'], trace_id=context['result']['trace_id'])
    for name in ('business_map.json', 'revenue.json'):
        data = read(output / name)
        data['metadata'].update(recovery_metadata(context))
        product_run.write_json(output / name, data)
    return counts


def derive(root, source_run, output):
    root, output = root.resolve(), (root / output).resolve()
    context = source_context(root, (root / source_run).resolve())
    require(output.is_relative_to(root) and not output.exists()
            and not output.is_relative_to(context['source_run']), 'new_separate_recovery_directory_required')
    output.mkdir(parents=True)
    for target, source in COPIES.items():
        (output / target).write_bytes(local(root, context['source_run'] / source).read_bytes())
    (output / 'normalized-response.json').write_bytes(context['inner'])
    manifest = {'schema_version': 'business-revenue-format-recovery-v1', 'format_recovery_version': VERSION,
                **{key: context['result'][key] for key in ('company_id', 'document_id', 'period_end', 'model', 'provider',
                                                         'trace_id', 'source_sha256', 'source_packet_sha256', 'skill_sha256',
                                                         'output_schema_sha256', 'request_sha256')},
                'source_binding': context['binding'], 'transformation': {
                    'removed_prefix_utf8': PREFIX.decode(), 'removed_suffix_utf8': SUFFIX.decode(),
                    'inner_byte_range': [len(PREFIX), len(context['raw']) - len(SUFFIX)],
                    'inner_bytes_unchanged': True, 'internal_trailing_newline_preserved': True},
                'additional_model_calls': 0, 'additional_estimated_usd': '0',
                'cost_accounting': 'source_call_reference_only_do_not_sum_again',
                'copied_file_sha256': {name: sha((output / name).read_bytes()) for name in COPIES},
                'recovery_implementation_sha256': sha(Path(__file__).read_bytes()),
                'materializer_implementation_sha256': product_run.implementation_hashes()}
    product_run.write_json(output / 'manifest.json', manifest)
    counts = materialize(context, root, output)
    product_run.write_json(output / 'validation.json', VALIDATION)
    result = {**manifest, 'manifest_sha256': sha((output / 'manifest.json').read_bytes()), 'status': 'derived_candidate',
              'validation': 'passed_after_format_recovery', 'semantic_acceptance': 'not_evaluated', 'adoption': 'candidate',
              'stop_reason': 'local_format_recovery_completed', 'counts': counts,
              'artifacts_sha256': {name: sha((output / name).read_bytes()) for name in OUTPUTS},
              'normalized_response_sha256': sha(context['inner']), 'source_call_costs': context['result']['costs']}
    product_run.write_json(output / 'result.json', result)
    verify_derived(root, output, output / 'manifest.json')
    return result


def verify_derived(root, output, manifest_path):
    root, output = root.resolve(), output.resolve()
    manifest_path = local(root, manifest_path)
    require(manifest_path == output / 'manifest.json', 'recovery_manifest_must_belong_to_output')
    manifest, result = read(manifest_path), read(local(root, output / 'result.json'))
    require(manifest.get('format_recovery_version') == VERSION, 'unsupported_format_recovery_version')
    binding = manifest.get('source_binding')
    require(isinstance(binding, dict) and isinstance(binding.get('source_run'), str), 'recovery_source_binding_required')
    context = source_context(root, Path(binding['source_run']))
    require(binding == context['binding'], 'recovery_source_binding_mismatch')
    require(not output.is_relative_to(context['source_run']), 'recovery_cannot_replace_source_run')
    for key in ('company_id', 'document_id', 'period_end', 'model', 'provider', 'trace_id', 'source_sha256',
                'source_packet_sha256', 'skill_sha256', 'output_schema_sha256', 'request_sha256'):
        require(manifest.get(key) == context['result'][key], 'recovery_scope_mismatch: ' + key)
    expected_transformation = {'removed_prefix_utf8': PREFIX.decode(), 'removed_suffix_utf8': SUFFIX.decode(),
                              'inner_byte_range': [len(PREFIX), len(context['raw']) - len(SUFFIX)],
                              'inner_bytes_unchanged': True, 'internal_trailing_newline_preserved': True}
    require(manifest.get('transformation') == expected_transformation, 'recovery_transformation_mismatch')
    require(manifest.get('additional_model_calls') == 0 and manifest.get('additional_estimated_usd') == '0'
            and manifest.get('cost_accounting') == 'source_call_reference_only_do_not_sum_again', 'recovery_cost_accounting_invalid')
    for target, source in COPIES.items():
        raw = local(root, output / target).read_bytes()
        require(raw == local(root, context['source_run'] / source).read_bytes()
                and sha(raw) == manifest.get('copied_file_sha256', {}).get(target), 'recovery_input_copy_changed: ' + target)
    require(local(root, output / 'normalized-response.json').read_bytes() == context['inner'], 'recovery_inner_bytes_changed')
    require(all(result.get(key) == value for key, value in manifest.items())
            and result.get('manifest_sha256') == sha(manifest_path.read_bytes()), 'recovery_result_manifest_mismatch')
    require(result.get('status') == 'derived_candidate' and result.get('validation') == 'passed_after_format_recovery'
            and result.get('stop_reason') == 'local_format_recovery_completed'
            and result.get('semantic_acceptance') == 'not_evaluated' and result.get('adoption') == 'candidate', 'explicit_derived_candidate_required')
    require(read(local(root, output / 'validation.json')) == VALIDATION, 'recovery_validation_record_changed')
    require(result.get('source_call_costs') == context['result']['costs'] and 'costs' not in result
            and result.get('normalized_response_sha256') == sha(context['inner']), 'recovery_source_cost_or_response_mismatch')
    # Re-materialize the untouched JSON to reject edited derived facts, even if
    # somebody also updates the derived file checksums. Only the evidence file's
    # location changes between this temporary directory and the published one.
    with tempfile.TemporaryDirectory(prefix='.format-recovery-check-', dir=root) as temp:
        expected_dir = Path(temp)
        counts = materialize(context, root, expected_dir)
        expected_evidence = str((expected_dir / 'evidence.html').relative_to(root))
        actual_evidence = str((output / 'evidence.html').relative_to(root))
        def relocate(value):
            if isinstance(value, dict):
                return {k: relocate(v) for k, v in value.items()}
            if isinstance(value, list):
                return [relocate(v) for v in value]
            return actual_evidence if value == expected_evidence else value
        for name in OUTPUTS:
            path = local(root, output / name)
            require(sha(path.read_bytes()) == result.get('artifacts_sha256', {}).get(name), 'recovery_artifact_hash_mismatch')
            matches = read(path) == relocate(read(expected_dir / name)) if name.endswith('.json') else path.read_bytes() == (expected_dir / name).read_bytes()
            require(matches, 'recovery_materialized_artifact_changed: ' + name)
        require(result.get('counts') == counts, 'recovery_counts_mismatch')
    return context


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'source-run', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = derive(args.root, args.source_run, args.output)
    print(json.dumps({'output': str(args.output), 'status': result['status'], 'counts': result['counts'],
                      'source_binding': result['source_binding'], 'additional_model_calls': 0}, ensure_ascii=False, indent=2))
