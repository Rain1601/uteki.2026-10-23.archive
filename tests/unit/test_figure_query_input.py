"""The public caller binding fails before mutation or any paid execution."""
import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.agents.data_query.coordinator import CompanyDataCoordinator
from tests.unit.test_autonomous_data_agent import ScriptedPlanner


class FigureQueryInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.bundle = self.root / 'figure-bundle'
        self.bundle.mkdir()
        self.request = dict(question='Read reported image content.', purpose='analysis_evidence',
            dataset=str(self.root / 'dataset'),
            scope=dict(snapshot_id='synthetic-scoped-v1', company_ids=['acme'],
                source_snapshot_ids=['acme-annual'], source_policy_id='local-frozen-v1',
                knowledge_cutoff='2032-05-01', include_candidates=True))
        self.ref = dict(path=str(self.bundle), manifest_sha256='a' * 64)

    def test_old_request_serialization_has_no_implicit_supplement(self):
        request = CompanyQueryInput.model_validate(self.request)
        self.assertNotIn('figure_bundle_ref', request.model_dump(mode='json'))
        self.assertIsNone(request.figure_bundle_ref)

    def test_supplement_is_an_explicit_full_pinned_reference(self):
        for bad in ({'path': str(self.bundle)}, {'manifest_sha256': 'a' * 64},
                    {'path': str(self.bundle), 'manifest_sha256': 'bad'},
                    {**self.ref, 'scope_override': 'any'}):
            with self.subTest(ref=bad), self.assertRaises(ValueError):
                CompanyQueryInput.model_validate({**self.request, 'figure_bundle_ref': bad})
        checked = CompanyQueryInput.model_validate({**self.request, 'figure_bundle_ref': self.ref})
        self.assertEqual(checked.model_dump(mode='json')['figure_bundle_ref'], self.ref)

    def test_supplement_cannot_enable_unsupported_purposes(self):
        for purpose in ('question_answer', 'business_materials'):
            with self.subTest(purpose=purpose), self.assertRaisesRegex(ValueError, 'analysis_evidence'):
                CompanyQueryInput.model_validate({**self.request, 'purpose': purpose, 'figure_bundle_ref': self.ref})

    def test_preparation_cannot_implicitly_attach_a_different_dataset(self):
        for kind, value in (('prepared_run', str(self.root / 'prepared')), ('company_config', {'symbol': 'ACME'})):
            request = dict(question='Read image.', include_candidates=True,
                           figure_bundle_ref=self.ref, **{kind: value})
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'frozen dataset'):
                CompanyQueryInput.model_validate(request)

    def test_coordinator_cannot_write_output_or_workspace_into_supplement(self):
        request = {**self.request, 'figure_bundle_ref': self.ref}
        for workspace, output in ((self.root / 'workspace', self.bundle / 'new-query'),
                                  (self.bundle / 'cache', self.root / 'new-query')):
            planner = ScriptedPlanner([])
            coordinator = CompanyDataCoordinator(workspace)
            with self.subTest(workspace=str(workspace)), self.assertRaises(ValueError):
                asyncio.run(coordinator.query(request, output=output, planner=planner))
            self.assertFalse(output.exists())
            self.assertEqual(list(self.bundle.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
