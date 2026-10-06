import test from 'node:test';
import assert from 'node:assert/strict';
import { createAllocationHistoryViews } from './allocation-history-view.mjs';
import { getAllocationHistory } from './allocation-history.mjs';
import { ALLOCATION_PALETTES } from './allocation-palettes.mjs';
import { catalog,getInstitution } from './model.mjs';

const institution = getInstitution('uteki');
const render = language => createAllocationHistoryViews({
  t:(zh,en) => language === 'en' ? en : zh,
  companyIcon:company => `<span class="company-icon" data-company-icon="${company.id}"></span>`,
});
const attributes = html => [...html.matchAll(/<[a-zA-Z][^>]*>/g)].map(([tag]) => Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([,key,value]) => [key,value])));
const options = (managerId,period = institution.periods.find(item => item.id === '1y')) => ({ institutionId:'uteki',managerId,period,paletteId:'classic' });
const rows = html => attributes(html).filter(item => item['data-history-company']);
const history = selection => getAllocationHistory({ institutionId:selection.institutionId,managerId:selection.managerId,start:selection.period.start,end:selection.period.end });
const weight = (point,id) => id === 'cash' ? point.cashWeightPct : point.holdings.find(item => item.companyId === id).weightPct;

test('each Agent shows every scoped company, cash and exact selected snapshot weights', () => {
  const view = render('zh');
  for (const managerId of ['north','field']) for (const period of institution.periods) {
    const selection = options(managerId,period),data = history(selection);
    for (const point of data.snapshots) {
      const html = view.snapshot(selection,point.date),holdings = rows(html);
      assert.deepEqual(holdings.map(row => row['data-history-company']),[...data.companyIds,'cash']);
      assert.deepEqual(holdings.map(row => Number(row['data-weight'])),[...point.holdings.map(holding => holding.weightPct),point.cashWeightPct]);
      assert.equal(holdings.reduce((sum,row) => sum + Number(row['data-weight']),0),100);
      assert.ok(html.includes(`datetime="${point.date}"`));
      assert.ok(html.includes('合计 100%'));
      assert.doesNotMatch(html,/收益|成交价|市值|USD/);
    }
    const main = view.main(selection);
    assert.ok(main.includes(`data-selected-date="${data.snapshots.at(-1).date}"`),'the latest explicit snapshot is initially selected');
    assert.ok(main.includes('模拟配置记录 · 非实盘'));
  }
  assert.doesNotMatch(view.main(options('north')),/data-history-company="(?:arista|eaton)"/);
  assert.doesNotMatch(view.main(options('field')),/data-history-company="nvidia"/);
});

test('comparison is percentage-point difference from the immediately preceding in-period record', () => {
  const view = render('zh');
  for (const managerId of ['north','field']) for (const period of institution.periods) {
    const selection = options(managerId,period),data = history(selection);
    for (let index = 0;index < data.snapshots.length;index++) {
      const point = data.snapshots[index],previous = data.snapshots[index - 1];
      const html = view.snapshot(selection,point.date);
      for (const row of rows(html)) {
        assert.equal(row['data-previous-date'],previous?.date ?? '');
        assert.equal(row['data-delta-pp'],previous ? String(Number((weight(point,row['data-history-company']) - weight(previous,row['data-history-company'])).toFixed(2))) : '');
      }
      if (!previous) {
        assert.match(html,/暂无前序比较/);
        assert.doesNotMatch(html,/class="allocation-history-previous-mark"/);
      } else {
        assert.ok(html.includes(`较上次记录 ${previous.date}`));
        assert.doesNotMatch(html,/暂无前序比较/);
      }
    }
  }
  const html = view.snapshot(options('north'),'2026-09-30');
  assert.match(html,/−2 个百分点/);
  assert.match(html,/\+1 个百分点/);
  assert.match(html,/>不变</);
  assert.doesNotMatch(html,/环比收益|买入|卖出/);
  assert.match(render('en').snapshot(options('north'),'2026-09-30'),/−2 pp/);
});

test('zero holdings stay visible, including trend points, with stable company colors across Agents and palettes', () => {
  const view = render('en');
  for (const palette of ALLOCATION_PALETTES) for (const managerId of ['north','field']) {
    const selection = { ...options(managerId),paletteId:palette.id };
    const html = view.main(selection,{ date:selection.period.start });
    for (const row of rows(html).filter(item => item['data-history-company'] !== 'cash')) {
      const companyId = row['data-history-company'];
      const slot = catalog.companies.findIndex(company => company.id === companyId) % palette.light.length;
      assert.equal(row.style,`--history-color:var(--holding-${slot})`);
    }
    assert.equal(rows(html).at(-1).style,'--history-color:var(--holding-cash)');
    const zeroCompany = managerId === 'north' ? 'nvidia' : 'microsoft';
    assert.equal(rows(html).find(row => row['data-history-company'] === zeroCompany)['data-weight'],'0');
    assert.ok(attributes(html).some(item => item['data-trend-company'] === zeroCompany),'zero positions retain their recorded history');
    assert.ok(attributes(html).some(item => item['data-timeline-company'] === zeroCompany && item['data-weight'] === '0'),'an explicit zero remains in each date composition');
    assert.ok(html.includes('Simulated allocations · Not live'));
  }
});

test('timeline offers exactly one explicit button per date, full composition and a persistent back action', () => {
  const view = render('zh');
  for (const managerId of ['north','field']) for (const period of institution.periods) {
    const selection = options(managerId,period),data = history(selection);
    const selected = data.snapshots[Math.floor(data.snapshots.length / 2)].date;
    const html = view.main(selection,{ date:selected }),tags = attributes(html);
    const buttons = tags.filter(item => item['aria-controls'] === 'allocation-history-detail');
    assert.deepEqual(buttons.map(item => item['data-date']),data.snapshots.map(point => point.date));
    assert.deepEqual(buttons.filter(item => item['aria-pressed'] === 'true').map(item => item['data-date']),[selected]);
    for (const button of buttons) {
      assert.equal(button.id,`allocation-history-date-${button['data-date']}`);
      assert.equal(button['data-action'],'allocation-history-snapshot');
    }
    const bands = tags.filter(item => item['data-timeline-company']);
    for (let index = 0;index < data.snapshots.length;index++) {
      const band = bands.slice(index * (data.companyIds.length + 1),(index + 1) * (data.companyIds.length + 1));
      assert.deepEqual(band.map(item => item['data-timeline-company']),[...data.companyIds,'cash']);
      assert.equal(band.reduce((sum,item) => sum + Number(item['data-weight']),0),100);
    }
    assert.ok(html.includes(`${period.start} — ${period.end}`));
    assert.ok(tags.some(item => item.id === 'allocation-history-back' && item['data-action'] === 'allocation-history-close'));
    assert.doesNotMatch(html,/allocation-history-hit|allocation-history-area|allocation-history-guide/,'there is no implicit pointer-area selection or stacked area view');
  }
});

test('small trends contain only actual dated observations on one shared scale and highlight the selected date', () => {
  const view = render('en');
  for (const managerId of ['north','field']) for (const period of institution.periods) {
    const selection = options(managerId,period),data = history(selection);
    const selected = data.snapshots.at(-2).date;
    const html = view.snapshot(selection,selected),tags = attributes(html);
    const charts = tags.filter(item => item['data-trend-company']);
    assert.deepEqual(charts.map(item => item['data-trend-company']),[...data.companyIds,'cash']);
    assert.equal(new Set(charts.map(item => item['data-scale-max'])).size,1,'all row charts share a single visible scale');
    const dots = tags.filter(item => item['data-history-point']);
    for (let index = 0;index < charts.length;index++) {
      const chart = charts[index],points = dots.slice(index * data.snapshots.length,(index + 1) * data.snapshots.length);
      assert.deepEqual(points.map(item => item['data-history-point']),data.snapshots.map(point => point.date));
      assert.deepEqual(points.map(item => Number(item['data-point-weight'])),data.snapshots.map(point => weight(point,chart['data-trend-company'])));
      assert.deepEqual(points.filter(item => item.class.includes('is-selected')).map(item => item['data-history-point']),[selected]);
      assert.equal(Number(points[0].cx),6);
      assert.equal(Number(points.at(-1).cx),154);
      for (let pointIndex = 0;pointIndex < points.length;pointIndex++) {
        const actual = data.snapshots[pointIndex];
        const elapsed = Date.parse(actual.date) - Date.parse(data.start),duration = Date.parse(data.end) - Date.parse(data.start);
        assert.ok(Math.abs(Number(points[pointIndex].cx) - (6 + elapsed / duration * 148)) < .006,'x positions reflect dates, including the shorter weekly intervals');
        assert.ok(Number(points[pointIndex].cy) >= 6 && Number(points[pointIndex].cy) <= 34);
      }
    }
    assert.doesNotMatch(html,/NaN|Infinity/);
  }
});

test('unknown scope, missing periods, absent snapshot dates and unknown palettes fail explicitly', () => {
  const view = render('zh'),selection = options('north');
  for (const override of [
    { institutionId:undefined },{ institutionId:'missing' },{ managerId:undefined },{ managerId:'missing' },
    { period:undefined },{ period:{} },{ period:{ start:'2026-09-01',end:'2026-09-30' } },
    { period:{ start:'2025-01-01',end:'2025-01-31' } },{ paletteId:'missing' },
  ]) assert.throws(() => view.main({ ...selection,...override }));
  for (const date of ['2026-09-01','2024-09-30','missing',null,42]) {
    assert.throws(() => view.main(selection,{ date }),/date must identify a snapshot/);
    assert.throws(() => view.snapshot(selection,date),/date must identify a snapshot/);
  }
  assert.throws(() => view.snapshot(selection),/date must identify a snapshot/);
});

test('display strings are escaped before inclusion in markup', () => {
  const marker = '<img src=x onerror="alert(1)">&';
  const view = createAllocationHistoryViews({ t:() => marker,companyIcon:() => '<span class="company-icon"></span>' });
  const html = view.main(options('north'));
  assert.doesNotMatch(html,/<img| onerror="/);
  assert.ok(html.includes('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;'));
});
