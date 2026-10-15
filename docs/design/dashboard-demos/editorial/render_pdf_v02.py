"""Versioned, bounded two-page specimen using pdf-layout.json and shared input."""
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
parser.add_argument('--layout', type=Path, default=ROOT / 'pdf-layout.json')
parser.add_argument('--output', type=Path, default=ROOT / 'output/pdf/editorial-specimen-v0.2.pdf')
args = parser.parse_args()
layout = json.loads(args.layout.read_text())
labels = layout['specimenLabels']
source = json.loads(args.input.read_text())
model, theme = source['model'], source['theme']
if layout['limits']['language'] != 'en' or layout['limits']['pages'] != 2:
    raise ValueError('This renderer supports the explicit English two-page specimen only')
for row in model['rows']:
    if row['value'] is not None and (not isinstance(row['value'], (float, int)) or isinstance(row['value'], bool) or not math.isfinite(row['value'])):
        raise ValueError('PDF numeric values must be finite numbers or explicit null')
for role in ['ink', 'muted', 'line', 'canvas', 'accentSoft']:
    HexColor(theme[role])
for role, filename in layout['fontFiles'].items():
    pdfmetrics.registerFont(TTFont(role, str(args.font_dir / filename)))
for value in [model['title'], model['date'], model['kind'], model['summary'], model['note'], *labels.values(), *[r['label'] for r in model['rows']]]:
    if not isinstance(value, str) or any(ord(char) not in pdfmetrics.getFont('serif').face.charToGlyph for char in value if char not in '\n\r\t'):
        raise ValueError('Text contains unsupported glyphs; supply a supported font and renderer instead')
w, h = layout['page']['width'], layout['page']['height']
m, spacing = layout['margins'], layout['spacing']
args.output.parent.mkdir(parents=True, exist_ok=True)
c = canvas.Canvas(str(args.output), pagesize=(w, h))
c.setTitle(labels['documentTitle'])

def paragraph(text, top, role='body', cover=False):
    spec = layout['type'][role]
    left = m['coverLeft'] if cover else m['bodyLeft']
    right = m['coverRight'] if cover else m['bodyRight']
    style = ParagraphStyle(role, fontName=spec['font'], fontSize=spec['size'], leading=spec['leading'], textColor=HexColor(theme['ink']))
    p = Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
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
    c.setFillColor(HexColor(theme['ink'])); c.setFont(layout['type']['metadataLabel']['font'], layout['type']['metadataLabel']['size'])
    c.drawString(x, h-meta_top, label)
    c.setFont(layout['type']['metadata']['font'],layout['type']['metadata']['size']); c.drawString(x,h-meta_top-layout['cover']['metadataValueGap'],value)
paragraph(labels['coverNote'], layout['cover']['noteTop'], 'caption', True)
footer(1); c.showPage()
background('canvas')
top = paragraph(labels['summaryHeading'],m['bodyTop'],'section') + spacing['headingAfter']
top = paragraph(model['summary'],top) + spacing['paragraphAfter']
top = paragraph(model['note'],top) + spacing['sectionBefore']
top = paragraph(labels['observationsHeading'],top,'section') + spacing['headingAfter']
spec, table_spec = layout['type']['table'],layout['table']
style = ParagraphStyle('cell',fontName=spec['font'],fontSize=spec['size'],leading=spec['leading'],textColor=HexColor(theme['ink']))
data = [[labels['tableItem'],labels['tableValue']]] + [[Paragraph(escape(str(r['label'])),style), table_spec['missingLabel'] if r['value'] is None else f"{r['value']:,}"] for r in model['rows']]
width = w-m['bodyLeft']-m['bodyRight']
t=Table(data,colWidths=[width-table_spec['numericWidth'],table_spec['numericWidth']],minRowHeights=[table_spec['rowMinimum']]*len(data))
t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,0),table_spec['headerFont']),('FONTNAME',(0,1),(-1,-1),spec['font']),('FONTSIZE',(0,0),(-1,-1),spec['size']),('TEXTCOLOR',(0,0),(-1,-1),HexColor(theme['ink'])),('ALIGN',(1,0),(1,-1),'RIGHT'),('LINEBELOW',(0,0),(-1,-1),table_spec['lineWidth'],HexColor(theme['line'])),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),table_spec['cellInset']),('RIGHTPADDING',(0,0),(-1,-1),table_spec['cellInset']),('TOPPADDING',(0,0),(-1,-1),table_spec['verticalInset']),('BOTTOMPADDING',(0,0),(-1,-1),table_spec['verticalInset'])]))
_,th=t.wrap(width,h)
if top+th > h-m['bodyBottom']: raise ValueError('Table exceeds bounded page')
t.drawOn(c,m['bodyLeft'],h-top-th)
paragraph(labels['tableCaption'],top+th+spacing['captionBefore'],'caption')
footer(2); c.save()
print(args.output)
