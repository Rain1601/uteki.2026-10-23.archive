"""Company-parameterized annual originals, with three real HTTP observations.

No model calls, financial normalization, or automatic adoption. Directory adapters
are explicit profiles; changing the company never falls back to the sample issuer.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import signal

from .company_acquisition import _configuration, _day, _write_new, prepare_sources
from .sec_settings import resolve_sec_contact

VERSION = 'annual-package-verification-v1'
ROUNDS = 3


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _sealed_lineage(path, pin, identity, fiscal_year, period, as_of, workspace):
    """Follow only explicitly pinned parents; validate each preserved round."""
    reports, visited = [], set()
    for _ in range(10):
        path = Path(path).resolve()
        if path in visited or _sha(path.read_bytes()) != pin:
            raise ValueError('resume lineage cycle or SHA256 mismatch')
        visited.add(path)
        summary = json.loads(path.read_text())
        if (summary.get('schema_version') != VERSION or summary.get('company') != identity
                or summary.get('fiscal_year') != fiscal_year or summary.get('report_period_end') != period
                or summary.get('as_of') != as_of or summary.get('workspace') != str(workspace)):
            raise ValueError('resume lineage scope mismatch')
        sealed = dict(line.split('  ', 1)[::-1] for line in (path.parent/'SHA256SUMS').read_text().splitlines())
        names = ['input.json', *[f'round-{i}.json' for i in range(1, summary['completed_rounds']+1)]]
        data = {}
        for name in names:
            raw = (path.parent/name).read_bytes()
            if _sha(raw) != sealed.get(name):
                raise ValueError('resume round or input hash mismatch')
            data[name] = json.loads(raw)
        reports.extend(data[name] for name in reversed(names[1:]))
        parent = data['input.json'].get('resume_verification')
        if parent is None:
            return reports
        path, pin = parent, data['input.json']['resume_sha256']
    raise ValueError('resume lineage exceeds bounded depth')


def acquire_annual_package(profile, *, company, fiscal_year, report_period_end, as_of,
                           workspace, output, sec_user_agent, contact_origin='caller', fetch=None,
                           should_stop=None, resume_verification=None, resume_sha256=None,
                           use_frozen_directories=False):
    if (not isinstance(profile, dict) or profile.get('schema_version') != 'annual-material-profile-v1'
            or not isinstance(profile.get('company'), dict)):
        raise ValueError('explicit annual material profile required')
    identity = profile['company']
    aliases = identity.get('aliases')
    if (not isinstance(company, str) or not company.strip() or not isinstance(aliases, list)
            or any(not isinstance(a, str) or not a.strip() for a in aliases)
            or company.strip().casefold() not in {a.casefold() for a in aliases}
            or identity.get('symbol', '').casefold() not in {a.casefold() for a in aliases}):
        raise ValueError('company must match the explicitly selected profile')
    if type(fiscal_year) is not int or not 1900 <= fiscal_year <= 9999:
        raise ValueError('explicit fiscal_year required')
    if profile.get('fiscal_year_label') != 'period_end_year':
        raise ValueError('explicit supported fiscal_year_label required')
    if _day(report_period_end, 'report_period_end').year != fiscal_year:
        raise ValueError('fiscal year label conflicts with the selected report period')
    if profile.get('annual_form') not in ('10-K', '20-F'):
        raise ValueError('profile must explicitly select 10-K or 20-F')
    # Period dates are caller inputs, not derived from a calendar-year assumption.
    config = {'symbol': identity['symbol'], 'cik': identity['cik'], 'market': identity['market'],
              'as_of': as_of, 'sec_user_agent': sec_user_agent, 'sec_contact_origin': contact_origin,
              'document_validation': 'sec_inline_identity_v1', 'download_policy': 'revalidate',
              'filing_selection': {'mode': 'annual_filing_period', 'annual_form': profile['annual_form'],
                                   'report_period_end': report_period_end},
              'source_policy': {'official': [], 'third_party': []},
              'annual_package': {'version': 'annual-financial-package-v1', 'report_year': fiscal_year,
                                'directories': deepcopy(profile['directories']),
                                'required_roles': list(profile['required_roles'])},
              'limits': {'max_requests': 26, 'max_documents': 40, 'max_bytes_per_document': 32*1024*1024,
                         'max_total_bytes': 80*1024*1024, 'max_discovery_links': 100,
                         'timeout_seconds': 40, 'retries': 1, 'backoff_seconds': 1,
                         'min_request_interval_seconds': .5}}
    _configuration(config)  # Reject incomplete scope before creating any artifacts.
    output, workspace = Path(output).resolve(), Path(workspace).resolve()
    prior = None
    reuse = {'cik': identity['cik'], 'report_period_end': report_period_end, 'as_of': as_of,
             'verification_sha256': resume_sha256 or '0'*64, 'items': {}}
    expected, observations, last_documents = {}, {}, {}
    if type(use_frozen_directories) is not bool or use_frozen_directories and resume_verification is None:
        raise ValueError('frozen directories require explicit pinned resume')
    if resume_verification is not None:
        raw = Path(resume_verification).read_bytes()
        if _sha(raw) != resume_sha256:
            raise ValueError('resume verification SHA256 mismatch')
        prior = json.loads(raw)
        if (prior.get('schema_version') != VERSION or prior.get('company') != identity
                or prior.get('fiscal_year') != fiscal_year or prior.get('report_period_end') != report_period_end
                or prior.get('as_of') != as_of or prior.get('workspace') != str(workspace)):
            raise ValueError('resume verification belongs to another company, period, cutoff or store')
        old_rounds = _sealed_lineage(resume_verification, resume_sha256, identity, fiscal_year,
                                    report_period_end, as_of, workspace)
        if use_frozen_directories:
            directories = {}
            for entry in profile['directories']:
                event = next((e for r in old_rounds for e in reversed(r['discovery'])
                    if e['source_url'] == entry['url'] and e['status'] == 'fetched'
                    and e.get('http_status') == 200 and e.get('transport') in
                    ('http', 'trusted_local_http_proxy')), None)
                if event is None:
                    raise ValueError('no verified directory snapshot for explicit profile')
                directories[entry['url']] = event
            reuse['directories'] = directories
        for material in prior['materials']:
            expected[material['source_url']] = set(material['roles'])
            obs = material['observations']
            if (not 0 < len(obs) <= ROUNDS
                    or len({o['content_sha256'] for o in obs}) != 1
                    or [o['round'] for o in obs] != list(range(1, len(obs)+1))
                    or not all(o['storage_hash_verified'] and o['remote_request']
                        and o['remote_request'].get('http_status') == 200
                        and o['remote_request'].get('transport') in ('http', 'trusted_local_http_proxy')
                        and o['remote_request'].get('content_sha256') == o['content_sha256']
                        and o['remote_request'].get('source_url') == material['source_url'] for o in obs)):
                continue
            doc = next(d for r in old_rounds for d in r['documents']
                       if d['source_url'] == material['source_url'] and
                       d['content_sha256'] == obs[-1]['content_sha256'])
            if any(doc[key] != obs[-1][key] for key in ('path', 'content_sha256')):
                raise ValueError('resume material disagrees with sealed original')
            for o in obs:
                path = workspace/o['path']
                if (path.is_symlink() or not path.resolve().is_relative_to(workspace/'sources/objects')
                        or _sha(path.read_bytes()) != o['content_sha256']):
                    raise ValueError('resume original path or hash mismatch')
            observations[material['source_url']] = deepcopy(obs)
            last_documents[material['source_url']] = doc
            if len(obs) == ROUNDS:
                reuse['items'][material['source_url']] = doc
    elif resume_sha256 is not None:
        raise ValueError('resume SHA256 requires a verification file')
    if output.exists():
        raise ValueError('verification output already exists; prior runs are immutable')
    if output.is_relative_to(workspace/'sources') or output.is_relative_to(workspace/'source-runs'):
        raise ValueError('verification output must not overlap original storage')
    output.mkdir(parents=True)
    public_input = {k: v for k, v in config.items() if k != 'sec_user_agent'}
    public_input.update(schema_version=VERSION, company_requested=company, repeat_count=ROUNDS,
                        directory_policy='reuse_pinned' if use_frozen_directories else 'require_fresh',
                        profile_sha256=_sha(json.dumps(profile, sort_keys=True).encode()),
                        method_sha256=_sha(Path(__file__).read_bytes()),
                        downloader_sha256=_sha(Path(__file__).with_name('company_acquisition.py').read_bytes()))
    if prior:
        public_input.update(resume_verification=str(resume_verification), resume_sha256=resume_sha256,
                            prior_remote_verified_materials=len(reuse['items']),
                            prior_partial_materials=sum(len(o) < ROUNDS for o in observations.values()))
    _write_new(output/'input.json', (json.dumps(public_input, ensure_ascii=False, indent=2)+'\n').encode())
    for name in ('annual_package.py', 'company_acquisition.py'):
        _write_new(output/'method-snapshot'/name, Path(__file__).with_name(name).read_bytes())
    prior_complete = len(reuse['items'])
    prior_partial = sum(len(o) < ROUNDS for o in observations.values())
    rounds, duplicates, directory_inventories = [], [], []
    reuse_checks, blocked = {}, {}
    for number in range(1, ROUNDS+1):
        if should_stop and should_stop():
            break
        report = prepare_sources(config, workspace, fetch=fetch, should_stop=should_stop,
                                 prior_repeat_verification=reuse, blocked_sources=blocked)
        rounds.append(report)
        inventory = set()
        for task in [*report['selected_filings'], *report['selected_assets']]:
            url = task.get('source_url')
            if url:
                role = task.get('role', 'filing')
                expected.setdefault(url, set()).add(role)
                inventory.add((url, role))
        directory_inventories.append(inventory)
        by_hash = {}
        for doc in report['documents']:
            url = doc['source_url']
            expected.setdefault(url, set()).add(doc['role'])
            event = next((e for e in reversed(report['discovery'])
                          if e.get('source_url') == url and e['status'] == 'fetched'), None)
            original = workspace/doc['path']
            with original.open('rb') as stream:
                storage_valid = hashlib.file_digest(stream, 'sha256').hexdigest() == doc['content_sha256']
            if not storage_valid:
                report['gaps'].append({'reason': 'original_hash_mismatch', 'source_url': url})
            if doc['acquisition'] == 'reused_remote_verified':
                reuse_checks.setdefault(url, []).append({'round': number, 'storage_hash_verified': storage_valid,
                                                         'verification_sha256': reuse['verification_sha256']})
            else:
                obs = observations.setdefault(url, [])
                obs.append({'round': len(obs)+1, 'batch_round': number, 'content_sha256': doc['content_sha256'],
                'storage_hash_verified': storage_valid,
                'path': doc['path'], 'mime_type': doc['mime_type'], 'validation': doc['validation'],
                'as_of_eligible': doc['as_of_eligible'], 'remote_request': event})
                last_documents[url] = doc
                if len(obs) == ROUNDS and all(o['storage_hash_verified'] and o['remote_request']
                        and o['remote_request'].get('http_status') == 200
                        and o['remote_request'].get('transport') in ('http', 'trusted_local_http_proxy') for o in obs):
                    # Hold completed observations even when their hashes differ:
                    # the result remains changed; do not hide it with a fourth GET.
                    reuse['items'][url] = doc
            by_hash.setdefault(doc['content_sha256'], set()).add(url)
        duplicates.extend({'round': number, 'content_sha256': sha, 'source_urls': sorted(urls),
                           'relation': 'byte_identical', 'sources_preserved': True}
                          for sha, urls in by_hash.items() if len(urls) > 1)
        round_raw = (json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode()
        _write_new(output/f'round-{number}.json', round_raw)
        reuse['verification_sha256'] = _sha(round_raw)
        blocked.update({e['source_url']: e['http_status'] for e in report['discovery']
                        if e['status'] == 'failed' and e.get('http_status') in (401, 403, 404, 410)})
        # An auxiliary denial blocks that URL for this batch, not unrelated
        # material verification. Missing issuer/original or limits stop the batch.
        if (report['company'] is None or report['status'] == 'cancelled'
                or any(g['reason'] == 'annual_required_role_missing' and g.get('role') == 'filing'
                       for g in report['gaps'])
                or any(g['reason'] in ('request_limit', 'total_byte_limit')
                       or g.get('detail') in ('request_limit', 'total_byte_limit') for g in report['gaps'])):
            break
    materials = []
    for url, roles in sorted(expected.items()):
        obs = observations.get(url, [])
        hashes = {o['content_sha256'] for o in obs}
        downloaded_all = len(obs) == ROUNDS and {o['round'] for o in obs} == set(range(1, ROUNDS+1))
        real_http = downloaded_all and all(o['remote_request'] and
            o['remote_request'].get('transport') in ('http', 'trusted_local_http_proxy') and
            o['remote_request'].get('http_status') == 200 for o in obs)
        materials.append({'source_url': url, 'roles': sorted(roles), 'observations': obs,
                          'reuse_checks': reuse_checks.get(url, []),
                          'repeat_complete': downloaded_all, 'remote_repeat_complete': real_http,
                          'byte_consistency': 'changed' if len(hashes) > 1 else
                                              'stable' if downloaded_all else 'incomplete'})
    gaps = [{'round': i, **gap} for i, report in enumerate(rounds, 1) for gap in report['gaps']]
    if len(rounds) != ROUNDS:
        gaps.append({'reason': 'repeat_rounds_incomplete', 'completed': len(rounds), 'expected': ROUNDS})
    inventories_agree = len(directory_inventories) == ROUNDS and all(
        inventory == directory_inventories[0] for inventory in directory_inventories)
    if len(directory_inventories) > 1 and not inventories_agree:
        gaps.append({'reason': 'material_inventory_changed_between_rounds'})
    if prior and (not directory_inventories or any((url, role) not in directory_inventories[-1]
                     for url, roles in expected.items() for role in roles)):
        gaps.append({'reason': 'prior_material_missing_from_current_inventory'})
    summary = {'schema_version': VERSION, 'company': identity, 'fiscal_year': fiscal_year,
               'report_period_end': report_period_end, 'as_of': as_of, 'repeat_count': ROUNDS,
               'completed_rounds': len(rounds), 'expected_materials': len(materials),
               'stable_materials': sum(m['byte_consistency'] == 'stable' for m in materials),
               'changed_materials': sum(m['byte_consistency'] == 'changed' for m in materials),
               'incomplete_materials': sum(not m['repeat_complete'] for m in materials),
               'requests': sum(r['requests'] for r in rounds),
               'bytes_received': sum(r['bytes_received'] for r in rounds), 'model_calls': 0,
               'reused_prior_materials': prior_complete,
               'inherited_partial_materials': prior_partial,
               'prior_verification_sha256': resume_sha256,
               'directory_policy': public_input['directory_policy'],
               'current_directory_discovery_complete': not use_frozen_directories and len(rounds) == ROUNDS and all(
                   not any(g['reason'] == 'annual_directory_discovery_failed' for g in r['gaps']) for r in rounds),
               'inventory_consistent': inventories_agree, 'materials': materials,
               'byte_duplicate_groups': duplicates, 'gaps': gaps,
               'status': 'completed_with_gaps' if gaps else 'completed',
               'financial_fact_coverage': 'not_audited', 'parsing_acceptance': 'not_run',
               'workspace': str(workspace)}
    _write_new(output/'verification.json', (json.dumps(summary, ensure_ascii=False, indent=2)+'\n').encode())
    files = sorted(output.rglob('*'))
    _write_new(output/'SHA256SUMS', ''.join(_sha(p.read_bytes())+'  '+p.relative_to(output).as_posix()+'\n'
        for p in files if p.is_file()).encode())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--company', required=True)
    parser.add_argument('--fiscal-year', type=int, required=True)
    parser.add_argument('--report-period-end', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--settings-root', type=Path, required=True)
    parser.add_argument('--resume-verification', type=Path)
    parser.add_argument('--resume-sha256')
    parser.add_argument('--use-frozen-directories', action='store_true',
                        help='Use pinned directory snapshots; current directory coverage stays unverified')
    args = parser.parse_args(argv)
    stopped = [False]
    signal.signal(signal.SIGINT, lambda *_: stopped.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: stopped.__setitem__(0, True))
    try:
        profile = json.loads(args.profile.read_text())
        contact, origin = resolve_sec_contact(settings_root=args.settings_root)
        if contact is None:
            raise ValueError('private SEC contact is not configured')
        result = acquire_annual_package(profile, company=args.company, fiscal_year=args.fiscal_year,
            report_period_end=args.report_period_end, as_of=args.as_of, workspace=args.workspace,
            output=args.output, sec_user_agent=contact, contact_origin=origin, should_stop=lambda: stopped[0],
            resume_verification=args.resume_verification, resume_sha256=args.resume_sha256,
            use_frozen_directories=args.use_frozen_directories)
        print(json.dumps({k: result[k] for k in ('status', 'expected_materials', 'stable_materials',
              'changed_materials', 'incomplete_materials', 'completed_rounds',
              'requests', 'bytes_received', 'model_calls', 'parsing_acceptance')}, ensure_ascii=False))
        return 0 if result['status'] == 'completed' else 2
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__, 'message': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
