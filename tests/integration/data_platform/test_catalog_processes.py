"""Independent-process ownership, interrupted publication and old-reference reads."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import unittest

from uteki.data_platform.catalog import Catalog, CatalogError
from uteki.data_platform.content.publication import Publication

WORKER=Path(__file__).resolve().parents[2]/"fixtures/data_platform/catalog_worker.py"
FIXTURE=runpy.run_path(str(WORKER))
setup,snapshot,begin,bundle,publish=(FIXTURE[k] for k in ("setup","snapshot","begin","bundle","publish"))


class CatalogProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="uteki-catalog-process-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()

    def command(self,mode,*args):
        return [sys.executable,"-I",str(WORKER),mode,str(self.root),*args]

    def test_normal_example_reopens_two_distinct_versions(self):
        result=subprocess.run(self.command("example"),cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertTrue(value["reopened"])
        self.assertFalse(value["business_verified"])
        self.assertEqual(value["old"]["asset_id"],value["new"]["asset_id"])
        self.assertNotEqual(value["old"]["snapshot_id"],value["new"]["snapshot_id"])

    def test_snapshot_move_interruptions_are_explicit_and_old_reference_survives(self):
        for mode in ("snapshot_before_move","snapshot_after_move"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve()
                with Catalog.initialize(root) as catalog:
                    context=setup(catalog)
                    old=publish(catalog,begin(catalog,context))
                    pending=snapshot(catalog,context,mode,figure=b"new figure",previous=context["snapshot_id"],freeze=False)
                command=[sys.executable,"-I",str(WORKER),mode,str(root),"--identity",pending["snapshot_id"]]
                failed=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(failed.returncode,73,failed.stderr)
                self.assertEqual(failed.stdout,"")
                with Catalog.open(root) as catalog:
                    self.assertEqual(catalog.get_snapshot(pending["snapshot_id"])["status"],"collecting")
                    with self.assertRaises(CatalogError): catalog.read_snapshot(pending["snapshot_id"])
                    catalog.read_published(old)
                with Catalog.open(root,recover=True) as catalog:
                    expected="frozen" if mode.endswith("after_move") else "failed"
                    self.assertEqual(catalog.get_snapshot(pending["snapshot_id"])["status"],expected)
                    catalog.read_published(old)
                    view=catalog.view()
                    self.assertEqual(catalog.recover(),[])
                    self.assertEqual(catalog.view(),view)

    def test_build_move_and_commit_interruptions_do_not_publish_partial_output(self):
        for mode in ("build_before_move","build_after_move","build_after_commit"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve()
                with Catalog.initialize(root) as catalog:
                    context=setup(catalog)
                    old=publish(catalog,begin(catalog,context))
                    pending=begin(catalog,context,variant=mode)
                    files,manifest=bundle(catalog,pending)
                    Publication(catalog).stage(pending["build_id"],files=files,manifest=manifest)
                    reference=catalog.asset_ref(pending)
                command=[sys.executable,"-I",str(WORKER),mode,str(root),"--identity",pending["build_id"]]
                failed=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(failed.returncode,73,failed.stderr)
                self.assertEqual(failed.stdout,"")
                if mode=="build_after_commit":
                    with self.assertRaises(CatalogError) as problem: Catalog.open(root)
                    self.assertEqual(problem.exception.code,"RECOVERY_REQUIRED")
                else:
                    with Catalog.open(root) as catalog:
                        self.assertEqual(catalog.get_build(pending["build_id"])["status"],"staging")
                        with self.assertRaises(CatalogError): catalog.read_published(reference)
                        catalog.read_published(old)
                with Catalog.open(root,recover=True) as catalog:
                    expected="failed" if mode=="build_before_move" else "published"
                    self.assertEqual(catalog.get_build(pending["build_id"])["status"],expected)
                    catalog.read_published(old)
                    if expected=="published":
                        self.assertEqual(catalog.read_artifact(reference,"blocks.jsonl"),files["blocks.jsonl"])
                    view=catalog.view()
                    self.assertEqual(catalog.recover(),[])
                    self.assertEqual(catalog.view(),view)

    def test_live_owner_cannot_be_stolen_by_recovery_even_with_old_timestamps(self):
        with Catalog.initialize(self.root) as catalog:
            context=setup(catalog)
            pending=begin(catalog,context)
            catalog._db.execute("UPDATE asset_builds SET updated_at='1980-01-01T00:00:00+00:00'")
        ready=self.root/"owner-ready"
        worker=subprocess.Popen(self.command("hold","--ready",str(ready)),cwd=self.root,
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+5
            while not ready.exists() and worker.poll() is None and time.monotonic()<deadline:
                time.sleep(0.02)
            self.assertIsNone(worker.poll(),"worker exited before taking lock")
            self.assertTrue(ready.exists(),"worker did not confirm lock ownership")
            with self.assertRaises(CatalogError) as problem: Catalog.open(self.root,recover=True)
            self.assertEqual(problem.exception.code,"CATALOG_BUSY")
            ready.unlink()
            stdout,stderr=worker.communicate(timeout=10)
            self.assertEqual(worker.returncode,0,stderr)
        finally:
            if worker.poll() is None:
                worker.kill(); worker.communicate(timeout=5)
        with Catalog.open(self.root,recover=True) as catalog:
            self.assertEqual(catalog.get_build(pending["build_id"])["status"],"failed")


if __name__=="__main__":
    unittest.main()
