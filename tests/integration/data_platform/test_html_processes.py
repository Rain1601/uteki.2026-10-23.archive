"""Real process exits while writing and publishing the actual HTML format."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

from uteki.data_platform.catalog import Catalog,CatalogError
from uteki.data_platform.content.publication import Publication
from uteki.data_platform.build.pipeline import build_bundle,build_html,html_recipe
from uteki.data_platform.retrieval.content import HtmlReader

FIXTURES=Path(__file__).resolve().parents[2]/'fixtures/data_platform'
F=runpy.run_path(str(FIXTURES/'html_fixture.py'))
C=runpy.run_path(str(FIXTURES/'catalog_worker.py'))


class HtmlProcessTests(unittest.TestCase):
    def interrupted(self,mode):
        with tempfile.TemporaryDirectory(prefix='uteki-html-process-') as directory:
            root=Path(directory).resolve()
            with Catalog.initialize(root) as catalog:
                context=C['setup'](catalog,main=F['source']().replace(b'<img src="chart.png" alt="Synthetic chart">',b''))
                recipe=html_recipe(catalog,encoding='utf-8',form_type='synthetic',profile_ref='synthetic-v1',taxonomy_ref='none')
                old=build_html(catalog,snapshot_id=context['snapshot_id'],representation_id=context['representation_id'],recipe=recipe,run_id=context['run_id'])
                recipe=recipe.model_copy(update={'profile_ref':'interrupted-v2'})
                build=catalog.begin_build(snapshot_id=context['snapshot_id'],representation_id=context['representation_id'],recipe=recipe,run_id=context['run_id'])
                reference=catalog.asset_ref(build)
                if mode!='partial_stage':
                    files,manifest=build_bundle(catalog,build)
                    Publication(catalog).stage(build['build_id'],files=files,manifest=manifest)
            if mode=='partial_stage':
                command=[sys.executable,'-I',str(FIXTURES/'html_stage_worker.py'),str(root),build['build_id']]
            else:
                command=[sys.executable,'-I',str(FIXTURES/'catalog_worker.py'),mode,str(root),'--identity',build['build_id']]
            result=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,73,result.stderr);self.assertEqual(result.stdout,'')
            if mode=='build_after_commit':
                with self.assertRaises(CatalogError) as raised:Catalog.open(root)
                self.assertEqual(raised.exception.code,'RECOVERY_REQUIRED')
            else:
                with Catalog.open(root) as catalog:
                    with self.assertRaises(CatalogError):HtmlReader(catalog,reference)
                    self.assertTrue(HtmlReader(catalog,old).inventory()['records'])
            with Catalog.open(root,recover=True) as catalog:
                expected='failed' if mode in {'partial_stage','build_before_move'} else 'published'
                self.assertEqual(catalog.get_build(build['build_id'])['status'],expected)
                self.assertTrue(HtmlReader(catalog,old).inventory()['records'])
                if expected=='published':HtmlReader(catalog,reference)
                else:
                    with self.assertRaises(CatalogError):HtmlReader(catalog,reference)
                    self.assertTrue((root/'staging'/build['job_id']).exists())
                view=catalog.view();self.assertEqual(catalog.recover(),[]);self.assertEqual(catalog.view(),view)

    def test_partial_file_stage_is_retained_failed_not_published(self):self.interrupted('partial_stage')
    def test_before_move_failure_keeps_old_html_readable(self):self.interrupted('build_before_move')
    def test_after_move_explicit_recovery_verifies_html(self):self.interrupted('build_after_move')
    def test_after_commit_uncertain_head_requires_recovery(self):self.interrupted('build_after_commit')


if __name__=='__main__':unittest.main()
