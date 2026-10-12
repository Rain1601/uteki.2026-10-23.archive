"""Challenge the independent auditor against deliberately damaged package copies."""
import argparse,copy,hashlib,json,shutil,tempfile
from pathlib import Path
from audit_dom import audit

def hashes(root):
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

def main(dataset):
 source=json.loads((dataset/'sources.json').read_text())[0];raw=dataset/source['raw_file'];package=dataset/source['index_folder'];before=hashes(dataset)
 blocks=list(map(json.loads,(package/'blocks.jsonl').read_text().splitlines()))
 pi=next(i for i,b in enumerate(blocks) if b['type']=='paragraph' and len(b['text'])>200)
 ti=next(i for i,b in enumerate(blocks) if b.get('table') and len(b['table']['cells'])>10)
 tests=[]
 for kind in ('removed_prose_block','duplicated_prose_block','altered_table_cell'):
  with tempfile.TemporaryDirectory(prefix='uteki-eval-mutation-') as td:
   work=Path(td)/'package';shutil.copytree(package,work);changed=copy.deepcopy(blocks)
   if kind=='removed_prose_block':changed.pop(pi);field='omitted_text_nodes';target=blocks[pi]['block_id']
   elif kind=='duplicated_prose_block':changed.insert(pi,copy.deepcopy(changed[pi]));field='multiply_represented_text_nodes';target=blocks[pi]['block_id']
   else:
    changed[ti]['table']['cells'][0]['text']='INTENTIONALLY WRONG EVALUATION CELL';field='table_errors';target=blocks[ti]['block_id']
   (work/'blocks.jsonl').write_text(''.join(json.dumps(b,ensure_ascii=False)+'\n' for b in changed));r=audit(raw,work)
   tests.append(dict(mutation=kind,source_block=target,expected_error_field=field,detected_count=len(r[field]),structural_pass=r['structural_pass'],passed=bool(r[field]) and not r['structural_pass']))
 return dict(schema='independent-audit-mutation-check-v1',dataset=str(dataset),tests=tests,original_dataset_unchanged=before==hashes(dataset),passed=all(t['passed'] for t in tests) and before==hashes(dataset))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=main(a.dataset);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False));assert r['passed']
