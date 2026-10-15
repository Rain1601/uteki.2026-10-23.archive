/** Native disclosure directory. Selection identifies a resource; it never opens it. */
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const text = (value, name) => {
  if (typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} must be non-empty text`);
  return value;
};
export function safeResourceHref(value) {
  text(value, 'href');
  if (/[\u0000-\u0020\u007f\\]/.test(value) || value.startsWith('//')) throw new TypeError('Unsafe resource href');
  const parsed = new URL(value, 'https://resource.invalid/');
  if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new TypeError('Unsafe resource href');
  return value;
}
export function validateResourceTree(input) {
  if (!input || !Array.isArray(input.nodes)) throw new TypeError('nodes must be an array');
  const ids = new Set();
  const visit = (nodes, depth = 0) => {
    if (depth > 12) throw new TypeError('Resource tree is too deep');
    return nodes.map(node => {
      const id = text(node?.id, 'id');
      if (!/^[a-zA-Z0-9_-]+$/.test(id) || ids.has(id)) throw new TypeError(`Invalid or duplicate resource identity: ${id}`);
      ids.add(id);
      const label = text(node.label, 'label');
      if (Object.hasOwn(node, 'children')) {
        if (!Array.isArray(node.children) || node.href !== undefined || node.kind !== undefined) throw new TypeError('Folders require children and cannot contain resource fields');
        return {id, label, children: visit(node.children, depth + 1)};
      }
      return {id, label, kind: text(node.kind, 'kind'), href: safeResourceHref(node.href), ...(node.description !== undefined ? {description: text(node.description, 'description')} : {})};
    });
  };
  const nodes = visit(input.nodes);
  const all = flattenVisible(nodes, new Set(ids));
  if (input.selected !== undefined && input.selected !== null && !all.some(row => row.node.id === input.selected && !row.node.children)) throw new TypeError('selected must identify a leaf resource');
  if (input.onSelect !== undefined && typeof input.onSelect !== 'function') throw new TypeError('onSelect must be a function');
  return {nodes, selected: input.selected ?? null, onSelect: input.onSelect, labels: {region: text(input.labels?.region, 'labels.region'), empty: text(input.labels?.empty, 'labels.empty')}};
}
/** An explicit open set makes navigation independent of hidden DOM rows. */
export function flattenVisible(nodes, openIds = new Set(), parent = null, depth = 0) {
  return nodes.flatMap(node => [{node, parent, depth}, ...(node.children && openIds.has(node.id) ? flattenVisible(node.children, openIds, node.id, depth + 1) : [])]);
}
const countResources = node => node.children ? node.children.reduce((count, child) => count + countResources(child), 0) : 1;
const contains = (node, id) => node.id === id || Boolean(node.children?.some(child => contains(child, id)));
export function ResourceTree(input) {
  const model = validateResourceTree(input);
  const render = nodes => nodes.map(node => node.children
    ? `<li><details data-folder="${node.id}"${contains(node, model.selected) ? ' open' : ''}><summary class="resource-tree-row" data-resource-id="${node.id}" tabindex="-1"><span class="resource-tree-chevron" aria-hidden="true">›</span><span class="resource-tree-label">${esc(node.label)}</span><span class="resource-tree-count" aria-label="${countResources(node)}">${countResources(node)}</span></summary><ul>${render(node.children)}</ul></details></li>`
    : `<li><button type="button" class="resource-tree-row resource-tree-leaf${model.selected === node.id ? ' is-selected' : ''}" data-resource-id="${node.id}" tabindex="-1"${model.selected === node.id ? ' aria-current="true"' : ''}><span class="resource-tree-kind">${esc(node.kind)}</span><span class="resource-tree-label">${esc(node.label)}</span>${node.description ? `<span class="resource-tree-description">${esc(node.description)}</span>` : ''}</button></li>`).join('');
  return `<nav class="resource-tree" aria-label="${esc(model.labels.region)}">${model.nodes.length ? `<ul>${render(model.nodes)}</ul>` : `<p class="resource-tree-empty">${esc(model.labels.empty)}</p>`}</nav>`;
}
export function mountResourceTree(host, input) {
  if (!host?.ownerDocument || typeof host.replaceChildren !== 'function') throw new TypeError('A DOM host is required');
  const model = validateResourceTree(input);
  host.innerHTML = ResourceTree(input);
  const root = host.querySelector('.resource-tree');
  const rows = new Map([...root.querySelectorAll('[data-resource-id]')].map(row => [row.dataset.resourceId, row]));
  const folders = new Map([...root.querySelectorAll('details[data-folder]')].map(folder => [folder.dataset.folder, folder]));
  const all = flattenVisible(model.nodes, new Set(folders.keys()));
  const nodes = new Map(all.map(row => [row.node.id, row.node]));
  let current = model.selected ?? all[0]?.node.id, selected = model.selected, destroyed = false;
  const visible = () => flattenVisible(model.nodes, new Set([...folders].filter(([, folder]) => folder.open).map(([id]) => id)));
  const sync = () => {
    const list = visible();
    if (!list.some(row => row.node.id === current)) current = list[0]?.node.id;
    for (const [id, row] of rows) {
      row.tabIndex = id === current ? 0 : -1;
      if (!nodes.get(id).children) {
        row.classList.toggle('is-selected', selected === id);
        if (selected === id) row.setAttribute('aria-current', 'true'); else row.removeAttribute('aria-current');
      }
    }
  };
  const focus = id => { current = id; sync(); rows.get(id)?.focus(); };
  const click = event => {
    const row = event.target.closest('[data-resource-id]');
    if (!row || !root.contains(row)) return;
    current = row.dataset.resourceId;
    const node = nodes.get(current);
    if (!node.children) { selected = current; sync(); model.onSelect?.(current, {...node}); }
  };
  const focusin = event => { const row = event.target.closest('[data-resource-id]'); if (row) { current = row.dataset.resourceId; sync(); } };
  const toggle = event => {
    if (!event.target.matches('details[data-folder]')) return;
    const folderId = event.target.dataset.folder;
    // Closing with pointer or keyboard restores the roving row to that folder.
    if (!event.target.open && contains(nodes.get(folderId), current)) current = folderId;
    sync();
  };
  const keydown = event => {
    const row = event.target.closest('[data-resource-id]');
    if (!row || !['ArrowUp','ArrowDown','ArrowRight','ArrowLeft','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const list = visible(), index = list.findIndex(item => item.node.id === row.dataset.resourceId), item = list[index];
    if (!item) return;
    const folder = folders.get(item.node.id);
    switch (event.key) {
      case 'ArrowUp': focus(list[Math.max(0, index - 1)].node.id); break;
      case 'ArrowDown': focus(list[Math.min(list.length - 1, index + 1)].node.id); break;
      case 'Home': focus(list[0].node.id); break;
      case 'End': focus(list.at(-1).node.id); break;
      case 'ArrowRight': if (folder) { if (!folder.open) { folder.open = true; sync(); } else if (item.node.children.length) focus(item.node.children[0].id); } break;
      case 'ArrowLeft': if (folder?.open) { folder.open = false; sync(); } else if (item.parent) focus(item.parent); break;
    }
  };
  root.addEventListener('click', click);
  root.addEventListener('focusin', focusin);
  root.addEventListener('toggle', toggle, true);
  root.addEventListener('keydown', keydown);
  sync();
  return {destroy() { if (destroyed) return; destroyed = true; root.removeEventListener('click', click); root.removeEventListener('focusin', focusin); root.removeEventListener('toggle', toggle, true); root.removeEventListener('keydown', keydown); if (root.parentNode === host) root.remove(); }};
}
