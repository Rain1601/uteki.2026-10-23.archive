"""Provider routing is a transport adaptation, never a model-content repair."""
import json
import unittest
from pathlib import Path
import runpy
import tempfile

from uteki.data_platform.agent.providers.gateway_claude import routed_request


class ClaudeRoutingTests(unittest.TestCase):
    def test_live_workdir_rejects_inherited_project_instructions_and_settings(self):
        root=Path(__file__).resolve().parents[3]
        validate=runpy.run_path(str(root/'examples/data_platform/live_function.py'))['validate_claude_workdir']
        with tempfile.TemporaryDirectory(prefix='uteki-workdir-boundary-') as directory:
            parent=Path(directory);work=parent/'new-session'
            self.assertEqual(validate(work),work.resolve())
            for name in ('AGENTS.md','CLAUDE.md','.claude/CLAUDE.md','.claude/settings.json','.claude/settings.local.json'):
                target=parent/name;target.parent.mkdir(exist_ok=True)
                target.write_text('unrelated project guidance')
                with self.subTest(name=name),self.assertRaises(ValueError):validate(work)
                target.unlink()

    def test_conflict_duplicates_and_nonobjects_fail_before_sending(self):
        profile={'route':{'provider':'openrouter','upstream':['openai']},
                 'request_controls':{'output_config':{'effort':'low'}}}
        for body in (b'{"provider":{}}',b'{"model":"a","model":"b"}',b'[]'):
            with self.subTest(body=body),self.assertRaises(ValueError):
                routed_request(body,profile)

    def test_deepseek_is_byte_exact_and_only_routing_is_added_for_openrouter(self):
        raw=b'{ "model": "sample", "messages": [{"role":"user","content":"unchanged"}] }'
        profile={'route':{'provider':'deepseek','upstream':['deepseek']},'request_controls':{}}
        self.assertEqual(routed_request(raw,profile),raw)
        profile['route']={'provider':'openrouter','upstream':['anthropic']}
        wire=routed_request(raw,profile)
        request=json.loads(wire);request.pop('provider')
        self.assertEqual(request,json.loads(raw))
        self.assertEqual(routed_request(wire,profile),wire)
