"""Legal packet ceilings must preserve bounded artifact reads; no model calls."""
import asyncio
import json
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.run_artifacts import ArtifactStore, json_size
from tests.unit import test_autonomous_data_agent as fixtures


class LargePacketArtifactTests(unittest.TestCase):
    setUp = fixtures.AutonomousDataAgentTests.setUp
    def test_maximum_packet_still_reads_and_delivers_source(self):
        planner = fixtures.ScriptedPlanner([fixtures.plan('business'), fixtures.read(), {'action': 'finish'}])
        result = asyncio.run(AutonomousDataAgent(self.port, planner,
            limits={'max_steps': 3, 'max_packet_bytes': 1000000}).run(
                self.request, output=self.root / 'run'))
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(len(planner.packets), 3)
        self.assertTrue(all(json_size(p) <= 1000000 for p in planner.packets))

    def test_large_state_retains_cursor_and_full_immutable_content(self):
        requirements = [{'requirement_id': f'req-{i}', 'description': '合成读取要求。' * 250}
                        for i in range(32)]
        state = {}

        def continue_state(packet):
            ref = packet['state_artifact']
            full = json.loads((self.root / 'run' / ref['path']).read_text())
            self.assertGreater(json_size(full), 200000)
            self.assertEqual(len(full['requirements']), 32)
            page = next(p for p in packet['state_reads'] if p.get('pointer') == '/requirements')
            self.assertIsNotNone(page['next_cursor'])
            state.update(ref=ref, page=page, full=full)
            return {'action': 'read_artifact', 'requirement_ids': ['req-0'],
                    'artifact_read': {'artifact_id': ref['artifact_id'], 'pointer': '/requirements',
                                      'cursor': page['next_cursor'], 'limit': 8, 'max_bytes': 100000}}

        def finish(packet):
            page = packet['observation']['result']
            self.assertEqual(page['offset'], state['page']['end_offset'])
            self.assertEqual(page['items'], state['full']['requirements'][page['offset']:page['end_offset']])
            self.assertLessEqual(page['bytes_returned'], 100000)
            return {'action': 'finish'}

        planner = fixtures.ScriptedPlanner([{'action': 'plan', 'reason': 'Large independent synthetic state',
                                    'requirements': requirements}, continue_state, finish])
        result = asyncio.run(AutonomousDataAgent(self.port, planner,
            limits={'max_steps': 3, 'max_packet_bytes': 1000000, 'observation_bytes': 100000,
                    'page_items': 8}).run(self.request, output=self.root / 'run'))
        self.assertEqual(len(planner.packets), 3)
        self.assertEqual(result['trace'][1]['status'], 'tool_returned', result['trace'])
        self.assertEqual(result['status'], 'limited')  # Metadata reads do not satisfy evidence requirements.
        store = ArtifactStore(self.root / 'run', refs=[state['ref']])
        self.assertEqual(store.load(state['ref']['artifact_id']), state['full'])
