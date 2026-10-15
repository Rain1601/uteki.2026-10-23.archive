"""A process exit during answer/child creation cannot fork a second successor."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService
from uteki.data_platform.contracts.common import canonical
from uteki.data_platform.contracts.content import ObjectRef

ROOT=Path(__file__).resolve().parents[3]


class ClarificationProcessTests(unittest.TestCase):
    def test_answer_and_child_creation_interruptions_keep_one_root_and_one_successor(self):
        cls=runpy.run_path(str(ROOT/'tests/unit/data_platform/test_queries.py'))['DataToolTests']
        for phase in ('clarification_answer_registered','context_prepared','context_head_written','context_mapping_written'):
            with self.subTest(phase=phase):
                f=cls();f.setUp()
                try:
                    response=f.service.clarify(f.context,dict(question='Which period?',blocking_need_ids=['need-1']),
                        state=f.state('clarify'),request_key='question')
                    parent=f.service.inspect_context(f.context)
                    answer=dict(f.request,revises_context_ref=f.context,clarification_response=dict(
                        clarification_id=response['clarification']['clarification_id'],answer='Same scope.'))
                    invocation=dict(method='create_context',request=answer,request_key='first-answer')
                    path=f.root/'child-invocation.json';path.write_text(json.dumps(invocation));f.catalog.close()
                    child=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/tools_worker.py'),
                        str(f.root),str(path),phase],cwd=f.root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(child.returncode,73,child.stderr[-3000:])
                    with Catalog.open(f.root) as catalog:
                        service=DataService(catalog)
                        resumed=service.create_context(answer,request_key='different-transport-key',recover=True)
                        self.assertEqual(service.create_context(answer,request_key='first-answer'),resumed)
                        self.assertEqual(resumed['root_run_id'],parent['context']['root_run_id'])
                        self.assertEqual(service.inspect_context(resumed['context_ref'])['turns'],parent['turns'])
                        count=catalog._db.execute('SELECT count(*) FROM runs WHERE parent_run_id=?',(parent['context']['run_id'],)).fetchone()[0]
                        self.assertEqual(count,1)
                        self.assertEqual(catalog.content.read_object(ObjectRef.model_validate(response['clarification_object'])),canonical(response['clarification']))
                finally:f.doCleanups()


if __name__=='__main__':unittest.main()
