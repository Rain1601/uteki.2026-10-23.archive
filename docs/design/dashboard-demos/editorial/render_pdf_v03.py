"""Shared bilingual bounded renderer. Requires explicit language, content and theme."""
import argparse
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
parser.add_argument('font_dir', type=Path)
parser.add_argument('--layout', type=Path, default=ROOT / 'pdf-layout-v03.json')
parser.add_argument('--output', type=Path, default=ROOT / 'output/pdf/editorial-specimen-v0.3.pdf')
args = parser.parse_args()
layout = json.loads(args.layout.read_text())

source = json.loads(args.input.read_text())
model, theme = source['model'], source['theme']
language = source['language']
if language not in layout['languages'] or layout['limits']['pages'] != 2:
    raise ValueError('Explicit supported language and two-page layout required')
profile = layout['languages'][language]
labels = profile['labels']
layout['fontFiles'] = profile['fonts']
layout['table']['missingLabel'] = profile['missingLabel']
for row in model['rows']:
    if row['value'] is not None and (not isinstance(row['value'], (float, int)) or isinstance(row['value'], bool) or not math.isfinite(row['value'])):
        raise ValueError('PDF numeric values must be finite numbers or explicit null')
for role in ['ink', 'muted', 'line', 'canvas', 'accentSoft']:
    HexColor(theme[role])
for role, filename in layout['fontFiles'].items():
    pdfmetrics.registerFont(TTFont(role, str(args.font_dir / filename)))
def validate_text(text, font):
    if not isinstance(text, str) or any(ord(char) not in pdfmetrics.getFont(font).face.charToGlyph for char in text if char not in '\n\r\t'):
        raise ValueError('Text contains unsupported glyphs in actual role font')

w, h = layout['page']['width'], layout['page']['height']
m, spacing = layout['margins'], layout['spacing']
args.output.parent.mkdir(parents=True, exist_ok=True)
temporary = args.output.with_suffix('.pending.pdf')
c = canvas.Canvas(str(temporary), pagesize=(w, h))
c.setTitle(labels['documentTitle'])

def make_paragraph(text, style, width):
    validate_text(text,style.fontName)
    if profile['wordWrap'] != 'CJK':
        return Paragraph(escape(text).replace('\n','<br/>'),style)
    # Measure actual embedded glyphs, then backtrack to a legal line boundary.
    # No hanging punctuation, clipping, shrinking or platform fallback.
    start_forbidden=set(profile['cannotStart'])
    end_forbidden=set(profile['cannotEnd'])
    lines=[]
    for segment in text.split('\n'):
        remaining=segment
        while remaining:
            used=0;count=0
            for char in remaining:
                advance=pdfmetrics.stringWidth(char,style.fontName,style.fontSize)
                if used+advance>width-0.01: break
                used+=advance;count+=1
            if count==0: raise ValueError('Glyph exceeds paragraph width')
            if count<len(remaining):
                # Preserve ASCII words when they fit; very long tokens may wrap.
                import re
                left=re.search(r'[A-Za-z0-9]+$',remaining[:count])
                if left and re.match(r'[A-Za-z0-9]',remaining[count:]) and left.start()>0:
                    count=left.start()
                while count>0 and (remaining[count-1] in end_forbidden or remaining[count] in start_forbidden):
                    count-=1
                if count==0: raise ValueError('No legal CJK line boundary within width')
            lines.append(remaining[:count].rstrip())
            remaining=remaining[count:].lstrip()
        if not segment: lines.append('')
    return Paragraph('<br/>'.join(escape(line) for line in lines),style)

def paragraph(text, top, role='body', cover=False):
    spec = layout['type'][role]
    validate_text(text, spec['font'])
    left = m['coverLeft'] if cover else m['bodyLeft']
    right = m['coverRight'] if cover else m['bodyRight']
    style = ParagraphStyle(role, fontName=spec['font'], fontSize=spec['size'], leading=spec['leading'], textColor=HexColor(theme['ink']), wordWrap=profile['wordWrap'])
    p = make_paragraph(text, style, w-left-right)
    _, height = p.wrap(w-left-right, h)
    bottom = top + height
    if bottom > h-m['bodyBottom']:
        raise ValueError(f'{role} exceeds bounded page: top={top}, bottom={bottom}')
    p.drawOn(c, left, h-bottom)
    return bottom

def footer(page):
    spec, geo = layout['type']['footer'], layout['footer']
    c.setFillColor(HexColor(theme['muted']))
    c.setFont(spec['font'], spec['size'])
    validate_text(labels['footer'], spec['font'])
    if pdfmetrics.stringWidth(labels['footer'],spec['font'],spec['size']) > w-geo['left']-geo['right']-28:
        raise ValueError('Footer collides with page number')
    c.drawString(geo['left'], geo['baseline'], labels['footer'])
    c.drawRightString(w-geo['right'], geo['baseline'], str(page).zfill(geo['pageDigits']))

def background(role):
    c.setFillColor(HexColor(theme[role])); c.rect(0, 0, w, h, fill=1, stroke=0)

background(layout['cover']['backgroundRole'])
paragraph(labels['brand'], layout['cover']['brandTop'], 'brand', True)
bottom = paragraph(model['title'], layout['cover']['titleTop'], 'coverTitle', True)
c.setStrokeColor(HexColor(theme['ink'])); c.setLineWidth(layout['cover']['ruleWidth'])
c.line(m['coverLeft'], h-bottom-layout['cover']['ruleGap'], w-m['coverRight'], h-bottom-layout['cover']['ruleGap'])
meta_top = bottom+layout['cover']['metadataGap']
for label, value, x in [(labels['published'],model['date'],m['coverLeft']), (labels['kind'],model['kind'],w/2)]:
    for text, role, offset in [(label,'metadataLabel',0),(value,'metadata',layout['cover']['metadataValueGap'])]:
        spec=layout['type'][role]; validate_text(text,spec['font'])
        width=(w/2-m['coverLeft']-16) if x==m['coverLeft'] else (w/2-m['coverRight'])
        p=make_paragraph(text,ParagraphStyle(role,fontName=spec['font'],fontSize=spec['size'],leading=spec['leading'],wordWrap=profile['wordWrap']),width)
        _,height=p.wrap(width,h)
        if height>spec['leading'] or meta_top+offset+height>layout['cover']['noteTop']-24:
            raise ValueError('Metadata exceeds bounded cover region')
        p.drawOn(c,x,h-meta_top-offset-height)
paragraph(labels['coverNote'], layout['cover']['noteTop'], 'caption', True)
footer(1); c.showPage()
background('canvas')
top = paragraph(labels['summaryHeading'],m['bodyTop'],'section') + spacing['headingAfter']
top = paragraph(model['summary'],top) + spacing['paragraphAfter']
top = paragraph(model['note'],top) + spacing['sectionBefore']
top = paragraph(labels['observationsHeading'],top,'section') + spacing['headingAfter']
spec, table_spec = layout['type']['table'],layout['table']
style = ParagraphStyle('cell',fontName=spec['font'],fontSize=spec['size'],leading=spec['leading'],textColor=HexColor(theme['ink']), wordWrap=profile['wordWrap'])
for text in [labels['tableItem'],labels['tableValue'],profile['missingLabel'],*[r['label'] for r in model['rows']]]:
    validate_text(text,spec['font'])
for text in [labels['tableItem'],labels['tableValue']]: validate_text(text,table_spec['headerFont'])
numeric_inner=table_spec['numericWidth']-2*table_spec['cellInset']
for row in model['rows']:
    number=profile['missingLabel'] if row['value'] is None else f"{row['value']:,}"
    if pdfmetrics.stringWidth(number,spec['font'],spec['size'])>numeric_inner:
        raise ValueError('Numeric value exceeds explicit column width')
header_style=ParagraphStyle('header',fontName=table_spec['headerFont'],fontSize=spec['size'],leading=spec['leading'],wordWrap=profile['wordWrap'])
right_header=ParagraphStyle('rightHeader',parent=header_style,alignment=2)
data = [[make_paragraph(labels['tableItem'],header_style,w-m['bodyLeft']-m['bodyRight']-table_spec['numericWidth']-2*table_spec['cellInset']),make_paragraph(labels['tableValue'],right_header,numeric_inner)]] + [[make_paragraph(r['label'],style,w-m['bodyLeft']-m['bodyRight']-table_spec['numericWidth']-2*table_spec['cellInset']), table_spec['missingLabel'] if r['value'] is None else f"{r['value']:,}"] for r in model['rows']]
width = w-m['bodyLeft']-m['bodyRight']
t=Table(data,colWidths=[width-table_spec['numericWidth'],table_spec['numericWidth']],minRowHeights=[table_spec['rowMinimum']]*len(data))
t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,0),table_spec['headerFont']),('FONTNAME',(0,1),(-1,-1),spec['font']),('FONTSIZE',(0,0),(-1,-1),spec['size']),('TEXTCOLOR',(0,0),(-1,-1),HexColor(theme['ink'])),('ALIGN',(1,0),(1,-1),'RIGHT'),('LINEBELOW',(0,0),(-1,-1),table_spec['lineWidth'],HexColor(theme['line'])),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),table_spec['cellInset']),('RIGHTPADDING',(0,0),(-1,-1),table_spec['cellInset']),('TOPPADDING',(0,0),(-1,-1),table_spec['verticalInset']),('BOTTOMPADDING',(0,0),(-1,-1),table_spec['verticalInset'])]))
_,th=t.wrap(width,h)
if top+th > h-m['bodyBottom']: raise ValueError('Table exceeds bounded page')
t.drawOn(c,m['bodyLeft'],h-top-th)
paragraph(labels['tableCaption'],top+th+spacing['captionBefore'],'caption')
footer(2); c.save()
temporary.replace(args.output)
print(args.output)
