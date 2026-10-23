"""Host-approved acquisition plans using the existing bounded official transport."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from pydantic import Field
from typing import Annotated, Literal

from ..build.pipeline import build_html, html_recipe
from ..catalog.database import ensure_directory
from ..content.publication import Publication
from ..contracts.assets import Acquisition, AssetId, SnapshotId, SnapshotRelation, SourceId
from ..contracts.common import Contract, SourceTime, Text, CatalogError, canonical, digest
from ..contracts.content import MissingResource
from ..contracts.query import AcquireUpdate, parse
from ..retrieval.assets import cutoff, period_match
from .official import acquire_html, store_acquisition


# 宿主预先批准的精确采集计划：冻结请求、身份、时间、URL 范围、限制与构建配方信息。
class OfficialAcquisitionPlan(Contract):
    """Trusted host configuration; tool callers cannot supply or broaden it."""
    request: AcquireUpdate
    asset_id: AssetId
    source_id: SourceId
    relation: SnapshotRelation
    published_at: SourceTime
    available_at: SourceTime
    source_revised_at: SourceTime
    version_consistency: Literal['consistent','inconsistent','unknown']
    revision_of_snapshot_id: SnapshotId | None
    revision_basis: str | None
    main_url: Text
    allowed_urls: tuple[Text,...]
    config: dict
    max_seconds: Annotated[int,Field(ge=1,le=120)]
    form_type: Text
    profile_ref: Text
    taxonomy_ref: Text


# 把宿主批准计划接入一次受控更新，串联权限检查、回执记录、快照冻结与 HTML 构建。
class OfficialAcquisitionAdapter:
    # 预先校验计划与私密设置目录；真实联网需明确开启，受控 fetch 只作为可注入传输。
    def __init__(self, plans, *, settings_root: Path, fetch=None, allow_network=False):
        self.plans=tuple(parse(OfficialAcquisitionPlan,p) for p in plans)
        self.settings_root=settings_root
        self.fetch=fetch
        self.allow_network=allow_network
        if type(allow_network) is not bool:
            raise CatalogError('INVALID_REQUEST','allow_network must be an explicit boolean')
        if not isinstance(settings_root,Path) or not settings_root.is_absolute() or not settings_root.is_dir():
            raise CatalogError('INVALID_REQUEST','explicit settings directory required')
        if fetch is not None and not callable(fetch):
            raise CatalogError('INVALID_REQUEST','fetch must be a controlled callable')
        for plan in self.plans:
            if 'sec_user_agent' in plan.config:
                raise CatalogError('INVALID_REQUEST','contact must come from private settings, never a stored acquisition plan')

    # 将计划与传输模式生成指纹，用于把宿主执行选择绑定到操作身份。
    def binding(self):
        return digest(canonical(dict(plans=[p.model_dump(mode='json') for p in self.plans],
            network_enabled=self.allow_network,controlled_transport=self.fetch is not None)))

    # 要求唯一精确计划，并逐项验证来源、主体、材料、期间与截止日是否在当前读策略内。
    def validate(self, execution):
        request=execution.request.acquire
        matches=[p for p in self.plans if p.request==request]
        if len(matches)!=1:
            raise CatalogError('POLICY_DENIED','no unique host-approved plan for this exact acquisition request')
        plan=matches[0]
        if self.fetch is None and not self.allow_network:
            raise CatalogError('POLICY_DENIED','network acquisition has not been enabled by the host')
        if plan.relation.company_id!=request.company_id or plan.relation.status!='confirmed' or plan.relation.role not in {'issuer','subject'}:
            raise CatalogError('SCOPE_DENIED','host plan lacks the requested confirmed entity relation')
        catalog=execution.catalog
        source=json.loads(catalog._get('sources','source_id',plan.source_id)['payload'])
        policy=execution.context['read_policy']
        if source['source_kind'] not in {'sec_edgar','official_site'} or source['source_kind'] not in policy['source_kinds']:
            raise CatalogError('SCOPE_DENIED','official source is outside read policy')
        if policy['source_ids'] and plan.source_id not in policy['source_ids']:
            raise CatalogError('SCOPE_DENIED','source identity is outside read policy')
        if source['canonical_url']!=plan.main_url or plan.main_url not in plan.allowed_urls:
            raise CatalogError('POLICY_DENIED','source URL does not match the approved exact URL policy')
        if len(request.source_hints)!=1 or any(h.get('connector')!='official_html' or h.get('url')!=plan.main_url or set(h)!={'connector','url'} for h in request.source_hints):
            raise CatalogError('CAPABILITY_UNSUPPORTED','this adapter requires one explicit official_html URL hint')
        asset=catalog.get_asset(plan.asset_id)
        payload=json.loads(asset['payload'])
        if asset['status']=='retired' or payload['material_type'] not in request.material_types:
            raise CatalogError('SCOPE_DENIED','target asset type is not in the requested acquisition scope')
        if request.periods and not any(period_match(payload['reporting_period'],p.model_dump(mode='json')) is True for p in request.periods):
            raise CatalogError('SCOPE_DENIED','target asset reporting period is not confirmed within requested scope')
        if execution.context['request']['periods'] and not any(period_match(payload['reporting_period'],p) is True for p in execution.context['request']['periods']):
            raise CatalogError('SCOPE_DENIED','target period is outside or unresolved in this context')
        # 截止日检查采用来源可用时间的上界；时间未知或无法证明在界内时拒绝采集。
        bound=cutoff(execution.context)
        if bound is not None:
            if plan.available_at.value is None:
                raise CatalogError('SCOPE_TIME_UNKNOWN','acquisition availability is unknown')
            if datetime.fromisoformat(plan.available_at.value.bounds()[1])>bound:
                raise CatalogError('SCOPE_DENIED','acquisition availability exceeds cutoff')
        if source['source_kind']=='sec_edgar' and plan.config.get('document_validation')!='sec_inline_identity_v1':
            raise CatalogError('POLICY_DENIED','SEC plans must enable existing inline filing identity validation')
        # Freeze host-side execution choices in the same operation fingerprint.
        return plan

    # 先冻结执行意图及回执，再登记原件、快照与构建；全过程保留资源用量和未决副作用。
    def execute(self, execution, plan):
        catalog=execution.catalog
        workspace=ensure_directory(catalog.root,'acquisitions/'+execution.operation)
        frozen_plan=catalog.content.put_object(plan.canonical_bytes())
        recipe=html_recipe(catalog,encoding='utf-8',form_type=plan.form_type,profile_ref=plan.profile_ref,taxonomy_ref=plan.taxonomy_ref)
        execution.prepare_acquisition(plan_ref=frozen_plan.model_dump(mode='json'),recipe=recipe.model_dump(mode='json'),
            transport_journal_version='uteki-acquisition-transport-v1')

        # 每次进度先持久化回执，再更新用量和意图引用，供中断后核验原请求。
        def progress(report):
            receipt=catalog.content.put_object(canonical(report))
            execution.resource_usage.update(transport_requests=report['requests'],bytes_received=report['bytes_received'],
                external_calls=report['requests'] if self.fetch is None else 0)
            execution.prepare_acquisition(source_run_id=report['run_id'],receipt_ref=receipt.model_dump(mode='json'))
            execution.check('acquisition_receipt_recorded')

        try:
            execution.check('before_acquisition')
            acquired=acquire_html(config=deepcopy(plan.config),workspace=workspace,settings_root=self.settings_root,
                main_url=plan.main_url,allowed_urls=plan.allowed_urls,
                max_seconds=min(plan.max_seconds,execution.limit.remaining()) if execution.limit else plan.max_seconds,fetch=self.fetch,
                should_cancel=execution.limit.stopped if execution.limit else execution.should_cancel,on_progress=progress)
        except CatalogError:
            if execution.limit is not None:
                execution.limit.check('acquisition_stopped')
            raise
        # 无论成功失败，都从保留的来源运行回执汇总实际用量，避免异常路径丢失请求和字节计数。
        finally:
            reports=[json.loads(p.read_bytes()) for p in (workspace/'source-runs').glob('*/manifest.json')]
            requests=sum(r['requests'] for r in reports)
            execution.resource_usage.update(transport_requests=requests,bytes_received=sum(r['bytes_received'] for r in reports),
                external_calls=requests if self.fetch is None else 0)
            if reports:
                execution.effect(kind='acquisition_receipt',status='recorded',operation_id=execution.operation,
                    source_run_ids=[r['run_id'] for r in reports],transport_requests=requests)
        # 先冻结所得输入和最终回执，再登记采集完成；后续恢复可核验同一份原件而无需再请求。
        input_ref=store_acquisition(catalog.content,acquired,main_url=plan.main_url)
        inputs=catalog.content.read_manifest(input_ref)
        receipt=catalog.content.put_object(canonical(acquired['report']))
        execution.prepare_acquisition(input_ref=input_ref.model_dump(mode='json'),receipt_ref=receipt.model_dump(mode='json'),
            acquisition_complete=True)
        execution.check('acquisition_received')
        execution.check('before_snapshot_registration')
        main=next(r for r in acquired['report']['discovery'] if r['status']=='fetched' and r['source_url']==plan.main_url)
        run=catalog.start_run('acquisition:'+execution.operation,purpose='explicit approved source update',kind='build',
            parent_run_id=execution.context['run_id'])['run_id']
        execution.prepare_acquisition(run_id=run)
        try:
            acquisition=Acquisition(source_id=plan.source_id,request_url=plan.main_url,final_url=acquired['final_url'],
                acquired_at=main['retrieved_at'],published_at=plan.published_at,available_at=plan.available_at,source_revised_at=plan.source_revised_at)
            snapshot=catalog.begin_snapshot(execution.operation+':snapshot',asset_id=plan.asset_id,acquisition=acquisition,
                completeness='partial' if any(isinstance(r,MissingResource) for r in inputs.resources) else 'complete',
                version_consistency=plan.version_consistency,revision_of_snapshot_id=plan.revision_of_snapshot_id,
                revision_basis=plan.revision_basis,run_id=run)
            representation=catalog.add_representation(execution.operation+':html',snapshot_id=snapshot,format='html',input_manifest=input_ref)
            catalog.relate_snapshot(snapshot,plan.relation)
            execution.prepare_acquisition(snapshot_id=snapshot,representation_id=representation)
            execution.check('before_snapshot_freeze')
            Publication(catalog,checkpoint=execution.check).freeze_snapshot(snapshot)
            execution.check('acquisition_snapshot_frozen')
            reference=build_html(catalog,snapshot_id=snapshot,representation_id=representation,recipe=recipe,run_id=run,checkpoint=execution.check)
            catalog.finish_run(run,status='completed')
            execution.check('acquisition_build_published')
        except (CatalogError,OSError) as error:
            pending = (catalog._db.execute("SELECT 1 FROM asset_builds WHERE run_id=? AND status='staging'",(run,)).fetchone()
                or catalog._db.execute("SELECT 1 FROM asset_snapshots WHERE run_id=? AND status='collecting'",(run,)).fetchone())
            # 没有 collecting/staging 遗留且提交头明确时才结束失败任务；否则保留原状态交恢复确认。
            if not pending and not catalog.database.head_uncertain and catalog._get('runs','run_id',run)['status']=='running':
                code=getattr(error,'code','STORAGE_IO_ERROR')
                catalog.finish_run(run,status='cancelled' if code=='CANCELLED' else 'failed',
                    failure_code=None if code=='CANCELLED' else code)
            raise
        # 对外逐项报告实际快照/构建副作用与恢复需求，不用函数抛错概括为“什么都没发生”。
        finally:
            for row in catalog._db.execute('SELECT * FROM asset_snapshots WHERE run_id=?',(run,)):
                execution.effect(kind='snapshot',snapshot_id=row['snapshot_id'],status=row['status'],failure_code=row['failure_code'],
                    recovery_required=row['status']=='collecting' or catalog.database.head_uncertain)
            for row in catalog._db.execute('SELECT * FROM asset_builds WHERE run_id=?',(run,)):
                execution.effect(kind='build',asset_ref=catalog.asset_ref(dict(row)).model_dump(mode='json'),status=row['status'],
                    failure_code=row['failure_code'],recovery_required=row['status']=='staging' or catalog.database.head_uncertain,
                    publication_outcome='uncertain' if catalog.database.head_uncertain else row['status'])
        return acquisition_result(catalog,reference,inputs,execution.resource_usage,frozen_plan,execution.operation,acquired['report']['run_id'])


# 为正常执行和恢复确认生成同形结果；输入资源缺口决定 partial，并保留计划与回执入口。
def acquisition_result(catalog, reference, inputs, resource_usage, frozen_plan, operation_id, source_run_id):
    """Same result shape for normal execution and verified existing publication."""
    gaps=[r.reason for r in inputs.resources if isinstance(r,MissingResource)]
    return dict(update_id=catalog.get_build(reference.build_id)['job_id'],status='partial' if gaps else 'completed',
            policy_decision=dict(allowed=True,denied_reason=None,matched_rules=['host_approved_exact_request','exact_url_allowlist']),
            new_asset_refs=[reference.model_dump(mode='json')],gaps=gaps,resource_usage=deepcopy(resource_usage),
            acquisition_plan_ref=frozen_plan.model_dump(mode='json'),
            acquisition_report_ref=dict(operation_id=operation_id,source_run_id=source_run_id))
