(function (environment) {
  'use strict';
  const dimensions = ['accuracy', 'coverage', 'analysis', 'evidence'];
  const labels = {accuracy:['事实准确性','Factual accuracy'],coverage:['任务覆盖','Task coverage'],analysis:['分析价值','Analytical value'],evidence:['证据可追溯','Evidence traceability']};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const bi = (zh,en) => '<span lang="zh">' + escape(zh) + '</span><span lang="en">' + escape(en) + '</span>';
  const sameBinding = (left,right) => Boolean(left && right && ['trace_id','revision','result_sha256'].every(key => left[key] === right[key]));
  const draftKey = binding => 'uteki-agent-review-draft:' + JSON.stringify([binding.trace_id,binding.revision,binding.result_sha256]);
  const runURL = (base, identity) => base + '/' + encodeURIComponent(identity);
  function artifactURL(base, run, id, {revision,cursor,browse} = {}) {
    const params = new URLSearchParams();
    if (Number.isInteger(revision) || (typeof revision === 'string' && /^[0-9a-f]{64}$/.test(revision))) params.set('revision',String(revision));
    if (cursor != null && browse != null) throw Error('Cursor and browse are mutually exclusive');
    if (cursor != null) params.set('cursor',String(cursor));
    if (browse != null) params.set('browse',String(browse));
    return runURL(base,run) + '/artifacts/' + encodeURIComponent(id) + (params.size ? '?' + params : '');
  }
  function scorePayload(binding, values) {
    const reviewer = String(values.reviewer ?? '').trim(), notes = String(values.notes ?? '').trim();
    if (!reviewer || reviewer.length > 100 || notes.length > 4000) throw Error('Invalid reviewer or notes');
    const scores = {};
    for (const key of dimensions) {
      const value = values.scores?.[key];
      if (value === '' || value == null) scores[key] = null;
      else if ((typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 5) || (typeof value === 'string' && /^[0-5]$/.test(value))) scores[key] = Number(value);
      else throw Error('Invalid score');
    }
    if (!Object.values(scores).some(value => value !== null)) throw Error('At least one score is required');
    return {binding:{...binding},rubric_version:'agent-result-v1',reviewer,scores,notes};
  }
  function createScoreController({url,binding,request,onState=()=>{}}) {
    let saving = false, sequence = 0, stopped = false;
    async function load() {
      const current = ++sequence;
      onState({status:'loading'});
      try {
        const data = await request(url);
        if (stopped || current !== sequence) return;
        if (!sameBinding(data.binding,binding) || data.rubric_version !== 'agent-result-v1') { onState({status:'stale'}); return; }
        if (!Array.isArray(data.current) || !Array.isArray(data.stale) || data.current.some(record=>!sameBinding(record.binding,binding)) || data.stale.some(record=>record.binding?.trace_id!==binding.trace_id)) throw Error('Invalid review response');
        onState({status:'loaded',data});
        return data;
      } catch(error) {
        if (!stopped && current === sequence) onState({status:error.status === 409 ? 'stale' : 'error'});
      }
    }
    return {
      load,
      async save(values) {
        if (saving || stopped) return false;
        let payload;
        try { payload = scorePayload(binding, values); } catch(_) { onState({status:'invalid'}); return false; }
        saving = true; sequence++; onState({status:'saving'});
        try {
          const record = await request(url,{method:'POST',headers:{'Content-Type':'application/json','X-Uteki-Request':'1'},body:JSON.stringify(payload)});
          if (stopped) return false;
          if (!sameBinding(record.binding,binding)) throw Error('Saved review binding mismatch');
          const loaded = await load();
          if (!stopped) onState({status:loaded ? 'saved' : 'saved_unloaded'});
          return true;
        } catch(error) {
          if (!stopped) onState({status:error.status === 409 ? 'stale' : 'error'});
          return false;
        } finally { saving = false; if (!stopped) onState({status:'idle'}); }
      },
      stop() { stopped = true; sequence++; },
      state() { return {saving}; }
    };
  }
  function createArtifactReader({base,run,revision,request,onState=()=>{}}) {
    let sequence = 0, current = null, cursor = null, busy = false, stopped = false;
    async function open(ref, {append=false,browse=null}={}) {
      if (stopped || (append && busy)) return;
      if (append && (!current || cursor == null)) return;
      const index = ++sequence;
      const after = append ? cursor : null;
      if (!append) { current = ref; cursor = null; }
      busy = true; onState({status:'loading',ref,append});
      try {
        const data = await request(artifactURL(base,run,ref.id,{revision,cursor:after,browse:append?null:browse}));
        if (stopped || sequence !== index) return;
        if (data.id !== ref.id || data.run_id !== ref.run_id || (ref.sha256 && data.sha256 !== ref.sha256)) throw Error('Artifact identity mismatch');
        if (!Array.isArray(data.children || [])) throw Error('Invalid artifact children');
        cursor = data.next_cursor ?? null;
        onState({status:'loaded',ref,data,append});
      } catch(error) {
        if (!stopped && sequence === index) onState({status:'error',ref,append});
      } finally { if (sequence === index) busy = false; }
    }
    return {open,more(){return current && open(current,{append:true});},browse(value){return current && open(current,{browse:value});},close(){sequence++;current=null;cursor=null;busy=false;onState({status:'closed'});},stop(){stopped=true;sequence++;},state(){return {current,cursor,busy};}};
  }
  function scoreHistoryHTML(data) {
    function recordHTML(record) {
      return '<article class="rr-score-record"><header><strong>' + escape(record.reviewer) + '</strong> · ' + escape(record.created_at) + '</header><dl>' + dimensions.map(key => '<div><dt>' + bi(...labels[key]) + '</dt><dd>' + (record.scores?.[key] == null ? bi('未评分','Unscored') : escape(record.scores[key])) + '</dd></div>').join('') + '</dl>' + (record.notes ? '<p>' + escape(record.notes) + '</p>' : '') + '</article>';
    }
    return (data.current.length ? data.current.map(recordHTML).join('') : '<p class="rr-note">' + bi('当前结果尚无人工评分。','No human review for this result yet.') + '</p>') + (data.stale.length ? '<details><summary>' + bi('旧版本评分（不计入当前结果）','Reviews of older revisions (not current)') + ' · ' + data.stale.length + '</summary>' + data.stale.map(recordHTML).join('') + '</details>' : '');
  }
  function bootstrap(document, config = null) {
    config = config || JSON.parse(document.querySelector('#rr-config').textContent);
    const q = selector => document.querySelector(selector), all = selector => Array.from(document.querySelectorAll(selector));
    const controllers = [];
    async function request(url,options={}) {
      const response = await environment.fetch(url,{credentials:'same-origin',cache:'no-store',...options});
      if (!response.ok) { const error = Error('Request failed'); error.status = response.status; throw error; }
      return response.json();
    }
    try { if (environment.sessionStorage?.getItem('uteki-agent-language') === 'en') document.documentElement.lang = 'en'; } catch(_) {}
    q('#rr-language')?.addEventListener('click',()=>{
      const next = document.documentElement.lang === 'en' ? 'zh-CN' : 'en'; document.documentElement.lang = next;
      try { environment.sessionStorage?.setItem('uteki-agent-language',next === 'en' ? 'en' : 'zh'); } catch(_) {}
    });
    q('#rr-refresh')?.addEventListener('click',()=>environment.location.reload());
    q('#rr-search')?.addEventListener('input',event=>{
      const needle = event.target.value.toLocaleLowerCase().trim(); let visible=0;
      for (const row of all('[data-result-row]')) { row.hidden = !row.textContent.toLocaleLowerCase().includes(needle); if (!row.hidden) visible++; }
      q('#rr-list-empty').hidden = visible > 0;
    });
    for (const detail of config.details || []) {
      const card = all('[data-result]').find(node=>node.dataset.result === detail.id);
      if (!card) continue;
      const within = selector=>card.querySelector(selector);
      const form = within('[data-score-form]'), status = within('[data-score-status]');
      const formValues = () => {
        const value = name=>form.elements.namedItem(name).value;
        return {reviewer:value('reviewer'),notes:value('notes'),scores:Object.fromEntries(dimensions.map(key=>[key,value(key)]))};
      };
      try {
        const saved=JSON.parse(environment.sessionStorage?.getItem(draftKey(detail.binding)) || 'null');
        if (saved && sameBinding(saved.binding,detail.binding)) {
          for (const name of ['reviewer','notes']) if(typeof saved.values?.[name]==='string') form.elements.namedItem(name).value=saved.values[name];
          for (const key of dimensions) if(saved.values?.scores?.[key] === '' || /^[0-5]$/.test(String(saved.values?.scores?.[key] ?? 'invalid'))) form.elements.namedItem(key).value=saved.values.scores[key];
        }
      } catch(_) {}
      form.addEventListener('input',()=>{
        try { environment.sessionStorage?.setItem(draftKey(detail.binding),JSON.stringify({binding:detail.binding,values:formValues()})); } catch(_) {}
      });
      const score = createScoreController({url:runURL(config.api,detail.id)+'/scores',binding:detail.binding,request,onState:state=>{
        const messages = {loading:['正在读取评分…','Loading reviews…'],saving:['正在保存评分…','Saving review…'],saved:['评分已保存，原产物保持不变。','Review saved; original output is unchanged.'],saved_unloaded:['评分已保存，但重读记录未成功或结果版本已变化。请重读评分并核对版本；无需重复提交。','Review saved, but rereading failed or the result revision changed. Reload reviews and check the revision; do not resubmit.'],invalid:['请填写评分人，并至少为一项选择 0–5 分。','Enter a reviewer and at least one score from 0 to 5.'],stale:['运行结果版本已变化。请保留草稿，刷新并重新核对后评分。','The result revision changed. Keep your draft and refresh to review the new result.'],error:['评分读取或保存失败，草稿已保留。可以重试。','Review could not be loaded or saved. Your draft is retained; retry when ready.']};
        if (messages[state.status]) status.innerHTML = bi(...messages[state.status]);
        if (state.status === 'loaded') { within('[data-score-history]').innerHTML = scoreHistoryHTML(state.data); status.textContent = ''; }
        if (state.status === 'saving') { form.querySelector('[type="submit"]').disabled=true; within('[data-reload-scores]').disabled=true; }
        if (state.status === 'idle') { form.querySelector('[type="submit"]').disabled=false; within('[data-reload-scores]').disabled=false; }
      }});
      controllers.push(score); score.load();
      form.addEventListener('submit',event=>{
        event.preventDefault();
        score.save(formValues());
      });
      within('[data-reload-scores]').addEventListener('click',()=>score.load());
      let lastTrigger = null;
      const artifact = createArtifactReader({base:config.artifact_api,run:detail.id,revision:detail.revision,request,onState:state=>{
        const pane = within('[data-artifact-view]'), more = within('[data-more-artifact]'), status = within('[data-artifact-status]');
        if (state.status === 'closed') { pane.hidden=true; lastTrigger?.focus({preventScroll:true}); return; }
        pane.hidden=false;
        if (state.status === 'loading') {
          within('[data-artifact-title]').textContent = state.ref.label || state.ref.id;
          status.innerHTML = bi('正在读取…','Loading…'); more.disabled=true;
          if (!state.append) { within('[data-artifact-content]').textContent=''; within('[data-artifact-children]').replaceChildren(); more.hidden=true; pane.scrollIntoView?.({block:'nearest'}); }
        }
        if (state.status === 'loaded') {
          const data=state.data;
          const content=typeof data.content === 'string' ? data.content : JSON.stringify(data.content,null,2);
          const target=within('[data-artifact-content]'); target.textContent=(state.append ? target.textContent+'\n' : '')+(content??'');
          const children=within('[data-artifact-children]');
          const links=(data.children||[]).map(child=>'<button type="button" data-browse="'+escape(child.browse)+'">'+escape(child.label)+'</button>').join('');
          if (state.append) children.insertAdjacentHTML('beforeend',links); else children.innerHTML=links;
          for (const diagnostic of data.diagnostics || []) { const node=document.createElement('p');node.className='rr-note rr-warning';node.textContent=diagnostic;children.append(node); }
          status.innerHTML=escape(data.availability)+' · '+(data.truncated ? bi('当前为部分内容，可继续读取或展开字段。','Partial content; continue reading or expand a field.') : bi('本页内容已读取。','This page has been read.'));
          if (data.sha256) status.append(document.createTextNode(' · SHA256 '+data.sha256));
          more.hidden=data.next_cursor==null;more.disabled=false;
        }
        if (state.status === 'error') { status.innerHTML=bi('文件读取失败。未替换成其他结果；可重新点击文件。','File could not be read. No other result was substituted; select the file to retry.');more.disabled=false; }
      }});
      controllers.push(artifact);
      const refs=[...(detail.artifacts||[]),...(detail.configs||[]),...(detail.result_view?.artifacts||[])];
      card.addEventListener('click',event=>{
        const trigger=event.target.closest('[data-artifact]');
        if (trigger && card.contains(trigger)) {
          const ref=refs.find(item=>item.id===trigger.dataset.artifact && item.run_id===trigger.dataset.artifactOwner);
          if (ref) { lastTrigger=trigger;artifact.open(ref); } return;
        }
        const browse=event.target.closest('[data-browse]');
        if (browse && card.contains(browse)) artifact.browse(browse.dataset.browse);
      });
      within('[data-close-artifact]').addEventListener('click',()=>artifact.close());
      within('[data-more-artifact]').addEventListener('click',()=>artifact.more());
      if (config.selection.artifact && config.selection.run===detail.id) { const ref=refs.find(item=>item.id===config.selection.artifact); if(ref) artifact.open(ref); }
    }
    environment.addEventListener?.('pagehide',()=>controllers.forEach(controller=>controller.stop()));
    return {controllers};
  }
  const exported = {artifactURL,scorePayload,createScoreController,createArtifactReader,scoreHistoryHTML,sameBinding,draftKey,bootstrap,escape};
  if (typeof module !== 'undefined' && module.exports) module.exports=exported;
  if (environment.document) {
    if (environment.document.readyState === 'loading') environment.document.addEventListener('DOMContentLoaded',()=>bootstrap(environment.document));
    else bootstrap(environment.document);
  }
})(typeof window !== 'undefined' ? window : globalThis);
