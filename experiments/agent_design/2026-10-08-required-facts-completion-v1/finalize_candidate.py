"""Re-normalize untouched model output after a general header adapter fix; no API call."""
import json
from pathlib import Path

from uteki.agents.runtime.observation import observed_run
from uteki.agents.runtime.run_budget import RunBudget
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet, _write_projection
from uteki.infrastructure.research_data.direct_normalization import normalize_direct_candidates
from uteki.infrastructure.research_data.fact_completion import verify_completion_publication, claim_completion_successor
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def main():
    observations = ROOT/'data/agent_observations'
    published = {}
    for name, artifact in [('run-01','01-extract_batch/output.json'), ('run-02','01-repair_batch/output.json')]:
        published[name] = verify_completion_publication(HERE/name, observations,
            ['result.json','packet.json','method-snapshot.json',artifact])
    # Record that the already executed recovery consumed this failed run's one
    # successor. This sidecar sits outside the immutable historical run directory.
    claim = HERE/'run-01.completion-claim.json'
    if not claim.exists():
        claim_completion_successor(HERE/'run-01',HERE/'run-02',published['run-01'])
    else:
        assert json.loads(claim.read_text())['successor'] == str(HERE/'run-02')
    write_new(HERE/'published-provenance-check.json', {'verified': published,
        'basis':'original artifact.published hashes, not newly accepted current-byte hashes',
        'new_model_calls':0})
    dataset = ROOT/'data/company_workspace/official-filing-preparations/amd-v2/dataset'
    job = json.loads((HERE/'job-year-headers.json').read_text())
    packet = build_extraction_packet(dataset,job)
    previous_packet = json.loads((HERE/'run-02/packet.json').read_text())
    assert {k:v for k,v in packet.items() if k not in ('period_alias_adapter','packet_id','output_schema')} == {
        k:v for k,v in previous_packet.items() if k not in ('period_alias_adapter','packet_id','output_schema')}
    extraction_path = HERE/'run-02/extraction.json'
    verify_completion_publication(HERE/'run-02', observations, ['extraction.json'])
    extraction = json.loads(extraction_path.read_text())
    normalized = normalize_direct_candidates(extraction, packet)
    assert len(normalized['records']) == 6 and not normalized['unresolved']
    assert all(i['status']=='candidate_present' for i in normalized['fact_coverage']['requirements'])
    checks=[]
    table = next(b for b in packet['blocks'] if b.get('table'))
    cells = table['table']['cells']
    for row in normalized['records']:
        raw = row['origin']['raw']
        labels = [c for c in cells if c['text']==raw['metric']]
        headers = [c for c in cells if c['text']==raw['period']]
        assert len(labels)==1 and len(headers)==1
        label, header = labels[0],headers[0]
        values = [c for c in cells if c['row']==label['row'] and
                  header['column'] <= c['column'] < header['column']+header['colspan'] and c['text']==raw['value']]
        assert len(values)==1
        assert any(c['text']=='(In millions)' for c in cells)
        for eid in (*row['evidence_ids'],*row['qualifier_evidence_ids']):
            ref=normalized['evidence'][eid];block=next(b for b in packet['blocks'] if b['block_id']==ref['block_id'])
            assert block['text'][ref['source_start']:ref['source_end']]==ref['quote']
        checks.append({'record_id':row['record_id'],'metric_id':row['metric_id'],
            'period':row['period'],'raw_value':raw['value'],'value_decimal':row['value_decimal'],
            'unit':row['unit'],'source_row':label['row'],'source_column':values[0]['column'],
            'row_header_and_period_column':'matched','scale_caption':'In millions',
            'evidence_offsets':'matched'})
    output=HERE/'run-03-normalized'
    with observed_run(output=output,kind='extraction',role='validator',origin='deterministic_replay',
            observation_root=observations,scope=job,title='Re-normalize original model facts with verified annual headers',
            protected=(dataset,)) as observer:
        output.mkdir()
        write_new(output/'packet.json',packet);write_new(output/'job.json',job)
        write_new(output/'extraction.json',extraction);write_new(output/'normalized.json',normalized)
        write_new(output/'source-cell-check.json',{'checks':checks,'scope':'six selected financial cells only',
            'accounting_framework':'not_stated_in_delivered_scope','whole_report_quality':'not_evaluated'})
        write_new(output/'lineage.json',{'model_run':'run-02','extraction_sha256':digest(extraction_path.read_bytes()),
            'model_output_changed':False,'new_model_calls':0,'period_alias_adapter':'table-year-header-v1',
            'normalizer_sha256':digest((ROOT/'src/uteki/infrastructure/research_data/direct_normalization.py').read_bytes()),
            'original_publication_verified':True})
        projection=_write_projection(dataset,output,packet,normalized,output/'dataset')
        summary={'status':'candidate','origin':'deterministic_replay','trace_id':observer.run_id,
            'model_origin_trace_id':json.loads((HERE/'run-02/result.json').read_text())['trace_id'],
            'required_fact_count':6,'present_fact_count':6,'unresolved_count':0,
            'source_cell_checks':'six_passed','semantic_acceptance':'bounded_table_cells_checked',
            'whole_report_acceptance':'not_evaluated','fact_coverage':normalized['fact_coverage']['status'],
            'new_model_calls':0,'task_budget':RunBudget(HERE/'run-01/budget.sqlite',3,allow_unknown_reservations=True).summary(),
            'dataset_snapshot_id':projection['snapshot_id']}
        write_new(output/'result.json',summary)
        write_new(output/'manifest.json',{'files':{str(p.relative_to(output)):digest(p.read_bytes()) for p in output.rglob('*') if p.is_file()}})
    print(json.dumps(summary))


if __name__=='__main__': main()
