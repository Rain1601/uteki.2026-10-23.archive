import { DEMO } from './demo-data.mjs';
import { createState, reduce } from './model.mjs';
import { renderLayout, renderSidebar, renderMain, renderInspector, escapeHTML } from './render.mjs';

export function createController(root, data=DEMO, environment=globalThis) {
  let state=createState(data);
  const scrollPositions=new Map();
  let artifactOpener=null, settingsOpener=null, toastTimer=null;
  const document=environment.document;
  const key=()=>state.view==='experiments'?'experiments':[state.view,state.taskId,state.runId,state.tab].join('|');
  const message=(zh,en)=>state.lang==='en'?en:zh;

  function rememberScroll() {
    const scroll=root.querySelector('#main-scroll');
    if(scroll)scrollPositions.set(key(),scroll.scrollTop);
  }
  function descriptor(element) {
    if(!element?.dataset)return null;
    return Object.fromEntries(['action','artifact','task','run','role','value','control','criterion'].filter(k=>element.dataset[k]!==undefined).map(k=>[k,element.dataset[k]]));
  }
  function focusDescriptor(value) {
    if(!value || !Object.keys(value).length)return;
    const candidate=[...root.querySelectorAll('[data-action], [data-control]')].find(element=>Object.entries(value).every(([key,value])=>element.dataset[key]===value));
    candidate?.focus({preventScroll:true});
  }
  function toast(content) {
    const element=root.querySelector('#toast');
    if(!element)return;
    environment.clearTimeout(toastTimer);
    element.textContent=content; element.hidden=false;
    toastTimer=environment.setTimeout(()=>{element.hidden=true;},5500);
  }
  function paint({focus=null, selection=null}={}) {
    const studio=root.querySelector('.studio');
    if(!studio)root.innerHTML=renderLayout(state,data);
    else {
      studio.classList.toggle('has-inspector',Boolean(state.artifactId || state.settingsRoleId));
      root.querySelector('.sidebar').innerHTML=renderSidebar(state,data);
      root.querySelector('.main-workspace').innerHTML=renderMain(state,data);
      const inspector=root.querySelector('.inspector');
      inspector.hidden=!(state.artifactId || state.settingsRoleId);
      inspector.setAttribute?.('aria-label',state.settingsRoleId?message('Agent 配置','Agent configuration'):message('产物检查','Artifact inspector'));
      inspector.innerHTML=renderInspector(state,data);
    }
    if(document)document.documentElement.lang=state.lang==='zh'?'zh-CN':'en';
    const scroll=root.querySelector('#main-scroll');
    if(scroll)scroll.scrollTop=scrollPositions.get(key()) || 0;
    focusDescriptor(focus);
    if(selection&&document?.activeElement?.setSelectionRange) {
      try {document.activeElement.setSelectionRange(...selection);} catch {}
    }
  }
  function dispatch(action, options={}) {
    rememberScroll();
    state=reduce(state,action,data);
    if(!['setDraft','setReviewDraft'].includes(action.type))paint(options);
    return state;
  }
  function selectTaskRun(taskId,runId) {
    state=reduce(state,{type:'selectTask',taskId},data);
    if(runId)state=reduce(state,{type:'selectRun',runId},data);
    state=reduce(state,{type:'setTab',tab:'process'},data);
  }
  function click(event) {
    const target=event.target.closest?.('[data-action]');
    if(!target||!root.contains(target))return;
    const value=target.dataset;
    try {
      switch(value.action) {
        case 'role': dispatch({type:'selectRole',role:value.role},{focus:descriptor(target)}); break;
        case 'agentSettings':
          settingsOpener=descriptor(target);
          if(state.settingsRoleId===value.role)dispatch({type:'closeAgentSettings'},{focus:settingsOpener});
          else {
            dispatch({type:'openAgentSettings',role:value.role});
            root.querySelector('.inspector-body')?.focus({preventScroll:true});
          }
          break;
        case 'closeAgentSettings': dispatch({type:'closeAgentSettings'},{focus:settingsOpener}); break;
        case 'task': dispatch({type:'selectTask',taskId:value.task}); break;
        case 'filter': dispatch({type:'setFilter',statusFilter:value.value},{focus:descriptor(target)}); break;
        case 'tab': dispatch({type:'setTab',tab:value.value},{focus:descriptor(target)}); break;
        case 'experiments': dispatch({type:'setView',view:'experiments'}); break;
        case 'language': dispatch({type:'setLanguage',lang:state.lang==='zh'?'en':'zh'},{focus:descriptor(target)}); break;
        case 'artifact':
          artifactOpener=descriptor(target);
          dispatch({type:'openArtifact',artifactId:value.artifact});
          root.querySelector('.inspector-body')?.focus({preventScroll:true});
          break;
        case 'experimentArtifact':
          artifactOpener=descriptor(target);
          dispatch({type:'openArtifact',artifactId:value.artifact,taskId:value.task,runId:value.run});
          root.querySelector('.inspector-body')?.focus({preventScroll:true});
          break;
        case 'closeArtifact': dispatch({type:'closeArtifact'},{focus:artifactOpener}); break;
        case 'artifactProcess':
          rememberScroll();
          selectTaskRun(value.task,value.run);
          paint();
          break;
        case 'about': toast(message('独立交互 Demo：示例数据；评审与追加要求仅保留在当前页面，刷新后清空。','Standalone interaction demo: sample data; reviews and instructions stay in this page and clear on refresh.')); break;
      }
    } catch(error) {toast(message('无法执行：','Cannot perform action: ')+error.message);}
  }
  function change(event) {
    const target=event.target;
    if(target.name==='verdict') { updateReviewDraft(target); return; }
    const actions={run:()=>({type:'selectRun',runId:target.value})};
    const makeAction=actions[target.dataset?.control];
    if(!makeAction)return;
    try {dispatch(makeAction(),{focus:descriptor(target)});} catch(error) {toast(error.message);}
  }
  function input(event) {
    const target=event.target;
    try {
      if(target.dataset?.control==='search')dispatch({type:'setSearch',search:target.value},{focus:descriptor(target),selection:[target.selectionStart,target.selectionEnd]});
      if(target.dataset?.control==='draft')dispatch({type:'setDraft',text:target.value});
      if(target.name==='note')updateReviewDraft(target);
    } catch(error) {toast(error.message);}
  }
  function updateReviewDraft(target) {
    const form=target.closest?.('form[data-form="review"]');
    if(!form)return;
    try {dispatch({type:'setReviewDraft',criterionId:form.dataset.criterion,[target.name]:target.value});}
    catch(error) {toast(error.message);}
  }
  function submit(event) {
    const form=event.target;
    if(!form.dataset?.form)return;
    event.preventDefault();
    try {
      if(form.dataset.form==='instruction') {
        const text=form.elements.namedItem('instruction').value;
        dispatch({type:'appendInstruction',text});
        const scroll=root.querySelector('#main-scroll'); if(scroll)scroll.scrollTop=scroll.scrollHeight;
        toast(message('追加要求已记录，新尝试待执行。Demo 没有调用模型。','Instruction recorded; the new attempt is pending. No model was called.'));
      } else if(form.dataset.form==='review') {
        dispatch({type:'saveReview',criterionId:form.dataset.criterion,verdict:form.elements.namedItem('verdict').value,note:form.elements.namedItem('note').value});
        toast(message('评审意见已在本页保存；没有触发执行。','Review saved in this page; no execution was triggered.'));
      }
    } catch(error) {toast(error.message);}
  }
  function keydown(event) {
    if(event.key==='Escape'&&state.settingsRoleId) {
      event.preventDefault(); dispatch({type:'closeAgentSettings'},{focus:settingsOpener}); return;
    }
    if(event.key==='Escape'&&state.artifactId) {
      event.preventDefault(); dispatch({type:'closeArtifact'},{focus:artifactOpener}); return;
    }
    if(event.target?.dataset?.action==='tab'&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
      event.preventDefault();
      const tabs=['result','process','review'];
      const index=tabs.indexOf(state.tab);
      const next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;
      dispatch({type:'setTab',tab:tabs[next]},{focus:{action:'tab',value:tabs[next]}});
    }
  }
  paint();
  root.addEventListener('click',click);
  root.addEventListener('change',change);
  root.addEventListener('input',input);
  root.addEventListener('submit',submit);
  root.addEventListener('keydown',keydown);
  return {getState:()=>state,dispatch,dispose:()=>{
    for(const [name,handler] of Object.entries({click,change,input,submit,keydown}))root.removeEventListener(name,handler);
    environment.clearTimeout(toastTimer);
  }};
}

if(typeof document!=='undefined') {
  const root=document.getElementById('app');
  if(root) {
    try {createController(root);} catch(error) {
      root.innerHTML=`<div class="empty-state"><h1>Demo 未能加载 / Demo unavailable</h1><p>${escapeHTML(error.message)}</p><p>请使用本地 HTTP 预览地址。 / Open the local HTTP preview.</p></div>`;
    }
  }
}
