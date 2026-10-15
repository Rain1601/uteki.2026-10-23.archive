"""Behavioral SDK-seam tests; every model/CLI response is explicitly synthetic."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.agents.runtime.run_budget import BudgetExceeded, RunBudget

try:
    import agents
    import claude_agent_sdk
except ImportError:
    agents = claude_agent_sdk = None

if agents is not None:
    from uteki.agents.sdk_probe.adapters import (claude_options, openai_agent,
        openrouter_chat_model, run_claude, run_openai)
    from uteki.agents.sdk_probe.contracts import FixtureStore, ReadRequest
    from uteki.agents.sdk_probe.offline import ScriptedCLI, ScriptedModel, exercise, no_external_io
    from uteki.agents.sdk_probe.profiles import load_profile, worker_environment

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config/sdk_probe'


@unittest.skipIf(agents is None, 'Install the isolated requirements/m0.txt environment')
class SDKProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='uteki-sdk-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = FixtureStore((CONFIG / 'fixture.json').read_bytes())
        self.openai = load_profile(CONFIG / 'openai-claude.json', model_id='fixture/claude-v1', kernel='openai')
        self.claude = load_profile(CONFIG / 'claude-claude.json', model_id='fixture/claude-v1', kernel='claude')
        self.guard = no_external_io()
        self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)

    def arguments(self, record='alpha', **changes):
        return {'record_id': record, 'snapshot_sha256': self.store.snapshot_sha256, **changes}

    def options(self):
        cli = Path(claude_agent_sdk.__file__).parent / '_bundled/claude'
        return claude_options(self.claude, self.store, cwd=self.directory,
                              cli_path=cli, path_environment='/usr/bin:/bin')

    async def test_nine_scenarios_through_actual_official_sdk_code(self):
        report = await asyncio.wait_for(exercise(CONFIG / 'fixture.json', CONFIG, self.directory), 15)
        self.assertEqual(len(report['scenarios']), 9)
        self.assertTrue(report['passed'], report['scenarios'])
        self.assertEqual(report['model_api_calls'], 0)
        self.assertEqual(report['native_cli_runs'], 0)

    async def test_openai_runner_recovers_tool_error_and_reads_independent_record(self):
        model = ScriptedModel([self.arguments('absent'), self.arguments('beta')])
        result = await run_openai(self.openai, self.store, model, 'Read beta', max_turns=3)
        self.assertEqual(result.status, 'completed', asdict(result))
        self.assertEqual(result.delivery['value'], '4.50')
        self.assertEqual(result.delivery['unit'], 'other_test_units')
        self.assertEqual(model.calls, 3)
        self.assertEqual(len(self.store.calls), 2)
        # The next native model input contains the actual tool response.
        self.assertIn('record_not_found', json.dumps(model.inputs[1]))
        self.assertIn(result.delivery['result_ref'], json.dumps(model.inputs[2]))
        self.assertEqual(result.native_usage, [None, None, None])
        self.assertIsNone(result.gateway_cost_usd)

    async def test_failed_scenario_retains_native_evidence_in_report(self):
        from uteki.agents.sdk_probe.contracts import finish

        def reject_success(*args, **kwargs):
            result = finish(*args, **kwargs)
            if result.status == 'completed':
                result.status, result.reason = 'error', 'injected_acceptance_failure'
            return result

        with patch('uteki.agents.sdk_probe.adapters.finish', side_effect=reject_success):
            report = await exercise(CONFIG / 'fixture.json', CONFIG, self.directory)
        self.assertFalse(report['passed'])
        for kernel in ('openai', 'claude'):
            failed = report['scenarios'][kernel + '/success']
            self.assertFalse(failed['passed'])
            self.assertEqual(failed['reason'], 'injected_acceptance_failure')
            self.assertTrue(failed['native_events'])

    async def test_turn_limit_does_not_adopt_intermediate_tool_result(self):
        result = await run_openai(self.openai, self.store, ScriptedModel([self.arguments()]), 'Read', max_turns=1)
        self.assertEqual(result.status, 'error')
        self.assertEqual(result.reason, 'MaxTurnsExceeded')
        self.assertIsNone(result.delivery)

    async def test_mcp_registration_and_independent_record_use_same_contract(self):
        peer = ScriptedCLI(self.arguments('beta'))
        result = await run_claude(self.options(), self.store, 'Read beta', transport=peer)
        self.assertEqual(result.status, 'completed', asdict(result))
        self.assertEqual(result.delivery['value'], '4.50')
        self.assertEqual(result.delivery['unit'], 'other_test_units')
        self.assertEqual([t['name'] for t in peer.listed_tools], ['read_fixture'])
        self.assertEqual(peer.listed_tools[0]['inputSchema'], ReadRequest.model_json_schema())
        self.assertFalse(peer.mcp_results[0].get('isError', False))
        self.assertEqual(result.native_usage, [None])
        self.assertIsNone(result.native_cost_estimate_usd)
        self.assertTrue(peer.closed)

    async def test_sdk_mcp_schema_rejects_extra_argument_before_business_read(self):
        peer = ScriptedCLI(self.arguments(extra='forbidden'))
        result = await run_claude(self.options(), self.store, 'Read', transport=peer)
        self.assertTrue(peer.mcp_results[0]['isError'])
        self.assertEqual(self.store.calls, [])
        self.assertEqual(result.status, 'invalid_delivery')

    async def test_openai_bad_schema_or_snapshot_never_registers_result(self):
        for args in (self.arguments(extra='forbidden'), self.arguments(snapshot_sha256='0' * 64)):
            with self.subTest(args=args):
                result = await run_openai(self.openai, self.store, ScriptedModel([args]), 'Read')
                self.assertEqual(result.status, 'invalid_delivery')
                self.assertFalse(self.store.exposed)

    async def test_native_error_cannot_be_overridden_by_valid_structured_output(self):
        peer = ScriptedCLI(self.arguments(), fatal=True, native_usage={'input_tokens': 5, 'output_tokens': 2}, native_cost=.75)
        result = await run_claude(self.options(), self.store, 'Read', transport=peer)
        self.assertEqual(result.status, 'error')
        self.assertIsNone(result.delivery)
        self.assertEqual(result.native_usage, [{'input_tokens': 5, 'output_tokens': 2}])
        self.assertEqual(result.native_cost_estimate_usd, .75)
        self.assertIsNone(result.gateway_cost_usd)

    async def test_value_or_unit_substitution_rejected_after_successful_read(self):
        source = self.store.read(self.arguments())
        for change in ({'value': '1725'}, {'unit': 'USD'}, {'result_ref': 'unread'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.store.validate_delivery({k: source[k] for k in ('result_ref', 'value', 'unit')} | change)

    async def test_prompt_binding_and_independently_authored_model_content(self):
        gpt = load_profile(CONFIG / 'openai-gpt.json', model_id='fixture/gpt-v1', kernel='openai')
        self.assertNotEqual(gpt.text, self.openai.text)
        self.assertNotEqual(gpt.sha256, self.openai.sha256)
        for model, kernel in [('fixture/new-v1', 'openai'), ('fixture/claude-v1', 'claude')]:
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                load_profile(CONFIG / 'openai-claude.json', model_id=model, kernel=kernel)

    async def test_claude_options_do_not_enable_default_tools_or_other_sources(self):
        options = self.options()
        self.assertEqual(options.tools, [])
        self.assertEqual(options.allowed_tools, [])
        self.assertEqual(options.setting_sources, [])
        self.assertEqual(options.skills, [])
        self.assertTrue(options.strict_mcp_config)
        self.assertIsNone(options.fallback_model)
        self.assertEqual(options.system_prompt['preset'], 'claude_code')
        self.assertEqual((await options.can_use_tool('Bash', {'command': 'anything'}, None)).behavior, 'deny')
        self.assertEqual((await options.can_use_tool('mcp__fixture__read_fixture', self.arguments(), None)).behavior, 'allow')
        with self.assertRaisesRegex(ValueError, 'offline transport required'):
            await run_claude(options, self.store, 'Read', transport=None)

    async def test_explicit_worker_environment_discards_ambient_configuration(self):
        before = dict(os.environ)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-secret', 'ANTHROPIC_BASE_URL': 'https://wrong.invalid',
             'CLAUDE_CODE_USE_BEDROCK': '1', 'OPENAI_API_KEY': 'other-secret', 'HTTP_PROXY': 'http://wrong.invalid'}):
            env = worker_environment(path='/usr/bin', config_directory=self.directory)
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'https://openrouter.ai/api')
        self.assertEqual(env['ANTHROPIC_API_KEY'], '')
        for name in ('OPENAI_API_KEY', 'CLAUDE_CODE_USE_BEDROCK', 'HTTP_PROXY'):
            self.assertNotIn(name, env)
        self.assertNotIn('test-secret', json.dumps(env))

    async def test_pinned_claude_sdk_generates_restricted_native_cli_arguments(self):
        # Version-specific inspection only; no CLI process is started.
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
        command = SubprocessCLITransport(prompt='offline fixture', options=self.options())._build_command()
        self.assertEqual(command[command.index('--tools') + 1], '')
        self.assertIn('--setting-sources=', command)
        self.assertIn('--strict-mcp-config', command)
        self.assertEqual(command[command.index('--model') + 1], 'fixture/claude-v1')
        self.assertIn('--append-system-prompt', command)
        self.assertNotIn('--dangerously-skip-permissions', command)

    async def test_official_openai_client_has_explicit_endpoint_and_no_retries(self):
        with patch.dict(os.environ, {'OPENAI_BASE_URL': 'https://wrong.invalid', 'OPENAI_API_KEY': 'ignored-test-secret'}):
            model, client = openrouter_chat_model(self.openai, api_key='offline-not-a-credential')
            try:
                self.assertEqual(str(client.base_url), 'https://openrouter.ai/api/v1/')
                self.assertEqual(client.max_retries, 0)
                self.assertEqual(model.model, self.openai.model_id)
                agent = openai_agent(self.openai, self.store, model)
                self.assertFalse(agent.model_settings.store)
                self.assertEqual(agent.model_settings.retry.max_retries, 0)
            finally:
                await client.close()

    async def test_missing_cost_retains_reservation_in_existing_root_ledger(self):
        path = self.directory / 'synthetic-budget.sqlite'
        budget = RunBudget(path, '1.00')
        token = budget.reserve('.25')
        budget.settle(token, None)
        resumed = RunBudget(path, '1.00')
        self.assertEqual(resumed.summary()['unknown_requests'], 1)
        self.assertEqual(resumed.summary()['held_usd'], '0.25')
        self.assertIsNone(resumed.summary()['actual_billed_usd'])
        with self.assertRaises(BudgetExceeded):
            resumed.reserve('.01')
        with self.assertRaises(ValueError):
            RunBudget(path, '2.00')


if __name__ == '__main__':
    unittest.main()
