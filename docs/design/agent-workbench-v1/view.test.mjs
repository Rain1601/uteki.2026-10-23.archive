import test from 'node:test';
import assert from 'node:assert/strict';
import { DEMO } from './demo-data.mjs';
import { createState, reduce, getRun, getArtifact, reviewKey } from './model.mjs';
import { renderLayout, renderMain, renderInspector } from './render.mjs';
import { createController } from './app.mjs';

// Minimal event/scroll harness. This verifies controller behavior, not browser layout.
function harness() {
  const listeners = new Map();
  const nodes = new Map();
  let mounted = false;
  for (const selector of ['.studio','.sidebar','.main-workspace','.inspector','.inspector-body','#main-scroll','#toast']) {
    nodes.set(selector, { innerHTML:'', textContent:'', hidden:false, scrollTop:0, scrollHeight:1000, focus(){}, classList:{toggle(){}} });
  }
  const root = {
    set innerHTML(value) { mounted=true; this.html=value; },
    querySelector(selector) { return selector==='.studio'&&!mounted ? null : nodes.get(selector); },
    querySelectorAll() { return []; }, contains() { return true; },
    addEventListener(name,handler) { listeners.set(name,handler); },
    removeEventListener(name) { listeners.delete(name); },
  };
  const controller=createController(root,DEMO,{setTimeout:()=>1,clearTimeout(){}});
  const emit=(name,target,extra={})=>listeners.get(name)?.({target,preventDefault(){},...extra});
  const click=(action,fields={})=>{const target={dataset:{action,...fields}};target.closest=()=>target;emit('click',target);};
  const form=(type,values,criterion='evidence')=>({dataset:{form:type,criterion},elements:{namedItem:name=>({value:values[name]})}});
  return {controller,nodes,emit,click,form,listeners};
}

test('every fixture run and tab renders in both languages with scoped artifact controls',()=>{
  for(const lang of ['zh','en']) for(const task of DEMO.tasks) for(const run of task.runs) for(const tab of ['result','process','review']) {
    let state=reduce(createState(DEMO),{type:'selectTask',taskId:task.id},DEMO);
    state=reduce(state,{type:'selectRun',runId:run.id},DEMO);
    state={...state,lang,tab};
    const html=renderLayout(state,DEMO);
    assert.ok(html.includes(task.title[lang]));
    assert.match(html,lang==='zh'?/全部为示例数据/:/Sample data/);
    for(const [,artifactId] of html.matchAll(/data-action="artifact" data-artifact="([^"]+)"/g)) {
      const artifact=getArtifact(DEMO,artifactId);
      assert.equal(artifact.taskId,task.id);assert.equal(artifact.runId,run.id);
    }
  }
});

test('pending requests expose no output or review controls and escape instruction markup',()=>{
  const state=reduce(createState(DEMO),{type:'appendInstruction',text:'<img src=x onerror=alert(1)> & evidence'},DEMO);
  const process=renderMain(state,DEMO);
  assert.ok(process.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(!process.includes('<img src=x'));
  assert.match(process,/尚无执行步骤/);
  assert.ok(!renderMain({...state,tab:'review'},DEMO).includes('data-form="review"'));
  assert.ok(!renderMain({...state,tab:'result'},DEMO).includes('data-action="artifact"'));
});

test('experiment cells declare their artifact task and run and inspector links back to that run',()=>{
  let state={...createState(DEMO),view:'experiments'};
  const html=renderMain(state,DEMO);
  let count=0;
  for(const [,artifactId,taskId,runId] of html.matchAll(/data-action="experimentArtifact" data-artifact="([^"]+)" data-task="([^"]+)" data-run="([^"]+)"/g)) {
    state=reduce(state,{type:'openArtifact',artifactId,taskId,runId},DEMO);
    assert.match(renderInspector(state,DEMO),new RegExp(`data-action="artifactProcess" data-task="${taskId}" data-run="${runId}"`));
    count++;
  }
  assert.equal(count,DEMO.experiment.cases.reduce((n,item)=>n+item.results.length,0));
});

test('opening and closing evidence preserves main scroll; each task tab remembers its position',()=>{
  const h=harness(); const scroll=h.nodes.get('#main-scroll');
  scroll.scrollTop=321;h.click('artifact',{artifact:'googl-record-v2'});
  assert.equal(scroll.scrollTop,321);assert.equal(h.controller.getState().artifactId,'googl-record-v2');
  h.emit('keydown',{}, {key:'Escape'});assert.equal(scroll.scrollTop,321);
  assert.equal(h.controller.getState().artifactId,null);
  h.click('tab',{value:'process'});assert.equal(scroll.scrollTop,0);
  scroll.scrollTop=160;h.click('tab',{value:'result'});assert.equal(scroll.scrollTop,321);
  h.click('tab',{value:'process'});assert.equal(scroll.scrollTop,160);
});

test('review drafts survive evidence inspection, language and run changes without becoming saved reviews',()=>{
  const h=harness();h.click('tab',{value:'review'});
  const form=h.form('review',{});
  h.emit('input',{name:'note',value:'需要核对 <单位>',closest:()=>form});
  h.emit('change',{name:'verdict',value:'insufficient',closest:()=>form});
  h.click('artifact',{artifact:'googl-record-v2'});h.click('language');h.click('closeArtifact');
  const html=h.nodes.get('.main-workspace').innerHTML;
  assert.ok(html.includes('需要核对 &lt;单位&gt;'));
  assert.ok(html.includes('value="insufficient" selected'));
  assert.deepEqual(h.controller.getState().notes,{});
  h.emit('change',{dataset:{control:'run'},value:'googl-cashflow-r1'});
  assert.ok(!h.nodes.get('.main-workspace').innerHTML.includes('需要核对'));
  h.emit('change',{dataset:{control:'run'},value:'googl-cashflow-r2'});
  assert.ok(h.nodes.get('.main-workspace').innerHTML.includes('需要核对'));
});

test('saving review and submitting instruction use distinct actions and preserve historical data',()=>{
  const h=harness();const before=JSON.stringify(DEMO);
  h.emit('submit',h.form('review',{verdict:'insufficient',note:'核对单位和期间'}));
  let state=h.controller.getState();
  assert.equal(state.notes[reviewKey(state.taskId,state.runId,'evidence')].note,'核对单位和期间');
  assert.equal(state.pendingRuns.length,0);
  h.emit('submit',h.form('instruction',{instruction:'请补充单位证据'}));
  state=h.controller.getState();const run=getRun(DEMO,state.taskId,state.runId,state);
  assert.equal(run.status,'pending');assert.deepEqual(run.steps,[]);assert.deepEqual(run.artifactIds,[]);
  assert.equal(state.tab,'process');assert.equal(state.reviewHistory.length,1);
  assert.equal(JSON.stringify(DEMO),before);
});

test('experiment inspection preserves comparison scroll and can open its exact historical process',()=>{
  const h=harness();h.click('experiments');h.nodes.get('#main-scroll').scrollTop=190;
  h.click('experimentArtifact',{artifact:'googl-record-v1',task:'data-googl-cashflow',run:'googl-cashflow-r1'});
  assert.equal(h.controller.getState().view,'experiments');assert.equal(h.nodes.get('#main-scroll').scrollTop,190);
  h.click('artifactProcess',{task:'data-googl-cashflow',run:'googl-cashflow-r1'});
  const state=h.controller.getState();assert.equal(state.runId,'googl-cashflow-r1');assert.equal(state.tab,'process');
  assert.equal(state.view,'tasks');assert.equal(state.artifactId,null);
});

test('composer draft survives role navigation; new Analysis workspace has explicit empty selection',()=>{
  const h=harness();
  h.emit('input',{dataset:{control:'draft'},value:'尚未发送'});
  h.click('role',{role:'analysis'});
  assert.equal(h.controller.getState().taskId,null);
  assert.match(h.nodes.get('.main-workspace').innerHTML,/选择一项任务/);
  h.click('role',{role:'data'});
  assert.ok(h.nodes.get('.main-workspace').innerHTML.includes('尚未发送'));
  h.controller.dispose();assert.equal(h.listeners.size,0);
});

test('Agent list exposes separate selection and configuration controls in both languages',()=>{
  for(const lang of ['zh','en']) {
    const html=renderLayout({...createState(DEMO),lang},DEMO);
    assert.ok(!html.includes('data-control="role"'));
    for(const role of DEMO.roles) {
      assert.ok(html.includes(`data-action="role" data-role="${role.id}"`));
      assert.ok(html.includes(`data-action="agentSettings" data-role="${role.id}"`));
    }
  }
});

test('viewing another Agent configuration retains task, review draft, output and scroll context',()=>{
  const h=harness();h.click('tab',{value:'review'});
  h.emit('input',{name:'note',value:'核对期间',closest:()=>h.form('review',{})});
  h.click('artifact',{artifact:'googl-record-v2'});
  const before=h.controller.getState();h.nodes.get('#main-scroll').scrollTop=142;
  h.click('agentSettings',{role:'analysis'});
  let state=h.controller.getState();
  assert.equal(state.role,before.role);assert.equal(state.taskId,before.taskId);assert.equal(state.runId,before.runId);
  assert.equal(state.settingsRoleId,'analysis');assert.equal(state.artifactId,before.artifactId);
  assert.deepEqual(state.reviewDrafts,before.reviewDrafts);assert.equal(h.nodes.get('#main-scroll').scrollTop,142);
  let html=h.nodes.get('.inspector').innerHTML;
  assert.match(html,/Analysis Agent/);assert.match(html,/Demo Research Model/);assert.ok(!html.includes('Demo Model A'));
  assert.match(html,/尚未登记提示词正文/);assert.ok(!html.includes('<form'));
  h.click('language');assert.match(h.nodes.get('.inspector').innerHTML,/Read only/);
  h.emit('keydown',{}, {key:'Escape'});
  state=h.controller.getState();assert.equal(state.settingsRoleId,null);assert.equal(state.artifactId,'googl-record-v2');
  assert.equal(h.nodes.get('#main-scroll').scrollTop,142);
  assert.equal(state.pendingRuns.length,0);
});

test('Agent selection changes only on its list button and closes settings',()=>{
  const h=harness();h.click('agentSettings',{role:'analysis'});
  h.click('role',{role:'analysis'});
  assert.equal(h.controller.getState().role,'analysis');assert.equal(h.controller.getState().taskId,null);
  assert.equal(h.controller.getState().settingsRoleId,null);
  h.click('role',{role:'data'});h.click('tab',{value:'process'});
  const taskId=h.controller.getState().taskId;
  h.click('role',{role:'data'});
  assert.equal(h.controller.getState().taskId,taskId);assert.equal(h.controller.getState().tab,'process');
});

test('configuration scope rejects unknown Agents and ordinary navigation clears stale settings',()=>{
  const initial=createState(DEMO);
  assert.throws(()=>reduce(initial,{type:'openAgentSettings',role:'missing'},DEMO),/Unknown role/);
  const settings=reduce(initial,{type:'openAgentSettings',role:'analysis'},DEMO);
  for(const action of [{type:'selectTask',taskId:'data-msft-report'},{type:'selectRun',runId:'googl-cashflow-r1'},{type:'setView',view:'experiments'},{type:'openArtifact',artifactId:'googl-record-v2'}]) {
    assert.equal(reduce(settings,action,DEMO).settingsRoleId,null);
  }
});
