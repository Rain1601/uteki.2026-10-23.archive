"""Local per-request ledger. Estimates are never presented as provider bills."""
from dataclasses import asdict
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import html
from pathlib import Path
import time
from uuid import uuid4

from agents.models.interface import Model

from .model_configuration import capture_model_configuration


def pricing_snapshot(provider, model):
    if (provider, model) == ('aihubmix', 'qwen3.8-flash'):
        return {'provider': provider, 'model': model, 'currency': 'USD',
                'input_per_million': '0.1126', 'output_per_million': '0.38',
                'cached_input_per_million': '0.0141',
                'source': 'https://aihubmix.com/model/qwen3.8-flash', 'checked_on': '2026-10-09',
                'basis': 'Public list price estimate; raw cached input counted once; unsupported cache writes remain unknown'}
    if provider == 'deepseek' and model in ('deepseek-flash', 'deepseek-v4-pro'):
        rates = {'deepseek-flash': ('0.30', '1.20', '0.006'),
                 'deepseek-v4-pro': ('1.32', '3.96', '0.044')}
        input_rate, output_rate, cached_rate = rates[model]
        return {'provider': provider, 'model': model, 'currency': 'USD',
                'input_per_million': input_rate, 'output_per_million': output_rate,
                'cached_input_per_million': cached_rate,
                'source': 'https://api-docs.deepseek.com/quick_start/pricing',
                'checked_on': '2026-10-09',
                'basis': 'Peak list price estimate; no cache or off-peak discounts applied'}
    if provider == 'aihubmix' and model in ('claude-opus-5-5', 'claude-sonnet-5-5'):
        input_rate, output_rate = ('4', '20') if model == 'claude-opus-5-5' else ('2', '10')
        return {'provider': provider, 'model': model, 'currency': 'USD',
                'input_per_million': input_rate, 'output_per_million': output_rate,
                'cached_input_per_million': '0.2',
                'source': 'https://aihubmix.com/model/' + model,
                'checked_on': '2026-10-06',
                'basis': 'Uncached public list price estimate; excludes cache discounts, cache-writing charges, fees and account discounts'}
    if (provider, model) != ('aihubmix', 'gpt-5.4-mini'):
        return None
    return {'provider': provider, 'model': model, 'currency': 'USD',
            'input_per_million': '0.75', 'output_per_million': '4.5',
            'cached_input_per_million': None,
            'source': 'https://aihubmix.com/model/gpt-5.4-mini',
            'checked_on': '2026-09-13',
            'basis': 'Public list price; no cache discount, fees or account discounts applied'}


def estimate(usage, pricing):
    if not usage or not pricing or any(usage.get(k) is None for k in ('input_tokens', 'output_tokens')):
        return None
    return str((Decimal(usage['input_tokens']) * Decimal(pricing['input_per_million'])
                + Decimal(usage['output_tokens']) * Decimal(pricing['output_per_million'])) / Decimal(1000000))


def estimate_qwen_usage(raw, pricing):
    """Chat totals already include reasoning and cached reads; never add twice."""
    if not isinstance(raw, dict):
        return None
    incoming, outgoing = raw.get('prompt_tokens'), raw.get('completion_tokens')
    if any(type(n) is not int or n < 0 for n in (incoming, outgoing)):
        return None
    details = raw.get('prompt_tokens_details') or {}
    if not isinstance(details, dict):
        return None
    cached = details.get('cached_tokens', 0)
    if type(cached) is not int or not 0 <= cached <= incoming:
        return None
    def unsupported_cache(value):
        if not isinstance(value, dict):
            return False
        return any((('cache' in key.lower() and key != 'cached_tokens') and item not in (None, 0))
                   or unsupported_cache(item) for key, item in value.items())
    # No cache-writing controls are sent. An unexpected write charge is not
    # covered by this rate snapshot, so retain the full unknown reservation.
    if unsupported_cache(raw):
        return None
    return str((Decimal(incoming-cached)*Decimal(pricing['input_per_million'])
                + Decimal(cached)*Decimal(pricing['cached_input_per_million'])
                + Decimal(outgoing)*Decimal(pricing['output_per_million']))/Decimal(1000000))


def estimate_anthropic_usage(usage, pricing):
    """Anthropic input excludes cache reads; unsupported charges stay unknown."""
    if not isinstance(usage, dict) or not pricing:
        return None
    if any(isinstance(name, str) and 'cache' in name.lower()
           and name not in ('cache_read_input_tokens', 'cache_creation_input_tokens', 'cache_creation')
           for name in usage):
        return None
    for name in ('input_tokens', 'output_tokens'):
        if type(usage.get(name)) is not int or usage[name] < 0:
            return None
    for name in ('cache_read_input_tokens', 'cache_creation_input_tokens'):
        if name in usage and (type(usage[name]) is not int or usage[name] < 0):
            return None
    # This adapter sends no cache controls or server tools; their rates are not
    # part of its registered price snapshot. Never silently omit such charges.
    if usage.get('cache_creation_input_tokens', 0):
        return None
    for name in ('cache_creation', 'server_tool_use'):
        if name in usage and (not isinstance(usage[name], dict)
                or any(type(n) is not int or n != 0 for n in usage[name].values())):
            return None
    try:
        rates = [Decimal(str(pricing[name])) for name in ('input_per_million', 'output_per_million')]
        cached = usage.get('cache_read_input_tokens', 0)
        cache_rate = Decimal(str(pricing['cached_input_per_million'])) if cached else Decimal(0)
        if not all(rate.is_finite() and rate >= 0 for rate in (*rates, cache_rate)):
            return None
        return str((Decimal(usage['input_tokens']) * rates[0]
                    + Decimal(usage['output_tokens']) * rates[1] + Decimal(cached) * cache_rate) / Decimal(1000000))
    except (ArithmeticError, ValueError, TypeError, KeyError):
        return None


def write_record(path, record):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2,
                  default=lambda obj: obj.model_dump(mode='json'))


class MeteredModel(Model):
    """Non-streaming SDK adapter. Persist a start event before any network work."""
    def __init__(self, inner, folder, stage, provider, model, pricing, budget=None, *, max_request_bytes=400000, observation_context=None):
        if type(max_request_bytes) is not int or max_request_bytes < 1:
            raise ValueError('max_request_bytes must be a positive integer')
        self.inner, self.folder, self.stage = inner, Path(folder), stage
        self.provider, self.model, self.pricing = provider, model, pricing
        self.budget = budget
        self.observation_context = observation_context
        self.max_request_bytes = max_request_bytes
        self.folder.mkdir(exist_ok=True)

    def with_observation(self, context):
        model = copy(self)
        model.observation_context = context
        return model

    async def get_response(self, *args, **kwargs):
        observation = self.observation_context
        if observation:
            observation.guard()
        native = getattr(self.inner, 'native_usage_format', None) == 'anthropic_messages'
        settings = kwargs.get('model_settings', args[2] if len(args) > 2 else None)
        request_metadata = {}
        if native:
            # Native settings are validated before a reservation or request.
            self.inner.response_metadata = None
            self.inner.response_text = None
            configuration = self.inner.request_configuration(*args, **kwargs)
            if (configuration['fields']['provider']['value'] != self.provider
                    or configuration['fields']['model']['value'] != self.model):
                raise ValueError('Native adapter and meter provider/model must match')
            raw = self.inner.request_body(*args, **kwargs)
            request_metadata = {'request_sha256': hashlib.sha256(raw).hexdigest(), 'request_bytes': len(raw)}
            # Reserve from the actual body, including the schema instruction.
            # reserve_request adds its usual 16k overhead and output bound.
            reserve_args, reserve_kwargs = (), {'input': raw.decode('utf-8'), 'model_settings': settings}
        else:
            configuration = capture_model_configuration(self.provider, self.model, self.inner, args, kwargs)
            reserve_args, reserve_kwargs = args, kwargs
        reservation = None
        reserved_usd = None
        if self.budget is not None:
            from uteki.agents.runtime.run_budget import reserve_request
            reservation, reserved_usd = reserve_request(
                self.budget, self.pricing, reserve_args, reserve_kwargs, max_request_bytes=self.max_request_bytes,
                serialized_body=raw if native else None)
        extra_body = getattr(settings, 'extra_body', None)
        reasoning_effort = extra_body.get('reasoning_effort') if isinstance(extra_body, dict) else None
        if native:
            reasoning_effort = configuration['fields']['reasoning_effort']['value']
        call_id = str(uuid4())
        record = dict(call_id=call_id, stage=self.stage, provider=self.provider,
                      requested_model=self.model, actual_upstream_model=None, reasoning_effort=reasoning_effort,
                      started_at=datetime.now(timezone.utc).isoformat(),
                      pricing_snapshot=self.pricing, actual_billed_usd=None,
                      status='started', usage=None, estimated_usd=None,
                      usage_presence='unknown', usage_source='sdk_normalized',
                      configuration_snapshot=configuration,
                      cost_basis='uncached_list_price_estimate_not_bill',
                      budget_reservation_id=reservation, reserved_usd=reserved_usd)
        if native:
            record.update(request_metadata, usage_source='provider_raw',
                          cost_basis='anthropic_raw_input_output_cache_read_public_price_estimate_not_bill')
        start_path = self.folder/(call_id+'-start.json')
        try:
            write_record(start_path, record)
            if observation:
                ref = observation.publish(start_path, kind='model_call_start', owned_by_context=True)
                observation.emit('model_call.started', call_id=call_id, record_ref=ref,
                    role=observation.role, decision_index=observation.decision_index,
                    attempt=observation.attempt, stage=self.stage, provider=self.provider,
                    requested_model=self.model, reasoning_effort=reasoning_effort)
                observation.guard()
        except BaseException as error:
            # No provider invocation has happened: release only this known-unsent reservation.
            record.update(status='locally_blocked', dispatch_status='not_sent',
                error_type=type(error).__name__, ended_at=datetime.now(timezone.utc).isoformat(),
                elapsed_seconds=0, estimated_usd='0', usage_presence='absent', usage_source='host_not_sent')
            try:
                write_record(self.folder/(call_id+'-end.json'), record)
            finally:
                if self.budget is not None and reservation is not None:
                    self.budget.settle(reservation, '0')
            raise
        started = time.monotonic()
        try:
            inner = self.inner
            if isinstance(inner, str):
                from agents.models.openai_provider import OpenAIProvider
                inner = OpenAIProvider().get_model(inner)
            response = await inner.get_response(*args, **kwargs)
            record.update(status='succeeded', usage=asdict(response.usage),
                          response_id=response.response_id,
                          request_id=getattr(response, 'request_id', None))
            record['estimated_usd'] = estimate(record['usage'], self.pricing)
            # ChatCompletions SDK defaults missing usage to zeros. Without raw
            # provider evidence these zeros cannot settle a billable request.
            if self.provider != 'deepseek' and not any(record['usage'].get(k) for k in ('input_tokens', 'output_tokens')):
                record.update(usage=None, estimated_usd=None)
            return response
        except BaseException as exc:
            # No exception messages, headers, inputs or credentials in this ledger.
            record.update(status='failed_or_cancelled', error_type=type(exc).__name__,
                          http_status=getattr(exc, 'status_code', None))
            raise
        finally:
            if native:
                metadata = getattr(self.inner, 'response_metadata', None) or {}
                # Adapter metadata is allowlisted; never merge arbitrary errors,
                # response bodies or header dictionaries into the ledger.
                for key in ('actual_upstream_model', 'response_id', 'request_id', 'stop_reason',
                            'raw_usage', 'usage_presence', 'dispatch_status', 'http_status',
                            'visible_text_secret_redacted', 'transport_error_type', 'transport_phase',
                            'headers_received', 'headers_received_elapsed_seconds',
                            'first_event_elapsed_seconds', 'stream_complete', 'stream_event_count',
                            'stream_error_type', 'provider_error_type', 'schema_protocol',
                            'wire_schema_sha256', 'host_output_schema_sha256', 'transport_decode',
                            'transport_decode_error', 'host_decision_sha256',
                            'host_schema_validation', 'provider_enforced_schema'):
                    if key in metadata:
                        record[key] = metadata[key]
                raw_usage = metadata.get('raw_usage')
                known = metadata.get('usage_presence') == 'reported'
                record.update(usage_source='provider_raw', usage=None, estimated_usd=None)
                if known:
                    record['usage'] = {'input_tokens': raw_usage['input_tokens'],
                        'output_tokens': raw_usage['output_tokens'],
                        'cache_read_input_tokens': raw_usage.get('cache_read_input_tokens', 0),
                        'cache_creation_input_tokens': raw_usage.get('cache_creation_input_tokens', 0)}
                    record['estimated_usd'] = estimate_anthropic_usage(raw_usage, self.pricing)
                if metadata.get('dispatch_status') == 'not_sent':
                    record.update(estimated_usd='0', usage_presence='absent', usage_source='host_not_sent')
            elif self.provider == 'deepseek' or getattr(self.inner, 'raw_chat_usage', False):
                metadata = getattr(self.inner, 'response_metadata', None)
                if metadata:
                    record.update(metadata)
                raw = (metadata or {}).get('raw_usage') or {}
                # A failed/truncated answer may still have billable usage. A
                # missing/malformed usage object must not settle at SDK zeros.
                counters = (raw.get('prompt_tokens'), raw.get('completion_tokens'))
                if all(type(n) is int and n >= 0 for n in counters):
                    record.update(usage_presence='reported', usage_source='provider_raw')
                    record['usage'] = {
                        'input_tokens': counters[0], 'output_tokens': counters[1],
                        'total_tokens': raw.get('total_tokens'),
                        'input_tokens_details': raw.get('prompt_tokens_details') or {
                            'cached_tokens': raw.get('prompt_cache_hit_tokens')},
                        'output_tokens_details': raw.get('completion_tokens_details'),
                    }
                    record['estimated_usd'] = estimate(record['usage'], self.pricing)
                    if (self.provider, self.model) == ('aihubmix', 'qwen3.8-flash'):
                        record['estimated_usd'] = estimate_qwen_usage(raw, self.pricing)
                        record['cost_basis'] = 'qwen_raw_prompt_completion_cache_read_public_price_estimate_not_bill'
                else:
                    record.update(usage=None, estimated_usd=None,
                                  usage_presence='absent' if metadata and metadata.get('raw_usage') is None else 'unknown',
                                  usage_source='provider_raw')
            record.update(configuration_snapshot=configuration,
                          ended_at=datetime.now(timezone.utc).isoformat(),
                          elapsed_seconds=time.monotonic()-started)
            end_path = self.folder/(call_id+'-end.json')
            try:
                write_record(end_path, record)
            finally:
                # Observation failure must never bypass existing accounting cleanup.
                if self.budget is not None:
                    self.budget.settle(reservation, record['estimated_usd'])
            if observation:
                ref = observation.publish(end_path, kind='model_call_end', owned_by_context=True)
                observation.emit('model_call.finished', call_id=call_id, record_ref=ref,
                    role=observation.role, decision_index=observation.decision_index,
                    attempt=observation.attempt, stage=self.stage, provider=self.provider,
                    requested_model=self.model, reasoning_effort=reasoning_effort, status=record['status'])
                if record['status'] == 'succeeded':
                    observation.guard()

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError('Streaming metering is not implemented; use non-streaming runner')
        yield  # pragma: no cover


def summarize(folder):
    folder = Path(folder)
    records = []
    for start in sorted(folder.glob('*-start.json')):
        end = start.with_name(start.name.replace('-start.json', '-end.json'))
        records.append(json.loads((end if end.exists() else start).read_text()))
    return {'requests': len(records),
            'unknown_cost_requests': sum(r['estimated_usd'] is None for r in records),
            'known_estimated_usd': str(sum((Decimal(r['estimated_usd']) for r in records
                                         if r['estimated_usd'] is not None), Decimal(0))),
            'actual_billed_usd': None, 'records': records}


def cost_report(run, backfill=False):
    run = Path(run)
    manifest = json.loads((run/'manifest.json').read_text())
    records = []
    for case in manifest['cases']:
        for mode in ('single', 'team'):
            folder = run/case/mode
            if (folder/'costs.json').exists():
                rows = json.loads((folder/'costs.json').read_text())['records']
            elif backfill:
                rows = []
                for stage in ('analyst', 'reviewer', 'analyst_revision'):
                    path = folder/(stage+'-output.json')
                    if not path.exists():
                        continue
                    usage = json.loads(path.read_text())['usage']
                    for i, entry in enumerate(usage.get('request_usage_entries', []), 1):
                        pricing = pricing_snapshot(manifest['provider'], manifest['model'])
                        rows.append(dict(call_id=f'{case}/{mode}/{stage}/{i}', stage=stage,
                            provider=manifest['provider'], requested_model=manifest['model'],
                            status='historical_usage_backfill', started_at=None, ended_at=None,
                            elapsed_seconds=None, request_id=None, response_id=None,
                            usage=entry, pricing_snapshot=pricing, actual_billed_usd=None,
                            estimated_usd=estimate(entry, pricing)))
            else:
                rows = []
            records.extend(dict(r, case=case, mode=mode) for r in rows)
    totals = {}
    for mode in ('single', 'team'):
        selected = [r for r in records if r['mode'] == mode]
        totals[mode] = dict(requests=len(selected),
            unknown_cost_requests=sum(r['estimated_usd'] is None for r in selected),
            known_estimated_usd=str(sum((Decimal(r['estimated_usd']) for r in selected
                                      if r['estimated_usd'] is not None), Decimal(0))))
    data = dict(schema_version='1', run_id=run.name, totals=totals, records=records,
                actual_billed_usd=None, backfilled=backfill,
                note='USD estimates without cache discounts; not a bill. Historical backfill excludes unsaved probes/failed calls and cannot recover request timestamps or IDs.')
    write_record(run/'cost-report.json', data)
    e = lambda value: html.escape(str(value))
    table = ''
    for r in records:
        u = r.get('usage') or {}
        cached = (u.get('input_tokens_details') or {}).get('cached_tokens')
        values = [r['case'], r['mode'], r['stage'], r['call_id'], r.get('started_at') or '未记录',
                  u.get('input_tokens', '未知'), cached if cached is not None else '未知',
                  u.get('output_tokens', '未知'), r['estimated_usd'] or '未知', r['status']]
        table += '<tr>'+''.join('<td>'+e(v)+'</td>' for v in values)+'</tr>'
    page = '''<!doctype html><meta charset="utf-8"><title>调用费用明细</title>
<style>body{font:14px/1.6 system-ui;margin:28px;color:#243b30}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}td{overflow-wrap:anywhere}h1{font-size:24px}</style>
<h1>调用费用明细 · '''+e(run.name)+'''</h1>
<p>全部金额为 USD。不含缓存折扣的公开单价估算，并非实际账单；失败/缺失用量不计作零费用。</p>
<p>历史补录无法恢复请求时间、请求 ID，也不包含之前未保存的兼容性探测调用。缓存 Token 属于输入 Token，不重复计费；推理 Token 属于输出 Token，不重复计费。</p>
<p>'''+e(json.dumps(totals, ensure_ascii=False))+'''</p><p><a href="cost-report.json">完整机器可读记录（含价格快照）</a> · <a href="review.html">返回回答对比</a></p>
<table><thead><tr>'''+''.join('<th>'+s+'</th>' for s in ['问题','模式','阶段','调用 ID','开始时间','输入','缓存输入','输出','估算费用','状态'])+'</tr></thead><tbody>'+table+'</tbody></table>'
    with (run/'costs.html').open('x', encoding='utf-8') as f:
        f.write(page)
    return totals
