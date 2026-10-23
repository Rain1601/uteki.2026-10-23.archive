"""Prepare, run or inspect one explicitly authorized real-provider function batch.

No answer keys, scripted model responses or implicit data roots are accepted.
The official SDKs own their loops. All lanes share the existing durable budget.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

from uteki.data_platform.agent.profiles import load_profile, validate_distinct_prompts
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.gateway_batch import create_gateway_batch, load_gateway_binding, prepare_gateway_attempt
from uteki.data_platform.application.gateway_supervisor import GatewaySupervisor
from uteki.data_platform.application.session import Session
from uteki.data_platform.application.run_completion import read_result
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import canonical, digest
from uteki.data_platform.service import DataService


def write(path, value):
    with Path(path).open('x') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def profile(config_root, entry):
    return load_profile(config_root/entry['profile_path'], config_root=config_root,
                        kernel=entry['kernel'], model_id=entry['model_id'], role='query')


def prepare(args):
    config = args.config_root.resolve(strict=True)
    plan = json.loads(args.plan.read_bytes())
    case = json.loads(args.case.read_bytes())
    if set(case) != {'context', 'read_policy'}:
        raise ValueError('Case contains only business context and read policy, never gold or tool steps')
    from uteki.data_platform.contracts.query import ContextRequest, ReadPolicy, parse
    parse(ContextRequest, case['context'])
    parse(ReadPolicy, case['read_policy'])
    if (plan['inference_authorized'] is not True or plan['limit_usd'] != '1'
            or plan['max_requests'] != 40 or len(plan['lanes']) != 4):
        raise ValueError('This entry requires the explicit four-lane, $1/40-request task contract')
    if args.data_root.exists() or args.manifest.exists():
        raise ValueError('Do not overwrite/recreate a batch; reuse its manifest for subsequent lanes')
    loaded = [profile(config, entry) for entry in plan['lanes'].values()]
    validate_distinct_prompts(loaded)
    for p in loaded:
        p.validate(kernel=p.profile.kernel, mode='gateway')
    shutil.copytree(args.source_data_root.resolve(strict=True), args.data_root)
    root = args.data_root.resolve(strict=True)
    batch_id = str(uuid.uuid4())
    scopes, frozen = [], {}
    with Catalog.open(root) as catalog:
        run = catalog.start_run(batch_id+':policy', purpose='bounded real model function acceptance', kind='read')
        catalog.register_policy(case['context']['source_policy_ref'], definition=canonical(case['read_policy']).decode(), run_id=run['run_id'])
        catalog.finish_run(run['run_id'], status='completed')
        service = DataService(catalog)
        for (lane, entry), p in zip(plan['lanes'].items(), loaded):
            context = deepcopy(case['context'])
            if context['run_policy']['max_usd'] != plan['limit_usd']:
                raise ValueError('Business and batch monetary limits differ')
            context_ref = service.create_context(context, request_key=batch_id+':'+lane)['context_ref']
            scope = dict(scope_id=lane, context_ref=context_ref, profile=p.metadata(),
                         limits=entry['limits'], transport=entry['transport'])
            scopes.append(scope)
            frozen[lane] = dict(profile=p.metadata(), transport=entry['transport'],
                max_requests=entry['limits']['max_model_requests'], pricing=entry['pricing'])
        contract = dict(schema='uteki-live-function-v1', inference_authorized=True,
            limit_usd=plan['limit_usd'], max_requests=plan['max_requests'], warning_usd=plan['warning_usd'],
            authorization=plan['authorization'], case_sha256=digest(canonical(case)), scopes=frozen)
        bindings = create_gateway_batch(catalog, batch_id=batch_id, scopes=scopes,
            limit_usd=plan['limit_usd'], max_requests=plan['max_requests'], origin='live',
            contract_sha256=digest(canonical(contract)))
    write(args.manifest, dict(schema='uteki-live-function-manifest-v1', data_root=str(root),
        config_root=str(config), batch_id=batch_id, contract=contract, scopes=scopes,
        bindings=bindings, lanes=plan['lanes']))
    print(json.dumps(dict(status='prepared', manifest=str(args.manifest), model_calls=0)))


def credentials(name, path):
    value = os.environ.get(name)
    if not value and path:
        for line in Path(path).read_text().splitlines():
            k, sep, v = line.strip().removeprefix('export ').partition('=')
            if sep and k.strip() == name:
                value = v.strip().strip('\"\'')
    if not value or any(c in value for c in '\r\n'):
        raise ValueError('Credential unavailable: '+name)
    return value


def prepare_attempt(args):
    """Prepare one new native session; retain the original contract and ledger."""
    if args.output.exists():raise ValueError('Keep the previous manifest; output already exists')
    manifest=json.loads(args.manifest.read_bytes())
    entry=manifest['lanes'][args.lane]
    loaded=profile(Path(manifest['config_root']),entry)
    loaded.validate(kernel=entry['kernel'],mode='gateway')
    scope=next(s for s in manifest['scopes'] if s['scope_id']==args.lane)
    with Catalog.open(Path(manifest['data_root'])) as catalog:
        attempt=prepare_gateway_attempt(catalog,manifest['bindings'][args.lane],loaded.metadata(),
            request_key=args.attempt_key,max_request_bytes=args.max_request_bytes)
        if args.max_request_bytes is not None:
            from uteki.data_platform.contracts.content import ObjectRef
            saved=json.loads(catalog.content.read_object(ObjectRef.model_validate(attempt['binding']['attempt_ref'])))
            scope.update(limits=saved['policy']['limits'],transport=saved['policy']['transport'])
    scope.update(context_ref=attempt['context_ref'],profile=loaded.metadata())
    manifest['bindings'][args.lane]=attempt['binding']
    manifest['attempt']=dict(lane=args.lane,request_key=args.attempt_key,
        original_manifest=str(args.manifest.resolve()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write(args.output,manifest)
    print(json.dumps(dict(status='prepared',manifest=str(args.output),context_ref=attempt['context_ref'],
        shared_batch_id=manifest['batch_id'],new_model_calls=0)))


def export_result(args):
    from uteki.data_platform.application.exports import export_delivery
    manifest=json.loads(args.manifest.read_bytes())
    scope=next(s for s in manifest['scopes'] if s['scope_id']==args.lane)
    with Catalog.open(Path(manifest['data_root'])) as catalog:
        result=read_result(Session(catalog,scope['context_ref']))
    if not result or not result.get('delivery'):
        raise ValueError('No successfully committed runtime delivery; inspect the original failure')
    saved=export_delivery(result['delivery']['delivery'],args.output)
    print(json.dumps(dict(status='exported',output=str(args.output),manifest=saved)))


def extend_allowance(args):
    """Record the supplied user decision and continue the original ledger."""
    from uteki.data_platform.application.gateway_extension import extend_gateway_batch
    if args.output.exists():raise ValueError('Keep the previous manifest; output already exists')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.manifest.read_bytes())
    authorization=json.loads(args.authorization.read_bytes())
    # A monetary-only revision must not reload newer historical configurations.
    profiles=({scope['scope_id']:scope['profile'] for scope in manifest['scopes']}
        if authorization.get('preserve_existing_scopes') is True else
        {lane:profile(Path(manifest['config_root']),entry).metadata() for lane,entry in manifest['lanes'].items()})
    additions=[]
    entries=json.loads(args.add_scopes.read_bytes()) if args.add_scopes else []
    for item in entries:
        entry=item['entry'];loaded=profile(Path(manifest['config_root']),entry)
        loaded.validate(kernel=entry['kernel'],mode='gateway')
        binding = {k:item[k] for k in ('source_scope_id','context_ref') if k in item}
        additions.append(dict(scope_id=item['scope_id'],**binding,
            profile=loaded.metadata(),limits=entry['limits'],transport=entry['transport'],pricing=entry['pricing']))
    base_refs={canonical(b['batch_ref']) for b in manifest['bindings'].values()}
    if len(base_refs)!=1:raise ValueError('All lanes must share the same original batch')
    with Catalog.open(Path(manifest['data_root'])) as catalog:
        revised=extend_gateway_batch(catalog,json.loads(next(iter(base_refs))),profiles,manifest['contract'],authorization,
            additional_scopes=additions)
    manifest.update(revised)
    manifest['lanes'].update({item['scope_id']:item['entry'] for item in entries})
    manifest['allowance_revision']=dict(original_manifest=str(args.manifest.resolve()),authorization_id=authorization['authorization_id'])
    write(args.output,manifest)
    print(json.dumps(dict(status='allowance_extended',manifest=str(args.output),shared_batch_id=manifest['batch_id'],new_model_calls=0)))


async def worker(args):
    manifest = json.loads(args.manifest.read_bytes())
    entry = manifest['lanes'][args.lane]
    loaded = profile(Path(manifest['config_root']), entry)
    key = credentials(entry['credential_env'], args.env_file)
    scope = next(s for s in manifest['scopes'] if s['scope_id'] == args.lane)
    work = args.work.resolve(strict=True)
    # The native CLI receives only a private loopback token. Provider secrets
    # remain in this Python host, outside SDK tools, messages and CLI settings.
    env = dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='C.UTF-8', PYTHONNOUSERSITE='1',
        CLAUDE_CONFIG_DIR=str(work/'claude-config'), ANTHROPIC_BASE_URL='http://127.0.0.1:9',
        ANTHROPIC_API_KEY='', ANTHROPIC_AUTH_TOKEN='uteki-gateway-worker',
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(loaded.profile.max_output_tokens),
        HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', ALL_PROXY='http://127.0.0.1:9',
        NO_PROXY='127.0.0.1,localhost')
    os.environ.clear()
    os.environ.update(env)
    options = {}
    if entry['kernel'] == 'claude':
        import claude_agent_sdk
        from uteki.data_platform.agent.claude_runtime import run_gateway
        options.update(cwd=work, cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude')
    else:
        from uteki.data_platform.agent.openai_runtime import run_gateway
    with Catalog.open(Path(manifest['data_root'])) as catalog:
        result = await run_gateway(DataService(catalog), scope['context_ref'], loaded,
            gateway_binding=manifest['bindings'][args.lane], endpoint=entry['endpoint'], credential=key,
            limits=scope['limits'], execution_contract=manifest['contract'], **options)
    write(work/'result.json', result)
    print(json.dumps(dict(status=result['status'], real_model_calls=result['real_model_calls'])))


def validate_claude_workdir(work):
    """Reject project settings inherited by the native project-only Skill loader."""
    work=Path(work).resolve()
    for parent in (work,*work.parents):
        if any((parent/name).exists() for name in ('AGENTS.md','CLAUDE.md',
                '.claude/CLAUDE.md','.claude/settings.json','.claude/settings.local.json')):
            raise ValueError('Claude live work directory must have no ancestor project instructions or settings; use a fresh directory outside the repository')
    return work


def run(args):
    manifest = json.loads(args.manifest.read_bytes())
    entry = manifest['lanes'][args.lane]
    scope = next(s for s in manifest['scopes'] if s['scope_id'] == args.lane)
    loaded=profile(Path(manifest['config_root']),entry)
    loaded.validate(kernel=entry['kernel'],mode='gateway')
    if loaded.metadata()!=scope['profile']:
        raise ValueError('Current profile differs; use prepare-attempt with the original manifest')
    if entry['kernel']=='claude':
        # Project settings traverse ancestors. A private config dir alone does
        # not prevent the SDK from reading repository development instructions.
        validate_claude_workdir(args.work)
    root = Path(manifest['data_root'])
    with Catalog.open(root) as catalog:
        supervisor = GatewaySupervisor(catalog, scope['context_ref'], manifest['bindings'][args.lane],
            scope['profile'], scope['limits'], batch_deadline=time.monotonic()+600)
        if supervisor.budget.inspect_scope(args.lane)['stop_reason']:
            raise ValueError('Scope is stopped; inspect the original result, do not restart it')
        ledger=supervisor.budget.inspect_root()
        if ledger['stop_reason'] or Decimal(ledger['cost']['unknown_reserved_usd'])>0:
            raise ValueError('Original batch is stopped or has unresolved billing; no worker or request started')
        if any(ledger['request_stages'].get(stage) for stage in ('prepared','dispatched','outcome_unknown')):
            raise ValueError('Original batch contains a pending or uncertain request; inspect before starting')
    credentials(entry['credential_env'], args.env_file)  # Fail before creating a worker.
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-I', str(Path(__file__).resolve()), '_worker',
        '--manifest', str(args.manifest.resolve()), '--lane', args.lane, '--work', str(work)]
    if args.env_file:
        command += ['--env-file', str(args.env_file.resolve())]
    with (work/'stdout.log').open('w') as stdout, (work/'stderr.log').open('w') as stderr:
        process = ObservedWorker(command, cwd=work, env=dict(os.environ), stdout=stdout, stderr=stderr)
        observation = supervisor.wait(process)
    # Keep the actual host observation even if later clock binding fails.
    write(work/'supervision.json', observation)
    with Catalog.open(root) as catalog:
        recorded = supervisor.record(catalog)
        if not (work/'result.json').exists():
            # A supervised stop can kill the native worker before it writes
            # its result. Recover the already-recorded stop without starting
            # an SDK or issuing another model request.
            from uteki.data_platform.application.runtime import RuntimeJournal
            journal = RuntimeJournal(DataService(catalog), scope['context_ref'],
                scope['profile'], scope['limits'], gateway_binding=manifest['bindings'][args.lane],
                recover=True)
            if journal.cached is not None:
                write(work/'result.json', journal.cached)
        session = Session(catalog, scope['context_ref'])
        budget = load_gateway_binding(session, manifest['bindings'][args.lane], scope['profile'], scope['limits'])['budget']
        requests = [r for r in budget.inspect_requests() if r.get('control_scope_id') == args.lane]
        write(work/'evidence.json', dict(scope=scope, requests=requests, ledger=budget.inspect_root(),
            operations=session.data['operations'], supervision=observation, exit_record=recorded,
            exit_code=process.child.returncode))
        held = Decimal(budget.summary()['held_usd']) + Decimal(budget.summary()['estimated_spent_usd'])
    result_path = work/'result.json'
    status = json.loads(result_path.read_bytes())['status'] if result_path.exists() else 'recovery_required'
    print(json.dumps(dict(lane=args.lane, status=status, exit_code=process.child.returncode, output=str(work),
                         warning=held >= Decimal(manifest['contract']['warning_usd']))))
    return 0 if status == 'completed' else 1


def retain_reservation(args):
    """Record an already-given user decision; no credential or network access."""
    manifest = json.loads(args.manifest.read_bytes())
    scope = next(s for s in manifest['scopes'] if s['scope_id'] == args.lane)
    with Catalog.open(Path(manifest['data_root'])) as catalog:
        session = Session(catalog, scope['context_ref'])
        budget = load_gateway_binding(session, manifest['bindings'][args.lane],
            scope['profile'], scope['limits'])['budget']
        if any(budget.inspect_request(key).get('control_scope_id') != args.lane for key in args.request_key):
            raise ValueError('Request does not belong to the selected lane')
        for key in args.request_key:
            budget.retain_response_reservation(key, confirmation=args.confirmation)
        print(json.dumps(dict(retained_requests=args.request_key, cost=budget.inspect_root()['cost'],
            new_model_calls=0)))


def inspect_or_reconcile(args):
    manifest = json.loads(args.manifest.read_bytes())
    if args.command == 'reconcile' and args.lane not in manifest['lanes']:
        raise ValueError('Unknown lane in the existing batch')
    rows = []
    with Catalog.open(Path(manifest['data_root'])) as catalog:
        for scope in manifest['scopes']:
            lane = scope['scope_id']
            if args.command == 'reconcile' and lane != args.lane:
                continue
            session = Session(catalog, scope['context_ref'])
            budget = load_gateway_binding(session, manifest['bindings'][lane],
                scope['profile'], scope['limits'])['budget']
            requests = [r for r in budget.inspect_requests() if r.get('control_scope_id') == lane]
            errors = []
            if args.command == 'reconcile':
                if args.output.exists():
                    raise ValueError('Retain prior billing observations; output already exists')
                from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
                entry = manifest['lanes'][lane]
                if scope['profile']['route']['provider'] != 'openrouter':
                    raise ValueError('DeepSeek has no per-request bill lookup in this adapter')
                wire = GatewayHTTP(budget, lane, endpoint=entry['endpoint'], origin='live',
                    credential=credentials(entry['credential_env'], args.env_file),
                    deadline=time.monotonic()+90, before_request=lambda request:None,
                    execution_contract=manifest['contract'])
                try:
                    for request in requests:
                        if request['cost_state'] == 'unknown':
                            try:
                                wire.observe_bill(request['request_key'])
                            except Exception as error:
                                errors.append(dict(request_key=request['request_key'], error_type=type(error).__name__))
                finally:
                    wire.close()
                requests = [budget.inspect_request(r['request_key']) for r in requests]
            result = read_result(session)
            own_requests=[r for r in requests if r['request'].get('context_ref')==scope['context_ref']]
            rows.append(dict(lane=lane, session_status=session.data['status'],
                status=result['status'] if result else 'not_executed' if not own_requests else 'result_unavailable',
                requests=len(requests),
                session_requests=len(own_requests),
                stop_reason=budget.inspect_scope(lane)['stop_reason'],
                cost_states=[r['cost_state'] for r in requests], errors=errors))
            ledger = budget.inspect_root()
        report = dict(lanes=rows, ledger=ledger, new_model_calls=0)
        if args.command == 'reconcile':
            report['billing_observations'] = {r['request_key']:budget.inspect_billing_observations(r['request_key']) for r in requests}
            write(args.output, report)
    print(json.dumps({k:v for k,v in report.items() if k != 'billing_observations'}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    for name in ('source-data-root', 'data-root', 'config-root', 'plan', 'case', 'manifest'):
        p.add_argument('--'+name, type=Path, required=True)
    p=commands.add_parser('prepare-attempt')
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--lane',required=True)
    p.add_argument('--attempt-key',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-request-bytes',type=int,help='Explicit new execution byte bound; money and request counts remain cumulative')
    p=commands.add_parser('extend-allowance')
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--authorization',type=Path,required=True)
    p.add_argument('--add-scopes',type=Path,help='Explicit additional model lanes sharing the original ledger and business input')
    p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('export',help='Export an existing runtime delivery without model calls')
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--lane',required=True)
    p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('retain-reservation', help='Record user approval to keep a complete response unbilled')
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--lane',required=True)
    p.add_argument('--request-key',action='append',required=True)
    p.add_argument('--confirmation',required=True)
    for name in ('run', '_worker'):
        p = commands.add_parser(name)
        p.add_argument('--manifest', type=Path, required=True)
        p.add_argument('--lane', required=True)
        p.add_argument('--work', type=Path, required=True)
        p.add_argument('--env-file', type=Path)
    for name in ('inspect', 'reconcile'):
        p = commands.add_parser(name)
        p.add_argument('--manifest', type=Path, required=True)
        if name == 'reconcile':
            p.add_argument('--lane', required=True)
            p.add_argument('--env-file', type=Path)
            p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args)
    elif args.command == 'prepare-attempt':
        prepare_attempt(args)
    elif args.command == 'extend-allowance':
        extend_allowance(args)
    elif args.command == 'export':
        export_result(args)
    elif args.command == 'retain-reservation':
        retain_reservation(args)
    elif args.command == 'run':
        raise SystemExit(run(args))
    elif args.command in {'inspect', 'reconcile'}:
        inspect_or_reconcile(args)
    else:
        asyncio.run(worker(args))


if __name__ == '__main__':
    main()
