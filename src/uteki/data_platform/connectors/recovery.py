"""Confirm one interrupted official publication, without transport or parsing."""
from copy import deepcopy
import json

from ..content.publication import Publication
from ..content.store import ContentStoreError
from ..contracts.common import CatalogError, canonical
from ..contracts.content import MissingResource, ObjectRef, PresentResource
from .official import image_key
from .updates import OfficialAcquisitionPlan, acquisition_result


# 仅接受已完成采集的冻结输入，逐项比对计划、传输回执、资源覆盖及累计用量。
def acquired_inputs(catalog, operation, request):
    """Read complete frozen inputs and verify their original acquisition receipt."""
    target = operation['effect_intent']['target']
    if target.get('acquisition_complete') is not True:
        raise CatalogError('RECOVERY_REQUIRED','complete frozen acquisition input is required')
    plan_ref = ObjectRef.model_validate(target['plan_ref'])
    plan = OfficialAcquisitionPlan.model_validate_json(catalog.content.read_object(plan_ref))
    if plan.request != request.acquire:
        raise CatalogError('RECOVERY_REQUIRED','frozen acquisition plan differs from the original request')
    report_raw = catalog.content.read_object(ObjectRef.model_validate(target['receipt_ref']))
    report = json.loads(report_raw)
    inputs = catalog.content.read_manifest(ObjectRef.model_validate(target['input_ref']))
    if (canonical(report) != report_raw or report['run_id'] != target['source_run_id']
            or report['status'] not in {'completed','completed_with_gaps'}):
        raise CatalogError('RECOVERY_REQUIRED','no verified completed acquisition receipt')
    fetched = [r for r in report['discovery'] if r['status']=='fetched' and r['source_url']==plan.main_url]
    if len(fetched)!=1 or fetched[0]['content_sha256']!=inputs.main.sha256 or fetched[0]['final_url']!=inputs.main_source_url:
        raise CatalogError('RECOVERY_REQUIRED','main input and source receipt differ')
    for resource in inputs.resources:
        if isinstance(resource,PresentResource):
            matches = [r for r in report['discovery'] if r['status']=='fetched' and r['source_url']==resource.source_url]
            if len(matches)!=1 or matches[0]['content_sha256']!=resource.object_ref.sha256 or resource.resource_key!=image_key(resource.source_url):
                raise CatalogError('RECOVERY_REQUIRED','resource input and source receipt differ')
    # present、missing、unsupported 集合必须与完成回执完全一致，且不能留有 dispatched 未确认传输。
    declared = report['input_resources']
    if (sorted(r.source_url for r in inputs.resources if isinstance(r,PresentResource))!=declared['present']
            or {r.source_url:r.reason for r in inputs.resources if isinstance(r,MissingResource) and r.source_url is not None}!=declared['missing']
            or {r.resource_key:r.reason for r in inputs.resources if isinstance(r,MissingResource) and r.source_url is None}!=declared['unsupported']
            or (report.get('transport_state') or {}).get('status')=='dispatched'):
        raise CatalogError('RECOVERY_REQUIRED','input resource coverage differs from completed acquisition')
    usage = deepcopy(operation['resource_usage'])
    if (usage['transport_requests']!=report['requests'] or usage['bytes_received']!=report['bytes_received']):
        raise CatalogError('RECOVERY_REQUIRED','acquisition usage and source receipt differ')
    return plan_ref, plan, report, inputs, usage


# 只确认原运行中已移动且完整的快照/构建；不重新联网、解析或创建发布动作。
def confirm_acquisition(catalog, context, operation, request, *, checkpoint):
    """Only already-moved versions may be committed. Never adopt another run."""
    target = operation['effect_intent']['target']
    try:
        required = {'plan_ref','receipt_ref','source_run_id','input_ref','acquisition_complete',
                    'run_id','snapshot_id','representation_id','recipe'}
        if not required <= target.keys() or target['acquisition_complete'] is not True:
            raise CatalogError('RECOVERY_REQUIRED','acquisition is incomplete; recorded receipts and inputs retained, no request repeated')
        plan_ref, plan, report, inputs, usage = acquired_inputs(catalog,operation,request)
        fetched = [r for r in report['discovery'] if r['status']=='fetched' and r['source_url']==plan.main_url]
        run = catalog._get('runs','run_id',target['run_id'])
        if (run['request_key']!='acquisition:'+operation['operation_id'] or run['parent_run_id']!=context['run_id']
                or run['kind']!='build' or run['status'] not in {'running','completed'}):
            raise CatalogError('RECOVERY_REQUIRED','acquisition run ownership or state differs')
        snapshot = catalog.get_snapshot(target['snapshot_id'])
        payload = json.loads(snapshot['payload'])
        expected = dict(source_id=plan.source_id,request_url=plan.main_url,final_url=inputs.main_source_url,
            acquired_at=fetched[0]['retrieved_at'],published_at=plan.published_at.model_dump(mode='json'),
            available_at=plan.available_at.model_dump(mode='json'),source_revised_at=plan.source_revised_at.model_dump(mode='json'))
        if (snapshot['run_id']!=run['run_id'] or snapshot['asset_id']!=plan.asset_id
                or payload['acquisition']!=expected or payload['version_consistency']!=plan.version_consistency
                or payload['revision_of_snapshot_id']!=plan.revision_of_snapshot_id or payload['revision_basis']!=plan.revision_basis
                or payload['completeness']!=('partial' if any(isinstance(r,MissingResource) for r in inputs.resources) else 'complete')
                or catalog.snapshot_relations(snapshot['snapshot_id'])!=[plan.relation.model_dump(mode='json')]):
            raise CatalogError('RECOVERY_REQUIRED','snapshot differs from the frozen acquisition intent')
        representation = catalog._get('snapshot_representations','representation_id',target['representation_id'])
        if (representation['snapshot_id']!=snapshot['snapshot_id'] or representation['format']!='html'
                or json.loads(representation['input_ref'])!=target['input_ref']):
            raise CatalogError('RECOVERY_REQUIRED','snapshot representation differs from obtained input')
        builds = [dict(r) for r in catalog._db.execute('SELECT * FROM asset_builds WHERE run_id=?',(run['run_id'],))]
        if len(builds)!=1:
            raise CatalogError('RECOVERY_REQUIRED','no unique existing build; recovery does not parse or create one')
        build = builds[0]
        if (build['snapshot_id']!=snapshot['snapshot_id'] or build['representation_id']!=representation['representation_id']
                or json.loads(build['recipe'])!=target['recipe'] or json.loads(build['input_ref'])!=target['input_ref']):
            raise CatalogError('RECOVERY_REQUIRED','build differs from acquisition intent')
        publication = Publication(catalog,checkpoint=checkpoint)
        # Verify both final directories before acknowledging either. Staged-only
        # files are retained; recovery cannot start a new publication action.
        # 先验证两个最终目录，再补数据库确认；只有暂存文件时不启动新的移动或解析。
        publication.verify_snapshot(snapshot['snapshot_id'])
        publication.verify_build(build,final=True)
        publication.commit_snapshot(snapshot['snapshot_id'])
        publication.commit_build(build['build_id'])
        catalog.finish_run(run['run_id'],status='completed')
        checkpoint('acquisition_publication_reconciled')
        return acquisition_result(catalog,catalog.asset_ref(build),inputs,usage,plan_ref,
                                  operation['operation_id'],report['run_id'])
    except (CatalogError,ContentStoreError,OSError,ValueError,KeyError,TypeError) as error:
        if isinstance(error,CatalogError) and error.code=='RECOVERY_REQUIRED':
            raise
        raise CatalogError('RECOVERY_REQUIRED','original acquisition/publication could not be verified; no request repeated') from error
