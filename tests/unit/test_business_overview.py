import copy
import unittest

from uteki.presentation.business_overview import overview_selection


def example():
    nodes = [('c', 'company'), ('g', 'business'), ('s', 'reportable_segment'),
             ('a', 'offering_group'), ('p', 'business'), ('u', 'business')]
    edges = [('g', 'c', 'explicit'), ('s', 'g', 'explicit'),
             ('a', 's', 'derived'), ('p', 'a', 'explicit'), ('u', 'c', 'unknown')]
    return dict(schema_version='business-map-v0.2', businesses=[dict(id=i, name=i, kind=k) for i, k in nodes],
                relationships=[dict(source_id=s, target_id=t, basis=b, kind='part_of')
                               for s, t, b in edges])


class OverviewTests(unittest.TestCase):
    def test_hierarchy_and_dispositions_preserve_every_identity_without_mutation(self):
        data = example(); before = copy.deepcopy(data)
        actual = overview_selection(data)
        self.assertEqual(actual['selected_node_ids'], ['c', 'g', 's', 'a'])
        self.assertEqual(actual['folded_node_ids'], ['p'])
        self.assertEqual(actual['unplaced_node_ids'], ['u'])
        self.assertEqual(data, before)
        self.assertFalse(actual['importance_ranking'])

    def test_no_segment_uses_explicit_input_not_company_specific_fallback(self):
        data = example()
        data['businesses'][2]['kind'] = 'business'
        self.assertEqual(overview_selection(data)['selected_node_ids'], ['c', 'g'])
        data['relationships'] = []
        self.assertEqual(overview_selection(data)['selected_node_ids'], ['c'])
        self.assertEqual(len(overview_selection(data)['unplaced_node_ids']), 5)

    def test_shared_ancestors_and_cycles_terminate_without_fabricated_links(self):
        data = example()
        data['relationships'] += [dict(source_id='g', target_id='p', basis='derived', kind='part_of'),
                                 dict(source_id='p', target_id='c', basis='explicit', kind='supports')]
        self.assertEqual(overview_selection(data)['folded_node_ids'], ['p'])

    def test_detached_segment_is_unplaced_not_attached_by_type(self):
        data = example()
        data['relationships'] = [e for e in data['relationships'] if e['source_id'] != 's']
        actual = overview_selection(data)
        self.assertEqual(actual['selected_node_ids'], ['c', 'g'])
        self.assertIn('s', actual['unplaced_node_ids'])

    def test_invalid_root_or_endpoints_reject(self):
        for mutation in ('root', 'endpoint', 'duplicate'):
            data = example()
            if mutation == 'root': data['businesses'][0]['kind'] = 'business'
            elif mutation == 'endpoint': data['relationships'][0]['source_id'] = 'outside'
            else: data['businesses'].append(dict(data['businesses'][0]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                overview_selection(data)

    def test_legacy_and_missing_basis_cannot_be_promoted_to_explicit(self):
        data = example(); data['schema_version'] = 'business-map-v0.1'
        with self.assertRaisesRegex(ValueError, 'business_map_v2_required'):
            overview_selection(data)
        data = example(); del data['relationships'][0]['basis']
        with self.assertRaisesRegex(ValueError, 'relationship_basis_required'):
            overview_selection(data)


if __name__ == '__main__': unittest.main()
