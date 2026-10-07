(function (root) {
  'use strict';

  const STATUS = {completed: '已回复', failed: '未交付', interrupted: '已中断', running: '正在回复'};
  function statusLabel(status) { return STATUS[status] || '状态未记录'; }
  function actorLabel(actor) { return actor === 'codex' ? 'Codex' : actor === 'user' ? '你' : '历史提问'; }
  function preview(text, length = 100) {
    const value = String(text || '').replace(/\s+/gu, ' ').trim();
    return value.length > length ? value.slice(0, length) + '…' : value;
  }
  function numericAmount(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value === 'string' && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim())) return Number.isFinite(Number(value)) ? Number(value) : null;
    return null;
  }
  function money(value) { const amount = numericAmount(value); return amount === null ? '未记录' : '$' + amount.toFixed(4); }
  function blockingText(conversation) {
    if (!conversation) return '';
    if (conversation.pending) return '';
    const reason = conversation.budget && conversation.budget.send_blocked_reason;
    if (reason === 'budget_insufficient') return '当前额度不足以预留下一次完整请求。可在左侧配置中调整总上限。';
    if (reason === 'request_too_large') return '当前完整上下文超过请求上限。请先核对会话材料，暂不能继续发送。';
    if (reason === 'previous_turn_failed_or_interrupted' || conversation.blocked) return '上一轮未完整完成。请先核对结果与费用；会话暂停发送，不会自动重试。';
    return reason ? '当前会话暂停发送。原因：' + String(reason) : '';
  }
  function shouldSendKey(event) {
    return Boolean(event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing && !event.repeat);
  }
  function budgetPayload(value, revision) {
    const text = String(value).trim();
    if (!/^\d+(?:\.\d+)?$/.test(text) || !Number.isFinite(Number(text)) || Number(text) <= 0) {
      throw new Error('请输入大于 0 的美元总上限。');
    }
    return {limit_usd: Number(text), expected_revision: revision};
  }
  function normalizeConversation(value) {
    if (!value || typeof value.revision !== 'string' || !value.revision || !Array.isArray(value.turns)) {
      throw new Error('会话数据格式不完整，请刷新后重试。');
    }
    const seen = new Set();
    const turns = value.turns.map(turn => {
      if (!turn || !Number.isInteger(turn.number) || turn.number < 1 || seen.has(turn.number) || typeof turn.user !== 'string' || (turn.answer != null && typeof turn.answer !== 'string')) {
        throw new Error('历史轮次数据不完整，已保留当前阅读内容。');
      }
      seen.add(turn.number);
      return {...turn, answer: turn.answer == null ? '' : turn.answer};
    }).sort((a, b) => a.number - b.number);
    return {...value, turns};
  }
  function errorText(error) {
    const code = String(error && error.code || '');
    const explanations = {
      budget_exceeded: '剩余额度不足。请检查累计额度，必要时调整总上限。',
      budget_blocked: '额度状态待核对，本次没有继续发送。',
      budget_insufficient: '剩余额度不足。请检查累计额度，必要时调整总上限。',
      request_or_cumulative_budget_exceeded: '剩余额度不足以预留本次完整请求。请检查累计额度。',
      session_budget_exhausted: '会话额度不足。请检查累计额度。',
      previous_turn_failed_or_interrupted: '上一轮未完整完成。请先核对结果与费用；不会自动重试。',
      pending: '已有请求正在执行，请等待当前回复。',
      busy: '已有请求正在执行，请等待当前回复。',
      revision_conflict: '会话已更新。已保留输入；请查看最新历史后再发送。',
      stale_revision: '会话已更新。已保留输入；请查看最新历史后再发送。',
      interrupted: '本次请求已中断，未得到完整回复。输入仍保留。',
      failed: '本次请求未完整完成，输入仍保留。请核对本轮状态与费用。',
      submission_state_invalid: '本次请求的状态无法核实，输入仍保留。请刷新查看；不会自动重发。',
      upstream_error: 'Claude 请求失败，未得到完整回复。输入仍保留。',
      csrf_invalid: '页面会话已失效，请刷新页面。输入尚未发送。'
    };
    let lead = explanations[code];
    if (!lead) {
      const status = error && error.status;
      lead = status === 409 ? '当前会话或额度状态不允许发送。已保留输入，请先查看最新状态。'
        : status === 502 ? 'Claude 服务调用失败，未得到完整回复。输入仍保留。'
        : status === 401 || status === 403 ? '页面会话验证失败，请点击上方“刷新”重新连接。输入仍保留。'
        : status === 429 ? '请求过于频繁，请稍后手动重试。'
        : status === 400 ? '请求未被接受，请检查输入与额度。'
        : status ? '本机服务暂时无法处理请求，输入仍保留。'
        : '无法连接本机服务。已保留历史与输入；不会自动重发。';
    }
    const detail = error && error.publicMessage;
    return lead + (typeof detail === 'string' && detail && detail !== lead ? '\n' + detail : '') + (code ? '\n错误代码：' + code : '');
  }
  async function requestJSON(url, options) {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 15000);
    try {
      const response = await fetch(url, {cache: 'no-store', credentials: 'same-origin', redirect: 'error', ...options, signal: abort.signal});
      let payload;
      try { payload = await response.json(); } catch (_) { payload = null; }
      if (!response.ok) {
        const error = new Error('Local service request failed');
        error.status = response.status;
        error.code = payload && payload.error && payload.error.code;
        error.publicMessage = payload && payload.error && payload.error.message;
        throw error;
      }
      if (!payload) throw new Error('Missing JSON response');
      return payload;
    } finally { clearTimeout(timeout); }
  }

  function createController({request = requestJSON, onChange = () => {}, onCompleted = () => {}, newId = () => root.crypto.randomUUID()} = {}) {
    let token = null, readSequence = 0, attempt = null;
    const state = {conversation: null, sessionReady: false, loading: false, writing: false, waiting: false, notice: '', noticeKind: 'info', connectionError: '', budgetSaved: 0};
    const publish = () => onChange({...state});
    const writeOptions = payload => ({method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': token}, body: JSON.stringify(payload)});
    function terminal(submission) {
      if (!attempt || !submission || submission.client_request_id !== attempt.id) return false;
      if (submission.status === 'running') { state.waiting = true; return false; }
      if (!['completed', 'failed', 'interrupted'].includes(submission.status)) return false;
      const text = attempt.message;
      attempt = null;
      state.waiting = false;
      if (submission.status === 'completed') {
        state.notice = 'Claude 已回复。'; state.noticeKind = 'info'; onCompleted(text);
      } else {
        state.notice = errorText({status: 502, code: submission.error_code || submission.status, publicMessage: submission.error_message}); state.noticeKind = 'error';
      }
      return true;
    }
    async function reconcile(conversation, sequence) {
      if (!attempt) return;
      if (conversation.last_submission && conversation.last_submission.client_request_id === attempt.id) {
        terminal(conversation.last_submission); return;
      }
      if (conversation.pending && conversation.pending.client_request_id === attempt.id) { state.waiting = true; return; }
      const requestId = attempt.id;
      try {
        // Another client can replace the latest submission. Only its durable
        // request ID identifies our result; matching text is never evidence.
        const value = await request('/api/submissions/' + encodeURIComponent(requestId));
        if (sequence !== readSequence || !attempt || attempt.id !== requestId) return;
        const submission = value && value.submission;
        if (!submission || submission.client_request_id !== requestId || !['running', 'completed', 'failed', 'interrupted'].includes(submission.status)) {
          throw Object.assign(new Error('Invalid submission response'), {code: 'submission_state_invalid'});
        }
        terminal(submission);
      } catch (error) {
        if (sequence !== readSequence || !attempt || attempt.id !== requestId) return;
        if (error.status === 404) {
          state.notice = '暂未找到这次请求的记录。输入仍保留，请刷新核对；系统不会自动重发。';
          state.noticeKind = 'error';
          return;
        }
        throw error;
      }
    }
    async function load() {
      if (state.writing) return false;
      const sequence = ++readSequence;
      state.loading = true; publish();
      try {
        const value = normalizeConversation(await request('/api/conversation'));
        if (sequence !== readSequence) return false;
        state.conversation = value; state.connectionError = ''; await reconcile(value, sequence);
        return sequence === readSequence;
      } catch (error) {
        if (sequence === readSequence) state.connectionError = errorText(error);
        return false;
      } finally { if (sequence === readSequence) { state.loading = false; publish(); } }
    }
    async function start() {
      try {
        const session = await request('/api/session');
        if (typeof session.csrf_token !== 'string' || !session.csrf_token) throw new Error('Missing session token');
        token = session.csrf_token; state.sessionReady = true; state.notice = ''; state.noticeKind = 'info';
      } catch (error) { state.notice = errorText(error); state.noticeKind = 'error'; publish(); }
      return load();
    }
    async function send(message) {
      const conversation = state.conversation;
      if (state.writing || state.waiting || (conversation && conversation.pending) || blockingText(conversation) || !state.sessionReady || !conversation || typeof message !== 'string' || !message.trim()) return false;
      if (!attempt || attempt.message !== message) {
        attempt = {id: newId(), message, revision: conversation.revision};
      }
      const submitted = attempt;
      ++readSequence; state.loading = false; state.writing = true;
      state.notice = ''; state.noticeKind = 'info'; publish();
      try {
        const response = await request('/api/messages', writeOptions({message, expected_revision: submitted.revision, client_request_id: submitted.id}));
        if (response.accepted !== true) throw new Error('Missing acceptance receipt');
        state.waiting = true;
        state.notice = response.replayed ? '已找回这次请求的记录，正在同步状态；没有再次调用模型。' : '请求已接受，正在等待 Claude 回复。输入在成功回复前保留。';
        terminal(response.submission);
        state.writing = false; publish();
        await load();
        return true;
      } catch (error) {
        state.notice = errorText(error); state.noticeKind = 'error';
        // Retain an uncertain request ID in memory for an explicit retry only.
        // A definite 4xx rejection is not an accepted request.
        if (error.status >= 400 && error.status < 500) attempt = null;
        if (error.status === 401 || error.status === 403) state.sessionReady = false;
        state.writing = false; publish();
        await load();
        return false;
      }
    }
    async function saveBudget(value) {
      if (state.writing || !state.sessionReady || !state.conversation) return false;
      let payload;
      try { payload = budgetPayload(value, state.conversation.revision); }
      catch (error) { state.notice = error.message; state.noticeKind = 'error'; publish(); return false; }
      ++readSequence; state.loading = false; state.writing = true; state.notice = ''; publish();
      try {
        await request('/api/budget', writeOptions(payload));
        state.budgetSaved += 1; state.notice = '累计额度上限已保存。'; state.noticeKind = 'info';
        state.writing = false; publish();
        if (!(await load())) { state.notice = '额度已保存，但最新状态尚未加载。请刷新查看，无须重复保存。'; publish(); }
        return true;
      } catch (error) { state.writing = false; if (error.status === 401 || error.status === 403) state.sessionReady = false; state.notice = errorText(error); state.noticeKind = 'error'; publish(); await load(); return false; }
    }
    return {start, load, send, saveBudget, state: () => ({...state})};
  }

  function mount(document) {
    const byId = id => document.getElementById(id);
    const history = byId('history'), thread = byId('thread'), input = byId('message-input');
    const turns = new Map(), links = new Map();
    let lastState = null, budgetDirty = false, budgetSaved = 0, firstLoad = true, selected = null;
    function el(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    }
    function setNotice(text, kind = 'info') { const node = byId('notice'); node.textContent = text; node.dataset.kind = kind; node.hidden = !text; }
    function capturePosition() {
      const top = history.getBoundingClientRect().top;
      const visible = Array.from(turns.values()).find(view => view.node.getBoundingClientRect().bottom > top + 1);
      return {scrollTop: history.scrollTop, number: visible && visible.number, offset: visible ? visible.node.getBoundingClientRect().top - top : 0};
    }
    function restorePosition(position) {
      const view = turns.get(position.number);
      if (view) history.scrollTop += view.node.getBoundingClientRect().top - history.getBoundingClientRect().top - position.offset;
      else history.scrollTop = position.scrollTop;
    }
    function jump(number) {
      const view = turns.get(number);
      if (!view) return;
      selected = number;
      history.scrollTop += view.node.getBoundingClientRect().top - history.getBoundingClientRect().top - 20;
      for (const [key, link] of links) link.button.setAttribute('aria-current', String(key === number));
    }
    async function copy(text, button) {
      try { await root.navigator.clipboard.writeText(text); button.textContent = '已复制全文'; setTimeout(() => { button.textContent = '复制全文'; }, 1800); }
      catch (_) { setNotice('复制未成功。请展开消息后选择文字复制。', 'error'); }
    }
    function fillMessage(slot, text, role, actor, actorRecorded) {
      const wasOpen = slot.querySelector('details') && slot.querySelector('details').open;
      slot.replaceChildren(); slot.dataset.role = role;
      const head = el('div', 'message-head'), author = el('div', 'message-author', role === 'answer' ? 'Claude' : actorLabel(actor));
      author.append(el('small', '', role === 'answer' ? 'Assistant' : actorRecorded === false ? '历史导入' : actor === 'codex' ? 'Codex 发起' : actor === 'user' ? '手工发送' : '历史消息'));
      const copyButton = el('button', 'copy-button', '复制全文'); copyButton.type = 'button'; copyButton.addEventListener('click', () => copy(text, copyButton));
      head.append(author, copyButton); slot.append(head);
      const body = el('pre', 'message-body', text);
      if (text.length > 2400 || text.split('\n').length > 36) {
        const teaser = el('p', 'message-preview', preview(text, 180));
        const detail = el('details', 'message-details'); detail.open = Boolean(wasOpen);
        const summary = el('summary', '', `展开原文 · ${text.length.toLocaleString('zh-CN')} 字符`);
        detail.append(summary, body); slot.append(teaser, detail);
        detail.addEventListener('toggle', () => { summary.textContent = `${detail.open ? '收起原文' : '展开原文'} · ${text.length.toLocaleString('zh-CN')} 字符`; teaser.hidden = detail.open; });
      } else slot.append(body);
    }
    function renderTurn(turn) {
      let view = turns.get(turn.number);
      if (!view) {
        const node = el('article', 'turn'); node.id = 'turn-' + turn.number;
        const heading = el('div', 'turn-heading'), title = el('h3', '', `第 ${turn.number} 轮`); title.id = node.id + '-title'; node.setAttribute('aria-labelledby', title.id);
        const status = el('span', 'turn-state'), metadata = el('span', 'turn-model');
        heading.append(title, status, metadata);
        const user = el('section', 'message'), answer = el('section', 'message'), error = el('p', 'turn-error');
        node.append(heading, user, answer, error); thread.append(node);
        view = {number: turn.number, node, status, metadata, user, answer, error, signature: null}; turns.set(turn.number, view);
        const li = el('li'), button = el('button', 'round-button'); button.type = 'button';
        const meta = el('div', 'round-meta'), label = el('span', '', `第 ${turn.number} 轮`), state = el('span'), text = el('div', 'round-preview');
        meta.append(label, state); button.append(meta, text); li.append(button); byId('turn-list').append(li);
        button.addEventListener('click', () => jump(turn.number)); links.set(turn.number, {li, button, state, text});
      }
      const signature = JSON.stringify(turn);
      if (view.signature === signature) return false;
      const previous = view.value;
      view.signature = signature; view.value = turn;
      view.status.textContent = statusLabel(turn.status);
      view.status.dataset.kind = ['failed', 'interrupted'].includes(turn.status) ? 'error' : turn.status === 'running' ? 'running' : 'complete';
      const time = turn.started_at ? new Date(turn.started_at) : null;
      const timeLabel = time && !Number.isNaN(time.valueOf()) ? time.toLocaleString('zh-CN', {hour12: false}) : '时间未记录';
      view.metadata.textContent = `${turn.model || '模型未记录'} · ${timeLabel}${time ? '（本地时间）' : ''} · ${money(turn.estimated_usd)}${numericAmount(turn.estimated_usd) !== null ? ' 估算' : ''}`;
      view.metadata.title = turn.started_at || '';
      if (!previous || previous.user !== turn.user || previous.actor !== turn.actor || previous.actor_recorded !== turn.actor_recorded) fillMessage(view.user, turn.user, 'user', turn.actor, turn.actor_recorded);
      if (!previous || previous.answer !== turn.answer || previous.status !== turn.status) {
        if (turn.answer) fillMessage(view.answer, turn.answer, 'answer');
        else view.answer.replaceChildren(el('p', 'answer-placeholder', turn.status === 'running' ? 'Claude 正在回复…' : ['failed', 'interrupted'].includes(turn.status) ? '本轮没有完整交付。提问与已有记录保留。' : '未记录回复内容。'));
      }
      view.error.textContent = ['failed', 'interrupted'].includes(turn.status) ? errorText({status: 502, code: turn.error_code || turn.status, publicMessage: turn.error_message}) : '';
      view.error.hidden = !view.error.textContent;
      const link = links.get(turn.number); link.state.textContent = `${actorLabel(turn.actor)} · ${statusLabel(turn.status)}`; link.text.textContent = preview(turn.user, 110);
      return true;
    }
    function renderConfiguration(conversation) {
      const c = conversation.configuration || {}, budget = conversation.budget || {};
      byId('model-label').textContent = conversation.model || '模型未记录';
      byId('remaining-budget').textContent = money(budget.remaining_usd);
      byId('spent-budget').textContent = money(budget.spent_usd); byId('held-budget').textContent = money(budget.held_usd); byId('limit-budget').textContent = money(budget.limit_usd);
      byId('next-reservation').textContent = money(budget.minimum_next_turn_reserved_usd);
      if (!budgetDirty && document.activeElement !== byId('budget-limit')) byId('budget-limit').value = numericAmount(budget.limit_usd) !== null ? String(budget.limit_usd) : '';
      const fields = [['模型', conversation.model || '未记录'], ['供应商', c.provider || '未记录'], ['Thinking', c.thinking && c.thinking.type || '未记录'], ['Effort', c.effort || c.output_config && c.output_config.effort || '未记录'], ['输出上限', c.max_tokens == null ? '未记录' : String(c.max_tokens)], ['Stream', c.stream === false ? '关闭 / false' : c.stream === true ? '开启 / true' : '未记录']];
      const box = byId('configuration-values');
      const signature = JSON.stringify(fields);
      if (box.dataset.signature !== signature) { box.replaceChildren(...fields.map(([label, value]) => { const row = el('div'); row.append(el('dt', '', label), el('dd', '', value)); return row; })); box.dataset.signature = signature; }
    }
    function updateControls() {
      if (!lastState) return;
      const pending = lastState.waiting || Boolean(lastState.conversation && lastState.conversation.pending);
      const blocked = blockingText(lastState.conversation);
      byId('send-message').disabled = !lastState.sessionReady || !lastState.conversation || lastState.writing || pending || Boolean(blocked) || !input.value.trim();
      byId('send-message').textContent = lastState.writing ? '正在提交…' : pending ? '等待 Claude…' : '发送给 Claude';
      byId('save-budget').disabled = !lastState.sessionReady || !lastState.conversation || lastState.writing;
      byId('refresh').disabled = lastState.loading || lastState.writing;
      byId('composer-hint').textContent = pending ? '当前请求完成后可继续发送；可以先编辑下一条。' : blocked ? '会话暂停发送 · 请查看状态说明' : 'Enter 换行 · ⌘ / Ctrl + Enter 发送';
    }
    function render(state) {
      lastState = state;
      if (state.budgetSaved !== budgetSaved) { budgetDirty = false; budgetSaved = state.budgetSaved; }
      const connection = byId('connection-status');
      connection.textContent = state.connectionError ? '连接暂不可用 · 历史已保留' : state.conversation && (state.waiting || state.conversation.pending) ? 'Claude 正在回复' : state.conversation ? '本机已连接 · 自动同步' : '正在连接本机服务…';
      connection.dataset.kind = state.connectionError ? 'error' : 'info';
      const blocked = blockingText(state.conversation);
      setNotice([state.notice, state.connectionError, blocked].filter(Boolean).join('\n'), state.connectionError || state.noticeKind === 'error' || blocked ? 'error' : 'info');
      if (state.conversation) {
        const position = capturePosition(); let changed = false;
        const wanted = new Set(state.conversation.turns.map(turn => turn.number));
        for (const [number, view] of turns) if (!wanted.has(number)) { view.node.remove(); turns.delete(number); links.get(number).li.remove(); links.delete(number); }
        byId('empty-message').hidden = state.conversation.turns.length > 0;
        byId('empty-message').textContent = '当前会话暂无消息。发送后会继续保存在同一份上下文中。';
        for (const turn of state.conversation.turns) changed = renderTurn(turn) || changed;
        // Existing nodes are retained on polling. Never jump to the newest turn.
        if (!firstLoad) restorePosition(position);
        if (changed && !firstLoad) byId('latest').hidden = false;
        firstLoad = false;
        byId('turn-count').textContent = String(state.conversation.turns.length);
        renderConfiguration(state.conversation);
      } else if (state.connectionError) byId('empty-message').textContent = '未能加载对话。请确认本机服务已启动，然后点击刷新重试。';
      updateControls();
    }
    const controller = createController({onChange: render, onCompleted: text => { if (input.value === text) input.value = ''; }});
    input.addEventListener('input', updateControls);
    input.addEventListener('keydown', event => { if (shouldSendKey(event)) { event.preventDefault(); controller.send(input.value); } });
    byId('message-form').addEventListener('submit', event => { event.preventDefault(); controller.send(input.value); });
    byId('budget-limit').addEventListener('input', () => { budgetDirty = true; });
    byId('budget-form').addEventListener('submit', event => { event.preventDefault(); controller.saveBudget(byId('budget-limit').value); });
    byId('refresh').addEventListener('click', () => { if (!controller.state().sessionReady) controller.start(); else controller.load(); });
    byId('latest').addEventListener('click', () => { history.scrollTop = history.scrollHeight; byId('latest').hidden = true; });
    history.addEventListener('scroll', () => { if (history.scrollHeight - history.scrollTop - history.clientHeight < 40) byId('latest').hidden = true; }, {passive: true});
    controller.start();
    const poll = setInterval(() => { if (!document.hidden) controller.load(); }, 3000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) controller.load(); });
    root.addEventListener('pagehide', () => clearInterval(poll), {once: true});
  }

  const api = {statusLabel, actorLabel, preview, numericAmount, money, blockingText, shouldSendKey, budgetPayload, normalizeConversation, errorText, createController};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else { root.ClaudeDialogue = api; if (root.document) mount(root.document); }
})(typeof globalThis !== 'undefined' ? globalThis : this);
