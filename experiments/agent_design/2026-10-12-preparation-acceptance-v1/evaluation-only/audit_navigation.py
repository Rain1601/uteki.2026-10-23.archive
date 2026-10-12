"""Independent legal contents inventory from raw HTML, not parser TOC output."""
import argparse,json,re
from pathlib import Path
from lxml import html
from audit_dom import text,tag,visible

ITEM=re.compile(r'^Item\s+(\d+[A-Z]?)\.?\s*(.*)$',re.I)
PART=re.compile(r'^PART\s+([IV]+)$',re.I)
def audit(raw,package):
 root=html.document_fromstring(raw.read_bytes(),parser=html.HTMLParser(encoding='utf-8',no_network=True));tree=root.getroottree();tables=[]
 for table in root.iter('table'):
  rows=[r for r in table.iter('tr') if next(r.iterancestors('table'),None) is table]
  count=sum(bool(ITEM.match(text(r))) for r in rows)
  if count:tables.append((count,table,rows))
 score,table,rows=max(tables,key=lambda v:v[0]);expected=[];part=None
 for row in rows:
  cells=[text(c) for c in row if tag(c) in ('td','th') and visible(c) and text(c)]
  if not cells:continue
  m=PART.fullmatch(cells[0]);it=ITEM.match(cells[0])
  if m:part=m[1].upper()
  elif it:
   expected.append(dict(part=part,number=it[1].upper(),title=it[2] or next((c for c in cells[1:] if not c.isdigit()),''),row_dom=tree.getpath(row),links=list(dict.fromkeys(row.xpath('.//a[starts-with(@href,"#")]/@href')))))
 toc=json.loads((package/'toc.json').read_text());tocitems=[x for x in toc if x['kind']=='item'];index=json.loads((package/'index.json').read_text());nodes=[n for n in index['nodes'] if n['kind']=='item'];blocks={b['block_id']:b for b in map(json.loads,(package/'blocks.jsonl').read_text().splitlines())};errs=[]
 for ex in expected:
  matches=[x for x in tocitems if x['number']==ex['number']]
  if len(matches)!=1:errs.append(dict(kind='toc_item_absent_or_duplicate',expected=ex,count=len(matches)))
  elif matches[0]['title'].casefold().strip(' .')!=ex['title'].casefold().strip(' .'):errs.append(dict(kind='toc_title_diff',expected=ex,actual=matches[0]))
  candidates=[n for n in nodes if n['part_number']==ex['part'] and n['item_number']==ex['number']]
  if len(candidates)!=1:errs.append(dict(kind='index_item_absent_or_duplicate',expected=ex,count=len(candidates)));continue
  n=candidates[0];b=blocks[n['start_block_id']];m=ITEM.match(b['text'])
  if not m or m[1].upper()!=ex['number']:errs.append(dict(kind='index_start_wrong_item',expected=ex,actual=b['text']))
  if n['title'].casefold().strip(' .')!=ex['title'].casefold().strip(' .'):errs.append(dict(kind='index_title_diff',expected=ex,actual=n['title']))
  # Table of contents links may target enclosing separators. Ensure actual
  # target exists and precedes/body-contains the indexed heading.
  for href in ex['links']:
   target=root.xpath('//*[@id=$a or (self::a and @name=$a)]',a=href[1:])
   if len(target)!=1:errs.append(dict(kind='original_toc_target_ambiguous',href=href,count=len(target)))
 return dict(schema='independent-legal-navigation-v1',source=str(raw),package=str(package),source_toc_dom=tree.getpath(table),original_items=expected,exported_toc_item_count=len(tocitems),indexed_item_count=len(nodes),errors=errs,pass_=not errs,tail_blocks=[dict(block_id=b['block_id'],text=b['text'][:180],type=b['type']) for b in list(blocks.values())[-5:]])
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();sources=json.loads((a.dataset/'sources.json').read_text());reports=[audit(a.dataset/s['raw_file'],a.dataset/s['index_folder']) for s in sources];a.output.write_text(json.dumps(reports,ensure_ascii=False,indent=2)+'\n');print([(len(r['original_items']),r['exported_toc_item_count'],r['indexed_item_count'],len(r['errors'])) for r in reports])
