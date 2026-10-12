"""Discover and freeze complete image bytes from a caller-selected SEC dataset.

This sidecar never modifies the source dataset. Decoding is an integrity check,
not OCR or semantic interpretation. All unsupported/missing images remain gaps.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings

from .company_acquisition import AcquisitionError, _ExplicitProxy, _Redirect, _transport, _url, SEC_HOSTS
from .filing_integrity import atomic_write_new
from .sec_settings import _contact
from .snapshots import _discover_assets, SnapshotError

VERSION = 'filing-figure-acquisition-v1'
DEFAULT_LIMITS = dict(max_images=100, max_requests=120, max_bytes_per_image=10000000,
                      max_total_bytes=100000000, max_pixels=40000000,
                      timeout_seconds=30, retries=1)
MAX_LIMITS = dict(max_images=500, max_requests=600, max_bytes_per_image=50000000,
                  max_total_bytes=500000000, max_pixels=100000000,
                  timeout_seconds=60, retries=1)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def _contained(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('dataset path must be relative')
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('dataset path escapes root')
    return path


def _scoped_url(url, source_url):
    # Reuse the snapshot contract before any request or redirected request.
    refs, _, _ = _discover_assets(('<img src="' + escape(url, quote=True) + '">').encode(), source_url)
    return refs[0]['source_url']


def _unsupported_graphics(tree, source_id):
    """Fail closed on visual resources outside the supported static img contract.

    This is an inventory check, not CSS rendering. Inline hidden markers do not
    establish that an asset is irrelevant: a stylesheet can override them. Keep
    such cases explicit instead of silently treating an unknown image as absent.
    The SEC tracking-pixel exception remains in _discover_assets for img tags.
    """
    findings = []
    unsupported_tags = {'svg', 'object', 'embed', 'picture', 'canvas', 'video', 'image'}
    css_resource = re.compile(r'url\s*\(|image-set\s*\(|@import', re.IGNORECASE)
    for node in tree.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower().split('}')[-1].split(':')[-1]
        location = {'source_snapshot_id': source_id, 'dom_path': tree.getpath(node)}
        if tag in unsupported_tags:
            findings.append({**location, 'code': 'unsupported_graphic_type', 'kind': tag})
        if node.get('srcset') is not None:
            findings.append({**location, 'code': 'unsupported_graphic_type', 'kind': 'srcset'})
        if tag == 'source' and (node.get('src') or node.get('srcset')):
            findings.append({**location, 'code': 'unsupported_graphic_type', 'kind': 'media_source'})
        if tag == 'link' and 'stylesheet' in node.get('rel', '').lower().split():
            findings.append({**location, 'code': 'unprocessed_external_stylesheet',
                             'href': node.get('href', '')})
        candidates = [('inline_style', node.get('style', ''))]
        if tag == 'style':
            candidates.append(('stylesheet', ''.join(node.itertext())))
        for kind, value in candidates:
            if css_resource.search(value):
                findings.append({**location, 'code': 'unprocessed_css_resource', 'kind': kind,
                                 'css_sha256': _sha(value.encode()), 'css_preview': value[:500]})
    return findings


def discover_figures(dataset: Path):
    """Verify frozen inputs and compare raw-image discovery to indexed identities."""
    dataset = Path(dataset).resolve()
    manifest_raw = (dataset / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    def verified(relative):
        content = _contained(dataset, relative).read_bytes()
        if _sha(content) != manifest['files'].get(relative):
            raise ValueError('dataset artifact hash mismatch: ' + relative)
        return content
    sources_raw = verified('sources.json')
    figures, sources, gaps = [], [], []
    seen_sources = set()
    for source in json.loads(sources_raw):
        source_id = source['source_snapshot_id']
        if source_id in seen_sources:
            raise ValueError('duplicate source identity')
        seen_sources.add(source_id)
        _url(source['source_url'], SEC_HOSTS)
        filing_path = urllib.parse.urlsplit(source['source_url']).path
        accession = re.fullmatch(r'/Archives/edgar/data/([0-9]+)/([0-9]{18})/[^/]+', filing_path)
        entity = re.fullmatch(r'sec-([0-9]{10})', source['company_id'])
        if not accession or not entity or int(accession[1]) != int(entity[1]):
            raise ValueError('source must identify the selected SEC company accession')
        raw = verified(source['raw_file'])
        if _sha(raw) != source['raw_file_sha256'] or _sha(raw) != source['source_sha256']:
            raise ValueError('original source hash mismatch')
        index_manifest = json.loads(verified(source['index_folder'] + '/manifest.json'))
        if index_manifest.get('source_sha256') != _sha(raw):
            raise ValueError('index source hash mismatch')
        indexed = {}
        for name in ('assets.json', 'blocks.jsonl'):
            content = verified(source['index_folder'] + '/' + name)
            if _sha(content) != index_manifest['artifacts'][name]['sha256']:
                raise ValueError('index artifact hash mismatch: ' + name)
            indexed[name] = content
        assets = json.loads(indexed['assets.json'])['assets']
        blocks = [json.loads(line) for line in indexed['blocks.jsonl'].splitlines()]
        from lxml import html
        raw_tree = html.document_fromstring(raw).getroottree()
        gaps.extend(_unsupported_graphics(raw_tree, source_id))
        try:
            refs, count, excluded = _discover_assets(raw, source['source_url'])
        except SnapshotError as error:
            # Preserve a failed source inventory instead of choosing a fallback
            # representation (for example img.src when srcset is present).
            gaps.append({'source_snapshot_id': source_id, 'code': 'unsupported_image_source_contract',
                         'reason': str(error)})
            sources.append({'source_snapshot_id': source_id, 'company_id': source['company_id'],
                            'source_url': source['source_url'], 'source_sha256': _sha(raw),
                            'raw_image_reference_count': len(raw_tree.xpath('//img')),
                            'unique_image_count': None, 'excluded_references': [],
                            'discovery_status': 'unsupported'})
            continue
        sources.append({'source_snapshot_id': source_id, 'company_id': source['company_id'],
                        'source_url': source['source_url'], 'source_sha256': _sha(raw),
                        'raw_image_reference_count': count, 'unique_image_count': len(refs),
                        'excluded_references': excluded})
        discovered_urls = {ref['source_url'] for ref in refs}
        raw_locations = {url: set() for url in discovered_urls}
        excluded_paths = {row['source_path'] for row in excluded}
        for node in raw_tree.xpath('//img[@src]'):
            reference = node.get('src')
            if reference in excluded_paths:
                continue
            resolved = _scoped_url(reference, source['source_url'])
            raw_locations[resolved].add(raw_tree.getpath(node))
        for asset in assets:
            if asset['source_url'] not in discovered_urls:
                gaps.append({'source_snapshot_id': source_id, 'code': 'index_asset_not_in_raw',
                             'asset_id': asset['asset_id']})
        for ref in refs:
            matches = [asset for asset in assets if asset['source_url'] == ref['source_url']]
            locations = []
            for asset in matches:
                nodes = raw_tree.xpath(asset['dom_path'])
                if (len(nodes) != 1 or nodes[0].tag.lower() != 'img'
                        or _scoped_url(nodes[0].get('src', ''), source['source_url']) != ref['source_url']):
                    raise ValueError('image locator does not identify original image')
                selected = [b for b in blocks if b.get('image_asset_id') == asset['asset_id']
                            and b.get('dom_path') == asset['dom_path']]
                if len(selected) != 1:
                    gaps.append({'source_snapshot_id': source_id, 'code': 'image_index_locator_not_unique',
                                 'asset_id': asset['asset_id']})
                locations.extend({'asset_id': asset['asset_id'], 'block_id': b['block_id'],
                                  'dom_path': b['dom_path'], 'alt': asset.get('alt', '')}
                                 for b in selected)
            if {location['dom_path'] for location in locations} != raw_locations[ref['source_url']]:
                gaps.append({'source_snapshot_id': source_id, 'code': 'image_occurrence_coverage_mismatch',
                             'source_url': ref['source_url'],
                             'expected_dom_paths': sorted(raw_locations[ref['source_url']]),
                             'indexed_dom_paths': sorted({location['dom_path'] for location in locations})})
            if not locations:
                gaps.append({'source_snapshot_id': source_id, 'code': 'image_missing_index_locator',
                             'source_url': ref['source_url']})
            figures.append({**ref, 'figure_id': 'fig-' + _sha((source_id + '\n' + ref['source_url']).encode())[:24],
                            'source_snapshot_id': source_id, 'company_id': source['company_id'],
                            'document_source_url': source['source_url'], 'source_sha256': _sha(raw),
                            'locations': locations, 'status': 'pending'})
    return {'schema_version': VERSION, 'dataset_manifest_sha256': _sha(manifest_raw),
            'sources': sources, 'figures': figures, 'gaps': gaps}


def inspect_image(raw, max_pixels):
    try:
        from PIL import Image
    except ImportError as error:
        raise AcquisitionError('missing_image_decoder_install_data_extra') from error
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise AcquisitionError('image_pixel_limit')
            if image.format not in ('JPEG', 'PNG', 'GIF', 'WEBP'):
                raise AcquisitionError('unsupported_image_format')
            if getattr(image, 'n_frames', 1) != 1:
                raise AcquisitionError('animated_image_requires_frame_processing')
            fmt = image.format
            image.verify()
        # verify() alone does not decode compressed JPEG scan data.
        with Image.open(BytesIO(raw)) as image:
            image.load()
    return {'width': width, 'height': height, 'format': fmt,
            'media_type': {'JPEG': 'image/jpeg', 'PNG': 'image/png',
                           'GIF': 'image/gif', 'WEBP': 'image/webp'}[fmt]}


def acquire_figures(dataset: Path, workspace: Path, *, user_agent: str,
                    transport=None, limits=None, fetch=None):
    """Freeze a new independent run; fetch injection is test-only bytes transport."""
    user_agent = _contact(user_agent)
    policy = dict(DEFAULT_LIMITS)
    if limits is not None:
        if not isinstance(limits, dict) or set(limits) - set(policy):
            raise ValueError('unknown figure acquisition limits')
        policy.update(limits)
    for key, value in policy.items():
        if type(value) is not int or not (0 if key == 'retries' else 1) <= value <= MAX_LIMITS[key]:
            raise ValueError('invalid figure acquisition limit: ' + key)
    proxy = _transport({'transport': transport})
    report = discover_figures(dataset)
    workspace = Path(workspace)
    if workspace.exists() or workspace.is_symlink():
        raise FileExistsError('figure output already exists')
    workspace = workspace.resolve()
    if workspace.resolve().is_relative_to(Path(dataset).resolve()):
        raise ValueError('figure output must not modify source dataset')
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / 'originals').mkdir()
    report.update(started_at=datetime.now(timezone.utc).isoformat(), limits=policy,
                  transport=proxy or {'mode': 'public_dns_http'}, requests=0, total_bytes=0,
                  model_calls=0, status='running', implementation_sha256=_sha(Path(__file__).read_bytes()))
    atomic_write_new(workspace / 'input.json', _json(report))
    last_request = 0.0

    def record(event):
        event['recorded_at'] = datetime.now(timezone.utc).isoformat()
        with (workspace / 'requests.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()

    def reserve(url, figure, *, redirect=False):
        nonlocal last_request
        _scoped_url(url, figure['document_source_url'])
        if report['requests'] >= policy['max_requests']:
            raise AcquisitionError('request_limit')
        report['requests'] += 1
        if fetch is None:
            time.sleep(max(0, .15 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        record({'figure_id': figure['figure_id'], 'source_url': url,
                'status': 'redirect_started' if redirect else 'request_started',
                'request_ordinal': report['requests']})

    def retrieve(figure):
        url = figure['source_url']
        host = urllib.parse.urlsplit(url).hostname
        use_proxy = proxy is not None and host in proxy['destination_hosts']
        for attempt in range(policy['retries'] + 1):
            if report['total_bytes'] >= policy['max_total_bytes']:
                raise AcquisitionError('total_byte_limit')
            reserve(url, figure)
            receipt = {'figure_id': figure['figure_id'], 'source_url': url, 'attempt': attempt + 1}
            try:
                if fetch is not None:
                    raw = fetch(url, headers={'User-Agent': user_agent, 'Accept-Encoding': 'identity'},
                                timeout=policy['timeout_seconds'])
                    receipt.update(transport='injected_fetch', final_url=url)
                else:
                    _url(url, {host}, resolve=not use_proxy)
                    def on_redirect(previous, target):
                        reserve(target, figure, redirect=True)
                    handlers = [_Redirect({host}, on_redirect, resolve=not use_proxy)]
                    if use_proxy:
                        handlers.insert(0, _ExplicitProxy({'https': proxy['proxy_url']}))
                    else:
                        handlers.insert(0, urllib.request.ProxyHandler({}))
                    opener = urllib.request.build_opener(*handlers)
                    request = urllib.request.Request(url, headers={'User-Agent': user_agent, 'Accept-Encoding': 'identity'})
                    with opener.open(request, timeout=policy['timeout_seconds']) as response:
                        _scoped_url(response.url, figure['document_source_url'])
                        receipt.update(http_status=response.status, final_url=response.url,
                                       content_type=response.headers.get('Content-Type'))
                        if response.status != 200:
                            raise AcquisitionError('unexpected_http_status')
                        raw = response.read(min(policy['max_bytes_per_image'],
                                                policy['max_total_bytes'] - report['total_bytes']) + 1)
                        receipt['content_length'] = response.headers.get('Content-Length')
                if not isinstance(raw, bytes) or not raw:
                    raise AcquisitionError('empty_or_nonbytes_response')
                report['total_bytes'] += len(raw)
                if len(raw) > policy['max_bytes_per_image'] or report['total_bytes'] > policy['max_total_bytes']:
                    raise AcquisitionError('image_byte_limit')
                digest = _sha(raw)
                # Freeze even malformed responses; inspection failures must be inspectable.
                path = workspace / 'originals' / (digest + '.bin')
                if not path.exists():
                    atomic_write_new(path, raw)
                figure.update(artifact_path=str(path.relative_to(workspace)), sha256=digest, bytes=len(raw))
                receipt.update(bytes=len(raw), sha256=digest, artifact_path=figure['artifact_path'])
                if receipt.get('content_length') is not None and int(receipt['content_length']) != len(raw):
                    raise AcquisitionError('content_length_mismatch')
                info = inspect_image(raw, policy['max_pixels'])
                record({**receipt, 'status': 'fetched', **info})
                return info
            except Exception as error:
                event = {**receipt, 'status': 'failed', 'error_type': type(error).__name__,
                         'reason': str(error) if isinstance(error, AcquisitionError) else type(error).__name__,
                         'http_status': getattr(error, 'code', receipt.get('http_status'))}
                record(event)
                transient = isinstance(error, (TimeoutError, ConnectionError, urllib.error.URLError))
                if isinstance(error, urllib.error.HTTPError):
                    transient = error.code in (408, 429) or error.code >= 500
                    retry_after = error.headers.get('Retry-After') if error.headers else None
                    if retry_after:
                        # Preserve and defer; never immediately retry against a server deadline.
                        record({**event, 'status': 'deferred', 'retry_after': retry_after})
                        raise
                if not transient or attempt == policy['retries']:
                    raise
                time.sleep(.5 * (2 ** attempt))
        raise AcquisitionError('request_failed')

    try:
        if len(report['figures']) > policy['max_images']:
            raise AcquisitionError('image_count_limit')
        for figure in report['figures']:
            try:
                figure.update(retrieve(figure), status='frozen')
            except Exception as error:
                figure.update(status='failed', error_type=type(error).__name__)
                report['gaps'].append({'figure_id': figure['figure_id'], 'code': str(error)
                                     if isinstance(error, AcquisitionError) else type(error).__name__})
    except Exception as error:
        report['gaps'].append({'code': str(error), 'error_type': type(error).__name__})
    report['status'] = 'complete' if not report['gaps'] else 'with_gaps'
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    atomic_write_new(workspace / 'manifest.json', _json(report))
    return report


def main():
    """Standalone system entry point; caller selects scope through a frozen dataset."""
    import argparse
    from .sec_settings import resolve_sec_contact
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--settings-root', type=Path, required=True)
    parser.add_argument('--transport-config', type=Path)
    parser.add_argument('--limits-config', type=Path)
    args = parser.parse_args()
    contact, _ = resolve_sec_contact(settings_root=args.settings_root)
    if contact is None:
        parser.error('SEC contact is required in settings or environment')
    result = acquire_figures(args.dataset, args.workspace, user_agent=contact,
        transport=json.loads(args.transport_config.read_text()) if args.transport_config else None,
        limits=json.loads(args.limits_config.read_text()) if args.limits_config else None)
    print(json.dumps({'status': result['status'], 'figures': len(result['figures']),
                      'gaps': result['gaps'], 'manifest': str(args.workspace / 'manifest.json')}))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
