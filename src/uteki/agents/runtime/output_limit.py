"""Typed output-capacity failure; classification does not authorize recovery."""
from agents.exceptions import ModelBehaviorError
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def validate_capacity_recovery(value, *, provider, model, base_max_tokens):
    """Opt-in provider capability; None preserves the historical frozen config."""
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'version','max_tokens','max_recoveries'}
            or value['version'] != 'output-capacity-recovery-v1'
            or provider != 'deepseek' or model != 'deepseek-flash'
            or type(base_max_tokens) is not int
            or type(value['max_tokens']) is not int or not base_max_tokens < value['max_tokens'] <= 16384
            or type(value['max_recoveries']) is not int or value['max_recoveries'] != 1):
        raise ValueError('unsupported explicit output capacity recovery policy')
    return dict(value)


def validate_capacity_settlement(paths, *, budget, expected_ledger, effective_max_tokens,
                                 diagnostic, artifact_root):
    """Authorize no dispatch; return evidence for one fully settled length call."""
    from .call_costs import estimate, pricing_snapshot
    fail = 'output capacity recovery requires one complete settled length call'
    if (Path(budget.path).resolve() != Path(expected_ledger).resolve()
            or diagnostic.get('finish_reason') != 'length'
            or diagnostic.get('usage_presence') != 'reported'
            or diagnostic.get('requested_max_tokens') != effective_max_tokens
            or diagnostic.get('usage',{}).get('output_tokens') != effective_max_tokens):
        raise ValueError(fail)
    ends = [Path(path) for path in paths if str(path).endswith('-end.json')]
    starts = [Path(path) for path in paths if str(path).endswith('-start.json')]
    if len(ends) != 1 or len(starts) != 1:
        raise ValueError(fail)
    raw = ends[0].read_bytes(); end = json.loads(raw)
    start = json.loads(starts[0].read_bytes())
    usage = end.get('raw_usage')
    if (end.get('provider') != 'deepseek' or end.get('requested_model') != 'deepseek-flash'
            or end.get('finish_reason') != 'length' or end.get('error_type') != 'ModelOutputLimitExceeded'
            or end.get('status') != 'failed_or_cancelled' or end.get('usage_presence') != 'reported'
            or end.get('usage_source') != 'provider_raw' or not isinstance(usage,dict)
            or any(type(usage.get(key)) is not int or usage[key] < 0
                   for key in ('prompt_tokens','completion_tokens','total_tokens'))
            or usage['completion_tokens'] != effective_max_tokens
            or usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']
            or diagnostic['usage'].get('input_tokens') != usage['prompt_tokens']
            or start.get('call_id') != end.get('call_id')
            or not isinstance(end.get('budget_reservation_id'),str)
            or start.get('budget_reservation_id') != end['budget_reservation_id']
            or end.get('pricing_snapshot') != pricing_snapshot('deepseek','deepseek-flash')):
        raise ValueError(fail)
    config = end.get('configuration_snapshot',{}).get('fields',{})
    if config.get('max_tokens',{}).get('value') != effective_max_tokens:
        raise ValueError(fail)
    expected = estimate({'input_tokens':usage['prompt_tokens'],
                         'output_tokens':usage['completion_tokens']},end['pricing_snapshot'])
    try:
        amount = Decimal(end['estimated_usd'])
        if not amount.is_finite() or amount < 0 or amount != Decimal(expected):
            raise ValueError(fail)
        with budget._transaction() as db:
            row = db.execute('SELECT actual,state FROM reservations WHERE id=?',
                             (end['budget_reservation_id'],)).fetchone()
        if row is None or row[1] != 'settled' or Decimal(row[0]) != amount:
            raise ValueError(fail)
    except (ArithmeticError, TypeError, KeyError):
        raise ValueError(fail) from None
    root = Path(artifact_root).resolve()
    return {'terminal':{'path':str(ends[0].relative_to(root)),
                        'sha256':hashlib.sha256(raw).hexdigest()},
            'settlement':{'budget_ledger':str(Path(budget.path).resolve()),
                          'reservation_id':end['budget_reservation_id'],
                          'state':'settled','estimated_usd':str(amount)}}


class ModelOutputLimitExceeded(ModelBehaviorError):
    """Reject the entire response while retaining safe, inspectable diagnostics."""

    def __init__(self, *, max_tokens, finish_reason, raw_usage):
        super().__init__('Model output limit exhausted; no action was accepted')
        raw = raw_usage if isinstance(raw_usage, dict) else {}
        details = raw.get('completion_tokens_details')
        details = details if isinstance(details, dict) else {}
        counters = {'input_tokens': raw.get('prompt_tokens'),
                    'output_tokens': raw.get('completion_tokens'),
                    'reasoning_tokens': details.get('reasoning_tokens')}
        # Missing provider counters remain unknown, never inferred as zero.
        counters = {key: value if type(value) is int and value >= 0 else None
                    for key, value in counters.items()}
        self.diagnostic = {
            'code': 'model_output_limit_exhausted', 'requested_max_tokens': max_tokens,
            'finish_reason': finish_reason, 'usage': counters,
            'usage_presence': 'reported' if all(counters[key] is not None
                for key in ('input_tokens', 'output_tokens')) else 'absent' if raw_usage is None else 'unknown',
            'action_accepted': False, 'automatic_recovery': False,
        }
