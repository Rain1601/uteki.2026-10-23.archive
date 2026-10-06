import test from 'node:test';
import assert from 'node:assert/strict';
import { createInvestmentEventViews } from './investment-event-view.mjs';
import { investmentEventFixture } from './investment-events.mjs';
import { getInstitution, getCompany, getManager, getReport, parseRoute } from './model.mjs';

const data = getInstitution('uteki');
const render = language => createInvestmentEventViews({
  t:(zh,en) => language === 'en' ? en : zh,
  companyIcon:company => `<span class="company-icon" data-company-icon="${company.id}"></span>`,
});
const decode = value => value.replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'");
const elements = html => [...html.matchAll(/<[a-zA-Z][^>]*>/g)].map(([tag]) => Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([,name,value]) => [name,decode(value)])));
const defaults = { agentId:'north',period:data.periods.find(period => period.id === '1m') };
const day = value => Date.parse(`${value}T00:00:00Z`);

const plotFor = options => ({ pointAt(managerId,date) {
  assert.equal(managerId,options.agentId);
  const start = day(options.period.start),span = day(options.period.end) - start;
  return { x:42 + (span ? (day(date) - start) / span : .5) * 934,y:managerId === 'north' ? 70 : 28 };
} });
const bothTracks = (view,options) => view.trades(options,plotFor(options)) + view.timeline(options);

test('all widths, periods, Agents, kinds and grains retain every event once in the correct lane', () => {
  const view = render('zh');
  for (const width of [1000,600,250]) for (const period of data.periods) for (const agent of data.agents) {
    for (const kind of ['all','buy','sell','report']) for (const granularity of ['auto','day','week','month']) {
      const options = { agentId:agent.managerId,period,width,kind,granularity };
      const groups = view.groups(options),events = groups.flatMap(group => group.events);
      const expected = investmentEventFixture.events.filter(event => event.managerId === agent.managerId && event.date >= period.start && event.date <= period.end && (kind === 'all' || event.kind === kind));
      assert.deepEqual(events.map(event => event.id).sort(),expected.map(event => event.id).sort());
      assert.equal(new Set(events.map(event => event.id)).size,events.length);
      assert.equal(new Set(groups.map(group => group.id)).size,groups.length);
      const html = bothTracks(view,options),markers = elements(html).filter(element => element['data-action'] === 'investment-event-group');
      assert.deepEqual(markers.map(marker => marker['data-group']).sort(),groups.map(group => group.id).sort());
      assert.equal(new Set(markers.map(marker => marker.id)).size,markers.length);
      assert.doesNotMatch(html,/NaN|undefined|Infinity/);
      for (const lane of ['trade','report']) {
        const laneGroups = groups.filter(group => group.lane === lane);
        for (let index = 0;index < laneGroups.length;index++) {
          const group = laneGroups[index],marker = markers.find(marker => marker['data-group'] === group.id);
          const expectedDate = lane === 'trade' ? day(group.anchorDate) : (day(group.start) + day(group.end)) / 2;
          const expectedX = 4.2 + ((expectedDate - day(period.start)) / (day(period.end) - day(period.start))) * 93.4;
          assert.ok(Math.abs(group.x - expectedX) < 1e-9);
          assert.ok(group.events.every(event => event.date >= group.start && event.date <= group.end));
          assert.ok(group.events.every(event => (event.kind === 'report') === (lane === 'report')));
          if (lane === 'trade') assert.ok(group.events.some(event => event.date === group.anchorDate),'trade anchor is an actual event date');
          assert.equal(marker['aria-expanded'],'false');
          assert.equal(marker['aria-controls'],'investment-event-popover');
          assert.equal(marker['aria-haspopup'],'dialog');
          assert.ok(marker['aria-label'].includes(group.start));
          if (index) assert.ok((group.x - laneGroups[index - 1].x) * width / 100 >= (lane === 'trade' ? 60 : 64) - 1e-8,`${width}px: adjacent markers in one lane do not overlap`);
          if (group.clustered) {
            assert.ok(group.sourceGroups.length > 1);
            assert.ok(marker['aria-label'].includes(group.end),'combined markers announce the complete date range');
          }
        }
      }
      assert.ok(elements(view.timeline(options)).filter(element => element['data-action'] === 'investment-event-group').every(marker => marker['data-kind'] === 'report'));
      assert.ok(elements(view.trades(options,plotFor(options))).filter(element => element['data-action'] === 'investment-event-group').every(marker => marker['data-kind'] !== 'report'));
    }
  }
});

test('same-day Buy and Report stay separate, with a precise trade anchor and independent highlights', () => {
  const view = render('zh'),options = { agentId:'north',period:{ start:'2026-09-18',end:'2026-09-18' },granularity:'day',width:600 };
  const groups = view.groups(options);
  assert.equal(groups.length,2);
  assert.ok(groups.every(group => Math.abs(group.x - 50.9) < 1e-9));
  assert.deepEqual(groups.map(group => group.events.map(event => event.kind)).sort(),[['buy'],['report']]);
  const trade = groups.find(group => group.lane === 'trade'),report = groups.find(group => group.lane === 'report');
  const selected = { ...options,groupId:trade.id };
  assert.equal(elements(view.timeline(selected)).find(element => element['data-action'] === 'investment-event-group')['aria-expanded'],'false');
  assert.equal(elements(view.trades(selected,plotFor(options))).find(element => element['data-action'] === 'investment-event-group')['aria-expanded'],'true');
  assert.notEqual(trade.id,report.id);
});

test('trade marker positions use the selected Agent and exact anchor date on the shared performance plot', () => {
  const view = render('zh'),options = { ...defaults,width:250 },groups = view.groups(options).filter(group => group.lane === 'trade');
  const calls = [],plot = { pointAt(managerId,date) { calls.push([managerId,date]);return { x:123,y:35 }; } };
  const html = view.trades(options,plot),slots = elements(html).filter(element => element.class === 'investment-trade-slot');
  assert.deepEqual(calls,groups.map(group => ['north',group.anchorDate]));
  assert.equal(slots.length,groups.length);
  assert.ok(slots.every(slot => slot.style === 'left:12.30000%;top:7.29167%'));
  assert.ok(slots.every(slot => slot['data-placement'] === 'below'));
  assert.deepEqual(slots.map(slot => slot['data-anchor-date']),groups.map(group => group.anchorDate));
  assert.deepEqual(view.groups({ ...options,granularity:'month' }).filter(group => group.lane === 'trade'),groups,'report grouping does not aggregate trade dates');
  const mixed = view.groups({ ...defaults,width:1000 }).find(group => group.lane === 'trade' && new Set(group.events.map(event => event.kind)).size === 2);
  assert.ok(mixed.events.every(event => event.date === '2026-09-28'));
  assert.equal(elements(view.trades({ ...defaults,width:1000 },plotFor(defaults))).find(element => element['data-group'] === mixed.id)['data-kind'],'mixed');
  for (const invalid of [null,{}, { pointAt:null }]) assert.throws(() => view.trades(options,invalid),/explicit performance plot/);
  for (const point of [null,{ x:NaN,y:1 },{ x:1,y:Infinity },{ x:-1,y:1 },{ x:1001,y:1 },{ x:1,y:481 }]) assert.throws(() => view.trades(options,{ pointAt:() => point }),/outside the performance plot/);
});

test('narrow plots combine company logos and expose each exact event individually in the popover', () => {
  const view = render('zh'),options = { ...defaults,width:250,granularity:'day' },groups = view.groups(options);
  const group = groups.find(item => new Set(item.events.map(event => event.companyId)).size > 1);
  assert.ok(group);
  const companies = [...new Set(group.events.map(event => event.companyId))];
  const html = bothTracks(view,options);
  const markerBody = html.split(`id="investment-group-${group.id}"`)[1].split('</button>')[0];
  assert.ok(markerBody.includes('investment-marker-icons'));
  assert.deepEqual(elements(markerBody).filter(element => element['data-company-icon']).map(element => element['data-company-icon']),companies.slice(0,2));
  const marker = elements(html).find(element => element.id === `investment-group-${group.id}`);
  for (const companyId of companies) assert.ok(marker['aria-label'].includes(getCompany(companyId).company.name));
  for (const event of group.events) {
    const html = view.popover(options,group.id,event.id),entries = elements(html).filter(element => element['data-event-id']);
    assert.deepEqual(entries.map(entry => entry['data-event-id']),[event.id],'only the selected event is shown');
    assert.ok(html.includes(`datetime="${event.date}"`));
    assert.ok(html.includes(getCompany(event.companyId).company.name));
    assert.ok(html.includes(getCompany(event.companyId).company.ticker));
    assert.ok(html.includes(`${group.start} → ${group.end}`),'group range is explicitly separated from the event date');
    assert.doesNotMatch(html,/investment-event-entries|panel-title|close-panel/);
  }
});

test('popover report titles and links retain the event author, company, document and historical version', () => {
  const view = render('en');
  for (const agent of data.agents) {
    const options = { agentId:agent.managerId,period:data.periods.find(period => period.id === '1y'),width:600 };
    for (const group of view.groups(options)) {
      for (const event of group.events) {
        const html = view.popover(options,group.id,event.id),tags = elements(html);
        const links = tags.filter(element => element.class === 'investment-event-report-link');
        if (event.kind === 'report') {
          const context = getReport(event.companyId,event.report.reportId,event.report.version);
          assert.equal(links.length,1);
          assert.equal(links[0].id,`investment-report-${event.id}`);
          assert.deepEqual(parseRoute(links[0].href),{ managerId:event.managerId,companyId:event.companyId,view:'report',reportId:event.report.reportId,version:event.report.version });
          assert.ok(html.includes(context.report.title),'title comes from the explicitly selected version');
        } else {
          assert.equal(links.length,0,'Buy and Sell do not imply a report or execution action');
          assert.ok(html.includes('execution price and quantity are not provided'));
        }
        assert.ok(tags.some(element => element.id === 'investment-popover-close' && element['data-action'] === 'investment-popover-close'));
        assert.ok(tags.some(element => element.id === 'investment-popover-title' && element.tabindex === '-1'));
        assert.ok(html.includes('Simulated event · Not live'));
        assert.ok(html.includes(getManager(agent.managerId).manager.name));
      }
    }
  }
});

test('empty and filtered-empty periods show no markers and explain the gap in both languages', () => {
  for (const language of ['zh','en']) {
    const view = render(language);
    for (const options of [
      { agentId:'north',period:{ start:'2025-01-01',end:'2025-01-31' } },
      { agentId:'north',period:{ start:'2026-09-03',end:'2026-09-03' },kind:'report' },
    ]) {
      assert.deepEqual(view.groups(options),[]);
      const html = view.timeline(options);
      assert.equal(elements(html).filter(element => element['data-action'] === 'investment-event-group').length,0);
      assert.match(html,language === 'en' ? /No report events/ : /暂无报告事件/);
      assert.match(html,language === 'en' ? /Simulated/ : /模拟/);
    }
  }
});

test('controls keep manual grain and event type selections with bilingual labels', () => {
  for (const language of ['zh','en']) {
    const view = render(language),options = { ...defaults,kind:'sell',granularity:'week' },html = view.controls(options);
    const tags = elements(html),filters = tags.filter(element => element['data-action'] === 'investment-event-kind');
    assert.deepEqual(filters.map(filter => filter['data-kind']),['all','buy','sell','report']);
    assert.deepEqual(filters.filter(filter => filter['aria-pressed'] === 'true').map(filter => filter['data-kind']),['sell']);
    assert.ok(tags.some(element => element.id === 'investment-event-granularity'));
    assert.match(html,/<option value="week" selected>/);
    assert.match(html,language === 'en' ? /Weekly/ : /按周/);
    const track = view.timeline({ ...options,showControls:false });
    assert.doesNotMatch(track,/investment-timeline-heading|investment-event-granularity|investment-event-kind/);
    assert.equal(elements(track).filter(element => element['data-action'] === 'investment-event-group').length,0);
    assert.doesNotMatch(track,/investment-events-empty/,'trade filters collapse the report lane');
    assert.ok(elements(view.trades(options,plotFor(options))).some(element => element['data-action'] === 'investment-event-group'));
    const full = view.timeline(options);
    assert.ok(full.includes(html),'standalone timeline still includes the controls by default');
  }
});

test('unknown or stale groups and invalid widths or scopes fail explicitly', () => {
  const view = render('zh'),options = { ...defaults,granularity:'day',width:1000 },group = view.groups(options)[0];
  assert.throws(() => view.detail(options,'missing-group'),/outside the current selection/);
  assert.throws(() => view.popover(options,'missing-group'),/outside the current selection/);
  assert.throws(() => view.popover(options,group.id,'missing-event'),/outside the selected group/);
  assert.throws(() => view.popover({ ...options,agentId:'field' },group.id),/outside the current selection/);
  assert.throws(() => view.popover(options,group.id,investmentEventFixture.events.find(event => !group.events.some(item => item.id === event.id)).id),/outside the selected group/);
  for (const invalid of [null,1,{},'']) assert.throws(() => view.popover(options,group.id,invalid),/outside the selected group/);
  assert.throws(() => view.timeline({ ...options,groupId:'missing-group' }),/outside the current selection/);
  assert.throws(() => view.detail({ ...options,agentId:'field' },group.id),/outside the current selection/);
  for (const width of [0,-1,NaN,Infinity]) assert.throws(() => view.groups({ ...options,width }),/positive width/);
  assert.throws(() => view.groups({ ...options,agentId:'missing' }),/unknown/);
});

test('grouped popovers default to the first event and provide bounded manual previous / next navigation', () => {
  for (const language of ['zh','en']) {
    const view = render(language),options = { ...defaults,granularity:'day',width:250 };
    const group = view.groups(options).find(item => item.events.length >= 3);
    const initial = view.popover(options,group.id);
    assert.deepEqual(elements(initial).filter(element => element['data-event-id']).map(element => element['data-event-id']),[group.events[0].id]);
    for (let index = 0;index < group.events.length;index++) {
      const html = view.popover(options,group.id,group.events[index].id);
      const buttons = elements(html).filter(element => element['data-action'] === 'investment-popover-step');
      assert.deepEqual(buttons.map(button => button['data-step']),['-1','1']);
      assert.ok(html.includes(`>${index + 1} / ${group.events.length}</span>`));
      const previous = html.match(/<button id="investment-popover-prev"[^>]*>/)[0];
      const next = html.match(/<button id="investment-popover-next"[^>]*>/)[0];
      assert.equal(/\bdisabled\b/.test(previous),index === 0);
      assert.equal(/\bdisabled\b/.test(next),index === group.events.length - 1);
    }
    const singleOptions = { ...defaults,period:{ start:'2026-09-03',end:'2026-09-03' },granularity:'day' };
    const single = view.popover(singleOptions,view.groups(singleOptions)[0].id);
    assert.doesNotMatch(single,/investment-popover-step|investment-popover-pagination/);
  }
});

test('multiple current groups may remain highlighted after resizing while malformed or stale selections are rejected', () => {
  const view = render('zh'),options = { ...defaults,granularity:'day',width:1000 };
  const groups = view.groups(options),groupIds = groups.slice(0,2).map(group => group.id);
  assert.equal(groupIds.length,2);
  const selected = args => elements(bothTracks(view,args)).filter(element => element['data-action'] === 'investment-event-group' && element['aria-expanded'] === 'true').map(element => element['data-group']).sort();
  assert.deepEqual(selected({ ...options,groupIds }),[...groupIds].sort());
  assert.deepEqual(selected({ ...options,groupId:groupIds[0] }),[groupIds[0]],'legacy single selection is preserved');
  assert.deepEqual(selected({ ...options,groupId:null }),[]);
  assert.deepEqual(selected({ ...options,groupId:groupIds[0],groupIds:[] }),[],'explicit groupIds takes precedence over the legacy field');
  for (const invalid of [null,groupIds[0],{},42]) {
    assert.throws(() => view.timeline({ ...options,groupIds:invalid }),/must be an array/);
    assert.throws(() => view.trades({ ...options,groupIds:invalid },plotFor(options)),/must be an array/);
  }
  for (const invalid of [['missing'],[groupIds[0],'missing'],[null],[1]]) {
    assert.throws(() => view.timeline({ ...options,groupIds:invalid }),/outside the current selection/);
    assert.throws(() => view.trades({ ...options,groupIds:invalid },plotFor(options)),/outside the current selection/);
  }
});
