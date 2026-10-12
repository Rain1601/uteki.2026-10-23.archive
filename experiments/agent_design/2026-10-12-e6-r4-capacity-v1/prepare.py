"""Build whole explicitly supplied sources locally; no semantic selection or API."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.query_dataset import build_dataset

ROOT=Path(__file__).resolve().parents[3]


def read(path):return json.loads(path.read_bytes())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def relative(path):return str(path.resolve().relative_to(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',type=Path,required=True)
    p.add_argument('--source-dataset',type=Path,action='append',required=True)
    p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--audit-root',type=Path,required=True)
    args=p.parse_args();base=args.batch.resolve();ledger=args.ledger.resolve()
    if base.exists():raise ValueError('New batch must not exist; preserve prior evidence')
    if not ledger.is_file():raise ValueError('Existing shared ledger required; never create one')
    with sqlite3.connect('file:'+str(ledger)+'?mode=ro',uri=True) as db:
        limit=db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
    if limit!='3':raise ValueError('Expected existing frozen USD 3 shared budget')
    base.mkdir(mode=0o700,parents=True)
    inventory=[];bindings=[];inputs=[];source_pins=[];block_count=0;table_count=0
    for dataset in args.source_dataset:
        dataset=dataset.resolve();manifest=read(dataset/'manifest.json')
        for name,expected in manifest['files'].items():
            if sha(dataset/name)!=expected:raise ValueError('Source dataset hash mismatch: '+name)
        source_pins.append({'path':str(dataset),'manifest_sha256':sha(dataset/'manifest.json')})
        for source in read(dataset/'sources.json'):
            sid=source['source_snapshot_id'];raw=dataset/source['raw_file'];index=dataset/source['index_folder']
            if sha(raw)!=source['source_sha256']:raise ValueError('Original source changed')
            block_count+=sum(1 for _ in (index/'blocks.jsonl').open())
            table_count+=sum(json.loads(line)['type']=='table' for line in (index/'blocks.jsonl').read_text().splitlines())
            # Explicit compatibility binding derives only immutable source metadata;
            # it is not represented as the acquisition's original manifest.
            binding_manifest=base/'builder-inputs'/(sid+'.source-binding.json')
            write_new(binding_manifest,{'schema':'e6-r4-explicit-source-binding-v1',
                'source_snapshot_id':sid,'company_id':source['company_id'],'document_id':source['document_id'],
                'content_sha256':source['source_sha256'],'form':source['form'],'period_end':source['period_end'],
                'published_at':source['available_at'],'source_url':source['source_url'],
                'derived_from':{'path':str(dataset/'sources.json'),'sha256':sha(dataset/'sources.json')}})
            index_files=[x for x in sorted(index.iterdir()) if x.is_file()]
            inventory.append({'source_snapshot_id':sid,'document_id':source['document_id'],
                'eligible_for_new_comparison':True,'declared_content_sha256':source['source_sha256'],
                'published_or_filed_at':source['available_at'],'period_end':source['period_end'],
                'source_url':source['source_url'],
                'source_manifest':{'path':relative(binding_manifest),'sha256':sha(binding_manifest)},
                'raw_file':{'path':relative(raw),'sha256':sha(raw)},
                'index_files':[{'path':relative(x),'sha256':sha(x)} for x in index_files]})
            entities=sorted({r['entity_id'] for r in read(dataset/'records.json')['rows']})
            if source['company_id'] not in entities:entities.append(source['company_id'])
            bindings.append({'source_snapshot_id':sid,'company_id':source['company_id'],
                'entity_ids':entities,'content_sha256':source['source_sha256']})
            inputs.append({'path':relative(raw),'sha256':sha(raw),'source_snapshot_id':sid,'adapter':'us-gaap-inline-v1'})
    inventory_path=base/'builder-inputs/source-inventory.json'
    write_new(inventory_path,{'schema':'e6-r4-complete-explicit-source-inventory-v1','sources':inventory})
    spec_path=base/'builder-inputs/build-spec.json'
    write_new(spec_path,{'spec_version':'query-build-v1','source_inventory':{'path':relative(inventory_path),'sha256':sha(inventory_path)},
        'sources':bindings,'inputs':inputs})
    built=build_dataset(ROOT,base/'dataset',spec=spec_path)
    rows=read(base/'dataset/sources.json')
    totals={'sources':len(rows),'blocks':block_count,'html_tables':table_count,'records':built['record_count']}
    original_hashes={s['source_snapshot_id']:s['declared_content_sha256'] for s in inventory}
    preserved=(len(rows)==len(inventory) and all(s['source_sha256']==original_hashes[s['source_snapshot_id']]
        and sha(base/'dataset'/s['raw_file'])==s['source_sha256'] for s in rows))
    write_new(base/'scope.json',{'execution_schema_version':'research-execution-v1','snapshot_id':built['snapshot_id'],
        'company_ids':sorted({s['company_id'] for s in rows}),
        'source_snapshot_ids':sorted(s['source_snapshot_id'] for s in rows),
        'source_policy_id':'local-frozen-v1','knowledge_cutoff':'2026-02-06','include_candidates':True})
    audit_pins=[]
    for path in sorted(args.audit_root.glob('*.json')):
        if path.name.endswith(('-dom.json','-navigation.json')):
            audit_pins.append({'path':str(path.resolve()),'sha256':sha(path)})
    if len(audit_pins)!=4:raise ValueError('Both prior source DOM/navigation audits required')
    write_new(base/'preparation.v1.json',{'schema':'e6-r4-zero-api-complete-material-v1','source_datasets':source_pins,
        'dataset_manifest_sha256':sha(base/'dataset/manifest.json'),'scope_sha256':sha(base/'scope.json'),
        'source_original_audits':audit_pins,'counts':totals,'whole_sources':True,'semantic_selection':False,
        'model_calls':0,'new_network_calls':0,'ledger':str(ledger),'ledger_limit_usd':limit,'created_ledger':False,
        'passed':preserved,'all_source_bytes_preserved':preserved,
        'new_batch_not_original_lost_package':True})
    print(json.dumps({'path':str(base),'counts':totals,'dataset_manifest_sha256':sha(base/'dataset/manifest.json')},ensure_ascii=False))


if __name__=='__main__':main()
