(() => {
  'use strict';
  const {pages,order,states}=window.UTEKI_BLUEPRINT;
  const el=id=>document.getElementById(id);
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const companyNames=[['alphabet','Alphabet'],['microsoft','Microsoft'],['nvidia','NVIDIA'],['costco','Costco'],['arista','Arista'],['eaton','Eaton']];
  const defaults=page=>({page,tab:page==='company'?'overview':page==='manager'?'portfolio':page==='report'?'body':'original',mode:'ready',note:'1',manager:'North',entry:['managers','manager'].includes(page)?'manager':'company',entryManager:'North',reportKind:'main',language:'zh',version:'v2',comparison:'version',period:'common',holding:'Alphabet',transaction:false,context:false,back:null,y:0,focus:null});
  let state=defaults(location.hash.slice(1)||'map');
  if(!pages[state.page])state=defaults('map');
  let linkOrdinal=0;
  const routeButton=(label,page,extra='')=>`<button id="screen-link-${++linkOrdinal}" class="text-button" data-page="${page}" ${extra}>${label}</button>`;
  const region=(id,body)=>`<section class="region ${state.note===id?'selected':''}" data-region="${id}"><button class="marker" data-note="${id}" aria-pressed="${state.note===id}" aria-label="查看区域 ${id} 的说明">${id}</button>${body}</section>`;
  const tabs=(items)=>`<div class="tabs" role="tablist">${items.map(([key,label])=>`<button id="tab-${key}" class="tab ${state.tab===key?'active':''}" role="tab" aria-selected="${state.tab===key}" data-tab="${key}">${label}</button>`).join('')}</div>`;
  const action=(label,key,value='',cls='text-button')=>`<button class="${cls}" data-action="${key}" data-value="${value}">${label}</button>`;
  const reportLink=(label='打开主报告',manager=state.manager)=>routeButton(label,'report',`data-manager="${manager}" data-version="v2" data-report-kind="${label.includes('专题')?'topic':'main'}"`);
  function productRail(type){
    if(type==='company')return `<aside class="object-rail"><p class="rail-title">公司 / COMPANIES</p>${companyNames.map(([id,name],i)=>`<div class="object-row ${i===0?'active':'muted'}"><img src="../../../apps/uteki_zero/assets/companies/${id}-icon.png" alt=""><span>${name}</span>${i===0?'<span class="dot-count">2</span>':''}</div>`).join('')}<p class="rail-note">保留现有六家公司。<br>本稿仅填入 Alphabet 的结构示例。</p></aside>`;
    return `<aside class="object-rail"><p class="rail-title">MANAGERS</p><button class="object-row ${state.page==='managers'?'active':''}" data-page="managers">全部 Manager</button>${['North','Field'].map(name=>`<button class="object-row ${state.page!=='managers'&&state.entryManager===name?'active':''}" data-page="manager" data-manager="${name}"><span class="avatar">${name[0]}</span>${name}</button>`).join('')}<p class="rail-note">独立模拟账户<br>投资方法与期限单独展示</p></aside>`;
  }
  function frame(body,type=state.entry){
    return `<div class="screen"><div class="screen-topbar"><span class="product-logo">uteki</span><button class="product-nav ${type==='company'?'active':''}" data-page="company">公司</button><button class="product-nav ${type==='manager'?'active':''}" data-page="managers">Managers</button><span class="demo-label">WIREFRAME · 内容示意</span></div><div class="screen-layout">${productRail(type)}<div class="screen-main">${body}</div></div></div>`;
  }
  function companyPage(){
    const head=region('1','<h2>Alphabet <small>GOOGL · NASDAQ</small></h2><p class="micro">2 项值得关注的变化 · 数量示意 · 更新时刻待接入</p>');
    const nav=region('2',tabs([['overview','概览'],['research','研究报告'],['materials','资料与数据'],['tracking','持续跟踪']]));
    const changes=region('3',`<div class="section-label"><h3>值得重新看的判断</h3><span class="micro">按研究影响排列</span></div><div class="event-row"><span class="tag review">判断受挑战 · 示例</span><p><b>一项新的资本开支披露，需要重新检查现金流假设</b></p><p>关联 North 主报告 · 因素 F02 · 影响待复核</p><div class="inline-actions">${reportLink('查看受影响判断 →','North')}${routeButton('查看依据','evidence','data-context="company"')}</div></div><div class="event-row"><span class="tag">新增证据 · 示例</span><p><b>一份新的业务披露，关联云业务增长观察项</b></p><p>关联 Field 主报告与专题 · 同一事项只计一次</p><div class="inline-actions">${reportLink('查看相关研究 →','Field')}</div></div>`);
    const reports=region('4',`<h3>不同 Manager 的研究</h3>${['North','Field'].map(name=>`<div class="report-row"><div class="section-label"><b>${name} <span class="micro">· 投资方法 / 期限</span></b><span class="tag ${name==='North'?'review':''}">${name==='North'?'结论待复核':'已发布 · 示例'}</span></div><p>一句话投资判断、关键成立条件与未知事项的位置。</p><div class="inline-actions">${reportLink('主报告 · v2 →',name)}${reportLink('专题报告 →',name)}<span class="micro">截止时间明确</span></div></div>`).join('')}`);
    const materials=region('5',`<h3>已有资料与数据</h3><p class="micro">准备目标：5 个完整财年 / 8 个季度；实际覆盖逐项展示，未知不当成已完成。</p><div class="table-wrap"><table><thead><tr><th>类别</th><th>期间与状态</th><th>入口</th></tr></thead><tbody><tr><td>年报 / 季报</td><td>按材料列出实际期间<br><small>已可读 ≠ 已完成数据核验</small></td><td>${routeButton('查看材料','evidence')}</td></tr><tr><td>核心财务数据</td><td>期间 · 单位 · 口径 · 核验状态</td><td>${routeButton('查看数据','evidence','data-evidence-tab="data"')}</td></tr><tr><td>新闻与官方披露</td><td>来源时间 · 获取时间 · 覆盖缺口</td><td><small>列表位置</small></td></tr></tbody></table></div>`);
    const tracking=region('5',`<h3>正在验证的问题</h3><div class="task-row"><b>资本开支变化是否改变原现金流假设？</b><p>North · 主报告 v2 · F02</p><p>最近发现：有新披露，影响待复核。下一观察条件：相关期间公开数据就绪。</p><div class="inline-actions">${reportLink('返回报告因素 →','North')}</div></div><div class="callout neutral">这里显示业务问题与证据进展。抓取、SQL、重试和运行日志位于工程后台。</div>`);
    return frame(head+nav+(state.tab==='overview'?changes+reports:state.tab==='research'?reports:state.tab==='materials'?materials:tracking));
  }
  function managersPage(){
    return frame(region('1','<h2>Managers <small>表现总览 / Performance</small></h2><p class="micro">了解不同投资方法的实际模拟表现，再进入持仓与决策。</p>')+region('2',`<div class="section-label"><h3>比较期间</h3><select id="period" aria-label="表现比较期间"><option value="common" ${state.period==='common'?'selected':''}>共同有效区间</option><option value="since" ${state.period==='since'?'selected':''}>各自启动以来</option></select></div><p class="micro">${state.period==='common'?'起止日待有效数据确定 · SPY 主对照 · QQQ 补充':'各自起止日单独标识 · 不按累计收益直接排名'}<br>统一税前、扣除约定模拟成本；本稿无真实收益。</p>`)+region('3',`<div class="table-wrap"><table><thead><tr><th>Manager / 方法</th><th>区间收益</th><th>SPY / 差额</th><th>状态</th></tr></thead><tbody><tr><td>${routeButton('<b>North →</b>','manager','data-manager="North"')}<br><small>方法与期限说明</small></td><td>+x.x%<br><small>占位，不是收益</small></td><td>+x.x% / x.xpp<br><small>同区间</small></td><td><span class="tag">模拟运行示意</span></td></tr><tr><td>${routeButton('<b>Field →</b>','manager','data-manager="Field"')}<br><small>方法与期限说明</small></td><td>—</td><td>—</td><td><span class="tag">样本不足示例</span></td></tr></tbody></table></div><div class="wire-chart">归一化表现曲线的位置<br>有真实核算序列后再绘制；缺失不画装饰曲线</div><p class="micro">展开项：最大回撤、实际样本区间、核算日、成本口径。</p>`)+region('4',`<h3>研究范围与最近动作</h3><div class="report-row"><b>North</b><p>研究覆盖 n 家 / 持仓 m 家 / 现金 x% · 分别统计</p><p>最近动作：公司 · 调整方向 · 已模拟成交时间</p><div class="inline-actions">${routeButton('查看持仓与交易 →','manager','data-manager="North"')}${routeButton('查看研究公司','manager','data-manager="North" data-start-tab="coverage"')}</div></div>`),'manager');
  }
  function managerPage(){
    const info=region('1',`<h2>${state.manager} <small>Manager · 独立模拟账户</small></h2><p class="micro">投资方法 / 期限 · 方法版本 · 所选区间 / 核算日期</p><div class="stat-row"><div class="stat"><small>区间收益 / Return</small><strong>${state.manager==='Field'?'—':'+x.x%'}</strong></div><div class="stat"><small>SPY 同期 / Benchmark</small><strong>${state.manager==='Field'?'—':'+x.x%'}</strong></div><div class="stat"><small>最大回撤 / Drawdown</small><strong>${state.manager==='Field'?'—':'−x.x%'}</strong></div></div><p class="micro">${state.manager==='Field'?'Field 用于演示样本不足；持仓与交易也尚无可用快照。':'以下持仓配比和交易仅用于演示版面，不是账户记录。'}</p>`);
    const nav=region('3',tabs([['portfolio','持仓与交易'],['coverage','研究公司'],['reports','研究报告']]));
    if(state.tab==='coverage')return frame(info+nav+region('3',`<h3>研究覆盖 / Coverage</h3><table><thead><tr><th>公司</th><th>覆盖 / 研究状态</th><th>持仓关系</th></tr></thead><tbody><tr><td>${routeButton('Alphabet →','company')}</td><td>有已发布报告 · 示例</td><td>${state.manager==='North'?'示意持仓':'未知'}</td></tr><tr><td>Microsoft</td><td>研究中 · 示例</td><td>不据研究状态推断持仓</td></tr></tbody></table><div class="callout neutral">研究过的公司可以未持仓；引用某公司的公开材料不意味着加入持续研究名单。</div>`),'manager');
    if(state.tab==='reports')return frame(info+nav+region('5',`<h3>按公司组织的报告</h3><div class="report-row"><b>Alphabet</b><p>主报告和专题分别管理身份与版本</p><div class="inline-actions">${reportLink('主报告 · v2 →')}${reportLink('专题报告 →')}</div></div><div class="report-row"><b>Microsoft</b><p>研究中 · 无正式报告示例</p></div><div class="callout neutral">组合判断 / 组合报告入口需要单独定义，不强行归入 Alphabet。</div>`),'manager');
    if(state.manager==='Field')return frame(info+nav+region('2','<div class="empty-state"><h3>暂无可用持仓快照</h3><p>收益、现金比例与持仓都保持未知，不能借 North 的持仓填充。</p></div>')+region('4','<h3>交易记录</h3><p class="micro">记录未接入，与“没有发生交易”不同。</p>'),'manager');
    const names=['Alphabet','Microsoft','NVIDIA','Costco','现金'];
    const weights=[30,25,20,15,10];const colors=['#355d9f','#6883b0','#91a6c8','#b8c5dc','#e5e9ef'];
    const holdings=region('2',`<div class="section-label"><h3>当前持仓 / Holdings</h3><small>同一快照 · 配比示意</small></div><div class="holding-layout"><div class="donut" role="img" aria-label="示意配比：Alphabet 30%，Microsoft 25%，NVIDIA 20%，Costco 15%，现金 10%。点击旁边公司行查看联动说明。"></div><div>${names.map((name,i)=>`<button class="holding-button ${state.holding===name?'active':''}" data-action="holding" data-value="${name}" aria-pressed="${state.holding===name}"><span><i class="holding-key" style="--swatch:${colors[i]}"></i>${name}</span><span>${weights[i]}%</span></button>`).join('')}</div></div><p class="hold-result">已选：${state.holding}。${state.holding==='Alphabet'?routeButton('查看公司 →','company'):state.holding==='现金'?'现金是配置的一部分。':'本稿仅演示 Alphabet 的公司跳转，其余公司复用页面结构。'}</p>`);
    const transactions=region('4',`<div class="section-label"><h3>交易记录 / Transactions</h3><small>已模拟成交</small></div><table><thead><tr><th>时间 / 公司</th><th>动作 / 状态</th><th>权重变化</th></tr></thead><tbody><tr><td>成交时刻占位<br>Alphabet</td><td>增持 · 已模拟成交<br>${action(state.transaction?'收起理由 ↑':'展开理由 ↓','transaction')}</td><td>27% → 30%<br><small>纯设计示例</small></td></tr></tbody></table>${state.transaction?region('5',`<div class="transaction-detail"><b>决策理由与当时依据</b><p>展示为何调整、组合取舍、决策时点与信息截止。此处不生成真实投资理由。</p><p>公司依据：Alphabet / ${state.manager} / 主报告 v2</p><div class="inline-actions">${reportLink('查看当时引用的报告 →')}</div><p class="micro">组合报告引用：独立对象，具体阅读设计待定。</p></div>`):''}<div class="report-row"><span class="tag">待执行动作 · 独立区域</span><p>目标仓位、决策时间与待执行原因的位置。尚未成交，不进入上方实际持仓。</p></div>`);
    return frame(info+nav+holdings+transactions,'manager');
  }
  function reportPage(){
    const reportName=state.reportKind==='topic'?'云业务专题报告':'公司主报告';
    const head=region('1',`<p class="micro">Alphabet · ${state.manager} · ${reportName} · ${state.version}</p><h2 class="report-title">${reportName}</h2><p class="micro">研究版本 / 发布时间 / 信息截止分别展示<br>当前为 ${state.language==='zh'?'中文':'英文'}正文结构示例 · 非真实报告</p><div class="inline-actions">${action('中文','language','zh')}${action('English','language','en')}<select id="version" aria-label="研究报告版本"><option value="v2" ${state.version==='v2'?'selected':''}>v2 · 当前版示意</option><option value="v1" ${state.version==='v1'?'selected':''}>v1 · 历史版示意</option></select></div>`);
    const reportStatus=state.version==='v1'?'历史全文保留：这里显示旧版截止、后续版本与复核关系（如有）。':state.manager==='North'?'结论待复核示例：因素 F02 出现新证据。完整正文继续可读，新版状态单独展示。':'已发布 · 示例：当前没有待复核标记。后续变化与来源截止仍应明确展示。';
    const nav=region('2',tabs([['body','完整正文'],['changes','版本变化'],['compare','比较']])+`<div class="callout ${state.manager==='Field'?'neutral':''}">${reportStatus}</div>`);
    if(state.tab==='changes')return frame(head+nav+region('2',`<h3>变化定位</h3><div class="report-row"><b>F02 · 现金流假设</b><p>展示前后表述、变化原因与证据，而非只有“报告更新了”。</p><div class="inline-actions">${action('回到正文','tab','body')}${routeButton('查看新证据 →','evidence','data-context="citation"')}</div></div>`));
    if(state.tab==='compare')return frame(head+nav+region('2',`<div class="inline-actions">${action('同一报告两版','comparison','version')}${action('不同 Manager','comparison','manager')}</div><div class="compare-panel"><article><h3>${state.manager} · ${state.comparison==='version'?'v1':'v2'}</h3><p>独立报告身份与截止</p><p>完整正文列的位置，产品中可独立滚动。</p></article><article><h3>${state.comparison==='version'?state.manager:(state.manager==='North'?'Field':'North')} · v2</h3><p>独立报告身份与截止</p><p>比较范围不同应显式说明。</p>${routeButton('查看本列引用 →','evidence',`data-context="citation" data-version="v2" data-manager="${state.comparison==='version'?state.manager:(state.manager==='North'?'Field':'North')}"`)}</article></div>`));
    const cn='<h3>01 / 业务与投资判断</h3><p>这里应是一段可以连续阅读的完整论证：公司靠什么创造价值，这位 Manager 的核心判断是什么，判断在什么条件下成立，以及哪些未知仍然重要。</p><h3>02 / 因素、风险与证据</h3><p>每个关键因素同时展示支持它的事实、挑战它的材料，以及尚未解决的问题。新的证据可能引发复核，但不会悄悄改写已经发布的旧版结论。</p>';
    const en='<h3>01 / Business & investment thesis</h3><p>This area contains the full argument: how the business creates value, the Manager’s investment thesis, the conditions under which it holds, and the material uncertainties that remain.</p><h3>02 / Factors, risks & evidence</h3><p>Each key factor presents supporting facts, contrary evidence, and unresolved questions. New evidence may trigger review while the previously published report remains available.</p>';
    return frame(head+nav+region('5','<div class="report-toc">目录 / CONTENTS　业务 · 判断 · 因素 / 风险 · 估值 · 未知</div>')+region('3',`<article class="reading">${state.language==='zh'?cn:en}</article>`)+region('4',`<p class="reading">${state.language==='zh'?'一条具体判断关联到一份明确的材料和原文位置。':'A specific claim links to an identified source and location.'} ${routeButton('[1] 查看引用','evidence','data-context="citation"')}</p><p class="micro">这是正文组织说明，不是对 Alphabet 的投资意见。</p>`));
  }
  function evidencePage(){
    const fromReport=state.context==='citation';
    const head=region('1',`<p class="micro">材料主体：Alphabet · 版本与地区单独标识</p><h2>材料与证据 <small>Source viewer</small></h2>${fromReport?`<div class="callout neutral">引用上下文：${state.manager} · ${state.reportKind==='topic'?'云业务专题':'主报告'} ${state.version} · 因素 F02<br>展示被支持 / 挑战的判断及其原始引用。</div>`:'<p class="micro">从公司资料进入：当前没有绑定的报告引用，不预设某位 Manager 已采纳。</p>'}<div class="source-meta"><span>来源材料</span><b>官方披露的名称占位</b><span>日期</span><b>发布日期 / 信息可用时间 / 取得时间</b><span>语言地区</span><b>原始语种与地区版本；不静默合并</b><span>定位</span><b>页码 / 段落 / 表格 / 快照版本</b></div>`);
    const nav=tabs([['original','原始材料'],['data','结构化数据']]);
    const source=region('2',`<h3>原文位置与上下文</h3><blockquote class="evidence-quote">这里展示可核对的原文，以及前后必要上下文。此稿没有真实源文件，因此保留占位，不生成“原文摘录”。</blockquote><p class="micro">对应页、段或表格保持可定位。原件不可用时显示缺口和来源信息。</p>`);
    const data=region('3',`<h3>数据值与定义</h3><table><thead><tr><th>指标</th><th>值 / 单位</th><th>范围与口径</th></tr></thead><tbody><tr><td>财务指标名称</td><td>—<br><small>未接入，不填 0</small></td><td>明确期间 / 币种 / 实际或指引</td></tr><tr><td>派生指标</td><td>—</td><td>公式 + 输入项 + 对应原始材料</td></tr></tbody></table><div class="callout neutral">核验状态和缺口在这里可见。查看已有数据不意味着发起新查询或补采。</div>`);
    const relation=region('4',`<h3>${fromReport?'这份证据与判断的关系':'材料适用范围与缺口'}</h3><p class="micro">${fromReport?'先展示事实，再展示 '+state.manager+' 的解释；支持 / 挑战的关系属于该报告版本。':'展示来源身份、覆盖范围与可用状态。没有报告引用时，不补写投资解释。'}</p><p class="micro">核验通过 ≠ 投资判断成立；资料获取失败 ≠ 事件没有发生。</p>`);
    return frame(head+nav+(state.tab==='data'?data:source)+relation);
  }
  function mapPage(){
    return `<section class="map-section"><h2>一个工作台，两个观察入口</h2><div class="entity-strip"><div><strong>公司 / Company</strong><small>共享资料与事实<br>关注变化，比较研究</small></div><span class="connector">n : m<br>↔</span><div><strong>Manager</strong><small>持续的投资角色<br>方法、研究与决策</small></div><span class="connector">1 : n<br>→</span><div><strong>公司研究报告</strong><small>每份归属一家公司与一位 Manager<br>主报告 / 专题各自有版本</small></div></div><p class="micro" style="margin-top:10px">Manager 的模拟账户提供收益、持仓与交易。组合报告回答配置问题，跨公司归属另行定义。</p></section><section class="map-section"><h2>五类页面，以及各自回答的问题</h2><div class="map-pages">${['company','managers','manager','report','evidence'].map(key=>`<button class="map-card" data-page="${key}"><span class="map-code">${pages[key].code}</span><b>${pages[key].title}</b><p>${pages[key].question}</p><small>${key==='company'?'入口 A · 左侧选公司':key==='managers'?'入口 B · 点击 Manager 进入详情':key==='manager'?'由 M01 进入 · 左侧选 Manager':key==='report'?'C01 / M02 共用 · 保留来源':'C01 / R01 共用 · 引用按版本定位'} →</small></button>`).join('')}<div class="map-card"><span class="map-code">LATER</span><b>后续页面</b><p>行业研究、组合报告阅读、工程后台。保留在整体范围中，本轮不展开线框。</p><small>先收敛前台主路径</small></div></div></section><section class="map-section"><h2>先用两条路径检验结构</h2><div class="journeys"><div class="journey"><b>A / 我自己研究一家公司</b><p>看到变化 → 定位受影响判断 → 阅读报告 → 核对原文 → 返回判断。</p><code>C01 → R01 → E01 → R01 → C01</code><div class="inline-actions">${routeButton('从公司开始 →','company')}</div></div><div class="journey"><b>B / 我了解一位 Manager 的决策</b><p>比较表现 → 看持仓和交易 → 展开决策理由 → 阅读当时的研究依据。</p><code>M01 → M02 → R01 → E01</code><div class="inline-actions">${routeButton('从 Manager 开始 →','managers')}</div></div></div></section><section class="map-section"><h2>页面、标签、辅助视图各有边界</h2><table><thead><tr><th>层级</th><th>什么会变</th><th>例子</th></tr></thead><tbody><tr><td>入口 / 主对象</td><td>左列表对象与右侧核心问题</td><td>公司 ↔ Manager</td></tr><tr><td>页面</td><td>主要任务和阅读对象</td><td>持仓与交易 → 一份报告 → 一条证据</td></tr><tr><td>页内标签</td><td>同一对象的内容类别</td><td>公司概览 / 研究报告 / 资料与数据</td></tr><tr><td>筛选、版本、比较</td><td>对象不变，范围或阅读方式变化</td><td>某位作者 / v1 与 v2 / 对照阅读</td></tr></tbody></table><div class="callout neutral">全局导航与对象选择靠点击；鼠标滚轮只阅读。打开已有报告或资料不启动模型，不执行交易。</div></section>`;
  }
  function boundaryPage(){
    return `<section class="map-section"><div class="boundary-grid"><section><p class="eyebrow">PRODUCT / 面向用户</p><h2>先命名用户要完成的事</h2><ul><li><b>公司</b>：长期研究对象，共享资料与事实的归属。</li><li><b>Manager</b>：有方法和期限的投资角色，负责研究判断与决策。</li><li><b>报告</b>：可完整阅读、有版本和引用的研究产物。</li><li><b>账户 / 持仓 / 交易</b>：独立记录配置与表现，不能从报告文字推导成事实。</li><li><b>变化 / 跟踪问题</b>：管理注意力，关联具体判断与证据。</li></ul></section><section><p class="eyebrow">EXECUTION / 内部实现</p><h2>技术提供能力，不直接变成菜单</h2><ul><li><b>Data Agent</b>：自主获取、持续监控、处理核验、查询计算、证据交付。</li><li><b>Analysis Agent</b>：使用方法与资料形成分析，承载 Manager 的执行。</li><li><b>Skill</b>：可复用的方法或约束；投资期限与发现 / 分析任务分别建模。</li><li><b>Extractor / Text-to-SQL</b>：数据处理中可用的工具，不覆盖全部数据能力。</li><li><b>Run / Prompt / 日志</b>：在工程后台诊断，不进入必要阅读路径。</li></ul></section></div></section><section class="map-section"><h2>数据能力怎样体现在页面上</h2><table><thead><tr><th>上层能力</th><th>给研究提供什么</th><th>前台可见结果</th></tr></thead><tbody><tr><td>自主获取与持续监控</td><td>来源材料、版本、时间、覆盖状态</td><td>C01 资料准备与重要变化</td></tr><tr><td>处理、结构化与核验</td><td>可阅读材料、可核验数据、缺口</td><td>E01 原文、口径和数据状态</td></tr><tr><td>理解问题并安排查询 / 补采</td><td>明确范围的证据、计算、数据文件</td><td>报告所引用的结果；无需先让用户操作 SQL</td></tr><tr><td>形成与复核投资判断</td><td>公司研究报告及其正式版本</td><td>R01 正文、反证与待复核状态</td></tr><tr><td>组合配置与模拟执行</td><td>决策、持仓、成交与绩效核算</td><td>M01 / M02 比例、表现和交易原因</td></tr></tbody></table><div class="callout neutral">Data Agent 也需要理解问题、分析数据与整理证据。投资判断与配置责任归 Manager；两者是一条协作链上的不同职责。</div></section><section class="map-section"><h2>本稿保留的三个设计问题</h2><div class="question-block"><span class="decision-label pending">01 · 待确认</span><h3>组合报告作为哪一种独立阅读对象？</h3><p>公司报告保持“一家公司＋一位 Manager”。建议组合报告归属 Manager / 账户，可引用多家公司报告；本轮只留连接位置，不扩展正式归属契约。</p></div><div class="question-block"><span class="decision-label pending">02 · 待确认</span><h3>关注、持续研究与提醒怎样衔接？</h3><p>新公司加入持续研究名单需用户确认已明确；关注按钮是否承载此流程、角标只数哪些事件、何时主动提醒仍需设计。先不把三个动作绑定。</p></div><div class="question-block"><span class="decision-label pending">03 · 待确认</span><h3>前台的数据探索做到多深？</h3><p>本稿先支持查看已有材料、数据和证据。用户自主问答、保存指标或发起补采是额外能力，不因设计了资料标签就默认开放。</p></div></section><section class="map-section"><h2>评审与后续顺序</h2><ol><li>先看 C01：默认区域是否能回答“为什么现在需要关注这家公司”。</li><li>再看 M01 / M02：表现 → 持仓 → 交易 → 研究的关系是否自然。</li><li>最后打磨 R01 / E01 的阅读、证据与返回，再制作最终视觉和产品实现。</li></ol><p class="micro">首批详细范围为上述五类前台页面；工程后台后续独立标注。图形直接点选、长报告定位、真实数据接入与生产持久化均未实现。</p></section>`;
  }
  const templates={map:mapPage,company:companyPage,managers:managersPage,manager:managerPage,report:reportPage,evidence:evidencePage,boundaries:boundaryPage};
  function annotation(){
    const notes=pages[state.page].notes;
    const n=notes.find(n=>n[0]===state.note)||notes[0];
    const proposal=n[2].includes('待确认')?'pending':n[2].includes('建议')?'proposal':'';
    return `<aside class="annotation-panel" aria-label="区域内容与交互说明"><p class="eyebrow">REGION ${n[0]} / 设计标注</p><h2>${n[1]}</h2><span class="decision-label ${proposal}">${n[2]}</span><p style="margin-top:13px">${n[3]}</p><dl><dt>展示什么</dt><dd>${n[4]}</dd><dt>业务来源</dt><dd>${n[5]}</dd><dt>怎么交互</dt><dd>${n[6]}</dd><dt>状态 / 边界</dt><dd>${n[7]}</dd></dl><div class="annotation-index">${notes.map(note=>`<button data-note="${note[0]}" class="${state.note===note[0]?'active':''}" aria-label="区域 ${note[0]}：${note[1]}">${note[0]}</button>`).join('')}</div><p class="micro" style="margin:12px 0 0">编号覆盖不同页内标签；部分区域需切换标签才能在左侧看到。</p></aside>`;
  }
  function stateDemo(){
    const [title,description]=states[state.page][state.mode];
    const normal=templates[state.page]();
    // Retain report text for a review state; never turn a review flag into a blank report.
    if(state.mode==='stale')return `<div class="callout"><b>${title}</b><br>${description}</div>${normal}`;
    return frame(`<h2>${pages[state.page].title}</h2><p class="micro">${state.page==='company'?'Alphabet':state.page==='manager'?state.manager:state.page==='report'?'Alphabet · '+state.manager+' · '+state.version:'对象身份保持明确'}</p><div class="empty-state" role="status"><h3>${title}</h3><p>${description}</p>${action(state.mode==='error'?'演示重试后恢复内容':'返回示意内容','reset-mode','','button')}</div>`,['manager','managers'].includes(state.page)?'manager':'company');
  }
  function render(){
    linkOrdinal=0;
    const p=pages[state.page];
    el('page-nav').innerHTML=order.map(key=>`<a id="nav-${key}" class="doc-link" href="#${key}" data-page="${key}" ${state.page===key?'aria-current="page"':''}><span class="number">${pages[key].code}</span><span><b>${pages[key].title}</b><small>${pages[key].en}</small></span></a>`).join('');
    el('page-code').textContent=`${p.code} / ${p.en.toUpperCase()}`;el('page-title').textContent=p.title;el('page-question').textContent=p.question;
    el('page-summary').innerHTML=`<div class="summary-strip"><div><b>主对象</b><span>${p.object}</span></div><div><b>默认内容</b><span>${p.default}</span></div><div><b>边界</b><span>${p.boundary}</span></div></div>`;
    el('back').hidden=!state.back;
    el('back').textContent=state.back?`← 返回${pages[state.back.page].title}`:'← 返回上一张线框';
    el('screen-tools').hidden=!p.notes;el('state-select').value=state.mode;
    el('design-body').innerHTML=p.notes?`<div class="design-grid"><div>${state.mode==='ready'?templates[state.page]():stateDemo()}</div>${annotation()}</div>`:templates[state.page]();
    el('page-contract').innerHTML=p.notes?`<div class="contract"><details open><summary>这一页怎样算设计清楚了？</summary><p>${p.acceptance}</p><p><b>本稿边界：</b>${p.gaps}</p></details><details><summary>展开全部 ${p.notes.length} 个区域的内容标注</summary><div class="table-wrap"><table><thead><tr><th>区域 / 状态</th><th>展示什么</th><th>来源与交互</th><th>异常与边界</th></tr></thead><tbody>${p.notes.map(n=>`<tr><td>${n[0]} · ${n[1]}<br><small>${n[2]}</small></td><td>${n[4]}</td><td>${n[5]}<br>${n[6]}</td><td>${n[7]}</td></tr>`).join('')}</tbody></table></div></details></div>`:'';
    document.title=`Uteki · ${p.title} · 设计稿`;
  }
  function save(){history.replaceState(state,'',`#${state.page}`);}
  function navigate(page,options={}){
    if(!pages[page])return;
    const snapshot={...state,y:window.scrollY,focus:document.activeElement?.id||null};
    const next=defaults(page);
    state={...next,...options,back:snapshot};
    history.pushState(state,'',`#${page}`);render();window.scrollTo(0,0);el('content').focus({preventScroll:true});
  }
  function returnBack(){
    if(!state.back)return;
    const snapshot=state.back;state={...snapshot};
    history.pushState(state,'',`#${state.page}`);render();window.scrollTo(0,state.y||0);
    if(state.focus)el(state.focus)?.focus({preventScroll:true});
  }
  document.addEventListener('click',event=>{
    const target=event.target.closest('button,a');if(!target)return;
    if(target.dataset.page){event.preventDefault();const destination=target.dataset.page;let opts={manager:target.dataset.manager||state.manager,version:target.dataset.version||state.version,reportKind:target.dataset.reportKind||state.reportKind};if(['report','evidence'].includes(destination)){opts.entry=state.entry;opts.entryManager=state.entryManager;}if(destination==='manager')opts.entryManager=opts.manager;if(target.dataset.startTab)opts.tab=target.dataset.startTab;if(target.dataset.evidenceTab)opts.tab=target.dataset.evidenceTab;if(target.dataset.context)opts.context=target.dataset.context;navigate(destination,opts);return;}
    if(target.id==='back'){returnBack();return;}
    if(target.dataset.note){state.note=target.dataset.note;save();const y=window.scrollY;render();window.scrollTo(0,y);document.querySelector(`.annotation-index [data-note="${state.note}"]`)?.focus({preventScroll:true});return;}
    if(target.dataset.tab){state.tab=target.dataset.tab;save();render();el(`tab-${state.tab}`)?.focus({preventScroll:true});return;}
    const key=target.dataset.action;if(!key)return;
    const value=target.dataset.value;
    if(key==='holding')state.holding=value;
    else if(key==='transaction')state.transaction=!state.transaction;
    else if(key==='language')state.language=value;
    else if(key==='comparison')state.comparison=value;
    else if(key==='tab')state.tab=value;
    else if(key==='reset-mode')state.mode='ready';
    save();const y=window.scrollY;render();window.scrollTo(0,y);
    document.querySelector(`[data-action="${escape(key)}"][data-value="${escape(value)}"]`)?.focus({preventScroll:true});
  });
  document.addEventListener('change',event=>{
    if(event.target.id==='state-select')state.mode=event.target.value;
    else if(event.target.id==='period')state.period=event.target.value;
    else if(event.target.id==='version')state.version=event.target.value;
    else return;
    const id=event.target.id;save();render();el(id)?.focus({preventScroll:true});
  });
  window.addEventListener('popstate',event=>{state=event.state&&pages[event.state.page]?event.state:defaults(pages[location.hash.slice(1)]?location.hash.slice(1):'map');render();window.scrollTo(0,state.y||0);});
  history.replaceState(state,'',`#${state.page}`);render();
})();
