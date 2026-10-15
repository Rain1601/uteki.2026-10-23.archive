import test from 'node:test';
import assert from 'node:assert/strict';
import {Tooltip,mountTooltips,Accordion,Breadcrumb,Pagination,validatePagination,Loading} from './utility-components.mjs';

const pagination={id:'pages',page:2,count:4,action:'paginate',label:'Result pages',previousLabel:'Previous',nextLabel:'Next',pageLabel:'Page',emptyLabel:'No pages'};
test('pagination rejects contradictory empty/current bounds and unsafe actions',()=>{
  for(const patch of [{page:0},{count:0},{page:5},{count:-1},{count:NaN},{page:1.5},{action:'bad action'},{count:Infinity}]) assert.throws(()=>validatePagination({...pagination,...patch}));
  assert.equal(validatePagination({...pagination,page:0,count:0}).count,0);
  assert.throws(()=>validatePagination({...pagination,page:1,count:0}),/range/);
});
test('pagination retains explicit total and bounded controls for large scopes',()=>{
  const html=Pagination({...pagination,page:500000,count:1000000});
  assert.match(html,/500000 \/ 1000000/);
  assert.ok((html.match(/<button/g)||[]).length<=9);
  assert.match(html,/data-page="500000" aria-current="page"/);
  assert.match(Pagination({...pagination,page:1,count:1}),/data-page="1" disabled/);
  assert.match(Pagination({...pagination,page:0,count:0}),/No pages/);
});
test('disclosures preserve plain content, independent identities and explicit boolean open state',()=>{
  const item={id:'scope',title:'Scope <b>',text:'Original <script> & text',open:true};
  const html=Accordion({id:'notes',label:'Notes',items:[item]});
  assert.match(html,/id="notes-scope" open/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.throws(()=>Accordion({id:'notes',label:'Notes',items:[item,item]}),/Duplicate/);
  assert.throws(()=>Accordion({id:'notes',label:'Notes',items:[{...item,open:'yes'}]}),/boolean/);
  assert.throws(()=>Accordion({id:'notes',label:'Notes',items:[{...item,href:'javascript:alert(1)',linkLabel:'Open'}]}));
});
test('breadcrumbs identify the current final page and validate inherited URL policy',()=>{
  const input={id:'crumbs',label:'Location',currentId:'reader',items:[{id:'list',label:'Library',href:'./workspace.html?view=library'},{id:'reader',label:'Reading'}]};
  assert.match(Breadcrumb(input),/<span aria-current="page">Reading<\/span>/);
  for(const href of ['javascript:alert(1)','./%2e%2e/private','https://user:pass@example.com','//example.com']) assert.throws(()=>Breadcrumb({...input,items:[{...input.items[0],href},input.items[1]]}));
  assert.throws(()=>Breadcrumb({...input,currentId:'list'}),/final/);
  assert.throws(()=>Breadcrumb({...input,items:[{...input.items[0],id:'reader'},input.items[1]]}),/Duplicate/);
});
test('tooltip markup associates help safely without accepting HTML',()=>{
  const html=Tooltip({id:'hint',label:'Help',description:'<script> help'});
  assert.match(html,/aria-describedby="hint"/);assert.match(html,/id="hint"[^>]+role="tooltip" hidden/);assert.match(html,/&lt;script&gt;/);
  assert.throws(()=>Tooltip({id:'unsafe id',label:'Help',description:'help'}),/identity/);
});
test('tooltip focus, Escape dismissal and remount cleanup retain trigger focus',()=>{
  const trigger=new EventTarget(); trigger.getAttribute=()=> 'hint';
  const tip={id:'hint',hidden:true};
  const wrapper=new EventTarget();wrapper.dataset={utilityTooltip:'hint'};wrapper.querySelector=selector=>selector==='button'?trigger:tip;
  const host={querySelectorAll:()=>[wrapper]};
  const ui=mountTooltips(host);
  trigger.dispatchEvent(new Event('focus'));assert.equal(tip.hidden,false);
  const escape=new Event('keydown',{cancelable:true});Object.defineProperty(escape,'key',{value:'Escape'});trigger.dispatchEvent(escape);assert.equal(tip.hidden,true);assert.equal(escape.defaultPrevented,true);
  trigger.dispatchEvent(new Event('blur'));trigger.dispatchEvent(new Event('focus'));assert.equal(tip.hidden,false);
  ui.destroy();assert.equal(tip.hidden,true);trigger.dispatchEvent(new Event('focus'));assert.equal(tip.hidden,true);ui.destroy();
  assert.throws(()=>mountTooltips({querySelectorAll:()=>[wrapper,wrapper]}),/Duplicate/);
});
test('loading retains unknown progress and rejects fabricated invalid percentages',()=>{
  assert.doesNotMatch(Loading({id:'loading',label:'Loading',description:'Waiting for source'}),/<progress/);
  const html=Loading({id:'loading',label:'Loading',description:'Waiting',progress:0,progressLabel:'Download progress'});
  assert.match(html,/role="status"/);assert.match(html,/<progress value="0"/);
  for(const progress of [-1,101,NaN,'50'])assert.throws(()=>Loading({id:'loading',label:'Loading',description:'Waiting',progress,progressLabel:'Progress'}),/range/);
});
