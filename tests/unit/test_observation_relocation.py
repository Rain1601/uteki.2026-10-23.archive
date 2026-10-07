import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from uteki.agents.business_map.coverage_run import verify_published_artifacts
from uteki.agents.runtime.observation_relocation import RECEIPT_PATH, create_receipt


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.old=self.base/'old-repo';self.root=self.base/'new-repo'
        self.trace='run-'+'a'*32;self.relative=Path('experiments/another-issuer/new-period')
        stage=self.old/self.relative;stage.mkdir(parents=True)
        artifact=b'{"scope":"explicit-synthetic"}\n';(stage/'draft.json').write_bytes(artifact)
        obs=self.old/'observations'/self.trace; (obs/'events').mkdir(parents=True)
        self.descriptor=dict(root_run_id=self.trace,run_id=self.trace,output_root=str(stage),generation='frozen-generation')
        (obs/'descriptor.json').write_text(json.dumps(self.descriptor))
        event=dict(type='artifact.published',root_run_id=self.trace,generation='frozen-generation',data=dict(ref=dict(run_id=self.trace,path='draft.json',sha256=hashlib.sha256(artifact).hexdigest())))
        (obs/'events/0001.json').write_text(json.dumps(event))
        shutil.copytree(self.old,self.root)
        self.args=dict(root=self.root,observation_root=self.root/'observations',stage=self.root/self.relative,trace_id=self.trace,relative_paths=['draft.json'])
    def install(self):
        value=create_receipt(root=self.root,old_root=self.old,observation_root=self.root/'observations')
        self.path=self.root/RECEIPT_PATH;self.path.parent.mkdir(exist_ok=True);self.path.write_text(json.dumps(value));return value
    def test_different_root_requires_explicit_receipt_and_keeps_history(self):
        before=(self.root/'observations'/self.trace/'descriptor.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'recovery_trace_output_mismatch'):verify_published_artifacts(**self.args)
        self.install();self.assertEqual(len(verify_published_artifacts(**self.args)),1)
        self.assertEqual(before,(self.root/'observations'/self.trace/'descriptor.json').read_bytes())
    def test_wrong_suffix_trace_and_descriptor_hash_rejected(self):
        value=self.install()
        for field,bad,error in [('stage_relative','experiments/other','suffix'),('trace_id','run-'+'b'*32,'not_registered'),('descriptor_sha256','0'*64,'hash')]:
            changed=json.loads(json.dumps(value));changed['traces'][0][field]=bad;self.path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,error):verify_published_artifacts(**self.args)
    def test_relocation_never_bypasses_original_publication(self):
        self.install();(self.root/self.relative/'draft.json').write_text('changed')
        with self.assertRaisesRegex(ValueError,'not_originally_published'):verify_published_artifacts(**self.args)
    def test_wrong_newroot_and_oldroot_rejected(self):
        value=self.install()
        for field,bad in [('new_root',str(self.old)),('old_root',str(self.old/'other'))]:
            changed=json.loads(json.dumps(value));changed[field]=bad;self.path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):verify_published_artifacts(**self.args)
    def test_escape_and_wrong_trace_descriptor_rejected(self):
        self.install();descriptor=self.root/'observations'/self.trace/'descriptor.json'
        value=dict(self.descriptor,run_id='run-'+'b'*32);descriptor.write_text(json.dumps(value))
        with self.assertRaises(ValueError):verify_published_artifacts(**self.args)
        with self.assertRaises(ValueError):create_receipt(root=self.root,old_root=self.old,observation_root=self.root/'observations')
    def test_create_command_rolls_back_only_new_receipt_on_check_failure(self):
        (self.root/self.relative/'draft.json').write_text('tampered')
        script=Path(__file__).resolve().parents[2]/'scripts/relocate_observation_history.py'
        result=subprocess.run([sys.executable,str(script),'create','--root',str(self.root),
                               '--old-root',str(self.old),'--observation-root','observations'],
                              capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/RECEIPT_PATH).exists())
        self.install();before=self.path.read_bytes()
        result=subprocess.run([sys.executable,str(script),'check','--root',str(self.root)],
                              capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.path.read_bytes(),before)

    def test_same_root_remains_backward_compatible(self):
        self.assertEqual(len(verify_published_artifacts(**dict(self.args,root=self.old,observation_root=self.old/'observations',stage=self.old/self.relative))),1)

if __name__=='__main__':unittest.main()
