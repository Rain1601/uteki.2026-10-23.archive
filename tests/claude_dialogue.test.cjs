const {test} = require('node:test');
const assert = require('node:assert/strict');
const {
  normalizeConversation, money, numericAmount, blockingText, shouldSendKey,
  budgetPayload, errorText, actorLabel, createController,
} = require('../apps/claude_dialogue/chat.js');

function conversation(overrides={}) {
  return {revision:'revision-1',model:'claude-opus-5-5',configuration:{thinking:{type:'adaptive'},effort:'high',stream:false},
    budget:{limit_usd:'5.00',spent_usd:'0.25',held_usd:'0',remaining_usd:'4.75'},turns:[],pending:null,...overrides};
}
function deferred() { let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject}; }
function apiError(status,code,message) { return Object.assign(new Error('request failed'),{status,code,publicMessage:message}); }

test('all nine original turns and unsafe-looking content remain exact text; duplicate identity is rejected',()=>{
  const source=conversation({turns:Array.from({length:9},(_,i)=>({number:i+1,actor:i%2?'user':'codex',status:'completed',user:'提问\n <script>not code</script>\n ',answer:'## 原文\n<script>alert(1)</script>\n| 原表 |\n'}))});
  const normalized=normalizeConversation(source);
  assert.equal(normalized.turns.length,9);
  assert.deepEqual(normalized.turns.map(t=>[t.user,t.answer]),source.turns.map(t=>[t.user,t.answer]));
  assert.throws(()=>normalizeConversation({...source,turns:[source.turns[0],source.turns[0]]}));
  assert.throws(()=>normalizeConversation({...source,turns:[{number:1,user:null}]}));
  assert.equal(actorLabel('codex'),'Codex');assert.equal(actorLabel('user'),'你');
});

test('money accepts Decimal strings and distinguishes missing from zero; budget input has explicit scope',()=>{
  assert.equal(money('0.25'),'$0.2500');assert.equal(money('0E-7'),'$0.0000');assert.equal(money(0),'$0.0000');
  for(const value of [null,undefined,true,false,'',' ','0x10','Infinity',NaN]) assert.equal(numericAmount(value),null);
  assert.equal(money(null),'未记录');assert.deepEqual(budgetPayload('8.50','r2'),{limit_usd:8.5,expected_revision:'r2'});
  for(const value of [0,-1,'NaN','1e3','Infinity','',true]) assert.throws(()=>budgetPayload(value,'r2'));
});

test('only explicit command-enter sends; native Enter and IME composition retain line breaks',()=>{
  assert.equal(shouldSendKey({key:'Enter'}),false);
  assert.equal(shouldSendKey({key:'Enter',metaKey:true}),true);
  assert.equal(shouldSendKey({key:'Enter',ctrlKey:true}),true);
  assert.equal(shouldSendKey({key:'Enter',ctrlKey:true,isComposing:true}),false);
  assert.equal(shouldSendKey({key:'Enter',ctrlKey:true,repeat:true}),false);
  assert.equal(shouldSendKey({key:'a',ctrlKey:true}),false);
});

test('CSRF bootstrap, exact user payload and a single accepted pending request precede completion',async()=>{
  const calls=[],completed=[],post=deferred();let current=conversation();
  const controller=createController({newId:()=> 'request-1',onCompleted:t=>completed.push(t),request:async(url,options)=>{
    calls.push({url,options});if(url==='/api/session')return {csrf_token:'test-csrf'};
    if(url==='/api/conversation')return current;
    return post.promise;
  }});
  await controller.start();
  const message='  完整提问\n第二行 <script>literal</script>  ';
  const sending=controller.send(message);
  assert.equal(await controller.send(message),false);
  const written=calls.find(c=>c.options);
  assert.equal(written.options.headers['X-CSRF-Token'],'test-csrf');
  assert.deepEqual(JSON.parse(written.options.body),{message,expected_revision:'revision-1',client_request_id:'request-1'});
  assert.equal('actor' in JSON.parse(written.options.body),false);
  current=conversation({revision:'revision-2',pending:{client_request_id:'request-1',message,actor:'user',status:'running'}});
  post.resolve({accepted:true});assert.equal(await sending,true);
  assert.equal(controller.state().waiting,true);assert.deepEqual(completed,[]);
  assert.equal(await controller.send('next'),false);
  current=conversation({revision:'revision-3',last_submission:{client_request_id:'request-1',status:'completed'},turns:[{number:1,actor:'user',status:'completed',user:message,answer:'答复'}]});
  await controller.load();await controller.load();
  assert.deepEqual(completed,[message]);assert.equal(controller.state().waiting,false);
  assert.equal(calls.filter(c=>c.url==='/api/messages').length,1);
});

test('an asynchronous provider failure preserves the draft and reports blocked state without retries',async()=>{
  const calls=[],completed=[];let current=conversation();
  const controller=createController({newId:()=> 'failed-request',onCompleted:t=>completed.push(t),request:async(url,options)=>{
    calls.push({url,options});if(url==='/api/session')return {csrf_token:'csrf'};if(url==='/api/conversation')return current;
    current=conversation({revision:'running',pending:{client_request_id:'failed-request'}});return {accepted:true};
  }});
  await controller.start();await controller.send('保留这份输入');
  current=conversation({revision:'failed',blocked:true,last_submission:{client_request_id:'failed-request',status:'failed',error_code:'request_failed'},budget:{send_blocked_reason:'previous_turn_failed_or_interrupted'}});
  await controller.load();
  assert.deepEqual(completed,[]);assert.equal(controller.state().waiting,false);
  assert.match(controller.state().notice,/Claude 服务调用失败/);
  assert.match(blockingText(current),/核对结果与费用/);
  assert.equal(await controller.send('保留这份输入'),false);
  assert.equal(calls.filter(c=>c.url==='/api/messages').length,1);
});

test('lost acceptance response reuses its request ID only after explicit manual retry',async()=>{
  const calls=[],completed=[];let count=0,ids=0;
  const controller=createController({newId:()=> 'id-'+(++ids),onCompleted:t=>completed.push(t),request:async(url,options)=>{
    calls.push({url,options});if(url==='/api/session')return {csrf_token:'csrf'};
    if(url==='/api/conversation')return conversation({revision:count?'newer':'revision-1'});
    if(url.startsWith('/api/submissions/'))throw apiError(404,'submission_not_found');
    count++;if(count===1)throw new Error('connection lost');
    return {accepted:true,replayed:true,submission:{client_request_id:'id-1',status:'completed'}};
  }});
  await controller.start();assert.equal(await controller.send('same exact message'),false);
  assert.equal(calls.filter(c=>c.url==='/api/messages').length,1);assert.deepEqual(completed,[]);
  await controller.load();assert.equal(calls.filter(c=>c.url==='/api/messages').length,1);
  assert.equal(await controller.send('same exact message'),true);
  const posts=calls.filter(c=>c.options).map(c=>JSON.parse(c.options.body));
  assert.deepEqual(posts[0],posts[1]);assert.deepEqual(completed,['same exact message']);assert.equal(ids,1);
});

test('409 leaves draft intact, refreshes revision, and does not automatically submit again',async()=>{
  let writes=0;const completed=[];
  const controller=createController({newId:()=> 'conflict-'+writes,onCompleted:t=>completed.push(t),request:async(url,options)=>{
    if(url==='/api/session')return {csrf_token:'csrf'};
    if(url==='/api/conversation')return conversation({revision:writes?'revision-2':'revision-1'});
    writes++;throw apiError(409,'revision_conflict','会话已有新消息。');
  }});
  await controller.start();assert.equal(await controller.send('draft'),false);
  assert.equal(writes,1);assert.deepEqual(completed,[]);assert.equal(controller.state().conversation.revision,'revision-2');
  assert.match(controller.state().notice,/已保留输入/);
});

test('a replayed failed submission is not presented as a new running model call',async()=>{
  const completed=[];
  const controller=createController({newId:()=> 'failed-replay',onCompleted:t=>completed.push(t),request:async(url)=>{
    if(url==='/api/session')return {csrf_token:'csrf'};if(url==='/api/conversation')return conversation();
    return {accepted:true,replayed:true,submission:{client_request_id:'failed-replay',status:'failed',error_code:'budget_insufficient'}};
  }});
  await controller.start();await controller.send('draft');
  assert.equal(controller.state().waiting,false);assert.deepEqual(completed,[]);assert.match(controller.state().notice,/额度不足/);
});

test('a slower previous read cannot overwrite a newer history or falsely complete a submission',async()=>{
  const first=deferred(),second=deferred();let reads=0;
  const controller=createController({request:()=> (++reads===1?first:second).promise});
  const a=controller.load(),b=controller.load();
  second.resolve(conversation({revision:'newest'}));await b;
  first.resolve(conversation({revision:'older'}));await a;
  assert.equal(controller.state().conversation.revision,'newest');
});

test('budget save uses CSRF and current revision; refresh failure does not invite duplicate saving',async()=>{
  const calls=[];let saved=false;
  const controller=createController({request:async(url,options)=>{
    calls.push({url,options});if(url==='/api/session')return {csrf_token:'budget-csrf'};
    if(url==='/api/conversation'){if(saved)throw new Error('offline');return conversation();}
    saved=true;return {saved:true};
  }});
  await controller.start();assert.equal(await controller.saveBudget('bad'),false);
  assert.equal(calls.filter(c=>c.options).length,0);
  assert.equal(await controller.saveBudget('10.25'),true);
  const post=calls.find(c=>c.url==='/api/budget');
  assert.equal(post.options.headers['X-CSRF-Token'],'budget-csrf');
  assert.deepEqual(JSON.parse(post.options.body),{limit_usd:10.25,expected_revision:'revision-1'});
  assert.match(controller.state().notice,/额度已保存/);assert.match(controller.state().notice,/无须重复保存/);
  assert.equal(controller.state().budgetSaved,1);
});

test('pending, exhausted budget and unverified session prevent writes; public errors explain 502/409',async()=>{
  let writes=0;let current=conversation({pending:{actor:'codex',client_request_id:'external'}});
  const controller=createController({request:async(url,options)=>{
    if(options){writes++;return {accepted:true};}if(url==='/api/session')return {csrf_token:'csrf'};return current;
  }});
  assert.equal(await controller.send('draft'),false);await controller.start();assert.equal(await controller.send('draft'),false);
  current=conversation({budget:{send_blocked_reason:'budget_insufficient'}});await controller.load();assert.equal(await controller.send('draft'),false);
  assert.equal(writes,0);assert.match(blockingText(current),/调整总上限/);
  assert.match(errorText(apiError(502,'upstream_error')),/Claude 请求失败/);
  assert.match(errorText(apiError(409,'session_locked','已有请求执行中。')),/已保留输入/);
});

test('expired CSRF requires reconnecting before another write while keeping the same draft',async()=>{
  let sessions=0,writes=0;const completed=[];
  const controller=createController({newId:()=> 'session-'+writes,onCompleted:t=>completed.push(t),request:async(url,options)=>{
    if(url==='/api/session')return {csrf_token:'csrf-'+(++sessions)};
    if(url==='/api/conversation')return conversation();
    writes++;assert.equal(options.headers['X-CSRF-Token'],'csrf-1');throw apiError(403,'unauthorized');
  }});
  await controller.start();await controller.send('未发送的草稿');
  assert.equal(controller.state().sessionReady,false);assert.deepEqual(completed,[]);
  assert.equal(await controller.send('未发送的草稿'),false);assert.equal(writes,1);
  await controller.start();assert.equal(sessions,2);assert.equal(controller.state().sessionReady,true);
});

test('identical text from another client cannot complete our request; exact ID is polled without POST',async()=>{
  const calls=[],completed=[];let current=conversation(),ownStatus='running';
  const message='同样的问题';
  const controller=createController({newId:()=> 'own-id',onCompleted:t=>completed.push(t),request:async(url,options)=>{
    calls.push({url,options});if(url==='/api/session')return {csrf_token:'csrf'};
    if(url==='/api/conversation')return current;
    if(url==='/api/submissions/own-id')return {submission:{client_request_id:'own-id',status:ownStatus}};
    assert.equal(url,'/api/messages');
    current=conversation({revision:'other-client-finished',last_submission:{client_request_id:'other-id',status:'completed'},
      turns:[{number:1,actor:'user',user:message,answer:'另一端的回复',status:'completed'}]});
    return {accepted:true};
  }});
  await controller.start();await controller.send(message);
  assert.equal(controller.state().waiting,true);assert.deepEqual(completed,[]);
  assert.equal(calls.filter(c=>c.url==='/api/submissions/own-id').length,1);
  assert.equal(await controller.send(message),false);
  ownStatus='completed';await controller.load();await controller.load();
  assert.deepEqual(completed,[message]);assert.equal(controller.state().waiting,false);
  assert.equal(calls.filter(c=>c.url==='/api/messages').length,1);
  assert.ok(calls.filter(c=>c.url.startsWith('/api/submissions/')).every(c=>c.options===undefined));
});

test('another client success cannot mask our exact failed submission',async()=>{
  const completed=[];let current=conversation();
  const controller=createController({newId:()=> 'own-failed',onCompleted:t=>completed.push(t),request:async(url)=>{
    if(url==='/api/session')return {csrf_token:'csrf'};if(url==='/api/conversation')return current;
    if(url==='/api/submissions/own-failed')return {submission:{client_request_id:'own-failed',status:'failed',error_code:'budget_insufficient'}};
    current=conversation({last_submission:{client_request_id:'other',status:'completed'},turns:[{number:1,actor:'user',user:'same',answer:'other',status:'completed'}]});
    return {accepted:true};
  }});
  await controller.start();await controller.send('same');
  assert.deepEqual(completed,[]);assert.equal(controller.state().waiting,false);assert.match(controller.state().notice,/额度不足/);
});

test('missing or mismatched exact submission records never clear an accepted draft or resend',async()=>{
  for(const mode of ['missing','mismatch']) {
    let posts=0;const completed=[];
    const controller=createController({newId:()=> 'expected-id',onCompleted:t=>completed.push(t),request:async(url)=>{
      if(url==='/api/session')return {csrf_token:'csrf'};if(url==='/api/conversation')return conversation();
      if(url==='/api/submissions/expected-id'){
        if(mode==='missing')throw apiError(404,'submission_not_found');
        return {submission:{client_request_id:'wrong-id',status:'completed'}};
      }
      posts++;return {accepted:true};
    }});
    await controller.start();await controller.send('draft');await controller.load();
    assert.deepEqual(completed,[]);assert.equal(controller.state().waiting,true);assert.equal(posts,1);
    assert.equal(await controller.send('draft'),false);
    assert.match(mode==='missing'?controller.state().notice:controller.state().connectionError,/记录|核实/);
  }
});

test('a late exact-ID lookup cannot overwrite a newer confirmed completion',async()=>{
  const lookups=[],completed=[];let current=conversation();
  const controller=createController({newId:()=> 'own-late',onCompleted:t=>completed.push(t),request:async(url)=>{
    if(url==='/api/session')return {csrf_token:'csrf'};if(url==='/api/conversation')return current;
    if(url==='/api/submissions/own-late'){const value=deferred();lookups.push(value);return value.promise;}
    current=conversation({pending:{client_request_id:'own-late',status:'running'}});return {accepted:true};
  }});
  await controller.start();await controller.send('draft');
  current=conversation({last_submission:{client_request_id:'other',status:'completed'}});
  const first=controller.load();await new Promise(resolve=>setImmediate(resolve));
  const second=controller.load();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(lookups.length,2);
  lookups[1].resolve({submission:{client_request_id:'own-late',status:'completed'}});await second;
  lookups[0].resolve({submission:{client_request_id:'own-late',status:'failed',error_code:'request_failed'}});await first;
  assert.deepEqual(completed,['draft']);assert.equal(controller.state().waiting,false);assert.equal(controller.state().notice,'Claude 已回复。');
});
