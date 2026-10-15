// Stateless components: content and selected identity are supplied by the caller.
import {number} from './tokens.mjs?v=1';
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const text=(v,name)=>{if(typeof v!=='string'||!v.trim())throw Error(`${name} requires text`);return esc(v)};
const id=v=>{if(typeof v!=='string'||!/^[-a-zA-Z0-9_]+$/.test(v))throw Error('Invalid component id');return v};
const href=v=>{if(typeof v!=='string'||!(/^(https?:\/\/|#|\.\/|\/[^/])/.test(v)))throw Error('Unsupported link');return esc(v)};

export function Header({brand,brandHref,links,label,action,mountId}){
 if(!Array.isArray(links))throw Error('Header links required');
 return `<header class="site-head" ${mountId?`id="${id(mountId)}"`:''}><a class="brand" href="${href(brandHref)}">${text(brand,'Brand')}</a><nav aria-label="${text(label,'Navigation label')}">${links.map(l=>`<a href="${href(l.href)}">${text(l.label,'Link')}</a>`).join('')}</nav>${action?`<button type="button" class="button primary" data-action="${id(action.id)}">${text(action.label,'Action')}</button>`:''}</header>`;
}
export function Sidebar({entries,label,currentId=null,showIndex=false,variant='workspace'}){
 if(!Array.isArray(entries)||!['workspace','article'].includes(variant))throw Error('Invalid Sidebar props');
 const keys=entries.map(e=>id(e.id));if(new Set(keys).size!==keys.length)throw Error('Duplicate sidebar id');
 if(currentId!==null&&!keys.includes(currentId))throw Error('Unknown sidebar selection');
 return `<nav class="component-sidebar sidebar-${variant}" aria-label="${text(label,'Sidebar label')}">${entries.map((e,i)=>`<button type="button" data-section="${id(e.id)}" class="${e.id===currentId?'active':''}" ${e.id===currentId?'aria-current="location"':''}>${showIndex?`<span class="serial">${String(i+1).padStart(2,'0')}</span>`:''}<span>${text(e.label,'Entry')}</span></button>`).join('')}</nav>`;
}
export function DataTable({rows,columns,rowKey,caption,sortKey=null,direction='asc',selected=null,locale='en-US',variant='ruled'}){
 if(!Array.isArray(rows)||!Array.isArray(columns)||!columns.length||typeof rowKey!=='string'||!rowKey)throw Error('Rows, columns and rowKey required');
 if(!['asc','desc'].includes(direction)||!['ruled','grid'].includes(variant))throw Error('Invalid table mode');
 if(columns.some(c=>c.slot!==undefined&&typeof c.slot!=='boolean'||c.slot&&(c.numeric||c.interactive)))throw Error('Cell slots must be explicit nonnumeric noninteractive columns');
 const keys=columns.map(c=>id(c.key));if(new Set(keys).size!==keys.length)throw Error('Duplicate column key');
 if(sortKey!==null&&!columns.some(c=>c.key===sortKey&&c.sortable))throw Error('Unknown sortable column');
 const ids=rows.map(r=>{if(r[rowKey]==null)throw Error('Missing row identity');return String(r[rowKey])});if(new Set(ids).size!==ids.length)throw Error('Duplicate row identity');
 return `<div class="table-wrap"><table class="data-table ${variant}"><caption class="sr">${text(caption,'Table caption')}</caption><thead><tr>${columns.map(c=>`<th scope="col" class="${c.numeric?'numeric':''}" ${c.key===sortKey?`aria-sort="${direction==='asc'?'ascending':'descending'}"`:''}>${c.sortable?`<button type="button" data-sort="${id(c.key)}">${text(c.label,'Column label')} <span class="sort-mark">${c.key===sortKey?(direction==='asc'?'↑':'↓'):'↕'}</span></button>`:text(c.label,'Column label')}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr class="${selected!==null&&String(selected)===String(r[rowKey])?'selected':''}">${columns.map(c=>{const v=c.numeric?number(r[c.key],{unit:c.unit??'',locale,digits:c.digits??0}):(r[c.key]??'—');return `<td class="${c.numeric?'numeric':''}">${c.slot?`<span data-cell-slot="${id(c.key)}" data-row-id="${esc(r[rowKey])}">${esc(v)}</span>`:c.interactive?`<button type="button" class="row-link" data-record="${esc(r[rowKey])}">${esc(v)} <span aria-hidden="true">↗</span></button>`:esc(v)}${c.descriptionKey?`<small class="cell-note">${esc(r[c.descriptionKey])}</small>`:''}</td>`}).join('')}</tr>`).join('')}</tbody></table></div>`;
}

// Physical layout is supplied explicitly. This bounded specimen supports two English pages.
export function PDFPreview({model,layout,locale}){
 if(layout?.limits?.language!=='en'||layout.limits.pages!==2||!model||!Array.isArray(model.rows))throw Error('Unsupported PDF preview scope');
 const {page:p,margins:m,type:t,cover:c,footer:f,specimenLabels:l}=layout;
 const dimension=v=>{if(!Number.isFinite(v)||v<0)throw Error('Invalid PDF dimension');return v};
 const width=dimension(p.width),height=dimension(p.height);if(!width||!height)throw Error('Invalid page size');
 const pct=v=>`${dimension(v)/width*100}cqw`,ypct=v=>`${dimension(v)/height*100}%`;
 const font=role=>{const s=t[role];if(!['sans','sansBold','serif'].includes(s.font))throw Error('Unsupported PDF font role');return `font-family:var(--font-${s.font==='serif'?'reading':'ui'});font-weight:${s.font==='sansBold'?700:400};font-size:${pct(s.size)};line-height:${s.leading/s.size}`};
 const body=`padding:${ypct(m.bodyTop)} ${m.bodyRight/width*100}% ${ypct(m.bodyBottom)} ${m.bodyLeft/width*100}%`;
 const footer=n=>`<div class="pdf-footer" style="left:${f.left/width*100}%;right:${f.right/width*100}%;bottom:${ypct(f.baseline)};${font('footer')}"><span>${text(l.footer,'Footer')}</span><span>${n}</span></div>`;
 const frame=html=>`<div class="pdf-page-frame"><div class="pdf-sheet" style="aspect-ratio:${width}/${height}">${html}</div></div>`;
 const cover=`<div class="pdf-cover-fill"></div><div class="pdf-brand" style="position:absolute;top:${ypct(c.brandTop)};left:${m.coverLeft/width*100}%;${font('brand')}">${text(l.brand,'PDF brand')}</div><div class="pdf-cover-content" style="position:absolute;top:${ypct(c.titleTop)};left:${m.coverLeft/width*100}%;right:${m.coverRight/width*100}%"><h3 style="${font('coverTitle')}">${text(model.title,'PDF title')}</h3><hr style="margin-top:${pct(c.ruleGap)};border-top-width:${pct(c.ruleWidth)}"><div class="cover-meta" style="margin-top:${pct(c.metadataGap-c.ruleGap-t.metadataLabel.leading)};${font('metadata')}"><div><b style="${font('metadataLabel')}">${text(l.published,'Metadata')}</b><br>${text(model.date,'Date')}</div><div><b style="${font('metadataLabel')}">${text(l.kind,'Metadata')}</b><br>${text(model.kind,'Kind')}</div></div></div><p class="pdf-cover-note" style="position:absolute;top:${ypct(c.noteTop)};left:${m.coverLeft/width*100}%;right:${m.coverRight/width*100}%;${font('caption')}">${text(l.coverNote,'Cover note')}</p>${footer(1)}`;
 const main=`<div class="pdf-body" style="${body};${font('body')}"><h3 style="${font('section')};margin-bottom:${pct(layout.spacing.headingAfter)}">${text(l.summaryHeading,'Heading')}</h3><p style="${font('body')};margin-bottom:${pct(layout.spacing.paragraphAfter)}">${text(model.summary,'Summary')}</p><p style="${font('body')};margin-bottom:${pct(layout.spacing.sectionBefore)}">${text(model.note,'Note')}</p><h3 style="${font('section')};margin-bottom:${pct(layout.spacing.headingAfter)}">${text(l.observationsHeading,'Heading')}</h3><table class="pdf-data" style="${font('table')}"><caption class="sr">${text(l.tableCaption,'Caption')}</caption><colgroup><col><col style="width:${layout.table.numericWidth/(width-m.bodyLeft-m.bodyRight)*100}%"></colgroup><thead><tr><th>${text(l.tableItem,'Table heading')}</th><th class="numeric">${text(l.tableValue,'Table heading')}</th></tr></thead><tbody>${model.rows.map(r=>`<tr><td>${text(r.label,'Row label')}</td><td class="numeric">${r.value===null?text(layout.table.missingLabel,'Missing label'):esc(number(r.value,{locale}))}</td></tr>`).join('')}</tbody></table><p class="pdf-caption" style="${font('caption')};margin-top:${pct(layout.spacing.captionBefore)}">${text(l.tableCaption,'Caption')}</p></div>${footer(2)}`;
 return `<div class="pdf-pages" lang="en">${frame(cover)}${frame(main)}</div>`;
}
