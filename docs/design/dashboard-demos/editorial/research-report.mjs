import {applyPalette} from './palette-presets.mjs';
import {Header} from './components.mjs';
import {componentCSS} from './tokens.mjs?v=1';
import {mountReportReader,normalizeReportState} from './report-reader.mjs?v=0.22';
import {REPORT_SPECIMENS,getReportSpecimen} from './report-content.mjs?v=0.22';
import {readSession,writeSession,updateReadingRecord} from './reading-session.mjs';
const params=new URLSearchParams(location.search),ids=REPORT_SPECIMENS.map(r=>r.id);
const report=getReportSpecimen(params.has('report')?params.get('report'):'editorial-reading');
let storage;try{storage=window.sessionStorage;}catch{storage={getItem(){throw Error('Unavailable')},setItem(){throw Error('Unavailable')}};}
const loaded=readSession(storage,ids);let session=loaded.value,storageStatus=loaded.status;
let language=['zh','en'].includes(params.get('language'))?params.get('language'):session.appearance.language;
let palette=['paper','paper-night','mineral','plum'].includes(params.get('palette'))?params.get('palette'):session.appearance.palette;
let reader;
const host=document.querySelector('#report-host'),scrollContainer=document.scrollingElement;
const tr=(zh,en)=>language==='zh'?zh:en;
function notice(){
 document.querySelector('#report-scope').textContent=storageStatus==='unavailable'?tr('无法保存本标签页阅读位置；当前交互仍可使用。','Reading position cannot be saved in this tab; the current interactions remain available.'):storageStatus==='invalid'?tr('旧阅读记录无效，当前从报告起点开始。','The previous reading record is invalid; this report starts from its beginning.'):tr('原创报告样稿 · 阅读记录仅在本标签页保存','Authored report specimen · Reading state is stored only in this tab');
}
function save(state){
 if(!report)return;
 session.appearance={language,palette};
 if(state)session=updateReadingRecord(session,report.id,state,{status:session.reports[report.id]?.status??'started'},ids);
 const result=writeSession(storage,session,ids);if(result.status==='unavailable')storageStatus='unavailable';notice();
}
function statusLabel(){document.querySelector('#report-read-status').textContent=session.reports[report?.id]?.status==='completed'?tr('已标记读完 · 改为阅读中','Marked read · Resume reading'):tr('标记读完','Mark as read');}
function render(){
 let state=reader?.getState();
 if(!reader&&!location.hash&&report&&session.reports[report.id]){try{state=normalizeReportState(session.reports[report.id].state,report);}catch{storageStatus='invalid';delete session.reports[report.id];}}
 reader?.destroy();document.documentElement.lang=language==='zh'?'zh-CN':'en';document.body.style.cssText=componentCSS();applyAppearance();
 document.querySelector('#report-header').innerHTML=Header({brand:'UTEKI / EDITIONS',brandHref:'./workspace.html',label:tr('辅助导航','Supporting navigation'),links:[{href:'./report-library.html',label:tr('返回报告列表','Back to reports')},{href:'./',label:tr('组件样册','Components')}],action:{id:'report-theme-toggle',label:tr('夜间模式','Dark mode')}});syncThemeButton();
 document.querySelector('#palette-label').textContent=tr('配色','Palette');document.querySelector('#principles-link').textContent=tr('共用设计原则 ↗','Shared design principles ↗');document.querySelector('#report-palette').value=palette;document.querySelector('#report-language').value=language;notice();statusLabel();
 if(!report){document.querySelector('#report-read-status').disabled=true;host.innerHTML=`<section class="report-reader"><h1>${tr('没有这份报告','Report not found')}</h1><p>${tr('报告身份未知，未替换为其他报告。','This report identity is unknown; no other report was substituted.')}</p><a href="./report-library.html">${tr('返回报告列表','Back to reports')}</a></section>`;return;}
 document.querySelector('#report-edition').textContent=`RESEARCH EDITION / ${String(ids.indexOf(report.id)+1).padStart(2,'0')}`;
 document.title=`${report.title[language]} · Uteki Editions`;
 reader=mountReportReader(host,{report,tr,language,scrollContainer,state,sourcePanelAction:{label:tr('切换明暗','Switch light / dark'),onClick:()=>changePalette(palette==='paper-night'?'paper':'paper-night')},onStateChange:state=>save(state)});
 if(!state&&!location.hash)save(reader.getState());
}
function syncThemeButton(){const button=document.querySelector('[data-action="report-theme-toggle"]');if(button){button.textContent=palette==='paper-night'?tr('日间模式','Light mode'):tr('夜间模式','Dark mode');button.setAttribute('aria-pressed',String(palette==='paper-night'));}}
function applyAppearance(){applyPalette(document.body,palette);document.body.style.setProperty('color-scheme',palette==='paper-night'?'dark':'light');document.querySelector('#report-palette').value=palette;syncThemeButton();}
function changePalette(value){palette=value;applyAppearance();const url=new URL(location.href);url.searchParams.set('palette',palette);history.replaceState(null,'',url);save(reader?.getState());}
document.querySelector('#report-palette').addEventListener('change',e=>changePalette(e.target.value));
document.querySelector('#report-header').addEventListener('click',e=>{if(e.target.closest('[data-action="report-theme-toggle"]'))changePalette(palette==='paper-night'?'paper':'paper-night');});
document.querySelector('#report-language').addEventListener('change',e=>{language=e.target.value;render();save(reader?.getState());document.querySelector('#report-language').focus({preventScroll:true});});
document.querySelector('#report-read-status').addEventListener('click',()=>{if(!reader)return;const status=session.reports[report.id]?.status==='completed'?'started':'completed';session=updateReadingRecord(session,report.id,reader.getState(),{status},ids);save();statusLabel();});
addEventListener('pagehide',()=>save(reader?.getState()));
render();
