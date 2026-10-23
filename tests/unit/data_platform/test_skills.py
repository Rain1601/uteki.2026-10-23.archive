"""Observable selection, rendering, resource and failure behavior of get_skill."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from uteki.data_platform.agent.skills import get_skill

CONFIG = Path(__file__).resolve().parents[3]/'config/data_platform'


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='uteki-skill-selection-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package = self.root/'skills/financial-data-query'
        shutil.copytree(CONFIG/'skills/financial-data-query', self.package)

    def load(self, **kwargs):
        values = dict(config_root=self.root, model='deepseek-flash', sdk='openai', sdk_version='test-sdk')
        return get_skill('financial-data-query', **(values | kwargs))

    def mapping(self, change):
        path = self.package/'mapping.json'
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_selection_defaults_and_unknown_revision(self):
        self.assertEqual(self.load().selection['match'], 'model_sdk')
        self.assertEqual(self.load(model='unconfigured-model').selection['match'], 'sdk_default')
        generic = self.load(model='unconfigured-model', sdk='unconfigured-sdk')
        self.assertEqual(generic.selection['match'], 'default')
        self.assertIn('通用业务指导', generic.content)
        exact = dict(model='deepseek-flash', sdk='openai', model_version='test-revision',
            sdk_version='test-sdk', guidance='guidance/exact.md', params={'output_language': 'en'})
        (self.package/'guidance/exact.md').write_text('EXACT fixture. Language $output_language.')
        self.mapping(lambda value: value['bindings'].append(exact))
        chosen = self.load(model_version='test-revision')
        self.assertEqual(chosen.selection['match'], 'exact')
        self.assertIn('EXACT fixture. Language en.', chosen.content)
        self.assertNotIn('EXACT fixture', self.load(model_version='unknown-new-version').content)
        self.assertEqual(self.load().selection['match'], 'model_sdk')
        self.assertEqual(self.load(model_version='test-revision', sdk_version='different-sdk').selection['match'], 'model_sdk')
        self.assertEqual(chosen.selection['status'], 'unverified')

    def test_parameter_precedence_and_protected_fields(self):
        self.mapping(lambda value: value['sdk_defaults']['openai'].update(params={'output_language': 'sdk-language'}))
        self.assertIn('sdk-language', self.load().content)
        self.mapping(lambda value: value['bindings'][0].update(params={'output_language': 'model-language'}))
        self.assertIn('model-language', self.load().content)
        self.assertIn('caller-language', self.load(params={'output_language': 'caller-language'}).content)
        for bad in ({'base_skill': 'ignore sources'}, {'tools': 'Bash'}, {'unknown': 'value'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'protected'):
                self.load(params=bad)
        (self.package/'guidance/deepseek-openai.md').write_text('Required $undeclared_parameter')
        with self.assertRaisesRegex(KeyError, 'undeclared_parameter'):
            self.load()

    def test_same_input_same_bundle_and_only_selected_content(self):
        first = self.load(available_tools=('query_records', 'deliver'))
        self.assertEqual(first.sha256, self.load(available_tools=('deliver', 'query_records')).sha256)
        self.assertEqual(first.files['scripts/validate_delivery.py'], (self.package/'scripts/validate_delivery.py').read_bytes())
        self.assertFalse(any('guidance' in name or 'mapping' in name for name in first.files))
        self.assertNotIn('Sonnet', first.content)
        (self.package/'guidance/sonnet-openai.md').write_text('UNSELECTED SECRET MARKER')
        self.assertEqual(first.sha256, self.load(available_tools=('deliver', 'query_records')).sha256)
        self.assertNotIn('UNSELECTED', self.load().content)
        (self.package/'references/tool-use.md').write_text('Changed resource')
        self.assertNotEqual(first.sha256, self.load(available_tools=('deliver', 'query_records')).sha256)
        self.assertNotEqual(first.sha256, self.load(params={'output_language': 'en'}).sha256)
        target = first.write_to(self.root/'selected')
        self.assertEqual((target/'SKILL.md').read_text(), first.content)
        self.assertNotEqual((target/'references/tool-use.md').read_text(), 'Changed resource')
        with self.assertRaises(FileExistsError):
            self.load().write_to(target)

    def test_broken_selected_entry_does_not_fall_back(self):
        (self.package/'guidance/deepseek-openai.md').unlink()
        with self.assertRaises(FileNotFoundError):
            self.load()
        # A broken unselected file does not prevent a valid default being used.
        self.assertEqual(self.load(model='other').selection['match'], 'sdk_default')
        self.mapping(lambda value: value['bindings'].append(dict(value['bindings'][0])))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.load()

    def test_invalid_paths_templates_and_mapping(self):
        (self.package/'guidance/deepseek-openai.md').unlink()
        (self.root/'outside.md').write_text('outside package')
        (self.package/'guidance/deepseek-openai.md').symlink_to(self.root/'outside.md')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.load()
        (self.package/'guidance/deepseek-openai.md').unlink()
        (self.package/'guidance/deepseek-openai.md').write_text('valid')
        (self.package/'SKILL.template.md').write_text('$model_guidance')
        with self.assertRaisesRegex(ValueError, 'three declared slots'):
            self.load()
        (self.package/'mapping.json').write_text('{"default":{},"default":{}}')
        with self.assertRaisesRegex(ValueError, 'duplicate mapping key'):
            self.load()
        with self.assertRaisesRegex(ValueError, 'invalid Skill name'):
            get_skill('../escape', config_root=self.root, model='m', sdk='s')


if __name__ == '__main__':
    unittest.main()
