"""Offline preparation/scope checks, separate from runtime and semantic gold."""
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained, save
from uteki.infrastructure.research_data.query_service import QueryDataPort, ScopedQueryDataPort


def audit(experiment, repository):
    e, root = Path(experiment).resolve(), Path(repository).resolve()
    config = json.loads((e / 'input-v1.json').read_bytes())
    preparation = e / 'preparation-v1'
    assert (preparation / 'input.json').read_bytes() == (e / 'input-v1.json').read_bytes()
    dataset = preparation / 'dataset'
    manifest = json.loads((dataset / 'manifest.json').read_bytes())
    for relative, sha in manifest['files'].items():
        assert digest(contained(dataset, relative).read_bytes()) == sha, relative
    sources = json.loads((dataset / 'sources.json').read_bytes())
    selected = {s['source_id']: s for a in config['acquisitions'] for s in a['sources']}
    assert {s['source_snapshot_id'] for s in sources} == set(selected)
    origin_checks = []
    for acquisition in config['acquisitions']:
        original = contained(root, acquisition['manifest'])
        assert digest(original.read_bytes()) == acquisition['manifest_sha256']
        documents = json.loads(original.read_bytes())['documents']
        for expected in acquisition['sources']:
            d = next(d for d in documents if d['source_id'] == expected['source_id'])
            s = next(s for s in sources if s['source_snapshot_id'] == d['source_id'])
            assert s['company_id'] == config['company_id']
            assert s['form'] == d['form'] == expected['form']
            assert s['period_end'] == d['period_end'] == expected['period_end']
            assert s['available_at'] == d['filed_at'] <= config['knowledge_cutoff']
            assert digest(contained(dataset, s['raw_file']).read_bytes()) == d['content_sha256']
            assert digest(contained(contained(root, acquisition['workspace']), d['path']).read_bytes()) == d['content_sha256']
            origin_checks.append({k: s[k] for k in ('source_snapshot_id', 'company_id', 'form', 'period_end',
                                                   'available_at', 'source_sha256')})
    scope_checks = []
    with QueryDataPort(dataset) as port:
        scope = {'snapshot_id': port.snapshot_id, 'company_ids': [config['company_id']],
                 'source_snapshot_ids': sorted(selected), 'source_policy_id': config['source_policy_id'],
                 'knowledge_cutoff': config['knowledge_cutoff'], 'include_candidates': True}
        mixed = ScopedQueryDataPort(port, scope)
        assert {s['source_snapshot_id'] for s in mixed.discover_data()['sources']} == set(selected)
        for source in sources:
            scoped = mixed.for_query_source(source['source_snapshot_id'])
            assert {s['source_snapshot_id'] for s in scoped.discover_data()['sources']} == {source['source_snapshot_id']}
            assert all(p['source_snapshot_id'] == source['source_snapshot_id'] for p in scoped.get_schema()['fiscal_periods'])
            excluded = next(s['source_snapshot_id'] for s in sources if s != source)
            try:
                scoped.for_query_source(excluded)
            except ValueError:
                pass
            else:
                raise AssertionError('narrowed scope accepted excluded source')
        scope_checks.append('each source pin narrows numeric/discovery scope; other sources rejected')
        latest = max(sources, key=lambda s: s['available_at'])
        prior_cutoff = (date.fromisoformat(latest['available_at']) - timedelta(days=1)).isoformat()
        early = ScopedQueryDataPort(port, {**scope, 'knowledge_cutoff': prior_cutoff})
        assert latest['source_snapshot_id'] not in {s['source_snapshot_id'] for s in early.discover_data()['sources']}
        assert early.outline_source({'source_snapshot_id': latest['source_snapshot_id']})['status'] == 'not_available_at_cutoff'
        try:
            early.for_query_source(latest['source_snapshot_id'])
        except ValueError:
            pass
        else:
            raise AssertionError('numeric source pin accepted post-cutoff source')
        scope_checks.append('post-cutoff source absent from discovery and rejected by body/numeric tools')
        for changes in ({'company_ids': ['sec-0000000001']}, {'company_ids': []},
                        {'source_snapshot_ids': ['unselected-source']}, {'source_policy_id': 'unknown-policy'}):
            try:
                ScopedQueryDataPort(port, {**scope, **changes})
            except ValueError:
                pass
            else:
                raise AssertionError('invalid scope accepted')
        scope_checks.append('missing/wrong company, unknown source/policy rejected; no fallback')
    module_spec = importlib.util.spec_from_file_location('e3_fixture_builder', e / 'build_preparation.py')
    builder = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(builder)
    invalid_inputs = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, mutate in (
            ('wrong_company', lambda c: c.update(company_id='sec-0000000001', cik='0000000001')),
            ('early_cutoff', lambda c: c.update(knowledge_cutoff='2025-05-31')),
            ('wrong_manifest_hash', lambda c: c['acquisitions'][0].update(manifest_sha256='0' * 64)),
            ('wrong_period', lambda c: c['acquisitions'][0]['sources'][0].update(period_end='2030-06-30')),
            ('missing_policy', lambda c: c.pop('source_policy')),
        ):
            candidate = json.loads(json.dumps(config)); mutate(candidate)
            path = tmp / (name + '.json'); save(path, candidate)
            target = tmp / name
            try:
                builder.build(path, repository=root, output=target)
            except (KeyError, ValueError):
                assert not target.exists()
            else:
                raise AssertionError('invalid fixture input accepted: ' + name)
            invalid_inputs.append(name)
    result = {'schema_version': 'e3-independent-preparation-audit-v1',
              'input_sha256': digest((e / 'input-v1.json').read_bytes()),
              'dataset_manifest_sha256': digest((dataset / 'manifest.json').read_bytes()),
              'original_identity_scope_checks': origin_checks, 'manifest_files_verified': len(manifest['files']),
              'scope_checks': scope_checks, 'invalid_inputs_rejected_before_output': invalid_inputs,
              'http_requests': 0, 'model_calls': 0, 'semantic_acceptance': 'not_evaluated',
              'revision_acceptance': 'not_evaluated', 'status': 'preparation_and_scope_checks_passed'}
    save(e / 'evaluation-only/preparation-audit-v1.json', result)
    return result


if __name__ == '__main__':
    print(json.dumps(audit(Path(__file__).resolve().parents[1], Path.cwd()), ensure_ascii=False))
