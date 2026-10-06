#!/usr/bin/env python3
"""Build an explicitly scoped, fictional research sample from the web projection.

Local authoring tool, not a production export API. Every business scope argument
is required. No network, source translation, calculation, or inferred values.
"""
import argparse
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

from reportlab import Version as REPORTLAB_VERSION
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, LINE, SOFT = [colors.HexColor(x) for x in ('#15212e', '#607080', '#d8e0e7', '#f2f5f8')]
PAGE_W, PAGE_H = A4
LEFT, RIGHT, TOP, BOTTOM = 48, 48, 46, 46
WIDTH = PAGE_W - LEFT - RIGHT


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('company', 'manager', 'report', 'version', 'language', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--node-bin', default=shutil.which('node'))
    parser.add_argument('--font-directory', default='/System/Library/Fonts/Supplemental')
    args = parser.parse_args()
    if any(not getattr(args, key).strip() for key in ('company', 'manager', 'report', 'version', 'language', 'output')):
        parser.error('scope and output must be non-empty')
    if not args.node_bin:
        parser.error('a Node.js executable is required')
    # This sample typesetter has been reviewed for the original Chinese edition.
    if args.language != 'zh-CN':
        parser.error('this sample typesetter supports zh-CN only; it does not translate editions')
    if Path(args.output).suffix.lower() != '.pdf':
        parser.error('output must be a .pdf file')
    return args


def register_fonts(directory):
    directory = Path(directory)
    fonts = [('Body', 'Songti.ttc', 4), ('BodyBold', 'Songti.ttc', 1),
             ('Latin', 'Times New Roman.ttf', 0), ('LatinBold', 'Times New Roman Bold.ttf', 0),
             ('Meta', 'Arial Unicode.ttf', 0)]
    for name, filename, index in fonts:
        path = directory / filename
        if not path.is_file():
            raise ValueError(f'Required local font is unavailable: {path}')
        pdfmetrics.registerFont(TTFont(name, str(path), subfontIndex=index))


def markup(value, family='body', bold=False):
    value = str(value)
    if family == 'meta':
        return html.escape(value)
    # Serif CJK text uses Songti; Latin names and numerals use Times New Roman.
    pieces = re.split(r'([\x20-\x7e]+)', value)
    return ''.join(f'<font name="{("LatinBold" if bold else "Latin") if all(ord(c)<128 for c in piece) else ("BodyBold" if bold else "Body")}">{html.escape(piece)}</font>' for piece in pieces if piece)


def styles():
    return {
        'brand': ParagraphStyle('brand', fontName='Meta', fontSize=13, leading=19, textColor=INK),
        'label': ParagraphStyle('label', fontName='Meta', fontSize=8.5, leading=13, textColor=MUTED, spaceAfter=5),
        'title': ParagraphStyle('title', fontName='BodyBold', fontSize=23, leading=31, textColor=INK, spaceAfter=10, wordWrap='CJK'),
        'subtitle': ParagraphStyle('subtitle', fontName='Meta', fontSize=9, leading=14, textColor=MUTED, spaceAfter=10, wordWrap='CJK'),
        'verdict': ParagraphStyle('verdict', fontName='BodyBold', fontSize=12, leading=20, textColor=INK, spaceAfter=9, wordWrap='CJK'),
        'summary': ParagraphStyle('summary', fontName='Body', fontSize=10.5, leading=18, textColor=MUTED, spaceAfter=12, wordWrap='CJK'),
        'kicker': ParagraphStyle('kicker', fontName='Meta', fontSize=8.5, leading=13, textColor=MUTED, spaceBefore=16, spaceAfter=4, keepWithNext=True),
        'h2': ParagraphStyle('h2', fontName='BodyBold', fontSize=15, leading=22, textColor=INK, spaceAfter=9, keepWithNext=True, wordWrap='CJK'),
        'body': ParagraphStyle('body', fontName='Body', fontSize=11, leading=19.5, textColor=INK, spaceAfter=9, wordWrap='CJK', allowWidows=0, allowOrphans=0),
        'bullet': ParagraphStyle('bullet', fontName='Body', fontSize=11, leading=19.5, textColor=INK, spaceAfter=5, leftIndent=11, firstLineIndent=-11, wordWrap='CJK'),
        'citation': ParagraphStyle('citation', fontName='Meta', fontSize=8, leading=12, textColor=MUTED, spaceBefore=1, spaceAfter=4, wordWrap='CJK'),
        'toc': ParagraphStyle('toc', fontName='Meta', fontSize=8.6, leading=14, textColor=INK, wordWrap='CJK'),
        'tableHead': ParagraphStyle('tableHead', fontName='Meta', fontSize=8.5, leading=13, textColor=MUTED, wordWrap='CJK'),
        'tableBody': ParagraphStyle('tableBody', fontName='Meta', fontSize=9.5, leading=16, textColor=INK, wordWrap='CJK'),
        'refHead': ParagraphStyle('refHead', fontName='Meta', fontSize=10.5, leading=16, textColor=INK, spaceBefore=15, spaceAfter=8, keepWithNext=True, wordWrap='CJK'),
        'refBody': ParagraphStyle('refBody', fontName='Body', fontSize=10, leading=17, textColor=INK, spaceAfter=7, wordWrap='CJK', allowWidows=0, allowOrphans=0),
        'refMeta': ParagraphStyle('refMeta', fontName='Meta', fontSize=8, leading=13, textColor=MUTED, spaceAfter=5, wordWrap='CJK'),
    }


class ReportDoc(BaseDocTemplate):
    def __init__(self, stream, projection, total_pages=None):
        super().__init__(stream, pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=TOP, bottomMargin=BOTTOM,
                         title=projection['report']['title'], author=projection['manager']['name'],
                         subject='Uteki · 虚构研究样本 · 非实盘', creator='Uteki static report presentation')
        self.projection, self.total_pages, self.section_pages = projection, total_pages, {}
        frame = Frame(LEFT, BOTTOM, WIDTH, PAGE_H - TOP - BOTTOM, id='body', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id='report', frames=[frame], onPage=self.draw_page))

    def draw_page(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(.45)
        canvas.line(LEFT, 35, PAGE_W-RIGHT, 35)
        canvas.setFont('Meta', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(LEFT, 23, f"Uteki · {self.projection['manager']['name']} · {self.projection['report']['version']} · 虚构研究样本")
        canvas.drawRightString(PAGE_W-RIGHT, 23, f"{doc.page} / {self.total_pages}" if self.total_pages else str(doc.page))
        if doc.page > 1:
            canvas.drawString(LEFT, PAGE_H-27, self.projection['document']['title'])
            canvas.drawRightString(PAGE_W-RIGHT, PAGE_H-27, f"资料截止 {self.projection['report']['cutoff']}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if hasattr(flowable, 'outline'):
            key, label = flowable.outline
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(label, key, level=0)
            self.section_pages[key] = self.page


def build_story(p, section_pages=None):
    ss = styles()
    story = []
    paragraph = lambda value, style='body', family='body', bold=False: Paragraph(markup(value, family, bold), ss[style])
    report, document, company, manager = p['report'], p['document'], p['company'], p['manager']
    header = Table([[paragraph('uteki / 研究', 'brand','meta'), paragraph('虚构研究样本 · 非实盘', 'label','meta')]], colWidths=[WIDTH*.55,WIDTH*.45])
    header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story.extend([header, HRFlowable(width='100%',thickness=1.1,color=INK), Spacer(1,14),paragraph(document['title'],'label','meta'),paragraph(report['title'],'title',bold=True),paragraph(report.get('subtitle',''),'subtitle','meta')])
    status = {'current':'当前版本','historical':'历史版本','review':'结论待复核'}.get(report['status'],report['status'])
    meta = Table([[paragraph(f"公司  {company['name']}",'label','meta'),paragraph(f"作者  {manager['name']} · {manager['style']}",'label','meta')],
                  [paragraph(f"版本  {report['version']} · {status}",'label','meta'),paragraph(f"发布  {report['publishedAt']}    截止  {report['cutoff']}",'label','meta')]],colWidths=[WIDTH*.44,WIDTH*.56])
    meta.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.extend([meta,Spacer(1,9),HRFlowable(width='100%',thickness=.6,color=LINE),Spacer(1,10),paragraph('本版判断','label','meta'),paragraph(report['verdict'],'verdict',bold=True),paragraph(report['summary'],'summary')])
    if report.get('reviewNote'):
        story.append(paragraph(report['reviewNote'],'summary'))
    # Compact two-column chapter index. The second build adds actual page numbers.
    toc_cells=[]
    for i,s in enumerate(p['sections']):
        key='section-'+s['id']; page=(section_pages or {}).get(key,'')
        toc_cells.append(Paragraph(f'<link href="#{key}">{i+1:02d}  {html.escape(s["title"])} <font color="#607080">{page}</font></link>',ss['toc']))
    toc_rows=[toc_cells[i:i+2]+([''] if len(toc_cells[i:i+2])==1 else []) for i in range(0,len(toc_cells),2)]
    toc=Table(toc_rows,colWidths=[WIDTH/2,WIDTH/2])
    toc.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),14),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story.extend([paragraph('章节目录','label','meta'),toc,Spacer(1,8),HRFlowable(width='100%',thickness=.6,color=LINE)])
    for section in p['sections']:
        story.append(paragraph(section['kicker'],'kicker','meta'))
        heading=paragraph(section['title'],'h2',bold=True); heading.outline=('section-'+section['id'],section['title']); story.append(heading)
        story.extend(paragraph(item) for item in section['paragraphs'])
        story.extend(paragraph('•  '+item,'bullet') for item in section.get('bullets',[]))
        if section.get('table'):
            table=section['table']; columns=table['columns']
            cell_styles=[]
            for col in columns:
                alignment=TA_RIGHT if col['align']=='right' else TA_LEFT
                cell_styles.append((ParagraphStyle('th-'+str(len(cell_styles)),parent=ss['tableHead'],alignment=alignment),ParagraphStyle('td-'+str(len(cell_styles)),parent=ss['tableBody'],alignment=alignment)))
            values=[[Paragraph(markup(c['label'],'meta'),cell_styles[i][0]) for i,c in enumerate(columns)]]
            values.extend([[Paragraph(markup(value,'meta'),cell_styles[i][1]) for i,value in enumerate(row)] for row in table['rows']])
            tab=Table(values,colWidths=[WIDTH/len(columns)]*len(columns),repeatRows=1,hAlign='LEFT')
            tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),SOFT),('LINEBELOW',(0,0),(-1,-1),.4,LINE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
            story.extend([Spacer(1,5),tab,Spacer(1,11)])
        for c in section['citations']:
            story.append(Paragraph(f'<link href="#reference-{html.escape(c["id"])}">[{c["number"]}] {html.escape(c["sourceTitle"])}</link>',ss['citation']))
    if p['evidence']:
        story.extend([PageBreak(),paragraph('引用与来源','kicker','meta')])
        heading=paragraph('证据附录','h2',bold=True); heading.outline=('evidence-appendix','证据附录');story.append(heading)
        story.append(paragraph('以下为当前版本引用的虚构演示资料，按首次引用排序。同名来源的不同原文位置分别保留。没有外部原始文件可供下载。','summary'))
        availability={'available':'演示正文可读','excerpt':'仅有摘录','unavailable':'资料不可用'}
        for evidence in p['evidence']:
            reference=[]
            heading=paragraph(f"[{evidence['number']}] {evidence['sourceTitle']}",'refHead','meta')
            heading.outline=('reference-'+evidence['id'],evidence['sourceTitle']+' / '+evidence['locator'])
            reference.append(heading)
            for line in [evidence['locator'],f"{evidence['sourceType']} · {availability[evidence['availability']]}",f"发布 {evidence['publishedAt']}    可取得 {evidence['availableAt']}"]:
                reference.append(paragraph(line,'refMeta','meta'))
            if evidence['availability']=='unavailable':
                reference.append(paragraph('原文不可用，不能用材料缺失证明或反驳判断。','refBody'))
            else:
                reference.append(paragraph(evidence['quote'],'refBody'))
                reference.extend(paragraph(x,'refBody') for x in evidence['context'])
            reference.extend([paragraph('使用边界','refMeta','meta'),paragraph(evidence['limitation'],'refBody'),Spacer(1,4),HRFlowable(width='100%',thickness=.4,color=LINE)])
            story.append(KeepTogether(reference))
    return story


def assert_font_coverage(projection):
    # Fail instead of shipping missing glyphs as boxes. Latin is rendered with Times.
    used=json.dumps(projection,ensure_ascii=False)
    for name in ('Body','BodyBold','Meta'):
        missing=sorted({c for c in used if ord(c)>127 and ord(c) not in pdfmetrics.getFont(name).face.charToGlyph})
        if missing:
            raise ValueError(f'Font {name} lacks source glyphs: {missing}')


def main():
    args=parse_args()
    cmd=[args.node_bin,str(ROOT/'scripts/export-report-presentation.mjs')]
    for key in ('company','manager','report','version','language'):
        cmd.extend(['--'+key,getattr(args,key)])
    result=subprocess.run(cmd,check=True,capture_output=True,text=True)
    projection=json.loads(result.stdout)
    register_fonts(args.font_directory); assert_font_coverage(projection)
    # First pass collects chapter locations; the second writes the final artifact.
    scratch=io.BytesIO(); preview=ReportDoc(scratch,projection); preview.build(build_story(projection))
    stream=io.BytesIO(); final=ReportDoc(stream,projection,total_pages=preview.page)
    final.build(build_story(projection,preview.section_pages))
    if final.page != preview.page or final.section_pages != preview.section_pages:
        raise ValueError('Chapter pagination did not stabilize between builds')
    output=Path(args.output).expanduser().resolve();output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(stream.getvalue())
    digest=hashlib.sha256(json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    manifest={'scope':projection['scope'],'fictionalResearch':True,'sourceProjectionSha256':digest,'pdfSha256':hashlib.sha256(stream.getvalue()).hexdigest(),'sections':len(projection['sections']),'references':len(projection['evidence']),'pages':final.page,'chapterPages':final.section_pages,'generator':'ReportLab '+REPORTLAB_VERSION,'fonts':['Songti SC','Times New Roman','Arial Unicode'],'reviewedAs':'Static design sample, not a production export service'}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(output),'pages':final.page,'sections':manifest['sections'],'references':manifest['references']},ensure_ascii=False))


if __name__=='__main__':
    main()
