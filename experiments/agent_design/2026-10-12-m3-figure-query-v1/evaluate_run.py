"""Withheld independent M3 evaluator. Never import from Query or material production.

The strict consumer checks engineering integrity. Independent rules inspect only
final selected originals and actual planner inputs; model audit agreement never
supplies a missing business premise. Unclassified substantive prose fails focus
pending Codex inspection, rather than being silently accepted.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from uteki.agents.data_query.answer_handoff import load_reviewed_data
from uteki.domain.research_data.execution_scope import ExecutionScope
from accept_materials import semantic_color

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normal(text):
    return ' '.join(text.split()).casefold()


def pointer(parent, key):
    return parent + '/' + str(key).replace('~', '~0').replace('/', '~1')


def at(value, ptr):
    for key in ptr.lstrip('/').split('/') if ptr else []:
        key = key.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def contained(root, path):
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Evaluation reference escapes explicit batch')
    return resolved


def verify_manifest(root, pin=None):
    if pin is not None and sha(root/'manifest.json') != pin:
        raise ValueError('Manifest pin changed')
    for name, expected in read(root/'manifest.json')['files'].items():
        path = contained(root, name)
        if path.is_symlink() or sha(path) != expected:
            raise ValueError('Frozen run file changed: ' + name)


class ObservedLeaves:
    """Independent reconstruction of exact leaves and character ranges delivered.

    Do not trust delivered_figures or read receipts alone. Read previews and
    pages from saved *next-call input*, retaining artifact identity and path.
    """
    def __init__(self, value):
        self.value = value
        self.seen = set()
        self.ranges = defaultdict(list)

    def full(self, value, ptr=''):
        if isinstance(value, (dict, list)) and value:
            entries = value.items() if isinstance(value, dict) else enumerate(value)
            for key, child in entries:
                self.full(child, pointer(ptr, key))
        else:
            self.seen.add(ptr)

    def preview(self, original, observed, ptr=''):
        if original == observed:
            self.full(original, ptr)
        elif isinstance(original, dict) and isinstance(observed, dict):
            for key, value in observed.items():
                if key in original:
                    self.preview(original[key], value, pointer(ptr, key))
        elif isinstance(original, list) and isinstance(observed, list):
            for i, child in enumerate(observed):
                if i < len(original):
                    self.preview(original[i], child, pointer(ptr, i))
        elif isinstance(original, str) and isinstance(observed, str) and original.startswith(observed):
            self.ranges[ptr].append((0, len(observed)))

    def page(self, page):
        required = {'pointer','unit','items','offset','end_offset','total_count','returned_count'}
        if not required <= page.keys():
            return
        ptr = page['pointer']
        value = at(self.value, ptr)
        lo, hi = page['offset'], page['end_offset']
        if lo < 0 or hi < lo or page['returned_count'] != hi-lo:
            raise ValueError('Observed page range invalid')
        items = page['items']
        if page['unit'] == 'characters':
            if not isinstance(value, str) or value[lo:hi] != items or len(value) != page['total_count']:
                raise ValueError('Observed characters differ from original artifact')
            self.ranges[ptr].append((lo,hi))
        elif page['unit'] == 'items':
            if not isinstance(value, list) or value[lo:hi] != items or len(value) != page['total_count']:
                raise ValueError('Observed items differ from original artifact')
            for i, item in enumerate(items, lo):
                self.full(item, pointer(ptr,i))
        elif page['unit'] == 'entries':
            expected = [{'key':k,'value':v} for k,v in value.items()]
            if expected[lo:hi] != items or len(expected) != page['total_count']:
                raise ValueError('Observed entries differ from original artifact')
            for item in items:
                self.full(item['value'],pointer(ptr,item['key']))
        elif page['unit'] == 'scalar' and items == [value] and (lo,hi) == (0,1):
            self.full(value,ptr)
        if not value and page['total_count'] == 0:
            self.full(value,ptr)

    def missing(self):
        leaves = []
        def visit(value, ptr=''):
            if isinstance(value,(dict,list)) and value:
                for key,child in value.items() if isinstance(value,dict) else enumerate(value):
                    visit(child,pointer(ptr,key))
                return
            if ptr in self.seen:
                return
            if isinstance(value,str):
                end=0
                for lo,hi in sorted(self.ranges[ptr]):
                    if lo > end:
                        break
                    end=max(end,hi)
                if self.ranges[ptr] and end >= len(value):
                    return
            leaves.append(ptr)
        visit(self.value)
        return leaves


def independent_reading(query, selected):
    bundle=read(query/'evidence-bundle.json')
    by_id={i['evidence_id']:i for i in bundle['items']}
    rows=[]
    for fig in selected:
        item=by_id[fig['evidence_id']]
        ref=item['artifact']; path=contained(query,ref['path'])
        if sha(path) != ref['sha256']:
            raise ValueError('Figure evidence artifact changed')
        full=read(path); observer=ObservedLeaves(full); observed_inputs=[]; selections=[]
        for turn in sorted(query.glob('turn-*')):
            if not (turn/'input.json').is_file():
                continue
            packet=read(turn/'input.json'); obs=packet.get('observation') or {}
            if obs.get('result_artifact',{}).get('artifact_id') == ref['artifact_id']:
                observer.preview(full,obs.get('result'))
                observed_inputs.append(str((turn/'input.json').relative_to(query)))
            page=obs.get('result',{})
            if isinstance(page,dict) and page.get('artifact_id') == ref['artifact_id']:
                observer.page(page)
                observed_inputs.append(str((turn/'input.json').relative_to(query)))
            for view in obs.get('items',[]):
                if view.get('artifact',{}).get('artifact_id') == ref['artifact_id']:
                    observer.preview(full,view.get('value'))
                    observed_inputs.append(str((turn/'input.json').relative_to(query)))
            decision_path=turn/'decision.json'
            if decision_path.is_file():
                decision=read(decision_path)
                if decision.get('action')=='select_figures' and fig['evidence_id'] in decision.get('figure_delivery',{}).get('evidence_ids',[]):
                    receipt=read(turn/'receipt.json')
                    if receipt['status']=='figures_selected':
                        selections.append({'decision':str(decision_path.relative_to(query)),
                            'missing_at_selection':observer.missing()})
        missing=observer.missing()
        rows.append({'figure_id':fig['figure_id'],'evidence_id':fig['evidence_id'],
            'actual_input_paths':sorted(set(observed_inputs)), 'missing_leaf_pointers':missing,
            'successful_explicit_selections':selections,
            'passed':not missing and bool(selections) and all(not s['missing_at_selection'] for s in selections)})
    return rows


def independent_body_reading(query, documents):
    """Require actual selected HTML text in this role's saved planner inputs.

    Whole contexts, bounded previews, exact child pages and retained original
    body are equivalent ways of delivering text. Source figure document_context
    does not substitute for explicitly selected HTML here.
    """
    selected={(d['source_snapshot_id'],b['block_id']):b for d in documents for b in d['blocks']}
    seen=defaultdict(list)
    bundle=read(query/'evidence-bundle.json')
    context_items=[]
    for item in bundle['items']:
        if item['kind']!='context':
            continue
        ref=item['artifact'];path=contained(query,ref['path'])
        if sha(path)!=ref['sha256']:
            raise ValueError('Body evidence artifact changed')
        full=read(path);observer=ObservedLeaves(full)
        context_items.append((full,ref,observer))
    for turn in sorted(query.glob('turn-*')):
        if not (turn/'input.json').is_file():
            continue
        packet=read(turn/'input.json');obs=packet.get('observation') or {}
        for block in packet.get('retained_body',{}).get('items',[]):
            key=block['source_snapshot_id'],block['block_id']
            if key in selected and block['text']==selected[key]['text']:
                seen[key].append(str((turn/'input.json').relative_to(query)))
        for full,ref,observer in context_items:
            if obs.get('result_artifact',{}).get('artifact_id')==ref['artifact_id']:
                observer.preview(full,obs.get('result'))
            page=obs.get('result',{})
            if isinstance(page,dict) and page.get('artifact_id')==ref['artifact_id']:
                observer.page(page)
            for view in obs.get('items',[]):
                if view.get('artifact',{}).get('artifact_id')==ref['artifact_id']:
                    observer.preview(full,view.get('value'))
            if isinstance(page,dict):
                for document in page.get('documents',[]):
                    for context in document.get('contexts',[]):
                        if context.get('source_snapshot_id')==full['source_snapshot_id']:
                            observer.preview(full,context)
            missing=set(observer.missing())
            for i,block in enumerate(full.get('blocks',[])):
                key=full['source_snapshot_id'],block['block_id']
                if key in selected and block['text']==selected[key]['text'] and '/blocks/'+str(i)+'/text' not in missing:
                    seen[key].append(str((turn/'input.json').relative_to(query)))
    return [{'source_snapshot_id':sid,'block_id':bid,'actual_input_paths':sorted(set(seen[(sid,bid)])),
        'passed':bool(seen[(sid,bid)])} for sid,bid in selected]


def prose_components(documents, expected):
    """Source-original semantic premises, not block-ID/character-count scoring.

    Each class's exact source paragraph is split into statements. Multiple final
    selected blocks and repeated equivalent source occurrences may cover them.
    Source-bound whole paragraphs may use a new block ID or layout. Shared
    assumptions never establish the other class without its subject premise.
    """
    blocks=[{'source_snapshot_id':d['source_snapshot_id'],**b} for d in documents for b in d['blocks']]
    checks=[]; relevant=set()
    for gold in expected['required_prose_references']:
        text=gold['text']
        stock='Class A' if 'Class A' in text else 'Class C'
        identity=text[:text.index(' The graph tracks')]
        clauses={
            'comparison_identity':identity,
            'observation_period':'from December 31, 2020, to December 31, 2025.',
            'baseline_investment':'The graph tracks the performance of a $100 investment',
            'dividend_reinvestment':'(with the reinvestment of all dividends)',
            'historical_limit':'The returns shown are based on historical results and are not intended to suggest future performance.'}
        # Same-source contextual block groups preserve the stock identity when
        # parsers split sentences. Gold text is evaluation-only, never execution.
        by_source=defaultdict(list)
        for b in blocks:
            if normal(b['text']) in normal(text) or normal(text) in normal(b['text']):
                by_source[b['source_snapshot_id']].append(b)
        class_rows=[]
        for sid, group in by_source.items():
            joined=' '.join(b['text'] for b in group)
            if normal(identity) not in normal(joined):
                continue
            class_rows.extend(group)
        class_text=' '.join(b['text'] for b in class_rows)
        for name,clause in clauses.items():
            passed=normal(clause) in normal(class_text)
            refs=[{'source_snapshot_id':b['source_snapshot_id'],'block_id':b['block_id'],
                'quote':b['text']} for b in class_rows if normal(clause) in normal(b['text']) or normal(b['text']) in normal(clause)]
            checks.append({'component':stock+' '+name,'passed':passed,'references':refs})
        relevant.update((b['source_snapshot_id'],b['block_id']) for b in class_rows)
    extras=[]; headings=[]; repeats=[]; seen={}
    for b in blocks:
        key=b['source_snapshot_id'],b['block_id']; normalized=normal(b['text'])
        if key in relevant:
            residue=normalized
            for gold in expected['required_prose_references']:
                original=normal(gold['text'])
                if residue in original:
                    residue='';break
                residue=residue.replace(original,'').strip()
            if residue:
                extras.append({'source_snapshot_id':key[0],'block_id':key[1],'text':b['text'],
                    'unclassified_remainder':residue,
                    'reason':'Relevant original premises bundled with additional unclassified substantive prose; Codex must inspect'})
            if normalized in seen:
                repeats.append({'source_snapshot_id':key[0],'block_id':key[1],'duplicates':seen[normalized],
                    'reason':'Repeated original explanation adds no new information for this question'})
            seen[normalized]=b['block_id']
        elif b.get('type')=='image':
            headings.append({'source_snapshot_id':key[0],'block_id':key[1],'reason':'Source figure position marker'})
        elif normalized in {'stock performance','stock performance graph','class a','class c','class a common stock','class c capital stock'}:
            headings.append({'source_snapshot_id':key[0],'block_id':key[1],'reason':'Relevant identity heading'})
        else:
            extras.append({'source_snapshot_id':key[0],'block_id':key[1],'text':b['text'],
                'reason':'Not classified as a required premise or necessary original figure context; Codex must inspect'})
    return checks,extras,repeats,headings


def figure_components(figures, gold):
    checks=[]; hashes=[f['image_sha256'] for f in figures]
    checks.append({'component':'exactly two original images','passed':Counter(hashes)==Counter(gold['images'].keys())})
    for f in figures:
        label=gold['images'].get(f['image_sha256'],'unknown image')
        t=f['transcription']; ids={x['id']:x['text'] for x in t['texts']}
        texts=lambda role:[x['text'] for x in t['texts'] if x['role']==role]
        colors={ids[s['legend_id']]:semantic_color(s['color']) for s in t['series']}
        criteria={'comparison identities':Counter(texts('legend'))==Counter([label,*gold['legend_other']]),
            'observation ticks':Counter(texts('x_tick'))==Counter(gold['x_ticks']),
            'scale ticks':Counter(texts('y_tick'))==Counter(gold['y_ticks']),
            'no missing or extra visible text':len(t['texts'])==gold['visible_text_count_per_image'],
            'no printed curve point values':t['printed_values']==[],
            'no invented image title':texts('title')==[],
            'no unreadable omissions':t['unreadable_regions']==[],
            'curve identity/colors':set(colors)=={label,*gold['legend_other']} and all(v in gold['colors'].get(k,[]) for k,v in colors.items()),
            'original bytes':sha(f['original_image_path'])==f['image_sha256'],
            'strong image-bound OCR':f['status']==f['coordinate_status']=='ocr_grounded'}
        for name,passed in criteria.items():
            checks.append({'component':label+' '+name,'passed':passed,
                'reference':{'source_snapshot_id':f['source_snapshot_id'],'figure_id':f['figure_id'],
                    'image_sha256':f['image_sha256'],'transcription_sha256':f['transcription_sha256']}})
    return checks


def evaluate(base, slot, version, question_expected, material_expected):
    folder=base/('query-'+version)/slot; cycle=read(folder/'run/result.json')
    config=read(folder/'runtime-config.json'); freeze=read(base/('query-'+version)/('input-freeze.'+version+'.json'))
    question=read(HERE/'question.v1.json')['question']
    pins={'question':sha(HERE/'question.v1.json')==question_expected['question_sha256']==freeze['question_sha256'],
        'three repetitions':question_expected['repetitions']==freeze['repetitions']==3,
        'withheld question standard':sha(base/'evaluation-only/question-expected.v1.json')==freeze['question_standard_sha256'],
        'material gold':sha(material_expected)==question_expected['material_expected_sha256'],
        'dataset freeze':sha(Path(config['request']['dataset'])/'manifest.json')==freeze['dataset_manifest_sha256'],
        'figure freeze':sha(Path(config['request']['figure_bundle_ref']['path'])/'manifest.json')==freeze['figure_manifest_sha256']==config['request']['figure_bundle_ref']['manifest_sha256'],
        'independent material acceptance':sha(base/'evaluation-only'/('material-acceptance.'+freeze['material_version']+'.json'))==freeze['independent_acceptance_sha256'] and read(base/'evaluation-only'/('material-acceptance.'+freeze['material_version']+'.json'))['passed'],
        'cycle question':cycle['question']==question==config['request']['question'],
        'cycle scope':cycle['scope']==ExecutionScope.model_validate(config['request']['scope']).model_dump(mode='json'),
        'successful terminal status':cycle['status']=='reviewed_data_ready',
        'no Analysis invoked':cycle['analysis_called'] is False}
    before,after=read(folder/'budget-before.json'),read(folder/'budget-after.json')
    cost={**after,'slot_estimated_spent_usd':str(Decimal(after['estimated_spent_usd'])-Decimal(before['estimated_spent_usd'])),
        'slot_request_count':after['requests']-before['requests'],
        'scope':'Whole slot includes failed/revised calls; image preparation is in shared task total, not charged again here'}
    report={'schema':'m3-independent-query-acceptance-v1','slot':slot,'question':question,
        'cycle_status':cycle['status'],'pins':pins,'attempt_history':cycle['attempts'],
        'first_attempt_pass':len(cycle['attempts'])==1 and cycle['status']=='reviewed_data_ready',
        'cost':cost,'missing':[], 'extra':[], 'passed':False,
        'business_scope':'One frozen source question, three predetermined repetitions; no claim of long-term stability',
        'evaluation_origin':'Independent withheld original-material rules, separate from both model audits'}
    try:
        verify_manifest(folder/'run')
        for path, expected in freeze['implementation'].items():
            if sha(HERE.parents[2]/path)!=expected:
                raise ValueError('Frozen runtime implementation changed: '+path)
        if not all(pins.values()):
            raise ValueError('Input, denominator or terminal pin failed')
        review_ref=cycle['final_review_ref']; review=contained(base,review_ref['path'])
        handoff=load_reviewed_data(review,expected_scope=cycle['scope'],
            expected_review_manifest_sha256=review_ref['manifest_sha256'])
        packet=read(review/'input.json'); audit=read(review/'result.json')
        if packet['delivery_schema_version']!='selected-originals-v5' or handoff['execution_origin']!='model':
            raise ValueError('Real selected-originals-v5 handoff required')
        query=contained(base,cycle['final_query_ref']['path'])
        verify_manifest(query,cycle['final_query_ref']['manifest_sha256'])
        figures=handoff['source_figures']; documents=handoff['source_documents']
        prose,extras,repeats,context=prose_components(documents,question_expected)
        visual=figure_components(figures,read(material_expected))
        reading=independent_reading(query,figures)
        body_reading=independent_body_reading(query,documents)
        numeric=[f for f in handoff['facts'] if f['kind']=='record']
        report.update(strict_load_pass=True,delivery_schema_version=packet['delivery_schema_version'],
            dual_audit={'source_policy':packet['source_review_policy'],'question_policy':packet['question_review_policy'],
                'source_coverage':audit['assessment']['question_coverage'],
                'source_response_path':str(review/'source-response.json'),
                'question_response_path':str(review/'question-response.json')},
            selected_figures=[{'figure_id':f['figure_id'],'image_sha256':f['image_sha256']} for f in figures],
            selected_prose=[{'source_snapshot_id':d['source_snapshot_id'],'block_id':b['block_id'],'text':b['text']}
                for d in documents for b in d['blocks']],
            semantic_checks=prose+visual,actual_role_reading=reading,actual_body_reading=body_reading,
            role_audit_status=('parent_actual_inputs_verified' if all(r['passed'] for r in reading+body_reading)
                else 'uncertified_role_reading_requires_Codex_inspection; not a newly invented business omission'),
            missing=[c['component'] for c in prose+visual if not c['passed']],
            extra=extras+repeats+[{'reason':'Unrequested financial/numeric record','fact_id':f['fact_id']} for f in numeric],
            allowed_context=context,
            sufficient_to_support=['Source-bound comparison identities and assumptions' if all(c['passed'] for c in prose)
                else 'Only components marked passed; missing premises prevent full requested coverage',
                'Original labels, legend colors and printed ticks; no exact curve observation values'],
            no_curve_estimates=not numeric and all(f['transcription']['printed_values']==[] for f in figures),
            review_ref=review_ref,query_ref=cycle['final_query_ref'])
        report['passed']=(not report['missing'] and not report['extra'] and all(r['passed'] for r in reading)
            and all(r['passed'] for r in body_reading)
            and report['no_curve_estimates'] and audit['analysis_eligible'] and handoff['execution_origin']=='model')
    except (ValueError,KeyError,FileNotFoundError,TypeError) as error:
        report['failure']={'type':type(error).__name__,'message':str(error)}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--slot',choices=['R1','R2','R3'],required=True)
    parser.add_argument('--query-version',default='v1',choices=['v1','v2'])
    parser.add_argument('--material-expected',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();base=args.batch.resolve()
    expected=read(base/'evaluation-only/question-expected.v1.json')
    result=evaluate(base,args.slot,args.query_version,expected,args.material_expected)
    output=args.output or base/'evaluation-only'/('query-'+args.query_version+'-'+args.slot+'.json')
    with output.open('x',encoding='utf8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'slot':args.slot,'passed':result['passed'],'missing':result['missing'],
        'extra':len(result['extra']),'failure':result.get('failure'),'cost':result['cost']},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
