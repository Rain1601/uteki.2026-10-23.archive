"""One strict JSON object, without coercing ambiguous or non-finite values."""
import json
import math


class StrictJSONError(ValueError):
    """A fixed reason code; rejected text and keys never enter the message."""

    def __init__(self, code):
        self.code = code
        super().__init__('JSON output rejected: ' + code)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise StrictJSONError('duplicate_key')
        value[key] = item
    return value


def _constant(_):
    raise StrictJSONError('non_finite_number')


def _float(text):
    value = float(text)
    if not math.isfinite(value):
        raise StrictJSONError('non_finite_number')
    return value


def parse_json_object(text):
    """Reject duplicate keys at every depth, non-finite numbers and extra text."""
    if not isinstance(text, str):
        raise StrictJSONError('invalid_json')
    failure = None
    try:
        value = json.loads(text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float)
    except StrictJSONError as error:
        failure = error.code
    except (ValueError, TypeError, RecursionError, OverflowError):
        failure = 'invalid_json'
    # Raise outside the parser's except block so raw decoder errors are not
    # retained as exception context or echoed by the caller.
    if failure:
        raise StrictJSONError(failure)
    if not isinstance(value, dict):
        raise StrictJSONError('root_not_object')
    return value
