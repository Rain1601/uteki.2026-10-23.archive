import {CITATION_KINDS, validateCitationSources} from './citation-components.mjs';

let instance = 0;
const label = (value, fallback, name) => {
  if(value === undefined) return fallback;
  if(typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} must be nonempty text`);
  return value;
};

/** Exact identity only: source order never supplies a missing citation. */
export function resolveSourceSelection(sources, id) {
  const records = validateCitationSources(sources);
  const selected = records.find(source => source.id === id);
  if(!selected) throw new TypeError(`Unknown source: ${id}`);
  return selected;
}

/** Search only the supplied public excerpt fields; never retrieves or rewrites originals. */
export function filterSourceExcerpts(sources, query = '') {
  const records = validateCitationSources(sources);
  if(typeof query !== 'string') throw new TypeError('Source query must be text');
  const terms = query.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return records.flatMap((source, index) => {
    const searchable = [source.title, source.caption, source.locator ?? '', source.text].join('\n').normalize('NFKC').toLocaleLowerCase();
    // Keep the caller's optional-field shape. The citation validator adds empty
    // locator/null href fields, which are not valid explicit caller inputs.
    return terms.every(term => searchable.includes(term)) ? [{...sources[index]}] : [];
  });
}

/** Restore the reader's two-dimensional position without moving focus. */
export function restoreReadingPosition(container, position) {
  if(!container || !position || !Number.isFinite(position.top) || !Number.isFinite(position.left)) throw new TypeError('A scroll container and finite reading position are required');
  container.scrollTop = position.top;
  container.scrollLeft = position.left;
}

/** Explicit portal ownership preserves scoped theme inheritance; default remains body. */
export function resolveSourcePortal(host, container){
 const doc=host?.ownerDocument, portal=container??doc?.body;
 if(!doc||!portal||portal.ownerDocument!==doc||typeof portal.append!=='function')throw new TypeError('Source portal must be an appendable container in the host document');
 return portal;
}

/** Centralized reading of supplied excerpts; performs no retrieval or full-document loading. */
export function mountSourcePanel(host, {sources, labels = {}, scrollContainer, portalContainer, headerAction} = {}) {
  if(!host?.ownerDocument || typeof host.addEventListener !== 'function') throw new TypeError('A mounted host is required');
  if(headerAction!==undefined&&(!headerAction||typeof headerAction.label!=='string'||!headerAction.label.trim()||typeof headerAction.onClick!=='function'))throw new TypeError('A labeled source header action with callback required');
  const portal = resolveSourcePortal(host, portalContainer);
  const records = validateCitationSources(sources);
  const byId = new Map(records.map(source => [source.id, source]));
  const searchRecords = sources.map(source => ({...source}));
  const doc = host.ownerDocument;
  const reader = scrollContainer ?? doc.scrollingElement;
  if(!reader || !('scrollTop' in reader) || !('scrollLeft' in reader)) throw new TypeError('A reading scroll container is required');
  if(labels.kinds !== undefined && (!labels.kinds || typeof labels.kinds !== 'object' || Array.isArray(labels.kinds))) throw new TypeError('Kind labels must be an object');
  const kinds = Object.fromEntries(CITATION_KINDS.map(kind => [kind, label(labels.kinds?.[kind], {
    'local-document':'Local document / 本地文档',
    'authored-specimen':'Authored specimen / 原创样稿',
    'external-document':'External document / 外部文档'
  }[kind], 'kind label')]));
  const title = label(labels.title, 'Sources / 来源', 'title');
  const returnLabel = label(labels.returnToReading, 'Return to reading / 回到阅读位置', 'returnToReading');
  const scopeLabel = label(labels.scopeNote, 'Source excerpts · Supplied scope / 原文摘录 · 按调用方提供的范围', 'scopeNote');
  const sourceLabel = label(labels.openSource, 'Open original / 打开原件', 'openSource');
  const searchLabel = label(labels.search, 'Find in supplied excerpts / 查找已有摘录', 'search');
  const searchPlaceholder = label(labels.searchPlaceholder, 'Title, location or excerpt / 标题、定位或摘录', 'searchPlaceholder');
  const clearLabel = label(labels.clearSearch, 'Clear / 清除', 'clearSearch');
  const emptyLabel = label(labels.noResults, 'No matching excerpts. Clear the search to see all sources. / 无匹配摘录，清除搜索可查看全部来源。', 'noResults');
  const resultsLabel = label(labels.results, 'Matching excerpts / 匹配摘录', 'results');
  const triggers = [...host.querySelectorAll('button[data-citation],button[data-source-panel]')];
  const triggerId = trigger => trigger.dataset.citation ?? trigger.dataset.sourcePanel;
  for(const trigger of triggers) {
    if(!byId.has(triggerId(trigger))) throw new TypeError(`Unknown source: ${triggerId(trigger)}`);
  }
  const prefix = `source-library-${++instance}`;
  const make = (tag, className, text) => {
    const node = doc.createElement(tag);
    if(className) node.className = className;
    if(text !== undefined) node.textContent = text;
    return node;
  };
  const dialog = make('dialog', 'source-library'); dialog.id = prefix;
  const heading = make('h2', 'source-library-title', title); heading.id = `${prefix}-title`;
  dialog.setAttribute('aria-labelledby', heading.id);
  const header = make('header', 'source-library-header');
  const returnButton = make('button', 'source-library-return', returnLabel); returnButton.type = 'button';
  const headingGroup = make('div', 'source-library-heading-group');
  headingGroup.append(heading, make('p', 'source-library-scope', scopeLabel));
  const headerActions=make('div','source-library-actions');headerActions.append(returnButton);
  let actionButton;if(headerAction){actionButton=make('button','source-library-return',headerAction.label);actionButton.type='button';actionButton.addEventListener('click',headerAction.onClick);headerActions.append(actionButton);}
  header.append(headingGroup, headerActions);
  const searchBar = make('div', 'source-library-search');
  const searchCaption = make('label', '', searchLabel); searchCaption.htmlFor = `${prefix}-search`;
  const search = make('input'); search.type = 'search'; search.id = searchCaption.htmlFor; search.placeholder = searchPlaceholder;
  const clearButton = make('button', 'source-library-clear', clearLabel); clearButton.type = 'button'; clearButton.hidden = true;
  const results = make('p', 'source-library-results'); results.setAttribute('role', 'status'); results.setAttribute('aria-live', 'polite');
  searchBar.append(searchCaption, search, clearButton, results);
  const nav = make('nav', 'source-library-nav'); nav.setAttribute('aria-label', title);
  const groups = new Map();
  for(const kind of CITATION_KINDS.filter(kind => records.some(source => source.kind === kind))) {
    const group = make('section', 'source-library-group');
    const groupTitle = make('h3', '', kinds[kind]); groupTitle.id = `${prefix}-group-${kind}`;
    group.setAttribute('aria-labelledby', groupTitle.id);
    const list = make('ol'); group.append(groupTitle, list); nav.append(group);
    groups.set(kind, {group, list, title:groupTitle});
  }
  const scroller = make('div', 'source-library-excerpts');
  const noResults = make('p', 'source-library-empty', emptyLabel); noResults.hidden = true; scroller.append(noResults);
  const sections = new Map(), navButtons = new Map(), navItems = new Map();
  for(const source of records) {
    const item = make('li'), button = make('button', 'source-library-nav-button', source.title);
    button.type = 'button'; button.dataset.sourceSelect = source.id;
    button.setAttribute('aria-controls', `${prefix}-${source.id}`);
    item.append(button); groups.get(source.kind).list.append(item); navButtons.set(source.id, button); navItems.set(source.id, item);
    const section = make('section', 'source-library-excerpt'); section.id = `${prefix}-${source.id}`;
    const kind = make('p', 'source-library-kind', kinds[source.kind]);
    const sourceHeading = make('h3', '', source.title); sourceHeading.id = `${section.id}-title`;
    sourceHeading.tabIndex = -1;
    section.setAttribute('aria-labelledby', sourceHeading.id);
    const provenance = make('p', 'source-library-provenance', source.caption);
    section.append(kind, sourceHeading, provenance);
    if(source.locator) section.append(make('p', 'source-library-locator', source.locator));
    section.append(make('blockquote', 'source-library-text', source.text));
    if(source.href) {
      const link = make('a', 'source-library-original', sourceLabel);
      link.href = source.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; section.append(link);
    }
    scroller.append(section); sections.set(source.id, section);
  }
  dialog.append(header, searchBar, nav, scroller);
  const previousAttributes = new Map();
  function register(trigger) {
    if(previousAttributes.has(trigger)) return;
    previousAttributes.set(trigger, Object.fromEntries(['aria-expanded','aria-haspopup','aria-controls'].map(name => [name, trigger.getAttribute(name)])));
    trigger.setAttribute('aria-haspopup', 'dialog'); trigger.setAttribute('aria-controls', prefix); trigger.setAttribute('aria-expanded', 'false');
  }
  triggers.forEach(register);
  portal.append(dialog);
  let session = null, selected = null, destroyed = false;
  function applyQuery() {
    const matches = filterSourceExcerpts(searchRecords, search.value), visible = new Set(matches.map(source => source.id));
    for(const source of records) {
      sections.get(source.id).hidden = !visible.has(source.id);
      navItems.get(source.id).hidden = !visible.has(source.id);
    }
    for(const [kind, {group, title}] of groups) {
      const count = matches.filter(source => source.kind === kind).length;
      group.hidden = count === 0; title.textContent = `${kinds[kind]} · ${count}`;
    }
    clearButton.hidden = search.value.length === 0;
    noResults.hidden = matches.length !== 0;
    results.textContent = `${resultsLabel} · ${matches.length} / ${records.length}`;
  }
  applyQuery();
  function select(id) {
    if(!byId.has(id)) throw new TypeError(`Unknown source: ${id}`);
    selected = id;
    for(const [sourceId, section] of sections) {
      section.classList.toggle('is-current', sourceId === id);
      if(sourceId === id) {section.setAttribute('aria-current', 'true'); navButtons.get(sourceId).setAttribute('aria-current', 'true');}
      else {section.removeAttribute('aria-current'); navButtons.get(sourceId).removeAttribute('aria-current');}
    }
    const section = sections.get(id);
    scroller.scrollTop += section.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 20;
    section.querySelector('h3').focus({preventScroll:true});
  }
  function open(id, opener) {
    if(destroyed) throw new TypeError('Source panel was destroyed');
    if(!byId.has(id)) throw new TypeError(`Unknown source: ${id}`);
    if(!session) {
      const origin = opener ?? doc.activeElement;
      session = {opener: origin, top:reader.scrollTop, left:reader.scrollLeft};
      if(origin?.setAttribute && host.contains(origin)) {register(origin); origin.setAttribute('aria-expanded','true');}
      try {dialog.showModal();} catch(error) {session = null; if(origin && previousAttributes.has(origin)) origin.setAttribute('aria-expanded','false'); throw error;}
    }
    // A citation always reveals its exact source, even after a previous directory search.
    if(search.value) {search.value = ''; applyQuery();}
    select(id);
  }
  function finish() {
    if(!session) return;
    const original = session; session = null; selected = null;
    for(const trigger of previousAttributes.keys()) trigger.setAttribute('aria-expanded', 'false');
    restoreReadingPosition(reader, original);
    if(original.opener?.isConnected && typeof original.opener.focus === 'function') original.opener.focus({preventScroll:true});
    restoreReadingPosition(reader, original);
  }
  function close() {if(destroyed || !session) return; if(dialog.open) dialog.close(); finish();}
  function onHostClick(event) {
    const trigger = event.target.closest?.('button[data-citation],button[data-source-panel]');
    if(!trigger || !host.contains(trigger)) return;
    event.preventDefault(); open(triggerId(trigger), trigger);
  }
  function onNavClick(event) {const button = event.target.closest?.('button[data-source-select]'); if(button && nav.contains(button)) select(button.dataset.sourceSelect);}
  function onCancel(event) {event.preventDefault(); close();}
  function onKeyDown(event) {
    // Search inputs can consume Escape to clear text; retain the panel's return action.
    if(event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); close();}
  }
  function onClose() {if(!dialog.open) finish();}
  function onSearch() {applyQuery();}
  function onClear() {search.value = ''; applyQuery(); search.focus({preventScroll:true});}
  host.addEventListener('click', onHostClick);
  nav.addEventListener('click', onNavClick);
  returnButton.addEventListener('click', close);
  search.addEventListener('input', onSearch); clearButton.addEventListener('click', onClear);
  dialog.addEventListener('cancel', onCancel); dialog.addEventListener('close', onClose);
  dialog.addEventListener('keydown', onKeyDown);
  return {
    open, close,
    destroy() {
      if(destroyed) return;
      destroyed = true; session = null; selected = null;
      host.removeEventListener('click', onHostClick); nav.removeEventListener('click', onNavClick);
      actionButton?.removeEventListener('click',headerAction.onClick);
      returnButton.removeEventListener('click', close); dialog.removeEventListener('cancel', onCancel); dialog.removeEventListener('close', onClose);
      dialog.removeEventListener('keydown', onKeyDown);
      search.removeEventListener('input', onSearch); clearButton.removeEventListener('click', onClear);
      const currentPosition = {top:reader.scrollTop, left:reader.scrollLeft};
      dialog.remove();
      restoreReadingPosition(reader, currentPosition);
      for(const [trigger, attributes] of previousAttributes) for(const [name, value] of Object.entries(attributes)) {
        if(value === null) trigger.removeAttribute(name); else trigger.setAttribute(name, value);
      }
      previousAttributes.clear();
    }
  };
}
