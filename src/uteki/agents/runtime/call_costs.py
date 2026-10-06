"""Local per-request ledger. Estimates are never presented as provider bills."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import html
from pathlib import Path
import time
from uuid import uuid4

from agents.models.interface import Model


def pricing_snapshot(provider, model):
    if provider == 'deepseek' and model in ('deepseek-flash', 'deepseek-v4-pro'):
        rates = {'deepseek-flash': ('0.30', '1.20', '0.006'),
                 'deepseek-v4-pro': ('1.32', '3.96', '0.044')}
        input_rate, output_rate, cached_rate = rates[model]
        return {'provider': provider, 'model': model, 'currency': 'USD',
                'input_per_million': input_rate, 'output_per_million': output_rate,
                'cached_input_per_million': cached_rate,
                'source': 'https://api-docs.deepseek.com/quick_start/pricing',
                'checked_on': '2026-09-22',
                'basis': 'Peak list price estimate; no cache or off-peak discounts applied'}
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


def write_record(path, record):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2,
                  default=lambda obj: obj.model_dump(mode='json'))


class MeteredModel(Model):
    """Non-streaming SDK adapter. Persist a start event before any network work."""
    def __init__(self, inner, folder, stage, provider, model, pricing, budget=None, *, max_request_bytes=400000):
        if type(max_request_bytes) is not int or max_request_bytes < 1:
            raise ValueError('max_request_bytes must be a positive integer')
        self.inner, self.folder, self.stage = inner, Path(folder), stage
        self.provider, self.model, self.pricing = provider, model, pricing
        self.budget = budget
        self.max_request_bytes = max_request_bytes
        self.folder.mkdir(exist_ok=True)

    async def get_response(self, *args, **kwargs):
        reservation = None
        reserved_usd = None
        if self.budget is not None:
            from uteki.agents.runtime.run_budget import reserve_request
            reservation, reserved_usd = reserve_request(
                self.budget, self.pricing, args, kwargs, max_request_bytes=self.max_request_bytes)
        call_id = str(uuid4())
        record = dict(call_id=call_id, stage=self.stage, provider=self.provider,
                      requested_model=self.model, actual_upstream_model=None,
                      started_at=datetime.now(timezone.utc).isoformat(),
                      pricing_snapshot=self.pricing, actual_billed_usd=None,
                      status='started', usage=None, estimated_usd=None,
                      cost_basis='uncached_list_price_estimate_not_bill',
                      budget_reservation_id=reservation, reserved_usd=reserved_usd)
        write_record(self.folder/(call_id+'-start.json'), record)
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
            return response
        except BaseException as exc:
            # No exception messages, headers, inputs or credentials in this ledger.
            record.update(status='failed_or_cancelled', error_type=type(exc).__name__,
                          http_status=getattr(exc, 'status_code', None))
            raise
        finally:
            if self.provider == 'deepseek':
                metadata = getattr(self.inner, 'response_metadata', None)
                if metadata:
                    record.update(metadata)
                raw = (metadata or {}).get('raw_usage') or {}
                # A failed/truncated answer may still have billable usage. A
                # missing/malformed usage object must not settle at SDK zeros.
                counters = (raw.get('prompt_tokens'), raw.get('completion_tokens'))
                if all(type(n) is int and n >= 0 for n in counters):
                    record['usage'] = {
                        'input_tokens': counters[0], 'output_tokens': counters[1],
                        'total_tokens': raw.get('total_tokens'),
                        'input_tokens_details': raw.get('prompt_tokens_details') or {
                            'cached_tokens': raw.get('prompt_cache_hit_tokens')},
                        'output_tokens_details': raw.get('completion_tokens_details'),
                    }
                    record['estimated_usd'] = estimate(record['usage'], self.pricing)
                else:
                    record.update(usage=None, estimated_usd=None)
            record.update(ended_at=datetime.now(timezone.utc).isoformat(),
                          elapsed_seconds=time.monotonic()-started)
            write_record(self.folder/(call_id+'-end.json'), record)
            if self.budget is not None:
                self.budget.settle(reservation, record['estimated_usd'])

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
