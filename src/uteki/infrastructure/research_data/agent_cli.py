"""Argument parsing only; company-agent behavior lives in its coordinator."""
import asyncio
import json
from pathlib import Path


def _company_arguments(action, *, allow_frozen=False):
    source = action.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', type=Path, help='versioned company source configuration')
    source.add_argument('--company', help='company name or symbol registered in the explicit catalog')
    if allow_frozen:
        source.add_argument('--from-run', type=Path, help='reprocess a frozen preparation without network')
        source.add_argument('--from-acquisition', type=Path, help='prepare explicitly selected frozen acquisition sources without network')
        action.add_argument('--acquisition-sha256', help='required SHA256 pin of the acquisition manifest bytes')
        action.add_argument('--source-id', action='append', dest='source_ids', help='exact frozen source ID to replay; repeat for each selection')
    action.add_argument('--company-catalog', type=Path, help='explicit registered-company catalog with pinned source profiles')


def _company_config(args):
    company = getattr(args, 'company', None)
    catalog = getattr(args, 'company_catalog', None)
    if (company is not None) != (catalog is not None):
        raise ValueError('--company and --company-catalog must be supplied together')
    if company is not None:
        from uteki.infrastructure.document_sources.company_registry import resolve_company_profile
        return resolve_company_profile(catalog, company)
    config = getattr(args, 'config', None)
    return json.loads(config.read_text()) if config else None


def register_agent_commands(commands):
    agent = commands.add_parser('agent', help='prepare/extract/query/refresh/inspect company research data')
    actions = agent.add_subparsers(dest='agent_action', required=True)
    business = actions.add_parser('business', help='system-selected original material to a business candidate; no section/excerpt arguments')
    for name in ('request', 'root', 'workspace', 'output', 'model-config', 'extractor-model-config',
                 'credentials-root', 'observation-root'):
        business.add_argument('--'+name, type=Path, required=True)
    business.add_argument('--sec-user-agent', help='SEC application/contact identity when acquiring sources')
    acquire = actions.add_parser('acquire', help='discover and download official filings without parsing or model calls')
    _company_arguments(acquire)
    acquire.add_argument('--workspace', type=Path, required=True, help='original files and immutable acquisition runs')
    acquire.add_argument('--sec-user-agent', help='application and contact identity, or UTEKI_SEC_USER_AGENT')
    acquire.add_argument('--settings-root', type=Path, default=Path.cwd(), help='directory containing private local .env settings')
    for name in ('prepare', 'refresh', 'query'):
        action = actions.add_parser(name)
        action.add_argument('--workspace', type=Path, required=True, help='immutable source store')
        action.add_argument('--output', type=Path, required=True, help='new run directory')
        action.add_argument('--sec-user-agent', help='explicit SEC contact identity, or UTEKI_SEC_USER_AGENT environment')
        action.add_argument('--settings-root', type=Path, default=Path.cwd(), help='directory containing private local .env settings')
        if name == 'query':
            action.add_argument('--observation-root', type=Path, help='explicit separate directory for live run events')
            action.add_argument('--request', type=Path, required=True, help='CompanyQueryInput JSON')
            action.add_argument('--model-config', type=Path, required=True, help='explicit provider/model/shared budget JSON')
            action.add_argument('--credentials-root', type=Path, default=Path.cwd())
            action.add_argument('--extractor-model-config', type=Path, help='explicit financial extractor model on the same shared ledger')
            action.add_argument('--method-root', type=Path, help='explicit root of registered financial task methods')
        elif name == 'prepare':
            _company_arguments(action, allow_frozen=True)
        else:
            _company_arguments(action)
        if name == 'refresh':
            action.add_argument('--previous', type=Path, required=True)
    inspect = actions.add_parser('inspect')
    inspect.add_argument('--run', type=Path, required=True)
    inspect.add_argument('--artifact-request', type=Path, help='registered ArtifactReadRequest JSON')
    extract = actions.add_parser('extract', help='direct candidate extraction from an explicit frozen source scope')
    for name in ('dataset', 'job', 'output', 'model-config'):
        extract.add_argument('--'+name, type=Path, required=True)
    extract.add_argument('--strategy', choices=('direct', 'structured', 'independent_multi_pass', 'langextract'), required=True)
    extract.add_argument('--credentials-root', type=Path, default=Path.cwd())
    extract.add_argument('--observation-root', type=Path, help='explicit separate directory for live run events')
    batch = actions.add_parser('extract-batch', help='run one table batch with a task-allowed, hash-pinned prompt and skill')
    for name in ('dataset', 'job', 'task-profile', 'method-root', 'model-config', 'credentials-root', 'output'):
        batch.add_argument('--'+name, type=Path, required=True)
    batch.add_argument('--method-id', help='explicit override within the task profile allowed methods')
    batch.add_argument('--batch-index', type=int, required=True)
    batch.add_argument('--observation-root', type=Path, help='explicit separate directory for live run events')


def run_agent_command(args):
    def load(path): return json.loads(path.read_text())
    if args.agent_action == 'business':
        from uteki.agents.business_map.workflow import run_business_task
        from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact
        request = load(args.request)
        source_config = request.get('query', {}).get('company_config')
        contact = None
        if source_config is not None:
            if not isinstance(source_config, dict):
                raise ValueError('explicit company configuration object required')
            contact, _ = resolve_sec_contact(explicit=args.sec_user_agent,
                configured=source_config.get('sec_user_agent'), settings_root=args.credentials_root)
        return asyncio.run(run_business_task(request, root=args.root, workspace=args.workspace,
            output=args.output, planner_model_config=load(args.model_config),
            extractor_model_config=load(args.extractor_model_config), credentials_root=args.credentials_root,
            observation_root=args.observation_root, sec_user_agent=contact))
    if args.agent_action == 'acquire':
        from uteki.infrastructure.document_sources.company_acquisition import prepare_sources
        from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact
        config = _company_config(args)
        if not isinstance(config, dict):
            raise ValueError('explicit company configuration object required')
        contact, origin = resolve_sec_contact(explicit=args.sec_user_agent,
            configured=config.get('sec_user_agent'), settings_root=getattr(args, 'settings_root', Path.cwd()))
        if contact is not None:
            config['sec_user_agent'] = contact
        config['sec_contact_origin'] = origin
        return prepare_sources(config, args.workspace)
    from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
    if args.agent_action == 'prepare':
        acquisition = getattr(args, 'from_acquisition', None)
        pin = getattr(args, 'acquisition_sha256', None)
        source_ids = getattr(args, 'source_ids', None)
        if acquisition is not None:
            if pin is None or not source_ids:
                raise ValueError('--from-acquisition requires --acquisition-sha256 and at least one --source-id')
            if getattr(args, 'company_catalog', None) is not None or getattr(args, 'sec_user_agent', None) is not None:
                raise ValueError('frozen acquisition replay does not accept company catalog or SEC contact overrides')
            return CompanyDataCoordinator(args.workspace).prepare_acquisition(acquisition,
                acquisition_sha256=pin, source_ids=source_ids, output=args.output)
        if pin is not None or source_ids is not None:
            raise ValueError('--acquisition-sha256 and --source-id require --from-acquisition')
    if args.agent_action == 'inspect':
        return inspect_run(args.run, artifact_read=load(args.artifact_request) if args.artifact_request else None)
    if args.agent_action == 'extract':
        from .direct_extraction import run_direct_extraction
        return asyncio.run(run_direct_extraction(args.dataset, load(args.job), args.output,
            strategy=args.strategy, model_config=load(args.model_config), credentials_root=args.credentials_root,
            observation_root=getattr(args, 'observation_root', None)))
    if args.agent_action == 'extract-batch':
        from .extraction_batches import run_extraction_batch
        return asyncio.run(run_extraction_batch(args.dataset, load(args.job), args.output,
            task_profile=args.task_profile, method_id=args.method_id, method_root=args.method_root, batch_index=args.batch_index,
            model_config=load(args.model_config), credentials_root=args.credentials_root,
            observation_root=getattr(args, 'observation_root', None)))
    from uteki.infrastructure.document_sources.sec_settings import resolve_sec_contact
    source_config = _company_config(args)
    request = load(args.request) if getattr(args, 'request', None) else None
    if source_config is None and isinstance(request, dict):
        source_config = request.get('company_config')
    contact = None
    if source_config is not None:
        if not isinstance(source_config, dict):
            raise ValueError('explicit company configuration object required')
        contact, origin = resolve_sec_contact(explicit=args.sec_user_agent,
            configured=source_config.get('sec_user_agent'), settings_root=args.settings_root)
        source_config['sec_contact_origin'] = origin
    coordinator = CompanyDataCoordinator(args.workspace, sec_user_agent=contact)
    if args.agent_action == 'prepare':
        if args.from_run:
            return coordinator.reprocess(args.from_run, output=args.output)
        return coordinator.prepare(source_config, output=args.output)
    if args.agent_action == 'refresh':
        return coordinator.refresh(source_config, previous=args.previous, output=args.output)
    return asyncio.run(coordinator.query(request, output=args.output,
        model_config=load(args.model_config), credential_root=args.credentials_root,
        observation_root=getattr(args, 'observation_root', None),
        extractor_model_config=load(args.extractor_model_config) if args.extractor_model_config else None,
        method_root=args.method_root))
