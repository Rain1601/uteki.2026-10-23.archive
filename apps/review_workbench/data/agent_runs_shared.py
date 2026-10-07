"""Read-only, bounded projections shared by historical and live run views.

These objects are presentation records, never business inputs or adoption state.
"""
import base64
from decimal import Decimal
import hashlib
import json
import re

PROJECTION_VERSION = 'agent-artifact-projection-v1'
_PRIVATE = re.compile(r'(api[_-]?key|authorization|credential|password|secret|access[_-]?token|sec[_-]?user[_-]?agent|budget_ledger|shared_budget|budget_at_|headers|environ)', re.I)
_ABSOLUTE = re.compile(r'(?<![\w:/])/(?:Users|home|private|tmp|var|etc)/[^\s\"\'<>;,)}\]]+')
_CONFIG = set('schema_version plan_origin role provider model prompt prompt_version prompt_sha256 decision_schema pricing_snapshot strict_provider_schema local_output_validation max_tokens request_timeout max_retries reasoning_effort thinking_mode provider_sdk_retries max_requests_total budget_policy limits method method_id version supported_forms batching assets method_file selection strategy'.split())
_CALL = set('call_id stage provider requested_model actual_upstream_model started_at ended_at elapsed_seconds pricing_snapshot actual_billed_usd status usage estimated_usd cost_basis response_id request_id system_fingerprint finish_reason raw_usage error error_type usage_presence usage_source'.split())
_CALL.update(('configuration_snapshot', 'http_status', 'provider_finish_reason'))
_BUSINESS = set(('schema_version request active_scope scope question task company_id source source_snapshot_id source_sha256 source_ids company_ids snapshot_id dataset dataset_snapshot_id dataset_manifest_sha256 knowledge_cutoff as_of role plan_origin delegation_instruction catalog financial_tasks state artifact_index artifacts recent_actions observations feedback prior_observations skills loaded_skills requirements coverage gaps pending_body_reads plans reason action status stop_reason trace decision_budget evidence_budget worker_runs financial_extractions evidence_bundle semantic_completeness adoption semantic_acceptance candidate_only result packet_id blocks entity_catalog metric_catalog period_catalog record_schema_version output_schema records evidence sources metrics relations unresolved validation normalization_version input_records normalized_records model_gaps raw_record_count normalized_record_count unresolved_count method_ref method selection batch_index total_batches core_package_complete strategy pass passes started_at completed_at finished_at projection_snapshot_id usage summary text version prompt prompt_version prompt_sha256 system_prompt effective_prompt parameters input output content items value kind artifact_id sha256 size_bytes scope_id created_step parent_ids evidence_id requirements requirement_ids query receipt full_output result_artifact preview_truncated reads execution_limited error error_type error_code validation layer retryable request_fingerprint progress_delta observation_bytes observation_budget tokens limits path decision attempt retry packet_sha256 visible_output calls elapsed_seconds source_period_contexts_ref source_block_references_ref block_ids task_type method_id method_sha256 task_id catalog_id query_run operation implementation run source_check source_hash checks diagnostics constraints metadata facts field value reported_value normalized_value unit currency period period_end source_refs block_refs candidates title label name input_sha256 packet_bytes response available_at form source_url block_id type table reported_page text_hash units source_documents outcome accepted rejected program_check input_packet output_packet current_plan context tool_result observation tool_outputs history tool artifact_refs next_action tools availability count bundle_id consumed_by produced_by source_policy_id include_candidates document_id index_id data request_id outputs records_path financial_task_catalog parent_packet batch_job').split())
_BUSINESS.update('packet raw_text parsed source_snapshot_ids periods period_start report_period_end execution_schema_version fiscal_periods fiscal_year fiscal_period source_period_contexts source_block_references'.split())
_BUSINESS.update('rows files tables columns company materialization limits source_count record_count evidence_count manifest_sha256 config_sha256 code_hashes'.split())
_BUSINESS.update('businesses relationships unknowns charts reported_subtotals'.split())
_CONFIG.add('text')


_BUSINESS.update({'model_input', 'model_input_sha256', 'model_config_sha256', 'provider', 'model',
                  'review', 'reasoning_effort', 'thinking_mode', 'input_format'})


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items() if not _PRIVATE.search(str(k))}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        value = _ABSOLUTE.sub('[local path restricted]', value)
        value = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [restricted]', value)
        return value
    return value


def project_artifact(value, kind):
    """Named top-level allowlists plus recursive removal of private fields.

    Callers classify artifacts from registered paths, not client-supplied kinds.
    Arbitrary implementation/environment files must not enter this function.
    """
    if kind == 'restricted':
        return {'notice': 'This artifact is not available in the public projection.'}
    if isinstance(value, dict):
        allowed = _CONFIG if kind == 'config' else _CALL if kind == 'model_call' else _BUSINESS
        projected = {k: v for k, v in value.items() if k in allowed and not _PRIVATE.search(k)}
        if 'configuration_snapshot' in projected:
            from uteki.agents.runtime.model_configuration import validate_configuration_snapshot
            projected['configuration_snapshot'] = validate_configuration_snapshot(projected['configuration_snapshot'])
        removed = len(value) - len(projected)
        if removed:
            projected['_projection_notice'] = f'{removed} top-level fields excluded by the display policy.'
        return _clean(projected)
    return _clean(value)


def call_configuration_snapshot(record, *, start=None, config=None, limits=None,
                                fingerprints=None, reasoning_configuration=None):
    """Prefer a captured request; reconstruct only documented historical fields.

    Unknown provider defaults remain unknown. Start/end captures, when both
    present, must describe the same outgoing request. No endpoint is inferred
    merely from a provider name.
    """
    from uteki.agents.runtime.model_configuration import build_configuration_snapshot, validate_configuration_snapshot
    start, config, limits = start or {}, config or {}, limits or {}
    captured = [validate_configuration_snapshot(value['configuration_snapshot'])
                for value in (start, record) if value.get('configuration_snapshot') is not None]
    if captured:
        if len({item['sha256'] for item in captured}) != 1:
            raise ValueError('Model call configuration changed between start and end')
        snapshot = captured[0]
        for key, recorded_key in (('provider', 'provider'), ('model', 'requested_model')):
            selected = snapshot['fields'][key]
            if selected['status'] != 'not_recorded' and selected['value'] != record.get(recorded_key):
                raise ValueError('Captured model configuration differs from call identity')
        return snapshot
    values = {'provider': record.get('provider'), 'model': record.get('requested_model')}
    sources = {key: 'call.' + recorded_key for key, recorded_key in (('provider', 'provider'), ('model', 'requested_model'))}
    for key, recorded_key in (('provider', 'provider'), ('model', 'model'), ('api_format', 'api_format'),
                              ('base_url', 'base_url'), ('max_tokens', 'max_tokens'), ('thinking', 'thinking_mode'),
                              ('reasoning_effort', 'reasoning_effort'), ('temperature', 'temperature'), ('top_p', 'top_p'),
                              ('seed', 'seed'), ('response_format', 'response_format'), ('tool_choice', 'tool_choice'),
                              ('parallel_tool_calls', 'parallel_tool_calls'), ('stream', 'stream'),
                              ('timeout_seconds', 'request_timeout'), ('max_retries', 'provider_sdk_retries')):
        if config.get(recorded_key) is not None:
            if key in {'provider', 'model'} and values.get(key) != config[recorded_key]:
                raise ValueError('Historical model configuration differs from call identity')
            values[key] = config[recorded_key]
            sources[key] = 'model-config.' + recorded_key
    for key, recorded_key in (('max_tokens', 'max_output_tokens_per_arm'), ('timeout_seconds', 'timeout_seconds')):
        if limits.get(recorded_key) is not None:
            values[key] = limits[recorded_key]
            sources[key] = 'experiment.limits.' + recorded_key
    if reasoning_configuration == 'thinking_enabled_high':
        values.update(thinking='enabled', reasoning_effort='high')
        sources.update(thinking='call.reasoning_configuration', reasoning_effort='call.reasoning_configuration')
    # provider_default_unspecified says no explicit setting was saved. It does
    # not identify the provider's effective thinking mode or reasoning effort.
    return build_configuration_snapshot(values, capture_kind='historical_partial', source='historical.record',
                                        sources=sources, fingerprints=fingerprints)


def configured_value(snapshot, key):
    item = snapshot['fields'][key]
    return item['value'] if item['status'] in {'explicit', 'recorded'} else None


def configured_thinking(snapshot):
    value = configured_value(snapshot, 'thinking')
    return value.get('type') if isinstance(value, dict) else value


def _encoded(value):
    return base64.urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).decode().rstrip('=')


def _decoded(token):
    if not isinstance(token, str) or not token or len(token) > 12000:
        raise ValueError('Invalid artifact navigation token')
    try:
        value = json.loads(base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)))
    except (ValueError, UnicodeError) as error:
        raise ValueError('Invalid artifact navigation token') from error
    if not isinstance(value, dict):
        raise ValueError('Invalid artifact navigation token')
    return value


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def artifact_page(ref, value, *, cursor=None, browse=None, max_bytes=65536):
    """Page an already-safe projection; bind all tokens to its exact identity."""
    if cursor and browse:
        raise ValueError('Choose either a continuation or a child item')
    if type(max_bytes) is not int or not 512 <= max_bytes <= 65536:
        raise ValueError('Artifact preview limit must be 512..65536 bytes')
    binding = {k: ref.get(k) for k in ('id', 'run_id', 'sha256')}
    binding.update(projection=PROJECTION_VERSION, projection_sha256=hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    parts, offset = [], 0
    if cursor or browse:
        token = _decoded(cursor or browse)
        if any(token.get(k) != v for k, v in binding.items()):
            raise ValueError('Artifact cursor run, hash or projection mismatch')
        if set(token) != set(binding) | {'parts', 'offset', 'mode'} or token['mode'] != ('cursor' if cursor else 'browse'):
            raise ValueError('Invalid artifact navigation token')
        parts, offset = token['parts'], token['offset']
        if (not isinstance(parts, list) or len(parts) > 100 or type(offset) is not int or offset < 0
                or any(not isinstance(p, (str, int)) or isinstance(p, bool) for p in parts)):
            raise ValueError('Invalid artifact navigation position')
    selected = value
    for part in parts:
        if isinstance(selected, dict) and isinstance(part, str) and part in selected:
            selected = selected[part]
        elif isinstance(selected, list) and type(part) is int and 0 <= part < len(selected):
            selected = selected[part]
        else:
            raise ValueError('Artifact child is not in the safe projection')
    def token(mode, next_parts, next_offset=0):
        return _encoded({**binding, 'mode': mode, 'parts': next_parts, 'offset': next_offset})
    children, next_cursor = [], None
    content_type = 'text' if isinstance(selected, str) else 'json'
    if isinstance(selected, str):
        if offset > len(selected):
            raise ValueError('Artifact text offset out of range')
        end = min(len(selected), offset + max_bytes // 6)
        content = selected[offset:end]
        if end < len(selected):
            next_cursor = token('cursor', parts, end)
    elif isinstance(selected, (dict, list)):
        entries = list(selected.items()) if isinstance(selected, dict) else list(enumerate(selected))
        if offset > len(entries):
            raise ValueError('Artifact offset out of range')
        content = {} if isinstance(selected, dict) else []
        end = offset
        for key, child in entries[offset:offset + 100]:
            candidate = {**content, key: child} if isinstance(content, dict) else [*content, child]
            if _size(candidate) <= max_bytes // 2:
                content = candidate
            else:
                children.append({'label': str(key), 'browse': token('browse', [*parts, key])})
            end += 1
            if _size(content) + _size(children) >= max_bytes - 1024:
                break
        if end < len(entries):
            next_cursor = token('cursor', parts, end)
    else:
        if offset:
            raise ValueError('Scalar artifacts have no continuation')
        content = selected
    return {**{k: ref.get(k) for k in ('id', 'run_id', 'label', 'kind', 'sha256', 'availability')},
            'pointer': '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts) if parts else '',
            'content': content, 'content_type': content_type, 'truncated': bool(next_cursor or children),
            'next_cursor': next_cursor, 'children': children, 'diagnostics': []}


def summarize_calls(calls):
    """Sum already deduplicated call records, retaining absent usage and cost."""
    ids = [c['call_id'] for c in calls]
    if len(ids) != len(set(ids)):
        raise ValueError('Call summaries require unique call IDs')
    for call in calls:
        for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens'):
            if call.get(key) is not None and (type(call[key]) is not int or call[key] < 0):
                raise ValueError('Invalid saved token count')
        if call.get('estimated_usd') is not None:
            try:
                price = Decimal(str(call['estimated_usd']))
            except ArithmeticError as error:
                raise ValueError('Invalid saved cost estimate') from error
            if not price.is_finite() or price < 0:
                raise ValueError('Invalid saved cost estimate')
    def summary(rows):
        known = [c for c in rows if c.get('usage_presence') == 'reported' and all(c.get(k) is not None for k in ('input_tokens', 'output_tokens'))]
        result = {'requests': len(rows), 'known_usage_calls': len(known), 'unknown_usage_calls': len(rows) - len(known),
                  'actual_billed_usd': None, 'unknown_cost_requests': sum(c.get('estimated_usd') is None for c in rows)}
        result['unknown_token_fields'] = {}
        for field in ('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens'):
            values = [c[field] for c in known if c.get(field) is not None]
            result[field] = sum(values) if values or not rows else None
            result['unknown_token_fields'][field] = len(rows) - len(values)
        result['known_estimated_usd'] = str(sum((Decimal(str(c['estimated_usd'])) for c in rows if c.get('estimated_usd') is not None), Decimal(0)))
        return result
    return {**summary(calls), 'roles': [{'role': role, **summary([c for c in calls if c.get('role') == role])}
                                      for role in sorted({c.get('role', 'unknown') for c in calls})]}
