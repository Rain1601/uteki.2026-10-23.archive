"""Reject an observed native reasoning mismatch before live dispatch."""
import json
from pathlib import Path
import runpy
import time
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
from uteki.data_platform.application.gateway_batch import load_gateway_binding
from uteki.data_platform.application.session import Session

ROOT=Path(__file__).resolve().parents[3]
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/gateway_peer.py'))


class GatewayReasoningTests(unittest.TestCase):
    def test_missing_thinking_plus_effort_is_diagnostic_only_and_never_live_admitted(self):
        case,args,bindings=F['fixture']();self.addCleanup(case.doCleanups)
        scope=args['scopes'][1]
        budget=load_gateway_binding(Session(case.catalog,scope['context_ref']),bindings[scope['scope_id']],scope['profile'],scope['limits'])['budget']
        wire=GatewayHTTP(budget,scope['scope_id'],endpoint='http://127.0.0.1:1',origin='synthetic',
            credential='uteki-synthetic-gateway',deadline=time.monotonic()+5,before_request=lambda req:None)
        self.addCleanup(wire.close)
        body=dict(model=scope['profile']['model_id'],max_tokens=4096,stream=True,
            output_config={'effort':'high'},messages=[dict(role='user',content='Synthetic request')])
        # Match the independently captured real CLI fields. No endpoint is
        # called; this tests the live guard separately from authorization.
        raw=json.dumps(body).encode()
        self.assertEqual(wire.validate_request('/v1/messages?beta=true',raw,{}),body)
        with patch.object(wire,'origin','openrouter'),patch('http.client.HTTPConnection.connect',side_effect=AssertionError('must not connect')) as connect:
            with self.assertRaisesRegex(ValueError,'gateway_reasoning_disable_not_transmitted'):
                wire.exchange('/v1/messages?beta=true',raw,{})
            # Explicit disabled wins over effort in the documented API mapping.
            fixed=dict(body,thinking={'type':'disabled'})
            self.assertEqual(wire.validate_request('/v1/messages',json.dumps(fixed).encode(),{}),fixed)
            for thinking in ({'type':'adaptive'},{'type':'enabled','budget_tokens':512},None):
                with self.assertRaisesRegex(ValueError,'gateway_reasoning_controls_differ'):
                    wire.validate_request('/v1/messages',json.dumps(dict(body,thinking=thinking)).encode(),{})
            connect.assert_not_called()
        self.assertEqual(budget.summary()['requests'],0)
