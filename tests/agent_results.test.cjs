const {test} = require('node:test');
const assert = require('node:assert/strict');
const {artifactURL,scorePayload,createScoreController,createArtifactReader,scoreHistoryHTML,draftKey} = require('../apps/review_workbench/static/js/agent_results.js');
const binding={trace_id:'orchard-2033',revision:'rev3',result_sha256:'a'.repeat(64)};
const values={reviewer:'Rain',scores:{accuracy:0,coverage:'5',analysis:'',evidence:null},notes:'Check source'};
const record={id:'review1',binding,rubric_version:'agent-result-v1',reviewer:'Rain',scores:{accuracy:0,coverage:5,analysis:null,evidence:null},notes:'Check source'};
const page={binding,rubric_version:'agent-result-v1',current:[record],stale:[]};

test('reviews retain zero and null separately, reject invalid values, and bind to one result',()=>{
  const payload=scorePayload(binding,values);
  assert.deepEqual(payload.scores,{accuracy:0,coverage:5,analysis:null,evidence:null});
  assert.deepEqual(payload.binding,binding);assert.notEqual(payload.binding,binding);
  for(const invalid of [true,false,-1,6,1.2,'NaN','1e0','01']) assert.throws(()=>scorePayload(binding,{...values,scores:{...values.scores,accuracy:invalid}}));
  assert.throws(()=>scorePayload(binding,{...values,reviewer:' '}));
  assert.throws(()=>scorePayload(binding,{...values,scores:{}}));
});

test('score save uses same-origin write headers and saves exactly once while a request is pending',async()=>{
  const calls=[],states=[];let finish;
  const control=createScoreController({binding,url:'/scores',request:(url,options)=>{calls.push({url,options});return options ? new Promise(resolve=>finish=resolve) : Promise.resolve(page);},onState:s=>states.push(s)});
  const saving=control.save(values);assert.equal(await control.save(values),false);
  assert.equal(calls.length,1);assert.equal(calls[0].options.headers['X-Uteki-Request'],'1');
  assert.deepEqual(JSON.parse(calls[0].options.body).binding,binding);
  finish(record);assert.equal(await saving,true);
  assert.equal(calls.length,2);assert.ok(states.some(s=>s.status==='saved'));assert.equal(control.state().saving,false);
});

test('a 409 does not rebind a draft or retry against a different result',async()=>{
  const states=[],calls=[];
  const control=createScoreController({binding,url:'/scores',request:async(url,options)=>{calls.push(options);const error=Error('stale');error.status=409;throw error;},onState:s=>states.push(s)});
  assert.equal(await control.save(values),false);assert.equal(calls.length,1);
  assert.ok(states.some(s=>s.status==='stale'));assert.deepEqual(values.scores,{accuracy:0,coverage:'5',analysis:'',evidence:null});
  assert.equal(JSON.parse(calls[0].body).binding.revision,'rev3');
});

test('a saved review whose refresh fails remains marked saved without encouraging duplicate submission',async()=>{
  const states=[];
  const control=createScoreController({binding,url:'/scores',request:async(url,options)=>{if(options)return record;throw Error('offline');},onState:s=>states.push(s)});
  assert.equal(await control.save(values),true);assert.ok(states.some(s=>s.status==='saved_unloaded'));
  assert.equal(states.some(s=>s.status==='saved'),false);
});

test('current reviews with another Trace ID are rejected and outdated responses cannot overwrite newer ones',async()=>{
  const states=[],resolvers=[];
  const control=createScoreController({binding,url:'/scores',request:()=>new Promise(resolve=>resolvers.push(resolve)),onState:s=>states.push(s)});
  const first=control.load(),second=control.load();
  resolvers[1](page);await second;
  resolvers[0]({...page,current:[]});await first;
  assert.equal(states.filter(s=>s.status==='loaded').length,1);
  const bad=createScoreController({binding,url:'/scores',request:async()=>({...page,current:[{...record,binding:{...binding,trace_id:'harbor'}}]}),onState:s=>states.push(s)});
  await bad.load();assert.equal(states.at(-1).status,'error');
});

test('review history renders text safely and distinguishes zero, unscored and older revisions',()=>{
  const output=scoreHistoryHTML({...page,current:[{...record,reviewer:'<script>bad()</script>',notes:'<img src=x>'}],stale:[record]});
  assert.ok(output.includes('&lt;script&gt;'));assert.ok(output.includes('&lt;img'));assert.ok(output.includes('<dd>0</dd>'));
  assert.ok(output.includes('Unscored'));assert.ok(output.includes('older revisions'));assert.ok(!output.includes('<script>'));
});

test('review drafts never transfer to another trace, revision or result hash',()=>{
  const key=draftKey(binding);
  for(const other of [{...binding,trace_id:'harbor'}, {...binding,revision:'rev4'}, {...binding,result_sha256:'b'.repeat(64)}]) assert.notEqual(draftKey(other),key);
  assert.equal(draftKey({...binding}),key);
});

test('artifact URLs keep root selection distinct from child owner and encode cursor values',()=>{
  const value=artifactURL('/api/agent-runs','root/a','file?x',{revision:3,cursor:'opaque&run=bad'});
  assert.ok(value.startsWith('/api/agent-runs/root%2Fa/artifacts/file%3Fx?'));
  const query=new URL(value,'http://localhost').searchParams;
  assert.equal(query.get('cursor'),'opaque&run=bad');assert.equal(query.get('revision'),'3');
  const history=artifactURL('/api/agent-runs','root','file',{revision:'a'.repeat(64)});
  assert.equal(new URL(history,'http://localhost').searchParams.get('revision'),'a'.repeat(64));
  assert.throws(()=>artifactURL('/api','r','f',{cursor:'c',browse:'b'}));
});

test('artifact reads do not cross runs or hashes and ignore an older request after a new selection',async()=>{
  const a={id:'a',run_id:'child',sha256:'a'},b={id:'b',run_id:'child',sha256:'b'};
  const calls=[],states=[],resolvers=[];
  const reader=createArtifactReader({base:'/api/agent-runs',run:'root',revision:4,request:url=>{calls.push(url);return new Promise(resolve=>resolvers.push(resolve));},onState:s=>states.push(s)});
  const first=reader.open(a),second=reader.open(b);
  resolvers[1]({...b,content:'second',children:[],next_cursor:null});await second;
  resolvers[0]({...a,content:'first',children:[],next_cursor:null});await first;
  assert.deepEqual(states.filter(s=>s.status==='loaded').map(s=>s.data.content),['second']);
  assert.ok(calls.every(url=>url.includes('/root/artifacts/')));
  const third=reader.open(a);resolvers[2]({...a,run_id:'foreign-child',content:'foreign'});await third;
  assert.equal(states.at(-1).status,'error');
});

test('artifact continuation preserves opaque cursors, has one in-flight continuation, and close cancels display',async()=>{
  const ref={id:'file',run_id:'child',sha256:'hash'},calls=[],states=[],resolvers=[];
  const reader=createArtifactReader({base:'/api/agent-runs',run:'root',request:url=>{calls.push(url);return new Promise(resolve=>resolvers.push(resolve));},onState:s=>states.push(s)});
  const first=reader.open(ref);resolvers[0]({...ref,content:'first',children:[],next_cursor:'next'});await first;
  const more=reader.more();await reader.more();assert.equal(calls.length,2);assert.ok(calls[1].endsWith('?cursor=next'));
  reader.close();resolvers[1]({...ref,content:'late',children:[],next_cursor:null});await more;
  assert.equal(states.at(-1).status,'closed');assert.equal(reader.state().cursor,null);
});
