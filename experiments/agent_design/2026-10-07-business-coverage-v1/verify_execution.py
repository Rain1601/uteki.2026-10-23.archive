"""Read-only verification of actual model inputs and immutable stage bindings."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'src'))
from uteki.agents.business_map import product_run as base, coverage_contract as c
from uteki.agents.runtime.strict_json import parse_json_object
from uteki.agents.business_map.evidence_projection import project_relationship_evidence


def main():
    folder=Path(sys.argv[1]).resolve()
    if not folder.is_relative_to(ROOT):raise ValueError('scope')
    summary=json.loads((folder/'summary.json').read_text())
    original=ROOT/summary['input_run'];draft=json.loads((original/'draft.json').read_text())
    packet=json.loads((original/'source_packet.json').read_text());inventory=audit=None;checks=[]
    if summary.get('execution_mode')=='authorized_single_coverage_continuation':
        prior=json.loads((ROOT/summary['prior_run']/'summary.json').read_text())
        candidate=ROOT/summary['input_candidate_path']
        assert summary['input_candidate_path']==prior['candidate_path']
        draft=json.loads((candidate/'draft.json').read_text())
        assert c.canonical_hash(draft)==summary['input_candidate_sha256']==prior['candidate_sha256']
        audit_path=ROOT/summary['input_audit_path']
        assert base.digest(audit_path.read_bytes())==summary['input_audit_sha256']
        audit=json.loads(audit_path.read_text())
        assert audit['candidate_sha256']==c.canonical_hash(draft)
    for a in summary['attempts']:
        d=ROOT/a['path']
        if not (d/'manifest.json').exists():
            # The first recovery's final audit predates complete stage manifests.
            # Verify the actual request against frozen inputs without fabricating one.
            assert a['mode']=='audit_final' and summary['execution_mode']=='completed_revision_index_projection_and_final_audit'
            from uteki.agents.business_map.coverage_run import verify_published_artifacts, AUDIT, COMMON, _json
            verified=verify_published_artifacts(root=ROOT,observation_root=ROOT/'data/agent_observability/local',
                stage=d,trace_id=a['trace_id'],relative_paths=['request.json','configuration.json','output_schema.json','response.txt','response_metadata.json'])
            req=json.loads((d/'request.json').read_text());payload=parse_json_object(req['messages'][0]['content'])
            assert set(payload)=={'frozen_source_packet','source_inventory','own_candidate','candidate_sha256','inventory_sha256','check_targets'}
            assert payload==dict(frozen_source_packet=packet,source_inventory=inventory,own_candidate=draft,
                candidate_sha256=c.canonical_hash(draft),inventory_sha256=c.canonical_hash(inventory),check_targets=c.check_targets(draft))
            assert req['system']==AUDIT+COMMON.format(skill=(original/'skill.md').read_text(),schema=_json(c.Audit.model_json_schema()))
            if a['status']=='completed':
                validated=c.validate_audit(parse_json_object((d/'response.txt').read_text()),packet,inventory,draft)
                final=json.loads((d/'audit.json').read_text())
                assert all(final[k]==v for k,v in validated.items() if k not in ('computed_status','gaps'))
            checks.append(dict(stage=a['mode'],status=a['status'],actual_payload_verified=True,
                request_sha256=base.digest((d/'request.json').read_bytes()),stage_manifest='not_recorded_in_first_recovery',published_hashes=verified))
            continue
        m=json.loads((d/'manifest.json').read_text())
        req=(d/'request.json').read_bytes();payload=json.loads(json.loads(req)['messages'][0]['content'])
        assert base.digest(req)==m['request_sha256']
        assert payload['frozen_source_packet']==packet
        assert m['source_packet_sha256']==base.digest((original/'source_packet.json').read_bytes())
        assert (d/'skill.md').read_bytes()==(original/'skill.md').read_bytes()
        for path,expected in m['dependencies_sha256'].items():assert base.digest((ROOT/path).read_bytes())==expected
        expected={'frozen_source_packet','source_packet_sha256'} if a['mode']=='inventory' else (
            {'frozen_source_packet','source_inventory','own_candidate','own_audit'} if a['mode']=='revision' else
            {'frozen_source_packet','source_inventory','own_candidate','candidate_sha256','inventory_sha256','check_targets'})
        assert set(payload)==expected
        if summary.get('execution_mode')=='authorized_single_coverage_continuation' and a['mode']!='inventory':
            from uteki.agents.business_map.coverage_run import REVISE, AUDIT, COMMON, _json
            from uteki.agents.business_map.coverage_continuation import REVISION_INSTRUCTION
            system=(REVISION_INSTRUCTION if a['mode']=='revision' else AUDIT)+COMMON.format(
                skill=(original/'skill.md').read_text(),schema=_json(json.loads((d/'output_schema.json').read_text())))
            assert json.loads(req)['system']==system
        if a['mode']!='inventory':
            assert payload['own_candidate']==draft and payload['source_inventory']==inventory
        if a['mode']=='revision':assert payload['own_audit']==audit
        if a['mode'].startswith('audit'):
            assert payload['candidate_sha256']==c.canonical_hash(draft)
            assert payload['inventory_sha256']==c.canonical_hash(inventory)
            assert payload['check_targets']==c.check_targets(draft)
        if a['status'] in ('completed','candidate'):
            raw=parse_json_object((d/'response.txt').read_text())
            if a['mode']=='inventory':
                repair=d/'contract-repair'
                reused=m.get('reused_stage_response',{})
                if reused.get('validated_inventory_artifact'):
                    parent_inventory=ROOT/reused['path']/'inventory.json'
                    assert m['dependencies_sha256'][str(parent_inventory.relative_to(ROOT))]==base.digest(parent_inventory.read_bytes())
                    inventory=c.validate_inventory(json.loads(parent_inventory.read_text()),packet)
                elif repair.exists():
                    req=json.loads((repair/'request.json').read_text())
                    p=json.loads(req['messages'][0]['content'])
                    diagnostics=c.inventory_contract_errors(raw,packet)
                    assert set(p)=={'frozen_source_packet','inventory_sha256','source_packet_sha256','error_mentions','validation_errors'}
                    assert p['frozen_source_packet']==packet and p['validation_errors']==diagnostics
                    assert p['inventory_sha256']==c.canonical_hash(raw)
                    assert p['source_packet_sha256']==c.canonical_hash(packet)
                    assert p['error_mentions']==[m for m in raw['mentions'] if m['id'] in diagnostics['error_mention_ids']]
                    inventory=c.apply_inventory_repair(raw,packet,parse_json_object((repair/'response.txt').read_text()))
                else:inventory=c.validate_inventory(raw,packet)
                assert inventory==json.loads((d/'inventory.json').read_text())
            elif a['mode']=='revision':
                if m.get('execution_mode')=='deterministic_evidence_index_projection':
                    assert m['model_calls_in_this_trace']==0
                    assert m['original_response_sha256']==base.digest((d/'response.txt').read_bytes())
                    raw,projection=project_relationship_evidence(raw,packet,expected_version=m['source_business_contract_version'])
                    assert projection==json.loads((d/'projection.json').read_text())
                    assert raw==json.loads((d/'projected-raw.json').read_text())
                elif (d/'projection.json').exists():
                    raw,projection=project_relationship_evidence(raw,packet,expected_version=m['source_business_contract_version'])
                    assert projection==json.loads((d/'projection.json').read_text())
                draft=base.validate_draft(raw,packet,expected_version=m['source_business_contract_version']).model_dump()
                assert draft==json.loads((d/'draft.json').read_text())
            else:
                validated=c.validate_audit(raw,packet,inventory,draft);audit=json.loads((d/'audit.json').read_text())
                assert all(audit[k]==v for k,v in validated.items() if k not in ('computed_status','gaps'))
        checks.append({'stage':a['mode'],'status':a['status'],'actual_payload_verified':True,'request_sha256':m['request_sha256']})
    report={'status':'passed','source_blocks':len(packet['blocks']),'actual_stage_checks':checks,
        'reference_or_human_feedback_input':False,'raw_responses_preserved':True,
        'semantic_acceptance':'not_established_by_this_check','summary_sha256':base.digest((folder/'summary.json').read_bytes())}
    out=folder/'execution-isolation.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
