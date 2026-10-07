const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createPoller,mergeRunView,timedSteps,artifactURL,escape,bootstrap,observedTime,callTimingHTML,configurationSnapshotHTML,updateCallRecords} = require('../apps/review_workbench/static/js/agent_runs.js');

test('recorded timestamps convert across the Beijing date boundary without inventing missing timezones',()=>{
  assert.equal(observedTime('2034-03-02T14:30:00Z').beijing,'2034-03-02 22:30:00 UTC+08:00');
  assert.deepEqual(observedTime('2034-03-02T16:06:05.123456Z'),{beijing:'2034-03-03 00:06:05 UTC+08:00',utc:'2034-03-02T16:06:05.123456Z'});
  assert.equal(observedTime('2034-03-03T00:06:05+08:00').beijing,'2034-03-03 00:06:05 UTC+08:00');
  for(const value of [undefined,null,'','2034-03-02T16:06:05','2034-02-30T16:06:05Z','2034-03-02T24:00:00Z','bad']) assert.equal(observedTime(value),null);
  const view=callTimingHTML({call_id:'first',started_at:'2034-03-02T16:06:05Z'});
  assert.ok(view.includes('2034-03-03 00:06:05 UTC+08:00'));assert.ok(view.includes('Not recorded'));assert.ok(view.includes('Inspect UTC'));
});

test('configuration snapshots distinguish false, zero, explicit null, not sent and not recorded',()=>{
  const view=configurationSnapshotHTML({call_id:'call<script>',configuration_snapshot:{schema_version:'model-call-config-v1',capture_kind:'before_dispatch',sha256:'a'.repeat(64),fields:{seed:{status:'explicit',value:0,source:'request'},stream:{status:'explicit',value:false,source:'request'},tool_choice:{status:'explicit',value:null,source:'request'},temperature:{status:'not_sent',value:null,source:'request absent'},base_url:{status:'recorded',value:'https://example.test',source:'<img src=x>'},api_key:{status:'explicit',value:'must-not-render'}}}});
  assert.ok(view.includes('<td>0</td>'));assert.ok(view.includes('<td>false</td>'));assert.ok(view.includes('<td>null</td>'));
  assert.ok(view.includes('Not sent'));assert.ok(view.includes('Not recorded'));assert.ok(view.includes('effective configuration is unverified'));
  assert.ok(view.includes('a'.repeat(64)));assert.ok(view.includes('&lt;img'));assert.ok(!view.includes('<script>'));assert.ok(!view.includes('must-not-render'));
  assert.ok(configurationSnapshotHTML({call_id:'legacy'}).includes('Configuration snapshot not recorded'));
});

test('sampling rows show saved omission policies while explicit Top-P stays independent',()=>{
  const snapshot={schema_version:'model-call-config-v1',capture_kind:'before_dispatch',fields:{
    top_p:{status:'explicit',value:0.95,source:'request'},
    top_k:{status:'not_sent',value:null,source:'policy.deepseek_top_k_unsupported'},
    temperature:{status:'not_sent',value:null,source:'policy.deepseek_thinking_sampling_ignored'},
    seed:{status:'not_sent',value:null,source:'policy.seed_not_documented'}}};
  const view=configurationSnapshotHTML({call_id:'sampling',configuration_snapshot:snapshot});
  const row=key=>view.match(new RegExp('<tr data-config-field="'+key+'">(.*?)</tr>'))[1];
  assert.ok(row('top_p').includes('0.95'));assert.ok(!row('top_p').includes('ignores'));
  assert.ok(row('top_k').includes('Top-K'));assert.ok(row('top_k').includes('does not list Top-K'));
  assert.ok(row('temperature').includes('ignores temperature in thinking mode'));
  assert.ok(view.includes('not provider echoes'));assert.ok(view.includes('do not guarantee identical output'));
  const old=configurationSnapshotHTML({call_id:'old',requested_model:'deepseek-v4-pro'});
  assert.ok(old.match(/<tr data-config-field="top_k">(.*?)<\/tr>/)[1].includes('Not recorded'));
  assert.ok(!old.includes('ignores temperature in thinking mode'));
  snapshot.fields.top_k.source='policy.sonnet55_sampling_unsupported';
  assert.ok(configurationSnapshotHTML({call_id:'sonnet',configuration_snapshot:snapshot}).includes('does not permit non-default sampling settings'));
});

test('live call configuration updates preserve open details and do not rebuild for usage-only changes',()=>{
  let writes=0,opened={dataset:{detailKey:'config-first'},open:true},focused=0;
  const summary={closest(){return opened;}};
  const container={dataset:{},ownerDocument:{activeElement:summary},contains(node){return node===summary;},querySelectorAll(selector){return selector==='details[open]' ? (opened.open?[opened]:[]) : [opened];},set innerHTML(value){writes++;opened={dataset:{detailKey:'config-first'},open:false,querySelector(){return {focus(){focused++;}}}};}};
  const call={call_id:'first',started_at:'2034-03-02T14:30:00Z'};
  updateCallRecords(container,[call],()=>'<details></details>');assert.equal(opened.open,true);assert.equal(focused,1);assert.equal(writes,1);
  updateCallRecords(container,[{...call,input_tokens:50}],()=>'<details></details>');assert.equal(writes,1);
  updateCallRecords(container,[{...call,ended_at:'2034-03-02T14:30:02Z'}],()=>'<details></details>');assert.equal(writes,2);assert.equal(opened.open,true);
});

function scheduler() {
  let index=0; const tasks=new Map();
  return {tasks, setTimer(fn,ms){tasks.set(++index,{fn,ms});return index;},clearTimer(id){tasks.delete(id);},
    async next(){const [id,task]=tasks.entries().next().value || [];assert.ok(task,'expected scheduled work');tasks.delete(id);await task.fn();await settle();return task.ms;}};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const page = values => ({events:[],last_delivered_seq:1,high_watermark:1,next_cursor:'cursor-one',has_more:false,root_terminal:false,connection_state:'connected',...values});

test('root terminal drains all bounded tail pages and never restarts just because a heartbeat expires',async()=>{
  const clock=scheduler(),cursors=[],applied=[],states=[];
  const responses=[page({events:[{event_id:'finish'}],has_more:true,root_terminal:true,next_cursor:'tail'}),
    page({events:[{event_id:'late-accounting'}],root_terminal:true,last_delivered_seq:2,next_cursor:'done'})];
  const poller=createPoller({...clock,read:async cursor=>{cursors.push(cursor);return responses.shift();},apply:async p=>applied.push(...p.events),onState:s=>states.push(s)});
  poller.start();await clock.next();assert.equal(poller.state().ended,false);await clock.next();
  assert.deepEqual(cursors,[null,'tail']);assert.equal(applied.length,2);assert.equal(poller.state().ended,true);
  assert.equal(states.at(-1),'finished');assert.equal(clock.tasks.size,0);
  poller.visibilityChanged();assert.equal(clock.tasks.size,0);
});

test('a failed projection does not advance the event cursor or silently drop events',async()=>{
  const clock=scheduler(),cursors=[];let fail=true;
  const poller=createPoller({...clock,read:async c=>{cursors.push(c);return page();},apply:async()=>{if(fail){fail=false;throw Error('projection unavailable');}}});
  poller.start();await clock.next();assert.equal(poller.state().cursor,null);assert.equal(poller.state().retry,4000);
  await clock.next();assert.deepEqual(cursors,[null,null]);assert.equal(poller.state().cursor,'cursor-one');poller.stop();
});

test('polling never overlaps and visibility pauses the schedule while retaining the cursor',async()=>{
  const clock=scheduler();let hidden=false,finish,calls=0;
  const poller=createPoller({...clock,isHidden:()=>hidden,read:()=>{calls++;return new Promise(resolve=>finish=resolve);},apply:async()=>{}});
  poller.start();await clock.next();assert.equal(calls,1);poller.refresh();assert.equal(calls,1);
  hidden=true;poller.visibilityChanged();finish(page());await settle();assert.equal(clock.tasks.size,0);
  assert.equal(poller.state().cursor,'cursor-one');hidden=false;poller.visibilityChanged();assert.equal(clock.tasks.size,1);
  poller.stop();assert.equal(clock.tasks.size,0);
});

test('repeated network failures back off to 30 seconds without inventing a terminal outcome',async()=>{
  const clock=scheduler(),states=[];
  const poller=createPoller({...clock,read:async()=>{throw Error('offline');},apply:async()=>{},onState:s=>states.push(s)});
  poller.start();for(let i=0;i<6;i++)await clock.next();
  assert.equal(poller.state().retry,30000);assert.equal(poller.state().ended,false);
  assert.ok(states.every(s=>s==='error'));poller.stop();
});

test('explicit refresh can reread a completed run without automatic polling',async()=>{
  const clock=scheduler();let calls=0;
  const poller=createPoller({...clock,read:async()=>{calls++;return page({root_terminal:true});},apply:async()=>{}});
  poller.start();await clock.next();assert.equal(clock.tasks.size,0);await poller.refresh();
  assert.equal(calls,2);assert.equal(clock.tasks.size,0);
});

test('run projections cannot replace another scope or regress to an earlier revision',()=>{
  const current={id:'orchard',root_run_id:'root-one',revision:8,usage:{input_tokens:null}};
  assert.throws(()=>mergeRunView(current,{...current,id:'harbor'}),/identity/);
  assert.throws(()=>mergeRunView(current,{...current,root_run_id:'root-two'}),/identity/);
  assert.equal(mergeRunView(current,{...current,revision:7}),current);
  assert.equal(mergeRunView(current,{...current,revision:9}).usage.input_tokens,null);
});

test('artifact identities and cursors are encoded as values, never executable markup or paths',()=>{
  const value=artifactURL('/api/agent-runs','run/one','artifact?<bad>',{cursor:'a&run=other',browse:'/records/0'});
  assert.ok(value.startsWith('/api/agent-runs/run%2Fone/artifacts/artifact%3F%3Cbad%3E?'));
  const params=new URL(value,'http://local.test').searchParams;
  assert.equal(params.get('cursor'),'a&run=other');assert.equal(params.get('browse'),'/records/0');
  assert.equal(escape('<script>"&'), '&lt;script&gt;&quot;&amp;');
});

// Small DOM surface for read-state/focus and request races; no layout assertions.
function uiHarness(fetcher) {
  const nodes=[];
  const document={documentElement:{lang:'zh-CN'},hidden:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
  class Node {
    constructor(tag='div',id=null){this.tagName=tag;this.id=id;this.dataset={};this.children=[];this.attrs={};this.listeners={};this.hidden=false;this.disabled=false;this.value='';this.scrollTop=0;this._text='';this._html='';nodes.push(this);}
    matches(selector){if(selector.startsWith('#'))return this.id===selector.slice(1);if(selector.startsWith('[')){const key=selector.slice(1,-1).replace(/^data-/,'').replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return Object.hasOwn(this.dataset,key);}return this.tagName===selector;}
    querySelector(selector){return this.children.flatMap(child=>[child,...child.descendants()]).find(n=>n.matches(selector))||null;}
    descendants(){return this.children.flatMap(child=>[child,...child.descendants()]);}
    contains(target){return target===this||this.descendants().includes(target);}
    set innerHTML(value){if(this.contains(document.activeElement)&&this!==document.activeElement)document.activeElement=null;this.children=[];this._html=value;}
    get innerHTML(){return this._html;}
    set textContent(value){this.children=[];this._text=String(value);}
    get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
    setAttribute(k,v){this.attrs[k]=String(v);}
    removeAttribute(k){delete this.attrs[k];}
    addEventListener(name,fn){this.listeners[name]=fn;}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
    focus(){document.activeElement=this;}
    scrollIntoView(){this.scrollCalls=(this.scrollCalls||0)+1;}
  }
  document.querySelector=selector=>nodes.find(n=>n.matches(selector))||null;
  document.querySelectorAll=selector=>nodes.filter(n=>n.matches(selector));
  document.createElement=tag=>new Node(tag);
  document.createTextNode=text=>{const node=new Node('text');node.textContent=text;return node;};
  const ids=['ar-config','ar-language','ar-search','ar-message','ar-list-empty','ar-run-list','ar-list-count','ar-list-more','ar-main','ar-step-detail','ar-steps','ar-artifact-rows','ar-call-rows','ar-token-bars','ar-diagnostics','ar-call-detail','ar-connection','ar-refresh','ar-artifact-more','ar-artifact-close','ar-artifact-detail','ar-artifact-title','ar-artifact-status','ar-artifact-content','ar-artifact-children','ar-timing','ar-timing-note','ar-child-detail','ar-scope','ar-scope-config','ar-inputs','ar-configs','ar-run-relations','ar-run-tree-items'];
  const byId=Object.fromEntries(ids.map(id=>[id,new Node('div',id)]));
  const ref={id:'first',run_id:'orchard',label:'First',kind:'candidate',availability:'available',size_bytes:0};
  const second={...ref,id:'second',label:'Second'};
  const detail={id:'orchard',root_run_id:'orchard',revision:1,live:false,state:{execution:'running'},steps:[],artifacts:[ref,second],inputs:[],configs:[],calls:[{call_id:'call-one',run_id:'orchard',role:'planner',status:'started',input_tokens:null}],usage:{roles:[]},diagnostics:[]};
  byId['ar-config'].textContent=JSON.stringify({selection:{run:'orchard'},detail,listing:[],api:'/api/agent-runs'});
  const env={fetch:fetcher,sessionStorage:{getItem(){return null;},setItem(){}},location:{href:'http://local.test/agent-runs?run=orchard'},history:{replaceState(_s,_t,url){env.location.href=String(url);}},addEventListener(){},setTimeout,clearTimeout};
  const app=bootstrap(document,env);
  return {app,document,env,byId,detail,refs:[ref,second],Node};
}

test('late artifact response cannot replace a newer selected artifact; displayed content stays inert text',async()=>{
  const pending=[];
  const h=uiHarness(url=>new Promise(resolve=>pending.push({url,resolve})));
  const first=h.app.openArtifact(h.refs[0]);const second=h.app.openArtifact(h.refs[1]);
  pending[1].resolve({ok:true,json:async()=>({id:'second',run_id:'orchard',content:'<script>bad()</script>',availability:'available',children:[],truncated:false,next_cursor:null})});
  await second;
  pending[0].resolve({ok:true,json:async()=>({id:'first',run_id:'orchard',content:'stale first',availability:'available',children:[],truncated:false,next_cursor:null})});
  await first;
  assert.equal(h.byId['ar-artifact-title'].textContent,'Second');
  assert.equal(h.byId['ar-artifact-content'].textContent,'<script>bad()</script>');
  assert.equal(h.byId['ar-artifact-content'].children.length,0);
});

test('artifact pagination retains prior content and rejects a concurrent repeated load-more request',async()=>{
  const pending=[];const h=uiHarness(url=>new Promise(resolve=>pending.push({url,resolve})));
  const first=h.app.openArtifact(h.refs[0]);
  pending[0].resolve({ok:true,json:async()=>({id:'first',run_id:'orchard',content:'page one',availability:'available',children:[],truncated:true,next_cursor:'c&next'})});await first;
  const next=h.app.openArtifact(h.refs[0],{append:true});await h.app.openArtifact(h.refs[0],{append:true});
  assert.equal(pending.length,2);assert.equal(new URL(pending[1].url,'http://local').searchParams.get('cursor'),'c&next');
  pending[1].resolve({ok:true,json:async()=>({id:'first',run_id:'orchard',content:'page two',availability:'available',children:[],truncated:false,next_cursor:null})});await next;
  assert.equal(h.byId['ar-artifact-content'].textContent,'page one\npage two');assert.equal(h.byId['ar-artifact-more'].hidden,true);
});

test('live projections update summaries without replacing focused controls or open reading panels',()=>{
  const h=uiHarness(async()=>{throw Error('unexpected fetch');});
  h.byId['ar-step-detail'].innerHTML='currently reading a step';h.byId['ar-step-detail'].scrollTop=180;
  h.byId['ar-artifact-content'].textContent='kept body';h.byId['ar-artifact-content'].scrollTop=240;
  const row=new h.Node('tr');row.dataset.callRow='call-one';
  const cell=new h.Node('td'),button=new h.Node('button');button.dataset.call='call-one';cell.append(button);row.append(cell);h.byId['ar-call-rows'].append(row);button.focus();
  h.app.updateView({...h.detail,revision:2,calls:[{...h.detail.calls[0],status:'succeeded',input_tokens:100}]});
  assert.equal(h.document.activeElement,button);assert.equal(row.children[0].querySelector('[data-call]'),button);
  assert.equal(h.byId['ar-step-detail'].innerHTML,'currently reading a step');assert.equal(h.byId['ar-step-detail'].scrollTop,180);
  assert.equal(h.byId['ar-artifact-content'].textContent,'kept body');assert.equal(h.byId['ar-artifact-content'].scrollTop,240);
});

test('child-owned artifacts use selected root route and continuation excludes browse',async()=>{
  const urls=[];
  const h=uiHarness(async url=>{urls.push(url);return {ok:true,json:async()=>({id:'child-artifact',run_id:'child',content:'part',availability:'available',children:[],truncated:urls.length===1,next_cursor:urls.length===1?'opaque-cursor':null})};});
  const ref={id:'child-artifact',run_id:'child',label:'Child output'};
  await h.app.openArtifact(ref,{browse:'opaque-browse'});
  await h.app.openArtifact(ref,{append:true});
  assert.equal(new URL(urls[0],'http://local').pathname,'/api/agent-runs/orchard/artifacts/child-artifact');
  const query=new URL(urls[1],'http://local').searchParams;
  assert.equal(query.get('cursor'),'opaque-cursor');assert.equal(query.has('browse'),false);
  assert.equal(h.byId['ar-artifact-content'].textContent,'part\npart');
});

test('timing derives intervals only from complete timestamps, never elapsed guesses or history',()=>{
  const rows=[{id:'a',started_at:'2034-03-02T01:00:00Z',ended_at:'2034-03-02T01:00:02Z',elapsed_seconds:1.9},
    {id:'b',started_at:'2034-03-02T01:00:01Z',ended_at:'2034-03-02T01:00:04Z',elapsed_seconds:2.9},
    {id:'open',started_at:'2034-03-02T01:00:01Z',elapsed_seconds:20},
    {id:'bad',started_at:'2034-03-02T01:00:05Z',ended_at:'2034-03-02T01:00:04Z'},
    {id:'local',started_at:'2034-03-02T01:00:00',ended_at:'2034-03-02T01:00:02'}];
  assert.deepEqual(timedSteps({live:false,steps:rows}),[]);
  const timed=timedSteps({live:true,steps:rows});
  assert.deepEqual(timed.map(row=>[row.step.id,row.left,row.width]),[['a',0,50],['b',25,75]]);
});

test('child inspection remains inside the root and links back to its parent step',()=>{
  const h=uiHarness(async()=>{throw Error('unexpected fetch');});
  h.app.updateView({...h.detail,revision:2,run_tree:[{id:'orchard'},{id:'child',parent_run_id:'orchard',parent_step_id:'step-one',role:'extractor'}],
    artifacts:[{id:'child-artifact',run_id:'child',label:'Candidate'}]});
  h.app.showChild('child');
  assert.equal(h.byId['ar-child-detail'].hidden,false);
  assert.match(h.byId['ar-child-detail'].innerHTML,/data-step="step-one"/);
  assert.match(h.byId['ar-child-detail'].innerHTML,/data-artifact-run="child"/);
  assert.equal(new URL(h.env.location.href).searchParams.get('run'),'orchard');
  h.app.showChild('orchard');assert.equal(h.byId['ar-child-detail'].hidden,true);
});

test('new step actions, child relationships, scope and configuration references appear without losing step focus',()=>{
  const h=uiHarness(async()=>{throw Error('unexpected fetch');});
  const running={id:'step-one',run_id:'orchard',ordinal:1,action:null,phase:'planning',status:'running'};
  h.app.updateView({...h.detail,revision:2,steps:[running]});
  const row=h.byId['ar-steps'].children[0],button=row.children[0];button.focus();
  h.app.updateView({...h.detail,revision:3,scope:{company_id:'orchard',periods:['2033']},
    steps:[{...running,action:'extract_financials',phase:'executing'},{id:'child-step',run_id:'child',ordinal:1}],
    run_tree:[{id:'orchard'},{id:'child',parent_run_id:'orchard',parent_step_id:'step-one',role:'extractor'}],
    inputs:[{...h.refs[0],id:'input-one'}],configs:[{...h.refs[0],id:'config-one'}]});
  assert.equal(h.document.activeElement,button);
  assert.match(row.querySelector('[data-step-label]').textContent,/extract_financials/);
  assert.equal(h.byId['ar-steps'].children.length,1);
  assert.equal(h.byId['ar-inputs'].children[0].children[0].dataset.artifact,'input-one');
  assert.equal(h.byId['ar-configs'].children[0].children[0].dataset.artifact,'config-one');
  assert.equal(h.byId['ar-run-relations'].hidden,false);
  assert.equal(h.byId['ar-run-tree-items'].children.length,2);
  assert.equal(h.byId['ar-scope'].textContent,'orchard · 2033');
});
