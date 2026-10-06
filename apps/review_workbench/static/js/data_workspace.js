(() => {
  'use strict';
  const config = JSON.parse(document.getElementById('dw-config').textContent);
  const selection = config.selection;
  const q = (s) => document.querySelector(s);
  const all = (s) => [...document.querySelectorAll(s)];
  const store = {
    get(k) { try { return JSON.parse(sessionStorage.getItem('uteki-data-workspace:' + k)); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem('uteki-data-workspace:' + k, JSON.stringify(v)); } catch {} }
  };
  const context = [selection.dataset || '', selection.source || ''].join(':');
  let activeTab = selection.tab || 'original';
  let locatorRequest = 0;
  let locatorAbort;
  let sourceFeedback = {state: 'idle', zh: '已保存原件；外部资源不加载。', en: 'Saved original; external resources are disabled.'};
  let pendingFrame = null;
  const language = () => document.documentElement.lang === 'en' ? 'en' : 'zh';
  const text = (zh, en) => language() === 'en' ? en : zh;
  const message = (zh, en) => { const node = q('#dw-message'); node.textContent = text(zh, en); node.hidden = false; };
  function sourceStatus(state, zh, en) {
    sourceFeedback = {state, zh, en};
    const node = q('#dw-source-status');
    if (!node) return;
    node.textContent = text(zh, en); node.dataset.state = state;
    node.classList.toggle('dw-locator-error', state === 'unavailable' || state === 'error');
  }
  document.documentElement.lang = store.get('language') === 'en' ? 'en' : 'zh-CN';
  q('#dw-language').addEventListener('click', () => {
    document.documentElement.lang = language() === 'en' ? 'zh-CN' : 'en';
    store.set('language', language());
    sourceStatus(sourceFeedback.state, sourceFeedback.zh, sourceFeedback.en);
  });
  q('#dw-company-search')?.addEventListener('input', (event) => {
    let count = 0;
    all('[data-company-search]').forEach(node => {
      node.hidden = !node.dataset.companySearch.toLowerCase().includes(event.target.value.toLowerCase());
      if (!node.hidden) count++;
    });
    q('#dw-company-empty').hidden = count !== 0;
  });
  function savePositions() {
    all('[data-scroll-key]').forEach(node => store.set(context + ':' + activeTab + ':' + node.dataset.scrollKey, [node.scrollLeft, node.scrollTop]));
  }
  function restorePositions() {
    all('[data-scroll-key]').forEach(node => {
      const value = store.get(context + ':' + activeTab + ':' + node.dataset.scrollKey);
      if (Array.isArray(value)) { node.scrollLeft = value[0]; node.scrollTop = value[1]; }
    });
  }
  addEventListener('pagehide', savePositions);
  document.addEventListener('click', (event) => { if (event.target.closest('a[href]')) savePositions(); });
  const directory = q('#dw-material-directory');
  if (directory) {
    const key = selection.dataset + ':directory';
    const saved = store.get(key);
    directory.open = typeof saved === 'boolean' ? saved : !selection.source;
    directory.addEventListener('toggle', () => store.set(key, directory.open));
    const nodes = all('.dw-material');
    const controls = ['dw-material-search', 'dw-year', 'dw-form', 'dw-group'];
    const filters = store.get(selection.dataset + ':filters') || {};
    controls.forEach(id => { const el = document.getElementById(id); if (filters[id] !== undefined) el.value = filters[id]; });
    function arrange() {
      const savedFilters = {};
      controls.forEach(id => { savedFilters[id] = document.getElementById(id).value; });
      store.set(selection.dataset + ':filters', savedFilters);
      all('.dw-group-title').forEach(el => el.remove());
      const query = q('#dw-material-search').value.toLowerCase();
      const year = q('#dw-year').value;
      const form = q('#dw-form').value;
      const group = q('#dw-group').value;
      const sorted = [...nodes].sort((a, b) => group === 'form' ? a.dataset.form.localeCompare(b.dataset.form) || b.dataset.year.localeCompare(a.dataset.year) : b.dataset.year.localeCompare(a.dataset.year));
      let last = null, count = 0;
      sorted.forEach(node => {
        node.hidden = !node.textContent.toLowerCase().includes(query) || Boolean(year && node.dataset.year !== year) || Boolean(form && node.dataset.form !== form);
        const key = node.dataset[group] || text('报告期未标注', 'Period not recorded');
        if (!node.hidden) {
          count++;
          if (key !== last) { const title = document.createElement('div'); title.className = 'dw-group-title'; title.textContent = key; q('#dw-materials').append(title); last = key; }
        }
        q('#dw-materials').append(node);
      });
      q('#dw-material-empty').hidden = count !== 0;
    }
    controls.forEach(id => document.getElementById(id).addEventListener('input', arrange));
    arrange();
  }
  if (!selection.source) return;
  const reader = q('#dw-reader');
  function switchTab(tab, updateURL = true, save = true) {
    if (!all('[data-tab]').some(n => n.dataset.tab === tab)) return;
    if (save) savePositions();
    activeTab = tab;
    all('[data-tab]').forEach(n => { if (n.dataset.tab === tab) n.setAttribute('aria-current', 'page'); else n.removeAttribute('aria-current'); });
    all('[data-panel]').forEach(n => { n.hidden = n.dataset.panel !== tab; });
    reader.classList.toggle('dw-original', tab === 'original');
    reader.classList.toggle('dw-financial-mode', tab === 'financials');
    reader.classList.remove('dw-expanded');
    updateExpandControl();
    if (updateURL) { const current = new URL(location.href); current.searchParams.set('tab', tab); history.pushState({}, '', current); }
    restorePositions();
  }
  all('[data-tab]').forEach(n => n.addEventListener('click', event => {
    const current = new URL(location.href);
    if (n.dataset.tab === 'process' && current.searchParams.get('run') && current.searchParams.get('run') !== selection.run) {
      current.searchParams.set('tab', 'process');
      n.href = current.toString();
      return; // The chosen run's saved process is loaded and validated on the server.
    }
    event.preventDefault(); switchTab(n.dataset.tab);
  }));
  addEventListener('popstate', () => {
    const target = new URL(location.href);
    // Same-document history remains in the current material and never borrows another scope.
    if (target.searchParams.get('dataset') !== selection.dataset || target.searchParams.get('source') !== selection.source) { location.reload(); return; }
    switchTab(target.searchParams.get('tab') || 'original', false);
    if (!selectFactFromURL(target)) clearFact();
  });
  switchTab(activeTab, false, false);
  function updateExpandControl() {
    const expanded = reader.classList.contains('dw-expanded');
    q('#dw-expand-source').hidden = activeTab === 'original';
    q('#dw-expand-source').setAttribute('aria-pressed', String(expanded));
    q('[data-expand-label]').hidden = expanded;
    q('[data-collapse-label]').hidden = !expanded;
  }
  q('#dw-expand-source').addEventListener('click', () => {
    if (activeTab === 'original') return;
    reader.classList.toggle('dw-expanded');
    updateExpandControl();
  });
  const divider = q('#dw-divider');
  function width(value) {
    const clamped = Math.max(25, Math.min(75, Number(value)));
    if (!Number.isFinite(clamped)) return;
    reader.style.setProperty('--source-width', clamped + '%');
    divider.setAttribute('aria-valuenow', String(Math.round(clamped)));
    store.set('source-width', clamped);
  }
  width(store.get('source-width') || 50);
  divider.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); width(Number(divider.getAttribute('aria-valuenow')) + (event.key === 'ArrowLeft' ? -5 : 5)); }
  });
  divider.addEventListener('pointerdown', event => {
    divider.setPointerCapture(event.pointerId); document.body.classList.add('dw-resizing');
    const move = e => { const box = reader.getBoundingClientRect(); width((e.clientX - box.left) / box.width * 100); };
    const stop = () => { divider.removeEventListener('pointermove', move); document.body.classList.remove('dw-resizing'); };
    divider.addEventListener('pointermove', move);
    divider.addEventListener('pointerup', stop, {once: true}); divider.addEventListener('pointercancel', stop, {once: true});
  });
  async function locate(block, quote) {
    const sequence = ++locatorRequest;
    if (locatorAbort) locatorAbort.abort();
    locatorAbort = new AbortController();
    pendingFrame = null;
    sourceStatus('checking', '正在核对原文位置…', 'Checking source location…');
    const params = new URLSearchParams({dataset: selection.dataset, source: selection.source, block});
    const cited = q('#dw-source-quote');
    cited.hidden = !quote;
    cited.querySelector('blockquote').textContent = quote || '';
    try {
      const response = await fetch('/data-workspace/source-meta?' + params, {signal: locatorAbort.signal});
      const result = await response.json();
      if (sequence !== locatorRequest) return;
      if (!response.ok) throw new Error(result.error || response.statusText);
      if (result.dataset_id !== selection.dataset || result.source_snapshot_id !== selection.source || result.block_id !== block) throw new Error('Source scope mismatch');
      const src = '/data-workspace/source?' + params + (result.fragment ? '#' + result.fragment : '');
      pendingFrame = {sequence, src, result};
      sourceStatus('loading', '位置已核对，正在载入原件…', 'Location checked; loading the original…');
      q('#dw-source-frame').src = src;
      store.set(context + ':evidence', {block, quote});
    } catch (error) {
      if (error.name === 'AbortError' || sequence !== locatorRequest) return;
      pendingFrame = null;
      sourceStatus('error', '原文定位失败：' + error.message, 'Source location failed: ' + error.message);
      // Remove the previous highlight instead of presenting stale evidence for a new selection.
      q('#dw-source-frame').src = '/data-workspace/source?' + new URLSearchParams({dataset: selection.dataset, source: selection.source});
    }
  }
  q('#dw-source-frame').addEventListener('load', () => {
    if (!pendingFrame || pendingFrame.sequence !== locatorRequest) return;
    const result = pendingFrame.result;
    pendingFrame = null;
    sourceStatus(result.locator_status === 'unavailable' ? 'unavailable' : 'located', result.notice.zh, result.notice.en);
  });
  q('#dw-source-frame').addEventListener('error', () => {
    if (!pendingFrame || pendingFrame.sequence !== locatorRequest) return;
    pendingFrame = null;
    sourceStatus('error', '原件未能载入，请重新定位或稍后重试。', 'The original could not load. Locate it again or retry later.');
  });
  all('[data-locate]').forEach(button => button.addEventListener('click', () => locate(button.dataset.locate, button.dataset.quote)));
  function clearEvidence() {
    locatorRequest++;
    if (locatorAbort) locatorAbort.abort();
    pendingFrame = null;
    q('#dw-source-quote').hidden = true;
    q('#dw-source-quote').querySelector('blockquote').textContent = '';
    sourceStatus('idle', '尚未选择可定位的证据。', 'No locatable evidence selected.');
    q('#dw-source-context').textContent = ''; q('#dw-source-context').hidden = true;
    q('#dw-source-frame').src = '/data-workspace/source?' + new URLSearchParams({dataset: selection.dataset, source: selection.source});
    store.set(context + ':evidence', null);
  }
  function clearFact(removeURL = false) {
    all('[data-fact-target]').forEach(n => n.setAttribute('aria-pressed', 'false'));
    all('.dw-fact-detail').forEach(n => { n.hidden = true; });
    all('.dw-selected-row,.dw-selected-cell').forEach(n => { n.classList.remove('dw-selected-row', 'dw-selected-cell'); });
    q('#dw-fact-inspector')?.classList.remove('has-selection');
    if (q('#dw-inspector-empty')) q('#dw-inspector-empty').hidden = false;
    if (q('#dw-close-inspector')) q('#dw-close-inspector').hidden = true;
    if (q('#dw-return-fact')) q('#dw-return-fact').hidden = true;
    if (removeURL) { const current = new URL(location.href); current.searchParams.delete('fact'); current.searchParams.delete('block'); history.replaceState({}, '', current); }
    clearEvidence();
  }
  function selectFact(button, updateURL = true) {
    if (!button) return;
    if (button.closest('[data-financial-row]')?.hidden) { clearFact(true); return; }
    const previous = all('[data-fact-target]').find(n => n.getAttribute('aria-pressed') === 'true');
    all('[data-fact-target]').forEach(n => n.setAttribute('aria-pressed', String(n === button)));
    all('.dw-fact-detail').forEach(n => { n.hidden = n.id !== 'fact-' + button.dataset.factTarget; });
    const detail = document.getElementById('fact-' + button.dataset.factTarget);
    all('.dw-selected-row,.dw-selected-cell').forEach(n => { n.classList.remove('dw-selected-row', 'dw-selected-cell'); });
    button.closest('[data-financial-row]')?.classList.add('dw-selected-row');
    button.closest('td')?.classList.add('dw-selected-cell');
    q('#dw-fact-inspector')?.classList.add('has-selection');
    if (q('#dw-inspector-empty')) q('#dw-inspector-empty').hidden = true;
    if (q('#dw-close-inspector')) q('#dw-close-inspector').hidden = false;
    if (q('#dw-return-fact')) q('#dw-return-fact').hidden = false;
    if (previous !== button && q('#dw-fact-details')) q('#dw-fact-details').scrollTop = 0;
    q('#dw-source-context').textContent = [button.dataset.factLabel, button.dataset.factPeriod].filter(Boolean).join(' · ');
    q('#dw-source-context').hidden = !q('#dw-source-context').textContent;
    const evidence = detail.querySelector('[data-locate]');
    if (evidence) locate(evidence.dataset.locate, evidence.dataset.quote);
    else clearEvidence();
    if (updateURL) {
      const current = new URL(location.href);
      current.searchParams.set('fact', button.dataset.fact);
      if (button.dataset.run) current.searchParams.set('run', button.dataset.run); else current.searchParams.delete('run');
      current.searchParams.delete('block'); history.replaceState({}, '', current);
    }
  }
  function selectFactFromURL(current) {
    const fact = current.searchParams.get('fact'), run = current.searchParams.get('run') || '';
    const button = all('[data-fact-target]').find(n => n.dataset.fact === fact && n.dataset.run === run);
    if (button) selectFact(button, false);
    return Boolean(button);
  }
  all('[data-fact-target]').forEach(button => button.addEventListener('click', () => selectFact(button)));
  q('#dw-close-inspector')?.addEventListener('click', () => {
    const button = all('[data-fact-target]').find(n => n.getAttribute('aria-pressed') === 'true');
    clearFact(true); button?.focus({preventScroll: true});
  });
  q('#dw-return-fact')?.addEventListener('click', () => {
    const button = all('[data-fact-target]').find(n => n.getAttribute('aria-pressed') === 'true');
    button?.scrollIntoView({block: 'nearest', inline: 'nearest'});
    button?.focus({preventScroll: true});
  });
  function filterFinancials() {
    const query = q('#dw-financial-search').value.toLowerCase();
    const filter = q('#dw-financial-filter').value;
    let count = 0;
    all('[data-financial-row]').forEach(row => {
      const reviewPending = [...row.querySelectorAll('[data-review-status]')].some(n => !['supported', 'value_scope_matched'].includes(n.dataset.reviewStatus));
      row.hidden = !row.textContent.toLowerCase().includes(query) || (filter === 'conflict' && row.dataset.conflict !== 'true') || (filter === 'review' && !reviewPending);
      if (!row.hidden) count++;
    });
    if (q('#dw-financial-empty')) q('#dw-financial-empty').hidden = count !== 0;
    const selected = all('[data-fact-target]').find(n => n.getAttribute('aria-pressed') === 'true');
    if (selected?.closest('[data-financial-row]')?.hidden) clearFact(true);
    store.set(context + ':financial-filter', {query, filter});
  }
  const savedFilter = store.get(context + ':financial-filter');
  if (savedFilter) { q('#dw-financial-search').value = savedFilter.query || ''; q('#dw-financial-filter').value = savedFilter.filter || 'all'; }
  q('#dw-financial-search').addEventListener('input', filterFinancials);
  q('#dw-financial-filter').addEventListener('change', filterFinancials);
  filterFinancials();
  let changing = false;
  const savedChoices = new Map(all('[data-task-choice]').map(n => [n, n.value]));
  async function change(action, task, run) {
    if (changing) return;
    changing = true;
    all('[data-state-action],[data-task-choice]').forEach(n => { n.disabled = true; });
    savePositions();
    try {
      const response = await fetch('/api/data-workspace/state', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Uteki-Request': '1'}, body: JSON.stringify({action, expected_revision: config.revision, dataset_id: selection.dataset, source_snapshot_id: selection.source, task_id: task, run_id: run})});
      const result = await response.json();
      if (!response.ok) throw new Error(response.status === 409 ? text('另一个页面已修改展示状态，请刷新后重试。', 'Another page changed this view. Refresh and retry.') : result.error || response.statusText);
      const target = new URL(location.href); target.searchParams.delete('fact'); target.searchParams.delete('run');
      if (action === 'select_version') { target.searchParams.delete('base'); target.searchParams.set('tab', 'financials'); }
      location.replace(target);
    } catch (error) {
      message('保存失败：' + error.message, 'Save failed: ' + error.message);
      changing = false;
      all('[data-state-action],[data-task-choice]').forEach(n => { n.disabled = false; });
      savedChoices.forEach((value, node) => { node.value = value; });
    }
  }
  all('[data-task-choice]').forEach(n => n.addEventListener('change', () => change('select_version', n.dataset.taskChoice, n.value || null)));
  all('[data-state-action]').forEach(n => n.addEventListener('click', () => change(n.dataset.stateAction, n.dataset.task, n.dataset.run)));
  // Preserve native reading; scrolling never changes company, material, or tab.
  if (!selectFactFromURL(new URL(location.href))) {
    const previous = store.get(context + ':evidence');
    if (selection.block) locate(selection.block);
    else if (previous && previous.block) locate(previous.block, previous.quote);
  }
  requestAnimationFrame(restorePositions);
})();
