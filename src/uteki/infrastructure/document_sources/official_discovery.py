"""Model-selected official HTML acquisition using the common source-run storage.

The caller supplies registered identity and official roots, never target files.
Text witness checks are not independent semantic acceptance or historical adoption.
"""
from copy import deepcopy
import http.client
import ipaddress
import json
import re
import socket
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from .company_acquisition import (AcquisitionError, AcquisitionCancelled, LimitReached,
    _day, _mime, _sha, _url, _write_new, prepare_sources)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        # Resolve once, validate every result, and connect to that exact address.
        # TLS still verifies the original hostname. No second DNS lookup/rebinding.
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise AcquisitionError('non-public DNS destination forbidden')
        last = None
        for family, kind, proto, _, address in addresses:
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(self.timeout)
                sock.connect(address)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as error:
                last = error
                sock.close()
        raise last


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=ssl.create_default_context())


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.skip = [], [], 0
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if not self.skip and tag == 'a' and attrs.get('href'):
            self.active = {'href': attrs['href'], 'text': ''}

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip:
            self.skip -= 1
        if tag == 'a' and self.active:
            self.links.append(self.active)
            self.active = None

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)
            if self.active is not None:
                self.active['text'] += data


def _text(raw):
    page = _Page()
    page.feed(raw.decode('utf-8-sig', errors='replace'))
    return ' '.join(' '.join(page.text).split()), page.links


def validate_task(config, task):
    required = {'company', 'fiscal_year', 'period_end', 'material_type', 'task', 'roots', 'allowed_hosts',
                'max_steps', 'page_chars', 'links_per_page'}
    if not isinstance(task, dict) or set(task) != required:
        raise ValueError('explicit official discovery task fields required')
    company = task['company']
    if (not isinstance(company, dict) or set(company) != {'company_id', 'symbol', 'cik', 'market', 'name', 'aliases'}
            or any(company.get(k) != config.get(k) for k in ('symbol', 'cik', 'market'))
            or company['company_id'] != 'sec-' + company['cik']):
        raise ValueError('official company identity mismatch')
    if (not isinstance(company['name'], str) or not company['name'].strip()
            or not isinstance(company['aliases'], list) or not company['aliases']
            or any(not isinstance(a, str) or len(a.strip()) < 3 for a in company['aliases'])):
        raise ValueError('explicit company names required')
    period = _day(task['period_end'], 'period_end')
    if period > _day(config['as_of'], 'as_of') or config['filing_selection'].get('report_period_end') != task['period_end']:
        raise ValueError('official period conflicts with source scope')
    if type(task['fiscal_year']) is not int or not 1900 <= task['fiscal_year'] <= 9999:
        raise ValueError('explicit fiscal year required')
    if task['material_type'] not in {'annual_report', 'annual_results'}:
        raise ValueError('unsupported official material type')
    if not isinstance(task['task'], str) or not task['task'].strip():
        raise ValueError('explicit material task required')
    for key, maximum in [('max_steps', 60), ('page_chars', 24000), ('links_per_page', 100)]:
        if type(task[key]) is not int or not 1 <= task[key] <= maximum:
            raise ValueError('invalid discovery bound: ' + key)
    hosts = task['allowed_hosts']
    if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) for h in hosts):
        raise ValueError('official hosts required')
    approved = set().union(*(set(e['allowed_hosts']) for e in config['source_policy']['official']))
    if not set(hosts) <= approved:
        raise ValueError('official hosts outside caller policy')
    if not isinstance(task['roots'], list) or not task['roots']:
        raise ValueError('official roots required')
    for root in task['roots']:
        _url(root, set(hosts))
        parsed = urllib.parse.urlsplit(root)
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('discovery starts only at explicit official roots')
    if config.get('transport') is not None:
        raise ValueError('official discovery requires direct public HTTPS transport')
    if not {'max_requests', 'max_documents', 'max_total_bytes', 'max_bytes_per_document', 'timeout_seconds', 'retries'} <= config.get('limits', {}).keys():
        raise ValueError('explicit official network resource limits required')
    if config.get('annual_package') or config['limits'].get('retries', 1) > 1:
        raise ValueError('directory adapters and unbounded retries forbidden in model discovery')


class OfficialDiscovery:
    """A persistent, bounded session; URLs enter the frontier only through observations."""
    def __init__(self, config, task, workspace, *, fetch=None, should_stop=None):
        validate_task(config, task)
        self.task, self.workspace = deepcopy(task), Path(workspace).resolve()
        self.should_stop = should_stop
        self.worker_stop = None
        self.session = prepare_sources(config, workspace, fetch=fetch, should_stop=lambda: bool((self.should_stop and self.should_stop()) or
            (self.worker_stop and self.worker_stop())), _session_only=True)
        self.report = self.session['report']
        self.report['company'] = {k: v for k, v in task['company'].items() if k != 'aliases'}
        self.report['scope']['official_discovery'] = deepcopy(task)
        self.report['scope']['identity_resolution'] = 'caller_registered_official_roots'
        self.allowed = set(task['allowed_hosts'])
        self.frontier = {root: [] for root in task['roots']}
        self.pages, self.observed, self.blocked = {}, {}, set()
        self.steps, self.closed = 0, False

    def execute(self, arguments, *, should_stop=None):
        self.worker_stop = should_stop
        if self.closed:
            raise ValueError('official session already closed')
        self.steps += 1
        if self.steps > self.task['max_steps']:
            raise LimitReached('discovery_step_limit')
        self.session['check_stop']()
        op = arguments.get('operation')
        expected = {'operation', 'url', 'offset', 'link_offset'} if op == 'browse' else {
            'operation', 'url', 'reason', 'company_quote', 'period_quote', 'material_quote'}
        if set(arguments) != expected or op not in {'browse', 'download'}:
            raise ValueError('unsupported official action fields')
        url = _url(arguments['url'], self.allowed)
        if url not in self.frontier:
            raise ValueError('URL was not observed in this discovery session')
        if url in self.blocked:
            return {'status': 'gap', 'reason': 'permanent_failure_already_observed', 'url': url}
        try:
            return self._browse(url, arguments) if op == 'browse' else self._download(url, arguments)
        except (AcquisitionCancelled, LimitReached):
            raise
        except Exception as error:
            code = getattr(error, 'code', None)
            if code in (401, 403, 404, 410):
                self.blocked.add(url)
            reason = ('access_denied_or_challenge' if code in (401, 403) else 'not_found' if code in (404, 410)
                      else str(error) if isinstance(error, AcquisitionError) else type(error).__name__)
            self.session['gap'](reason, url, http_status=code)
            return {'status': 'gap', 'reason': reason, 'url': url, 'http_status': code}

    def _browse(self, url, args):
        for field in ('offset', 'link_offset'):
            if type(args[field]) is not int or args[field] < 0:
                raise ValueError('nonnegative page offsets required')
        raw = self.session['request'](url, self.allowed)
        if _mime(raw) != 'text/html':
            raise AcquisitionError('unsupported_text_format')
        text, links = _text(raw)
        if re.search(r'(?i)(just a moment|verify you are human|cf-chl-|access denied)', text[:500]):
            self.blocked.add(url)
            raise AcquisitionError('access_denied_or_challenge')
        final = next(d['final_url'] for d in reversed(self.report['discovery'])
                     if d.get('source_url') == url and d.get('status') == 'fetched')
        clean = []
        for link in links:
            try:
                target = _url(urllib.parse.urljoin(final, link['href']), self.allowed)
            except (ValueError, TypeError):
                continue
            if target not in {r['url'] for r in clean}:
                clean.append({'url': target, 'text': ' '.join(link['text'].split())[:500]})
        lo, offset = args['link_offset'], args['offset']
        shown = clean[lo:lo + self.task['links_per_page']]
        witness = {'page_url': url, 'final_url': final, 'page_sha256': _sha(raw)}
        for link in shown:
            parents = self.frontier.setdefault(link['url'], [])
            if witness not in parents:
                parents.append(witness)
        snippet = text[offset:offset + self.task['page_chars']]
        self.pages[url] = (raw, text)
        self.observed.setdefault(url, []).append(snippet)
        return {'status': 'observed', **witness, 'text': snippet, 'links': shown,
                'next_offset': offset + len(snippet) if offset + len(snippet) < len(text) else None,
                'next_link_offset': lo + len(shown) if lo + len(shown) < len(clean) else None}

    def _download(self, url, args):
        existing = next((d for d in self.report['documents'] if d['source_url'] == url), None)
        if existing is not None:
            return {'status': 'archived_pending_review', 'document': existing}
        if url not in self.pages:
            raise AcquisitionError('browse_candidate_before_download')
        for key in ('reason', 'company_quote', 'period_quote', 'material_quote'):
            if not isinstance(args[key], str) or not args[key].strip() or len(args[key]) > 2000:
                raise AcquisitionError('explicit_bounded_selection_witness_required')
        for key in ('company_quote', 'period_quote', 'material_quote'):
            if not any(args[key] in part for part in self.observed[url]):
                raise AcquisitionError('selection_quote_not_observed:' + key + ':copy_exact_observed_text_including_case')
        if not any(alias.casefold() in args['company_quote'].casefold() for alias in self.task['company']['aliases']):
            raise AcquisitionError('company_witness_mismatch')
        if not re.search(r'(?<!\d)' + str(self.task['fiscal_year']) + r'(?!\d)', args['period_quote']):
            raise AcquisitionError('period_witness_mismatch')
        pattern = r'annual\s+report' if self.task['material_type'] == 'annual_report' else r'(full[ -]year|annual|year ended|fiscal year)'
        if not re.search(pattern, args['material_quote'], re.I):
            raise AcquisitionError('material_witness_mismatch')
        row = self.session['document'](url, self.allowed, form='OFFICIAL_MATERIAL', role='ir',
            period_end=self.task['period_end'])
        if row is None:
            raise AcquisitionError('after_as_of')
        row['discovered_from'] = deepcopy(self.frontier[url])
        row['selection'] = deepcopy(args)
        row['validation'] = {'version': 'official-text-witness-v1', 'identity_verified': False,
            'text_witnesses_verified': True, 'semantic_acceptance': 'requires_independent_review'}
        # Even a page's publication meta is not proof of its FIRST availability.
        row.update(as_of_eligible=False, status='frozen_pending_review', available_at=None)
        row['same_content_sources'] = [d['source_url'] for d in self.report['documents']
            if d['content_sha256'] == row['content_sha256'] and d['source_url'] != url]
        _write_new(self.workspace/'source-runs'/self.report['run_id']/'official-receipts'/
            (row['source_id']+'.json'), (json.dumps(row, ensure_ascii=False, indent=2)+'\n').encode())
        return {'status': 'archived_pending_review', 'document': row}

    def finish(self, reason):
        if self.closed:
            return self.report
        self.closed = True
        self.report['stop_reason'] = reason
        if reason != 'finished':
            self.session['gap'](reason)
        if not self.report['documents']:
            self.session['gap']('no_material_acquired')
        self.report['model_actions'] = self.steps
        return self.session['finish']()
