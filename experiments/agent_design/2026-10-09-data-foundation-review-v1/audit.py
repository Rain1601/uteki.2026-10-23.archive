"""Read-only audit of explicitly selected frozen retrieval inputs; no model/network."""
import json
from pathlib import Path
from collections import Counter
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.document_sources.parsed_package import verify_parsed_package
from uteki.infrastructure.research_data.financial_records import digest
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
CASES=[('msft','experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/dataset'),('googl','data/company_workspace/extraction_ab_v1/corpus/googl/dataset'),('amd','experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-amd/dataset')]
results=[]
for key,relative in CASES:
 dataset=ROOT/relative
 manifest=_verify_manifest(dataset)
 sources=json.loads((dataset/'sources.json').read_text())
 row={'case':key,'dataset':relative,'dataset_manifest_sha256':digest((dataset/'manifest.json').read_bytes()),'snapshot_id':manifest.get('snapshot_id'),'verified_dataset_files':len(manifest['files']),'sources':[]}
 with QueryDataPort(dataset) as port:
  row['record_counts_by_source']=[list(r) for r in port._db.execute('SELECT source_snapshot_id, count(*) FROM observations GROUP BY source_snapshot_id').fetchall()]
  row['orphan_source_records']=port._db.execute('SELECT count(*) FROM observations o LEFT JOIN sources s USING(source_snapshot_id) WHERE s.source_snapshot_id IS NULL').fetchone()[0]
  row['metric_descriptions']=port.metrics
 for source in sources:
  package=dataset/source['index_folder'];reader=DocumentReader(package)
  package_verified=False
  if (package/'source.json').exists():
   verify_parsed_package(package,expected_source={'company_id':source['company_id'],'document_id':source['document_id'],'source_snapshot_id':source['source_snapshot_id'],'raw_sha256':source['source_sha256'],'source_url':source['source_url'],'form_type':source['form'],'report_period_end':source['period_end'],'available_at':source['available_at'],'parser_version':reader.index['parser_version'],'export_version':'uteki-parsed-document-v1'})
   package_verified=True
  old=json.loads((ROOT/'experiments/agent_design/2026-10-08-tenk-section-coverage-v1'/f'{key}-coverage.json').read_text())
  audited=ROOT/old['package_path']
  row['sources'].append({'source_snapshot_id':source['source_snapshot_id'],'company_id':source['company_id'],'source_sha256':source['source_sha256'],'parser_version':reader.index['parser_version'],'block_count':len(reader.blocks),'node_kinds':dict(Counter(n['kind'] for n in reader.index['nodes'])),'diagnostics':reader.index.get('diagnostics',[]),'raw_matches_prior_audit':source['source_sha256']==old['source']['raw_sha256'],'index_matches_prior_audit':digest((package/'index.json').read_bytes())==digest((audited/'index.json').read_bytes()),'blocks_match_prior_audit':digest((package/'blocks.jsonl').read_bytes())==digest((audited/'blocks.jsonl').read_bytes()),'prior_audit_applies_to_same_original':source['source_sha256']==old['source']['raw_sha256'],'prior_audited_parser':old['source']['parser_version'],'stage_coverage':source.get('stage_coverage'), 'package_verified':package_verified})
 row['input_manifest_unchanged']=row['dataset_manifest_sha256']==digest((dataset/'manifest.json').read_bytes())
 results.append(row)
(HERE/'verification.json').write_text(json.dumps({'model_calls':0,'inputs_modified':False,'cases':results},ensure_ascii=False,indent=2)+'\n')
for row in results:
 print(row['case'],[(s['parser_version'],s['block_count'],s['index_matches_prior_audit'],s['blocks_match_prior_audit']) for s in row['sources']],row['record_counts_by_source'])
