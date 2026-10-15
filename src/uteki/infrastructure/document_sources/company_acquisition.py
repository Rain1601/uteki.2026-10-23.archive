"""Bounded company-source acquisition. Freezes originals; does not index or adopt them."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from .filing_integrity import atomic_write_new, validate_sec_filing

VERSION = 'company-source-run-v1'
TICKERS = 'https://www.sec.gov/files/company_tickers.json'
SEC_HOSTS = {'www.sec.gov', 'data.sec.gov'}
DEFAULT_LIMITS = dict(max_requests=60, max_documents=30, max_bytes_per_document=20000000,
                      timeout_seconds=20, retries=1, backoff_seconds=.5, max_discovery_links=12,
                      max_total_bytes=25000000000, min_request_interval_seconds=.15)
MAX_LIMITS = dict(max_requests=500, max_documents=200, max_bytes_per_document=50000000,
                  timeout_seconds=60, retries=3, backoff_seconds=5, max_discovery_links=100,
                  max_total_bytes=25000000000, min_request_interval_seconds=60)


class AcquisitionError(ValueError):
    pass


class LimitReached(AcquisitionError):
    pass


class AcquisitionCancelled(AcquisitionError):
    pass


class AcquisitionDeferred(AcquisitionError):
    def __init__(self, next_retry_at, http_status):
        super().__init__('request_cooldown_active')
        self.next_retry_at, self.code = next_retry_at, http_status


def _utc_now():
    return datetime.now(timezone.utc)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _day(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'{label} must be an explicit ISO date')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'invalid {label}') from error


def _url(value, allowed, *, resolve=False):
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not host or host not in allowed or host == 'localhost' or host.endswith(('.localhost', '.local'))):
        raise AcquisitionError('URL outside approved public HTTPS hosts')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise AcquisitionError('non-public address forbidden')
    if resolve:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise AcquisitionError('non-public DNS destination forbidden')
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ''))


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed, on_redirect=None, *, resolve=True):
        self.allowed = allowed
        self.on_redirect = on_redirect
        self.resolve = resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _url(newurl, self.allowed, resolve=self.resolve)
        if self.on_redirect is not None:
            self.on_redirect(req.full_url, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _transport(config):
    """Explicit local CONNECT proxy for SEC endpoints; never trust target fake IPs.

    The configured proxy is the trust boundary for destination DNS. Target TLS
    remains verified by urllib's HTTPS handler against the original hostname.
    Non-SEC acquisition retains the normal public-DNS transport.
    """
    value = config.get('transport')
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'mode', 'proxy_url', 'destination_hosts'}:
        raise ValueError('explicit proxy transport requires mode, proxy_url and destination_hosts')
    if value['mode'] != 'trusted_local_http_proxy':
        raise ValueError('unsupported acquisition transport')
    if not isinstance(value['proxy_url'], str):
        raise ValueError('proxy_url must be an explicit URL string')
    parsed = urllib.parse.urlsplit(value['proxy_url'])
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port
    except ValueError as error:
        raise ValueError('proxy must use an explicit loopback IP and port') from error
    if (parsed.scheme != 'http' or not address.is_loopback or port is None
            or not 1 <= port <= 65535 or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('proxy must be credential-free HTTP at an explicit loopback IP and port')
    hosts = value['destination_hosts']
    if (not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) for h in hosts)
            or len(set(hosts)) != len(hosts) or not set(hosts) <= SEC_HOSTS):
        raise ValueError('proxy destination hosts must be explicit SEC hostnames')
    return {'mode': value['mode'], 'proxy_url': value['proxy_url'], 'destination_hosts': sorted(hosts)}


class _ExplicitProxy(urllib.request.ProxyHandler):
    """Honor the caller's fixed proxy even when ambient NO_PROXY matches SEC."""
    def proxy_open(self, req, proxy, type):
        req.set_proxy(urllib.parse.urlsplit(proxy).netloc, 'http')
        return None


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.rows, self.dates = [], [], []
        self.active, self.row, self.text = None, None, []
        self.section, self.heading = '', None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('h1', 'h2', 'h3'):
            self.heading = []
        if tag == 'tr':
            self.row = {'text': [], 'links': []}
        if tag == 'a' and attrs.get('href'):
            self.active = {'href': attrs['href'], 'text': '', 'section': self.section}
        if tag == 'link' and attrs.get('href') and attrs.get('type') in ('application/rss+xml', 'application/atom+xml'):
            self.links.append({'href': attrs['href'], 'text': 'feed'})
        if tag == 'meta' and attrs.get('property', attrs.get('name', '')).lower() in ('article:published_time', 'date', 'datepublished'):
            self.dates.append(attrs.get('content', '')[:10])
        if tag == 'time' and attrs.get('datetime'):
            self.dates.append(attrs['datetime'][:10])

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.active is not None:
            self.active['text'] += data
        if self.row is not None:
            self.row['text'].append(data)

    def handle_endtag(self, tag):
        if tag in ('h1', 'h2', 'h3') and self.heading is not None:
            self.section = ' '.join(''.join(self.heading).split())
            self.heading = None
        if tag == 'a' and self.active is not None:
            self.links.append(self.active)
            if self.row is not None:
                self.row['links'].append(self.active)
            self.active = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def _mime(raw):
    if raw.startswith(b'%PDF-'):
        return 'application/pdf'
    lead = raw[:65536].decode('utf-8-sig', errors='replace').lstrip()
    if lead.startswith(('{', '[')):
        return 'application/json'

    class RootTag(HTMLParser):
        root = None

        def handle_starttag(self, tag, attrs):
            if self.root is None:
                self.root = (tag, dict(attrs))

    parser = RootTag()
    parser.feed(lead)
    tag, attrs = parser.root or ('', {})
    prefix, _, local = tag.rpartition(':')
    if tag == 'html' or (local == 'html' and attrs.get('xmlns:' + prefix) == 'http://www.w3.org/1999/xhtml'):
        return 'text/html'
    if lead.lower().startswith('<?xml') or tag in ('rss', 'feed') or attrs.get('xmlns') or prefix:
        return 'application/xml'
    return 'text/html' if '<' in lead else 'application/octet-stream'


def _write_new(path, raw):
    try:
        atomic_write_new(path, raw)
    except ValueError as error:
        raise AcquisitionError(str(error)) from error


def _filing_selection(config, as_of):
    """Validate caller-selected filing scope without filesystem/network access."""
    selection = config.get('filing_selection')
    if not isinstance(selection, dict):
        raise ValueError('filing_selection must be an explicit object')
    mode = selection.get('mode')
    target_period = None
    period_range = None
    # The two existing explicitly named modes retain their 10-K semantics.
    annual_form = '10-K'
    if mode == 'filing_period':
        if (set(selection) != {'mode', 'form_type', 'report_period_end'}
                or selection['form_type'] not in ('10-K', '20-F', '10-Q')):
            raise ValueError('filing_period requires form_type 10-K, 20-F or 10-Q and explicit report_period_end')
        annual_form = selection['form_type']
    if mode in ('annual_filing_period', 'annual_filings_range'):
        dates = {'report_period_end'} if mode == 'annual_filing_period' else {'report_period_end_from', 'report_period_end_to'}
        if set(selection) != {'mode', 'annual_form'} | dates or selection['annual_form'] not in ('10-K', '20-F'):
            raise ValueError(f'{mode} requires annual_form 10-K or 20-F and explicit report period dates')
        annual_form = selection['annual_form']
    if mode == 'annual_filings_range':
        start = _day(selection['report_period_end_from'], 'report_period_end_from')
        end = _day(selection['report_period_end_to'], 'report_period_end_to')
        if start > end or end > as_of:
            raise ValueError('annual_filings_range requires report_period_end_from <= report_period_end_to <= as_of')
        period_range = (start, end)
    elif (mode == 'annual_report_period' and set(selection) == {'mode', 'report_period_end'}) or mode in ('annual_filing_period', 'filing_period'):
        target_period = _day(selection['report_period_end'], 'report_period_end')
        if target_period > as_of:
            raise ValueError('report_period_end cannot exceed as_of')
    elif mode != 'latest_10k_and_subsequent_filings' or set(selection) != {'mode'}:
        raise ValueError('unsupported or incomplete filing_selection')
    return selection, mode, target_period, annual_form, period_range


def _configuration(config):
    if not isinstance(config, dict):
        raise ValueError('explicit source configuration required')
    _transport(config)
    symbol = config.get('symbol')
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-]{0,14}', symbol):
        raise ValueError('explicit valid symbol required')
    if 'cik' in config:
        cik = config['cik']
        if not isinstance(cik, str) or not re.fullmatch(r'[0-9]{10}', cik) or int(cik) == 0:
            raise ValueError('cik must be an explicit nonzero 10-digit SEC identifier')
    market = config.get('market')
    if market not in ('US', 'NASDAQ', 'NYSE', 'NYSEAMERICAN', 'CBOE'):
        raise ValueError('unsupported or missing market; only US SEC issuer markets supported')
    as_of = _day(config.get('as_of'), 'as_of')
    if as_of > datetime.now(timezone.utc).date():
        raise ValueError('as_of cannot be in the future')
    _filing_selection(config, as_of)
    _annual_package(config)
    ua = config.get('sec_user_agent')
    if not isinstance(ua, str) or not ua.strip() or '\n' in ua or '\r' in ua:
        raise ValueError('explicit sec_user_agent required')
    if config.get('document_validation') not in (None, 'sec_inline_identity_v1'):
        raise ValueError('unsupported document_validation')
    if config.get('download_policy', 'revalidate') not in ('revalidate', 'reuse_verified'):
        raise ValueError('unsupported download_policy')
    if config.get('download_policy') == 'reuse_verified' and config.get('document_validation') != 'sec_inline_identity_v1':
        raise ValueError('reuse_verified requires sec_inline_identity_v1 validation')
    if config.get('document_validation') == 'sec_inline_identity_v1' and not re.search(r'\S+@\S+\.\S+', ua):
        raise ValueError('SEC automatic access requires an application name and contact email in sec_user_agent')
    policy = config.get('source_policy')
    if not isinstance(policy, dict) or not isinstance(policy.get('official'), list) or not isinstance(policy.get('third_party'), list):
        raise ValueError('source_policy requires official and third_party source lists')
    entries = []
    for group in ('official', 'third_party'):
        for source in policy[group]:
            if not isinstance(source, dict) or source.get('kind') not in ('ir', 'blog', 'events'):
                raise ValueError('source kind must be ir, blog or events')
            if group == 'third_party' and source.get('approved') is not True:
                raise ValueError('third-party source is not approved')
            hosts = source.get('allowed_hosts')
            if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) or not h.strip() for h in hosts):
                raise ValueError('explicit allowed_hosts required for each source')
            allowed = {h.lower() for h in hosts}
            url = _url(source.get('url', ''), allowed)
            entries.append({**source, 'url': url, 'allowed_hosts': sorted(allowed), 'policy_group': group})
    window_config = policy.get('updates_window')
    updates_window = None
    if entries or 'updates_window' in policy:
        if not isinstance(window_config, dict) or set(window_config) != {'trailing_calendar_days'}:
            raise ValueError('explicit updates_window with trailing_calendar_days required for update sources')
        days = window_config['trailing_calendar_days']
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise ValueError('trailing_calendar_days must be a positive integer')
        try:
            start = as_of - timedelta(days=days - 1)
        except (OverflowError, ValueError) as error:
            raise ValueError('updates_window exceeds supported calendar dates') from error
        updates_window = {'start': start.isoformat(), 'end': as_of.isoformat(),
                          'calendar_days': days, 'bounds': 'inclusive'}
    supplied = config.get('limits')
    if not isinstance(supplied, dict) or set(supplied) - DEFAULT_LIMITS.keys():
        raise ValueError('limits must be an explicit object with supported resource keys')
    limits = {**DEFAULT_LIMITS, **supplied}
    for key, value in limits.items():
        integer = key not in ('timeout_seconds', 'backoff_seconds', 'min_request_interval_seconds')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (integer and not isinstance(value, int)):
            raise ValueError(f'invalid resource limit: {key}')
        minimum = 0 if key in ('retries', 'backoff_seconds', 'min_request_interval_seconds') else 1
        if not minimum <= value <= MAX_LIMITS[key]:
            raise ValueError(f'invalid resource limit: {key}')
    return symbol.upper(), market, as_of, ua.strip(), entries, limits, updates_window


def _annual_package(config):
    """Explicit directory adapters; no issuer-dependent URL or label defaults."""
    package = config.get('annual_package')
    if package is None:
        return None
    if (not isinstance(package, dict) or set(package) != {'version', 'report_year', 'directories', 'required_roles'}
            or package['version'] != 'annual-financial-package-v1'
            or type(package['report_year']) is not int or not 1900 <= package['report_year'] <= 9999
            or not isinstance(package['directories'], list) or not package['directories']
            or not isinstance(package['required_roles'], list) or not package['required_roles']
            or any(not isinstance(r, str) or not r for r in package['required_roles'])):
        raise ValueError('invalid explicit annual_package')
    selection = config['filing_selection']
    if selection.get('mode') != 'annual_filing_period':
        raise ValueError('annual_package requires one explicit annual filing period')
    for entry in package['directories']:
        if (not isinstance(entry, dict) or set(entry) != {'url', 'allowed_hosts', 'selectors'}
                or not isinstance(entry['allowed_hosts'], list) or not entry['allowed_hosts']
                or any(not isinstance(h, str) or not h for h in entry['allowed_hosts'])
                or not isinstance(entry['selectors'], list) or not entry['selectors']):
            raise ValueError('invalid annual directory adapter')
        _url(entry['url'], set(entry['allowed_hosts']))
        for selector in entry['selectors']:
            if (not isinstance(selector, dict) or set(selector) != {'role', 'section', 'text_pattern', 'url_pattern'}
                    or not isinstance(selector['role'], str) or not selector['role']
                    or selector['section'] is not None and not isinstance(selector['section'], str)):
                raise ValueError('invalid annual directory selector')
            for key in ('text_pattern', 'url_pattern'):
                value = selector[key]
                if not isinstance(value, str) or '{year}' not in value:
                    raise ValueError('annual selectors require explicit year-bound patterns')
                try:
                    re.compile(value.replace('{year}', str(package['report_year'])))
                except re.error as error:
                    raise ValueError('invalid annual selector pattern') from error
    return package


def prepare_sources(config: dict, workspace: Path, *, fetch=None, should_stop=None, clock=None,
                    prior_repeat_verification=None, blocked_sources=None, _session_only=False,
                    request_guard=None, remaining_seconds=None) -> dict:
    """Fetch and freeze a bounded source run. Inject fetch(url, headers=..., timeout=...) -> bytes.

    Filing selection is required. latest_10k_and_subsequent_filings selects the
    latest 10-K filed by as_of, then subsequent 10-Q/8-K and their amendments.
    Legacy annual_report_period selects matching SEC reportDate 10-K/10-K/A.
    annual_filing_period additionally requires annual_form (10-K or 20-F),
    selecting that form and its amendments, including archived submissions.
    annual_filings_range selects original annuals and their amendments within
    explicit inclusive report-period-end bounds. An explicit cik bypasses the
    ticker directory; SEC submissions must still match cik, symbol and market.
    filing_period requires form_type (10-K, 20-F or 10-Q) and report_period_end;
    only that period's original and amendments available at as_of are selected.
    An amendment cannot substitute for a missing original. Legacy annual modes
    retain their original selection and scope fields.
    should_stop cooperatively cancels before requests, after responses and
    before freezing; cancelled runs retain prior receipts and originals.
    Official pages with unknown dates are retained but not
    eligible as historical evidence. Approval is an explicit caller policy.

    Retry-After deadlines persist in this workspace and defer new requests until
    eligible. A corrupt historical object is preserved; a separate verified
    recovery copy can be used while the run retains an explicit integrity gap.
    ``clock`` may supply an aware datetime for deterministic offline recovery tests.
    """
    symbol, market, as_of, ua, entries, limits, updates_window = _configuration(config)
    if request_guard is not None and not callable(request_guard):
        raise ValueError('request_guard must be callable')
    proxy_transport = _transport(config)
    selection, mode, target_period, annual_form, period_range = _filing_selection(config, as_of)
    requested_cik = config.get('cik')
    if blocked_sources is not None and (not isinstance(blocked_sources, dict)
            or any(not isinstance(url, str) or code not in (401, 403, 404, 410)
                   for url, code in blocked_sources.items())):
        raise ValueError('blocked sources require explicit URL and permanent HTTP status')
    if prior_repeat_verification is not None:
        prior_scope = prior_repeat_verification
        if (not isinstance(prior_scope, dict) or prior_scope.get('cik') != requested_cik
                or prior_scope.get('report_period_end') != (target_period.isoformat() if target_period else None)
                or prior_scope.get('as_of') != as_of.isoformat()
                or not re.fullmatch(r'[a-f0-9]{64}', prior_scope.get('verification_sha256', ''))
                or not isinstance(prior_scope.get('items'), dict)):
            raise ValueError('prior repeat verification must match explicit company, period and cutoff')
    target_start = period_range[0] if period_range else target_period
    if should_stop is not None and not callable(should_stop):
        raise ValueError('should_stop must be callable')
    if clock is not None and not callable(clock):
        raise ValueError('clock must be callable')

    def now():
        value = (clock or _utc_now)()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('clock must return a timezone-aware datetime')
        return value.astimezone(timezone.utc)

    started_at = now()
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ('sources', 'source-runs', 'request-cooldowns'):
        if (workspace / name).is_symlink():
            raise AcquisitionError('workspace storage symlink forbidden')
    run_id = started_at.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:12]
    report = {'schema_version': VERSION, 'run_id': run_id, 'company': None,
              'scope': {'symbol': symbol, 'market': market, 'as_of': as_of.isoformat(),
                        'source_policy': config['source_policy'], 'limits': limits,
                        'updates_window': updates_window,
                        'selection': mode, 'filing_selection': dict(selection),
                        'identity_resolution': 'explicit_cik' if requested_cik else 'ticker_directory',
                        'requested_cik': requested_cik,
                        'sec_contact_origin': config.get('sec_contact_origin', 'caller_configuration'),
                        'document_validation': config.get('document_validation', 'legacy_transport_only'),
                        'download_policy': config.get('download_policy', 'revalidate'),
                        'transport': proxy_transport or {'mode': 'public_dns_http'},
                        'annual_form': annual_form, 'automatic_adoption': False},
              'documents': [], 'selected_filings': [], 'selected_assets': [], 'gaps': [], 'discovery': [],
              'requests': 0, 'bytes_received': 0, 'model_calls': 0,
              'storage_integrity': {'status': 'referenced_objects_only', 'findings': []},
              'filing_catalog': {'items': [], 'discovery_complete': False,
                                 'selection_discovery_complete': False, 'gaps': []},
              'retrieved_at': started_at.isoformat()}
    if target_period is not None:
        report['scope']['report_period_end'] = target_period.isoformat()
    if mode == 'filing_period':
        report['scope'].pop('annual_form')
        report['scope']['form_type'] = annual_form
    if period_range:
        report['scope'].update(report_period_end_from=period_range[0].isoformat(),
                               report_period_end_to=period_range[1].isoformat())
    if config.get('annual_package'):
        report['scope']['annual_package'] = config['annual_package']
    if prior_repeat_verification:
        report['scope']['prior_repeat_verification_sha256'] = prior_repeat_verification['verification_sha256']
    cache, seen, previous, verified_previous, transport, frozen_paths = {}, set(), {}, {}, {}, {}
    prior_candidates = []
    previous_rank = {}

    def remember_version(doc, prior_cik):
        if requested_cik and prior_cik != requested_cik:
            return
        url = doc['source_url']
        rank = doc.get('verified_at') or ''
        if url not in previous_rank or rank > previous_rank[url]:
            previous[url] = doc['content_sha256']
            previous_rank[url] = rank

    last_http_start = 0.0

    def remember(doc):
        existing = verified_previous.get(doc['source_url'])
        # Run IDs have random suffixes, so lexical directory order is not recency.
        rank = lambda d: (d.get('verified_at') or '', len(d.get('storage_recovery') or []))
        if existing is None or rank(doc) >= rank(existing):
            verified_previous[doc['source_url']] = doc

    for prior in sorted((workspace / 'source-runs').glob('*/manifest.json')):
        if not prior.resolve().is_relative_to(workspace) or prior.is_symlink():
            continue
        try:
            old = json.loads(prior.read_text())
            if old.get('scope', {}).get('symbol') == symbol:
                prior_cik = (old.get('company') or {}).get('cik')
                for doc in old.get('documents', []):
                    prior_candidates.append((prior_cik, doc))
                    remember_version(doc, prior_cik)
        except (OSError, ValueError, KeyError):
            continue
    # Each completed filing has its own atomic receipt, so a process crash before
    # the final manifest does not lose an already verified original.
    for receipt in sorted((workspace / 'source-runs').glob('*/receipts/*.json')):
        if receipt.is_symlink() or not receipt.resolve().is_relative_to(workspace):
            continue
        try:
            prior = json.loads(receipt.read_text())
            if prior['company']['symbol'] == symbol:
                doc = prior['document']
                prior_candidates.append((prior['company']['cik'], doc))
                remember_version(doc, prior['company']['cik'])
        except (OSError, ValueError, KeyError, TypeError):
            continue

    def gap(reason, url=None, **details):
        report['gaps'].append({'reason': reason, **({'source_url': url} if url else {}), **details})

    def check_stop():
        if should_stop is not None and should_stop():
            raise AcquisitionCancelled('acquisition_cancelled')

    def request_timeout():
        check_stop()
        if remaining_seconds is None:
            return limits['timeout_seconds']
        remaining = remaining_seconds()
        if remaining <= 0:
            raise AcquisitionCancelled('acquisition_deadline_exhausted')
        return min(limits['timeout_seconds'],remaining)

    def damaged(path, expected_sha, observed_sha, recovery_path=None):
        relative = path.relative_to(workspace).as_posix()
        findings = report['storage_integrity']['findings']
        finding = next((item for item in findings if item['damaged_path'] == relative
                        and item['observed_sha256'] == observed_sha), None)
        if finding is None:
            finding = {'damaged_path': relative, 'expected_sha256': expected_sha,
                       'observed_sha256': observed_sha, 'historical_bytes_preserved': True}
            findings.append(finding)
            gap('historical_object_corruption', path=relative, expected_sha256=expected_sha,
                observed_sha256=observed_sha)
        if recovery_path:
            finding['recovery_path'] = recovery_path
        report['storage_integrity']['status'] = 'damaged_history_preserved'
        return finding

    def freeze(raw):
        check_stop()
        sha = _sha(raw)
        if sha in frozen_paths:
            return frozen_paths[sha]
        path = workspace / 'sources' / 'objects' / (sha + '.bin')
        if not path.resolve().is_relative_to(workspace):
            raise AcquisitionError('artifact path outside workspace')
        try:
            _write_new(path, raw)
        except AcquisitionError as error:
            if str(error) != 'immutable_artifact_conflict' or path.is_symlink() or not path.is_file():
                raise
            with path.open('rb') as stream:
                observed = hashlib.file_digest(stream, 'sha256').hexdigest()
            recovered = workspace/'sources/objects/recovered'/run_id/(sha+'.bin')
            _write_new(recovered, raw)
            damaged(path, sha, observed, recovered.relative_to(workspace).as_posix())
            path = recovered
        frozen_paths[sha] = path.relative_to(workspace).as_posix()
        return frozen_paths[sha]

    def cooldown(url):
        """Read append-only URL-bound deadlines afresh before each HTTP request."""
        directory = workspace/'request-cooldowns'/_sha(url.encode())
        if directory.is_symlink() or not directory.resolve().is_relative_to(workspace/'request-cooldowns'):
            raise AcquisitionError('unsafe_request_cooldown_path')
        latest = None
        for path in directory.glob('*.json'):
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('unsafe cooldown record')
                entry = json.loads(path.read_text())
                if entry['schema_version'] != 'request-cooldown-v1' or entry['source_url'] != url:
                    raise ValueError('cooldown identity mismatch')
                if type(entry['http_status']) is not int or not 400 <= entry['http_status'] <= 599:
                    raise ValueError('invalid cooldown HTTP status')
                deadline = datetime.fromisoformat(entry['next_retry_at'])
                if deadline.tzinfo is None or deadline.utcoffset() is None:
                    raise ValueError('timezone required')
                if latest is None or deadline > latest[0]:
                    latest = deadline, entry
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise AcquisitionError('invalid_request_cooldown_record') from error
        return latest if latest and latest[0] > now() else None

    def enforce_cooldown(url):
        active = cooldown(url)
        if active:
            deadline, entry = active
            report['discovery'].append({'source_url': url, 'status': 'deferred',
                'reason': 'request_cooldown_active', 'next_retry_at': deadline.isoformat(),
                'http_status': entry['http_status'], 'retry_deferred': True})
            raise AcquisitionDeferred(deadline.isoformat(), entry['http_status'])

    def save_cooldown(url, error, failed):
        header = error.headers.get('Retry-After') if isinstance(error, urllib.error.HTTPError) and error.headers else None
        if not header:
            return 0.0
        observed_at = now()
        try:
            deadline = (observed_at + timedelta(seconds=int(header)) if re.fullmatch(r'[0-9]+', header)
                        else parsedate_to_datetime(header))
            if deadline.tzinfo is None or deadline.utcoffset() is None:
                raise ValueError('timezone required')
            deadline = deadline.astimezone(timezone.utc)
            delay = max(0.0, (deadline-observed_at).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0.0
        failed.update(retry_after_seconds=delay, next_retry_at=deadline.isoformat())
        entry = {'schema_version': 'request-cooldown-v1', 'source_url': url,
                 'observed_at': observed_at.isoformat(), 'next_retry_at': deadline.isoformat(),
                 'http_status': error.code, 'run_id': run_id}
        path = workspace/'request-cooldowns'/_sha(url.encode())/(uuid.uuid4().hex+'.json')
        _write_new(path, (json.dumps(entry, sort_keys=True)+'\n').encode())
        return delay

    def throttle():
        nonlocal last_http_start
        # A per-run rate below the SEC published ten-requests/second ceiling.
        remaining = limits['min_request_interval_seconds'] - (time.monotonic() - last_http_start)
        if remaining > 0:
            time.sleep(remaining)
        last_http_start = time.monotonic()

    def redirect(previous_url, target):
        check_stop()
        if request_guard is not None:
            request_guard(target)
        enforce_cooldown(target)
        if report['requests'] >= limits['max_requests']:
            raise LimitReached('request_limit')
        report['requests'] += 1
        throttle()
        check_stop()
        report['discovery'].append({'source_url': previous_url, 'status': 'redirect', 'target_url': target})

    def request(url, allowed):
        check_stop()
        url = _url(url, allowed)
        if request_guard is not None:
            request_guard(url)
        if url in (blocked_sources or {}):
            report['discovery'].append({'source_url': url, 'status': 'deferred',
                'reason': 'permanent_failure_in_current_batch', 'http_status': blocked_sources[url]})
            raise AcquisitionError('permanent_failure_in_current_batch')
        if url in cache:
            return cache[url]
        for attempt in range(limits['retries'] + 1):
            check_stop()
            enforce_cooldown(url)
            if report['requests'] >= limits['max_requests']:
                raise LimitReached('request_limit')
            if report['bytes_received'] >= limits['max_total_bytes']:
                raise LimitReached('total_byte_limit')
            report['requests'] += 1
            info = {}
            raw = None
            requested_at = now().isoformat()
            try:
                if fetch is None:
                    use_proxy = proxy_transport is not None and urllib.parse.urlsplit(url).hostname in proxy_transport['destination_hosts']
                    request_allowed = set(allowed) & set(proxy_transport['destination_hosts']) if use_proxy else allowed
                    _url(url, request_allowed, resolve=not use_proxy)
                    throttle()
                    check_stop()
                    handlers = [_Redirect(request_allowed, redirect, resolve=not use_proxy)]
                    if _session_only:
                        from .official_discovery import PublicHTTPSHandler
                        handlers.extend([urllib.request.ProxyHandler({}), PublicHTTPSHandler()])
                    if use_proxy:
                        handlers.insert(0, _ExplicitProxy({'https': proxy_transport['proxy_url']}))
                    opener = urllib.request.build_opener(*handlers)
                    with opener.open(urllib.request.Request(url, headers={'User-Agent': ua, 'Accept-Encoding': 'identity'}),
                                     timeout=request_timeout()) as response:
                        info = {'http_status': response.status, 'final_url': response.url,
                                'content_type': response.headers.get('Content-Type'),
                                'content_length': response.headers.get('Content-Length'), 'transport': 'http'}
                        info['cache_headers'] = {k: response.headers.get(k) for k in
                            ('Date', 'ETag', 'Last-Modified', 'Age', 'Cache-Control') if response.headers.get(k) is not None}
                        _url(response.url, request_allowed)
                        if request_guard is not None:
                            request_guard(response.url)
                        if use_proxy:
                            info.update(transport='trusted_local_http_proxy', proxy_url=proxy_transport['proxy_url'])
                        if response.status != 200:
                            raise AcquisitionError('unexpected_http_status')
                        cap = min(limits['max_bytes_per_document'], limits['max_total_bytes'] - report['bytes_received'])
                        raw = response.read(cap + 1)
                        report['bytes_received'] += len(raw)
                        if info['content_length'] is not None and int(info['content_length']) != len(raw):
                            raise AcquisitionError('content_length_mismatch')
                else:
                    raw = fetch(url, headers={'User-Agent': ua, 'Accept-Encoding': 'identity'}, timeout=request_timeout())
                    info = {'transport': 'injected_fetch', 'final_url': url}
                    if isinstance(raw, bytes):
                        report['bytes_received'] += len(raw)
                check_stop()
                if not isinstance(raw, bytes) or not raw:
                    raise AcquisitionError('empty_or_nonbytes_response')
                if len(raw) > limits['max_bytes_per_document']:
                    raise AcquisitionError('document_size_limit')
                if report['bytes_received'] > limits['max_total_bytes']:
                    raise LimitReached('total_byte_limit')
                cache[url] = raw
                transport[url] = {**info, 'bytes_received': len(raw), 'retrieved_at': now().isoformat()}
                report['discovery'].append({'source_url': url, 'status': 'fetched',
                    'content_sha256': _sha(raw), 'path': freeze(raw), 'attempt': attempt + 1,
                    'requested_at': requested_at, **transport[url]})
                return raw
            except Exception as error:
                # urllib raises before entering the response context for 4xx/5xx.
                # Keep a bounded error response too; a status alone cannot locate
                # whether the denial came from the origin, cache or transport.
                if isinstance(error, urllib.error.HTTPError):
                    info.update(http_status=error.code, final_url=error.url,
                                transport='http_error', response_headers={k: v for k, v in
                                    (error.headers or {}).items() if k.lower() in
                                    ('date', 'server', 'via', 'content-type', 'content-length',
                                     'retry-after', 'cf-ray', 'cf-cache-status', 'cache-control',
                                     'etag', 'last-modified', 'x-cache', 'x-error')})
                    try:
                        cap = min(65536, limits['max_bytes_per_document'],
                                  max(0, limits['max_total_bytes'] - report['bytes_received']))
                        raw = error.read(cap) if cap and error.fp is not None else None
                        if isinstance(raw, bytes):
                            report['bytes_received'] += len(raw)
                            info['error_body_limit'] = cap
                            info['error_body_may_be_truncated'] = len(raw) == cap
                    except Exception as read_error:
                        info['error_body_read_error'] = type(read_error).__name__
                    finally:
                        error.close()
                failed = {'source_url': url, 'status': 'failed', 'attempt': attempt + 1,
                    **info,
                    'error_type': type(error).__name__, 'http_status': getattr(error, 'code', info.get('http_status')),
                    'requested_at': requested_at, 'retrieved_at': now().isoformat(),
                    'reason': str(error) if isinstance(error, AcquisitionError) else type(error).__name__}
                if isinstance(raw, bytes) and raw and not isinstance(error, AcquisitionCancelled):
                    partial = workspace/'source-runs'/run_id/'partial-responses'/(_sha(url.encode())+'-'+str(attempt+1)+'.bin')
                    _write_new(partial, raw)
                    failed.update(bytes_received=len(raw), partial_path=partial.relative_to(workspace).as_posix(),
                                  partial_sha256=_sha(raw), eligible_original=False)
                report['discovery'].append(failed)
                retry_after_delay = save_cooldown(url, error, failed)
                # Access denial is not transient. Do not repeatedly retry 403 or
                # permanent 4xx; rate limits and server/network errors are bounded.
                permanent_http = isinstance(error, urllib.error.HTTPError) and error.code < 500 and error.code not in (408, 429)
                if isinstance(error, AcquisitionError) or permanent_http or attempt == limits['retries']:
                    if retry_after_delay > 0:
                        failed['retry_deferred'] = True
                    raise
                delay = max(limits['backoff_seconds'] * (2 ** attempt), retry_after_delay)
                if delay > 60:
                    failed['retry_deferred'] = True
                    raise  # A later invocation may resume; never retry earlier than requested.
                time.sleep(delay)
        raise AcquisitionError('request_failed')

    def update_outside_window(published_at, url):
        if not published_at:
            return False
        day = _day(published_at, 'published_at').isoformat()
        if day < updates_window['start'] or day > updates_window['end']:
            gap('before_updates_window' if day < updates_window['start'] else 'after_as_of',
                url, published_at=day, updates_window=updates_window)
            return True
        return False

    def document(url, allowed, *, form, filed_at=None, period_end=None, role, published_at=None):
        url = _url(url, allowed)
        if url in seen:
            return next(row for row in report['documents'] if row['source_url'] == url)
        if len(report['documents']) >= limits['max_documents']:
            raise LimitReached('document_limit')
        raw, reused, validation = None, None, None
        repeat_reused = False
        strict = role == 'filing' and config.get('document_validation') == 'sec_inline_identity_v1'
        prior = verified_previous.get(url)
        repeated = (prior_repeat_verification or {}).get('items', {}).get(url)
        if repeated and repeated['form'] == form and repeated['period_end'] == period_end:
            old_path = workspace/repeated['path']
            if old_path.is_symlink() or not old_path.resolve().is_relative_to(workspace/'sources/objects'):
                raise AcquisitionError('invalid_prior_repeat_path')
            old_raw = old_path.read_bytes()
            if _sha(old_raw) != repeated['content_sha256']:
                gap('prior_repeat_object_hash_mismatch', url)
            elif len(old_raw) <= limits['max_bytes_per_document']:
                if strict:
                    validation = validate_sec_filing(old_raw, report['company']['cik'], form, period_end)
                raw, reused, repeat_reused = old_raw, repeated, True
                cache[url] = raw
                transport[url] = {'transport': 'prior_remote_verification',
                                  'verification_sha256': prior_repeat_verification['verification_sha256']}
                report['discovery'].append({'source_url': url, 'status': 'reused_prior_repeat_verification',
                    'content_sha256': repeated['content_sha256'], 'path': repeated['path'], **transport[url]})
        if raw is None and strict and config.get('download_policy') == 'reuse_verified' and prior:
            try:
                old_path = workspace / prior['path']
                if old_path.is_symlink() or not old_path.resolve().is_relative_to(workspace / 'sources' / 'objects'):
                    raise ValueError('invalid_cached_path')
                old_raw = old_path.read_bytes()
                observed_sha = _sha(old_raw)
                if observed_sha != prior['content_sha256']:
                    damaged(old_path, prior['content_sha256'], observed_sha)
                    raise ValueError('cached_content_integrity_mismatch')
                if len(old_raw) > limits['max_bytes_per_document']:
                    raise ValueError('cached_document_size_limit')
                validation = validate_sec_filing(old_raw, expected_cik=report['company']['cik'],
                    expected_form=form, expected_period_end=period_end)
                raw, reused = old_raw, prior
                report['discovery'].append({'source_url': url, 'status': 'reused_verified',
                    'content_sha256': prior['content_sha256'], 'path': prior['path']})
            except (OSError, ValueError, KeyError, TypeError) as error:
                report['discovery'].append({'source_url': url, 'status': 'reuse_rejected', 'error_type': type(error).__name__})
        if raw is None:
            raw = request(url, allowed)
        if strict and validation is None:
            try:
                validation = validate_sec_filing(raw, expected_cik=report['company']['cik'],
                    expected_form=form, expected_period_end=period_end)
            except ValueError as error:
                raise AcquisitionError('filing_content_invalid: ' + str(error)) from error
        if config.get('annual_package') and role != 'filing':
            suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
            expected = {'pdf': 'application/pdf', 'htm': 'text/html', 'html': 'text/html',
                        'xml': 'application/xml', 'xsd': 'application/xml'}.get(suffix.lstrip('.'))
            if expected and _mime(raw) != expected:
                raise AcquisitionError('asset_content_type_mismatch')
        if published_at is None and role not in ('filing', 'filing_attachment') and _mime(raw) == 'text/html':
            page = _Links(); page.feed(raw.decode('utf-8', errors='replace'))
            dates = set()
            for value in page.dates:
                try:
                    dates.add(_day(value, 'published_at').isoformat())
                except ValueError:
                    pass
            if len(dates) == 1:
                published_at = dates.pop()
        if form in ('OFFICIAL_UPDATE', 'THIRD_PARTY_UPDATE') and update_outside_window(published_at, url):
            return
        known_date = filed_at or published_at
        if known_date and _day(known_date, 'document_date') > as_of:
            gap('after_as_of', url)
            return
        sha = _sha(raw)
        path = reused['path'] if reused else freeze(raw)
        # Recovery provenance survives subsequent reuse. Only issuer/period-
        # validated bytes reach this point; no historical path supplies content.
        if strict and prior and prior['content_sha256'] == sha:
            for finding in prior.get('storage_recovery', []):
                old_path = workspace / finding['damaged_path']
                if (old_path.is_symlink() or not old_path.resolve().is_relative_to(workspace/'sources/objects')
                        or finding['expected_sha256'] != sha
                        or not re.fullmatch(r'[a-f0-9]{64}', finding['observed_sha256'])):
                    raise AcquisitionError('invalid_storage_recovery_record')
                damaged(old_path, sha, finding['observed_sha256'], path)
        recoveries = []
        for finding in report['storage_integrity']['findings']:
            if finding['expected_sha256'] == sha:
                finding['recovery_path'] = path
                recoveries.append(dict(finding))
        row = {'source_id': 'source-' + _sha((url + ':' + sha).encode())[:24], 'source_url': url,
               'form': form, 'filed_at': filed_at, 'period_end': period_end, 'published_at': published_at,
               'content_sha256': sha, 'path': path, 'mime_type': _mime(raw),
               'status': 'frozen' if known_date else 'frozen_date_unverified', 'role': role,
               'as_of_eligible': bool(known_date), 'change': 'new' if url not in previous else 'unchanged' if previous[url] == sha else 'revised',
               'previous_content_sha256': previous.get(url)}
        report['documents'].append(row)
        seen.add(url)
        row['acquisition'] = 'reused_remote_verified' if repeat_reused else 'reused_verified' if reused else 'downloaded'
        row['validation'] = validation or {'version': 'legacy_transport_only', 'identity_verified': False}
        row['transport'] = transport.get(url) if repeat_reused else reused.get('transport') if reused else transport.get(url)
        row['verified_at'] = now().isoformat()
        if recoveries:
            row['storage_recovery'] = recoveries
        if strict:
            _write_new(workspace/'source-runs'/run_id/'receipts'/(row['source_id']+'.json'),
                (json.dumps({'company': report['company'], 'document': row}, ensure_ascii=False, indent=2)+'\n').encode())
        if not known_date:
            gap('publication_date_unverified', url)
        return row

    def package_asset(url, allowed, *, role, form, filed_at=None, period_end=None):
        task = {'source_url': url, 'role': role, 'status': 'not_attempted',
                'period_end': period_end, 'filed_at': filed_at}
        report['selected_assets'].append(task)
        _write_new(workspace/'source-runs'/run_id/'planned-assets'/(_sha((role+':'+url).encode())+'.json'),
                   (json.dumps(task, sort_keys=True)+'\n').encode())
        try:
            doc = document(url, allowed, role=role, form=form, filed_at=filed_at, period_end=period_end)
            task.update(status=doc['acquisition'], source_id=doc['source_id'],
                        content_sha256=doc['content_sha256'], path=doc['path'])
        except AcquisitionCancelled:
            raise
        except Exception as error:
            task.update(status='failed', error_type=type(error).__name__, http_status=getattr(error, 'code', None))
            gap('annual_asset_acquisition_failed', url, role=role, error_type=type(error).__name__,
                detail=str(error) if isinstance(error, AcquisitionError) else type(error).__name__)
        return task

    def rows(value):
        if not isinstance(value, dict) or not value or any(not isinstance(v, list) for v in value.values()):
            raise AcquisitionError('invalid_submission_rows')
        if len({len(v) for v in value.values()}) != 1:
            raise AcquisitionError('submission_column_length_mismatch')
        return [dict(zip(value, cells)) for cells in zip(*value.values())]

    def catalog(filings):
        items = {}
        for filing in filings:
            if filing.get('form') not in (annual_form, annual_form + '/A'):
                continue
            try:
                filed = _day(filing['filingDate'], 'filingDate')
                period = _day(filing.get('reportDate'), 'reportDate')
                if period > filed:
                    raise ValueError('reportDate after filingDate')
                if filed <= as_of:
                    value = {'form': filing['form'], 'report_period_end': period.isoformat() if period else None,
                             'filed_at': filed.isoformat(), 'accession': filing['accessionNumber']}
                    items[tuple(value.values())] = value
            except (ValueError, KeyError):
                diagnostic = {'reason': 'invalid_filing_metadata' if mode == 'filing_period' else 'invalid_annual_filing_metadata',
                              'accession': filing.get('accessionNumber')}
                if diagnostic not in report['filing_catalog']['gaps']:
                    report['filing_catalog']['gaps'].append(diagnostic)
        report['filing_catalog']['items'] = sorted(items.values(), key=lambda r: (r['filed_at'], r['accession']), reverse=True)

    def finalize():
        cancelled = any(g['reason'] == 'acquisition_cancelled' for g in report['gaps'])
        if should_stop is not None and should_stop():
            if not cancelled:
                gap('acquisition_cancelled')
            cancelled = True
        report['status'] = ('cancelled' if cancelled else 'identity_unresolved' if report['company'] is None
                            else 'completed_with_gaps' if report['gaps'] else 'completed')
        manifest = workspace / 'source-runs' / run_id / 'manifest.json'
        if not manifest.resolve().is_relative_to(workspace):
            raise AcquisitionError('run path outside workspace')
        report['manifest_path'] = manifest.relative_to(workspace).as_posix()
        _write_new(manifest, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
        return report

    if _session_only:
        return dict(report=report, request=request, document=document, freeze=freeze,
                    finish=finalize, gap=gap, check_stop=check_stop)

    try:
        if requested_cik:
            cik = int(requested_cik)
        else:
            ticker_data = json.loads(request(TICKERS, SEC_HOSTS))
            matches = [r for r in ticker_data.values() if str(r.get('ticker', '')).upper() == symbol]
            if len(matches) != 1:
                raise AcquisitionError('symbol_unknown_or_ambiguous')
            cik = int(matches[0]['cik_str'])
        if not 0 < cik < 10**10:
            raise AcquisitionError('invalid_cik')
        submission_url = f'https://data.sec.gov/submissions/CIK{cik:010d}.json'
        data = json.loads(request(submission_url, SEC_HOSTS))
        if int(data.get('cik', 0)) != cik or symbol not in [str(x).upper() for x in data.get('tickers', [])]:
            raise AcquisitionError('submission_company_identity_mismatch')
        exchanges = [str(x).upper() for x in data.get('exchanges', [])]
        if market != 'US' and market not in exchanges:
            raise AcquisitionError('submission_market_mismatch')
        report['company'] = {'company_id': f'sec-{cik:010d}', 'symbol': symbol,
                             'name': data['name'], 'cik': f'{cik:010d}', 'market': market}
        # Resolve and verify current issuer identity before trusting either
        # manifest or crash-recovery candidates. Ticker-selected runs can reuse
        # originals too, but a reused ticker must never inherit another issuer.
        for prior_cik, doc in prior_candidates:
            if prior_cik == report['company']['cik']:
                remember(doc)
        filings = rows(data['filings']['recent'])
        catalog(filings)
        older = data['filings'].get('files')
        if not isinstance(older, list):
            report['filing_catalog']['gaps'].append({'reason': 'submission_archive_catalog_missing_or_invalid'})
            gap('submission_archive_catalog_missing_or_invalid')
            older = []
        # Historical as_of may require an archived submission page. Always inspect
        # eligible archives under the shared request cap, not a fixed year cutoff.
        for archive in sorted(older, key=lambda a: a.get('filingTo', ''), reverse=True):
            if _day(archive['filingFrom'], 'filingFrom') > as_of:
                continue
            recent_annuals = [r['filingDate'] for r in filings if r.get('form') == annual_form
                              and r.get('filingDate', '') <= as_of.isoformat()]
            if target_start is not None and _day(archive['filingTo'], 'filingTo') < target_start:
                report['filing_catalog']['gaps'].append({'reason': 'archive_not_inspected', 'archive': archive['name'],
                                                        'outside_selection': True})
                continue
            if target_start is None and recent_annuals and _day(archive['filingTo'], 'filingTo').isoformat() < max(recent_annuals):
                report['filing_catalog']['gaps'].append({'reason': 'archive_not_inspected', 'archive': archive['name']})
                continue
            if _day(archive['filingFrom'], 'filingFrom') <= as_of:
                name = archive['name']
                if not re.fullmatch(r'[A-Za-z0-9_.-]+\.json', name):
                    raise AcquisitionError('invalid_archive_name')
                try:
                    filings += rows(json.loads(request('https://data.sec.gov/submissions/' + name, SEC_HOSTS)))
                    catalog(filings)
                except Exception as error:
                    if isinstance(error, AcquisitionCancelled):
                        raise
                    gap('submission_archive_unavailable', error_type=type(error).__name__)
                    report['filing_catalog']['gaps'].append({'reason': 'submission_archive_unavailable',
                        'archive': name, 'error_type': type(error).__name__,
                        'limit': str(error) if isinstance(error, LimitReached) else None})
                    break
        # Cross-check index identities before scope filtering: a contradictory
        # copy must not disappear merely because its date/form is outside scope.
        groups = {}
        for row in filings:
            groups.setdefault(row.get('accessionNumber'), []).append(row)
        filings = []
        for accession, group in groups.items():
            keys = ('form', 'filingDate', 'reportDate', 'primaryDocument')
            if len({tuple(row.get(key) for key in keys) for row in group}) != 1:
                diagnostic = {'reason': 'conflicting_filing_metadata', 'accession': accession}
                report['filing_catalog']['gaps'].append(diagnostic)
                gap(**diagnostic)
                continue
            filings.append(group[0])
        catalog(filings)
        report['filing_catalog']['discovery_complete'] = not report['filing_catalog']['gaps']
        report['filing_catalog']['selection_discovery_complete'] = not any(
            not entry.get('outside_selection') for entry in report['filing_catalog']['gaps'])
        if target_start is not None and not report['filing_catalog']['selection_discovery_complete']:
            gap('filing_catalog_incomplete_for_selection')
        eligible = []
        scoped_forms = ({annual_form, annual_form + '/A'} if target_start is not None else
                        {'10-K', '10-Q', '8-K', '10-K/A', '10-Q/A', '8-K/A'})
        for row in filings:
            # reportDate on a proxy statement can be a future meeting date.
            # Such forms are outside this filing task and are not annual gaps.
            if row.get('form') not in scoped_forms:
                continue
            try:
                filed = _day(row['filingDate'], 'filingDate')
                if row.get('reportDate'):
                    period = _day(row['reportDate'], 'reportDate')
                    if period > filed:
                        raise ValueError('reportDate after filingDate')
                if filed <= as_of:
                    eligible.append(row)
            except (KeyError, ValueError):
                gap('invalid_filing_date', accession=row.get('accessionNumber'))
        annuals = [r for r in eligible if r['form'] == annual_form]
        if period_range:
            first, last = (day.isoformat() for day in period_range)
            annuals = [r for r in annuals if first <= (r.get('reportDate') or '') <= last]
            annual_periods = {r['reportDate'] for r in annuals}
            selected = [r for r in eligible if r['form'] in (annual_form, annual_form + '/A')
                        and r.get('reportDate') in annual_periods]
            selected.sort(key=lambda r: (r['reportDate'], r['filingDate'], r['accessionNumber']))
            for period in sorted({r['reportDate'] for r in eligible if r['form'] == annual_form + '/A'
                                  and first <= (r.get('reportDate') or '') <= last} - annual_periods):
                gap('annual_original_not_found_for_amendment', annual_form=annual_form, report_period_end=period)
            if not annuals:
                gap('annual_filing_range_not_found', annual_form=annual_form,
                    report_period_end_from=first, report_period_end_to=last)
        elif target_period is not None:
            annuals = [r for r in annuals if r.get('reportDate') == target_period.isoformat()]
            selected = [r for r in eligible if r['form'] in (annual_form, annual_form + '/A')
                        and r.get('reportDate') == target_period.isoformat()] if annuals else []
            selected.sort(key=lambda r: (r['filingDate'], r['accessionNumber']))
            if not annuals:
                if mode == 'filing_period':
                    if any(r['form'] == annual_form + '/A' and r.get('reportDate') == target_period.isoformat()
                           for r in eligible):
                        gap('filing_original_not_found_for_amendment', form_type=annual_form,
                            report_period_end=target_period.isoformat())
                    gap('filing_report_period_not_found', form_type=annual_form,
                        report_period_end=target_period.isoformat())
                else:
                    gap('annual_report_period_not_found', annual_form=annual_form,
                        report_period_end=target_period.isoformat())
        elif not annuals:
            gap('no_10k_at_as_of')
            selected = []
        else:
            annual = max(annuals, key=lambda r: (r['filingDate'], r['accessionNumber']))
            selected = [annual] + [r for r in eligible if r is not annual and r['filingDate'] >= annual['filingDate']
                and r['form'] in ('10-Q', '8-K', '10-K/A', '10-Q/A', '8-K/A')]
            selected.sort(key=lambda r: (r['filingDate'], r['accessionNumber']), reverse=True)
            selected.remove(annual); selected.insert(0, annual)
        accessions = set()
        report['selected_filings'] = [
            {'accession': r['accessionNumber'], 'form': r['form'], 'filed_at': r['filingDate'],
             'period_end': r.get('reportDate'), 'primary_document': r['primaryDocument'], 'status': 'not_attempted'}
            for r in selected]
        if config.get('annual_package'):
            _write_new(workspace/'source-runs'/run_id/'selected-filings.json',
                       (json.dumps(report['selected_filings'], indent=2)+'\n').encode())
        for filing in selected:
            acc = filing['accessionNumber']
            if acc in accessions:
                continue
            accessions.add(acc)
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', acc):
                gap('invalid_accession', accession=acc); continue
            base = f'https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace("-", "")}/'
            primary = filing['primaryDocument']
            if not isinstance(primary, str) or '/' in primary or not primary or primary in ('.', '..'):
                gap('invalid_primary_document', accession=acc); continue
            url = base + urllib.parse.quote(primary)
            task = next(r for r in report['selected_filings'] if r['accession'] == acc)
            task['source_url'] = url
            try:
                original = document(url, SEC_HOSTS, form=filing['form'], filed_at=filing['filingDate'],
                                    period_end=filing.get('reportDate') or None, role='filing')
                task.update(status=original['acquisition'], source_id=original['source_id'],
                            content_sha256=original['content_sha256'], path=original['path'])
                if config.get('annual_package'):
                    index_url = base + acc + '-index.html'
                    index = package_asset(index_url, SEC_HOSTS, role='filing_index', form='FILING_INDEX',
                        filed_at=filing['filingDate'], period_end=filing.get('reportDate') or None)
                    if index['status'] == 'failed':
                        gap('annual_filing_assets_discovery_incomplete', index_url)
                    else:
                        listing = _Links(); listing.feed(cache[index_url].decode('utf-8', errors='replace'))
                        assets = {}
                        for row in listing.rows:
                            label = ' '.join(row['text'])
                            for link in row['links']:
                                candidate = urllib.parse.urljoin(index_url, link['href'])
                                # EDGAR ixviewer links wrap the actual archive URL.
                                if '/ixviewer/' in candidate or '/ix?doc=' in candidate:
                                    inner = urllib.parse.parse_qs(urllib.parse.urlsplit(candidate).query).get('doc', [])
                                    if inner:
                                        candidate = urllib.parse.urljoin('https://www.sec.gov', inner[0])
                                if candidate == url or not urllib.parse.urlsplit(candidate).path.startswith(urllib.parse.urlsplit(base).path):
                                    continue
                                suffix = Path(urllib.parse.urlsplit(candidate).path).suffix.lower()
                                if suffix in ('.xml', '.xsd'):
                                    assets[candidate] = ('filing_xbrl', 'XBRL')
                                elif re.search(r'\bEX-\d', label, re.I) and suffix in ('.htm', '.html', '.pdf'):
                                    assets[candidate] = ('filing_attachment', 'EXHIBIT')
                        _write_new(workspace/'source-runs'/run_id/'filing-assets'/(acc+'.json'),
                            (json.dumps([{'source_url': u, 'role': r, 'form': f} for u, (r, f) in assets.items()], indent=2)+'\n').encode())
                        if not assets:
                            gap('annual_filing_assets_not_discovered', index_url)
                        for candidate, (role, form) in list(assets.items())[:limits['max_discovery_links']]:
                            package_asset(candidate, SEC_HOSTS, role=role, form=form,
                                filed_at=filing['filingDate'], period_end=filing.get('reportDate') or None)
                        if len(assets) > limits['max_discovery_links']:
                            gap('annual_filing_asset_discovery_limit', index_url, expected=len(assets))
                if filing['form'] in ('8-K', '8-K/A'):
                    listing = _Links(); listing.feed(request(base + acc + '-index.html', SEC_HOSTS).decode('utf-8', errors='replace'))
                    attachments = [link for row in listing.rows if re.search(r'\bEX-\d', ' '.join(row['text']), re.I)
                                   for link in row['links']]
                    if not attachments:
                        gap('no_exhibit_links_discovered', url)
                    for link in attachments[:limits['max_discovery_links']]:
                        attachment = urllib.parse.urljoin(base, link['href'])
                        if not urllib.parse.urlsplit(attachment).path.startswith(urllib.parse.urlsplit(base).path):
                            gap('exhibit_outside_accession', attachment); continue
                        document(attachment, SEC_HOSTS, form='EXHIBIT', filed_at=filing['filingDate'],
                                 period_end=filing.get('reportDate') or None, role='filing_attachment')
                    if len(attachments) > limits['max_discovery_links']:
                        gap('exhibit_discovery_limit', url)
            except Exception as error:
                if isinstance(error, AcquisitionCancelled):
                    raise
                reason = str(error) if isinstance(error, AcquisitionError) else type(error).__name__
                deferred = (error.next_retry_at if isinstance(error, AcquisitionDeferred) else
                            next((event['next_retry_at'] for event in reversed(report['discovery'])
                                  if event.get('source_url') == url and event.get('retry_deferred')
                                  and event.get('next_retry_at')), None))
                task.update(status='deferred' if deferred else 'access_blocked' if getattr(error, 'code', None) == 403 else 'failed',
                            http_status=getattr(error, 'code', None), error_type=type(error).__name__, reason=reason)
                if deferred:
                    task['next_retry_at'] = deferred
                gap(str(error) if isinstance(error, LimitReached) else 'filing_acquisition_failed', url,
                    error_type=type(error).__name__, http_status=getattr(error, 'code', None), detail=reason)
                if isinstance(error, LimitReached):
                    break
        package = config.get('annual_package')
        if package:
            for number, entry in enumerate(package['directories']):
                allowed, directory = set(entry['allowed_hosts']), entry['url']
                try:
                    snapshot = (prior_repeat_verification or {}).get('directories', {}).get(directory)
                    if snapshot:
                        path = workspace/snapshot['path']
                        if (path.is_symlink() or not path.resolve().is_relative_to(workspace/'sources/objects')
                                or snapshot.get('source_url') != directory or snapshot.get('http_status') != 200):
                            raise AcquisitionError('invalid_frozen_directory_snapshot')
                        raw = path.read_bytes()
                        if _sha(raw) != snapshot['content_sha256']:
                            raise AcquisitionError('frozen_directory_hash_mismatch')
                        report['discovery'].append({'source_url': directory, 'status': 'reused_directory_snapshot',
                            'path': snapshot['path'], 'content_sha256': snapshot['content_sha256'],
                            'original_request': snapshot, 'current_discovery_verified': False})
                        gap('current_directory_discovery_unverified', directory)
                    else:
                        raw = request(directory, allowed)
                    if _mime(raw) != 'text/html':
                        raise AcquisitionError('annual_directory_not_html')
                    page = _Links(); page.feed(raw.decode('utf-8', errors='replace'))
                    candidates = []
                    for selector in entry['selectors']:
                        matches = []
                        for link in page.links:
                            label = ' '.join(link['text'].split())
                            candidate = urllib.parse.urljoin(directory, link['href'])
                            if (selector['section'] is not None and link['section'] != selector['section']
                                    or not re.search(selector['text_pattern'].replace('{year}', str(package['report_year'])), label)
                                    or not re.search(selector['url_pattern'].replace('{year}', str(package['report_year'])), candidate)):
                                continue
                            _url(candidate, allowed)
                            matches.append({'source_url': candidate, 'role': selector['role'], 'directory_url': directory,
                                            'link_text': label, 'section': link['section']})
                        if not matches:
                            gap('annual_directory_role_not_found', directory, role=selector['role'])
                        candidates.extend(matches)
                    _write_new(workspace/'source-runs'/run_id/'directory-selections'/(str(number)+'.json'),
                               (json.dumps(candidates, indent=2)+'\n').encode())
                    for item in candidates[:limits['max_discovery_links']]:
                        package_asset(item['source_url'], allowed, role=item['role'], form='OFFICIAL_ANNUAL',
                                      period_end=target_period.isoformat())
                    if len(candidates) > limits['max_discovery_links']:
                        gap('annual_directory_discovery_limit', directory, expected=len(candidates))
                except AcquisitionCancelled:
                    raise
                except Exception as error:
                    gap('annual_directory_discovery_failed', directory, error_type=type(error).__name__,
                        detail=str(error) if isinstance(error, AcquisitionError) else type(error).__name__)
            acquired_roles = {d['role'] for d in report['documents']}
            acquired_roles.update(a['role'] for a in report['selected_assets'] if a['status'] == 'downloaded')
            for role in package['required_roles']:
                if role not in acquired_roles:
                    gap('annual_required_role_missing', role=role)
        for entry in entries if mode == 'latest_10k_and_subsequent_filings' else []:
            allowed, url = set(entry['allowed_hosts']), entry['url']
            try:
                raw = request(url, allowed)
                links = []
                try:
                    tree = ET.fromstring(raw)
                    for item in tree.iter():
                        if item.tag.split('}')[-1] not in ('item', 'entry'):
                            continue
                        href, published = None, None
                        for child in item:
                            tag = child.tag.split('}')[-1]
                            if tag == 'link':
                                href = child.get('href') or child.text
                            if tag in ('published', 'updated', 'pubDate') and child.text:
                                try:
                                    published = _day(child.text[:10], 'feed_date').isoformat()
                                except ValueError:
                                    try:
                                        published = parsedate_to_datetime(child.text).date().isoformat()
                                    except (ValueError, TypeError):
                                        pass
                        if href:
                            links.append((href.strip(), published))
                except ET.ParseError:
                    pass
                if not links:
                    page = _Links(); page.feed(raw.decode('utf-8', errors='replace'))
                    links = [(link['href'], None) for link in page.links]
                    # Prioritize source content over global navigation without
                    # assigning any publication date from a URL or link label.
                    links.sort(key=lambda link: not bool(re.search(
                        r'(?:\d{4}|news|blog|event|press|release|earnings|transcript|\.pdf(?:$|\?))',
                        link[0], re.I)))
                accepted = 0
                for href, published in links:
                    if accepted >= limits['max_discovery_links']:
                        gap('official_discovery_limit', url); break
                    candidate = urllib.parse.urljoin(url, href)
                    try:
                        candidate = _url(candidate, allowed)
                    except (ValueError, TypeError):
                        continue
                    if candidate == url or candidate in seen:
                        continue
                    if update_outside_window(published, candidate):
                        continue
                    accepted += 1
                    try:
                        document(candidate, allowed, form='OFFICIAL_UPDATE' if entry['policy_group'] == 'official' else 'THIRD_PARTY_UPDATE',
                                 role=entry['kind'], published_at=published)
                    except Exception as error:
                        if isinstance(error, AcquisitionCancelled):
                            raise
                        gap(str(error) if isinstance(error, LimitReached) else 'linked_source_unavailable',
                            candidate, error_type=type(error).__name__)
                        if isinstance(error, LimitReached):
                            break
                report['discovery'].append({'source_url': url, 'status': 'coverage_partial', 'kind': entry['kind'],
                                             'links_considered': len(links), 'links_attempted': accepted,
                                             'policy_group': entry['policy_group']})
                gap('official_source_coverage_not_exhaustive', url)
                if not links:
                    gap('no_links_discovered', url)
            except Exception as error:
                if isinstance(error, AcquisitionCancelled):
                    raise
                gap(str(error) if isinstance(error, LimitReached) else 'official_source_unavailable', url, error_type=type(error).__name__)
        if not entries and mode == 'latest_10k_and_subsequent_filings':
            gap('official_ir_blog_events_not_configured')
        configured_kinds = {entry['kind'] for entry in entries if entry['policy_group'] == 'official'}
        for kind in sorted({'ir', 'blog', 'events'} - configured_kinds) if mode == 'latest_10k_and_subsequent_filings' else []:
            gap('official_source_kind_not_configured', kind=kind)
    except AcquisitionCancelled:
        gap('acquisition_cancelled')
    except Exception as error:
        gap(str(error) if isinstance(error, (AcquisitionError, LimitReached)) else 'identity_or_discovery_failed',
            error_type=type(error).__name__,
            **({'next_retry_at': error.next_retry_at} if isinstance(error, AcquisitionDeferred) else {}))
    return finalize()
