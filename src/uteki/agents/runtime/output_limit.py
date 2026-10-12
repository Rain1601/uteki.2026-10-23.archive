"""Typed output-capacity failure; classification does not authorize recovery."""
from agents.exceptions import ModelBehaviorError


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
