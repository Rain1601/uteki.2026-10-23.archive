"""Cross-process USD estimates; optional record-only limit, enforced charges fail closed."""
from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import hashlib
from datetime import datetime, timezone


class BudgetExceeded(RuntimeError):
    pass


class RequestEnvelopeTooLarge(BudgetExceeded):
    """The local serialized-request capacity was exceeded, before reserving cost."""


class RunBudget:
    def __init__(self, path, limit, *, enforce=True, allow_unknown_reservations=False):
        if type(enforce) is not bool:
            raise ValueError('Budget enforcement must be a boolean')
        self.enforce = enforce
        if type(allow_unknown_reservations) is not bool:
            raise ValueError('Unknown reservation policy must be a boolean')
        # Opt-in recovery keeps the entire original estimate committed. It never
        # settles a partial response at zero or pretends to know a provider bill.
        self.allow_unknown_reservations = allow_unknown_reservations
        self.path = Path(path)
        if limit is None:
            if enforce:
                raise ValueError('An unlimited budget requires record-only mode')
        else:
            limit = Decimal(str(limit))
            if not limit.is_finite() or limit <= 0:
                raise ValueError('Positive finite budget required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, usd TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, reserved TEXT, actual TEXT, state TEXT)')
            db.execute('INSERT OR IGNORE INTO config VALUES (1, ?)', (None if limit is None else str(limit),))
            stored = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
            if (None if stored is None else Decimal(stored)) != limit:
                raise ValueError('Existing budget limit cannot be silently changed')

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, amount):
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Positive finite reservation required')
        with self._transaction() as db:
            rows = db.execute('SELECT reserved, actual, state FROM reservations').fetchall()
            if self.enforce:
                if not self.allow_unknown_reservations and any(state == 'unknown' for _, _, state in rows):
                    raise BudgetExceeded('Prior request cost unknown; reconcile before continuing')
                committed = sum((Decimal(actual if state == 'settled' else reserved)
                                 for reserved, actual, state in rows), Decimal(0))
                limit = Decimal(db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0])
                if committed + amount > limit:
                    raise BudgetExceeded('Estimated budget exhausted including in-flight reservations')
            token = str(uuid4())
            db.execute('INSERT INTO reservations VALUES (?, ?, NULL, ?)', (token, str(amount), 'reserved'))
        return token

    def increase_limit(self, new_limit, *, expected_current, authorization):
        """Apply explicit user authorization once, retaining every old reservation.

        The caller supplies the user's approval context. This records approval;
        it does not infer permission from a positive numeric limit.
        """
        old, new = Decimal(str(expected_current)), Decimal(str(new_limit))
        if not old.is_finite() or not new.is_finite() or old <= 0 or new <= old:
            raise ValueError('Explicit finite limit increase required')
        if (not isinstance(authorization, dict) or authorization.get('authorized_by') != 'user'
                or not all(isinstance(authorization.get(k), str) and authorization[k].strip()
                           for k in ('authorization_id', 'confirmation', 'scope'))
                or authorization.get('old_limit_usd') != str(old)
                or authorization.get('new_limit_usd') != str(new)):
            raise ValueError('Matching explicit user authorization required')
        body = json.dumps(authorization, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        record = dict(authorization=authorization, authorization_sha256=hashlib.sha256(body.encode()).hexdigest(),
                      applied_at=datetime.now(timezone.utc).isoformat(), old_limit_usd=str(old), new_limit_usd=str(new))
        with self._transaction() as db:
            current = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
            if current is None or Decimal(current) != old:
                raise ValueError('Prior limit changed before authorization')
            if db.execute("SELECT 1 FROM reservations WHERE state='reserved'").fetchone():
                raise ValueError('Cannot change a limit while requests are in flight')
            db.execute('CREATE TABLE IF NOT EXISTS limit_authorizations (id TEXT PRIMARY KEY, record TEXT NOT NULL)')
            db.execute("CREATE TRIGGER IF NOT EXISTS limit_auth_no_update BEFORE UPDATE ON limit_authorizations BEGIN SELECT RAISE(ABORT, 'authorization immutable'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS limit_auth_no_delete BEFORE DELETE ON limit_authorizations BEGIN SELECT RAISE(ABORT, 'authorization immutable'); END")
            db.execute('INSERT INTO limit_authorizations VALUES (?, ?)',
                       (authorization['authorization_id'], json.dumps(record, ensure_ascii=False, sort_keys=True)))
            db.execute('UPDATE config SET usd=? WHERE id=1', (str(new),))
        return record

    def settle(self, token, actual):
        if actual is not None:
            actual = Decimal(str(actual))
            if not actual.is_finite() or actual < 0:
                raise ValueError('Invalid actual estimate')
        with self._transaction() as db:
            row = db.execute('SELECT state FROM reservations WHERE id=?', (token,)).fetchone()
            if row != ('reserved',):
                raise ValueError('Reservation missing or already settled')
            db.execute('UPDATE reservations SET actual=?, state=? WHERE id=?',
                       (str(actual) if actual is not None else None,
                       'settled' if actual is not None else 'unknown', token))

    def reconcile_preconnect_failure(self, token, metadata, *, evidence_sha256):
        """Release an old misclassified pre-HTTP failure; never a read interruption.

        Legacy native logs marked sent before connecting. Connect/Pool failures
        with no headers or usage mean no HTTP request reached the model service.
        Keep an immutable correction in this ledger instead of editing that log.
        """
        import re
        if (not isinstance(metadata, dict)
                or metadata.get('transport_error_type') not in {'ConnectError','ConnectTimeout','PoolTimeout'}
                or metadata.get('headers_received') is not False
                or metadata.get('transport_phase') != 'awaiting_headers'
                or metadata.get('usage_presence') != 'absent'
                or any(metadata.get(k) is not None for k in ('http_status','response_id','raw_usage'))
                or not isinstance(evidence_sha256,str)
                or not re.fullmatch('[a-f0-9]{64}',evidence_sha256)):
            raise ValueError('proven_preconnect_failure_required')
        with self._transaction() as db:
            row=db.execute('SELECT reserved, state FROM reservations WHERE id=?',(token,)).fetchone()
            if row is None or row[1] != 'unknown':
                return False
            db.execute('CREATE TABLE IF NOT EXISTS corrections (id TEXT PRIMARY KEY, evidence_sha256 TEXT, reason TEXT)')
            db.execute('INSERT INTO corrections VALUES (?,?,?)',
                (token,evidence_sha256,'preconnect_failure_no_http_dispatch'))
            db.execute("UPDATE reservations SET actual='0', state='settled' WHERE id=?",(token,))
            return True

    def summary(self):
        with self._transaction() as db:
            rows = db.execute('SELECT reserved, actual, state FROM reservations').fetchall()
            return {'limit_usd': db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0],
                    'estimated_spent_usd': str(sum((Decimal(a) for _, a, s in rows if s == 'settled'), Decimal(0))),
                    'held_usd': str(sum((Decimal(r) for r, _, s in rows if s != 'settled'), Decimal(0))),
                    'unknown_requests': sum(s == 'unknown' for _, _, s in rows),
                    'in_flight_requests': sum(s == 'reserved' for _, _, s in rows),
                    'requests': len(rows), 'actual_billed_usd': None,
                    'enforcement': 'enforced' if self.enforce else 'record_only'}


def reserve_request(budget, pricing, args, kwargs, *, max_request_bytes=400000, serialized_body=None):
    """Conservative text envelope estimate, not a provider-enforced billing cap."""
    if type(max_request_bytes) is not int or max_request_bytes < 1:
        raise ValueError('max_request_bytes must be a positive integer')
    if not pricing:
        raise BudgetExceeded('No price estimate available')
    settings = kwargs.get('model_settings', args[2] if len(args) > 2 else None)
    maximum = getattr(settings, 'max_tokens', None)
    if not isinstance(maximum, int) or maximum <= 0:
        raise BudgetExceeded('Bounded output required')
    # The application only sends text. Limit the entire serialized prompt envelope
    # and reserve at one token per UTF-8 byte plus 16k protocol/schema overhead.
    def encode(obj):
        if hasattr(obj, 'model_dump'):
            return obj.model_dump(mode='json')
        if hasattr(obj, 'params_json_schema'):
            return {'name':obj.name, 'description':obj.description, 'schema':obj.params_json_schema}
        if hasattr(obj, 'json_schema'):
            return obj.json_schema()
        return str(type(obj).__name__)
    if serialized_body is not None:
        if not isinstance(serialized_body, bytes):
            raise ValueError('serialized_body must be the exact request bytes')
        size = len(serialized_body)
    else:
        size = len(json.dumps([args, kwargs], default=encode, ensure_ascii=False).encode())
    if size > max_request_bytes:
        raise RequestEnvelopeTooLarge(
            f'Request envelope is {size} bytes; configured capacity is {max_request_bytes} bytes')
    estimate = ((Decimal(size + 16000) * Decimal(pricing['input_per_million'])
                 + Decimal(maximum) * Decimal(pricing['output_per_million'])) / Decimal(1000000))
    return budget.reserve(estimate), str(estimate)
