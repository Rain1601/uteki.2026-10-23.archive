/** Content cards and content-rich lists. Escaped markup only; caller owns actions and state. */
const escape = value => value.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export const CARD_ACTIONS = Object.freeze(['open','inspect','download','remove','retry','cancel','confirm','continue','edit']);
export const CONTENT_STATUSES = Object.freeze(['idle','queued','running','waiting','completed','failed','cancelled','draft','ready']);
const string = (value, name, optional = false) => {
  if (optional && value === undefined) return '';
  if (typeof value !== 'string' || (!optional && !value.trim())) throw new TypeError(`${name} must be text`);
  return value;
};
const identity = (value, name) => {
  string(value, name);
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new TypeError(`${name} must be a safe identity`);
  return value;
};
function content(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('Content must be an object');
  const status = input.status === undefined ? '' : string(input.status, 'status');
  if (status && !CONTENT_STATUSES.includes(status)) throw new TypeError('Unknown content status');
  return {id:identity(input.id,'id'), title:string(input.title,'title'), description:string(input.description,'description',true), meta:string(input.meta,'meta',true), status, statusLabel:input.statusLabel === undefined ? status : string(input.statusLabel,'statusLabel')};
}
export function validateCard(input) {
  const model = content(input), selected = input.selected === undefined ? false : input.selected;
  if (typeof selected !== 'boolean') throw new TypeError('selected must be boolean');
  const actions = input.actions === undefined ? [] : input.actions;
  if (!Array.isArray(actions)) throw new TypeError('actions must be an array');
  const seen = new Set();
  return {...model, eyebrow:string(input.eyebrow,'eyebrow',true), selected, actions:actions.map(action => {
    if (!action || !CARD_ACTIONS.includes(action.id) || seen.has(action.id)) throw new TypeError('Unknown or duplicate card action');
    seen.add(action.id);
    if (action.disabled !== undefined && typeof action.disabled !== 'boolean') throw new TypeError('disabled must be boolean');
    return {id:action.id,label:string(action.label,'action label'),disabled:action.disabled ?? false};
  })};
}
export function validateItemList(input) {
  if (!input || !Array.isArray(input.items)) throw new TypeError('items must be an array');
  const seen = new Set(), items = input.items.map(item => {
    const model = content(item);
    if (seen.has(model.id)) throw new TypeError('Duplicate list item identity');
    seen.add(model.id);
    return model;
  });
  const selected = input.selected === undefined ? null : input.selected;
  if (selected !== null && !seen.has(selected)) throw new TypeError('selected must identify a list item');
  return {id:identity(input.id,'list id'),label:string(input.label,'label'),items,selected,emptyText:input.emptyText === undefined ? 'No items' : string(input.emptyText,'emptyText')};
}
const statusMarkup = (status, label) => status ? `<span class="content-status" data-status="${status}">${escape(label)}</span>` : '';
export function Card(input) {
  const model = validateCard(input);
  return `<article id="${model.id}" class="content-card${model.selected ? ' is-selected' : ''}" data-card-id="${model.id}">${model.eyebrow ? `<p class="content-eyebrow">${escape(model.eyebrow)}</p>` : ''}<div class="content-card-heading"><h3>${escape(model.title)}</h3>${statusMarkup(model.status, model.statusLabel)}</div>${model.description ? `<p class="content-description">${escape(model.description)}</p>` : ''}${model.meta ? `<p class="content-meta">${escape(model.meta)}</p>` : ''}${model.actions.length ? `<div class="content-card-actions">${model.actions.map(action => `<button type="button" data-card-id="${model.id}" data-card-action="${action.id}"${action.disabled ? ' disabled' : ''}>${escape(action.label)}</button>`).join('')}</div>` : ''}</article>`;
}
export function ItemList(input) {
  const model = validateItemList(input);
  return `<section id="${model.id}" class="content-list" aria-label="${escape(model.label)}">${model.items.length ? `<ul>${model.items.map(item => `<li><button type="button" class="content-list-row${model.selected === item.id ? ' is-selected' : ''}" data-item-id="${item.id}"${model.selected === item.id ? ' aria-current="true"' : ''}><span class="content-list-heading"><strong>${escape(item.title)}</strong>${statusMarkup(item.status, item.statusLabel)}</span>${item.description ? `<span class="content-description">${escape(item.description)}</span>` : ''}${item.meta ? `<span class="content-meta">${escape(item.meta)}</span>` : ''}</button></li>`).join('')}</ul>` : `<p class="content-list-empty">${escape(model.emptyText)}</p>`}</section>`;
}
