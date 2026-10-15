import {createSourceExcerpt} from './source-excerpt.mjs';

const escape = value => value.replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const plain = (value, name) => {if(typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} must be nonempty text`); return value;};
const identity = value => {plain(value,'id'); if(!/^[A-Za-z][A-Za-z0-9_-]*$/.test(value)) throw new TypeError('Citation identity must start with a letter and contain only letters, numbers, underscores or hyphens'); return value;};
export const CITATION_KINDS=Object.freeze(['local-document','authored-specimen','external-document']);
let instance = 0;

/** Permit explicit local document paths or public web URLs; never infer a source. */
export function safeCitationHref(value) {
  plain(value,'href');
  if(/[\s\\\u0000-\u001f\u007f]/.test(value)) throw new TypeError('Unsafe source URL');
  let decoded;
  try {decoded=decodeURIComponent(value);} catch {throw new TypeError('Malformed source URL');}
  if(/[\\\u0000-\u001f\u007f]/.test(decoded) || /(?:^|\/)\.\.(?:\/|$|[?#])/.test(decoded) || /%[0-9a-f]{2}/i.test(decoded)) throw new TypeError('Unsafe source URL');
  if(/^https?:\/\//i.test(value)) {
    const url=new URL(value);
    if(url.username || url.password || !url.hostname) throw new TypeError('Unsafe source URL');
    return value;
  }
  if(!/^\.\//.test(value) || value.startsWith('.//')) throw new TypeError('Source URL must be explicit local ./ or http(s)');
  return value;
}

export function validateCitationSource(input) {
  if(!input || typeof input!=='object' || Array.isArray(input)) throw new TypeError('Source must be an object');
  if(!CITATION_KINDS.includes(input.kind)) throw new TypeError('Unknown citation source kind');
  return {id:identity(input.id), title:plain(input.title,'title'), text:plain(input.text,'text'), caption:plain(input.caption,'caption'), kind:plain(input.kind,'kind'), locator:input.locator===undefined?'':plain(input.locator,'locator'), href:input.href===undefined?null:safeCitationHref(input.href)};
}

export function validateCitationSources(inputs) {
  if(!Array.isArray(inputs)) throw new TypeError('sources must be an array');
  const seen=new Set();
  return inputs.map(input=>{const model=validateCitationSource(input); if(seen.has(model.id)) throw new TypeError('Duplicate citation source'); seen.add(model.id); return model;});
}

/** Plain-text inline citation. Wrap in ordinary inline flow, never inside another button. */
export function Citation({id,label}={}) {
  return `<span class="citation-anchor"><button type="button" class="citation-trigger" data-citation="${identity(id)}" aria-expanded="false">${escape(plain(label,'label'))}</button></span>`;
}

/** Click-only binding for supplied excerpts. Caller owns source discovery and truthfulness. */
export function mountCitations(host,{sources,labels={}}={}) {
  if(!host || typeof host.addEventListener!=='function' || !host.ownerDocument) throw new TypeError('A mounted host is required');
  const records=new Map(validateCitationSources(sources).map(source=>[source.id,source]));
  host.querySelectorAll('button[data-citation]').forEach(button=>{if(!records.has(button.dataset.citation))throw new TypeError(`Unknown citation: ${button.dataset.citation}`);});
  const linkLabel=labels.openSource===undefined?'Open source / 查看出处':plain(labels.openSource,'openSource');
  if(labels.kinds!==undefined && (!labels.kinds || typeof labels.kinds!=='object' || Array.isArray(labels.kinds))) throw new TypeError('Kind labels must be an object');
  const kindLabels=Object.fromEntries(CITATION_KINDS.map(kind=>[kind,labels.kinds?.[kind]===undefined?kind:plain(labels.kinds[kind],'kind label')]));
  const doc=host.ownerDocument, prefix=`citation-panel-${++instance}`;
  let active=null, destroyed=false;
  function close(restoreFocus=false) {
    if(!active) return;
    const previous=active; active=null; previous.panel.destroy();
    if(restoreFocus && previous.button.isConnected) previous.button.focus();
  }
  function onClick(event) {
    const button=event.target.closest?.('button[data-citation]');
    if(!button || !host.contains(button)) return;
    const source=records.get(button.dataset.citation);
    if(!source) throw new TypeError(`Unknown citation: ${button.dataset.citation}`);
    if(active?.button===button) {close(); return;}
    close();
    const panel=createSourceExcerpt(button,{id:`${prefix}-${source.id}`,title:source.title,text:source.text,caption:[kindLabels[source.kind],source.caption,source.locator].filter(Boolean).join(' · '),onClose:()=>{const previous=active;active=null; if(previous?.button.isConnected) previous.button.focus();}});
    panel.content.classList.add('citation-excerpt');
    if(source.href) {
      const link=doc.createElement('a'); link.className='citation-source-link'; link.textContent=linkLabel; link.href=source.href;
      link.target='_blank'; link.rel='noopener noreferrer'; panel.content.append(link);
    }
    const viewport=doc.defaultView, anchor=button.getBoundingClientRect(), size=panel.content.getBoundingClientRect();
    const margin=16, width=viewport.innerWidth, height=viewport.innerHeight;
    panel.content.style.left=`${Math.max(margin,Math.min(anchor.left,width-size.width-margin))}px`;
    const below=anchor.bottom+10, above=anchor.top-size.height-10;
    panel.content.style.top=`${Math.max(margin,Math.min(below+size.height<=height-margin?below:above,height-size.height-margin))}px`;
    active={button,panel};
  }
  function onOutside(event) {if(active && !active.button.contains(event.target) && !active.panel.content.contains(event.target)) close();}
  function onKey(event) {if(event.key==='Escape' && active) {event.preventDefault();close(true);}}
  function onScroll(event) {if(active && !(event.target?.nodeType && active.panel.content.contains(event.target))) close();}
  const viewport=doc.defaultView;
  host.addEventListener('click',onClick); doc.addEventListener('pointerdown',onOutside); doc.addEventListener('keydown',onKey);doc.addEventListener('scroll',onScroll,true);viewport.addEventListener('resize',onScroll);
  return {destroy(){if(destroyed)return;destroyed=true;close();host.removeEventListener('click',onClick);doc.removeEventListener('pointerdown',onOutside);doc.removeEventListener('keydown',onKey);doc.removeEventListener('scroll',onScroll,true);viewport.removeEventListener('resize',onScroll);}};
}
