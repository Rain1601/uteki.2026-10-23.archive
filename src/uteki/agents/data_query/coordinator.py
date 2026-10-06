"""Shared company preparation/query lifecycle; CLI is only an adapter."""
import asyncio
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import threading

from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.document_sources.company_acquisition import prepare_sources, _configuration
from uteki.infrastructure.research_data import company_materialization
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import contained
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import ArtifactStore
from .artifacts import write_new
from .autonomous import AutonomousDataAgent, AutonomousLimits


def _load(path):
    return json.loads(Path(path).read_text())


def _verify_manifest(root, expected=None):
    root = Path(root).resolve()
    path = root / 'manifest.json'
    if expected is not None and digest(path.read_bytes()) != expected:
        raise ValueError('manifest integrity mismatch')
    manifest = _load(path)
    for name, sha in manifest['files'].items():
        original = root / name
        if original.is_symlink() or any(p.is_symlink() for p in original.parents if p != root.parent):
            raise ValueError('manifest symlinks are not allowed')
        if digest(contained(root, name).read_bytes()) != sha:
            raise ValueError('manifest file integrity mismatch: ' + name)
    return manifest


def _dataset_ref(path):
    path = Path(path).resolve()
    manifest = _verify_manifest(path)
    return {'path': str(path), 'manifest_sha256': digest((path/'manifest.json').read_bytes()),
            'snapshot_id': manifest['snapshot_id'], 'source_count': len(_load(path/'sources.json'))}


def _seal(output, result):
    write_new(output/'result.json', result)
    write_new(output/'manifest.json', {'schema_version': 'company-agent-run-v1',
        'files': {str(p.relative_to(output)): digest(p.read_bytes())
                  for p in sorted(output.rglob('*')) if p.is_file()}})
    return result


def inspect_run(run, *, artifact_read=None):
    """Verify frozen files, then optionally read one registered query artifact."""
    root = Path(run).resolve()
    manifest = _verify_manifest(root)
    result = _load(root/'result.json')
    if result.get('dataset'):
        ref = result['dataset']
        dataset = _verify_manifest(ref['path'], ref['manifest_sha256'])
        if dataset['snapshot_id'] != ref['snapshot_id']:
            raise ValueError('dataset reference identity mismatch')
    report = {'status': 'verified', 'run': str(root), 'files_verified': len(manifest['files']), 'result': result}
    if artifact_read is not None:
        query = root/'query' if result.get('operation') == 'query' else root
        refs = _load(query/'artifact-index.json')
        report['artifact_page'] = ArtifactStore(query, refs=refs).read(artifact_read)
    return report


class CompanyDataCoordinator:
    def __init__(self, workspace, *, fetch=None, materializer=materialize_sources, port_factory=QueryDataPort, sec_user_agent=None):
        self.workspace = Path(workspace).resolve()
        self.fetch, self.materializer, self.port_factory = fetch, materializer, port_factory
        self.sec_user_agent = sec_user_agent

    def _output(self, output):
        output = Path(output).resolve()
        if output == self.workspace or any(output.is_relative_to(self.workspace/name) for name in ('sources', 'source-runs')):
            raise ValueError('run output must be separate from frozen source storage')
        output.mkdir(parents=True, exist_ok=False)
        return output

    @staticmethod
    def _stop(should_stop):
        if should_stop and should_stop():
            raise company_materialization.MaterializationCancelled('operation_cancelled')

    @staticmethod
    def _merge(old, new, *, refresh=False):
        if old['company'] != new['company']:
            raise ValueError('acquisition company identity changed')
        if old['scope']['source_policy'] != new['scope']['source_policy']:
            raise ValueError('acquisition source policy changed')
        by_id = {d['source_id']: d for d in old['documents']}
        if refresh and new['scope'].get('updates_window'):
            window = new['scope']['updates_window']
            by_id = {sid: d for sid, d in by_id.items() if d.get('role') in ('filing', 'filing_attachment')
                     or (d.get('published_at') and window['start'] <= d['published_at'] <= window['end'])}
        for doc in new['documents']:
            if doc['source_id'] in by_id and doc['content_sha256'] != by_id[doc['source_id']]['content_sha256']:
                raise ValueError('source identity reused for different bytes')
            by_id[doc['source_id']] = doc
        gaps = list(old['gaps'])
        gaps.extend(gap for gap in new['gaps'] if gap not in gaps)
        return {**new, 'documents': list(by_id.values()), 'gaps': gaps,
                'parent_run_ids': [old['run_id'], new['run_id']]}

    @staticmethod
    def _materialization_key(source_run):
        # Timestamp/request logs are deliberately excluded; content and parsing
        # semantics determine reuse, while the new acquisition record is retained.
        fields = ('source_id', 'content_sha256', 'source_url', 'form', 'period_end',
                  'filed_at', 'published_at', 'mime_type', 'status', 'as_of_eligible')
        return digest({'company': source_run['company'],
            'documents': sorted(({k: d.get(k) for k in fields} for d in source_run['documents']), key=lambda d: d['source_id']),
            'implementation': company_materialization.implementation_fingerprint()})

    def prepare(self, config, *, output, previous=None, should_stop=None):
        config = deepcopy(config)
        input_config = deepcopy(config)
        if self.sec_user_agent is not None:
            config['sec_user_agent'] = self.sec_user_agent
        _configuration(config)  # Reject missing identity/policy before any I/O.
        prior = inspect_run(previous)['result'] if previous else None
        if prior:
            target = Path(output).resolve()
            protected = [Path(previous).resolve()]
            if prior.get('dataset'):
                protected.append(Path(prior['dataset']['path']).resolve())
            if any(target.is_relative_to(path) for path in protected):
                raise ValueError('refresh output must be outside previous frozen runs and datasets')
            old_config = _load(Path(previous)/'source-config.json')
            for field in ('symbol', 'cik', 'market', 'source_policy', 'filing_selection', 'document_validation'):
                if old_config.get(field) != config.get(field):
                    raise ValueError('refresh cannot change company or source selection policy')
            if date.fromisoformat(config['as_of']) < date.fromisoformat(old_config['as_of']):
                raise ValueError('refresh cutoff cannot move backwards')
        output = self._output(output)
        write_new(output/'source-config.input.json', input_config)
        write_new(output/'source-config.json', config)
        result = {'schema_version': 'company-agent-result-v1', 'operation': 'refresh' if prior else 'prepare',
                  'status': 'unavailable', 'dataset': None, 'gaps': [], 'model_calls': 0,
                  'workspace': str(self.workspace), 'previous_run': str(Path(previous).resolve()) if previous else None}
        try:
            self._stop(should_stop)
            source = prepare_sources(config, self.workspace, fetch=self.fetch, should_stop=should_stop)
            write_new(output/'acquisition.json', source)
            result['acquisition'] = {'path': 'acquisition.json', 'status': source['status'], 'requests': source['requests']}
            result['gaps'] = list(source['gaps'])
            self._stop(should_stop)
            if not source['company']:
                return _seal(output, result)
            if prior and prior.get('dataset'):
                source = self._merge(_load(Path(previous)/'source-run.json'), source, refresh=True)
            write_new(output/'source-run.json', source)
            key = self._materialization_key(source)
            if prior and prior.get('dataset') and prior.get('materialization_key') == key:
                result.update(dataset=prior['dataset'], materialization='reused')
                manifest = _verify_manifest(prior['dataset']['path'], prior['dataset']['manifest_sha256'])
                result['stage_coverage'] = manifest.get('stage_coverage', {})
                result['gaps'] = [*source['gaps'], *[gap for gap in manifest['gaps'] if gap not in source['gaps']]]
            elif source['documents']:
                manifest = self.materializer(source, self.workspace, output/'dataset', should_stop=should_stop)
                result.update(dataset=_dataset_ref(output/'dataset'), materialization='created')
                result['gaps'] = manifest['gaps']
                result['stage_coverage'] = manifest.get('stage_coverage', {})
            self._stop(should_stop)
            result['materialization_key'] = key
            if result.get('dataset') and result['dataset']['source_count']:
                result['status'] = 'prepared_with_gaps' if result['gaps'] else 'prepared'
        except company_materialization.MaterializationCancelled:
            result.update(status='cancelled', stop_reason='cancelled')
        except Exception as error:
            result.update(status='failed', stop_reason=type(error).__name__)
            result['gaps'].append({'layer': 'preparation', 'reason': str(error)[:500]})
        return _seal(output, result)

    def refresh(self, config, *, previous, output, should_stop=None):
        return self.prepare(config, previous=previous, output=output, should_stop=should_stop)

    def reprocess(self, previous, *, output, should_stop=None):
        """Prepare a new dataset from a verified frozen acquisition, without HTTP."""
        previous = Path(previous).resolve()
        prior = inspect_run(previous)['result']
        if prior.get('operation') not in {'prepare', 'refresh'}:
            raise ValueError('reprocessing requires a preparation run')
        if Path(prior['workspace']).resolve() != self.workspace:
            raise ValueError('reprocessing requires the original source workspace')
        target = Path(output).resolve()
        protected = [previous]
        if prior.get('dataset'):
            protected.append(Path(prior['dataset']['path']).resolve())
        if any(target.is_relative_to(path) for path in protected):
            raise ValueError('reprocessing output must be outside frozen runs and datasets')
        source = _load(previous/'source-run.json')
        output = self._output(output)
        for name in ('source-config.input.json', 'source-config.json', 'source-run.json'):
            write_new(output/name, _load(previous/name))
        result = {'schema_version': 'company-agent-result-v1', 'operation': 'prepare',
            'status': 'unavailable', 'dataset': None, 'gaps': list(source['gaps']), 'model_calls': 0,
            'workspace': str(self.workspace), 'previous_run': str(previous),
            'acquisition': {'mode': 'reused_frozen', 'requests': 0,
                'origin_run': str(previous), 'origin_manifest_sha256': digest((previous/'manifest.json').read_bytes())}}
        try:
            self._stop(should_stop)
            manifest = self.materializer(source, self.workspace, output/'dataset', should_stop=should_stop)
            result.update(dataset=_dataset_ref(output/'dataset'), materialization='created',
                          materialization_key=self._materialization_key(source), gaps=manifest['gaps'],
                          stage_coverage=manifest.get('stage_coverage', {}))
            if manifest['source_count']:
                result['status'] = 'prepared_with_gaps' if manifest['gaps'] else 'prepared'
        except company_materialization.MaterializationCancelled:
            result.update(status='cancelled', stop_reason='cancelled')
        except Exception as error:
            result.update(status='failed', stop_reason=type(error).__name__)
            result['gaps'].append({'layer': 'preparation', 'reason': str(error)[:500]})
        return _seal(output, result)

    @staticmethod
    async def _drain(task):
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
            except Exception:
                break
        return task.result(), interrupted

    @staticmethod
    async def _worker(function, *args, **kwargs):
        stop = threading.Event()
        task = asyncio.create_task(asyncio.to_thread(function, *args, should_stop=stop.is_set, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            stop.set()
            # Drain the worker before sealing the run. It cannot publish late
            # success or hold a port after the caller has observed cancellation.
            try:
                await CompanyDataCoordinator._drain(task)
            except Exception:
                pass
            raise

    def _acquire_stage(self, config, output, *, should_stop):
        report = prepare_sources(config, self.workspace, fetch=self.fetch, should_stop=should_stop)
        # This runs inside the drained worker, including on cancellation.
        write_new(output/'source-run.json', report)
        return report

    @staticmethod
    def _scope(port, config, include_candidates):
        companies = {s['company_id'] for s in port.sources}
        if not companies or not port.sources:
            raise ValueError('no queryable sources; cannot invent an execution scope')
        scope = ExecutionScope(snapshot_id=port.snapshot_id, company_ids=tuple(sorted(companies)),
            source_snapshot_ids=tuple(s['source_snapshot_id'] for s in port.sources),
            source_policy_id=port.manifest['source_policy_id'], knowledge_cutoff=config['as_of'],
            include_candidates=include_candidates)
        port.scoped(scope).discover_data()
        return scope

    async def query(self, request, *, output, planner=None, model_config=None, credential_root=None,
                    worker_planner=None, worker_model_config=None, extractor_model_config=None,
                    method_root=None, financial_extractor=None):
        request = CompanyQueryInput.model_validate(request)
        limits = AutonomousLimits.model_validate(request.limits)
        if (planner is None) == (model_config is None):
            raise ValueError('select exactly one injected planner or explicit model_config')
        if planner is not None and getattr(planner, 'plan_origin', None) != 'scripted_fixture':
            raise ValueError('injected planners are scripted fixtures; model execution uses the metered adapter')
        if worker_planner is not None and worker_model_config is not None:
            raise ValueError('select at most one injected worker or explicit worker_model_config')
        if worker_planner is not None and getattr(worker_planner, 'plan_origin', None) != 'scripted_fixture':
            raise ValueError('injected workers are scripted fixtures; model execution uses the metered adapter')
        if worker_planner is not None and planner is None:
            raise ValueError('an injected worker requires an injected fixture planner')
        if worker_model_config is not None:
            if model_config is None:
                raise ValueError('worker_model_config requires a main model_config')
            self._validate_shared_model_configs(model_config, worker_model_config)
        if request.financial_tasks:
            if method_root is None or extractor_model_config is None or credential_root is None:
                raise ValueError('financial tasks require explicit method-root, extractor model config and credentials-root')
            self._validate_model_config(extractor_model_config)
            if model_config is not None:
                if financial_extractor is not None:
                    raise ValueError('injected financial extractor belongs only to scripted fixtures')
                self._validate_shared_model_configs(model_config, extractor_model_config)
            elif financial_extractor is None:
                raise ValueError('scripted financial tasks require an explicit fixture extractor')
        elif any(value is not None for value in (extractor_model_config, method_root, financial_extractor)):
            raise ValueError('financial execution configuration requires registered financial tasks')
        target = Path(output).resolve()
        protected = [Path(request.dataset).resolve()] if request.dataset else []
        prepared_result = None
        if request.prepared_run:
            prepared = Path(request.prepared_run).resolve()
            prepared_result = inspect_run(prepared)['result']
            protected.append(prepared)
            if prepared_result.get('dataset'):
                protected.append(Path(prepared_result['dataset']['path']).resolve())
        if any(target.is_relative_to(path) for path in protected):
            raise ValueError('query output must be outside existing frozen datasets and runs')
        if model_config is not None:
            self._validate_model_config(model_config)
            ledger = Path(model_config['budget_ledger']).resolve()
            if any(ledger.is_relative_to(path) for path in [target, *protected]):
                raise ValueError('shared model ledger must be outside frozen runs and datasets')
        if extractor_model_config is not None:
            ledger = Path(extractor_model_config['budget_ledger']).resolve()
            if any(ledger.is_relative_to(path) for path in [target, *protected]):
                raise ValueError('extractor ledger must be outside frozen runs and datasets')
        if request.company_config is not None:
            checked_config = deepcopy(request.company_config)
            if self.sec_user_agent is not None:
                checked_config['sec_user_agent'] = self.sec_user_agent
            _configuration(checked_config)
        output = self._output(output)
        write_new(output/'request.json', request.model_dump(mode='json'))
        if model_config is not None:
            write_new(output/'model-config.input.json', model_config)
        if worker_model_config is not None:
            write_new(output/'worker-model-config.input.json', worker_model_config)
        if extractor_model_config is not None:
            write_new(output/'extractor-model-config.input.json', extractor_model_config)
        owners, acquired = [], {}
        source_history, dataset_cache = {}, {}
        result = {'schema_version': 'company-agent-result-v1', 'operation': 'query', 'status': 'unavailable',
                  'dataset': None, 'query_run': None, 'gaps': [], 'workspace': str(self.workspace)}
        source, config, active_dataset = None, None, None
        managed_planner = None
        managed_worker = None
        cancelled = None
        try:
            if request.dataset:
                active_dataset = Path(request.dataset).resolve()
                if output.is_relative_to(active_dataset): raise ValueError('query output is inside frozen dataset')
                owner = self.port_factory(active_dataset); owners.append(owner)
                scope = request.scope
                owner.scoped(scope).discover_data()
            else:
                prepared = Path(request.prepared_run).resolve() if request.prepared_run else output/'prepare'
                if request.prepared_run:
                    assert prepared_result is not None
                else:
                    prepared_result = await self._worker(self.prepare, request.company_config, output=prepared)
                if prepared_result['status'] not in {'prepared', 'prepared_with_gaps'} or not prepared_result.get('dataset') or not prepared_result['dataset']['source_count']:
                    result.update(status=prepared_result['status'], gaps=prepared_result['gaps'], stop_reason='preparation_unavailable')
                    return _seal(output, result)
                active_dataset = Path(prepared_result['dataset']['path'])
                config, source = _load(prepared/'source-config.json'), _load(prepared/'source-run.json')
                owner = self.port_factory(active_dataset); owners.append(owner)
                scope = self._scope(owner, config, request.include_candidates)
            result['dataset'] = _dataset_ref(active_dataset)
            write_new(output/'scope.json', scope.model_dump(mode='json'))
            if source:
                source_history[scope.snapshot_id] = source
                dataset_cache[self._materialization_key(source)] = owner

            async def acquire(arguments, *, scope, output):
                if set(arguments) != {'filing_selection'}:
                    raise ValueError('acquire requires only explicit filing_selection')
                next_config = {**config, 'filing_selection': arguments['filing_selection']}
                report = await self._worker(self._acquire_stage, next_config, output)
                if report['company'] != source['company'] or not report['documents'] or report['status'] == 'cancelled':
                    return {'status': 'gap', 'reason': 'acquisition_unavailable', 'details': report['gaps']}
                run_id = report['run_id']; acquired[run_id] = report
                return {'status': 'acquired', 'source_run_id': run_id,
                        'sources': [{'source_id': d['source_id'], 'sha256': d['content_sha256']} for d in report['documents']],
                        'gaps': report['gaps'], 'artifacts': [str(output/'source-run.json')]}

            async def materialize(arguments, *, scope, output):
                if set(arguments) != {'source_run_id'} or arguments['source_run_id'] not in acquired:
                    raise ValueError('materialize requires a source_run_id acquired during this query')
                combined = self._merge(source_history[scope.snapshot_id], acquired[arguments['source_run_id']])
                output.mkdir(parents=True, exist_ok=False)
                write_new(output/'source-run.json', combined)
                key = self._materialization_key(combined)
                if key in dataset_cache:
                    cached = dataset_cache[key]
                    _verify_manifest(cached.dataset)
                    return {'status': 'materialized', 'scope': self._scope(cached, config, scope.include_candidates).model_dump(mode='json'),
                            'port': cached, 'artifacts': [str(cached.dataset/'manifest.json')]}
                manifest = await self._worker(self.materializer, combined, self.workspace, output/'dataset')
                target_ids = {d['source_id'] for d in acquired[arguments['source_run_id']]['documents']
                              if d.get('as_of_eligible') and d.get('status') == 'frozen'}
                indexed = {s['source_snapshot_id'] for s in _load(output/'dataset/sources.json')}
                if not target_ids <= indexed or not set(scope.source_snapshot_ids) <= indexed:
                    return {'status': 'gap', 'reason': 'materialization_incomplete', 'details': manifest['gaps']}
                next_owner = self.port_factory(output/'dataset'); owners.append(next_owner)
                next_scope = self._scope(next_owner, config, scope.include_candidates)
                AutonomousDataAgent._new_scope(request.scope or initial_scope, scope, next_scope)
                source_history[next_scope.snapshot_id] = combined
                dataset_cache[key] = next_owner
                # Host commits the active scope only after its own validation.
                return {'status': 'materialized', 'scope': next_scope.model_dump(mode='json'), 'port': next_owner,
                        'artifacts': [str(output/'dataset/manifest.json')]}

            financial_gateway = None
            if request.financial_tasks:
                from uteki.infrastructure.research_data.financial_tasks import FinancialTaskGateway
                financial_gateway = FinancialTaskGateway(active_dataset, scope,
                    [task.model_dump(mode='json') for task in request.financial_tasks],
                    method_root=method_root, output=output,
                    model_config=extractor_model_config, credentials_root=credential_root,
                    model_call=financial_extractor)
            initial_scope = scope
            if model_config is not None:
                managed_planner = self._planner(model_config, output/'model', credential_root)
                planner = managed_planner
            if worker_model_config is not None:
                managed_worker = self._planner(worker_model_config, output/'worker-model', credential_root, role='worker')
                worker_planner = managed_worker
            preparation = None if source is None else {'filing_catalog': source.get('filing_catalog', []),
                'acquisition_gaps': source['gaps'], 'callbacks': {
                    'acquire': {'filing_selection': {'mode': 'annual_filing_period',
                        'annual_form': '10-K or 20-F; copy the base form from the selected filing_catalog item',
                        'report_period_end': 'ISO date from filing_catalog'}},
                    'materialize': {'source_run_id': 'ID returned by acquire'}}}
            agent = AutonomousDataAgent(owner, planner, limits=limits, worker_planner=worker_planner,
                acquire=acquire if source else None, materialize=materialize if source else None, preparation=preparation,
                financial_extract=financial_gateway.extract if financial_gateway else None,
                financial_tasks=financial_gateway.catalog if financial_gateway else None)
            query_result = await agent.run({'question': request.question, 'scope': scope.model_dump(mode='json')}, output=output/'query')
            final_owner = next(p for p in owners if p.snapshot_id == query_result['active_scope']['snapshot_id'])
            result.update(status=query_result['status'], stop_reason=query_result['stop_reason'],
                query_run='query', dataset=_dataset_ref(final_owner.dataset), gaps=query_result['gaps'],
                plan_origin=query_result['plan_origin'], active_scope=query_result['active_scope'])
        except asyncio.CancelledError:
            result.update(status='cancelled', stop_reason='cancelled', query_run='query' if (output/'query').exists() else None)
            cancelled = asyncio.CancelledError()
        except Exception as error:
            result.update(status='failed', stop_reason=type(error).__name__)
            result['gaps'].append({'layer': 'coordination', 'reason': str(error)[:500]})
        finally:
            for port in reversed(owners):
                try: port.close()
                except Exception as error:
                    result.update(status='failed', stop_reason='port_close_failed')
                    result['gaps'].append({'layer': 'cleanup', 'reason': type(error).__name__})
            for role, managed, usage_file in (('planner', managed_planner, 'model-usage.json'),
                                               ('worker', managed_worker, 'worker-model-usage.json')):
                if managed is None:
                    continue
                try:
                    _, interrupted = await self._drain(asyncio.create_task(managed.aclose()))
                    if interrupted:
                        cancelled = asyncio.CancelledError()
                        result.update(status='cancelled', stop_reason='cancelled')
                except Exception as error:
                    result.update(status='failed', stop_reason='model_close_failed')
                    result['gaps'].append({'layer': 'cleanup', 'role': role, 'reason': type(error).__name__})
                try:
                    write_new(output/usage_file, managed.snapshot_usage())
                except Exception as error:
                    result.update(status='failed', stop_reason='model_accounting_snapshot_failed')
                    result['gaps'].append({'layer': 'accounting', 'role': role, 'reason': type(error).__name__})
        _seal(output, result)
        if cancelled: raise cancelled
        return result

    @staticmethod
    def _validate_model_config(config):
        required = {'provider', 'model', 'budget_ledger', 'budget_usd', 'budget_policy', 'max_requests_total'}
        allowed = required | {'max_tokens', 'request_timeout', 'max_retries', 'reasoning_effort'}
        if not required <= set(config) or set(config) - allowed or config['budget_policy'] not in {'enforced', 'record_only'}:
            raise ValueError('explicit model, shared ledger and budget policy are required')
        if any(not isinstance(config[key], str) or not config[key].strip() for key in ('provider', 'model', 'budget_ledger')):
            raise ValueError('provider/model/ledger must be nonempty')
        if config.get('reasoning_effort') is not None and (not isinstance(config['reasoning_effort'], str) or config['provider'] != 'deepseek'
                or config['reasoning_effort'] not in {'none', 'low', 'high', 'max'}):
            raise ValueError('Explicit reasoning effort is supported only for DeepSeek: none, low, high, max')
        if config['max_requests_total'] is not None and (type(config['max_requests_total']) is not int or config['max_requests_total'] < 1):
            raise ValueError('positive shared request allowance or explicit None required')
        from decimal import Decimal, InvalidOperation
        if config['budget_usd'] is None:
            if config['budget_policy'] != 'record_only':
                raise ValueError('an unlimited USD budget requires record_only policy')
            return
        try:
            limit = Decimal(str(config['budget_usd']))
            if not limit.is_finite() or limit <= 0: raise ValueError('positive budget_usd reference required')
        except InvalidOperation as error:
            raise ValueError('positive budget_usd reference required') from error

    @staticmethod
    def _validate_shared_model_configs(config, worker_config):
        from decimal import Decimal
        CompanyDataCoordinator._validate_model_config(config)
        CompanyDataCoordinator._validate_model_config(worker_config)
        def amount(value):
            return None if value is None else Decimal(str(value))
        if (Path(config['budget_ledger']).resolve() != Path(worker_config['budget_ledger']).resolve()
                or amount(config['budget_usd']) != amount(worker_config['budget_usd'])
                or any(config[key] != worker_config[key] for key in ('budget_policy', 'max_requests_total'))):
            raise ValueError('planner and worker must share the same budget ledger, USD limit, policy and request allowance')

    @staticmethod
    def _planner(config, output, credential_root, *, role='planner'):
        from uteki.agents.runtime.run_budget import RunBudget
        from .autonomous_model import SdkAutonomousPlanner
        CompanyDataCoordinator._validate_model_config(config)
        budget = RunBudget(config['budget_ledger'], config['budget_usd'], enforce=config['budget_policy'] == 'enforced')
        return SdkAutonomousPlanner(config['provider'], config['model'], budget=budget,
            max_requests_total=config['max_requests_total'], output=output, credentials_root=credential_root,
            max_tokens=config.get('max_tokens', 4096), request_timeout=config.get('request_timeout', 60),
            max_retries=config.get('max_retries', 0), role=role, reasoning_effort=config.get('reasoning_effort'))
