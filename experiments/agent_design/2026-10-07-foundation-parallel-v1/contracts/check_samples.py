"""Read-only contract and provenance checks of explicitly selected historical samples."""
from pathlib import Path
import hashlib
import json
import sys
import re

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
import jsonschema
from uteki.domain.business_map import business_map_from_dict
from uteki.domain.research_data.query_contract import ResearchRecord
from uteki.agents.business_map.product_contract import validate_draft
from uteki.presentation.business_map_view import mermaid

OUT = Path(__file__).resolve().parent
BASE = ROOT / 'experiments/agent_design/2026-10-07-data-foundation-v1'
RUN = ROOT / 'experiments/agent_design/2026-10-07-microsoft-agent-independent-v1/self-review-01/revision'
def read(p): return json.loads(p.read_text())
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
checks = []
def check(name, action):
    try:
        detail = action()
        checks.append(dict(name=name, status='passed', detail=detail))
    except Exception as exc:
        checks.append(dict(name=name, status='failed', error=f'{type(exc).__name__}: {exc}'))
def require(value, message):
    if not value: raise ValueError(message)
    return True
sample = read(BASE / 'product-samples.json')
check('historical_sample_sources_still_match_saved_hashes', lambda: require(all(
    digest(ROOT / item['path']) == item['sha256'] for item in sample['source_files']), 'source_hash_mismatch'))
check('amd_numeric_current_research_record_contract', lambda: bool(ResearchRecord.model_validate(sample['numeric_historical_candidate'])))
for key, schema in [('numeric_historical_candidate','numeric-fact.schema.json'),('brief_design_example','brief-example.schema.json')]:
    def validate(key=key,schema=schema):
        jsonschema.Draft202012Validator(read(BASE/'schemas'/schema)).validate(sample[key]); return True
    check(key+'_frozen_schema', validate)
check('amd_design_map_legacy_contract', lambda: bool(business_map_from_dict(sample['business_map_design_example'])))
blocks = {b['block_id']:b for b in sample['raw_blocks']}
check('brief_design_example_scope_and_references', lambda: require(
    sample['brief_design_example']['coverage']=='partial' and
    sample['brief_design_example']['presentation_status']=='design_example' and
    all(b in blocks for sentence in sample['brief_design_example']['sentences'] for b in sentence['evidence_block_ids']), 'brief_scope_or_reference_mismatch'))
packet=read(RUN/'source_packet.json'); draft=read(RUN/'draft.json'); business=read(RUN/'business_map.json')
check('msft_independent_draft_current_source_contract', lambda: bool(validate_draft(draft,packet)))
check('msft_independent_business_map_current_domain', lambda: bool(business_map_from_dict(business)))
def render_check():
    text, view=mermaid(business)
    return require(len(view['ids'])==len(business['businesses']) and text.startswith('flowchart LR'), 'render_mapping_failure')
check('msft_independent_mermaid_consumer_all_nodes', render_check)
def links():
    targets=re.findall(r'\]\(([^)]+)\)', (OUT/'README.zh-CN.md').read_text())
    missing=[x for x in targets if not x.startswith(('http:','https:')) and x!='sample-check.json' and not (OUT/x).resolve().exists()]
    return require(not missing, 'broken_document_links: '+repr(missing))
check('contract_document_links_exist',links)
files=[BASE/'product-samples.json',RUN/'draft.json',RUN/'source_packet.json',RUN/'business_map.json']
report=dict(kind='historical_sample_contract_and_provenance_check',model_calls=0,
  current_todo05_status='partial',semantic_acceptance='not_established_by_this_check',
  five_company_end_to_end='not_run',
  samples=[dict(path=str(p.relative_to(ROOT)),sha256=digest(p)) for p in files],
  checks=checks,all_checks_passed=all(x['status']=='passed' for x in checks),
  limitations=['AMD brief and business map are hand-built design examples.',
   'Microsoft independent candidate still has known semantic gaps despite valid contracts.',
   'No new model invocation or fresh document acquisition.'])
(OUT/'sample-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['all_checks_passed'] else 1)
