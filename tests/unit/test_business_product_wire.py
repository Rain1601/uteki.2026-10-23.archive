import copy
import json
import unittest

from uteki.agents.business_map.product_wire import build_wire_packet, expand_compact, semantic_projection, serialize_wire, verify_wire


def packet():
    return {'company_id':'synthetic-cobalt','document_id':'cobalt-report','period_end':'2022-11-30',
        'requested_period_label':'2022','financial_currency':'USD','financial_unit':'million',
        'source_local_path':'host/source.html','source_sha256':'a'*64,
        'blocks':[{'id':'b1','ordinal':1,'text':'Year 2022, USD millions.','section_path':['Note'], 'source_dom_path':'/html/body/table','text_sha256':'hosthash'}],
        'tables':[{'id':'t1','block_id':'b1','source_dom_path':'/html/body/table',
            'rows':[{'row_index':0,'cell_ids':['h']},{'row_index':1,'cell_ids':['blank','amount']},{'row_index':2,'cell_ids':[]}],
            'cells':[{'id':'h','text':'2022','row_index':0,'column_index':0,'rowspan':1,'colspan':2,'source_dom_path':'/html/body/table/tr[1]/td','text_sha256':'hash1'},
                     {'id':'blank','text':'','row_index':1,'column_index':0,'rowspan':1,'colspan':1,'source_dom_path':'/html/body/table/tr[2]/td[1]','text_sha256':'hash2'},
                     {'id':'amount','text':'(5)','row_index':1,'column_index':1,'rowspan':1,'colspan':1,'source_dom_path':'/html/body/table/tr[2]/td[2]','text_sha256':'hash3'}]}]}


def test_full_request_bytes_unchanged_and_source_not_mutated():
    p=packet();before=copy.deepcopy(p)
    assert serialize_wire(p) == json.dumps(p,ensure_ascii=False,separators=(',',':'))
    wire=build_wire_packet(p,'compact-v1')
    assert expand_compact(wire)==semantic_projection(p)
    assert p==before
    assert wire['tables'][0]['row_indices']==[0,1,2]
    assert wire['tables'][0]['cells'][1][1]==''
    assert wire['tables'][0]['cells'][2][1]=='(5)'
    assert wire['tables'][0]['cells'][0][5]==2
    assert 'source_dom_path' not in wire['tables'][0]['cell_columns']


def test_missing_or_inconsistent_fields_fail_closed():
    cases = [
        (lambda p:p['tables'][0]['cells'][0].pop('rowspan'),'wire_cell_key_missing'),
        (lambda p:p['tables'][0]['cells'][0].update(custom_label='only one cell'),'wire_heterogeneous_cell_fields'),
        (lambda p:p['tables'][0]['rows'][0].update(cell_ids=['amount']),'wire_row_cell_ids_mismatch'),
        (lambda p:p['tables'][0]['cells'][0].update(colspan=0),'wire_cell_geometry_invalid'),
        (lambda p:p.pop('document_id'),'wire_scope_required'),
    ]
    for mutator,error in cases:
        p=packet();mutator(p)
        with unittest.TestCase().assertRaisesRegex(ValueError,error):build_wire_packet(p,'compact-v1')


def test_consistent_extra_fields_are_preserved_as_columns():
    p=packet()
    for c in p['tables'][0]['cells']:c['is_header']=c['row_index']==0
    wire=build_wire_packet(p,'compact-v1')
    assert wire['tables'][0]['cell_columns'][-1]=='is_header'
    assert expand_compact(wire)==semantic_projection(p)


def test_changed_text_coordinates_or_scope_cannot_be_verified():
    p=packet();wire=build_wire_packet(p,'compact-v1')
    for mutate in [lambda w:w['tables'][0]['cells'][2].__setitem__(1,'5'),lambda w:w['tables'][0]['cells'][2].__setitem__(3,0),lambda w:w['scope'].update(company_id='other')]:
        changed=copy.deepcopy(wire);mutate(changed)
        with unittest.TestCase().assertRaisesRegex(ValueError,'wire_content_or_mode_mismatch'):verify_wire(p,json.dumps(changed,ensure_ascii=False,separators=(',',':')),'compact-v1')
    verify_wire(p,serialize_wire(p,'compact-v1'),'compact-v1')


def test_malformed_tuples_and_modes_are_rejected():
    p=packet();w=build_wire_packet(p,'compact-v1');w['tables'][0]['cells'][0].pop()
    with unittest.TestCase().assertRaisesRegex(ValueError,'wire_tuple_length_mismatch'):expand_compact(w)
    with unittest.TestCase().assertRaisesRegex(ValueError,'unsupported_source_wire_mode'):build_wire_packet(p,'guess')


class WireTests(unittest.TestCase):
    pass

for name, function in list(globals().items()):
    if name.startswith('test_') and callable(function):
        setattr(WireTests, name, lambda self, function=function: function())
del name, function

if __name__ == '__main__':
    unittest.main()
