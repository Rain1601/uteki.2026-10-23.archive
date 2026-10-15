import {esc} from './components.mjs';
import {safeCitationHref} from './citation-components.mjs';

const id = value => {
  if(typeof value !== 'string' || !/^[A-Za-z][A-Za-z0-9_-]*$/.test(value)) throw new TypeError('A safe component identity is required');
  return value;
};
const text = (value, name) => {
  if(typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} requires text`);
  return value;
};
const link = value => {
  if(typeof value === 'string' && /^#[A-Za-z][A-Za-z0-9_-]*$/.test(value)) return value;
  return safeCitationHref(value);
};

/** Short, nonessential help; button and description identities stay associated. */
export function Tooltip({id:identity,label,description}) {
  id(identity); text(label,'Tooltip label'); text(description,'Tooltip description');
  return `<span class="utility-tooltip" data-utility-tooltip="${identity}"><button type="button" class="button secondary" aria-describedby="${identity}">${esc(label)}</button><span id="${identity}" class="utility-tooltip-text" role="tooltip" hidden>${esc(description)}</span></span>`;
}

export function mountTooltips(host) {
  if(!host?.querySelectorAll) throw new TypeError('A mounted tooltip host is required');
  const seen = new Set(), cleanups = [];
  const models = [...host.querySelectorAll('[data-utility-tooltip]')].map(wrapper => {
    const identity = id(wrapper.dataset.utilityTooltip);
    if(seen.has(identity)) throw new TypeError('Duplicate tooltip identity'); seen.add(identity);
    const trigger = wrapper.querySelector('button'), tip = wrapper.querySelector('[role="tooltip"]');
    if(!trigger || !tip || tip.id !== identity || trigger.getAttribute('aria-describedby') !== identity) throw new TypeError('Tooltip trigger and description must be associated');
    return {wrapper,trigger,tip};
  });
  for(const {wrapper,trigger,tip} of models) {
    let hovered=false, focused=false, dismissed=false;
    const update = () => {tip.hidden = dismissed || !(hovered || focused);};
    const leave = () => {if(!hovered && !focused) dismissed=false; update();};
    const enter = () => {hovered=true; update();};
    const exit = () => {hovered=false; leave();};
    const focus = () => {focused=true; update();};
    const blur = () => {focused=false; leave();};
    const key = event => {if(event.key==='Escape' && !tip.hidden) {event.preventDefault(); event.stopPropagation(); dismissed=true; update();}};
    wrapper.addEventListener('pointerenter',enter); wrapper.addEventListener('pointerleave',exit);
    trigger.addEventListener('focus',focus); trigger.addEventListener('blur',blur); trigger.addEventListener('keydown',key);
    cleanups.push(() => {wrapper.removeEventListener('pointerenter',enter);wrapper.removeEventListener('pointerleave',exit);trigger.removeEventListener('focus',focus);trigger.removeEventListener('blur',blur);trigger.removeEventListener('keydown',key);tip.hidden=true;});
  }
  let destroyed=false;
  return {destroy(){if(destroyed)return;destroyed=true;cleanups.forEach(cleanup=>cleanup());}};
}

export function Accordion({id:identity,label,items}) {
  id(identity); text(label,'Disclosure group label');
  if(!Array.isArray(items)) throw new TypeError('Disclosure items must be an array');
  const seen=new Set();
  return `<section id="${identity}" class="accordion utility-disclosures" aria-label="${esc(label)}">${items.map(item=>{
    id(item.id); if(seen.has(item.id)) throw new TypeError('Duplicate disclosure identity'); seen.add(item.id);
    text(item.title,'Disclosure title'); text(item.text,'Disclosure text');
    if(item.open !== undefined && typeof item.open !== 'boolean') throw new TypeError('Disclosure open must be boolean');
    return `<details id="${identity}-${item.id}"${item.open?' open':''}><summary>${esc(item.title)}</summary><div class="utility-disclosure-body"><p>${esc(item.text)}</p>${item.href?`<a href="${esc(link(item.href))}" target="_blank" rel="noopener noreferrer">${esc(text(item.linkLabel,'Disclosure link label'))}</a>`:''}</div></details>`;
  }).join('')}</section>`;
}

export function Breadcrumb({id:identity,label,items,currentId}) {
  id(identity); text(label,'Breadcrumb label'); id(currentId);
  if(!Array.isArray(items)||!items.length) throw new TypeError('Breadcrumb requires entries');
  const seen=new Set();
  if(items.at(-1)?.id!==currentId) throw new TypeError('Breadcrumb current identity must be the final entry');
  return `<nav id="${identity}" class="bread utility-breadcrumb" aria-label="${esc(label)}"><ol>${items.map(item=>{
    id(item.id); if(seen.has(item.id)) throw new TypeError('Duplicate breadcrumb identity'); seen.add(item.id);text(item.label,'Breadcrumb entry');
    return `<li>${item.id===currentId?`<span aria-current="page">${esc(item.label)}</span>`:`<a href="${esc(link(item.href))}">${esc(item.label)}</a>`}</li>`;
  }).join('')}</ol></nav>`;
}

export function validatePagination({id:identity,page,count,action,label,previousLabel,nextLabel,pageLabel,emptyLabel}) {
  id(identity);id(action);text(label,'Pagination label');text(previousLabel,'Previous label');text(nextLabel,'Next label');text(pageLabel,'Page label');text(emptyLabel,'Empty pagination label');
  if(!Number.isSafeInteger(count)||count<0||!Number.isSafeInteger(page)||(count===0?page!==0:page<1||page>count)) throw new TypeError('Invalid pagination range');
  return {id:identity,page,count,action,label,previousLabel,nextLabel,pageLabel,emptyLabel};
}

/** Caller supplies total page count; the component never derives it from records. */
export function Pagination(input) {
  const model=validatePagination(input), {page,count,action}=model;
  const button=(target,label,disabled=false,current=false)=>`<button type="button" class="button secondary" data-page-action="${action}" data-page="${target}"${disabled?' disabled':''}${current?' aria-current="page"':''}>${esc(label)}</button>`;
  // A bounded window avoids a huge DOM for explicit large totals without inventing totals.
  const pages=count?Array.from(new Set([1,count,...Array.from({length:5},(_,i)=>page+i-2).filter(p=>p>=1&&p<=count)])).sort((a,b)=>a-b):[];
  return `<nav id="${model.id}" class="pagination utility-pagination" aria-label="${esc(model.label)}"><span>${count?`${esc(model.pageLabel)} ${page} / ${count}`:esc(model.emptyLabel)}</span><span class="utility-page-buttons">${button(Math.max(1,page-1),model.previousLabel,!count||page===1)}${pages.map((p,i)=>`${i&&p-pages[i-1]>1?'<span aria-hidden="true">…</span>':''}${button(p,`${model.pageLabel} ${p}`,false,p===page)}`).join('')}${button(Math.min(count,page+1),model.nextLabel,!count||page===count)}</span></nav>`;
}

export function Loading({id:identity,label,description,progress=null,progressLabel}) {
  id(identity);text(label,'Loading label');text(description,'Loading description');
  if(progress!==null&&(!Number.isFinite(progress)||progress<0||progress>100)) throw new TypeError('Invalid progress range');
  if(progress!==null)text(progressLabel,'Progress label');
  return `<section id="${identity}" class="state-block utility-loading" role="status" aria-live="polite"><span class="eyebrow">${esc(label)}</span><div aria-hidden="true"><div class="skeleton"></div><div class="skeleton short"></div><div class="skeleton"></div></div><p>${esc(description)}</p>${progress!==null?`<progress value="${progress}" max="100" aria-label="${esc(progressLabel)}"></progress>`:''}</section>`;
}
