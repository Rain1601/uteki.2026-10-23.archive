(function (root) {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bi = (zh, en) => `<span lang="zh">${escape(zh)}</span><span lang="en">${escape(en)}</span>`;
  const known = value => value === null || value === undefined || value === '' ? bi('未记录', 'Not recorded') : escape(typeof value === 'number' ? value.toLocaleString('en-US') : value);
  const runURL = id => '/agent-runs?' + new URLSearchParams({agent:'data',run:id});
  const apiRun = (base, id) => base + '/' + encodeURIComponent(id);
  const configFields = ['provider','model','api_format','base_url','max_tokens','thinking','reasoning_effort','temperature','top_p','top_k','seed','response_format','tool_choice','parallel_tool_calls','stream','timeout_seconds','max_retries'];
  const configLabels = {temperature:['采样温度','Temperature'],top_p:['累计概率','Top-P'],top_k:['候选 token 数','Top-K']};
  const configPolicies = {
    'policy.sonnet55_sampling_unsupported':[['temperature','top_p','top_k'],'按记录的模型规则，不接受非默认采样设置。','The recorded model policy does not permit non-default sampling settings.'],
    'policy.deepseek_thinking_sampling_ignored':[['temperature'],'按记录的模型规则，思考模式忽略 temperature。','The recorded model policy ignores temperature in thinking mode.'],
    'policy.deepseek_top_k_unsupported':[['top_k'],'记录的 API 文档未列出 Top-K，因此未发送。','The recorded API documentation does not list Top-K, so it was not sent.'],
    'policy.seed_not_documented':[['seed'],'记录的 API 文档未列出 seed，因此未发送。','The recorded API documentation does not list seed, so it was not sent.']
  };
  function observedTime(value) {
    if (typeof value !== 'string') return null;
    const parts=value.match(/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/);
    if (!parts || Number(parts[4])>23 || Number(parts[5])>59 || Number(parts[6])>59) return null;
    const date=new Date(Date.UTC(Number(parts[1]),Number(parts[2])-1,Number(parts[3])));
    if (date.getUTCFullYear()!==Number(parts[1]) || date.getUTCMonth()+1!==Number(parts[2]) || date.getUTCDate()!==Number(parts[3])) return null;
    const milliseconds=Date.parse(value);
    if (!Number.isFinite(milliseconds)) return null;
    return {beijing:new Date(milliseconds+8*3600000).toISOString().slice(0,19).replace('T',' ')+' UTC+08:00',
      utc:/(?:Z|\+00:00)$/.test(value) ? value.replace(/\+00:00$/,'Z') : new Date(milliseconds).toISOString()};
  }
  function callTimingHTML(call) {
    const fields=[['started_at','调用开始（北京时间）','Call started (Beijing time)'],['ended_at','调用结束（北京时间）','Call ended (Beijing time)']];
    const rows=fields.map(([key,zh,en])=>({value:observedTime(call[key]),label:bi(zh,en)}));
    return `<div class="model-call-timing" data-call-time="${escape(call.call_id)}"><dl>${rows.map(({value,label})=>`<div><dt>${label}</dt><dd>${value ? `<time datetime="${escape(value.utc)}" title="${escape(value.utc)}">${escape(value.beijing)}</time>` : known(null)}</dd></div>`).join('')}</dl><details data-detail-key="utc-${escape(call.call_id)}"><summary>${bi('查看 UTC 时间','Inspect UTC timestamps')}</summary>${rows.map(({value,label})=>`<p>${label}: ${value ? escape(value.utc) : known(null)}</p>`).join('')}</details></div>`;
  }
  function configurationSnapshotHTML(call) {
    const snapshot=call.configuration_snapshot?.schema_version==='model-call-config-v1' ? call.configuration_snapshot : {};
    const kind=snapshot.capture_kind;
    const capture=kind==='before_dispatch' ? bi('发送前记录','Captured before dispatch') : kind==='historical_partial' ? bi('历史部分记录','Partial historical record') : bi('未记录配置快照','Configuration snapshot not recorded');
    const labels={explicit:['明确指定','Explicit'],recorded:['已有记录','Recorded'],not_sent:['未发送','Not sent']};
    const rows=configFields.map(key=>{
      const field=snapshot.fields?.[key] || {}, knownValue=['explicit','recorded'].includes(field.status) && Object.hasOwn(field,'value');
      const value=knownValue ? escape(typeof field.value==='string' ? field.value : JSON.stringify(field.value)) : field.status==='not_sent' ? bi('未发送','Not sent') : known(null);
      const policy=Object.hasOwn(configPolicies,field.source) ? configPolicies[field.source] : null;
      const explanation=field.status==='not_sent' && policy?.[0].includes(key) ? '<small>'+bi(policy[1],policy[2])+'</small>' : '';
      return `<tr data-config-field="${key}"><td>${configLabels[key] ? bi(...configLabels[key]) : key}</td><td>${value}</td><td>${labels[field.status] ? bi(...labels[field.status]) : known(null)}</td><td>${known(field.source)}${explanation}</td></tr>`;
    }).join('');
    const fingerprints=snapshot.fingerprints && typeof snapshot.fingerprints==='object' && Object.keys(snapshot.fingerprints).length ? `<details data-detail-key="fingerprints-${escape(call.call_id)}"><summary>${bi('核对指纹','Verification fingerprints')}</summary><pre>${escape(JSON.stringify(snapshot.fingerprints,null,2))}</pre></details>` : '';
    return `<details class="model-call-snapshot" data-detail-key="config-${escape(call.call_id)}" data-call-snapshot="${escape(call.call_id)}"><summary>${bi('调用配置快照','Call configuration snapshot')} · ${capture}</summary><p class="model-call-note">${bi('这里显示已记录的请求配置。供应商实际生效配置尚未验证；未记录字段不补成默认值。','These are recorded request settings. The provider’s effective configuration is unverified; missing fields are not filled with defaults.')}</p><p class="model-call-note">${bi('未发送不代表已知默认值。未发送原因来自记录的文档政策，不是供应商回显；固定采样参数也不保证逐字复现。','Not sent does not mean a known default. Omission reasons are recorded documentation policies, not provider echoes; fixed sampling settings do not guarantee identical output.')}</p><p class="model-call-hash">SHA256: ${known(snapshot.sha256)}</p><div class="model-call-table-scroll"><table class="model-call-table"><thead><tr>${[['字段','Field'],['值','Value'],['记录状态','Record status'],['来源','Source']].map(label=>'<th>'+bi(...label)+'</th>').join('')}</tr></thead><tbody>${rows}</tbody></table></div>${fingerprints}</details>`;
  }
  function callConfigurationHTML(call) {
    return `<div class="model-call-record" data-config-call="${escape(call.call_id)}"><p class="model-call-label">${escape(call.call_id)} · ${known(call.role)} · ${known(call.provider)} · ${known(call.requested_model)} · ${bi('推理档位','Reasoning effort')}: ${known(call.reasoning_effort)}</p>${callTimingHTML(call)}${configurationSnapshotHTML(call)}</div>`;
  }
  function callTimeRecordsHTML(calls) {
    return calls.map(call=>`<div class="model-call-record" data-timed-call="${escape(call.call_id)}"><p class="model-call-label">${escape(call.call_id)} · ${known(call.requested_model)}</p>${callTimingHTML(call)}</div>`).join('');
  }
  function updateCallRecords(container, calls, render) {
    if (!container) return;
    const signature=JSON.stringify(calls.map(call=>[call.call_id,call.role,call.provider,call.requested_model,call.reasoning_effort,call.started_at,call.ended_at,call.configuration_snapshot]));
    if (container.dataset.callRecordSignature===signature) return;
    const open=new Set(Array.from(container.querySelectorAll?.('details[open]') || []).map(node=>node.dataset.detailKey));
    const active=container.ownerDocument?.activeElement;
    const focused=container.contains(active) ? active.closest?.('[data-detail-key]')?.dataset.detailKey : null;
    container.innerHTML=render(calls);container.dataset.callRecordSignature=signature;
    for(const node of container.querySelectorAll?.('[data-detail-key]') || []) {
      if(open.has(node.dataset.detailKey)) node.open=true;
      if(focused===node.dataset.detailKey) node.querySelector('summary')?.focus({preventScroll:true});
    }
  }
  function artifactURL(base, run, id, {cursor, browse} = {}) {
    const query = new URLSearchParams();
    if (cursor !== null && cursor !== undefined) query.set('cursor', String(cursor));
    if (browse !== null && browse !== undefined) query.set('browse', String(browse));
    return apiRun(base, run) + '/artifacts/' + encodeURIComponent(id) + (query.size ? '?' + query : '');
  }

  // The cursor advances only after the entire response has been accepted by the
  // reader. A terminal event does not stop pagination before its tail is drained.
  function createPoller({read, apply, onState = () => {}, isHidden = () => false,
      setTimer = setTimeout, clearTimer = clearTimeout, interval = 2000}) {
    let timer = null, busy = false, disposed = false, ended = false, retry = interval;
    let cursor = null, terminal = false, pending = false, hidden = isHidden();
    function schedule(delay) {
      if (timer !== null) clearTimer(timer);
      timer = null;
      if (!disposed && !hidden && (!ended || pending)) timer = setTimer(() => {timer = null; tick();}, delay);
    }
    async function tick(force = false) {
      if (disposed || hidden) return;
      if (busy) { if (force) pending = true; return; }
      if (ended && !force) return;
      if (timer !== null) { clearTimer(timer); timer = null; }
      busy = true; pending = false;
      try {
        const page = await read(cursor);
        if (disposed) return;
        if (!page || !Array.isArray(page.events) || typeof page.has_more !== 'boolean' || typeof page.next_cursor !== 'string' || !page.next_cursor) throw new Error('Invalid event response');
        await apply(page);
        if (disposed) return;
        cursor = page.next_cursor;
        terminal = terminal || page.root_terminal === true;
        ended = terminal && !page.has_more;
        retry = interval;
        onState(ended ? 'finished' : page.connection_state || 'connected', page);
        if (page.has_more) pending = true;
      } catch (error) {
        if (!disposed) { onState('error', error); retry = Math.min(30000, retry * 2); }
      } finally {
        busy = false;
        if (!disposed) schedule(pending ? 0 : retry);
      }
    }
    return {
      start() { schedule(0); },
      refresh() { return tick(true); },
      visibilityChanged() {
        hidden = isHidden();
        if (hidden) { if (timer !== null) clearTimer(timer); timer = null; }
        else if (!ended) { if (busy) pending = true; else schedule(0); }
      },
      stop() { disposed = true; if (timer !== null) clearTimer(timer); timer = null; },
      state() { return {busy, ended, terminal, cursor, retry, pending}; }
    };
  }

  function mergeRunView(current, incoming) {
    if (!incoming || incoming.id !== current.id || incoming.root_run_id !== current.root_run_id) throw new Error('Run identity changed');
    if (Number.isFinite(current.revision) && Number.isFinite(incoming.revision) && incoming.revision < current.revision) return current;
    return incoming;
  }

  function timedSteps(detail) {
    if (!detail.live) return [];
    const time = value => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN;
    const rows = (detail.steps || []).flatMap(step => {
      const start = time(step.started_at), end = time(step.ended_at);
      return Number.isFinite(start) && Number.isFinite(end) && end >= start ? [{step,start,end}] : [];
    });
    const origin = Math.min(...rows.map(row => row.start));
    const span = Math.max(...rows.map(row => row.end)) - origin || 1;
    return rows.map(row => ({...row,left:(row.start-origin)/span*100,width:(row.end-row.start)/span*100}));
  }

  function bootstrap(document, environment = root) {
    const q = selector => document.querySelector(selector);
    const all = selector => [...document.querySelectorAll(selector)];
    const configNode = q('#ar-config');
    if (!configNode) return;
    const config = JSON.parse(configNode.textContent);
    let detail = config.detail;
    const selection = config.selection;
    let activeTab = selection.tab || 'process', stepId = selection.step || null, processMode = 'list';
    let artifact = null, artifactCursor = null, artifactBrowse = null, artifactRequest = 0, stepRequest = 0;
    let artifactBusy = false, lastArtifactButton = null, poller = null;
    let listCursor = null, listInitialized = false, listBusy = false;
    const language = () => document.documentElement.lang === 'en' ? 'en' : 'zh';
    const text = (zh, en) => language() === 'en' ? en : zh;
    const message = (zh, en) => { q('#ar-message').textContent = text(zh,en); q('#ar-message').hidden = false; };
    async function get(url) {
      const response = await environment.fetch(url, {headers:{Accept:'application/json'}, cache:'no-store'});
      if (!response.ok) throw new Error('Request failed: ' + response.status);
      return response.json();
    }
    try { if (environment.sessionStorage.getItem('uteki-agent-language') === 'en') document.documentElement.lang = 'en'; } catch {}
    q('#ar-language').addEventListener('click', () => {
      document.documentElement.lang = language() === 'en' ? 'zh-CN' : 'en';
      try { environment.sessionStorage.setItem('uteki-agent-language', language()); } catch {}
    });
    function filterRuns() {
      const term = q('#ar-search').value.toLowerCase(); let count = 0;
      all('[data-run-row]').forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(term); if (!row.hidden) count++; });
      q('#ar-list-empty').hidden = count > 0;
    }
    q('#ar-search').addEventListener('input', filterRuns);
    function appendRuns(rows) {
      const ids = new Set(all('[data-run-row]').map(node => node.dataset.runRow));
      for (const run of rows) {
        if (ids.has(run.id)) continue;
        const node = document.createElement('a'); node.className = 'ar-run'; node.dataset.runRow = run.id;
        node.href = runURL(run.id);
        node.innerHTML = `<strong>${escape(run.title || run.id)}</strong><small>${escape(run.scope?.company_id)} · ${escape((run.scope?.periods || []).join(', '))}</small><small>${known(run.state?.execution)} · ${known(run.state?.delivery)}</small>`;
        if (run.id === detail?.id) node.setAttribute('aria-current','page');
        q('#ar-run-list').append(node); ids.add(run.id);
      }
      filterRuns();
      q('#ar-list-count').innerHTML = bi(`已列出 ${ids.size} 条运行`,`${ids.size} runs listed`);
    }
    async function loadList({more = false} = {}) {
      if (listBusy) return;
      listBusy = true; q('#ar-list-more').disabled = true;
      try {
        if (!listInitialized) {
          const page = await get(config.api + '?' + new URLSearchParams({agent:selection.agent || 'data',limit:'50'}));
          appendRuns(page.runs || []); listCursor = page.next_cursor; listInitialized = true;
        }
        if (more && listCursor) {
          const page = await get(config.api + '?' + new URLSearchParams({agent:selection.agent || 'data',limit:'50',cursor:listCursor}));
          appendRuns(page.runs || []); listCursor = page.next_cursor;
        }
        q('#ar-list-more').hidden = !listCursor;
      } catch { message('运行列表暂不可用；已保留当前列表。','Run list is unavailable; the current list is retained.'); }
      finally { listBusy = false; q('#ar-list-more').disabled = false; }
    }
    q('#ar-list-more').addEventListener('click', () => loadList({more:true}));
    function navigate(changes) {
      const url = new URL(environment.location.href);
      for (const [key,value] of Object.entries(changes)) value === null ? url.searchParams.delete(key) : url.searchParams.set(key,value);
      environment.history.replaceState({}, '', url);
    }
    function tab(name, update = true) {
      if (!['process','artifacts','usage','config'].includes(name)) return;
      activeTab = name;
      all('[data-tab]').forEach(node => { if (node.dataset.tab === name) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current'); });
      all('[data-panel]').forEach(node => { node.hidden = node.dataset.panel !== name; });
      if (update) navigate({tab:name});
    }
    const refHTML = ref => `<div class="ar-ref"><button type="button" data-artifact="${escape(ref.id)}" data-artifact-run="${escape(ref.run_id)}">${escape(ref.label || ref.id)}</button><small> ${known(ref.availability)}</small></div>`;
    const modelHTML = call => `${known(call.provider)} · ${known(call.requested_model)} · ${bi('推理档位','Reasoning effort')}: ${known(call.reasoning_effort)}`;
    function stepModels(item) {
      const calls = detail.calls.filter(call => (item.call_ids || []).includes(call.call_id));
      return calls.length ? `<div class="ar-step-models">${calls.map(call => `${callConfigurationHTML(call)}<p>Request ID: ${known(call.request_id)}</p>`).join('')}</div>` : `<p class="ar-notice">${bi('这一步没有已记录的模型调用。','No model call is recorded for this step.')}</p>`;
    }
    async function selectStep(id) {
      const step = detail.steps.find(item => item.id === id);
      if (!step) { message('该步骤不属于当前运行。', 'This step does not belong to this run.'); return; }
      const request = ++stepRequest;
      stepId = id; tab('process'); navigate({step:id});
      all('[data-step]').forEach(node => { if (node.dataset.step === id) node.setAttribute('aria-current','step'); else node.removeAttribute('aria-current'); });
      const render = item => {
        q('#ar-step-detail').innerHTML = `<h2>${escape(item.action || item.phase || item.id)}</h2><p>${known(item.status)}</p>${item.error_code ? `<p class="ar-error">${escape(item.error_code)}</p>` : ''}<p class="ar-notice">${bi('耗时（秒）','Elapsed seconds')}: ${known(item.elapsed_seconds)}</p>${stepModels(item)}${(item.files || []).map(refHTML).join('')}${(item.call_ids || []).map(call => `<p><button type="button" data-call="${escape(call)}">${bi('关联模型调用','Related model call')} · ${escape(call)}</button></p>`).join('')}${(item.child_run_ids || []).map(child => `<p><button type="button" data-child-run="${escape(child)}">${bi('打开子运行','Open child run')} · ${escape(child)}</button></p>`).join('')}`;
      };
      render(step);
      try {
        const full = await get(apiRun(config.api, detail.id) + '/steps/' + encodeURIComponent(id));
        if (request !== stepRequest) return;
        if (full.id !== id || full.run_id !== step.run_id) throw new Error('Step identity mismatch');
        render(full);
      } catch { if (request === stepRequest) message('步骤详情暂不可用；已保留当前记录。','Step details are unavailable; the current record is retained.'); }
    }
    async function openArtifact(ref, {append = false, browse = null} = {}) {
      if (append && artifactBusy) return;
      const request = ++artifactRequest;
      artifactBusy = true;
      if (!append) { artifact = ref; artifactCursor = null; artifactBrowse = browse; }
      q('#ar-artifact-detail').hidden = false;
      q('#ar-artifact-title').textContent = ref.label || ref.id;
      q('#ar-artifact-status').innerHTML = bi('正在读取…','Loading…');
      q('#ar-artifact-more').disabled = true;
      if (!append) { q('#ar-artifact-content').textContent = ''; q('#ar-artifact-children').replaceChildren(); q('#ar-artifact-detail').scrollIntoView?.({block:'nearest'}); }
      navigate({artifact:ref.id});
      try {
        const page = await get(artifactURL(config.api, detail.id, ref.id, {cursor:append ? artifactCursor : null,browse:append ? null : artifactBrowse}));
        if (request !== artifactRequest) return;
        if (page.id !== ref.id || page.run_id !== ref.run_id) throw new Error('Artifact identity mismatch');
        const content = typeof page.content === 'string' ? page.content : JSON.stringify(page.content, null, 2);
        q('#ar-artifact-content').textContent = (append ? q('#ar-artifact-content').textContent + '\n' : '') + (content ?? '');
        artifactCursor = page.next_cursor ?? null;
        q('#ar-artifact-more').hidden = artifactCursor === null;
        q('#ar-artifact-status').innerHTML = known(page.availability) + ' · ' + (page.truncated ? bi('当前为部分内容，可继续读取。','Partial content; continue reading.') : bi('本页内容已读取。','This page has been read.'));
        if (page.sha256) q('#ar-artifact-status').append(document.createTextNode(' · SHA256 ' + page.sha256));
        q('#ar-artifact-children').innerHTML = (page.children || []).map(child => `<button type="button" data-browse="${escape(child.browse)}">${escape(child.label)}</button>`).join(' ');
        for (const diagnostic of page.diagnostics || []) { const node = document.createElement('p'); node.className = 'ar-notice ar-error'; node.textContent = diagnostic; q('#ar-artifact-children').append(node); }
      } catch {
        if (request === artifactRequest) q('#ar-artifact-status').innerHTML = bi('产物读取失败。请重试；未替换为其他产物。','Artifact could not be read. Retry; no other artifact was substituted.');
      } finally {
        if (request === artifactRequest) { artifactBusy = false; q('#ar-artifact-more').disabled = false; }
      }
    }
    function findRef(id, runId) {
      const refs = [...(detail.artifacts || []),...(detail.inputs || []),...(detail.configs || []),
        ...(detail.steps || []).flatMap(s => s.files || []),...(detail.calls || []).flatMap(c => c.files || [])];
      return refs.find(ref => ref.id === id && ref.run_id === runId);
    }
    function showCall(id) {
      const call = detail.calls.find(item => item.call_id === id);
      if (!call) return;
      tab('usage');
      const node = q('#ar-call-detail');
      node.innerHTML = `<h2>${escape(call.call_id)}</h2>${callConfigurationHTML(call)}<p>${bi('返回模型','Returned model')}: ${known(call.actual_upstream_model)} · ${bi('原始阶段','Recorded stage')}: ${known(call.stage)}</p><p>Request ID: ${known(call.request_id)}<br>Response ID: ${known(call.response_id)}</p><p>${bi('思考模式','Thinking mode')}: ${known(call.thinking_mode)}</p>${call.step_id ? `<button type="button" data-step="${escape(call.step_id)}">${bi('返回所属步骤','Open related step')}</button>` : `<p class="ar-notice">${bi('该调用未关联到步骤，仍计入所属运行。','This call has no step link and remains included in its run.')}</p>`}${(call.files || []).map(refHTML).join('')}`;
    }
    function showChild(id) {
      const run = (detail.run_tree || []).find(item => item.id === id);
      if (!run) { message('子运行关系尚未记录。','The child run relationship is not recorded.'); return; }
      tab('process');
      const node = q('#ar-child-detail');
      if (id === detail.id) { node.hidden = true; return; }
      node.hidden = false;
      const ownerRefs = [...(detail.artifacts || []),...(detail.inputs || []),...(detail.configs || [])].filter(ref => ref.run_id === id);
      node.innerHTML = `<h2>${escape(id)}</h2><p>${known(run.role || run.kind)} · ${known(run.status)}</p><p><button type="button" data-child-run="${escape(run.parent_run_id || detail.id)}">${bi('返回父运行','Return to parent run')}</button> ${run.parent_step_id ? `<button type="button" data-step="${escape(run.parent_step_id)}">${bi('打开父步骤','Open parent step')}</button>` : ''}</p><div>${(detail.steps || []).filter(step => step.run_id === id).map(step => `<p><button type="button" data-step="${escape(step.id)}">${escape(step.action || step.phase || step.id)}</button> · ${known(step.status)}</p>`).join('')}</div>${ownerRefs.map(refHTML).join('')}<div>${(detail.calls || []).filter(call => call.run_id === id).map(call => `<p><button type="button" data-call="${escape(call.call_id)}">${escape(call.call_id)}</button> · ${known(call.status)}</p>`).join('')}</div>`;
    }
    function setProcessMode(mode) {
      if (mode !== 'list' && mode !== 'timing') return;
      if (mode === 'timing' && !timedSteps(detail).length) return;
      processMode = mode;
      all('[data-process-mode]').forEach(node => node.setAttribute('aria-pressed',String(node.dataset.processMode === mode)));
      q('#ar-timing').hidden = mode !== 'timing';
      q('#ar-steps').hidden = mode === 'timing';
    }
    function updateTiming() {
      const rows = timedSteps(detail);
      all('[data-process-mode]').filter(node => node.dataset.processMode === 'timing').forEach(node => { node.disabled = !rows.length; });
      q('#ar-timing-note').innerHTML = bi(`${rows.length} / ${(detail.steps || []).length} 步有完整起止时间。缺少时间的步骤保留在列表；区间不相加为总耗时。`,`${rows.length} / ${(detail.steps || []).length} steps have complete start and end times. Steps without timing stay in the list; intervals are not added into a total.`);
      for (const {step,left,width} of rows) {
        let row = all('[data-timing-row]').find(node => node.dataset.timingRow === step.id);
        if (!row) {
          row = document.createElement('div'); row.className = 'ar-timing-row'; row.dataset.timingRow = step.id;
          const button = document.createElement('button'); button.type = 'button'; button.dataset.step = step.id;
          const interval = document.createElement('div'); interval.className = 'ar-interval'; interval.append(document.createElement('span'));
          row.append(button,interval,document.createElement('small')); q('#ar-timing').append(row);
        }
        row.children[0].textContent = `${step.ordinal} · ${step.action || step.phase || step.id}`;
        row.children[1].children[0].setAttribute('style',`left:${left}%;width:${width}%`);
        row.children[2].innerHTML = `${escape(step.run_id)} · ${escape(step.started_at)} → ${escape(step.ended_at)} · ${known(step.elapsed_seconds)} s`;
      }
      if (processMode === 'timing' && !rows.length) setProcessMode('list');
    }
    function updateView(incoming) {
      const next = mergeRunView(detail, incoming);
      if (next === detail) return;
      const priorScope = JSON.stringify(detail.scope);
      detail = next;
      updateCallRecords(q('#ar-call-times'),detail.calls || [],callTimeRecordsHTML);
      updateCallRecords(q('#ar-call-snapshots'),detail.calls || [],calls=>calls.map(callConfigurationHTML).join(''));
      if (q('#ar-model-summary')) {
        const models = new Map();
        for (const call of detail.calls || []) models.set(JSON.stringify([call.role,call.provider,call.requested_model,call.reasoning_effort]),call);
        q('#ar-model-summary').innerHTML = [...models.values()].map(call => `<p>${known(call.role)} · ${modelHTML(call)}</p>`).join('');
      }
      all('[data-state]').forEach(node => { node.innerHTML = known(detail.state?.[node.dataset.state]); });
      all('[data-usage]').forEach(node => { node.innerHTML = known(detail.usage?.[node.dataset.usage]); });
      all('[data-own-usage]').forEach(node => { node.innerHTML = known(detail.usage?.own?.[node.dataset.ownUsage]); });
      if (JSON.stringify(detail.scope) !== priorScope) {
        q('#ar-scope').textContent = [detail.scope?.company_id,(detail.scope?.periods || []).join(', '),detail.scope?.knowledge_cutoff].filter(Boolean).join(' · ');
        q('#ar-scope-config').textContent = JSON.stringify(detail.scope || {},null,2);
      }
      function syncRefs(container, values) {
        for (const ref of values) {
          let row = [...container.children].find(node => node.dataset.refRow === ref.id);
          if (!row) {
            row = document.createElement('div'); row.className = 'ar-ref'; row.dataset.refRow = ref.id;
            const button = document.createElement('button'); button.type = 'button'; button.dataset.artifact = ref.id; button.dataset.artifactRun = ref.run_id;
            row.append(button,document.createElement('small')); container.append(row);
          }
          row.children[0].textContent = ref.label || ref.id;
          row.children[1].innerHTML = ' ' + known(ref.availability);
        }
      }
      syncRefs(q('#ar-inputs'),detail.inputs || []);
      syncRefs(q('#ar-configs'),detail.configs || []);
      q('#ar-run-relations').hidden = (detail.run_tree || []).length < 2;
      for (const run of detail.run_tree || []) {
        let row = all('[data-tree-run]').find(node => node.dataset.treeRun === run.id);
        if (!row) {
          row = document.createElement('li'); row.dataset.treeRun = run.id;
          const button = document.createElement('button'); button.type = 'button'; button.dataset.childRun = run.id; button.textContent = run.id;
          row.append(button,document.createElement('span')); q('#ar-run-tree-items').append(row);
        }
        row.children[1].innerHTML = ` · ${known(run.role || run.kind)} · ${known(run.status)}`;
      }
      for (const step of detail.steps || []) {
        if (step.run_id !== detail.id) continue;
        let row = all('[data-step-row]').find(node => node.dataset.stepRow === step.id);
        if (!row) {
          row = document.createElement('li'); row.className = 'ar-step'; row.dataset.stepRow = step.id;
          const button = document.createElement('button'); button.type = 'button'; button.dataset.step = step.id;
          const label = document.createElement('span'); label.dataset.stepLabel = '';
          const status = document.createElement('small'); status.dataset.stepStatus = '';
          button.append(label,status); row.append(button);
          q('#ar-steps').append(row);
        }
        row.querySelector('[data-step-label]').textContent = `${step.ordinal} · ${step.action || step.phase || step.id}`;
        row.querySelector('[data-step-status]').textContent = `${step.status ?? ''} · ${step.phase ?? ''}`;
      }
      for (const ref of detail.artifacts || []) {
        let row = all('[data-artifact-row]').find(node => node.dataset.artifactRow === ref.id);
        if (!row) { row = document.createElement('tr'); row.dataset.artifactRow = ref.id; q('#ar-artifact-rows').append(row); }
        while (row.children.length < 4) row.append(document.createElement('td'));
        let button = row.children[0].querySelector('[data-artifact]');
        if (!button) { button = document.createElement('button'); button.type = 'button'; button.dataset.artifact = ref.id; button.dataset.artifactRun = ref.run_id; row.children[0].append(button); }
        button.textContent = ref.label || ref.id;
        row.children[1].textContent = ref.kind || '';
        row.children[2].innerHTML = known(ref.availability);
        row.children[3].innerHTML = known(ref.size_bytes); row.children[3].className = 'ar-number';
      }
      for (const call of detail.calls || []) {
        let row = all('[data-call-row]').find(node => node.dataset.callRow === call.call_id);
        if (!row) { row = document.createElement('tr'); row.dataset.callRow = call.call_id; q('#ar-call-rows').append(row); }
        while (row.children.length < 9) row.append(document.createElement('td'));
        let button = row.children[0].querySelector('[data-call]');
        if (!button) { button = document.createElement('button'); button.type = 'button'; button.dataset.call = call.call_id; row.children[0].append(button); }
        button.textContent = call.call_id;
        let role = row.children[0].querySelector('small');
        if (!role) { role = document.createElement('small'); row.children[0].append(role); }
        role.textContent = call.role || '';
        row.children[1].textContent = call.requested_model || '';
        row.children[2].innerHTML = known(call.status);
        ['input_tokens','output_tokens','cached_tokens','reasoning_tokens','elapsed_seconds','estimated_usd'].forEach((key,index) => {
          row.children[index+3].innerHTML = known(call[key]); row.children[index+3].className = 'ar-number';
        });
      }
      const roles = detail.usage?.roles || [], maximum = Math.max(1,...roles.map(role => role.input_tokens || 0));
      q('#ar-token-bars').innerHTML = roles.map(role => `<div class="ar-token-row"><span>${escape(role.role)}</span><div class="ar-token-bar"><span style="width:${Math.min(100,Math.max(0,(role.input_tokens || 0)/maximum*100))}%"></span></div><output>${known(role.input_tokens)}</output></div>`).join('');
      q('#ar-diagnostics').innerHTML = (detail.diagnostics || []).map(value => `<p class="ar-notice ar-error">${escape(value)}</p>`).join('');
      updateTiming();
      // Selected step, open artifact, focus, and reading positions remain intact.
    }
    q('#ar-main').addEventListener('click', event => {
      const tabLink = event.target.closest('[data-tab]');
      if (tabLink) { event.preventDefault(); tab(tabLink.dataset.tab); return; }
      if (!detail) return;
      const mode = event.target.closest('[data-process-mode]');
      if (mode) { setProcessMode(mode.dataset.processMode); return; }
      const run = event.target.closest('[data-child-run]');
      if (run) { showChild(run.dataset.childRun); return; }
      const step = event.target.closest('[data-step]');
      if (step) { selectStep(step.dataset.step); return; }
      const trigger = event.target.closest('[data-artifact]');
      if (trigger) {
        const ref = findRef(trigger.dataset.artifact, trigger.dataset.artifactRun);
        if (ref) { lastArtifactButton = trigger; openArtifact(ref); }
        return;
      }
      const child = event.target.closest('[data-browse]');
      if (child && artifact) { openArtifact(artifact,{browse:child.dataset.browse}); return; }
      const call = event.target.closest('[data-call]'); if (call) showCall(call.dataset.call);
    });
    if (detail) {
      q('#ar-artifact-more').addEventListener('click', () => { if (artifact && artifactCursor !== null) openArtifact(artifact,{append:true}); });
      q('#ar-artifact-close').addEventListener('click', () => {
        artifactRequest++; artifactBusy = false; q('#ar-artifact-detail').hidden = true; navigate({artifact:null}); lastArtifactButton?.focus({preventScroll:true});
      });
      if (selection.artifact) {
        const ref = [...detail.artifacts,...detail.inputs,...detail.configs].find(ref => ref.id === selection.artifact);
        if (ref) openArtifact(ref);
      }
    }
    function connection(state) {
      const labels = {finished:['执行已结束','Execution ended'],connected:['更新正常','Updates connected'],
        error:['更新失败，正在重试','Update failed; retrying'],stale:['监控更新中断，执行状态未知','Updates interrupted; execution state unknown'],
        historical:['历史回看','Historical replay']};
      q('#ar-connection').innerHTML = labels[state] ? bi(...labels[state]) : escape(state);
    }
    if (detail?.live) {
      poller = createPoller({
        isHidden:() => document.hidden,
        setTimer:environment.setTimeout.bind(environment),clearTimer:environment.clearTimeout.bind(environment),
        read:cursor => get(apiRun(config.api,detail.id) + '/events?' + new URLSearchParams({after:cursor ?? '0',limit:'100'})),
        apply:async page => {
        const incoming = await get(apiRun(config.api,detail.id) + '?' + new URLSearchParams({revision:page.high_watermark}));
          updateView(incoming);
        },onState:connection
      });
      poller.start();
      document.addEventListener('visibilitychange', () => poller.visibilityChanged());
    }
    q('#ar-refresh').addEventListener('click', async () => {
      if (poller) { poller.refresh(); return; }
      try {
        if (detail) updateView(await get(apiRun(config.api,detail.id)));
        else { listInitialized = false; await loadList(); }
      } catch { message('刷新失败；保留当前内容。','Refresh failed; current content is retained.'); }
    });
    environment.addEventListener('pagehide', () => { poller?.stop(); artifactRequest++; stepRequest++; });
    return {poller,updateView,selectStep,openArtifact,showChild,setProcessMode,getDetail:() => detail};
  }
  const exports = {createPoller,mergeRunView,timedSteps,artifactURL,bootstrap,escape,observedTime,callTimingHTML,configurationSnapshotHTML,callConfigurationHTML,updateCallRecords};
  if (typeof module !== 'undefined' && module.exports) module.exports = exports;
  else if (root.document) bootstrap(root.document,root);
})(typeof window !== 'undefined' ? window : globalThis);
