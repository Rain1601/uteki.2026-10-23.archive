const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const periods=['quarter','ytd'];
export const PORTFOLIO_POSITIONS=Object.freeze([
 {id:'cedar',label:'Cedar Systems',weight:.35,returns:{quarter:12,ytd:18},forwardPE:24},
 {id:'harbor',label:'Harbor Materials',weight:.30,returns:{quarter:-6,ytd:4},forwardPE:13},
 {id:'lumen',label:'Lumen Services',weight:.25,returns:{quarter:8,ytd:-3},forwardPE:32},
 {id:'reserve',label:'Cash reserve',weight:.10,returns:{quarter:0,ytd:0},forwardPE:null}
].map(p=>Object.freeze({...p,returns:Object.freeze(p.returns)})));
export const PORTFOLIO_BENCHMARK=Object.freeze({label:'Synthetic reference basket',returns:Object.freeze({quarter:3.5,ytd:6})});
export function summarizePortfolio({positions,period,benchmark}={}){
 if(!periods.includes(period)||!Array.isArray(positions)||positions.length<2||positions.length>12)throw new TypeError('Explicit portfolio and supported period required');
 const ids=new Set();let weight=0,total=0;
 const entries=positions.map(p=>{
  if(!p||typeof p.id!=='string'||!/^[a-zA-Z0-9_-]+$/.test(p.id)||ids.has(p.id)||typeof p.label!=='string'||!p.label.trim())throw new TypeError('Unique position identity and label required');
  ids.add(p.id);
  if(!Number.isFinite(p.weight)||p.weight<0||!p.returns||periods.some(k=>!Number.isFinite(p.returns[k])||p.returns[k]<-100)||!(p.forwardPE===null||Number.isFinite(p.forwardPE)&&p.forwardPE>0))throw new TypeError('Invalid weight, returns, or forward PE');
  const contribution=p.weight*p.returns[period];weight+=p.weight;total+=contribution;
  if(!Number.isFinite(weight)||!Number.isFinite(total)||!Number.isFinite(contribution))throw new RangeError('Non-finite portfolio accumulation');
  return {...p,return:p.returns[period],contribution};
 });
 if(Math.abs(weight-1)>1e-9)throw new RangeError('Opening weights must sum to one');
 if(!benchmark||typeof benchmark.label!=='string'||!benchmark.label.trim()||!benchmark.returns||periods.some(k=>!Number.isFinite(benchmark.returns[k])||benchmark.returns[k]<-100))throw new TypeError('Explicit benchmark required');
 const reference=benchmark.returns[period],excess=total-reference;
 if(!Number.isFinite(excess))throw new RangeError('Non-finite excess return');
 return {period,entries,total,reference,excess,benchmarkLabel:benchmark.label,missingPE:entries.filter(p=>p.forwardPE===null)};
}
export function waterfallGeometry(entries,{height=210,top=28,bottom=174}={}){
 if(!Array.isArray(entries)||!entries.length||!Number.isFinite(height)||!Number.isFinite(top)||!Number.isFinite(bottom)||top<0||bottom<=top||height<bottom)throw new TypeError('Invalid waterfall geometry');
 let running=0;
 const bars=entries.map(p=>{if(!Number.isFinite(p.contribution))throw new TypeError('Finite contribution required');const start=running;running+=p.contribution;if(!Number.isFinite(running))throw new RangeError('Non-finite waterfall accumulation');return {id:p.id,start,end:running,value:p.contribution};});
 const extent=bars.flatMap(b=>[b.start,b.end]);let min=Math.min(0,...extent),max=Math.max(0,...extent);if(min===max){min=-1;max=1;}const pad=(max-min)*.15;min-=pad;max+=pad;if(!Number.isFinite(min)||!Number.isFinite(max)||!Number.isFinite(max-min))throw new RangeError('Non-finite waterfall scale');
 const y=v=>bottom-(v-min)/(max-min)*(bottom-top);
 return {total:running,min,max,zeroY:y(0),bars:bars.map(b=>({...b,y:Math.min(y(b.start),y(b.end)),height:Math.abs(y(b.end)-y(b.start)),startY:y(b.start),endY:y(b.end)})),totalY:Math.min(y(0),y(running)),totalHeight:Math.abs(y(running)-y(0))};
}
export function validatePortfolioViewState(state){
 if(state===undefined)return {period:'quarter',selected:null};
 if(!state||typeof state!=='object'||Array.isArray(state)||Object.keys(state).length!==2||Object.keys(state).some(k=>!['period','selected'].includes(k))||!periods.includes(state.period)||!(state.selected===null||PORTFOLIO_POSITIONS.some(p=>p.id===state.selected)))throw new TypeError('Explicit period and selected required in restored portfolio state');
 return {period:state.period,selected:state.selected};
}
export function movePortfolioSelection({ids,current,selected,direction}){
 if(!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length||!ids.includes(current)||!(selected===null||ids.includes(selected))||![-1,1].includes(direction))throw new TypeError('Invalid portfolio navigation state');
 const next=ids[(ids.indexOf(current)+direction+ids.length)%ids.length];
 return {focus:next,selected:selected===null?null:next};
}
let serial=0;
export function mountPortfolioWorkbench(host,{tr,language='en',state}={}){
 if(!host?.appendChild)throw new TypeError('Host required');
 if(!['zh','en'].includes(language))throw new TypeError('Unsupported portfolio language');
 const t=typeof tr==='function'?tr:(zh,en)=>language==='zh'?zh:en;
 let {period,selected}=validatePortfolioViewState(state);let hovered=null,focused=null;
 const root=document.createElement('section');root.className='portfolio-workbench';host.appendChild(root);const prefix=`portfolio-${++serial}`;
 const pct=v=>`${v>0?'+':''}${v.toFixed(2)}%`,pp=v=>`${v>0?'+':''}${v.toFixed(2)} pp`;
 function render(){
 const m=summarizePortfolio({positions:PORTFOLIO_POSITIONS,period,benchmark:PORTFOLIO_BENCHMARK}),g=waterfallGeometry(m.entries),step=80;
 const pe=m.entries.filter(p=>p.forwardPE!==null);const maxPE=Math.max(40,...pe.map(p=>p.forwardPE))*1.1;let lo=Math.min(0,...pe.map(p=>p.return))-4,hi=Math.max(0,...pe.map(p=>p.return))+4;
 const sx=v=>48+v/maxPE*312,sy=v=>174-(v-lo)/(hi-lo)*146;
 root.innerHTML=`<header class="portfolio-heading"><div><span class="portfolio-eyebrow">RESEARCH / 02</span><h2>${t('收益从哪里来。','Where returns come from.')}</h2><p>${t('固定期初权重，逐项对照收益贡献与估值。','Fixed opening weights. Read contribution alongside valuation.')}</p></div><label>${t('观察区间','Observation period')}<select data-portfolio-period><option value="quarter" ${period==='quarter'?'selected':''}>3M</option><option value="ytd" ${period==='ytd'?'selected':''}>YTD</option></select></label></header>
 <p class="portfolio-scope">${t('原创模拟组合 · 4 项资产 · 无期间资金流、再平衡或交易。','Original synthetic portfolio · 4 assets · no external flows, rebalancing, or trading.')}</p>
 <div class="portfolio-metrics">${[[t('组合收益','Portfolio return'),pct(m.total)],[t('模拟基准','Synthetic benchmark'),pct(m.reference)],[t('超额收益','Excess return'),pp(m.excess)]].map(([a,b])=>`<div><span>${a}</span><strong>${b}</strong></div>`).join('')}</div>
 <div class="portfolio-charts"><figure><figcaption><h3>${t('每项资产的贡献','Contribution by position')}</h3><span>${t('百分点 · 期初权重 × 区间收益','Percentage points · opening weight × return')}</span></figcaption><div class="portfolio-chart-stage"><svg viewBox="0 0 440 210" role="img" aria-label="${t('收益贡献瀑布图','Return contribution waterfall')}"><line class="portfolio-grid" x1="18" x2="425" y1="${g.zeroY}" y2="${g.zeroY}"/>${g.bars.map((b,i)=>`<g data-portfolio-mark="${b.id}"><rect class="portfolio-bar ${b.value<0?'negative':''}" x="${24+i*step}" y="${b.y}" width="44" height="${Math.max(1,b.height)}"/><text x="${46+i*step}" y="${Math.max(15,b.y-8)}" text-anchor="middle">${pp(b.value)}</text><text class="portfolio-axis" x="${46+i*step}" y="199" text-anchor="middle">${i+1}</text>${i<g.bars.length-1?`<line class="portfolio-connector" x1="${68+i*step}" x2="${104+i*step}" y1="${b.endY}" y2="${b.endY}"/>`:''}</g>`).join('')}<g class="portfolio-total"><rect x="362" y="${g.totalY}" width="44" height="${Math.max(1,g.totalHeight)}"/><text x="384" y="${Math.max(15,g.totalY-8)}" text-anchor="middle">${pp(m.total)}</text><text class="portfolio-axis" x="384" y="199" text-anchor="middle">${t('合计','Total')}</text></g></svg><div class="portfolio-waterfall-targets">${m.entries.map((p,i)=>`<button data-portfolio-target="${p.id}" style="left:${(24+i*step)/440*100}%;width:10%" aria-label="${esc(p.label)} ${pp(p.contribution)}"></button>`).join('')}</div></div></figure>
 <figure><figcaption><h3>${t('价格与表现','Valuation and performance')}</h3><span>${t('横轴预期市盈率 · 纵轴区间收益','Forward P/E on x · period return on y')}</span></figcaption><div class="portfolio-chart-stage"><svg viewBox="0 0 440 210" role="img" aria-label="${t('估值与收益散点图','Valuation and return scatter plot')}"><line class="portfolio-grid" x1="48" x2="360" y1="${sy(0)}" y2="${sy(0)}"/><line class="portfolio-grid" x1="48" x2="48" y1="28" y2="174"/>${[0,20,40].map(v=>`<text class="portfolio-axis" x="${sx(v)}" y="199" text-anchor="middle">${v}×</text>`).join('')}${[lo,0,hi].map(v=>`<text class="portfolio-axis" x="40" y="${sy(v)+4}" text-anchor="end">${v.toFixed(0)}%</text>`).join('')}${pe.map(p=>`<g data-portfolio-mark="${p.id}"><circle class="portfolio-dot" cx="${sx(p.forwardPE)}" cy="${sy(p.return)}" r="7"/><text x="${sx(p.forwardPE)+12}" y="${sy(p.return)+4}">${m.entries.indexOf(p)+1}</text></g>`).join('')}</svg><div class="portfolio-scatter-targets">${pe.map(p=>`<button data-portfolio-target="${p.id}" style="left:${sx(p.forwardPE)/440*100}%;top:${sy(p.return)/210*100}%" aria-label="${esc(p.label)} ${p.forwardPE}× ${pct(p.return)}"></button>`).join('')}</div></div><p class="portfolio-chart-note">${t('现金未定义市盈率，因此不绘制；明细仍完整保留。','Cash has no defined P/E and is omitted from the scatter, while retained in the ledger.')}</p></figure></div>
 <div class="portfolio-readout" aria-live="polite"><span data-portfolio-readout>${t('悬停或聚焦任一资产，图表与明细同步。','Hover or focus a position to link both charts and the ledger.')}</span><button data-portfolio-clear>${t('清除选择','Clear selection')}</button></div>
 <section class="portfolio-ledger"><h3>${t('持仓研究明细','Position research ledger')}</h3><div class="portfolio-ledger-layout ${selected?'has-detail':''}"><div class="portfolio-table-scroll"><table><thead><tr>${[t('资产','Position'),t('期初权重','Opening weight'),t('区间收益','Return'),t('贡献','Contribution'),t('预期市盈率','Forward P/E')].map(s=>`<th>${s}</th>`).join('')}</tr></thead><tbody>${m.entries.map((p,i)=>`<tr data-portfolio-row="${p.id}"><td><button data-portfolio-target="${p.id}" aria-expanded="${selected===p.id}"><span class="portfolio-position-number">0${i+1}</span>${esc(p.label)}</button></td><td>${(p.weight*100).toFixed(0)}%</td><td>${pct(p.return)}</td><td>${pp(p.contribution)}</td><td>${p.forwardPE===null?t('不适用','N/A'):`${p.forwardPE}×`}</td></tr>`).join('')}</tbody><tfoot><tr><td>${t('组合','Portfolio')}</td><td>100%</td><td>${pct(m.total)}</td><td>${pp(m.total)}</td><td>—</td></tr></tfoot></table></div>${selected?detail(m.entries.find(p=>p.id===selected)):''}</div></section>
 <details class="portfolio-method"><summary>${t('计算方法与范围','Method and scope')}</summary><p>${t('组合区间收益为期初权重与各项总收益率的加权和。贡献的单位为百分点；超额收益为组合收益减去显式模拟基准。3M 与 YTD 使用各自独立的固定期初权重示例，不串接期间。预期市盈率仅为模拟横轴数据，不用于推导建议。','Portfolio return is the sum of opening weight × position total return. Contributions and excess return use percentage points. Excess subtracts the explicit synthetic benchmark. 3M and YTD are separate fixed-opening-weight examples and are not chained. Forward P/E is synthetic axis data and does not imply recommendations.')}</p><p>${t('无真实证券、交易、投资建议或实测财报。所有资产与基准均为本组件原创模拟数据。','No real securities, transactions, investment advice, or reported financials. All assets and benchmark data are original synthetic examples.')}</p></details>`;
 function detail(p){return `<aside class="portfolio-detail" aria-labelledby="${prefix}-detail"><div><span>POSITION / ${esc(p.id.toUpperCase())}</span><button data-portfolio-close aria-label="${t('关闭资产详情','Close position details')}">×</button></div><h3 id="${prefix}-detail">${esc(p.label)}</h3><p>${period==='quarter'?'3M':'YTD'} · ${t('固定期初权重','Fixed opening weight')}</p><dl>${[[t('期初权重','Opening weight'),`${p.weight*100}%`],[t('区间收益','Period return'),pct(p.return)],[t('收益贡献','Contribution'),pp(p.contribution)],[t('预期市盈率','Forward P/E'),p.forwardPE===null?t('现金不适用','Not applicable to cash'):`${p.forwardPE}×`]].map(([a,b])=>`<div><dt>${a}</dt><dd>${b}</dd></div>`).join('')}</dl><p class="portfolio-formula">${(p.weight*100).toFixed(0)}% × ${pct(p.return)} = ${pp(p.contribution)}</p><small>${t('模拟记录。详情用于解释计算，不提供交易操作。','Synthetic record. Details explain the calculation; no trading actions.')}</small></aside>`;}
 root.querySelector('[data-portfolio-period]').onchange=e=>{period=e.target.value;hovered=null;focused=null;render();root.querySelector('[data-portfolio-period]').focus();};
 root.querySelectorAll('[data-portfolio-target]').forEach(b=>{const id=b.dataset.portfolioTarget;b.onpointerenter=()=>{hovered=id;paint();};b.onpointerleave=()=>{hovered=null;paint();};b.onfocus=()=>{focused=id;paint();};b.onblur=()=>{focused=null;paint();};b.onclick=()=>{selected=selected===id?null:id;render();root.querySelector(`[data-portfolio-target="${id}"]`)?.focus();};b.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();clear(id);}if(['ArrowDown','ArrowUp','ArrowRight','ArrowLeft'].includes(e.key)){e.preventDefault();const delta=['ArrowDown','ArrowRight'].includes(e.key)?1:-1;const move=movePortfolioSelection({ids:m.entries.map(p=>p.id),current:id,selected,direction:delta});if(selected!==null){selected=move.selected;hovered=null;focused=null;render();}root.querySelector(`tbody [data-portfolio-target="${move.focus}"]`).focus();}};});
 function clear(id){selected=null;hovered=null;focused=null;render();if(id){root.querySelector(`[data-portfolio-target="${id}"]`)?.focus();focused=null;paint();}}
 root.querySelector('[data-portfolio-clear]').onclick=()=>clear();root.querySelector('[data-portfolio-close]')?.addEventListener('click',()=>clear(selected));paint();
 function paint(){const id=selected??hovered??focused;root.classList.toggle('has-active',!!id);root.querySelectorAll('[data-portfolio-mark],[data-portfolio-row]').forEach(n=>n.classList.toggle('is-active',(n.dataset.portfolioMark??n.dataset.portfolioRow)===id));const p=m.entries.find(p=>p.id===id);root.querySelector('[data-portfolio-readout]').textContent=p?`${p.label} · ${pct(p.return)} · ${pp(p.contribution)}${selected?` · ${t('已锁定','Pinned')}`:''}`:t('悬停或聚焦任一资产，图表与明细同步。','Hover or focus a position to link both charts and the ledger.');root.querySelector('[data-portfolio-clear]').disabled=!id;}
 }
 render();return {getState(){return {period,selected};},destroy(){root.remove();}};
}
