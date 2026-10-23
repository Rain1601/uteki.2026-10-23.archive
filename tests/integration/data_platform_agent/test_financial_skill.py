"""Native Skill loading/execution, scripted model decisions, no paid inference.

The delivery is produced by real DataService calls over an existing synthetic
HTML fixture. These tests prove SDK wiring and helper behavior, not autonomous
financial task quality or production runtime Skill enablement.
"""
import asyncio
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest

from uteki.data_platform.agent.skills import get_skill

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT/'config/data_platform/skills/financial-data-query'
CHECK = SKILL/'scripts/validate_delivery.py'
FIXTURE = ROOT/'tests/fixtures/data_platform'
# The fixture uses a single-line description. SDKs, not this test, parse and
# expose the actual catalog; compare their model inputs to the source value.
DESCRIPTION = next(line.removeprefix('description: ') for line in (SKILL/'SKILL.md').read_text().splitlines()
    if line.startswith('description: '))


def evidence(name, result):
    if os.environ.get('UTEKI_SKILL_EVIDENCE'):
        path = Path(os.environ['UTEKI_SKILL_EVIDENCE'])
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = result | {'real_model_calls': 0, 'skill_sha256': hashlib.sha256((SKILL/'SKILL.md').read_bytes()).hexdigest()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def synthetic_delivery():
    fixture = runpy.run_path(str(FIXTURE/'sdk_fixture.py'))
    case = fixture['case']()
    script, outputs = fixture['Script'](), []
    from uteki.data_platform.agent.binding import ToolBinding
    # Scripted actions use the model-facing protocol, so they cross the same binding as SDK calls.
    binding = ToolBinding(case.service, case.context)
    try:
        for step in range(8):
            name, arguments = script.next(outputs)
            text = asyncio.run(binding.invoke(name, arguments, call_id='skill-fixture-'+str(step)))
            binding.observe(text, boundary='scripted-fixture')
            result = json.loads(text)
            if result.get('status') == 'error':
                raise AssertionError(result)
            outputs.append(result)
        return result['delivery']
    finally:
        case.doCleanups()


def prepare(work):
    package = synthetic_delivery()
    requirements = {'needs': [{'need_id': 'cash', 'required_result_kinds': ['record', 'calculation', 'evidence']}]}
    (work/'delivery.json').write_text(json.dumps(package))
    (work/'requirements.json').write_text(json.dumps(requirements))
    return package, requirements


def command(skill_path, python=None):
    return shlex.join([python or sys.executable, '-I', str(skill_path/'scripts/validate_delivery.py'),
        '--delivery', 'delivery.json', '--requirements', 'requirements.json', '--require-complete'])


class FinancialSkillTests(unittest.TestCase):
    def test_delivery_contract_normal_partial_and_text_only(self):
        checker = runpy.run_path(str(CHECK))['check']
        with tempfile.TemporaryDirectory(prefix='uteki-skill-contract-') as directory:
            package, requirements = prepare(Path(directory))
            normal = checker(package, requirements)
            self.assertTrue(normal['valid'] and normal['complete'], normal)
            partial = deepcopy(package)
            partial['records'], partial['calculations'] = [], []
            partial['needs'][0].update(status='partial', result_refs=[package['evidence'][0]['result_ref']],
                gaps=['unavailable: synthetic source record capability absent; comparison not computed'])
            partial['business_status'] = 'partial'
            incomplete = checker(partial, requirements)
            self.assertTrue(incomplete['valid'], incomplete)
            self.assertFalse(incomplete['complete'])
            manual = deepcopy(partial)
            manual['business_status'] = 'completed'
            manual['needs'][0].update(status='supported', gaps=[], note='Manual calculation is not a code result')
            rejected = checker(manual, requirements)
            self.assertFalse(rejected['valid'], rejected)
            corrupt = deepcopy(package)
            corrupt['calculations'][0]['operand_refs'][0]['item_id'] = 'missing'
            self.assertFalse(checker(corrupt, requirements)['valid'])
            path = Path(directory)/'partial.json'; path.write_text(json.dumps(partial))
            completed = subprocess.run([sys.executable, '-I', str(CHECK), '--delivery', str(path),
                '--requirements', str(Path(directory)/'requirements.json'), '--require-complete'], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            evidence('delivery_contract', dict(normal=normal, partial=incomplete, text_only=rejected,
                partial_cli_exit=completed.returncode, synthetic_data_tools_executed=8))

    def test_openai_native_skill_load_read_and_execute(self):
        from agents import Model, ModelResponse, Runner, RunConfig, Usage
        from agents.sandbox import Manifest, SandboxAgent, SandboxRunConfig, SandboxPathGrant
        from agents.sandbox.capabilities import Skills, Shell, LocalDirLazySkillSource
        from agents.sandbox.entries import LocalDir
        from agents.sandbox.sandboxes import UnixLocalSandboxClient
        from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText
        selected = get_skill('financial-data-query', config_root=ROOT/'config/data_platform',
            model='deepseek-flash', sdk='openai', sdk_version=importlib.metadata.version('openai-agents'))
        body = selected.content.split('---', 2)[2].strip()
        testcase = self
        class Scripted(Model):
            def __init__(self): self.calls = 0; self.outputs = []; self.discovery = False
            async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs):
                self.outputs = [i['output'] for i in input if isinstance(i, dict) and i.get('type') == 'function_call_output']
                if self.calls == 0:
                    self.discovery = f'- financial-data-query: {DESCRIPTION}' in system_instructions
                    testcase.assertTrue(self.discovery)
                    testcase.assertNotIn(body, system_instructions)
                    testcase.assertIn('load_skill', [tool.name for tool in tools])
                    testcase.assertFalse((work/'.agents/financial-data-query').exists())
                    name, args = 'load_skill', {'skill_name': 'financial-data-query'}
                elif self.calls == 1:
                    testcase.assertIn('loaded', str(self.outputs[-1]))
                    name, args = 'exec_command', {'cmd': 'cat .agents/financial-data-query/SKILL.md', 'max_output_tokens': 5000}
                elif self.calls == 2:
                    testcase.assertIn(body, str(self.outputs[-1]))
                    name, args = 'exec_command', {'cmd': command(Path('.agents/financial-data-query')), 'max_output_tokens': 2000}
                else:
                    testcase.assertIn('"complete": true', str(self.outputs[-1]))
                    return ModelResponse(output=[ResponseOutputMessage(id='done', type='message', role='assistant', status='completed',
                        content=[ResponseOutputText(type='output_text', text='synthetic check complete', annotations=[])])], usage=Usage(), response_id='fixture-done', raw_usage=None)
                self.calls += 1
                return ModelResponse(output=[ResponseFunctionToolCall(type='function_call', name=name, arguments=json.dumps(args),
                    call_id='fixture-'+str(self.calls))], usage=Usage(), response_id='fixture-'+str(self.calls), raw_usage=None)
            async def stream_response(self, *args, **kwargs):
                raise NotImplementedError
                yield
        async def run(work):
            model = Scripted()
            source = selected.write_to(work/'selected/financial-data-query')
            lazy_source = LocalDirLazySkillSource(source=LocalDir(src=str(source.parent)))
            skills = Skills(lazy_from=lazy_source)
            client = UnixLocalSandboxClient(inherit_host_environment=False)
            # Native LocalDir sources outside the host cwd need an explicit
            # source grant, as do the macOS interpreter/venv paths. Grant only
            # the rendered bundle, not the repository or the full temp root.
            grants = tuple(SandboxPathGrant(path=p, read_only=True)
                for p in sorted({sys.prefix, sys.base_prefix, str(source.parent)}))
            # Public SDK discovery API: no parallel metadata registry/parser.
            catalog = lazy_source.list_skill_metadata(skills_path='.agents', source_grants=grants)
            self.assertEqual([(s.name, s.description) for s in catalog], [('financial-data-query', DESCRIPTION)])
            session = await client.create(manifest=Manifest(root=str(work), extra_path_grants=grants))
            try:
                agent = SandboxAgent(name='Offline financial Skill check', model=model,
                    instructions='Use the named skill and run only the supplied local check.', capabilities=[skills, Shell()])
                result = await Runner.run(agent, 'Load financial-data-query and check the synthetic delivery.', max_turns=4,
                    run_config=RunConfig(tracing_disabled=True, sandbox=SandboxRunConfig(session=session)))
                self.assertEqual(result.final_output, 'synthetic check complete')
                for relative, raw in {'SKILL.md': selected.content.encode(), **selected.files}.items():
                    self.assertEqual(raw, (work/'.agents/financial-data-query'/relative).read_bytes())
                self.assertFalse((work/'.agents/financial-data-query/guidance').exists())
                evidence('openai_native', dict(sdk_version=importlib.metadata.version('openai-agents'),
                    discovery=True, body_visible=True, script_executed=True, file_bytes_equal=True,
                    description_visible_before_load=True, body_absent_before_load=True,
                    materialized_only_after_load=True, discovery_api='LocalDirLazySkillSource.list_skill_metadata',
                    selected_skill=selected.metadata(), model_decisions='scripted fixture', production_runtime_enabled=False))
            finally:
                await session.stop()
        with tempfile.TemporaryDirectory(prefix='uteki-openai-skill-') as directory:
            work = Path(directory).resolve(); prepare(work)
            asyncio.run(run(work))

    def test_claude_native_skill_body_and_script(self):
        selected = get_skill('financial-data-query', config_root=ROOT/'config/data_platform',
            model='deepseek-flash', sdk='claude', sdk_version=importlib.metadata.version('claude-agent-sdk'))
        body = selected.content.split('---', 2)[2].strip()
        requests, errors = [], []
        with tempfile.TemporaryDirectory(prefix='uteki-claude-skill-') as directory:
            work = Path(directory).resolve(); prepare(work)
            target = work/'.claude/skills/financial-data-query'
            selected.write_to(target)
            unselected = work/'.claude/skills/unselected-fixture'
            unselected.mkdir()
            unselected_description = 'UNSELECTED_SKILL_DESCRIPTION_7913'
            (unselected/'SKILL.md').write_text('---\nname: unselected-fixture\ndescription: '+unselected_description+'\n---\nUNSELECTED_BODY_7913\n')
            cmd = command(target)
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_CONNECT(self): self.send_error(403)
                def do_GET(self): self.send_error(403)
                def do_POST(self):
                    try:
                        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                        if self.path.split('?')[0] != '/v1/messages':
                            raise AssertionError('unexpected endpoint '+self.path)
                        requests.append(request); step = len(requests)
                        if step > 3: raise AssertionError('unexpected additional request')
                        if step < 3:
                            name, args = ('Skill', {'skill': 'financial-data-query'}) if step == 1 else ('Bash', {'command': cmd, 'description': 'Check synthetic delivery'})
                            block = dict(type='tool_use', id='skill-fixture-'+str(step), name=name, input={})
                            delta = dict(type='input_json_delta', partial_json=json.dumps(args))
                        else:
                            block = dict(type='text', text='')
                            delta = dict(type='text_delta', text='Synthetic skill check complete.')
                        events = [dict(type='message_start', message=dict(id='msg_'+str(step), type='message', role='assistant',
                            model=request['model'], content=[], stop_reason=None, stop_sequence=None, usage=dict(input_tokens=10, output_tokens=1))),
                            dict(type='content_block_start', index=0, content_block=block),
                            dict(type='content_block_delta', index=0, delta=delta), dict(type='content_block_stop', index=0),
                            dict(type='message_delta', delta=dict(stop_reason='tool_use' if step < 3 else 'end_turn', stop_sequence=None), usage=dict(output_tokens=10)),
                            dict(type='message_stop')]
                        raw = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
                    except Exception as error:
                        errors.append(repr(error)); self.send_error(400)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            endpoint = 'http://127.0.0.1:'+str(server.server_port)
            spec = work/'spec.json'; spec.write_text(json.dumps(dict(command=cmd, output=str(work/'result.json'))))
            env = dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='C.UTF-8', PYTHONNOUSERSITE='1',
                CLAUDE_CONFIG_DIR=str(work/'claude-config'), ANTHROPIC_BASE_URL=endpoint, ANTHROPIC_API_KEY='',
                ANTHROPIC_AUTH_TOKEN='synthetic', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
                CLAUDE_CODE_MAX_OUTPUT_TOKENS='4096', HTTP_PROXY=endpoint, HTTPS_PROXY=endpoint, ALL_PROXY=endpoint, NO_PROXY='127.0.0.1,localhost')
            try:
                result = subprocess.run([sys.executable, '-I', str(FIXTURE/'financial_skill_worker.py'), str(spec)],
                    cwd=work, env=env, capture_output=True, text=True, timeout=55)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(errors, [])
                self.assertEqual(len(requests), 3)
                def texts(value):
                    if isinstance(value, str): return [value]
                    if isinstance(value, list): return [t for v in value for t in texts(v)]
                    if isinstance(value, dict): return [t for v in value.values() for t in texts(v)]
                    return []
                self.assertTrue(any('financial-data-query' in t and DESCRIPTION in t for t in texts(requests[0])),
                    'Skill name and description missing from first model input')
                self.assertIn('Skill', [tool['name'] for tool in requests[0]['tools']])
                self.assertFalse(any('unselected-fixture' in t or unselected_description in t for t in texts(requests[0])),
                    'Skill outside the configured allowlist appeared in the model catalog')
                self.assertFalse(any(body in t for t in texts(requests[0])))
                self.assertTrue(any(body in t for t in texts(requests[1])), 'Skill body did not enter next model input')
                self.assertTrue(any('"complete": true' in t for t in texts(requests[2])), 'checker output missing')
                final = json.loads((work/'result.json').read_text())
                self.assertFalse(final['result']['is_error'], final)
                evidence('claude_native', dict(sdk_version=importlib.metadata.version('claude-agent-sdk'),
                    body_visible=True, script_executed=True, synthetic_requests=len(requests),
                    description_visible_before_load=True, body_absent_before_load=True,
                    unlisted_skill_hidden=True, discovery_api='native project discovery + skills allowlist',
                    selected_skill=selected.metadata(), model_decisions='scripted fixture', production_runtime_enabled=False))
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
