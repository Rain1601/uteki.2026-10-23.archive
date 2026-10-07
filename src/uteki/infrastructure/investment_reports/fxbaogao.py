"""Account-backed report tools. Credentials and signed URLs stay on the host."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from contextlib import contextmanager
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib import error, parse, request
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


@contextmanager
def _database(path):
    db = sqlite3.connect(path, timeout=30)
    try:
        with db:
            yield db
    finally:
        db.close()


class ReportError(ValueError):
    """Only fixed, safe error codes may cross the tool boundary."""


class Scope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str = Field(pattern='^fxbaogao$')
    start_date: date
    end_date: date
    org_names: list[str] = Field(min_length=1, max_length=20)
    report_ids: list[StrictInt] = Field(description='Explicit IDs; empty permits reports found within the selected dates and institutions.')

    @model_validator(mode='after')
    def check(self):
        if self.start_date > self.end_date or self.end_date == date.max:
            raise ValueError('invalid_publication_dates')
        if any(not n.strip() or n != n.strip() for n in self.org_names):
            raise ValueError('invalid_institution_scope')
        if any(n <= 0 for n in self.report_ids):
            raise ValueError('invalid_report_scope')
        return self


def load_key(credential_file=None):
    value = os.environ.get('FXBAOGAO_API_KEY')
    if value is None:
        if credential_file is None:
            raise ReportError('fxbaogao_credential_required')
        path = Path(credential_file)
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ReportError('private_credential_file_required')
        values = [line.partition('=')[2].strip().strip('\"\'') for line in path.read_text().splitlines()
                  if line.partition('=')[0].strip() == 'FXBAOGAO_API_KEY']
        if len(values) != 1:
            raise ReportError('one_credential_required')
        value = values[0]
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', value or ''):
        raise ReportError('invalid_credential')
    return value


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _transport(url, body, headers, limit):
    """No credential forwarding, retry or redirects, including PDF requests."""
    req = request.Request(url, data=body, headers=headers)
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=45) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ReportError('provider_response_too_large')
            length = response.headers.get('Content-Length')
            if length is not None and int(length) != len(data):
                raise ReportError('incomplete_response')
            return data
    except error.HTTPError as exc:
        code = {401: 'authentication_failed', 403: 'access_denied', 429: 'rate_limited'}.get(exc.code, 'provider_http_error')
        raise ReportError(code) from None
    except ReportError:
        raise
    except Exception:
        raise ReportError('provider_transport_failed') from None


def clean(value):
    if not isinstance(value, str):
        raise ReportError('invalid_provider_text')
    return html.unescape(re.sub(r'</?em>', '', value)).strip()


def _pdf(data):
    if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:
        raise ReportError('invalid_pdf_envelope')


class FxBaogaoService:
    """One explicit host scope and persistent download-attempt cap per workspace.

    A failed or uncertain download attempt keeps its reserved slot. This is an
    execution cap, not a claim about the provider's remaining account quota.
    """
    def __init__(self, *, scope, workspace, max_downloads=0, credential_file=None, transport=None):
        self.scope = Scope.model_validate(scope)
        if type(max_downloads) is not int or not 0 <= max_downloads <= 100:
            raise ReportError('invalid_download_cap')
        self._key = load_key(credential_file)
        self._transport = transport or _transport
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / 'reports.sqlite'
        self.available = set()
        self._lock = threading.RLock()
        self._cancelled = threading.Event()
        binding = json.dumps({'scope': self.scope.model_dump(mode='json'), 'max_downloads': max_downloads}, sort_keys=True)
        with _database(self.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, binding TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, report_id INTEGER, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS cache (report_id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO config VALUES (1, ?)', (binding,))
            if db.execute('SELECT binding FROM config WHERE id=1').fetchone()[0] != binding:
                raise ReportError('workspace_scope_or_budget_changed')
        self.max_downloads = max_downloads

    def cancel(self):
        """Stop new requests. Already-dispatched I/O cannot be revoked."""
        self._cancelled.set()

    def _check_active(self):
        if self._cancelled.is_set():
            raise ReportError('report_task_cancelled')

    def _api(self, operation, payload):
        self._check_active()
        if operation == 'download':
            url = 'https://api.fxbaogao.com/mofoun/agent/download?' + parse.urlencode(payload)
            body = None
        else:
            url = 'https://api.fxbaogao.com/mofoun/agent/' + operation
            body = json.dumps(payload).encode()
        raw = self._transport(url, body, {'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json'}, 2_000_000)
        try:
            value = json.loads(raw)
        except Exception:
            raise ReportError('invalid_provider_json') from None
        if not isinstance(value, dict) or type(value.get('code')) is not int or value['code'] != 0 or 'data' not in value:
            raise ReportError('provider_business_error')
        return value['data']

    def search_reports(self, keywords, page=1):
        if not isinstance(keywords, str) or not keywords.strip() or len(keywords) > 500:
            raise ReportError('nonblank_keywords_required')
        if type(page) is not int or not 1 <= page <= 10:
            raise ReportError('page_out_of_range')
        start = datetime.combine(self.scope.start_date, time(), timezone.utc)
        end = datetime.combine(self.scope.end_date + timedelta(days=1), time(), timezone.utc)
        values = self._api('search', {'keywords': keywords, 'orgNames': self.scope.org_names,
            'startTime': str(int(start.timestamp() * 1000)), 'endTime': str(int(end.timestamp() * 1000) - 1), 'pageNum': page})
        if not isinstance(values, list):
            raise ReportError('invalid_search_response')
        reports, excluded = [], 0
        for item in values:
            try:
                rid = item['reportId']
                institution = clean(item['orgName'])
                published = datetime.strptime(item['pubTimeStr'].strip('/'), '%Y/%m/%d').date()
                if type(rid) is not int or rid <= 0:
                    raise ValueError()
                if (institution not in self.scope.org_names or not self.scope.start_date <= published <= self.scope.end_date
                        or self.scope.report_ids and rid not in self.scope.report_ids):
                    excluded += 1
                    continue
                reports.append({'report_id': rid, 'title': clean(item['title']), 'institution': institution,
                    'published_at': published.isoformat(), 'reading_url': f'https://www.fxbaogao.com/view?id={rid}'})
            except (KeyError, TypeError, ValueError):
                raise ReportError('invalid_search_metadata') from None
        self.available.update(r['report_id'] for r in reports)
        return {'status': 'searched', 'reports': reports, 'excluded_out_of_scope': excluded,
                'page': page, 'coverage': 'provider_search_page_only', 'source_type': 'broker_research'}

    def _selected(self, report_id):
        if type(report_id) is not int or report_id not in self.available:
            raise ReportError('report_must_be_found_in_scoped_search')

    def get_paragraphs(self, report_id, keyword):
        self._selected(report_id)
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 500:
            raise ReportError('nonblank_keyword_required')
        value = self._api('paragraph', {'reportId': report_id, 'keyword': keyword})
        try:
            paragraphs = []
            for item in value['paragraphs']:
                if type(item['pageNum']) is not int or item['pageNum'] < 1:
                    raise ValueError()
                paragraphs.append({'text': clean(item['content']), 'pdf_page': item['pageNum']})
            result = {'status': 'excerpts_only', 'report_id': report_id, 'title': clean(value['title']),
                      'summary': clean(value.get('summary') or '') or None, 'paragraphs': paragraphs}
        except (KeyError, TypeError, ValueError):
            raise ReportError('invalid_paragraph_response') from None
        return result

    def _cached(self, report_id):
        with _database(self.db) as db:
            row = db.execute('SELECT sha256, size FROM cache WHERE report_id=?', (report_id,)).fetchone()
        if row is None:
            return None
        sha, size = row
        if not re.fullmatch('[0-9a-f]{64}', sha):
            raise ReportError('invalid_cache_receipt')
        path = self.root / (sha + '.pdf')
        if path.is_symlink() or not path.is_file():
            raise ReportError('cached_pdf_missing_or_changed')
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
            raise ReportError('cached_pdf_missing_or_changed')
        _pdf(data)
        return {'status': 'reused', 'report_id': report_id, 'artifact_id': sha, 'bytes': size,
                'download_attempts_this_call': 0, 'verification': 'bytes_and_pdf_envelope_only'}

    def _store(self, report_id, data):
        _pdf(data)
        sha = hashlib.sha256(data).hexdigest()
        path = self.root / (sha + '.pdf')
        if path.exists():
            if path.is_symlink() or path.read_bytes() != data:
                raise ReportError('existing_artifact_changed')
        else:
            with path.open('xb') as stream:
                stream.write(data)
        with _database(self.db) as db:
            db.execute('INSERT INTO cache VALUES (?, ?, ?)', (report_id, sha, len(data)))
        return sha

    def import_pdf(self, report_id, path, expected_sha256):
        """Host-only import; not exposed to model tools. Preserve prior receipt hash."""
        if type(report_id) is not int or report_id not in self.scope.report_ids:
            raise ReportError('import_requires_explicit_report_id')
        with self._lock:
            data = Path(path).read_bytes()
            if len(data) > 30_000_000 or hashlib.sha256(data).hexdigest() != expected_sha256:
                raise ReportError('import_hash_or_size_mismatch')
            existing = self._cached(report_id)
            if existing:
                if existing['artifact_id'] != expected_sha256:
                    raise ReportError('cached_version_conflict')
                return existing
            self._store(report_id, data)
            return self._cached(report_id)

    def download_pdf(self, report_id):
        self._selected(report_id)
        with self._lock:
            existing = self._cached(report_id)
            if existing:
                return existing
            attempt = str(uuid4())
            with _database(self.db) as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM attempts WHERE report_id=?', (report_id,)).fetchone():
                    raise ReportError('prior_download_attempt_requires_reconciliation')
                if db.execute("SELECT 1 FROM attempts WHERE state IN ('reserved', 'failed_or_unknown')").fetchone():
                    raise ReportError('unresolved_download_attempt')
                if db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] >= self.max_downloads:
                    raise ReportError('download_attempt_cap_reached')
                db.execute('INSERT INTO attempts VALUES (?, ?, ?)', (attempt, report_id, 'reserved'))
            try:
                url = self._api('download', {'reportId': report_id})
                parsed = parse.urlsplit(url) if isinstance(url, str) else None
                if (not parsed or parsed.scheme != 'https' or parsed.hostname != 'dr.fxbaogao.com'
                        or parsed.username or parsed.password or parsed.port not in (None, 443)):
                    raise ReportError('unapproved_pdf_address')
                self._check_active()
                data = self._transport(url, None, {}, 30_000_000)
                self._store(report_id, data)
                with _database(self.db) as db:
                    db.execute('UPDATE attempts SET state=? WHERE id=?', ('downloaded', attempt))
                return {**self._cached(report_id), 'status': 'downloaded', 'download_attempts_this_call': 1}
            except Exception:
                with _database(self.db) as db:
                    db.execute('UPDATE attempts SET state=? WHERE id=?', ('failed_or_unknown', attempt))
                raise

    def invoke(self, name, arguments):
        """Audited boundary shared by SDK tools and host CLI; safe errors only."""
        methods = {'search_reports': self.search_reports, 'get_paragraphs': self.get_paragraphs, 'download_pdf': self.download_pdf}
        call_id = str(uuid4())
        fields = {'search_reports': {'keywords', 'page'}, 'get_paragraphs': {'report_id', 'keyword'},
                  'download_pdf': {'report_id'}}
        args = {k: v for k, v in arguments.items() if k in fields.get(name, set())
                and (type(v) is int or isinstance(v, str) and len(v) <= 500)} if isinstance(arguments, dict) else {}
        args = {k: '<redacted>' if isinstance(v, str) and (self._key in v or 'auth_key=' in v) else v
                for k, v in args.items()}
        record = {'call_id': call_id, 'tool': name if name in methods else 'unknown', 'arguments': args,
                  'started_at': datetime.now(timezone.utc).isoformat()}
        with (self.root / (call_id + '-started.json')).open('x') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        try:
            if name not in methods:
                raise ReportError('unknown_report_tool')
            result = methods[name](**arguments)
        except ReportError as exc:
            result = {'status': 'error', 'error': str(exc)}
        except Exception:
            result = {'status': 'error', 'error': 'report_tool_failed'}
        # Neither transport headers nor raw URLs/bodies are part of this record.
        safe = json.dumps(result, ensure_ascii=False)
        if self._key in safe or 'auth_key=' in safe:
            result = {'status': 'error', 'error': 'sensitive_provider_response'}
        with (self.root / (call_id + '-tool.json')).open('x') as stream:
            json.dump({**record, 'ended_at': datetime.now(timezone.utc).isoformat(), 'result': result}, stream, ensure_ascii=False, indent=2)
        return result
