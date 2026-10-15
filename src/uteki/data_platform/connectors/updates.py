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
from ..contracts.assets import Acquisition, AssetId, SnapshotId, SnapshotRelation, SourceId
from ..contracts.common import Contract, SourceTime, Text, CatalogError, canonical, digest
from ..contracts.content import MissingResource
from ..contracts.query import AcquireUpdate, parse
from ..retrieval.assets import cutoff, period_match
from .official import acquire_html, store_acquisition


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


class OfficialAcquisitionAdapter:
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

    def binding(self):
        return digest(canonical(dict(plans=[p.model_dump(mode='json') for p in self.plans],
            network_enabled=self.allow_network,controlled_transport=self.fetch is not None)))

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

    def execute(self, execution, plan):
        catalog=execution.catalog
        workspace=ensure_directory(catalog.root,'acquisitions/'+execution.operation)
        frozen_plan=catalog.content.put_object(plan.canonical_bytes())
        try:
            acquired=acquire_html(config=deepcopy(plan.config),workspace=workspace,settings_root=self.settings_root,
                main_url=plan.main_url,allowed_urls=plan.allowed_urls,max_seconds=plan.max_seconds,fetch=self.fetch,
                should_cancel=execution.should_cancel)
        finally:
            reports=[json.loads(p.read_bytes()) for p in (workspace/'source-runs').glob('*/manifest.json')]
            requests=sum(r['requests'] for r in reports)
            execution.resource_usage.update(transport_requests=requests,bytes_received=sum(r['bytes_received'] for r in reports),
                external_calls=requests if self.fetch is None else 0)
        execution.check('acquisition_received')
        input_ref=store_acquisition(catalog.content,acquired,main_url=plan.main_url)
        inputs=catalog.content.read_manifest(input_ref)
        main=next(r for r in acquired['report']['discovery'] if r['status']=='fetched' and r['source_url']==plan.main_url)
        run=catalog.start_run('acquisition:'+execution.operation,purpose='explicit approved source update',kind='build',
            parent_run_id=execution.context['run_id'])['run_id']
        acquisition=Acquisition(source_id=plan.source_id,request_url=plan.main_url,final_url=acquired['final_url'],
            acquired_at=main['retrieved_at'],published_at=plan.published_at,available_at=plan.available_at,source_revised_at=plan.source_revised_at)
        snapshot=catalog.begin_snapshot(execution.operation+':snapshot',asset_id=plan.asset_id,acquisition=acquisition,
            completeness='partial' if any(isinstance(r,MissingResource) for r in inputs.resources) else 'complete',
            version_consistency=plan.version_consistency,revision_of_snapshot_id=plan.revision_of_snapshot_id,
            revision_basis=plan.revision_basis,run_id=run)
        representation=catalog.add_representation(execution.operation+':html',snapshot_id=snapshot,format='html',input_manifest=input_ref)
        catalog.relate_snapshot(snapshot,plan.relation)
        catalog.freeze_snapshot(snapshot)
        execution.check('acquisition_snapshot_frozen')
        recipe=html_recipe(catalog,encoding='utf-8',form_type=plan.form_type,profile_ref=plan.profile_ref,taxonomy_ref=plan.taxonomy_ref)
        reference=build_html(catalog,snapshot_id=snapshot,representation_id=representation,recipe=recipe,run_id=run)
        catalog.finish_run(run,status='completed')
        execution.check('acquisition_build_published')
        gaps=[r.reason for r in inputs.resources if isinstance(r,MissingResource)]
        return dict(update_id=catalog.get_build(reference.build_id)['job_id'],status='partial' if gaps else 'completed',
            policy_decision=dict(allowed=True,denied_reason=None,matched_rules=['host_approved_exact_request','exact_url_allowlist']),
            new_asset_refs=[reference.model_dump(mode='json')],gaps=gaps,resource_usage=deepcopy(execution.resource_usage),
            acquisition_plan_ref=frozen_plan.model_dump(mode='json'),
            acquisition_report_ref=dict(operation_id=execution.operation,source_run_id=acquired['report']['run_id']))
