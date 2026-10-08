"""Portable, pinned Data-only retrieval-suite delivery; never starts model work."""
from html import escape
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import quote, unquote, urlsplit

from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.financial_records import digest
from .data_review_delivery import render_data_review, validate_source_preview_config, _STYLE
from ..components.report_text import render_report

_STATUS = {
    'reviewed_data_ready':'模型复核通过 / Model reviewed',
    'attempts_exhausted':'修订轮次用尽 / Revision limit reached',
    'blocked_by_query':'检索未交付 / Retrieval blocked',
    'blocked_by_review_failure':'复核失败 / Review failed',
    'failed':'运行失败 / Failed', 'cancelled':'已取消 / Cancelled',
}


def _read(path):
    return json.loads(path.read_bytes())


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Explicit pinned SHA256 required')
    return value


def _path(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Explicit artifact path required')
    path = Path(value)
    return (base/path).resolve() if not path.is_absolute() else path.resolve()


def _frozen(root, sha, required=()):
    manifest = _verify_manifest(root, _sha(sha))
    if not set(required) <= manifest['files'].keys():
        raise ValueError('Required artifact missing from frozen manifest')
    for name in manifest['files']:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Frozen manifest requires contained relative file names')
        path = root/name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Frozen delivery files must be regular files')
    return manifest


def _link(path, label):
    return '<a href="' + escape(quote(path, safe='/#'), quote=True) + '">' + escape(label) + '</a>'


def _copy_frozen(root, manifest, target):
    target.mkdir(parents=True)
    for name in (*manifest['files'], 'manifest.json'):
        dest = target/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, dest)
    return [*manifest['files'], 'manifest.json']


def _assessment_page(assessment, dest, copied):
    """Render only verified copied targets as local links; keep input bytes intact."""
    path, raw = assessment['path'], assessment['raw']
    original = 'independent-assessment' + path.suffix
    (dest/original).write_bytes(raw)
    copied = dict(copied)
    copied[path] = original
    attachments = []
    for item in assessment['attachments']:
        target = 'assessment-files/' + item['path'].name
        (dest/target).parent.mkdir(exist_ok=True)
        (dest/target).write_bytes(item['raw'])
        copied[item['path']] = target
        attachments.append({'path':target,'sha256':digest(item['raw'])})
    unresolved, external, replacements = [], [], {}
    text = raw.decode('utf-8')
    def link(match):
        label, href = match.groups()
        parsed = urlsplit(href)
        if parsed.scheme in {'https','http'} and parsed.netloc:
            external.append(href)
            return '[' + label + '（外部来源，未随包复制 / External source）](' + href + ')'
        if not parsed.scheme and not parsed.netloc and not parsed.query and parsed.path:
            source = (path.parent/unquote(parsed.path)).resolve()
            if source in copied:
                target = quote(copied[source], safe='/')
                if parsed.fragment:
                    target += '#' + quote(unquote(parsed.fragment), safe='')
                token = 'https://uteki-assessment.invalid/' + str(len(replacements))
                replacements[token] = target
                return '[' + label + '](' + token + ')'
        unresolved.append(href)
        return label + '（未随包复制的来源 / Not bundled: ' + href + '）'
    if path.suffix == '.md':
        body = render_report(re.sub(r'\[([^\]]+)\]\(([^\s)]+)\)', link, text))
        for token, target in replacements.items():
            body = body.replace('href="'+token+'"', 'href="'+escape(target,quote=True)+'"')
    else:
        body = '<pre>' + escape(text) + '</pre>'
    metadata = {'original_path':original,'original_sha256':digest(raw),'attachments':attachments,
        'portable_link_count':len(replacements),'external_sources':external,'unbundled_sources':unresolved}
    (dest/'independent-assessment-links.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>独立验收 / Independent assessment</title><style>'+_STYLE+
        '.report-table{overflow:auto}table{border-collapse:collapse}th,td{padding:8px;border:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><main>'
        '<p>'+_link('../../index.html','返回验收入口 / Back')+'</p><h1>独立验收 / Independent assessment</h1>'
        '<p>本页只重映射已核验的交付副本链接，不改变验收结论。原 Markdown 内路径为执行时记录。外部来源依赖网络；未随包复制的路径只作来源说明。</p><p>'
        +_link(original,'原始文件（原样封存）/ Original')+' · '+_link('independent-assessment-links.json','文件校验与链接说明 / Integrity')+'</p>'
        +body+'</main></html>')
    (dest/'independent-assessment.html').write_text(page)
    return metadata


def render_data_retrieval_suite(suite_file, output):
    """Resolve only explicitly named sealed cycles and write one new portable directory.

    Relative input paths resolve against suite_file. Original JSON stays unchanged;
    page links point to copied artifacts. Optional independent assessments are pinned
    files, not an inferred acceptance verdict. No source registry or API is used.
    """
    suite_file, output = Path(suite_file).resolve(), Path(output).resolve()
    raw = suite_file.read_bytes(); suite = json.loads(raw)
    if (not isinstance(suite, dict) or set(suite) != {'schema_version','cases'}
            or suite['schema_version'] != 'data-retrieval-suite-v1'
            or not isinstance(suite['cases'], list) or not suite['cases']):
        raise ValueError('Explicit nonempty data-retrieval-suite-v1 cases required')
    if output.exists() or suite_file.is_relative_to(output):
        raise ValueError('Delivery output must be new and outside inputs')
    cases, ids, protected = [], set(), [suite_file.parent]
    for selected in suite['cases']:
        if (not isinstance(selected, dict) or not {'case_id','cycle_dir','manifest_sha256'} <= selected.keys()
                or set(selected)-{'case_id','cycle_dir','manifest_sha256','independent_assessment','preview'}):
            raise ValueError('Explicit case identity, cycle directory and manifest hash required')
        cid = selected['case_id']
        if not isinstance(cid,str) or not re.fullmatch('[a-z0-9][a-z0-9-]{0,95}',cid) or cid in ids:
            raise ValueError('Unique safe case_id required')
        ids.add(cid)
        preview = selected.get('preview', {})
        if 'preview' in selected:
            if (not isinstance(preview,dict) or set(preview)!={'dataset_key','source_preview_base_url'}
                    or any(value is None for value in preview.values())):
                raise ValueError('Preview requires both explicit dataset_key and source_preview_base_url')
            validate_source_preview_config(**preview)
        cycle = _path(selected['cycle_dir'],suite_file.parent)
        manifest = _frozen(cycle,selected['manifest_sha256'],('result.json','original-request.json'))
        result, request = _read(cycle/'result.json'), _read(cycle/'original-request.json')
        if (result.get('schema_version')!='data-retrieval-cycle-v1' or result.get('status') not in _STATUS
                or result.get('purpose')!='analysis_evidence' or request.get('purpose')!='analysis_evidence'
                or result.get('analysis_called') is not False
                or result.get('question')!=request.get('question') or result.get('scope')!=request.get('scope')
                or not isinstance(result.get('question'),str) or not result['question'].strip()
                or not result.get('scope',{}).get('company_ids')):
            raise ValueError('Cycle result must bind the original Data-only request and terminal state')
        attempts = result.get('attempts')
        if not isinstance(attempts,list) or any(a.get('attempt')!=i+1 or a.get('status')=='running' for i,a in enumerate(attempts)):
            raise ValueError('Cycle attempts must be ordered and terminal')
        for attempt in attempts:
            relative = attempt.get('path')
            if relative != f"attempt-{attempt['attempt']:02d}" or relative+'/result.json' not in manifest['files']:
                raise ValueError('Attempt result is not bound in the cycle manifest')
            if _read(cycle/relative/'result.json') != attempt:
                raise ValueError('Cycle attempt differs from its frozen result')
        case = {'id':cid,'cycle':cycle,'manifest':manifest,'result':result,'review':None,'assessment':None,'external':[], 'preview':preview}
        protected.append(cycle)
        ref = result.get('final_review_ref')
        if ref is not None:
            if not isinstance(ref,dict) or set(ref)!={'path','manifest_sha256'}:
                raise ValueError('Final review must have an explicit frozen reference')
            review = _path(ref['path'],cycle)
            rm = _frozen(review,ref['manifest_sha256'],('input.json','result.json'))
            packet, verdict = _read(review/'input.json'), _read(review/'result.json')
            if (packet.get('question')!=result['question'] or packet.get('scope')!=result['scope']
                    or packet.get('purpose')!='analysis_evidence'
                    or packet.get('query_ref')!=result.get('final_query_ref')):
                raise ValueError('Review differs from original suite case question or scope')
            if (not attempts or attempts[-1].get('query_ref')!=result.get('final_query_ref')
                    or not any(r.get('review_ref')==ref for r in attempts[-1].get('reviews',[]))):
                raise ValueError('Final review is not recorded in the final attempt')
            if result['status']=='reviewed_data_ready' and (verdict.get('status')!='reviewed' or verdict.get('analysis_eligible') is not True):
                raise ValueError('Successful cycle requires an eligible reviewed result')
            case['review']=(review,rm,ref,packet)
            protected += [review,Path(packet['query_ref']['path']).resolve(),Path(packet['dataset_ref']['path']).resolve()]
        elif result['status']=='reviewed_data_ready':
            raise ValueError('Successful cycle is missing its final review')
        # Resumed frozen queries can sit outside the cycle. Copy their trace too.
        for attempt in attempts:
            for field in ('query_run_ref','query_ref'):
                ref = attempt.get(field)
                if not ref: continue
                root = _path(ref['path'],cycle)
                fm = _frozen(root,ref['manifest_sha256'])
                protected.append(root)
                if not root.is_relative_to(cycle) and not any(root.is_relative_to(r) for r,_,_ in case['external']):
                    case['external'].append((root,fm,f'external-query-{len(case["external"])+1}'))
        independent = selected.get('independent_assessment')
        if independent is not None:
            if (not isinstance(independent,dict) or not {'path','sha256'} <= set(independent)
                    or set(independent)-{'path','sha256','attachments'}):
                raise ValueError('Independent assessment must have a path and SHA256')
            path = _path(independent['path'],suite_file.parent)
            content=path.read_bytes()
            if path.suffix not in {'.json','.md','.txt'} or digest(content)!=_sha(independent['sha256']):
                raise ValueError('Independent assessment type/hash mismatch')
            assessment_raw=content
            attachments = independent.get('attachments', [])
            if not isinstance(attachments,list) or len(attachments)>8:
                raise ValueError('Assessment attachments must be an explicit bounded JSON list')
            pinned, names = [], set()
            for item in attachments:
                if not isinstance(item,dict) or set(item)!={'path','sha256'}:
                    raise ValueError('Each assessment attachment requires path and SHA256')
                name=item['path']
                if (not isinstance(name,str) or Path(name).name!=name or Path(name).suffix!='.json'
                        or name in names):
                    raise ValueError('Assessment attachments must be unique same-directory JSON filenames')
                names.add(name)
                child=path.parent/name
                if child.is_symlink() or not child.is_file() or child.resolve().parent!=path.parent:
                    raise ValueError('Assessment attachment must be a regular same-directory file')
                content=child.read_bytes()
                if digest(content)!=_sha(item['sha256']):
                    raise ValueError('Assessment attachment hash mismatch')
                json.loads(content)
                pinned.append({'path':child.resolve(),'raw':content})
            case['assessment']={'path':path,'raw':assessment_raw,'attachments':pinned}
            if path.is_relative_to(output):
                raise ValueError('Output cannot contain an independent input artifact')
        cases.append(case)
    # Suite JSON may share an output parent; the actual frozen artifacts may not.
    if any(output.is_relative_to(p) for p in protected[1:]):
        raise ValueError('Delivery output cannot modify frozen input storage')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.retrieval-suite-',dir=output.parent) as temp:
        stage=Path(temp)/'delivery'; stage.mkdir()
        (stage/'suite-input.json').write_bytes(raw)
        rows, summaries=[],[]
        for case in cases:
            cid=case['id']; result=case['result']; dest=stage/'cases'/cid; dest.mkdir(parents=True)
            files=_copy_frozen(case['cycle'],case['manifest'],dest/'process'/'cycle')
            copied={(case['cycle']/name).resolve():'process/cycle/'+name for name in files}
            trace_links=[_link('cycle/'+name,name) for name in sorted(files)]
            for root,manifest,name in case['external']:
                external=_copy_frozen(root,manifest,dest/'process'/name)
                copied.update({(root/file).resolve():'process/'+name+'/'+file for file in external})
                trace_links += [_link(name+'/'+file,name+'/'+file) for file in sorted(external)]
            (dest/'process'/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>运行过程 / Process</title><style>'+_STYLE+'</style><main><h1>'+escape(cid)+' · 运行过程 / Process</h1><p>'+_link('../../../index.html','返回验收入口 / Back')+'</p><p>封存的完整过程文件；失败记录也保留。原始 JSON 内的路径为执行时记录，页面链接已相对化。</p><ul>'+''.join('<li>'+link+'</li>' for link in trace_links)+'</ul></main>')
            block_count=characters=None; detail='尚无复核交付 / No review delivery'
            if case['review']:
                root,manifest,ref,packet=case['review']
                render_data_review(root,dest/'review',expected_manifest_sha256=ref['manifest_sha256'],**case['preview'])
                for src,target in (('input.json','input.json'),('result.json','result.json'),('manifest.json','review-manifest.json')):
                    copied.setdefault((root/src).resolve(),'review/'+target)
                blocks=[b for d in packet['source_documents'] for b in d['blocks']]
                block_count=len(blocks); characters=sum(len(b.get('text','')) for b in blocks)
                detail=_link(f'cases/{cid}/review/index.html','查看证据 / Evidence')
            assessment='未附独立评估 / Not supplied'
            assessment_metadata=None
            if case['assessment']:
                assessment_metadata=_assessment_page(case['assessment'],dest,copied)
                assessment=_link(f'cases/{cid}/independent-assessment.html','独立评估；结论见文件 / Independent assessment')
            summary={'case_id':cid,'question':result['question'],'company_ids':result['scope']['company_ids'],
                'status':result['status'],'attempts':len(result['attempts']),'revision_rounds':max(0,len(result['attempts'])-1),
                'delivered_blocks':block_count,'original_characters':characters,'human_acceptance':'not_evaluated',
                'independent_assessment_supplied':case['assessment'] is not None,
                'independent_assessment_files':assessment_metadata,
                'query_executions':[{'attempt':a['attempt'],'execution':a.get('execution','not_recorded')} for a in result['attempts']],
                'external_query_copies':[name for _,_,name in case['external']], 'cycle_manifest_sha256':digest((case['cycle']/'manifest.json').read_bytes())}
            summaries.append(summary)
            reused = any(a.get('execution')=='reused_frozen' for a in result['attempts'])
            origin = '<br><small>含复用的封存 Query / Includes reused query</small>' if reused else ''
            rows.append('<tr><td>'+escape(cid)+'<p>'+escape(result['question'])+'</p><small>'+escape(', '.join(summary['company_ids']))+'</small></td><td>'+escape(_STATUS[result['status']])+'<br><code>'+escape(result['status'])+'</code>'+origin+'</td><td>'+str(summary['revision_rounds'])+'</td><td>'+('—' if block_count is None else str(block_count))+'</td><td>'+('—' if characters is None else str(characters))+'</td><td>'+detail+'<p>'+_link(f'cases/{cid}/process/index.html','运行过程 / Process')+'</p>'+assessment+'</td></tr>')
        text='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Data Agent · 验收入口</title><style>'+_STYLE+'table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:14px;border-bottom:1px solid #dedbd4}td:first-child{max-width:440px}td p{margin:8px 0}code,small{color:#666} .table-scroll{overflow:auto}</style><main><h1>Data Agent · 验收入口 / Acceptance suite</h1><p>模型复核通过不等于 Codex 独立验收，也不等于人工验收。这里只展示显式指定的封存运行，不选择最新结果。</p><p class="muted">修订轮数仅统计本次 cycle 内新增检索轮次；复核重试另见过程。原文字符数统计完整交付块，包含随附限定上下文。</p><div class="table-scroll"><table><thead><tr><th>问题与公司 / Question & company</th><th>运行状态 / Status</th><th>修订 / Revisions</th><th>块 / Blocks</th><th>字符 / Characters</th><th>交付与过程 / Artifacts</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><p>'+_link('suite-input.json','显式输入 / Selected inputs')+' · '+_link('suite-result.json','汇总数据 / Summary')+'</p></main></html>'
        (stage/'index.html').write_text(text)
        result={'schema_version':'data-retrieval-suite-delivery-v1','suite_input_sha256':digest(raw),'cases':summaries,'human_acceptance':'not_evaluated'}
        (stage/'suite-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (stage/'manifest.json').write_text(json.dumps({'files':{str(p.relative_to(stage)):digest(p.read_bytes()) for p in sorted(stage.rglob('*')) if p.is_file()}},indent=2))
        stage.rename(output)
    return result
