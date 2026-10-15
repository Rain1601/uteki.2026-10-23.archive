"""Explicit official HTML request -> freeze -> publish -> reopen -> source readback.

Uses an ordinary installed package. Supply your own reviewed metadata and exact
URL policy; there are no company, period, data-root or answer defaults. A saved
successful acquisition can be reused without a new network request.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.catalog.database import read_regular
from uteki.data_platform.content import ContentStore
from uteki.data_platform.contracts.assets import Acquisition,AssetInput,CompanyInput,Evidence,SnapshotRelation,SourceInput
from uteki.data_platform.contracts.common import CatalogError,SourceTime,canonical
from uteki.data_platform.contracts.content import InputManifest,MissingResource,ObjectRef,PresentResource
from uteki.data_platform.contracts.evidence import HtmlEvidenceRef
from uteki.data_platform.connectors.official import acquire_html,store_acquisition
from uteki.data_platform.build.pipeline import build_html,html_recipe
from uteki.data_platform.retrieval.content import HtmlReader


def load_receipt(root,receipt_path):
    source_store=ContentStore(root)
    receipt=json.loads(read_regular(receipt_path))
    path=root/receipt['source_run']
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise CatalogError('INVALID_ARGUMENT','source-run receipt must stay inside acquisition root')
    report=json.loads(read_regular(path))
    if report['status'] not in {'completed','completed_with_gaps'}:
        raise CatalogError('ACQUISITION_FAILED','source run did not complete')
    input_ref=ObjectRef.model_validate(receipt['input_manifest'])
    inputs=source_store.read_manifest(input_ref)
    fetched=[entry for entry in report['discovery'] if entry['status']=='fetched']
    main=[entry for entry in fetched if entry['content_sha256']==inputs.main.sha256 and entry['final_url']==inputs.main_source_url]
    if len(main)!=1:
        raise CatalogError('ACQUISITION_FAILED','source receipt does not identify this main object')
    for resource in inputs.resources:
        if isinstance(resource,PresentResource) and not any(e['source_url']==resource.source_url and e['content_sha256']==resource.object_ref.sha256 for e in fetched):
            raise CatalogError('ACQUISITION_FAILED','resource receipt differs from frozen input')
    return source_store,inputs,report,main[0]


def build_from_receipt(catalog,source_store,inputs,report,main,request):
    # Content hashes verify byte identity; logical IDs still come from Catalog.
    main_ref=catalog.content.put_object(source_store.read_object(inputs.main))
    resources=[]
    for item in inputs.resources:
        if isinstance(item,PresentResource):
            item=item.model_copy(update={'object_ref':catalog.content.put_object(source_store.read_object(item.object_ref))})
        resources.append(item)
    imported=InputManifest(schema_version=inputs.schema_version,main=main_ref,main_source_url=inputs.main_source_url,resources=tuple(resources))
    input_ref=catalog.content.put_manifest(imported)
    key=request['request_key']
    run=catalog.start_run(key,purpose='explicit official HTML material build',kind='build')['run_id']
    policy=request['policy_ref']
    catalog.register_policy(policy,definition=canonical(report['scope']).decode(),run_id=run)
    asset=AssetInput.model_validate_json(json.dumps(request['asset']))
    catalog.register_material_type(asset.material_type,asset_kind=asset.asset_kind,description=request['material_type_description'],run_id=run)
    company=CompanyInput.model_validate_json(json.dumps(request['company']))
    # Attach the verified original to caller-supplied identity evidence. This
    # does not promote unverified/candidate metadata to confirmed metadata.
    company=company.model_copy(update={'evidence':company.evidence.model_copy(update={'object_ref':main_ref})})
    co=catalog.register_company(key+':company',company,run_id=run)
    source=SourceInput.model_validate_json(json.dumps(request['source']|{'publisher_company_id':co if request['publisher_is_issuer'] else None,'policy_ref':policy}))
    if source.canonical_url!=main['source_url']:
        raise CatalogError('IDENTITY_CONFLICT','requested canonical URL differs from actual acquisition')
    source_id=catalog.register_source(key+':source',source,run_id=run)
    asset=asset.model_copy(update={'evidence':asset.evidence.model_copy(update={'object_ref':main_ref})})
    asset_id=catalog.register_asset(key+':asset',asset,run_id=run)
    times={name:SourceTime.model_validate_json(json.dumps(request[name])) for name in ('published_at','available_at','source_revised_at')}
    acquisition=Acquisition(source_id=source_id,request_url=main['source_url'],final_url=main['final_url'],acquired_at=main['retrieved_at'],**times)
    snapshot=catalog.begin_snapshot(key+':snapshot',asset_id=asset_id,acquisition=acquisition,
        completeness='partial' if any(isinstance(r,MissingResource) for r in resources) else 'complete',
        version_consistency=request['version_consistency'],revision_of_snapshot_id=None,revision_basis=None,run_id=run)
    representation=catalog.add_representation(key+':html',snapshot_id=snapshot,format='html',input_manifest=input_ref)
    catalog.relate_snapshot(snapshot,SnapshotRelation(company_id=co,role='issuer',basis='source_metadata',
        status='confirmed' if company.status=='confirmed' else 'candidate',evidence=company.evidence))
    catalog.freeze_snapshot(snapshot)
    recipe=html_recipe(catalog,encoding=request['encoding'],form_type=request['form_type'],profile_ref=request['profile_ref'],taxonomy_ref=request['taxonomy_ref'])
    reference=build_html(catalog,snapshot_id=snapshot,representation_id=representation,recipe=recipe,run_id=run)
    catalog.finish_run(run,status='completed')
    return reference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--acquisition-root',type=Path,required=True)
    parser.add_argument('--receipt',type=Path)
    parser.add_argument('--acquire',action='store_true')
    parser.add_argument('--settings-root',type=Path)
    parser.add_argument('--initialize',action='store_true',help='Explicitly initialize an empty existing data root')
    args=parser.parse_args()
    if args.acquire==bool(args.receipt):parser.error('choose exactly one of --acquire or --receipt')
    request=json.loads(args.request.read_text())
    if args.acquire:
        if args.settings_root is None:parser.error('--acquire requires explicit --settings-root')
        config=request['acquisition']
        if 'sec_user_agent' in config['config']:parser.error('keep SEC contact in private settings, not the request')
        acquired=acquire_html(config=config['config'],workspace=args.acquisition_root,settings_root=args.settings_root,
            main_url=config['main_url'],allowed_urls=tuple(config['allowed_urls']),max_seconds=config['max_seconds'])
        ref=store_acquisition(ContentStore(args.acquisition_root),acquired,main_url=config['main_url'])
        receipt_path=args.acquisition_root/(acquired['report']['run_id']+'-result.json')
        with receipt_path.open('xb') as stream:stream.write(canonical(dict(input_manifest=ref.model_dump(mode='json'),source_run=acquired['report']['manifest_path'])))
    else:
        receipt_path=args.receipt
    store,inputs,report,main_receipt=load_receipt(args.acquisition_root,receipt_path)
    with (Catalog.initialize(args.data_root) if args.initialize else Catalog.open(args.data_root)) as catalog:
        reference=build_from_receipt(catalog,store,inputs,report,main_receipt,request)
    with Catalog.open(args.data_root) as catalog:
        reader=HtmlReader(catalog,reference);inventory=reader.inventory()
        samples=[]
        block=next((b for b in inventory['blocks'] if b['text'] and b['kind']!='table'),None)
        if block:samples.append(reader.read(HtmlEvidenceRef(asset_ref=reference,kind='block',item_id=block['id'],field='text')))
        record=next((r for r in inventory['records'] if r['status']=='parsed'),None)
        if record:samples.append(reader.read(HtmlEvidenceRef(asset_ref=reference,kind='record_field',item_id=record['id'],field='value_decimal')))
        print(json.dumps(dict(asset_ref=reference.model_dump(mode='json'),schema=inventory['schema'],samples=samples,
            counts={name:len(inventory[name]) for name in ('blocks','sections','tables','records','images')},
            reopened=True,model_calls=0,autonomous_agent_evaluated=False),ensure_ascii=False))


if __name__=='__main__':main()
