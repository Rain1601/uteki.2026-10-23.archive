import {esc} from './components.mjs';
const safeId=id=>{if(typeof id!=='string'||!/^[-a-zA-Z0-9_]+$/.test(id))throw Error('Invalid control identity');return id};
export function TextField({id,label,value='',help='',error='',multiline=false,required=false,maxLength}){
 safeId(id);if(!Number.isInteger(maxLength)||maxLength<1)throw Error('Explicit field limit required');
 const attrs=`id="${id}" name="${id}" ${required?'required':''} maxlength="${maxLength*2}" data-character-limit="${maxLength}" aria-describedby="${id}-help ${id}-error" aria-invalid="${Boolean(error)}"`;
 return `<label class="edition-field" for="${id}"><span>${esc(label)}${required?' *':''}</span>${multiline?`<textarea ${attrs}>${esc(value)}</textarea>`:`<input type="text" ${attrs} value="${esc(value)}">`}<small id="${id}-help" class="muted">${esc(help)}</small><small id="${id}-error" class="edition-field-error" ${error?'':'hidden'}>${esc(error)}</small></label>`;
}
export function ActionMenu({id,items,label}){
 safeId(id);const ids=items.map(i=>safeId(i.id));if(new Set(ids).size!==ids.length)throw Error('Duplicate menu identity');
 return `<div id="${id}" class="edition-menu" popover="auto" role="menu" aria-label="${esc(label)}">${items.map(i=>`<button type="button" role="menuitem" tabindex="-1" data-menu-action="${i.id}" ${i.disabled?'disabled':''}><span>${esc(i.label)}</span>${i.hint?`<small>${esc(i.hint)}</small>`:''}</button>`).join('')}</div>`;
}
export function Notice({message,tone='info',action=null,closeLabel}){
 if(!['info','success','error'].includes(tone))throw Error('Invalid feedback tone');return `<div class="edition-notice ${tone}" role="${tone==='error'?'alert':'status'}"><span>${esc(message)}</span>${action?`<button type="button" data-notice-action>${esc(action.label)}</button>`:''}<button type="button" data-notice-close aria-label="${esc(closeLabel)}">×</button></div>`;
}
export function InlineAlert({message,tone='info'}){
 if(!['info','error'].includes(tone))throw Error('Invalid alert tone');return `<p class="edition-inline-alert ${tone}" role="${tone==='error'?'alert':'note'}">${esc(message)}</p>`;
}
