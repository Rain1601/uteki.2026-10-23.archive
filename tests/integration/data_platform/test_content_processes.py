"""Installed-package process interruption, reopen and concurrent-write checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from uteki.data_platform.content import ContentStore, ContentStoreError
from uteki.data_platform.contracts import ObjectRef
import uteki.data_platform.content.store as installed_store

WORKER=Path(__file__).resolve().parents[2]/'fixtures/data_platform/store_worker.py'


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='uteki-content-process-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.store=ContentStore(self.root)

    def command(self,mode,*args):
        return [sys.executable,'-I',str(WORKER),mode,str(self.root),*args]

    def run_worker(self,mode,*args):
        return subprocess.run(self.command(mode,*args),cwd=self.root,capture_output=True,text=True,timeout=15)

    def test_installed_package_has_no_agent_sdk_dependency(self):
        self.assertTrue(sys.flags.isolated)
        self.assertTrue(Path(installed_store.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()))
        self.assertIsNone(importlib.util.find_spec('agents'))
        self.assertIsNone(importlib.util.find_spec('claude_agent_sdk'))
        self.assertNotIn('uteki.infrastructure.research_data',sys.modules)
        self.assertNotIn('uteki.agents.data_query',sys.modules)

    def test_crash_before_and_after_link_preserves_old_objects_and_retry(self):
        old=self.store.put_object(b'previous successful original')
        for stage in ('partial_write','before_link','after_link'):
            with self.subTest(stage=stage):
                raw=('interrupted-'+stage).encode()
                reference=ObjectRef(sha256=hashlib.sha256(raw).hexdigest(),byte_length=len(raw))
                result=self.run_worker(stage,'--hex',raw.hex())
                self.assertEqual(result.returncode,73,result.stderr)
                self.assertEqual(result.stdout,'')
                self.assertEqual(self.store.read_object(old),b'previous successful original')
                leftovers={p:p.read_bytes() for p in self.root.rglob('.pending-*')}
                self.assertTrue(leftovers)
                if stage=='after_link':
                    self.assertEqual(ContentStore(self.root).read_object(reference),raw)
                else:
                    with self.assertRaises(ContentStoreError) as failed:
                        ContentStore(self.root).read_object(reference)
                    self.assertEqual(failed.exception.code,'OBJECT_MISSING')
                retry=self.run_worker('put','--hex',raw.hex())
                self.assertEqual(retry.returncode,0,retry.stderr)
                self.assertEqual(ObjectRef.model_validate_json(retry.stdout),reference)
                read=self.run_worker('read','--ref',reference.model_dump_json())
                self.assertEqual(read.returncode,0,read.stderr)
                self.assertEqual(bytes.fromhex(read.stdout),raw)
                self.assertEqual({p:p.read_bytes() for p in leftovers},leftovers)

    def test_independent_writers_reuse_same_complete_object(self):
        raw=bytes(range(256))*1024
        # Pass a compact payload rather than exceeding the OS argument-size limit.
        raw=raw[:4096]
        barrier=self.root/'start'
        workers=[]
        try:
            for _ in range(2):
                workers.append(subprocess.Popen(self.command('put','--hex',raw.hex(),'--barrier',str(barrier)),
                    cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
            barrier.touch()
            refs=[]
            for worker in workers:
                stdout,stderr=worker.communicate(timeout=15)
                self.assertEqual(worker.returncode,0,stderr)
                refs.append(ObjectRef.model_validate_json(stdout))
            self.assertEqual(refs[0],refs[1])
            self.assertEqual(self.store.read_object(refs[0]),raw)
            self.assertFalse(list(self.root.rglob('.pending-*')))
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill(); worker.communicate(timeout=5)

    def test_runnable_example_preserves_explicit_gap(self):
        result=self.run_worker('example')
        self.assertEqual(result.returncode,0,result.stderr)
        example=json.loads(result.stdout)
        self.assertTrue(example['main_round_trip'])
        self.assertFalse(example['source_identity_verified'])
        manifest=self.store.read_manifest(ObjectRef.model_validate(example['manifest_ref']))
        self.assertEqual({r.status for r in manifest.resources},{'missing','present'})


if __name__=='__main__':
    unittest.main()
