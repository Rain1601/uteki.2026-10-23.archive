"""Navigation omission must preserve review body traversal and reject stalls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from uteki.agents.data_query.answer_handoff import _source_documents
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import pin_dataset


class AnswerHandoffNavigationTests(unittest.TestCase):
    def test_real_reader_traverses_final_layout_only_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            make_scoped_dataset(root)
            folder=root/'indexes/acme-annual'
            data=[{'block_id':f'b{i}','type':'paragraph','text':f'Independent body {i}.','reported_page':'1','layout_role':None} for i in range(12)]
            data.append({'block_id':'b12','type':'paragraph','text':'Table of Contents','reported_page':'1','layout_role':'repeated_navigation'})
            (folder/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in data))
            index=json.loads((folder/'index.json').read_text())
            index['nodes']=[{'node_id':'root','kind':'document','start_block_id':'b0','end_block_id':'b12'}]
            index['parser_version']='sec-source-blocks-v0.1.9'
            (folder/'index.json').write_text(json.dumps(index))
            manifest=json.loads((folder/'manifest.json').read_text())
            manifest['parser_version']='sec-source-blocks-v0.1.9'
            for name in ('index.json','blocks.jsonl'):
                manifest['artifacts'][name]['sha256']=digest((folder/name).read_bytes())
            (folder/'manifest.json').write_text(json.dumps(manifest))
            pin_dataset(root)
            scope=ExecutionScope(snapshot_id='synthetic-scoped-v1',company_ids=('acme',),source_snapshot_ids=('acme-annual',),source_policy_id='local-frozen-v1',knowledge_cutoff='2032-06-01',include_candidates=True)
            with QueryDataPort(root) as owner:
                documents=_source_documents(owner.scoped(scope),scope,1_000_000)
            self.assertEqual([b['block_id'] for b in documents[0]['blocks']],[f'b{i}' for i in range(12)])
            self.assertEqual(documents[0]['omitted_navigation_block_ids'],['b12'])
            self.assertEqual(documents[0]['coverage'],'full_indexed_text_except_repeated_navigation')

    def fake(self, pages):
        class Port:
            def outline_source(self, request):
                return {'status':'available','nodes':[{'kind':'document','node_id':'root'}], 'index_id':'i','source_sha256':'hash','company_id':'synthetic','available_at':'2032-01-01'}
            def read_source(self, request):
                return deepcopy(pages.pop(0) if len(pages)>1 else pages[0])
        return Port()

    def test_repeated_layout_page_is_not_progress(self):
        page={'status':'layout_only','blocks':[],'omitted_block_ids':['nav'],'not_disclosed':False,'gaps':[],'next_cursor':{'start_block_id':'nav'}}
        with self.assertRaisesRegex(ValueError,'no progress'):
            _source_documents(self.fake([page]),SimpleNamespace(source_snapshot_ids=['s']),1000)

    def test_empty_or_unverified_omission_cannot_complete_review(self):
        for page in [
            {'status':'layout_only','blocks':[],'omitted_block_ids':[],'not_disclosed':False,'gaps':[]},
            {'status':'layout_only','blocks':[],'omitted_block_ids':['nav'],'gaps':[]},
            {'status':'layout_only','blocks':[],'omitted_block_ids':['nav'],'not_disclosed':False,'gaps':[]},
        ]:
            with self.subTest(page=page), self.assertRaises(ValueError):
                _source_documents(self.fake([page]),SimpleNamespace(source_snapshot_ids=['s']),1000)

    def test_cursor_stall_with_new_omissions_still_fails(self):
        pages=[{'status':'layout_only','blocks':[],'omitted_block_ids':[bid],'not_disclosed':False,'gaps':[],'next_cursor':{'start_block_id':'same'}} for bid in ('nav1','nav2')]
        with self.assertRaisesRegex(ValueError,'repeated a cursor'):
            _source_documents(self.fake(pages),SimpleNamespace(source_snapshot_ids=['s']),1000)

if __name__=='__main__':unittest.main()
