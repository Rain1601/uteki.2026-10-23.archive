"""Independent evaluator; never imported by material producer or Query Agent."""
import argparse,json,hashlib,re,colorsys
from collections import Counter
from pathlib import Path
from uteki.infrastructure.document_sources.figure_reader import FigureMaterialReader

def semantic_color(value):
    # Compare the frozen visual color category, not invented exact RGB precision.
    value=value.lower().strip()
    if re.fullmatch(r'#[0-9a-f]{6}',value):
        rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
        h,s,v=colorsys.rgb_to_hsv(*rgb);h*=360
        if s<0.25 or v<0.15:return 'unclassified'
        if h<30 or h>=330:return 'red'
        if 30<=h<75:return 'yellow'
        if 75<=h<165:return 'green'
        if 180<=h<270:return 'blue'
        return 'unclassified'
    return value

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True)
    p.add_argument('--expected',type=Path,required=True)
    p.add_argument('--material-version',choices=['v1','v2','v3'],required=True);args=p.parse_args()
    base=args.batch.resolve();gold=json.loads(args.expected.read_bytes());rows=[];bindings={}
    for c in ('msft','googl'):
        bindings[c]={'dataset_manifest_sha256':sha(base/'preparation'/c/'dataset/manifest.json'),
            'figure_manifest_sha256':sha(base/('transcribed-'+args.material_version)/c/'manifest.json')}
        reader=FigureMaterialReader(base/('transcribed-'+args.material_version)/c,base/'preparation'/c/'dataset')
        for entry in reader.list():
            m=reader.read(entry['figure_id']);t=m['transcription'];g=gold['images'][m['image_sha256']]
            role=lambda name: [x['text'] for x in t['texts'] if x['role']==name]
            ids={x['id']:x['text'] for x in t['texts']}
            colors={ids[s['legend_id']]:semantic_color(s['color']) for s in t['series']}
            checks={'legends':Counter(role('legend'))==Counter([g,*gold['legend_other']]),
                'x_ticks':Counter(role('x_tick'))==Counter(gold['x_ticks']),
                'y_ticks':Counter(role('y_tick'))==Counter(gold['y_ticks']),
                'text_count':len(t['texts'])==gold['visible_text_count_per_image'],
                'no_extra_title':role('title')==[], 'no_invented_point_values':t['printed_values']==[],
                'no_unreadable_regions':t['unreadable_regions']==[],
                'kind':t['kind']==gold['kind'],
                'colors':set(colors)=={g,*gold['legend_other']} and all(v in gold['colors'][k] for k,v in colors.items()),
                'strong_ocr_grounding':m['coordinate_status']=='ocr_grounded',
                'original_hash':hashlib.sha256(Path(m['original_image_path']).read_bytes()).hexdigest()==m['image_sha256']}
            rows.append({'figure_id':m['figure_id'],'source_snapshot_id':m['source_snapshot_id'],
                'image_sha256':m['image_sha256'],'checks':checks,'colors':colors})
    result={'schema':'m3-independent-material-acceptance-v1','expected_sha256':hashlib.sha256(args.expected.read_bytes()).hexdigest(),
        'material_version':args.material_version,'bindings':bindings,'figures':rows,
        'passed':Counter(r['image_sha256'] for r in rows)==Counter(gold['images'].keys()) and all(all(r['checks'].values()) for r in rows),
        'inspection':'Codex independently viewed originals; deterministic checks use withheld pre-run evaluation values',
        'query_model_execution':False}
    path=base/('evaluation-only/material-acceptance.'+args.material_version+'.json')
    with path.open('x') as f:json.dump(result,f,indent=2,ensure_ascii=False)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
