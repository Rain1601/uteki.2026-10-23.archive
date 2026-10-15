"""Cross-process USD estimates; optional record-only limit, enforced charges fail closed."""
from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import hashlib
import re
import stat
from datetime import datetime, timezone


class BudgetExceeded(RuntimeError):
    pass


class RequestEnvelopeTooLarge(BudgetExceeded):
    """The local serialized-request capacity was exceeded, before reserving cost."""


class RequestRecoveryRequired(RuntimeError):
    """An uncertain dispatch cannot be retried as a fresh request."""


class RequestIdentityConflict(ValueError):
    """A durable request key was reused for different input or a response."""


class RequestInFlight(RuntimeError):
    """A known active request occupies the frozen dispatch concurrency slot."""


class RunBudget:
    def __init__(self, path, limit, *, enforce=True, allow_unknown_reservations=False,
                 allow_zero_limit=False):
        if type(enforce) is not bool:
            raise ValueError('Budget enforcement must be a boolean')
        self.enforce = enforce
        if type(allow_unknown_reservations) is not bool:
            raise ValueError('Unknown reservation policy must be a boolean')
        # Opt-in recovery keeps the entire original estimate committed. It never
        # settles a partial response at zero or pretends to know a provider bill.
        self.allow_unknown_reservations = allow_unknown_reservations
        if type(allow_zero_limit) is not bool:
            raise ValueError('Zero-limit policy must be a boolean')
        self.path = Path(path)
        self.existing_only = False
        if limit is None:
            if enforce:
                raise ValueError('An unlimited budget requires record-only mode')
        else:
            limit = Decimal(str(limit))
            if not limit.is_finite() or limit < 0 or (limit == 0 and not allow_zero_limit):
                raise ValueError('Positive finite budget required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, usd TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, reserved TEXT, actual TEXT, state TEXT)')
            db.execute('INSERT OR IGNORE INTO config VALUES (1, ?)', (None if limit is None else str(limit),))
            stored = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
            if (None if stored is None else Decimal(stored)) != limit:
                raise ValueError('Existing budget limit cannot be silently changed')
        self.existing_only = True

    @classmethod
    def open_existing(cls, path, limit, *, root_run_id):
        """Open a bound ledger without initializing, recreating or repairing it."""
        path = Path(path)
        if not path.is_absolute() or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('An existing regular absolute ledger path is required')
        instance = cls.__new__(cls)
        instance.path, instance.existing_only = path, True
        instance.enforce, instance.allow_unknown_reservations = True, False
        with instance._transaction() as db:
            root = instance._root(db)
            if root['root_run_id'] != root_run_id or Decimal(root['limit_usd']) != Decimal(str(limit)):
                raise RequestIdentityConflict('Existing root ledger identity or limit differs')
        return instance

    @contextmanager
    def _transaction(self):
        db = (sqlite3.connect(self.path.absolute().as_uri()+'?mode=rw', uri=True, timeout=30)
              if self.existing_only else sqlite3.connect(self.path, timeout=30))
        try:
            db.execute('PRAGMA synchronous=FULL')
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
            self._legacy_write(db)
            return self._reserve(db, amount)

    def _reserve(self, db, amount):
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

    @staticmethod
    def _legacy_write(db):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metered_root'").fetchone():
            if db.execute('SELECT 1 FROM metered_root').fetchone():
                raise ValueError('Bound root ledger requires the durable request API')

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
            self._legacy_write(db)
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
            self._legacy_write(db)
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
            self._legacy_write(db)
            row=db.execute('SELECT reserved, state FROM reservations WHERE id=?',(token,)).fetchone()
            if row is None or row[1] != 'unknown':
                return False
            db.execute('CREATE TABLE IF NOT EXISTS corrections (id TEXT PRIMARY KEY, evidence_sha256 TEXT, reason TEXT)')
            db.execute('INSERT INTO corrections VALUES (?,?,?)',
                (token,evidence_sha256,'preconnect_failure_no_http_dispatch'))
            db.execute("UPDATE reservations SET actual='0', state='settled' WHERE id=?",(token,))
            return True

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

    @staticmethod
    def _text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(label+' must be nonempty text')
        return value

    def bind_root(self, root_run_id, *, mode, max_requests, policy, max_in_flight_requests=None,
                  scope_ids=None):
        """Freeze a root's dispatch policy in its one existing cost ledger.

        This records local limits, not user authorization to call a provider.
        Legacy populated ledgers need an explicit migration, never silent adoption.
        """
        self._text(root_run_id, 'root_run_id')
        if mode not in {'offline', 'remote'} or type(max_requests) is not int or max_requests < 1:
            raise ValueError('Explicit mode and positive physical request limit required')
        if not isinstance(policy, dict) or not policy:
            raise ValueError('Explicit frozen root policy required')
        if max_in_flight_requests is not None and (type(max_in_flight_requests) is not int
                or not 1 <= max_in_flight_requests <= max_requests):
            raise ValueError('Dispatch concurrency must be positive and no greater than the request limit')
        if scope_ids is not None:
            if not isinstance(scope_ids, (list, tuple)) or not scope_ids:
                raise ValueError('An explicit nonempty list of allowed control scopes is required')
            for scope_id in scope_ids:
                self._text(scope_id, 'scope_id')
            if len(set(scope_ids)) != len(scope_ids):
                raise ValueError('Duplicate control scopes are not permitted')
            scope_ids = sorted(scope_ids)
        if not self.enforce or self.allow_unknown_reservations:
            raise ValueError('Durable roots require enforcement and unresolved-cost blocking')
        with self._transaction() as db:
            limit = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
            if limit is None or (mode == 'remote' and Decimal(limit) <= 0):
                raise ValueError('Remote roots require a positive finite reservation limit')
            binding = dict(schema_version='uteki-metered-root-v1', root_run_id=root_run_id,
                mode=mode, max_requests=max_requests, policy=policy, limit_usd=limit)
            # Omit the optional extension to preserve existing root bytes.
            if max_in_flight_requests is not None:
                binding['max_in_flight_requests'] = max_in_flight_requests
            if scope_ids is not None:
                binding['scope_ids'] = scope_ids
            contract = self._json(binding)
            db.execute('CREATE TABLE IF NOT EXISTS metered_root '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), contract TEXT NOT NULL, stop_reason TEXT)')
            current = db.execute('SELECT contract FROM metered_root WHERE id=1').fetchone()
            if current:
                if current[0] != contract:
                    raise RequestIdentityConflict('Root identity, mode or frozen policy differs')
            else:
                if db.execute('SELECT 1 FROM reservations LIMIT 1').fetchone():
                    raise ValueError('Cannot adopt an existing ledger without an explicit migration')
                db.execute('INSERT INTO metered_root VALUES (1,?,NULL)', (contract,))
            db.execute('CREATE TABLE IF NOT EXISTS metered_requests ('
                'request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, token TEXT NOT NULL UNIQUE, '
                'request_json TEXT NOT NULL, stage TEXT NOT NULL, response_event TEXT, bill_json TEXT, '
                'reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
            return json.loads(contract)

    @staticmethod
    def _has_scopes(db):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metered_scopes'").fetchone() is not None

    @staticmethod
    def _scope(db, scope_id):
        if not RunBudget._has_scopes(db):
            raise ValueError('No control scopes have been bound')
        row = db.execute('SELECT contract,stop_reason FROM metered_scopes WHERE scope_id=?', (scope_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown control scope')
        return json.loads(row[0]) | {'stop_reason': row[1]}

    @staticmethod
    def _request_scope(db, request_key):
        if not RunBudget._has_scopes(db):
            return None
        row = db.execute('SELECT scope_id FROM metered_request_scopes WHERE request_key=?', (request_key,)).fetchone()
        return row[0] if row else None

    def bind_scope(self, scope_id, *, max_requests, policy):
        """Freeze one execution scope inside the SAME root cost ledger.

        This is a request/stop boundary, not a new balance, native session or
        authorization. Existing unscoped requests cannot be adopted into it.
        """
        self._text(scope_id, 'scope_id')
        if type(max_requests) is not int or max_requests < 1 or not isinstance(policy, dict) or not policy:
            raise ValueError('Explicit scope request limit and policy required')
        with self._transaction() as db:
            root = self._root(db)
            if root.get('scope_ids') is not None and scope_id not in root['scope_ids']:
                raise RequestIdentityConflict('Control scope is outside the frozen root scope list')
            if max_requests > root['max_requests']:
                raise ValueError('Control scope cannot expand the root request limit')
            encoded = self._json(dict(schema_version='uteki-metered-scope-v1',
                root_run_id=root['root_run_id'], scope_id=scope_id, max_requests=max_requests, policy=policy))
            db.execute('CREATE TABLE IF NOT EXISTS metered_scopes '
                       '(scope_id TEXT PRIMARY KEY, contract TEXT NOT NULL, stop_reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS metered_request_scopes '
                       '(request_key TEXT PRIMARY KEY, scope_id TEXT NOT NULL)')
            current = db.execute('SELECT contract FROM metered_scopes WHERE scope_id=?', (scope_id,)).fetchone()
            if current:
                if current[0] != encoded:
                    raise RequestIdentityConflict('Control scope identity, limits or policy differ')
            else:
                self._check_dispatch_allowed(db, root)
                db.execute('INSERT INTO metered_scopes VALUES (?,?,NULL)', (scope_id, encoded))
            return self._scope(db, scope_id)

    @staticmethod
    def _check_scope_allowed(scope):
        if scope['stop_reason'] is not None:
            raise BudgetExceeded('Control scope stopped: '+scope['stop_reason'])

    def stop_scope(self, scope_id, reason):
        """Stop only this execution; late response/billing remains recordable."""
        self._text(scope_id, 'scope_id'); self._text(reason, 'stop_reason')
        with self._transaction() as db:
            self._root(db)
            current = self._scope(db, scope_id)
            if current['stop_reason'] is None:
                db.execute('UPDATE metered_scopes SET stop_reason=? WHERE scope_id=?', (reason, scope_id))
            return self._scope(db, scope_id)

    def inspect_scope(self, scope_id):
        self._text(scope_id, 'scope_id')
        with self._transaction() as db:
            root = self._root(db)
            scope = self._scope(db, scope_id)
            rows = db.execute('SELECT m.stage,COUNT(*) FROM metered_requests m '
                'JOIN metered_request_scopes s ON s.request_key=m.request_key '
                'WHERE s.scope_id=? GROUP BY m.stage', (scope_id,)).fetchall()
            return scope | dict(root_stop_reason=root['stop_reason'], request_stages=dict(rows))

    def _root(self, db):
        if not self.enforce or self.allow_unknown_reservations:
            raise ValueError('Durable roots cannot bypass enforcement or unknown reservations')
        row = db.execute('SELECT contract,stop_reason FROM metered_root WHERE id=1').fetchone()
        if row is None:
            raise ValueError('Bind a root before using the durable request API')
        value = json.loads(row[0])
        if value['limit_usd'] != db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]:
            raise RequestIdentityConflict('Frozen root limit differs from its budget')
        return value | {'stop_reason': row[1]}

    @staticmethod
    def _request(db, key):
        row = db.execute('SELECT m.request_key,m.fingerprint,m.token,m.request_json,m.stage,'
            'm.response_event,m.bill_json,m.reason,m.created_at,m.updated_at,r.reserved,r.actual,r.state '
            'FROM metered_requests m JOIN reservations r ON r.id=m.token WHERE m.request_key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('Unknown metered request')
        names = ('request_key','fingerprint','reservation_id','request','stage','response_event',
                 'bill','reason','created_at','updated_at','reserved_usd','settled_usd','cost_state')
        result = dict(zip(names, row))
        for name in ('request','response_event','bill'):
            if result[name] is not None:
                result[name] = json.loads(result[name])
        scope_id = RunBudget._request_scope(db, key)
        if scope_id is not None:
            result['control_scope_id'] = scope_id
        return result

    def prepare_request(self, request_key, request, *, reserve_usd, scope_id=None):
        """Atomically bind an immutable request identity to its cost reservation."""
        self._text(request_key, 'request_key')
        if not isinstance(request, dict) or not request:
            raise ValueError('Nonempty request identity and transport metadata required')
        if scope_id is not None:
            self._text(scope_id, 'scope_id')
        encoded = self._json(request)
        amount = Decimal(str(reserve_usd))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Finite nonnegative reservation required')
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self._transaction() as db:
            root = self._root(db)
            if root.get('scope_ids') is not None and scope_id not in root['scope_ids']:
                raise RequestIdentityConflict('Request requires one of the frozen root control scopes')
            if (root['mode'] == 'offline' and amount != 0) or (root['mode'] == 'remote' and amount <= 0):
                raise ValueError('Only offline synthetic requests may reserve zero')
            if db.execute('SELECT 1 FROM metered_requests WHERE request_key=?', (request_key,)).fetchone():
                current = self._request(db, request_key)
                if (current['fingerprint'] != fingerprint or Decimal(current['reserved_usd']) != amount
                        or current.get('control_scope_id') != scope_id):
                    raise RequestIdentityConflict('Request key reused with different input or reservation')
                return current
            self._check_dispatch_allowed(db, root)
            if scope_id is not None:
                scope = self._scope(db, scope_id)
                self._check_scope_allowed(scope)
                scope_count = db.execute('SELECT COUNT(*) FROM metered_requests m '
                    'JOIN metered_request_scopes s ON s.request_key=m.request_key '
                    "WHERE s.scope_id=? AND m.stage!='abandoned'", (scope_id,)).fetchone()[0]
                if scope_count >= scope['max_requests']:
                    raise BudgetExceeded('Control scope physical request slots exhausted')
            occupied = db.execute("SELECT COUNT(*) FROM metered_requests WHERE stage!='abandoned'").fetchone()[0]
            if occupied >= root['max_requests']:
                raise BudgetExceeded('Physical request slots exhausted, including prepared requests')
            token = self._reserve(db, amount)
            stamp = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO metered_requests VALUES (?,?,?,?,?,NULL,NULL,NULL,?,?)',
                       (request_key, fingerprint, token, encoded, 'prepared', stamp, stamp))
            if scope_id is not None:
                db.execute('INSERT INTO metered_request_scopes VALUES (?,?)', (request_key, scope_id))
            return self._request(db, request_key)

    @staticmethod
    def _check_dispatch_allowed(db, root):
        if root['stop_reason'] is not None:
            raise BudgetExceeded('Root stopped: '+root['stop_reason'])
        if root.get('scope_ids') is not None:
            # A missing association must not silently turn a scoped request
            # into a legacy unscoped request and bypass its persisted stop.
            if not RunBudget._has_scopes(db):
                if db.execute('SELECT 1 FROM metered_requests LIMIT 1').fetchone():
                    raise RequestRecoveryRequired('Control scope records are missing; never adopt as unscoped')
            else:
                rows = db.execute('SELECT s.scope_id,c.contract FROM metered_requests m '
                    'LEFT JOIN metered_request_scopes s ON s.request_key=m.request_key '
                    'LEFT JOIN metered_scopes c ON c.scope_id=s.scope_id').fetchall()
                for scope_id, encoded in rows:
                    if scope_id not in root['scope_ids'] or encoded is None:
                        raise RequestRecoveryRequired('Request control scope association is missing or outside the root')
                    scope = json.loads(encoded)
                    if scope.get('scope_id') != scope_id or scope.get('root_run_id') != root['root_run_id']:
                        raise RequestRecoveryRequired('Request control scope identity differs from its root')
        if db.execute("SELECT 1 FROM reservations WHERE state='unknown' LIMIT 1").fetchone():
            raise RequestRecoveryRequired('Unknown request cost must be reconciled before dispatch')
        if db.execute("SELECT 1 FROM metered_requests WHERE stage='outcome_unknown' LIMIT 1").fetchone():
            raise RequestRecoveryRequired('Billing reconciliation does not resolve an unknown response')

    def begin_request(self, request_key):
        """Commit possible dispatch BEFORE network I/O; a second dispatch is forbidden."""
        with self._transaction() as db:
            root = self._root(db)
            current = self._request(db, request_key)
            if current['stage'] != 'prepared':
                raise RequestRecoveryRequired('Request is not prepared; inspect/replay, never resend')
            self._check_dispatch_allowed(db, root)
            scope_id = current.get('control_scope_id')
            if scope_id is not None:
                self._check_scope_allowed(self._scope(db, scope_id))
            concurrency = root.get('max_in_flight_requests')
            if concurrency is not None:
                occupied = db.execute("SELECT COUNT(*) FROM metered_requests WHERE stage='dispatched'").fetchone()[0]
                if occupied >= concurrency:
                    raise RequestInFlight('Another known active request occupies the root dispatch slot')
            # Another completed request can cost more than its estimate. Recheck
            # the total before dispatching even an already-prepared request.
            committed = sum((Decimal(a if s == 'settled' else r) for r,a,s in
                db.execute('SELECT reserved,actual,state FROM reservations')), Decimal(0))
            if committed > Decimal(root['limit_usd']):
                raise BudgetExceeded('Settled and held costs exceed the frozen limit')
            db.execute("UPDATE metered_requests SET stage='dispatched',updated_at=? WHERE request_key=?",
                       (datetime.now(timezone.utc).isoformat(), request_key))
            return self._request(db, request_key)

    def _bill(self, root, billed_usd, receipt):
        if billed_usd is None:
            if receipt is not None:
                raise ValueError('A billing receipt must include a cost')
            return None, None
        amount = Decimal(str(billed_usd))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Finite nonnegative billed cost required')
        if root['mode'] == 'offline':
            if amount != 0 or receipt is not None:
                raise ValueError('Offline fixtures have zero synthetic cost, no provider bill')
        elif (not isinstance(receipt, dict)
              or not all(isinstance(receipt.get(k), str) and receipt[k].strip() for k in ('request_id','source'))
              or not isinstance(receipt.get('evidence_sha256'), str)
              or not re.fullmatch('[a-f0-9]{64}', receipt['evidence_sha256'])):
            raise ValueError('Verified provider billing evidence required; SDK estimates are insufficient')
        bill = dict(billed_usd=str(amount), receipt=receipt,
                    basis='synthetic_zero' if root['mode'] == 'offline' else 'provider_bill')
        return str(amount), self._json(bill)

    def record_response(self, request_key, response, *, billed_usd, receipt=None):
        """Persist complete transport response and cost state in ONE transaction.

        `response` is a durable transport result, not a business-success claim.
        The adapter verifies provider billing evidence before passing a receipt.
        """
        if not isinstance(response, dict):
            raise ValueError('Structured transport response required')
        with self._transaction() as db:
            root = self._root(db)
            amount, bill = self._bill(root, billed_usd, receipt)
            encoded = self._json(dict(response=response, billed_usd=amount, receipt=receipt))
            current = self._request(db, request_key)
            if current['response_event'] is not None:
                if self._json(current['response_event']) != encoded:
                    raise RequestIdentityConflict('A different response cannot overwrite the original')
                return current
            if current['stage'] not in {'dispatched','outcome_unknown'}:
                raise RequestRecoveryRequired('Response has no possibly-dispatched request')
            if current['cost_state'] == 'settled':
                # A provider bill may have been reconciled before its response
                # was recovered. Keep it; absence of usage must not undo it.
                if bill is not None and self._json(current['bill']) != bill:
                    raise RequestIdentityConflict('Recovered response conflicts with reconciled bill')
            else:
                db.execute('UPDATE reservations SET actual=?,state=? WHERE id=?',
                    (amount, 'settled' if amount is not None else 'unknown', current['reservation_id']))
                db.execute('UPDATE metered_requests SET bill_json=? WHERE request_key=?', (bill, request_key))
            db.execute("UPDATE metered_requests SET stage='responded',response_event=?,updated_at=? WHERE request_key=?",
                       (encoded, datetime.now(timezone.utc).isoformat(), request_key))
            return self._request(db, request_key)

    def abandon_prepared(self, request_key, *, reason):
        """Release only a request that has never crossed the dispatch boundary."""
        self._text(reason, 'reason')
        with self._transaction() as db:
            self._root(db)
            current = self._request(db, request_key)
            if current['stage'] == 'abandoned':
                if current['reason'] != reason:
                    raise RequestIdentityConflict('Abandonment reason differs')
                return current
            if current['stage'] != 'prepared':
                raise RequestRecoveryRequired('Possibly dispatched request cannot be released as unsent')
            db.execute("UPDATE reservations SET actual='0',state='settled' WHERE id=?", (current['reservation_id'],))
            db.execute("UPDATE metered_requests SET stage='abandoned',reason=?,updated_at=? WHERE request_key=?",
                       (reason, datetime.now(timezone.utc).isoformat(), request_key))
            return self._request(db, request_key)

    def recover_requests(self, *, scope_id=None):
        """Caller must hold exclusive runtime ownership; never automatically resend.

        Conservative even if the process died between begin_request and sending.
        Already recorded responses and prepared requests are left untouched.
        """
        with self._transaction() as db:
            self._root(db)
            if scope_id is None:
                keys = [r[0] for r in db.execute("SELECT request_key FROM metered_requests WHERE stage='dispatched'")]
            else:
                self._text(scope_id, 'scope_id')
                self._scope(db, scope_id)
                keys = [r[0] for r in db.execute('SELECT m.request_key FROM metered_requests m '
                    'JOIN metered_request_scopes s ON s.request_key=m.request_key '
                    "WHERE m.stage='dispatched' AND s.scope_id=?", (scope_id,))]
            for key in keys:
                current = self._request(db, key)
                db.execute("UPDATE reservations SET actual=NULL,state='unknown' WHERE id=? AND state='reserved'",
                           (current['reservation_id'],))
                db.execute("UPDATE metered_requests SET stage='outcome_unknown',reason='dispatch_outcome_unknown',updated_at=? WHERE request_key=?",
                           (datetime.now(timezone.utc).isoformat(), key))
            return [self._request(db, key) for key in keys]

    def reconcile_request(self, request_key, *, billed_usd, receipt):
        """Resolve only cost, never fabricate the missing transport response."""
        with self._transaction() as db:
            root = self._root(db)
            amount, bill = self._bill(root, billed_usd, receipt)
            if amount is None:
                raise ValueError('Known billed cost required for reconciliation')
            current = self._request(db, request_key)
            if current['cost_state'] == 'settled' and current['bill'] is not None:
                if self._json(current['bill']) != bill:
                    raise RequestIdentityConflict('A different bill cannot overwrite the reconciled bill')
                return current
            if current['cost_state'] != 'unknown':
                raise RequestRecoveryRequired('Only unknown cost can be reconciled')
            db.execute("UPDATE reservations SET actual=?,state='settled' WHERE id=?", (amount, current['reservation_id']))
            db.execute('UPDATE metered_requests SET bill_json=?,updated_at=? WHERE request_key=?',
                       (bill, datetime.now(timezone.utc).isoformat(), request_key))
            return self._request(db, request_key)

    def stop_root(self, reason):
        self._text(reason, 'stop_reason')
        with self._transaction() as db:
            root = self._root(db)
            if root['stop_reason'] is None:
                db.execute('UPDATE metered_root SET stop_reason=? WHERE id=1', (reason,))
            # The first stop reason is authoritative. Late responses may still
            # be recorded/reconciled, but stop can never re-enable dispatch.
            return self._root(db)

    def inspect_request(self, request_key):
        with self._transaction() as db:
            self._root(db)
            return self._request(db, request_key)

    def inspect_requests(self):
        with self._transaction() as db:
            self._root(db)
            keys = [row[0] for row in db.execute('SELECT request_key FROM metered_requests ORDER BY created_at,request_key')]
            return [self._request(db, key) for key in keys]

    def inspect_root(self):
        with self._transaction() as db:
            root = self._root(db)
            rows = db.execute('SELECT stage,COUNT(*) FROM metered_requests GROUP BY stage').fetchall()
            amounts = db.execute('SELECT m.stage,m.bill_json,r.reserved,r.actual,r.state '
                'FROM metered_requests m JOIN reservations r ON r.id=m.token').fetchall()
            known = sum((Decimal(actual) for _,bill,_,actual,state in amounts
                if state == 'settled' and bill is not None), Decimal(0))
            unknown = sum((Decimal(reserved) for _,_,reserved,_,state in amounts
                if state == 'unknown'), Decimal(0))
            pending = sum((Decimal(reserved) for _,_,reserved,_,state in amounts
                if state == 'reserved'), Decimal(0))
            settled = sum((Decimal(actual) for _,_,_,actual,state in amounts
                if state == 'settled'), Decimal(0))
            return root | dict(request_stages=dict(rows), cost=dict(
                known_billed_usd=str(known) if root['mode'] == 'remote' else None,
                synthetic_cost_usd='0' if root['mode'] == 'offline' else None,
                unknown_reserved_usd=str(unknown), in_flight_reserved_usd=str(pending),
                remaining_usd=str(Decimal(root['limit_usd'])-settled-unknown-pending),
                over_limit=settled+unknown+pending > Decimal(root['limit_usd'])))

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
