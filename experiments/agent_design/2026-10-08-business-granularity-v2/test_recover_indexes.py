"""Real frozen failure must remain unpublished; this is an offline guard test."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('index_recovery', HERE/'recover_indexes.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryGuardTests(unittest.TestCase):
    def test_complete_parent_with_second_contract_error_does_not_publish_or_write_budget(self):
        paths = [recovery.PARENT/name for name in (*recovery.COPIES,'manifest.json','result.json')]
        before = {path:recovery.base.digest(path.read_bytes()) for path in paths}
        connect = recovery.sqlite3.connect
        modes = []
        def readonly(database, **kwargs):
            modes.append((database,kwargs))
            self.assertTrue(database.endswith('?mode=ro'))
            self.assertIs(kwargs.get('uri'),True)
            return connect(database,**kwargs)
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(recovery,'OUTPUT',Path(temp)/'must-not-exist') as output, \
                patch.object(recovery,'observed_run') as trace, \
                patch.object(recovery.base,'materialize') as materialize, \
                patch.object(recovery.sqlite3,'connect',side_effect=readonly):
            with self.assertRaisesRegex(ValueError,'monetization_claim_evidence_mismatch'):
                recovery.recover(execute=True)
            self.assertFalse(output.exists())
            trace.assert_not_called()
            materialize.assert_not_called()
        self.assertEqual(len(modes),1)
        self.assertEqual(before,{path:recovery.base.digest(path.read_bytes()) for path in paths})


if __name__=='__main__':
    unittest.main()
