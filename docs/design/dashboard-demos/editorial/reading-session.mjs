/** Per-tab navigation metadata only. No report bodies, files or Agent inputs are stored. */
export const READING_SESSION_KEY='uteki-editorial-reading-v1';
const plain=v=>v&&typeof v==='object'&&!Array.isArray(v);
const finite=v=>Number.isFinite(v)&&v>=0;
const id=v=>typeof v==='string'&&/^[A-Za-z][A-Za-z0-9_-]*$/.test(v);
export function createReadingSession(){return {version:1,appearance:{language:'zh',palette:'paper'},library:{query:'',filter:'all',sort:'date-desc',top:0,left:0,focus:null},reports:{}};}
export function validateReadingSession(value,reportIds){
 if(!Array.isArray(reportIds)||new Set(reportIds).size!==reportIds.length||reportIds.some(v=>!id(v)))throw new TypeError('Unique report identities required');
 if(!plain(value)||value.version!==1||!plain(value.appearance)||!['zh','en'].includes(value.appearance.language)||!['paper','paper-night','mineral','plum'].includes(value.appearance.palette)||!plain(value.library)||!plain(value.reports))throw new TypeError('Supported reading session required');
 const {library}=value;
 if(typeof library.query!=='string'||library.query.length>500||!['all','unread','started','completed'].includes(library.filter)||!['date-desc','title-asc'].includes(library.sort)||!finite(library.top)||!finite(library.left)||(library.focus!==null&&!reportIds.includes(library.focus)))throw new TypeError('Valid report library state required');
 const reports={};
 for(const [reportId,record] of Object.entries(value.reports)){
  if(!reportIds.includes(reportId)||!plain(record)||!['started','completed'].includes(record.status)||!Number.isSafeInteger(record.updatedAt)||record.updatedAt<0||!plain(record.state)||!finite(record.state.top)||!finite(record.state.left))throw new TypeError('Valid report reading record required');
  if(record.state.reportId!==undefined&&record.state.reportId!==reportId)throw new TypeError('Reading state must match its report');
  if(record.state.chapterId!==undefined&&record.state.chapterId!==null&&!id(record.state.chapterId))throw new TypeError('Valid chapter identity required');
  if(record.state.offset!==undefined&&!Number.isFinite(record.state.offset))throw new TypeError('Finite chapter offset required');
  if(record.state.figureView!==undefined&&!['chart','data'].includes(record.state.figureView))throw new TypeError('Valid figure view required');
  for(const key of ['figureViews','details']){
   if(record.state[key]!==undefined&&!plain(record.state[key]))throw new TypeError('Valid reading controls required');
   for(const [identity,item] of Object.entries(record.state[key]??{}))if(!id(identity)||(key==='figureViews'?!['chart','data'].includes(item):typeof item!=='boolean'))throw new TypeError('Valid reading control identity required');
  }
  reports[reportId]={status:record.status,updatedAt:record.updatedAt,state:JSON.parse(JSON.stringify(record.state))};
 }
 return {version:1,appearance:{...value.appearance},library:{...library},reports};
}
export function updateReadingRecord(session,reportId,state,{status='started',updatedAt=Date.now()}={},reportIds){
 const next=validateReadingSession(session,reportIds);
 next.reports[reportId]={state,status,updatedAt};
 return validateReadingSession(next,reportIds);
}
export function readSession(storage,reportIds){
 try{const raw=storage.getItem(READING_SESSION_KEY);if(raw===null)return {status:'empty',value:createReadingSession()};return {status:'saved',value:validateReadingSession(JSON.parse(raw),reportIds)};}
 catch(error){return {status:error instanceof SyntaxError||error instanceof TypeError?'invalid':'unavailable',value:createReadingSession()};}
}
export function writeSession(storage,session,reportIds){
 const value=validateReadingSession(session,reportIds);
 try{storage.setItem(READING_SESSION_KEY,JSON.stringify(value));return {status:'saved'};}catch{return {status:'unavailable'};}
}
export function reportLibraryRows(reports,library,reading={},language='zh'){
 if(!Array.isArray(reports)||reports.some(r=>!id(r.id)||!plain(r.title)||typeof r.title.zh!=='string'||typeof r.title.en!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(r.date??''))||new Set(reports.map(r=>r.id)).size!==reports.length)throw new TypeError('Explicit localized report catalog required');
 if(!plain(library)||typeof library.query!=='string'||!['all','unread','started','completed'].includes(library.filter)||!['date-desc','title-asc'].includes(library.sort)||!['zh','en'].includes(language))throw new TypeError('Valid catalog controls required');
 const query=library.query.trim().toLocaleLowerCase();
 return reports.filter(r=>(library.filter==='all'||(reading[r.id]?.status??'unread')===library.filter)&&(!query||[r.title.zh,r.title.en,r.deck?.zh,r.deck?.en,...(r.summaries??[]).flatMap(s=>[s.text?.zh,s.text?.en])].some(v=>typeof v==='string'&&v.toLocaleLowerCase().includes(query)))).sort((a,b)=>library.sort==='date-desc'?b.date.localeCompare(a.date)||a.id.localeCompare(b.id):a.title[language].localeCompare(b.title[language],language==='zh'?'zh-CN':'en')||a.id.localeCompare(b.id));
}
