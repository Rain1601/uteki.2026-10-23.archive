"""Bound scope, links and static behavior check; not browser visual approval."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from lxml import html
import build


def main():
    data = build.prepare()
    original_read = build.read
    def wrong_scope(path):
        value = original_read(path)
        if path.name == 'display_annotations.json':
            value = copy.deepcopy(value)
            value['binding']['business_map_sha256'] = 'another-candidate'
        return value
    with patch.object(build, 'read', side_effect=wrong_scope):
        try:
            build.prepare()
        except ValueError as error:
            assert str(error) == 'study_annotation_binding_mismatch'
        else:
            raise AssertionError('Wrong candidate annotations were accepted')
    page = build.OUTPUT.read_text()
    actual = json.loads(page.split('const DATA = ', 1)[1].split(';\n(() =>', 1)[0])
    assert actual == data
    links = set(data['links'].values()) | {e['href'] for e in data['evidence']}
    for href in links:
        url = urlsplit(href)
        assert not url.scheme
        target = (build.OUTPUT.parent / unquote(url.path)).resolve()
        assert target.is_relative_to(build.ROOT) and target.is_file(), href
        if url.fragment:
            assert len(html.fromstring(target.read_bytes()).xpath('//*[@id=$id]', id=unquote(url.fragment))) == 1, href
    script = html.fromstring(page).xpath('//script')[0].text
    harness = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');let all=[];
class E{constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.attributes={};this.events={};this.style={setProperty(k,v){this[k]=v}};this.classList={toggle(){}};this._text='';all.push(this)}set textContent(v){this._text=String(v);this.children=[]}get textContent(){return this._text+this.children.map(c=>c.textContent).join('')}append(...n){this.children.push(...n)}replaceChildren(...n){this.children=n;this._text=''}setAttribute(k,v){this.attributes[k]=v}addEventListener(k,v){this.events[k]=v}}
const els={};const tabs=['markets','segments','matrix'].map(view=>{const e=new E('button');e.dataset.view=view;return e});
const document={getElementById:id=>els[id]||(els[id]=new E('div')),createElement:t=>new E(t),querySelectorAll:q=>q==='[data-view]'?tabs:q==='[data-node]'?all.filter(e=>e.dataset.node):[]};vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{document,Map,Set});
assert.equal(els['markets-view'].hidden,false);assert.equal(els['segments-view'].hidden,true);assert.equal(els['matrix-view'].hidden,true);
assert.equal(els['market-cards'].children.length,4);assert.equal(els['segment-cards'].children.length,2);assert.equal(els['matrix-body'].children.length,12);
assert.deepEqual(els['missing-market'].children.map(b=>b.dataset.node),['jetson_embedded','vgpu_software','auto_infotainment']);assert.deepEqual(els['missing-segment'].children.map(b=>b.dataset.node),['nvidia_ai_enterprise']);
const marketButtons=els['market-cards'].children.flatMap(card=>card.children[2].children.slice(1));assert.equal(marketButtons.length,9);assert.equal(marketButtons.filter(b=>b.textContent.includes('待确认')).length,2);
const segmentButtons=els['segment-cards'].children.flatMap(card=>card.children[2].children);assert.equal(segmentButtons.length,11);assert.equal(segmentButtons.filter(b=>b.textContent.includes('待确认')).length,1);
tabs[1].events.click();assert.equal(els['segments-view'].hidden,false);assert.equal(els['markets-view'].hidden,true);tabs[2].events.click();assert.equal(els['matrix-view'].hidden,false);
const cells=els['matrix-body'].children.flatMap(row=>row.children.slice(1).map(td=>td.children[0]));assert.equal(cells.length,48);assert.equal(cells.filter(c=>c.className==='cell empty').length,39);assert.equal(cells.filter(c=>c.className==='cell inferred').length,2);assert.equal(cells.filter(c=>c.className==='cell recorded').length,7);
for(const cell of cells){cell.events.click();assert.equal(els['detail'].children[1].tag,'h2');if(cell.className==='cell empty')assert(els['detail'].textContent.includes('这不代表二者没有关系'));if(cell.className==='cell inferred')assert(els['detail'].textContent.includes('待确认：'));}
const walk=e=>[e,...e.children.flatMap(walk)];for(const id of new Set(all.filter(e=>e.dataset.node).map(e=>e.dataset.node))){all.find(e=>e.dataset.node===id).events.click();assert(els['detail'].textContent.includes('原候选'));}
const ai=all.find(e=>e.dataset.node==='nvidia_ai_enterprise');ai.events.click();assert(els['detail'].textContent.includes('To Watch'));assert.equal(walk(els['detail']).filter(e=>e.tag==='section'&&e.className==='watch').length,2);assert(walk(els['detail']).some(e=>e.tag==='a'&&e.href==='https://www.nvidia.com/en-us/data-center/products/ai-enterprise/'));
all.find(e=>e.dataset.node==='geforce_gpus').events.click();assert(els['detail'].textContent.includes('分组待修正'));assert(els['detail'].textContent.includes('另有游戏主机 SoC 与开发服务'));
assert.equal(els['support-list'].children.length,2);for(const row of els['support-list'].children){const line=row.children[0];assert.equal(line.children[2].dataset.node,'drive_hyperion');assert(['dc_compute','omniverse'].includes(line.children[0].dataset.node));row.children[2].events.click();assert(els['detail'].textContent.includes('→'));}
console.log('Three views, 48 cells, explicit gaps/inferences, source links and one shared product detail passed.');
'''
    with tempfile.TemporaryDirectory(prefix='business-display-check-') as tmp:
        js = Path(tmp) / 'page.js'
        js.write_text(script)
        check = Path(tmp) / 'check.cjs'
        check.write_text(harness)
        subprocess.run(['node', '--check', str(js)], check=True, capture_output=True)
        result = subprocess.run(['node', str(check), str(js)], check=True, capture_output=True, text=True)
        print(result.stdout.strip())
    report = original_read(build.HERE / 'verification.json')
    report.update(checked_local_links=len(links), syntax_check='passed', static_dom_behavior='passed', wrong_candidate_annotation_rejected=True)
    (build.HERE / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'checked_local_links': len(links), 'html_sha256': build.sha(build.OUTPUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
