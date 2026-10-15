import {applyPalette} from './palette-presets.mjs';
import {Header,esc} from './components.mjs';
import {Card} from './compound-components.mjs';
import {componentCSS} from './tokens.mjs?v=1';
import {REPORT_SPECIMENS} from './report-content.mjs?v=0.22';
import {readSession,writeSession,reportLibraryRows} from './reading-session.mjs';
const reports=REPORT_SPECIMENS,ids=reports.map(r=>r.id),$=s=>document.querySelector(s);
let storage;try{storage=window.sessionStorage;}catch{storage={getItem(){throw Error('Unavailable')},setItem(){throw Error('Unavailable')}};}
const loaded=readSession(storage,ids);let session=loaded.value,storageStatus=loaded.status,frame=0;
const params=new URLSearchParams(location.search);if(['zh','en'].includes(params.get('language')))session.appearance.language=params.get('language');if(['paper','paper-night','mineral','plum'].includes(params.get('palette')))session.appearance.palette=params.get('palette');
const tr=(zh,en)=>session.appearance.language==='zh'?zh:en,text=v=>v[session.appearance.language];
const href=(report,chapter='')=>`./research-report.html?report=${encodeURIComponent(report.id)}${chapter?`#${encodeURIComponent(chapter)}`:''}`;
function save(){const result=writeSession(storage,session,ids);if(result.status==='unavailable')storageStatus='unavailable';notice();}
function notice(){ $('#library-storage').textContent=storageStatus==='unavailable'?tr('当前无法保存本标签页阅读状态；离开页面后可能无法恢复。','Reading state cannot be stored in this tab; leaving the page may lose your position.'):storageStatus==='invalid'?tr('先前阅读记录格式无效。当前从空状态开始；新的操作将保存当前状态。','The previous reading record is invalid. This page starts empty; new actions will save the current state.') :''; }
function labels(){
 document.documentElement.lang=session.appearance.language==='zh'?'zh-CN':'en';document.body.style.cssText=componentCSS();applyPalette(document.body,session.appearance.palette);document.body.style.setProperty('color-scheme',session.appearance.palette==='paper-night'?'dark':'light');
 $('#library-header').innerHTML=Header({brand:'UTEKI / EDITIONS',brandHref:'./workspace.html',label:tr('辅助导航','Supporting navigation'),links:[{href:'./workspace.html?view=library',label:tr('研究工作台','Research desk')},{href:'./',label:tr('组件样册','Components')}]});
 $('#library-title').textContent=tr('报告，从这里读起。','A place to begin reading.');$('#library-deck').textContent=tr('先浏览摘要，再沿着章节理解。每份报告保留自己的阅读位置，核对之后可以接着读。','Scan the brief, then follow the chapters. Each report keeps its own reading position, so you can return after checking the evidence.');
 $('#query-label').textContent=tr('搜索报告','Search reports');$('#library-query').placeholder=tr('标题或摘要…','Title or brief…');$('#filter-label').textContent=tr('阅读状态','Reading state');$('#sort-label').textContent=tr('排列','Order');
 $('#library-filter').innerHTML=[['all',tr('全部','All')],['unread',tr('未开始','Not started')],['started',tr('阅读中','In progress')],['completed',tr('已标记读完','Marked read')]].map(([v,label])=>`<option value="${v}">${label}</option>`).join('');
 $('#library-sort').innerHTML=`<option value="date-desc">${tr('最新在前','Latest first')}</option><option value="title-asc">${tr('标题顺序','By title')}</option>`;
 $('#library-reset').textContent=tr('清除筛选','Clear filters');$('#library-query').value=session.library.query;$('#library-filter').value=session.library.filter;$('#library-sort').value=session.library.sort;$('#library-palette').value=session.appearance.palette;$('#library-language').value=session.appearance.language;
 $('#library-scope').textContent=tr('原创设计报告样稿 · 阅读状态仅保留在当前标签页','Authored design report specimens · Reading state is local to this tab');$('#library-principles').textContent=tr('共用设计原则 ↗','Shared design principles ↗');notice();
}
function renderResults(){
 const list=reportLibraryRows(reports,session.library,session.reports,session.appearance.language);$('#library-count').textContent=tr(`${list.length} / ${reports.length} 份报告`,`${list.length} / ${reports.length} reports`);
 $('#library-results').innerHTML=list.length?list.map(report=>{
  const reading=session.reports[report.id],status=reading?.status??'unread',chapter=report.sections.find(s=>s.id===reading?.state.chapterId);
  const statusLabel=status==='completed'?tr('已标记读完','Marked read'):status==='started'?tr('阅读中','In progress'):tr('未开始','Not started');
  return `<div class="rl-report">${Card({id:`card-${report.id}`,title:text(report.title),description:text(report.deck),eyebrow:tr('设计研究 · 原创样稿','DESIGN RESEARCH · AUTHORED SPECIMEN'),meta:`${report.date} · ${report.sections.length} ${tr('章','chapters')}`,status:status==='completed'?'completed':status==='started'?'running':'idle',statusLabel})}<p class="rl-meta">${esc(chapter?tr('上次读到：','Last read: ')+text(chapter.title):text(report.scope))}</p><details><summary>${tr('浏览摘要','Preview the brief')} · ${report.summaries.length}</summary><ol>${report.summaries.map(s=>`<li><a data-report="${report.id}" href="${href(report,s.sectionId)}">${esc(text(s.text))}</a></li>`).join('')}</ol></details><a class="rl-read" id="open-${report.id}" data-report="${report.id}" href="${href(report)}">${tr(status==='unread'?'打开报告':'继续阅读',status==='unread'?'Open report':'Continue reading')} <span aria-hidden="true">→</span></a></div>`;
 }).join(''):`<div class="rl-empty"><p>${tr('当前范围没有报告。','No reports match this scope.')}</p><button class="button secondary" data-clear>${tr('清除筛选','Clear filters')}</button></div>`;
 $('#library-results').querySelectorAll('[data-report]').forEach(a=>a.addEventListener('click',()=>{session.library.focus=a.dataset.report;capture();save();}));
 $('#library-results').querySelector('[data-clear]')?.addEventListener('click',reset);
}
function capture(){session.library.top=document.scrollingElement.scrollTop;session.library.left=document.scrollingElement.scrollLeft;}
function reset(){session.library={...session.library,query:'',filter:'all',sort:'date-desc',focus:null};labels();renderResults();save();$('#library-query').focus({preventScroll:true});}
function restore(){const {top,left,focus}=session.library;document.scrollingElement.scrollTop=top;document.scrollingElement.scrollLeft=left;if(focus)$(`#open-${focus}`)?.focus({preventScroll:true});}
$('#library-query').addEventListener('input',e=>{if(e.isComposing)return;session.library.query=e.target.value;renderResults();save();});
$('#library-query').addEventListener('compositionend',e=>{session.library.query=e.target.value;renderResults();save();});
for(const [selector,key] of [['#library-filter','filter'],['#library-sort','sort']])$(selector).addEventListener('change',e=>{session.library[key]=e.target.value;renderResults();save();});
$('#library-reset').addEventListener('click',reset);
for(const [selector,key] of [['#library-palette','palette'],['#library-language','language']])$(selector).addEventListener('change',e=>{capture();session.appearance[key]=e.target.value;labels();renderResults();restore();save();$(selector).focus({preventScroll:true});});
document.querySelector('form').addEventListener('submit',e=>e.preventDefault());
document.addEventListener('scroll',()=>{if(frame)return;frame=requestAnimationFrame(()=>{frame=0;capture();save();});},{passive:true});
addEventListener('pagehide',()=>{capture();save();});
addEventListener('pageshow',e=>{if(!e.persisted)return;const latest=readSession(storage,ids);session=latest.value;storageStatus=latest.status;labels();renderResults();restore();});
labels();renderResults();requestAnimationFrame(restore);
