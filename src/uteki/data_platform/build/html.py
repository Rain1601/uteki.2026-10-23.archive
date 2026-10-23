"""HTML artifacts from frozen bytes, reusing the existing candidate/heading rules."""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urljoin

from uteki.infrastructure.document_sources.sec_index import parse_sec_source

from ..contracts.common import CatalogError, digest
from ..contracts.content import InputManifest, MissingResource, PresentResource
from ..contracts.evidence import HtmlBlock, HtmlCell, HtmlImage, HtmlQuality, HtmlSection, HtmlTable
from .dom import SourceDOM, excluded, normalize, srcset_key, tag, visible_text
from .xbrl import parse_inline

PROCESSOR_VERSION = 'uteki-html-parser-v2'
CANDIDATE_VERSION = 'sec-source-blocks-v0.1.13'


# 以源 DOM 路径生成稳定内容 ID，类型前缀区分块、节、表、单元格等对象。
def item_id(kind, path):
    return kind + '-' + digest(path.encode())[:24]


# 在扩展表格网格前限制 rowspan/colspan，只接受 1..1000 的有限整数。
def spans(dom,cell):
    values=[]
    for attr in ('rowspan','colspan'):
        raw=cell.get(attr,'1')
        if not re.fullmatch(r'[0-9]+',raw) or len(raw)>4 or not 1<=int(raw)<=1000:
            raise CatalogError('PARSE_FAILED','unsupported/invalid table span at '+dom.path(cell))
        values.append(int(raw))
    return values


# 承载一次解析得到的结构化内容及质量信息；冻结容器避免结果字段被重新赋值。
@dataclass(frozen=True)
class ParsedHtml:
    sections: tuple
    blocks: tuple
    tables: tuple
    records: tuple
    images: tuple
    quality: HtmlQuality


# 为候选块遗漏的单个 text/tail 建立精确区间，避免补块时重复复制相邻文本。
def atom_locator(dom, node, *, tail):
    """Range for an otherwise uncovered text atom, without copying its siblings."""
    owner = node.getparent() if tail else node
    raw = visible_text(owner)
    if tail:
        prefix = owner.text or ''
        for sibling in owner:
            prefix += visible_text(sibling)
            if sibling is node:
                break
            prefix += sibling.tail or ''
        start, end = len(prefix), len(prefix) + len(node.tail or '')
    else:
        start, end = 0, len(node.text or '')
    # 同步建立规范化字符到源文本位置的映射，才能把 text/tail 的范围投影回稳定定位区间。
    chars, origins = [], []
    for token in re.finditer(r'\S+', raw):
        if chars:
            chars.append(' '); origins.append(token.start()-1)
        chars.extend(token.group()); origins.extend(range(token.start(),token.end()))
    indices = [i for i,p in enumerate(origins) if start <= p < end and chars[i] != ' ']
    if not indices:
        raise CatalogError('PARSE_FAILED','visible source atom could not be located')
    lower, upper = indices[0], indices[-1]+1
    text = ''.join(chars[lower:upper])
    locator = dom.locator(owner).model_copy(update={'char_start':lower,'char_end':upper,'text_sha256':digest(text.encode())})
    dom.resolve(locator)
    return locator, text


# 从源表格重建占位网格、显式表头、候选表头及脚注关系，保留原始出处和相邻块上下文。
def table_artifact(dom, node, blocks, block_index, table_ids, *, legacy_v1=False):
    path = dom.path(node); table_id = table_ids[path]
    # 只处理最近祖先表格就是当前表的行，嵌套表格有自己的网格与身份。
    rows = [r for r in node.iter('tr') if next(r.iterancestors('table'),None) is node and not excluded(r)]
    occupied, cells, node_cells = {}, [], []
    for row_index, row in enumerate(rows):
        col = 0
        for cell in row:
            if tag(cell) not in {'td','th'} or excluded(cell):
                continue
            while (row_index,col) in occupied:
                col += 1
            rowspan,colspan = spans(dom,cell)
            if row_index+rowspan > len(rows):
                raise CatalogError('PARSE_FAILED','rowspan exceeds source table rows')
            # 合并单元格占据整个矩形范围；先验越界和重叠，再记录占位，避免错列后继续产出。
            coords=[(r,c) for r in range(row_index,row_index+rowspan) for c in range(col,col+colspan)]
            if any(key in occupied for key in coords):
                raise CatalogError('PARSE_FAILED','overlapping source table cells')
            identity = item_id('cell',dom.path(cell))
            occupied.update({key:identity for key in coords})
            footnotes=[];links=[]
            for link in cell.iter('a'):
                if not legacy_v1 and excluded(link):continue
                href=link.get('href','')
                if not href:continue
                entry={'href':href,'link_path':dom.path(link),'status':'external'}
                # 内部脚注仅在锚点唯一时解析；缺失或多义都保留链接状态，不静默丢弃。
                if href.startswith('#'):
                    targets=(dom.by_id if legacy_v1 else dom.by_anchor).get(href[1:],[])
                    entry['status']='missing_target' if not targets else 'ambiguous_target' if len(targets)>1 else 'resolved'
                    if len(targets)==1:
                        footnotes.append(dom.path(targets[0]))
                        entry['target_path']=dom.path(targets[0])
                links.append(entry)
            cells.append(HtmlCell(id=identity,row=row_index,col=col,row_span=rowspan,col_span=colspan,text=dom.text(cell),
                locator=dom.locator(cell),header=tag(cell)=='th',scope=cell.get('scope'),explicit_headers=(),
                header_candidates=(),footnote_paths=tuple(dict.fromkeys(footnotes)),footnote_links=tuple(links)))
            node_cells.append(cell);col+=colspan
    source_ids={n.get('id'):c.id for n,c in zip(node_cells,cells) if n.get('id') and len(dom.by_id[n.get('id')])==1}
    updated=[]
    for source,cell in zip(node_cells,cells):
        references=source.get('headers','').split()
        if any(ref not in source_ids for ref in references):
            raise CatalogError('PARSE_FAILED','table headers attribute references unknown/ambiguous cell')
        # headers 属性是显式关联；位置/文字规则只生成候选表头，不能冒充已确认语义。
        candidates=tuple(c.id for c in cells if c.id!=cell.id and c.text and
            (((c.header or re.search('[A-Za-z]',c.text) or re.fullmatch(r'[12][0-9]{3}',c.text))
              and c.row<cell.row and c.col<cell.col+cell.col_span and cell.col<c.col+c.col_span)
             or (c.row==cell.row and c.col<cell.col and c.col==0)))
        updated.append(cell.model_copy(update={'explicit_headers':tuple(source_ids[ref] for ref in references),'header_candidates':candidates}))
    index=block_index[path]
    # Adjacent original blocks are evidence context, not inferred fiscal units.
    before=[b.id for b in blocks[:index] if b.kind!='table'][-2:]
    after=[b.id for b in blocks[index+1:] if b.kind!='table'][:2]
    captions=[c for c in node if tag(c)=='caption' and not excluded(c)]
    return HtmlTable(id=table_id,block_id=blocks[index].id,locator=dom.locator(node),row_count=len(rows),
        column_count=max((c for _,c in occupied),default=-1)+1,cells=tuple(updated),
        caption=' '.join(dom.text(c) for c in captions) if captions else None,
        context_block_ids=tuple(before+after),nested_table_ids=tuple(table_ids[dom.path(n)] for n in node.iterdescendants('table') if dom.path(n) in table_ids))


# 验证冻结输入后生成正文、章节、表格、数值事实及图片清单，显式记录排除项与处理缺口。
def parse_html(raw: bytes, inputs: InputManifest, *, encoding: str, form_type: str, legacy_v1=False):
    inputs=InputManifest.model_validate(inputs)
    if digest(raw)!=inputs.main.sha256 or len(raw)!=inputs.main.byte_length:
        raise CatalogError('PARSE_FAILED','HTML bytes differ from frozen input')
    if not isinstance(form_type,str) or not form_type.strip():
        raise CatalogError('INVALID_ARGUMENT','explicit material form required')
    dom=SourceDOM(raw,encoding=encoding)
    # Bound invalid spans before the legacy candidate parser expands its table
    # grids; the typed output contract already has this same 1..1000 bound.
    for node in dom.nodes:
        if tag(node) in {'td','th'} and not excluded(node):spans(dom,node)
    try:
        old=parse_sec_source('frozen-html',inputs.main_source_url or '',raw,source_snapshot_id='frozen-html',
                             form_type=form_type,parser_version=CANDIDATE_VERSION)
    except (ValueError,TypeError,OverflowError) as error:
        raise CatalogError('PARSE_FAILED','source candidate parsing failed') from error
    candidates={b.dom_path:b for b in old.blocks}
    selected={p for p,b in candidates.items() if p in dom.paths and not excluded(dom.paths[p]) and b.type!='image'
              and (dom.text(dom.paths[p]) or tag(dom.paths[p])=='table')}
    table_nodes=[n for n in dom.nodes if tag(n)=='table' and not excluded(n)]
    # 可见源表格全部纳入，避免旧候选规则未选中某张表而导致结构遗漏。
    selected.update(dom.path(n) for n in table_nodes)
    table_ids={dom.path(n):item_id('table',dom.path(n)) for n in table_nodes}
    positions={dom.path(n):i for i,n in enumerate(dom.nodes) if tag(n)}
    entries=[]
    for path in selected:
        node=dom.paths[path];old_block=candidates.get(path);text=dom.text(node)
        kind='table' if tag(node)=='table' else 'heading' if re.fullmatch('h[1-6]',tag(node)) or old_block and old_block.type=='heading_candidate' else 'list_item' if old_block and old_block.type=='list_item' else 'paragraph' if old_block and old_block.type=='paragraph' else 'other'
        entries.append((positions[path],0,HtmlBlock(id=item_id('block',path),kind=kind,text=text,locator=dom.locator(node),section_id=None,
            dependency_ids=(),table_id=table_ids.get(path),layout_role=old_block.layout_role if old_block else None)))
    # 逐个审计源 text/tail：排除项留原因，未被候选块覆盖的可见文本补成精确小块。
    exclusions=[];total_atoms=visible_atoms=covered_atoms=0
    # Check every non-whitespace source text/tail, including outside legacy candidates.
    for node in dom.nodes:
        for tail,value in ((False,node.text),(True,node.tail)):
            if not value or not normalize(value):
                continue
            owner=node.getparent() if tail else node
            if owner is None or not tag(owner):
                continue
            total_atoms+=1;path=dom.path(node)+('/tail' if tail else '/text')
            reason=excluded(owner) if tail else excluded(node)
            if not tag(node) and not tail:
                reason='comment_or_processing_instruction'
            if reason:
                exclusions.append({'kind':'text_atom','path':path,'reason':reason});continue
            visible_atoms+=1
            parents=(owner,*owner.iterancestors())
            if any(dom.path(p) in selected for p in parents):
                covered_atoms+=1;continue
            locator,text=atom_locator(dom,node,tail=tail)
            entries.append((positions[dom.path(owner)],1 if not tail else 2,HtmlBlock(id=item_id('block',path),kind='other',text=text,
                locator=locator,section_id=None,dependency_ids=(),table_id=None,layout_role='unwrapped_text')))
            covered_atoms+=1
    entries.sort(key=lambda entry:(entry[0],entry[1],entry[2].id))
    # 真实 h1..h6 用层级栈建父子关系；样式推断标题只标 inferred_style，不虚构标题等级。
    sections=[];blocks=[];stack=[];current=None
    for _,_,block in entries:
        node=dom.paths[block.locator.dom_path]
        if block.kind=='heading' and block.text:
            actual=re.fullmatch('h([1-6])',tag(node))
            if actual:
                level=int(actual.group(1))
                while stack and stack[-1][0]>=level:stack.pop()
                parent=stack[-1][1] if stack else None
            else:
                level=None;parent=None
            current=item_id('section',block.locator.dom_path)
            sections.append(HtmlSection(id=current,title=block.text,parent_id=parent,block_id=block.id,
                basis='heading_element' if actual else 'inferred_style'))
            if actual:stack.append((level,current))
        blocks.append(block.model_copy(update={'section_id':current}))
    block_index={b.locator.dom_path:i for i,b in enumerate(blocks) if b.kind=='table'}
    tables=tuple(table_artifact(dom,n,blocks,block_index,table_ids,legacy_v1=legacy_v1) for n in table_nodes)
    records=parse_inline(dom,legacy_v1=legacy_v1)
    resources={r.source_url:r for r in inputs.resources if r.source_url is not None}
    images=[];issues=[]
    for table in tables:
        for cell in table.cells:
            for link in cell.footnote_links:
                if not legacy_v1 and link['status'] in {'missing_target','ambiguous_target'}:
                    issues.append('unresolved_table_link:'+link['link_path']+':'+link['status'])
    for node in dom.nodes:
        if tag(node)!='img':continue
        path=dom.path(node);src=node.get('src');url=urljoin(inputs.main_source_url or '',src) if src else None
        resource=resources.get(url);reason=excluded(node)
        if not src:reason=reason or 'image_without_src'
        # 可见图片必须在冻结输入中明确 present 或 missing；未登记的依赖使输入不完整。
        if reason is None and resource is None:
            raise CatalogError('INPUT_INCOMPLETE','visible image is neither present nor declared missing: '+path)
        status='excluded' if reason else 'present' if isinstance(resource,PresentResource) else 'missing'
        if status=='missing':reason=resource.reason if resource is not None else 'resource_not_registered'
        if status=='missing':issues.append('image_missing:'+path+':'+reason)
        if node.get('srcset') and (legacy_v1 or not excluded(node)):
            if not legacy_v1 and not any(isinstance(r,MissingResource) and r.resource_key==srcset_key(path) for r in inputs.resources):
                raise CatalogError('INPUT_INCOMPLETE','unsupported srcset must be explicitly declared missing: '+path)
            issues.append('unsupported_srcset:'+path)
        images.append(HtmlImage(id=item_id('image',path),dom_path=path,source_url=url,
            resource_key=resource.resource_key if resource else None,alt=node.get('alt',''),status=status,reason=reason))
    for node in dom.nodes:
        name=tag(node)
        if name=='table' and excluded(node):exclusions.append({'kind':'table','path':dom.path(node),'reason':excluded(node)})
        if name in {'td','th'} and excluded(node):
            exclusions.append({'kind':'table_cell','path':dom.path(node),'reason':excluded(node)})
        if name.split(':')[-1]=='fraction':
            exclusions.append({'kind':'inline_fraction','path':dom.path(node),'reason':'unsupported_inline_fraction'})
            issues.append('unsupported_inline_fraction:'+dom.path(node))
    for record in records:
        if record.status in {'unsupported','invalid'}:issues.append(record.status+':'+record.id+':'+ ';'.join(record.issues))
    if not blocks:raise CatalogError('PARSE_FAILED','no supported visible content')
    # HTML 解析器修复、未解脚注及不支持事实均进入质量问题，保留 partial 与能力降级的依据。
    if dom.diagnostics:issues.extend('html_recovery:'+code for code in dom.diagnostics)
    counts=dict(source_text_atoms=total_atoms,visible_text_atoms=visible_atoms,covered_text_atoms=covered_atoms,
        excluded_text_atoms=sum(e['kind']=='text_atom' for e in exclusions),source_tables=sum(tag(n)=='table' for n in dom.nodes),
        tables=len(tables),excluded_tables=sum(e['kind']=='table' for e in exclusions),table_cells=sum(len(t.cells) for t in tables),
        source_table_cells=sum(tag(n) in {'td','th'} for n in dom.nodes),
        excluded_table_cells=sum(e['kind']=='table_cell' for e in exclusions),
        source_images=len(images),images_present=sum(i.status=='present' for i in images),
        images_missing=sum(i.status=='missing' for i in images),images_excluded=sum(i.status=='excluded' for i in images),
        source_inline_facts=sum(tag(n).split(':')[-1]=='nonfraction' for n in dom.nodes),inline_facts=len(records),
        facts_parsed=sum(r.status=='parsed' for r in records),facts_nil=sum(r.status=='nil' for r in records),
        facts_unsupported=sum(r.status=='unsupported' for r in records),facts_invalid=sum(r.status=='invalid' for r in records),
        blocks=len(blocks),sections=len(sections),unexplained_omissions=visible_atoms-covered_atoms)
    quality=HtmlQuality(schema_version='uteki-html-quality-v1',issues=tuple(issues),counts=counts,exclusions=tuple(exclusions),
        coverage='partial' if issues else 'complete')
    return ParsedHtml(tuple(sections),tuple(blocks),tables,records,tuple(images),quality)
