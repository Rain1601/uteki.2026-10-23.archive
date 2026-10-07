"""BusinessMap v0.2 -> evidence-aware Mermaid/SVG. No company defaults or API calls."""
from collections import Counter
import re
import xml.etree.ElementTree as ET

from uteki.domain.business_map import business_map_from_dict

KIND = {'company':'公司 / Company','reportable_segment':'报告分部 / Segment',
        'business':'业务 / Business','offering_group':'产品服务 / Offering'}
BASIS = {'explicit':'原文明示 / Explicit','derived':'有据推断 / Derived','unknown':'尚未确定 / Unknown'}
RELATION = {'part_of':'属于 / Part of','reported_under':'报告列于 / Reported under','supports':'支撑 / Supports'}
INVERSE = {'part_of':'包含 / Includes','reported_under':'报告列示 / Reports','supports':'支撑 / Supports'}


def _label(value):
    return (str(value).replace('&','#amp;').replace('"','#quot;').replace('<','#lt;')
            .replace('>','#gt;').replace('\r',' ').replace('\n',' '))


def presentation(data):
    if data.get('schema_version')!='business-map-v0.2':
        raise ValueError('business_map_v2_required')
    business_map_from_dict(data)
    if any(n['kind'] not in KIND for n in data['businesses']) or any(
            e['kind'] not in RELATION for e in data['relationships']):
        raise ValueError('separate_business_and_revenue_dimensions')
    ids={n['id']:f'N{i:03}' for i,n in enumerate(data['businesses'])}
    labels={n['id']:n['name'] for n in data['businesses']}
    edges,unresolved=[],[]
    for i,edge in enumerate(data['relationships']):
        item={'index':i,'id':f'R{i+1:02}','basis':edge['basis'],'kind':edge['kind'],
            'domain_source':edge['source_id'],'domain_target':edge['target_id']}
        if edge['basis']=='unknown':
            unresolved.append(item)
            continue
        source,target=(edge['source_id'],edge['target_id']) if edge['kind']=='supports' else (edge['target_id'],edge['source_id'])
        item.update(source=ids[source],target=ids[target],
            label=f'{item["id"]} · {INVERSE[edge["kind"]]} · '+('明示' if edge['basis']=='explicit' else '推断'))
        edges.append(item)
    return {'ids':ids,'labels':labels,'edges':edges,'unresolved':unresolved}


def mermaid(data):
    view=presentation(data)
    lines=['flowchart LR','  accTitle: Selected filing business structure',
        '  accDescr: Solid edges are explicit source assertions. Dashed edges are derived. Unknown relations are omitted; absent edges do not imply independence.']
    for node in data['businesses']:
        lines.append(f'  {view["ids"][node["id"]]}["{_label(node["name"])}"]:::{node["kind"]}')
    for edge in view['edges']:
        arrow='-->' if edge['basis']=='explicit' else '-.->'
        lines.append(f'  {edge["source"]} {arrow}|"{_label(edge["label"])}"| {edge["target"]}')
    lines.extend(['  classDef company fill:#263c46,color:#fff,stroke:#263c46,stroke-width:1.5px',
        '  classDef reportable_segment fill:#e4eef2,color:#203c49,stroke:#91aeba,stroke-width:1px',
        '  classDef business fill:#eaf1e9,color:#2b4432,stroke:#a4b8a7,stroke-width:1px',
        '  classDef offering_group fill:#fff,color:#302c26,stroke:#c9c2b7,stroke-width:1px'])
    return '\n'.join(lines)+'\n',view


def inline_svg(raw,view):
    """Validate rendered identities, labels, direction and basis before embedding."""
    svg=ET.fromstring(raw)
    reverse={v:k for k,v in view['ids'].items()}
    compact=lambda s:''.join(s.split())
    seen=[]
    for el in svg.iter():
        if el.tag.split('}')[-1] in {'script','foreignObject','image','iframe'}:
            raise ValueError('active_svg_not_allowed')
        for key,value in el.attrib.items():
            if key.lower().startswith('on') or (key.split('}')[-1]=='href' and not value.startswith('#')):
                raise ValueError('active_svg_reference')
        text=' '.join(el.attrib.values())+(el.text or '')
        if re.search(r'@import|url\(\s*["\']?\s*(?!#)[^\s"\')]',text,re.I):
            raise ValueError('external_svg_style')
        if 'node' in el.get('class','').split():
            match=re.fullmatch(r'flowchart-(N\d+)-\d+',el.get('id',''))
            if not match or match[1] not in reverse:
                raise ValueError('svg_node_mismatch')
            nid=reverse[match[1]]
            if compact(''.join(el.itertext()))!=compact(view['labels'][nid]):
                raise ValueError('svg_label_mismatch')
            seen.append(nid)
            el.set('data-node-key',match[1]);el.set('tabindex','0');el.set('role','button')
            el.set('aria-label','查看依据 / Evidence: '+view['labels'][nid])
    if Counter(seen)!=Counter(view['ids'].keys()):
        raise ValueError('svg_node_mismatch')
    labels={e.get('data-id'):compact(''.join(e.itertext())) for e in svg.iter()
            if e.get('class')=='label' and e.get('data-id')}
    expected={(e['source'],e['target'],compact(e['label'])):e for e in view['edges']}
    observed=[]
    for el in svg.iter():
        if 'flowchart-link' not in el.get('class','').split():continue
        match=re.fullmatch(r'L_(N\d+)_(N\d+)_\d+',el.get('id',''))
        if not match:raise ValueError('svg_edge_mismatch')
        key=(*match.groups(),labels.get(el.get('id')))
        edge=expected.get(key)
        if edge is None:raise ValueError('svg_edge_mismatch')
        dotted='edge-pattern-dotted' in el.get('class','').split()
        if dotted!=(edge['basis']=='derived'):raise ValueError('svg_basis_style_mismatch')
        observed.append(key)
        el.set('data-relation-key',edge['id']);el.set('tabindex','0');el.set('role','button')
        el.set('aria-label',edge['label'])
    if Counter(observed)!=Counter(expected.keys()):raise ValueError('svg_edge_mismatch')
    ET.register_namespace('','http://www.w3.org/2000/svg')
    return ET.tostring(svg,encoding='unicode')
