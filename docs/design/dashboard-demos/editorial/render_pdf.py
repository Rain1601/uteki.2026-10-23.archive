"""Bounded English two-page specimen; not a production document exporter."""
import json
import sys
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle

root = Path(__file__).resolve().parent
source = json.loads(Path(sys.argv[1]).read_text())
model, theme = source['model'], source['theme']
font_dir = Path(sys.argv[2])
for name, filename in [('EditorialSans','LiberationSans-Regular.ttf'),('EditorialSansBold','LiberationSans-Bold.ttf'),('EditorialSerif','LiberationSerif-Regular.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
out = root / 'output/pdf/editorial-specimen-v0.1.pdf'
out.parent.mkdir(parents=True, exist_ok=True)
c = canvas.Canvas(str(out), pagesize=A4)
c.setTitle('Uteki Editorial - Design specimen v0.1')
w, h = A4
margin = 72
def ink(role='ink'):
    c.setFillColor(HexColor(theme[role]))
def footer(page):
    ink('muted')
    c.setFont('EditorialSans', 8)
    c.drawString(margin, 42, 'UTEKI EDITORIAL / DESIGN SPECIMEN / v0.1')
    c.drawRightString(w-margin, 42, str(page).zfill(2))
def para(text, y, size=12, font='EditorialSerif'):
    style = ParagraphStyle('prose', fontName=font, fontSize=size, leading=size*1.55, textColor=HexColor(theme['ink']))
    p = Paragraph(text, style)
    _, ph = p.wrap(w-2*margin, h)
    p.drawOn(c, margin, y-ph)
    return y-ph

ink('accentSoft'); c.rect(0, 0, w, h, fill=1, stroke=0)
ink(); c.setFont('EditorialSansBold', 16); c.drawString(margin, h-100, 'UTEKI / RESEARCH EDITIONS')
y = h-215
c.setFont('EditorialSerif', 35)
for line in model['title'].split('\n'):
    c.drawString(margin, y, line); y -= 46
c.setStrokeColor(HexColor(theme['ink'])); c.setLineWidth(.5); c.line(margin, y-12, w-margin, y-12)
ink(); c.setFont('EditorialSansBold', 10)
c.drawString(margin, y-95, 'PUBLISHED'); c.drawString(w/2+20, y-95, 'TYPE')
c.setFont('EditorialSerif', 12)
c.drawString(margin, y-117, model['date']); c.drawString(w/2+20, y-117, model['kind'])
para('A fictional layout specimen for typography, semantic color tokens and paged research content. The palette comes from the same versioned theme module as the web components.', 185, 11)
footer(1); c.showPage()
ink('canvas'); c.rect(0,0,w,h,fill=1,stroke=0)
ink(); c.setFont('EditorialSansBold', 25); c.drawString(margin,h-100,'Research summary')
y = para(model['summary'], h-135)
y = para(model['note'], y-24)
data=[['Item','Sample value']]+[[r['label'],'Missing' if r['value'] is None else f"{r['value']:,}"] for r in model['rows']]
t=Table(data,colWidths=[w-2*margin-130,130],rowHeights=[30]*len(data))
t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,0),'EditorialSansBold'),('FONTNAME',(0,1),(-1,-1),'EditorialSans'),('FONTSIZE',(0,0),(-1,-1),11),('TEXTCOLOR',(0,0),(-1,-1),HexColor(theme['ink'])),('ALIGN',(1,0),(1,-1),'RIGHT'),('LINEBELOW',(0,0),(-1,-1),.4,HexColor(theme['line'])),('BACKGROUND',(0,0),(-1,0),HexColor(theme['surface'])),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
tw,th=t.wrap(w-2*margin,h); t.drawOn(c,margin,y-40-th)
y=para('Table 01. Fixed simulated observations. Zero and missing are distinct. The PDF embeds Liberation Sans and Serif; it preserves type roles, not exact browser fonts. This English-only two-page renderer has not been validated for arbitrary reports or Chinese fonts.', y-th-65, 10, 'EditorialSans')
footer(2); c.save(); print(out)
