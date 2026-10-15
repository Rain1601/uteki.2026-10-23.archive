import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Header,Sidebar,DataTable,PDFPreview} from './editorial-primitives.mjs';
import {themes,themeCSS,componentCSS,number,orderedRows} from './tokens.mjs';
import {reportModel} from './report-model.mjs';
const layout=JSON.parse(readFileSync(new URL('./pdf-layout.json',import.meta.url)));
const columns=[{key:'label',label:'Entity',interactive:true},{key:'value',label:'Amount',numeric:true,sortable:true}];
const rows=[{key:'z',label:'Zero',value:0},{key:'n',label:'Negative',value:-3.4},{key:'m',label:'Missing',value:null}];
const table=extra=>DataTable({rows,columns,rowKey:'key',caption:'Independent synthetic records',sortKey:'value',...extra});

test('table works with arbitrary row and label keys; selection preserves signed, zero and missing values',()=>{
 const html=table({selected:'n'});assert.match(html,/data-record="n"/);assert.match(html,/<tr class="selected">/);assert.match(html,/>0<\/td>/);assert.match(html,/>-3<\/td>/);assert.match(html,/>—<\/td>/);assert.deepEqual(rows.map(r=>r.value),[0,-3.4,null]);
});
test('unknown sort columns and duplicate or absent identities fail explicitly',()=>{
 assert.throws(()=>table({sortKey:'other'}));assert.throws(()=>table({rows:[rows[0],rows[0]]}));assert.throws(()=>table({rowKey:'id'}));assert.throws(()=>table({columns:[columns[0],columns[0]]}));
});
test('rendered data is escaped in both table variants',()=>{
 for(const variant of ['ruled','grid']){const html=table({variant,rows:[{key:'x"',label:'<img src=x onerror=alert(1)>',value:0}]});assert.ok(!html.includes('<img'));assert.match(html,/&lt;img/);assert.match(html,/data-record="x&quot;"/)}
});
test('null remains last in both directions without mutating caller rows',()=>{
 assert.deepEqual(orderedRows(rows,'value','asc').map(r=>r.key),['n','z','m']);assert.deepEqual(orderedRows(rows,'value','desc').map(r=>r.key),['z','n','m']);assert.deepEqual(rows.map(r=>r.key),['z','n','m']);assert.equal(number(0),'0');assert.equal(number(null),'—');assert.throws(()=>number(NaN));
});
test('custom palettes require complete semantic roles and safe color values',()=>{
 for(const name of Object.keys(themes)){assert.ok(themeCSS(name));assert.match(table({selected:'n'}),/<tr class="selected">/)}
 assert.ok(themeCSS({...themes.paper,accent:'#123456'}));assert.throws(()=>themeCSS({...themes.paper,accent:'red;display:none'}));assert.throws(()=>themeCSS({ink:'#123456'}));assert.throws(()=>themeCSS('unknown'));
});
test('dimensions are bounded and unknown customization keys fail',()=>{
 assert.match(componentCSS({sidebarWidth:240,tableText:15}),/--sidebar-width:240px/);assert.throws(()=>componentCSS({tableText:'14px'}));assert.throws(()=>componentCSS({tableLeading:0.2}));assert.throws(()=>componentCSS({other:4}));
});
test('navigation rejects active identities outside its input and unsafe links',()=>{
 assert.throws(()=>Sidebar({entries:[{id:'one',label:'One'}],label:'Contents',currentId:'two'}));const sidebar=Sidebar({entries:[{id:'one',label:'One'}],label:'Contents',currentId:'one'});assert.match(sidebar,/aria-current="location"/);assert.ok(!sidebar.includes('class="component-sidebar workspace"'));assert.throws(()=>Header({brand:'Study',brandHref:'javascript:alert(1)',links:[],label:'Nav'}));
});
test('PDF preview uses explicit shared content and rejects unsupported scope',()=>{
 const html=PDFPreview({model:reportModel,layout,locale:'en-US'});assert.match(html,/Observation B/);assert.match(html,/>0<\/td>/);assert.match(html,/>Missing<\/td>/);assert.match(html,/612\/792/);assert.match(html,/v0.2/);assert.throws(()=>PDFPreview({model:reportModel,layout:{...layout,limits:{...layout.limits,language:'zh'}}}));
});
