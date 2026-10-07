import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1]/'experiments/model_comparison/2026-10-07-reproducibility-pilot-v1/run_case.py'
spec = importlib.util.spec_from_file_location('pilot_dispatch', PATH)
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


class PilotDispatchTests(unittest.TestCase):
    def test_sequential_gate_keeps_unknown_failed_and_oversized_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cases = [{'output_path': 'first'}, {'output_path': 'second'}]
            budget = {'unknown_requests': 0, 'in_flight_requests': 0, 'requests': 1}
            (root/'first').mkdir()
            path = root/'first/summary.json'
            good = {'status': 'completed', 'arms': [{'raw_usage': {'prompt_tokens': 100}}]}
            path.write_text(json.dumps(good))
            dispatch.verify_previous(root,cases,2,budget)
            for field in ('unknown_requests','in_flight_requests'):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    dispatch.verify_previous(root,cases,2,{**budget,field:1})
            with self.assertRaises(ValueError):
                dispatch.verify_previous(root,cases,2,{**budget,'requests':0})
            for status,tokens in [('completed_with_invalid_outputs',100),('completed',6001)]:
                path.write_text(json.dumps({'status':status,'arms':[{'raw_usage':{'prompt_tokens':tokens}}]}))
                with self.assertRaises(ValueError): dispatch.verify_previous(root,cases,2,budget)


if __name__ == '__main__':
    unittest.main()
