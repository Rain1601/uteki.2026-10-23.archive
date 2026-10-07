"""Independent semantic display boundaries. Synthetic data is never a model run."""
from copy import deepcopy
import html
import unittest

from uteki.presentation.business_map_view import mermaid,inline_svg,presentation


def fixture():
    text='Orion has Nimbus. Nimbus supports Helix.'
    excerpt={'evidence_id':'source-block','quote':text}
    nodes=[]
    for ident,name,kind in [('orion','Orion','company'),('nimbus','Nimbus','business'),('helix','Helix','offering_group')]:
        nodes.append(dict(id=ident,name=name,kind=kind,description=text,evidence_ids=['source-block'],
            claim_evidence=[dict(field=f,item_index=None,excerpts=[excerpt]) for f in ('name','description')]))
    def edge(source,target,kind,basis):
        return dict(source_id=source,target_id=target,kind=kind,basis=basis,description='Selected relationship.',
            rationale='Explicit test premise.' if basis=='explicit' else 'Synthetic inference or unresolved scope.',
            evidence_ids=['source-block'],excerpts=[excerpt])
    return dict(schema_version='business-map-v0.2',company_id='orion',document_id='filing-2031',
        relationship_absence='unknown',summary='Synthetic scope.',businesses=nodes,
        relationships=[edge('nimbus','orion','part_of','explicit'),edge('nimbus','helix','supports','derived'),
            edge('helix','orion','reported_under','unknown')],
        unknowns=[dict(id='gap',question='Where is Helix reported?',materiality='unassessed',
            reason_unanswered='Selected source does not establish segment membership.',related_business_ids=['helix','orion'])],
        evidence=[dict(id='source-block',company_id='orion',document_id='filing-2031',section_path=['Products'],
            paragraph_ordinal=1,text_hash='a'*64,source_url='https://example.invalid/report',support=text)])


def svg_fixture(view):
    nodes=''.join(f'<g class="node" id="flowchart-{key}-{i}"><text>{html.escape(view["labels"][nid])}</text></g>'
        for i,(nid,key) in enumerate(view['ids'].items()))
    edges=''
    for i,e in enumerate(view['edges']):
        ident=f'L_{e["source"]}_{e["target"]}_{i}'
        style='dotted' if e['basis']=='derived' else 'solid'
        edges+=f'<path id="{ident}" class="flowchart-link edge-pattern-{style}"/><g class="label" data-id="{ident}"><text>{html.escape(e["label"])}</text></g>'
    return '<svg xmlns="http://www.w3.org/2000/svg">'+nodes+edges+'</svg>'


class BusinessMapViewTests(unittest.TestCase):
    def test_explicit_derived_unknown_and_support_direction_remain_distinct(self):
        data=fixture();frozen=deepcopy(data)
        code,view=mermaid(data)
        self.assertIn('N000 -->|"R01',code)
        self.assertIn('N001 -.->|"R02',code)
        self.assertNotIn('R03',code)
        self.assertEqual(view['unresolved'][0]['index'],2)
        self.assertEqual(data,frozen)
        rendered=inline_svg(svg_fixture(view),view)
        self.assertIn('data-relation-key="R02"',rendered)
        self.assertIn('data-node-key="N002"',rendered)

    def test_no_edge_is_kept_as_node_not_invented_independence_or_parent(self):
        data=fixture();data['relationships']=[]
        code,view=mermaid(data)
        self.assertEqual(len(view['ids']),3)
        self.assertEqual(view['edges'],[])
        self.assertIn('absent edges do not imply independence',code)
        self.assertNotIn('-->',code)

    def test_mutated_labels_edges_basis_and_active_svg_are_rejected(self):
        view=presentation(fixture());raw=svg_fixture(view)
        variants=[raw.replace('Orion</text>','Another</text>'),raw.replace('L_N000_N001_0','L_N001_N000_0'),
            raw.replace('edge-pattern-dotted','edge-pattern-solid'),raw.replace('</svg>','<script>x</script></svg>'),
            raw.replace('<text>Orion','<text onclick="bad()">Orion'),
            raw.replace('</svg>','<a href="https://bad.invalid"/></svg>')]
        for candidate in variants:
            with self.subTest(candidate=candidate[:80]),self.assertRaises(ValueError):inline_svg(candidate,view)

    def test_labels_cannot_inject_mermaid_and_revenue_is_separate(self):
        data=fixture();data['businesses'][0]['name']='Orion "\n X-->Y <script>'
        data['evidence'][0]['support']+=' Orion " X-->Y <script>'
        data['businesses'][0]['claim_evidence'][0]['excerpts']=[dict(evidence_id='source-block',quote='Orion')]
        code,_=mermaid(data)
        self.assertNotIn('\n X-->',code)
        self.assertIn('#quot;',code)
        data=fixture();data['businesses'][1]['kind']='revenue_line'
        with self.assertRaisesRegex(ValueError,'separate_business_and_revenue_dimensions'):mermaid(data)


if __name__=='__main__':unittest.main()
