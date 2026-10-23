"""Opaque reasoning belongs to the exact durable model/tool response."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from uteki.data_platform.agent.providers.openrouter_evidence import capture_response
from uteki.data_platform.agent.providers.openrouter_reasoning import restore_reasoning
from uteki.data_platform.contracts.common import CatalogError, canonical


class OpenRouterReasoningTests(unittest.TestCase):
    def fixture(self):
        details=[dict(type='reasoning.text',text='Synthetic protocol fixture.',signature='fixture-signature',
                      format='anthropic-claude-v1',index=0),
                 dict(type='reasoning.encrypted',data='fixture-ciphertext',format='anthropic-claude-v1',index=1)]
        message=dict(role='assistant',content=None,reasoning_details=details,
                     tool_calls=[dict(id='fixture-call',type='function',function=dict(name='echo',arguments='{"value":"fixture"}'))])
        response=canonical(dict(model='model-fixture',choices=[dict(index=0,message=message)]))
        capture=capture_response('chat_completions',200,[('content-type','application/json')],[response],max_bytes=10000)
        record=dict(stage='responded',cost_state='settled',request={'context_ref':'run-one'},
                    response_event={'response':dict(complete=True,http=capture)})
        history=[dict(request_key='first',request_ref='original')]
        journal=SimpleNamespace(profile=dict(model_id='model-fixture',route=dict(provider='openrouter')),
            budget=SimpleNamespace(inspect_request=lambda key:deepcopy(record)),
            session=lambda:SimpleNamespace(data={'native_execution':{'openai_requests':history}}))
        state=SimpleNamespace(journal=journal,cursor=1,read=lambda ref:dict(context_ref='run-one'),
                              record_matches=lambda saved,request:saved['request']==request)
        replay=deepcopy(message);replay.pop('reasoning_details')
        body=dict(model='model-fixture',messages=[replay,dict(role='tool',tool_call_id='fixture-call',content='fixture')])
        return state,record,body,details

    def test_preserves_original_array_and_is_idempotent_without_process_cache(self):
        state,record,body,details=self.fixture()
        raw=canonical(body)
        restored=restore_reasoning(raw,state)
        self.assertEqual(json.loads(restored)['messages'][0]['reasoning_details'],details)
        self.assertEqual(restore_reasoning(restored,state),restored)
        fresh,*_=self.fixture()
        self.assertEqual(restore_reasoning(raw,fresh),restored)
        self.assertNotIn('reasoning_details',body['messages'][0])

    def test_missing_conflicting_reordered_or_changed_tool_history_fails(self):
        for change in ('missing','duplicate','arguments','content','signature','model'):
            with self.subTest(change=change):
                state,record,body,details=self.fixture()
                if change=='missing':body['messages']=[]
                if change=='duplicate':body['messages'].append(deepcopy(body['messages'][0]))
                if change=='arguments':body['messages'][0]['tool_calls'][0]['function']['arguments']='{}'
                if change=='content':body['messages'][0]['content']='Different text'
                if change=='signature':body['messages'][0]['reasoning_details']=list(reversed(details))
                if change=='model':body['model']='another-model'
                with self.assertRaisesRegex(CatalogError,'RECOVERY_REQUIRED'):
                    restore_reasoning(canonical(body),state)

    def test_foreign_incomplete_unknown_or_corrupt_receipt_never_supplies_reasoning(self):
        for change in ('context','incomplete','unknown-cost','corrupt'):
            with self.subTest(change=change):
                state,record,body,details=self.fixture()
                if change=='context':record['request']['context_ref']='another-run'
                if change=='incomplete':record['response_event']['response']['complete']=False
                if change=='unknown-cost':record['cost_state']='unknown'
                if change=='corrupt':record['response_event']['response']['http']['body_sha256']='0'*64
                with self.assertRaisesRegex(CatalogError,'RECOVERY_REQUIRED'):
                    restore_reasoning(canonical(body),state)

    def test_unconsumed_receipts_and_other_provider_leave_wire_bytes_unchanged(self):
        state,record,body,details=self.fixture()
        raw=json.dumps(body,indent=4).encode()+b'\n'
        state.cursor=0
        self.assertEqual(restore_reasoning(raw,state),raw)
        state.cursor=1;state.journal.profile['route']['provider']='deepseek'
        self.assertEqual(restore_reasoning(raw,state),raw)


if __name__=='__main__':unittest.main()
