const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const WORKFLOW_COLUMNS=['collected','working','recorded'];
export const WORKFLOW_TASKS=[
 {id:'source-map',title:['补齐案例出处','Complete case references'],type:['资料','Sources'],description:['记录客户案例的原始链接、发布日期与交互用途，保留未确认项。','Record original case links, publication dates and interaction purpose; keep unknowns explicit.'],column:'collected'},
 {id:'caption-study',title:['整理图注层级','Study caption hierarchy'],type:['编辑','Editorial'],description:['比较正文图注、媒体编号与来源说明的层级，形成可复用排版规则。','Compare captions, media numbering and source notes to form reusable composition rules.'],column:'collected'},
 {id:'reading-check',title:['检查阅读页键盘路径','Check reader keyboard navigation'],type:['交互','Interaction'],description:['从目录进入正文媒体，再打开与关闭详情，检查焦点返回到原操作。','Navigate from contents to media, open and close detail, and check focus returns to the initiating control.'],column:'working'},
 {id:'finance-scope',title:['定义财务对照范围','Define financial comparison scope'],type:['内容','Content'],description:['写清期间、单位、分母和缺失数据；模拟数据不代表投资判断。','State period, unit, denominator and missing data; sample data does not constitute an investment judgment.'],column:'working'},
 {id:'pdf-rules',title:['记录双语 PDF 规则','Document bilingual PDF rules'],type:['排版','Typography'],description:['把字体角色、换行、表格和页脚规则归入组件说明。此状态只表示设计记录，不代表生产验收。','Document font roles, line wrapping, tables and footers. This column marks design notes, not production acceptance.'],column:'recorded'},
 {id:'media-window',title:['归档展开媒体用法','Record expandable media patterns'],type:['组件','Components'],description:['保存打开、关闭、播放与状态保留的接口说明及适用边界。','Save the API and boundaries for opening, closing, playback and retained state.'],column:'recorded'}
];
export function createWorkflowState(){return {tasks:WORKFLOW_TASKS.map(task=>({...task,title:[...task.title],type:[...task.type],description:[...task.description]}))};}
export function validateWorkflowState(state){
 if(!state||!Array.isArray(state.tasks))throw new TypeError('Workflow state requires a tasks array');
 const ids=new Set();
 for(const task of state.tasks){
  if(!task||typeof task.id!=='string'||!/^[a-zA-Z0-9_-]+$/.test(task.id)||ids.has(task.id))throw new TypeError('Task identities must be unique safe strings');
  ids.add(task.id);
  if(!WORKFLOW_COLUMNS.includes(task.column))throw new TypeError('Unknown workflow column');
  for(const key of ['title','type','description'])if(!Array.isArray(task[key])||task[key].length!==2||task[key].some(v=>typeof v!=='string'||!v.trim()))throw new TypeError(`Task ${key} requires Chinese and English text`);
 }
 return state;
}
const copy=state=>({tasks:state.tasks.map(t=>({...t,title:[...t.title],type:[...t.type],description:[...t.description]}))});
export function moveTask(state,id,target){
 validateWorkflowState(state);
 if(!WORKFLOW_COLUMNS.includes(target))throw new TypeError('Unknown target column');
 if(!state.tasks.some(t=>t.id===id))throw new TypeError('Unknown task identity');
 const next=copy(state);next.tasks.find(t=>t.id===id).column=target;return next;
}
export function workflowCounts(state){validateWorkflowState(state);return Object.fromEntries(WORKFLOW_COLUMNS.map(c=>[c,state.tasks.filter(t=>t.column===c).length]));}
let serial=0;
export function mountWorkflowBoard(host,{tr,language='zh',state}={}){
 if(!host||typeof host.append!=='function')throw new TypeError('Workflow host required');
 if(!['zh','en'].includes(language))throw new TypeError('Unsupported workflow language');
 const t=typeof tr==='function'?tr:(zh,en)=>language==='en'?en:zh;
 let current=copy(validateWorkflowState(state===undefined?createWorkflowState():state));
 const prefix=`workflow-${++serial}`;const root=document.createElement('section');root.className='workflow-board';
 const columns=[t('待整理','Collected'),t('进行中','In progress'),t('已记录','Recorded')];
 let dialog=null,opener=null;
 function closeDialog(){if(dialog){dialog.close();dialog.remove();dialog=null;}if(opener?.isConnected)opener.focus();opener=null;}
 function openDetail(id,button){
  const task=current.tasks.find(v=>v.id===id);if(!task)return;
  if(dialog)closeDialog();opener=button;
  dialog=document.createElement('dialog');dialog.className='workflow-dialog';dialog.setAttribute('aria-labelledby',`${prefix}-detail-title`);
  dialog.innerHTML=`<div class="workflow-dialog-heading"><span>${esc(t(...task.type))}</span><button type="button" data-close aria-label="${esc(t('关闭详情','Close detail'))}">×</button></div><h3 id="${prefix}-detail-title">${esc(t(...task.title))}</h3><p>${esc(t(...task.description))}</p><dl><dt>${esc(t('当前列','Current column'))}</dt><dd>${esc(columns[WORKFLOW_COLUMNS.indexOf(task.column)])}</dd></dl><p class="workflow-session-note">${esc(t('模拟设计工作项。移列只保留在当前页面会话中。','Sample design task. Moves remain in this page session only.'))}</p>`;
  root.append(dialog);dialog.querySelector('[data-close]').onclick=closeDialog;dialog.addEventListener('cancel',e=>{e.preventDefault();closeDialog();});dialog.showModal();
 }
 function render(focus){
  const counts=workflowCounts(current);
  root.innerHTML=`<header class="workflow-heading"><div><span class="workflow-eyebrow">${esc(t('运营协作 · 模拟工作项','OPERATIONS · SAMPLE TASKS'))}</span><h3>${esc(t('让下一步有明确的位置。','A clear place for the next step.'))}</h3></div><p>${esc(t('用列状态协调设计工作。可打开详情，或用箭头移到相邻列；变更仅在当前页面会话内保留。','Coordinate design tasks by column. Open detail or move to a neighbouring column using arrows. Changes remain in this page session.'))}</p></header><div class="workflow-columns">${WORKFLOW_COLUMNS.map((column,i)=>`<section class="workflow-column" aria-labelledby="${prefix}-${column}"><header><h4 id="${prefix}-${column}">${esc(columns[i])}</h4><span aria-label="${esc(t('工作项数量','Task count'))}">${counts[column]}</span></header><div class="workflow-task-list">${current.tasks.filter(task=>task.column===column).map(task=>`<article class="workflow-task" data-task-id="${task.id}"><span class="workflow-type">${esc(t(...task.type))}</span><button class="workflow-task-title" data-detail="${task.id}">${esc(t(...task.title))}<span aria-hidden="true">↗</span></button><p>${esc(t(...task.description))}</p><div class="workflow-moves"><button type="button" data-move="${task.id}" data-target="${WORKFLOW_COLUMNS[i-1]||''}" ${i===0?'disabled':''} aria-label="${esc(i===0?t('已在首列','Already in first column'):t('移至','Move to')+' '+columns[i-1])}">←</button><span>${esc(t('移列','Move'))}</span><button type="button" data-move="${task.id}" data-target="${WORKFLOW_COLUMNS[i+1]||''}" ${i===2?'disabled':''} aria-label="${esc(i===2?t('已在末列','Already in final column'):t('移至','Move to')+' '+columns[i+1])}">→</button></div></article>`).join('')||`<p class="workflow-empty">${esc(t('暂无工作项','No tasks here'))}</p>`}</div></section>`).join('')}</div><p class="workflow-live" role="status" aria-live="polite"></p>`;
  root.querySelectorAll('[data-detail]').forEach(button=>button.onclick=()=>openDetail(button.dataset.detail,button));
  root.querySelectorAll('[data-move]').forEach(button=>button.onclick=()=>{
   const id=button.dataset.move,target=button.dataset.target;current=moveTask(current,id,target);render(id);
   const task=current.tasks.find(v=>v.id===id);root.querySelector('.workflow-live').textContent=t(...task.title)+' · '+t('已移至','Moved to')+' '+columns[WORKFLOW_COLUMNS.indexOf(target)];
  });
  if(focus)root.querySelector(`[data-detail="${focus}"]`)?.focus();
 }
 host.append(root);render();
 return {getState(){return copy(current);},destroy(){if(dialog){dialog.close();dialog.remove();dialog=null;}root.remove();}};
}
