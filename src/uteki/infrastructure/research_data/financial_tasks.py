"""Host-registered, immutable financial extraction tasks for the Data Agent."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re

from uteki.agents.data_query.artifacts import write_new
from uteki.domain.research_data.execution_scope import ExecutionScope
from .direct_extraction import build_extraction_packet
from .extraction_batches import load_task_method, run_extraction_batch, table_batch_catalog
from .financial_records import digest


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _verify_files(root, expected):
    """Check the pinned registration or completed run before using it again."""
    manifest = root / 'manifest.json'
    if manifest.is_symlink() or digest(manifest.read_bytes()) != expected:
        raise ValueError('financial task artifact manifest integrity mismatch')
    for name, sha in _json(manifest)['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('financial task artifact path escapes its root')
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError('financial task artifacts must not contain symlinks')
        if not path.is_file() or digest(path.read_bytes()) != sha:
            raise ValueError('financial task artifact file integrity mismatch')


class FinancialTaskGateway:
    """Expose only explicitly registered batches; never adopt their candidates."""

    def __init__(self, dataset, scope, tasks, *, method_root, output, model_config,
                 credentials_root, model_call=None):
        if isinstance(model_config, dict) and 'output_capacity_recovery' in model_config:
            raise ValueError('financial extractor does not support output_capacity_recovery')
        self.dataset = Path(dataset).resolve()
        self.scope = ExecutionScope.model_validate(scope)
        self.output = Path(output).resolve()
        if self.output == self.dataset or self.output.is_relative_to(self.dataset):
            raise ValueError('financial task output must be outside the frozen dataset')
        if not isinstance(tasks, list) or not tasks:
            raise ValueError('an explicit nonempty financial task list is required')
        if (not isinstance(model_config, dict)
                or model_config.get('budget_policy') not in {'enforced', 'record_only'}):
            raise ValueError('explicit financial extraction budget_policy is required')
        if (not all(isinstance(model_config.get(k), str) and model_config[k].strip()
                    for k in ('provider', 'model', 'budget_ledger'))
                or 'budget_usd' not in model_config or 'max_requests_total' not in model_config
                or credentials_root is None):
            raise ValueError('explicit financial extraction model, shared ledger and credentials are required')
        if ('max_retries' in model_config
                and (type(model_config['max_retries']) is not int or model_config['max_retries'] != 0)):
            raise ValueError('financial extraction supports only max_retries=0; automatic retries are unsupported')
        if type(model_config.get('allow_unknown_reservations', False)) is not bool:
            raise ValueError('allow_unknown_reservations must be a boolean')
        if model_config.get('allow_unknown_reservations', False):
            raise ValueError('financial extraction does not support allow_unknown_reservations=True')
        self.model_config = deepcopy(model_config)
        enforced = model_config['budget_policy'] == 'enforced'
        if 'enforce_cost' in model_config and model_config['enforce_cost'] is not enforced:
            raise ValueError('enforce_cost conflicts with explicit budget_policy')
        self.model_config['enforce_cost'] = enforced
        ledger = Path(model_config['budget_ledger']).resolve()
        if ledger.is_relative_to(self.output) or ledger.is_relative_to(self.dataset):
            raise ValueError('shared ledger must be outside frozen task output and dataset')
        self.credentials_root, self.model_call = credentials_root, model_call
        self._lock = asyncio.Lock()
        self._tasks, self._receipts, self._started = {}, {}, {}
        self._catalog = []
        manifest = _json(self.dataset / 'manifest.json')
        manifest_sha = digest((self.dataset / 'manifest.json').read_bytes())
        if (self.scope.snapshot_id != manifest['snapshot_id']
                or self.scope.source_policy_id != manifest['source_policy_id']):
            raise ValueError('financial task execution snapshot or source policy mismatch')
        sources = _json(self.dataset / 'sources.json')
        selected = []
        for sid in self.scope.source_snapshot_ids:
            matches = [source for source in sources if source['source_snapshot_id'] == sid]
            if len(matches) != 1 or matches[0]['company_id'] not in self.scope.company_ids:
                raise ValueError('financial task execution source is unknown or outside company scope')
            if date.fromisoformat(matches[0]['available_at']) > self.scope.knowledge_cutoff:
                raise ValueError('financial task execution source is unavailable at cutoff')
            selected.append(matches[0])
        if {s['company_id'] for s in selected} != set(self.scope.company_ids):
            raise ValueError('each execution company requires an explicitly selected source')

        # Validate every registration before writing any task. Shared asset paths
        # must have identical bytes, including across different task profiles.
        assets_seen, prepared = {}, []
        for registration in tasks:
            fields = {'task_id', 'job', 'task_profile', 'task_profile_sha256', 'max_new_batches'}
            if not isinstance(registration, dict) or set(registration) != fields:
                raise ValueError('financial task registration fields are incomplete or unsupported')
            task_id = registration['task_id']
            if (not isinstance(task_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', task_id)
                    or any(item['task_id'] == task_id for item in prepared)):
                raise ValueError('financial task requires a unique safe task_id')
            maximum = registration['max_new_batches']
            if type(maximum) is not int or maximum < 1:
                raise ValueError('financial task max_new_batches must be a positive integer')
            job = deepcopy(registration['job'])
            if not isinstance(job, dict) or 'prompt' in job:
                raise ValueError('registered financial job must not contain an inline prompt')
            if (job.get('company_id') not in self.scope.company_ids
                    or job.get('source_snapshot_id') not in self.scope.source_snapshot_ids
                    or job.get('as_of') != str(self.scope.knowledge_cutoff)
                    or job.get('dataset_manifest_sha256') != manifest_sha):
                raise ValueError('financial job company/source/cutoff/manifest differs from execution scope')
            packet = build_extraction_packet(self.dataset, job)
            if job.get('source_sha256', packet['source']['source_sha256']) != packet['source']['source_sha256']:
                raise ValueError('financial job source hash mismatch')
            profile_path = registration['task_profile']
            if (not isinstance(profile_path, str) or Path(profile_path).is_absolute()
                    or '..' in Path(profile_path).parts):
                raise ValueError('task_profile must be relative to method-root')
            default = load_task_method(profile_path, method_root, task_type=job.get('task_type'))
            profile = default['task_profile']
            if profile['sha256'] != registration['task_profile_sha256']:
                raise ValueError('registered task profile hash mismatch')
            snapshots = {}
            assets = {profile['path']: profile['text'].encode('utf-8')}
            for entry in profile['profile']['allowed_methods']:
                snapshot = load_task_method(profile_path, method_root, task_type=job['task_type'], method_id=entry['method_id'])
                if snapshot['task_profile']['sha256'] != profile['sha256']:
                    raise ValueError('task profile changed while registering allowed methods')
                if snapshot['method']['batching'] != default['method']['batching']:
                    raise ValueError('allowed methods must share one batch catalog configuration')
                if packet['source']['form'] not in snapshot['method']['supported_forms']:
                    raise ValueError('source form is unsupported by an allowed task method')
                snapshots[entry['method_id']] = snapshot
                for asset in [snapshot['method_file'], *snapshot['assets'].values()]:
                    name, data = str(Path(asset['path'])), asset['text'].encode('utf-8')
                    if name in assets and assets[name] != data:
                        raise ValueError('shared method asset path has conflicting contents')
                    assets[name] = data
            for name, data in assets.items():
                if name in assets_seen and assets_seen[name] != data:
                    raise ValueError('shared method asset path has conflicting contents')
                assets_seen[name] = data
            batches = table_batch_catalog(packet, neighbor_radius=default['method']['batching']['neighbor_radius'])
            blocks = {block['block_id']: block for block in packet['blocks']}
            catalog = {'task_id': task_id, 'task_type': job['task_type'], 'company_id': packet['company_id'],
                'source_snapshot_id': packet['source']['source_snapshot_id'], 'source_sha256': packet['source']['source_sha256'],
                'dataset_manifest_sha256': manifest_sha, 'catalog_id': batches['catalog_id'], 'task': job['task'],
                'default_method_id': profile['profile']['default_method_id'], 'allowed_method_ids': list(snapshots),
                'max_new_batches': maximum, 'batches': [{'batch_index': batch['batch_index'],
                    'table_block_id': batch['table_block_id'], 'source_excerpt': blocks[batch['table_block_id']]['text'][:600],
                    'block_ids': batch['block_ids'], 'status': 'pending'} for batch in batches['batches']],
                'limits': batches['limits']}
            prepared.append({'task_id': task_id, 'job': job, 'task_profile': profile_path,
                'snapshots': snapshots, 'assets': assets, 'catalog': catalog, 'max_new_batches': maximum})

        registered = self.output / 'registered-financial'
        if registered.exists():
            raise ValueError('financial task registration output must be new')
        for item in prepared:
            root = registered / item['task_id']
            root.mkdir(parents=True, exist_ok=False)
            frozen = root / 'method-root'
            for name, data in item.pop('assets').items():
                path = frozen / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(data)
            write_new(root / 'job.json', item['job'])
            write_new(root / 'catalog.json', item['catalog'])
            write_new(root / 'scope.json', self.scope.model_dump(mode='json'))
            write_new(root / 'manifest.json', {'files': {str(path.relative_to(root)): digest(path.read_bytes())
                for path in sorted(root.rglob('*')) if path.is_file()}})
            item.update(root=root, method_root=frozen, manifest_sha256=digest((root / 'manifest.json').read_bytes()))
            self._tasks[item['task_id']] = item
            self._started[item['task_id']] = 0
            self._catalog.append(item['catalog'])

    @property
    def catalog(self):
        return deepcopy(self._catalog)

    async def extract(self, arguments, *, scope, output, observation_context=None):
        if ExecutionScope.model_validate(scope) != self.scope:
            raise ValueError('financial extraction active scope must exactly match its registered execution scope')
        if (not isinstance(arguments, dict) or not {'task_id', 'batch_index'} <= set(arguments)
                or set(arguments) - {'task_id', 'batch_index', 'method_id'}):
            raise ValueError('financial extraction accepts only task_id, batch_index and optional method_id')
        task_id, batch_index = arguments['task_id'], arguments['batch_index']
        if not isinstance(task_id, str) or task_id not in self._tasks:
            raise ValueError('unknown registered financial task')
        item = self._tasks[task_id]
        if type(batch_index) is not int or not 0 <= batch_index < len(item['catalog']['batches']):
            raise ValueError('unknown registered financial batch')
        method_id = arguments.get('method_id')
        selected = item['catalog']['default_method_id'] if method_id is None else method_id
        if not isinstance(selected, str) or selected not in item['snapshots']:
            raise ValueError('method is not allowed for the registered task')
        method_sha = item['snapshots'][selected]['method_file']['sha256']
        key = (task_id, batch_index, method_sha)
        async with self._lock:
            _verify_files(item['root'], item['manifest_sha256'])
            if key in self._receipts:
                receipt = self._receipts[key]
                _verify_files(Path(receipt['run']['path']), receipt['run']['manifest_sha256'])
                if observation_context:
                    observation_context.guard()
                    observation_context.publish(Path(receipt['run']['path'])/'manifest.json',
                        kind='reused_extraction_manifest', reused=True)
                return deepcopy(receipt)
            if self._started[task_id] >= item['max_new_batches']:
                raise ValueError('registered financial task new-batch allowance exhausted')
            output = Path(output).resolve()
            if (not output.is_relative_to(self.output) or output == self.output
                    or output.is_relative_to(self.output / 'registered-financial') or output.exists()):
                raise ValueError('financial batch output must be new and inside its execution output')
            self._started[task_id] += 1
            # A failed model call consumes the task allowance and is sealed by
            # run_extraction_batch. It never creates a reusable success receipt.
            try:
                result = await run_extraction_batch(self.dataset, deepcopy(item['job']), output,
                    task_profile=item['task_profile'], method_root=item['method_root'], batch_index=batch_index,
                    method_id=method_id, model_config=deepcopy(self.model_config), credentials_root=self.credentials_root,
                    model_call=self.model_call, observation_context=observation_context)
            except BaseException as error:
                # Batch input validation can fail before the runner creates its
                # directory. Retain that attempted execution without altering a
                # failure manifest already written by the runner.
                if not (output / 'manifest.json').exists():
                    output.mkdir(parents=True, exist_ok=True)
                    write_new(output / 'gateway-failure.json', {'status': 'failed', 'task_id': task_id,
                        'batch_index': batch_index, 'method_id': selected, 'method_sha256': method_sha,
                        'error_type': type(error).__name__, 'candidate_only': True,
                        'adoption': 'unchanged_candidate', 'semantic_acceptance': 'not_evaluated'})
                    write_new(output / 'manifest.json', {'files': {str(path.relative_to(output)): digest(path.read_bytes())
                        for path in sorted(output.rglob('*')) if path.is_file()}})
                raise
            if result.get('status') != 'candidate':
                raise ValueError('financial batch did not produce a candidate')
            extraction = _json(output / 'extraction-01/extraction.json')
            coverage = _json(output / 'coverage.json')
            receipt = {'status': 'candidate', 'task_id': task_id, 'batch_index': batch_index,
                'catalog_id': item['catalog']['catalog_id'], 'method_id': selected, 'method_sha256': method_sha,
                'run': {'path': str(output), 'manifest_sha256': digest((output / 'manifest.json').read_bytes())},
                'dataset': result['dataset'], **{name: result[name] for name in
                    ('raw_record_count', 'normalized_record_count', 'unresolved_count')},
                'gaps': list(extraction['gaps']) + item['catalog']['limits'] + [
                    f"Pending table batches: {coverage['pending_batch_indexes']}; "
                    f"unassigned parent blocks: {len(coverage['unassigned_parent_block_ids'])}."],
                'adoption': 'unchanged_candidate', 'semantic_acceptance': 'not_evaluated', 'candidate_only': True}
            receipt_path = self.output / 'financial-receipts' / (digest(key) + '.json')
            write_new(receipt_path, receipt)
            self._receipts[key] = deepcopy(receipt)
            return receipt
