"""Native envelope enforces wire shape; original decision validation stays local."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx2 as httpx
from agents import AgentOutputSchema, ModelSettings
from agents.exceptions import ModelBehaviorError
from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.agents.runtime.claude_messages import ClaudeMessagesModel, decision_envelope_schema, decode_decision_envelope, _canonical, _sha
from uteki.agents.runtime.model_configuration import validate_configuration_snapshot
from uteki.agents.runtime.strict_json import StrictJSONError


def envelope(action='discover_catalog', payload=None, **changes):
    return {'action':action,'requirement_ids':[], 'reason':None,
            'payload_json':json.dumps({'kind':'sources'} if payload is None else payload), **changes}


class ClaudeDecisionEnvelopeTests(unittest.TestCase):
    def kwargs(self):
        return dict(system_instructions='Select the next host action.', input='Inspect sources.',
            model_settings=ModelSettings(max_tokens=1024), tools=[],
            output_schema=AgentOutputSchema(AutonomousDecision, strict_json_schema=False), handoffs=[])

    def run_wire(self, text, *, protocol='native_decision_envelope'):
        self.requests=[]
        def respond(request):
            self.requests.append(request)
            return httpx.Response(200,json={'id':'msg_fixture','model':'claude-sonnet-5-5','stop_reason':'end_turn',
                'usage':{'input_tokens':12,'output_tokens':24},
                'content':[{'type':'thinking','thinking':'DO_NOT_SAVE'}, {'type':'text','text':text}]})
        def factory(**kwargs):
            kwargs['transport']=httpx.MockTransport(respond)
            return httpx.AsyncClient(**kwargs)
        async def run():
            self.model=ClaudeMessagesModel('claude-sonnet-5-5',timeout_seconds=30,
                schema_protocol=protocol,client_factory=factory)
            try:
                return await self.model.get_response(**self.kwargs())
            finally:
                await self.model.aclose()
        with patch.dict(os.environ,{'AIHUBMIX_API_KEY':'offline-envelope-secret'}):
            return asyncio.run(run())

    def test_exact_native_wire_and_decoded_sdk_response_keep_distinct_texts(self):
        raw=json.dumps(envelope())
        result=self.run_wire(raw)
        wire=json.loads(self.requests[0].content)
        self.assertEqual(wire['output_config']['format'],{'type':'json_schema','schema':decision_envelope_schema()})
        self.assertEqual(wire['output_config']['effort'],'high')
        self.assertIn('Original host decision JSON Schema',wire['system'])
        self.assertNotIn('tools',wire)
        self.assertEqual(self.model.response_text,raw)
        host=json.loads(result.output[0].content[0].text)
        self.assertEqual(host,{'action':'discover_catalog','catalog':{'kind':'sources'},'requirement_ids':[],'reason':None})
        AutonomousDecision.model_validate(host)
        self.assertEqual(self.model.response_metadata['transport_decode'],'decoded')
        self.assertEqual(self.model.response_metadata['host_schema_validation'],'passed')
        self.assertEqual(self.model.response_metadata['provider_enforced_schema'],'decision_envelope_only')
        self.assertNotIn('DO_NOT_SAVE',json.dumps(self.model.response_metadata)+self.model.response_text)

    def test_configuration_records_provider_wire_schema_not_host_schema(self):
        model=ClaudeMessagesModel('claude-sonnet-5-5',timeout_seconds=30,schema_protocol='native_decision_envelope')
        snapshot=model.request_configuration(**self.kwargs())
        validate_configuration_snapshot(snapshot)
        self.assertEqual(snapshot['fields']['response_format'],{'value':{'type':'json_schema'},
            'status':'explicit','source':'http_request.output_config.format'})
        self.assertEqual(snapshot['fingerprints']['output_schema_sha256'],_sha(_canonical(decision_envelope_schema())))
        schema=decision_envelope_schema()
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(sum('anyOf' in p for p in schema['properties'].values()),2)

    def test_array_and_string_payloads_decode_to_original_action_field(self):
        examples=[('plan',[{'kind':'source_evidence','requirement_id':'r','source_id':'s','description':'Source evidence'}],'requirements'),
                  ('reread',['evidence-a'],'evidence_ids'),('load_skill','query','skill')]
        for action,payload,field in examples:
            with self.subTest(action=action):
                value=envelope(action,payload,reason='Read relevant material.',requirement_ids=['r'] if action=='reread' else [])
                decoded=json.loads(decode_decision_envelope(json.dumps(value)))
                self.assertEqual(decoded[field],payload)
                AutonomousDecision.model_validate(decoded)

    def test_finish_requires_null_payload_and_keeps_no_payload_field(self):
        valid=envelope('finish',payload_json=None)
        result=self.run_wire(json.dumps(valid))
        self.assertEqual(json.loads(result.output[0].content[0].text)['action'],'finish')
        with self.assertRaises(StrictJSONError):
            decode_decision_envelope(json.dumps(envelope('finish',{})))

    def test_malformed_wire_and_payloads_are_not_repaired(self):
        cases=[ '<invoke name="discover_catalog"/>',
                json.dumps(envelope())+' trailing',
                json.dumps(envelope(action='unknown')),
                json.dumps(envelope(extra='not allowed')),
                json.dumps(envelope(reason=12)),
                json.dumps(envelope(requirement_ids=[12])),
                json.dumps(envelope(payload_json=None)),
                json.dumps(envelope(payload_json='<invoke/>')),
                json.dumps(envelope(payload_json='{"kind":"sources","kind":"entities"}')),
                json.dumps(envelope(payload_json='{"limit":NaN}')),
                json.dumps(envelope(payload_json='{},"injected":true'))]
        for text in cases:
            with self.subTest(text=text),self.assertRaises(ModelBehaviorError):
                self.run_wire(text)
            self.assertEqual(self.model.response_text,text)
            self.assertEqual(self.model.response_metadata['transport_decode'],'rejected')
            self.assertEqual(self.model.response_metadata['raw_usage'],{'input_tokens':12,'output_tokens':24})

    def test_semantic_action_constraints_still_fail_local_validation(self):
        # Valid outer JSON does not make a query action without references valid.
        with self.assertRaises(ModelBehaviorError):
            self.run_wire(json.dumps(envelope('read_context',{'source_snapshot_id':'s','block_id':'b'})))
        self.assertEqual(self.model.response_metadata['transport_decode'],'decoded')
        self.assertEqual(self.model.response_metadata['host_schema_validation'],'rejected')

    def test_unencodable_unicode_is_a_fixed_error_without_raw_exception_context(self):
        raw = json.dumps(envelope('load_skill', payload_json='"private-marker-\\ud800"'))
        with self.assertRaises(StrictJSONError) as raised:
            decode_decision_envelope(raw)
        self.assertEqual(raised.exception.code, 'invalid_decision_unicode')
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn('private-marker', str(raised.exception))
        with self.assertRaises(ModelBehaviorError):
            self.run_wire(raw)
        self.assertEqual(self.model.response_metadata['transport_decode'], 'rejected')
        self.assertEqual(self.model.response_metadata['transport_decode_error'], 'invalid_decision_unicode')
        self.assertEqual(self.model.response_metadata['raw_usage'], {'input_tokens':12,'output_tokens':24})

    def test_legacy_host_mode_does_not_silently_enable_native_format(self):
        self.run_wire('{"action":"load_skill","skill":"query"}',protocol='host_decision')
        self.assertNotIn('format',json.loads(self.requests[0].content)['output_config'])


if __name__=='__main__':unittest.main()
