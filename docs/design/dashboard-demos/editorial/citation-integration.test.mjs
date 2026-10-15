import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DataTable} from './editorial-primitives.mjs';
import {RESEARCH_CITATION_SOURCES,AGENT_CITATION_SOURCES} from './citation-sources.mjs';
import {validateCitationSources} from './citation-components.mjs';
test('table slots preserve row identity without injecting untrusted markup',()=>{
 const html=DataTable({rows:[{id:'row"<x>',ref:'<img onerror=bad>'}],columns:[{key:'ref',label:'Source',slot:true}],rowKey:'id',caption:'Independent sample'});
 assert.match(html,/data-cell-slot="ref" data-row-id="row&quot;&lt;x&gt;"/);
 assert.ok(!html.includes('<img'));assert.match(html,/&lt;img onerror=bad&gt;/);
 assert.throws(()=>DataTable({rows:[],columns:[{key:'ref',label:'Source',slot:true,numeric:true}],rowKey:'id',caption:'sample'}));
});
test('every supplied excerpt is present verbatim in its explicit local original',()=>{
 const sources=validateCitationSources([...Object.values(RESEARCH_CITATION_SOURCES),...AGENT_CITATION_SOURCES]);
 for(const source of sources){const original=readFileSync(new URL(source.href,import.meta.url),'utf8');assert.ok(original.includes(source.text),source.id);assert.ok(source.locator);}
 assert.equal(new Set(Object.keys(RESEARCH_CITATION_SOURCES)).size,6);
});
