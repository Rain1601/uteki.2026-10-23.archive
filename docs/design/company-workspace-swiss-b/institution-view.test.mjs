import test from 'node:test';
import assert from 'node:assert/strict';
import { createInstitutionViews } from './institution-view.mjs';
import { getInstitution, getCompany, getManager, getManagerCompanyReport, parseRoute } from './model.mjs';
import { ALLOCATION_PALETTES, DEFAULT_ALLOCATION_PALETTE } from './allocation-palettes.mjs';

const route={institutionId:'uteki',view:'overview'};
const data=getInstitution(route.institutionId);
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const decode=value=>value.replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'");
const attributes=html=>[...html.matchAll(/<[a-zA-Z][^>]*>/g)].map(([tag])=>Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([,name,value])=>[name,decode(value)])));
const hasClass=(item,name)=>item.class?.split(/\s+/).includes(name);
const percent=value=>`${value>0?'+':''}${value.toFixed(2)}%`;
const render=language=>createInstitutionViews({t:(zh,en)=>language==='en'?en:zh,companyIcon:company=>`<span data-company-icon="${company.id}"></span>`});
const buttonHTML=(html,id)=>html.match(new RegExp(`<button\\b[^>]*id="${id}"[^>]*>([\\s\\S]*?)<\\/button>`))?.[1];

test('Agent legends and manual portfolio thumbnails expose all returns for the same selected period with one selected Agent',()=>{
  for(const language of ['zh','en'])for(const period of data.periods)for(const selected of data.agents) {
    const html=render(language).main(route,{period:period.id,agentId:selected.managerId}),elements=attributes(html);
    const periods=elements.filter(item=>item['data-action']==='institution-period');
    assert.deepEqual(periods.map(item=>item['data-period']),data.periods.map(item=>item.id));
    assert.deepEqual(periods.filter(item=>item['aria-pressed']==='true').map(item=>item['data-period']),[period.id]);
    const chart=elements.find(item=>hasClass(item,'institution-chart'));
    assert.ok(chart['aria-label']||chart['aria-hidden']==='true','chart has an accessible label or is represented by the named HTML legends');
    const legend=elements.find(item=>hasClass(item,'institution-agent-legend'));
    assert.equal(legend.role,'group');assert.ok(legend['aria-label']);
    assert.ok(html.includes(period.start)&&html.includes(period.end),'the selected comparison interval is visible');
    const lines=elements.filter(item=>hasClass(item,'agent-line'));
    assert.equal(lines.length,data.agents.length,'each Agent has a separate plotted history');
    for(const agent of data.agents)for(const prefix of ['institution-agent','institution-slide']) {
      const id=`${prefix}-${agent.managerId}`,button=elements.find(item=>item.id===id),body=buttonHTML(html,id);
      assert.ok(button&&body,`${id} is an accessible button with visible content`);
      assert.equal(button['data-action'],'institution-agent');assert.equal(button['data-agent'],agent.managerId);
      assert.equal(button['aria-pressed'],String(agent.managerId===selected.managerId));
      assert.ok(body.includes(escape(getManager(agent.managerId).manager.name)));
      assert.ok(body.includes(percent(agent.returns[period.id])),`${id} displays the ${period.id} return`);
    }
    const benchmark=elements.find(item=>hasClass(item,'benchmark-line'));
    assert.ok(benchmark);assert.equal(benchmark['data-action'],undefined);assert.equal(benchmark['data-agent'],undefined);
    assert.ok(html.includes(percent(period.benchmarkReturnPct)));
    assert.match(render(language).header(route),language==='en'?/Illustrative data|Not a live account/:/模拟/);
    assert.ok(html.includes(data.simulation.asOf));assert.doesNotMatch(html,/NaN|undefined|Infinity/);
    assert.ok(!elements.some(item=>item['data-institution-return']!==undefined),'the comparison is not replaced by an institution aggregate return');
  }
  const defaults=attributes(render('zh').main(route));
  assert.deepEqual(defaults.filter(item=>item.id?.startsWith('institution-agent-')&&item['aria-pressed']==='true').map(item=>item['data-agent']),[data.defaultAgentId]);
});

test('all Agent curves and the benchmark space mixed monthly and weekly observations by elapsed time',()=>{
  const period=data.periods.find(item=>item.id==='ytd'),series=period.series;
  const timestamps=series.map(point=>Date.parse(point.date));
  const gaps=timestamps.slice(1).map((date,index)=>date-timestamps[index]);
  assert.ok(new Set(gaps).size>1,'the fixture includes unequal observation intervals');
  const paths=attributes(render('zh').main(route,{period:period.id})).filter(item=>hasClass(item,'agent-line')||hasClass(item,'benchmark-line'));
  assert.equal(paths.length,data.agents.length+1);
  for(const path of paths) {
    const x=[...path.d.matchAll(/[ML](-?[\d.]+),-?[\d.]+/g)].map(match=>Number(match[1]));
    assert.equal(x.length,series.length);
    const width=x.at(-1)-x[0],duration=timestamps.at(-1)-timestamps[0];
    for(let index=0;index<x.length;index++) {
      const displayFraction=(x[index]-x[0])/width,timeFraction=(timestamps[index]-timestamps[0])/duration;
      assert.ok(Math.abs(displayFraction-timeFraction)<0.0001,`${path.class} places ${series[index].date} at its elapsed-time position`);
    }
    const shortest=gaps.indexOf(Math.min(...gaps)),longest=gaps.indexOf(Math.max(...gaps));
    assert.ok(x[shortest+1]-x[shortest]<x[longest+1]-x[longest],'a weekly interval occupies less width than a monthly interval');
  }
});

test('the single portfolio stage uses only the selected Agent holdings and cash, never the institution or another Agent portfolio',()=>{
  for(const agent of data.agents) {
    const holdings=[...agent.portfolio.holdings.map(item=>({...item,id:item.companyId})),{id:'cash',weightPct:agent.portfolio.cashWeightPct,marketValue:agent.portfolio.cashValue}];
    for(const language of ['zh','en'])for(const selection of [null,...holdings.map(item=>item.id)]) {
      const html=render(language).main(route,{agentId:agent.managerId,holdingId:selection}),elements=attributes(html);
      assert.equal(elements.filter(item=>hasClass(item,'portfolio-stage')).length,1);
      assert.equal(elements.find(item=>item.id==='portfolio-stage')['data-agent'],agent.managerId);
      assert.ok(!elements.some(item=>item.id==='institution-agents'));
      const weights=elements.filter(item=>hasClass(item,'holding-weight'));
      assert.deepEqual(weights.map(item=>item['data-holding']),holdings.map(item=>item.id));
      assert.deepEqual(weights.filter(item=>item['aria-pressed']==='true').map(item=>item['data-holding']),selection?[selection]:[]);
      for(const holding of holdings) {
        const button=weights.find(item=>item['data-holding']===holding.id);
        assert.ok(button['aria-label'].includes(`${holding.weightPct.toFixed(1)}%`));
        assert.equal(button.id,`allocation-${holding.id}`);
        if(holding.id!=='cash') {
          const link=elements.find(item=>item.id===`institution-company-${holding.id}`);
          const report=getManagerCompanyReport(agent.managerId,holding.id);
          if(report.status==='available')assert.deepEqual(parseRoute(link.href),report.route);
          else {
            assert.equal(report.status,'missing','the current fixture has no ambiguous report pair');
            assert.equal(link.href,undefined,'missing authored reports do not open another Manager or company overview');
          }
          assert.ok(html.includes(escape(getCompany(holding.id).company.name)));
        }
      }
      for(const link of elements.filter(item=>item.href?.startsWith('#')).map(item=>parseRoute(item.href))) {
        if(link.companyId)assert.ok(agent.portfolio.holdings.some(item=>item.companyId===link.companyId));
        if(link.managerId)assert.equal(link.managerId,agent.managerId,'Manager details open the displayed Agent');
        assert.notEqual(link.view,'activity');
      }
      const slices=elements.filter(item=>hasClass(item,'allocation-segment'));
      assert.equal(slices.length,holdings.length);
      assert.deepEqual(slices.filter(item=>item['aria-pressed']==='true').map(item=>item['data-holding']),selection?[selection]:[]);
      assert.equal(elements.find(item=>item.id==='institution-donut').role,'group');
      for(const slice of slices) {
        const holding=holdings.find(item=>item.id===slice['data-holding']);
        assert.ok(holding);assert.equal(slice.id,`allocation-slice-${holding.id}`);
        assert.equal(slice.role,'button');assert.equal(slice.tabindex,'0');assert.equal(slice['data-action'],'institution-holding');
        assert.ok(slice['aria-label'].includes(`${holding.weightPct.toFixed(1)}%`));
        assert.match(slice.d,/^M[\s\S]*[zZ]$/,'each hit target is its own closed annular region');
        assert.equal(slice['stroke-dasharray'],undefined,'slices do not use overlapping full-circle hit targets');
        const row=elements.find(item=>item.id===`institution-holding-${holding.id}`);
        assert.equal(row['data-allocation-row'],holding.id);
      }
      assert.ok(html.includes(new Intl.NumberFormat('en-US').format(agent.portfolio.totalValue)));
      const ids=elements.filter(item=>item.id).map(item=>item.id);assert.equal(new Set(ids).size,ids.length);
    }
  }
});

test('institution heading owns the compact simulation label and dated currency context without a duplicated status row',()=>{
  for(const language of ['zh','en']) {
    const view=render(language),header=view.header(route),body=view.main(route),headerElements=attributes(header);
    const label=headerElements.find(item=>item.id==='institution-simulation-label');
    assert.ok(label);assert.equal(label['data-action'],'context');
    assert.ok(header.includes(data.simulation.asOf));assert.ok(header.includes(data.simulation.currency));
    assert.ok(!attributes(body).some(item=>hasClass(item,'institution-status')));
    assert.ok(!attributes(body).some(item=>item.id==='institution-simulation-label'));
  }
});

test('manual portfolio selection keeps the page focused on comparison and one portfolio with explicit simulation provenance',()=>{
  for(const language of ['zh','en']) {
    const view=render(language),html=view.main(route),context=view.context(route),elements=attributes(html);
    assert.equal(view.sidebar(route),'','institution home has no middle section-index sidebar');
    assert.ok(!elements.some(item=>item['data-action']==='institution-section'));
    assert.deepEqual(elements.filter(item=>item['data-action']==='institution-step').map(item=>item['data-step']),['-1','1']);
    for(const agent of data.agents) {
      const curve=elements.find(item=>item.id===`institution-curve-${agent.managerId}`);
      assert.ok(curve);assert.equal(curve['data-action'],'institution-agent');assert.equal(curve['data-agent'],agent.managerId);
    }
    for(const value of [data.simulation.id,data.simulation.version,data.simulation.asOf])assert.ok(context.body.includes(value));
    assert.match(context.body,language==='en'?/not live accounts/:/不代表实盘账户/);
  }
});

test('Agent comparison rejects unsupported periods, unknown Agents and holdings outside the selected Agent scope',()=>{
  const view=render('zh');
  for(const period of ['', 'unknown', 'monthly'])assert.throws(()=>view.main(route,{period}),/period/i);
  for(const agentId of [null, '', 'unknown', 'alphabet'])assert.throws(()=>view.main(route,{agentId}),/agent/i);
  for(const holdingId of ['', 'unknown', 'north'])assert.throws(()=>view.main(route,{holdingId}),/holding/i);
  for(const agent of data.agents) {
    const foreign=data.portfolio.holdings.find(item=>!agent.portfolio.holdings.some(own=>own.companyId===item.companyId));
    assert.ok(foreign,'each Agent differs from the institution portfolio');
    assert.throws(()=>view.main(route,{agentId:agent.managerId,holdingId:foreign.companyId}),/holding/i);
  }
  for(const invalid of [
    {institutionId:'unknown',view:'overview'},
    {institutionId:'uteki',view:'reports'},
    {institutionId:'uteki',companyId:'alphabet',view:'overview'},
    {companyId:'alphabet',view:'overview'},
  ])assert.throws(()=>view.main(invalid));
});

test('four bilingual allocation palettes offer the approved Bright palette as the recommendation and a single explicit selection',()=>{
  assert.equal(DEFAULT_ALLOCATION_PALETTE,'bright');
  assert.deepEqual(ALLOCATION_PALETTES.map(item=>item.id),['classic','bright','jewel','vivid']);
  for(const language of ['zh','en']) {
    const defaults=attributes(render(language).main(route));
    assert.equal(defaults.find(item=>item.id==='institution-dashboard')['data-allocation-palette'],'bright');
    for(const selected of ALLOCATION_PALETTES) {
      const html=render(language).main(route,{paletteId:selected.id}),elements=attributes(html);
      const buttons=elements.filter(item=>item['data-action']==='allocation-palette');
      assert.deepEqual(buttons.map(item=>item['data-palette']),ALLOCATION_PALETTES.map(item=>item.id));
      assert.deepEqual(buttons.filter(item=>item['aria-pressed']==='true').map(item=>item['data-palette']),[selected.id]);
      for(const palette of ALLOCATION_PALETTES) {
        const button=buttons.find(item=>item['data-palette']===palette.id),body=buttonHTML(html,button.id);
        assert.equal(button['aria-controls'],'institution-donut');
        assert.ok(body.includes(language==='en'?palette.nameEn:palette.name));
        assert.ok(decode(body).includes(language==='en'?palette.descriptionEn:palette.description));
        const recommended=language==='en'?'Recommended':'推荐';
        assert.equal(button['aria-label'].includes(recommended),palette.id==='bright');
        assert.equal(body.includes(recommended),palette.id==='bright');
      }
    }
  }
});

test('palette previews use the selected Agent allocation geometry and independent light and dark colors',()=>{
  const declarations=style=>Object.fromEntries(style.split(';').filter(Boolean).map(item=>item.split(':')));
  const checkThemeColors=(style,palette)=>{
    const properties=declarations(style);
    for(const theme of ['light','dark'])for(let index=0;index<6;index++) {
      assert.equal(properties[`--holding-${index}-${theme}`],palette[theme][index]);
    }
    assert.equal(Object.keys(properties).length,12,'cash stays in the shared neutral CSS token');
  };
  for(const language of ['zh','en'])for(const agent of data.agents)for(const selected of ALLOCATION_PALETTES) {
    const html=render(language).main(route,{agentId:agent.managerId,paletteId:selected.id}),elements=attributes(html);
    const dashboard=elements.find(item=>item.id==='institution-dashboard');
    assert.equal(dashboard['data-selected-agent'],agent.managerId);
    assert.equal(dashboard['data-allocation-palette'],selected.id);
    checkThemeColors(dashboard.style,selected);
    const sectors=elements.filter(item=>hasClass(item,'allocation-segment'));
    const geometry=sectors.map(item=>({d:item.d,fill:item.fill}));
    assert.equal(sectors.length,agent.portfolio.holdings.length+1);
    for(const palette of ALLOCATION_PALETTES) {
      const previewElements=attributes(buttonHTML(html,`allocation-palette-${palette.id}`));
      const preview=previewElements.find(item=>hasClass(item,'allocation-palette-preview'));
      assert.equal(preview['aria-hidden'],'true');assert.equal(preview.focusable,'false');
      checkThemeColors(preview.style,palette);
      assert.deepEqual(previewElements.filter(item=>item.d).map(item=>({d:item.d,fill:item.fill})),geometry,'each option compares the same actual holdings, not an equal-slice decorative chart');
    }
    const swatches=elements.filter(item=>hasClass(item,'holding-swatch'));
    const bars=elements.filter(item=>hasClass(item,'holding-weight-bar'));
    for(let index=0;index<sectors.length;index++) {
      assert.equal(declarations(swatches[index].style)['--holding-color'],sectors[index].fill);
      assert.equal(declarations(bars[index].style)['--holding-color'],sectors[index].fill);
      assert.equal(declarations(bars[index].style)['--weight'],sectors[index]['data-weight'].replace(/\.0%$/,'%'));
    }
  }
});

test('allocation color choices preserve report scope, weights, selected holding and company identity across Agents',()=>{
  const knownCompanyTokens=new Map();
  const semantics=elements=>elements.filter(item=>
    hasClass(item,'allocation-segment')||hasClass(item,'holding-weight')||item.id?.startsWith('institution-company-')||hasClass(item,'agent-line')
  ).map(item=>({id:item.id,d:item.d,href:item.href,holding:item['data-holding'],weight:item['data-weight'],value:item['data-value'],selected:item['aria-pressed']}));
  for(const language of ['zh','en'])for(const agent of data.agents) {
    const selection=agent.portfolio.holdings[0].companyId;
    const baseline=attributes(render(language).main(route,{agentId:agent.managerId,holdingId:selection}));
    for(const palette of ALLOCATION_PALETTES) {
      const elements=attributes(render(language).main(route,{agentId:agent.managerId,holdingId:selection,paletteId:palette.id}));
      assert.deepEqual(semantics(elements),semantics(baseline),'a display preference does not modify research routes or portfolio facts');
      const slices=elements.filter(item=>hasClass(item,'allocation-segment'));
      assert.equal(new Set(slices.map(item=>item.fill)).size,slices.length,'current portfolio categories have distinct color slots');
      for(const slice of slices) {
        const id=slice['data-holding'];
        if(id==='cash')assert.equal(slice.fill,'var(--holding-cash)');
        else assert.match(slice.fill,/^var\(--holding-[0-5]\)$/);
        if(knownCompanyTokens.has(id))assert.equal(slice.fill,knownCompanyTokens.get(id),'company identity does not depend on Agent holding order');
        else knownCompanyTokens.set(id,slice.fill);
      }
    }
  }
  assert.ok(knownCompanyTokens.size>data.agents[0].portfolio.holdings.length,'the check includes the other Agent’s additional companies');
});

test('unknown or blank allocation palette selections are rejected without silently selecting a default',()=>{
  for(const language of ['zh','en'])for(const paletteId of [null,'','unknown','mist','CLASSIC']) {
    assert.throws(()=>render(language).main(route,{paletteId}),/palette/i);
  }
});
