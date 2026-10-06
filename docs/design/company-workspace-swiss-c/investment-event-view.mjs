import { getInvestmentEvents } from './investment-events.mjs';
import { getCompany, getManager, getReport, formatRoute } from './model.mjs';
import { PERFORMANCE_PLOT } from './performance-geometry.mjs';

const e = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[character]));
const day = value => Date.parse(`${value}T00:00:00Z`);
const shortDate = value => `${Number(value.slice(5,7))}/${Number(value.slice(8,10))}`;
const rangeLabel = (start,end) => start === end ? shortDate(start) : `${shortDate(start)}–${start.slice(0,7) === end.slice(0,7) ? Number(end.slice(8,10)) : shortDate(end)}`;
const exactRange = (start,end) => start === end ? start : `${start} → ${end}`;

export function createInvestmentEventViews({ t, companyIcon }) {
  const labels = { all:t('全部','All'), buy:t('买入','Buy'), sell:t('卖出','Sell'), report:t('报告','Report') };
  const codes = { buy:'B', sell:'S', report:'R' };
  const grainLabels = { auto:t('自动','Auto'), day:t('按日','Daily'), week:t('按周','Weekly'), month:t('按月','Monthly') };

  function selection(options) {
    const { agentId,period,kind = 'all',granularity = 'auto',width = 1000 } = options;
    if (!Number.isFinite(width) || width <= 0) throw new Error('Investment timeline requires a positive width');
    const data = getInvestmentEvents({ managerId:agentId,start:period?.start,end:period?.end,kind,granularity });
    const manager = getManager(agentId).manager;
    return { data,manager,kind,granularity,width,period };
  }

  // Report buckets retain their complete period. Trades use an actual event date
  // as their anchor and never turn a combined date range into an execution date.
  function visualGroups(data,period,width) {
    const first = day(period.start),span = day(period.end) - first;
    const center = group => span ? ((day(group.start) + day(group.end)) / 2 - first) / span : .5;
    const clusters = [];
    for (const group of [...data.groups].sort((a,b) => day(a.start) - day(b.start))) {
      const previous = clusters.at(-1);
      if (previous && (center(group) - center(previous)) * width * .934 < 64) {
        previous.sourceGroups.push(group);
        previous.end = group.end > previous.end ? group.end : previous.end;
        previous.events.push(...group.events);
      } else clusters.push({ start:group.start,end:group.end,events:[...group.events],sourceGroups:[group] });
    }
    return clusters.map(group => ({
      ...group,
      id:`report-${group.sourceGroups.length === 1 ? group.sourceGroups[0].id : `cluster-${group.sourceGroups.map(item => item.id).join('_')}`}`,
      lane:'report',
      x:4.2 + center(group) * 93.4,
      clustered:group.sourceGroups.length > 1,
      events:group.events.sort((a,b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id)),
    }));
  }

  function tradeGroups(data,period,width) {
    const first = day(period.start),span = day(period.end) - first;
    const position = date => 4.2 + (span ? (day(date) - first) / span : .5) * 93.4;
    const daily = new Map();
    for (const event of data.events.filter(event => event.kind !== 'report')) {
      if (!daily.has(event.date)) daily.set(event.date,{ start:event.date,end:event.date,anchorDate:event.date,events:[] });
      daily.get(event.date).events.push(event);
    }
    const clusters = [];
    for (const source of daily.values()) {
      const previous = clusters.at(-1);
      if (previous && (position(source.start) - position(previous.anchorDate)) * width / 100 < 60) {
        previous.sourceGroups.push(source);
        previous.end = source.end;
        previous.events.push(...source.events);
      } else clusters.push({ ...source,events:[...source.events],sourceGroups:[source] });
    }
    return clusters.map(group => ({
      ...group,lane:'trade',x:position(group.anchorDate),clustered:group.sourceGroups.length > 1,
      id:`trade-${group.events.map(event => event.id).join('_')}`,
    }));
  }

  function selectionGroups({ data,period,width }) {
    const reports = { groups:data.groups.map(group => ({ ...group,events:group.events.filter(event => event.kind === 'report') })).filter(group => group.events.length) };
    return [...tradeGroups(data,period,width),...visualGroups(reports,period,width)]
      .sort((a,b) => a.start.localeCompare(b.start) || a.lane.localeCompare(b.lane));
  }

  function groups(options) {
    return selectionGroups(selection(options));
  }

  function selectedGroups(options,items) {
    const ids = options.groupIds === undefined ? (options.groupId === undefined || options.groupId === null ? [] : [options.groupId]) : options.groupIds;
    if (!Array.isArray(ids)) throw new Error('Investment event groupIds must be an array');
    if (ids.some(id => typeof id !== 'string' || !items.some(item => item.id === id))) throw new Error('Investment event group is outside the current selection');
    return new Set(ids);
  }

  function markerButton(group,selected,extraClass = '') {
    const kinds = [...new Set(group.events.map(event => event.kind))];
    const companies = [...new Set(group.events.map(event => event.companyId))].map(id => getCompany(id).company);
    const kind = kinds.length === 1 ? kinds[0] : 'mixed';
    const anchor = group.lane === 'trade' ? ` · ${t('曲线锚点','Curve anchor')} ${group.anchorDate}` : '';
    const label = `${exactRange(group.start,group.end)} · ${companies.map(company => company.name).join(', ')} · ${kinds.map(value => labels[value]).join(' / ')} · ${group.events.length} ${t('条事件','events')}${anchor}`;
    const code = kind === 'mixed' ? '+' : codes[kind];
    const icons = companies.length > 1 ? `<span class="investment-marker-icons" aria-hidden="true">${companies.slice(0,2).map(companyIcon).join('')}</span>` : companyIcon(companies[0]);
    return `<button id="investment-group-${e(group.id)}" class="investment-marker${extraClass ? ` ${extraClass}` : ''}" data-action="investment-event-group" data-group="${e(group.id)}" data-lane="${group.lane}" data-kind="${kind}" aria-expanded="${selected}" aria-controls="investment-event-popover" aria-haspopup="dialog" aria-label="${e(label)}">${icons}<span class="investment-marker-code" aria-hidden="true">${code}${group.events.length > 1 ? `<small>${group.events.length}</small>` : ''}</span></button>`;
  }

  function marker(group,selected) {
    return `<div class="investment-marker-slot" style="left:${group.x.toFixed(5)}%" data-group-x="${group.x.toFixed(5)}" data-group-start="${e(group.start)}" data-group-end="${e(group.end)}"><span class="investment-marker-stem" aria-hidden="true"></span>${markerButton(group,selected)}<span class="investment-marker-date" aria-hidden="true">${e(rangeLabel(group.start,group.end))}</span></div>`;
  }

  function trades(options,plot) {
    const items = groups(options),selected = selectedGroups(options,items);
    if (typeof plot?.pointAt !== 'function') throw new Error('Investment trades require an explicit performance plot');
    return items.filter(group => group.lane === 'trade').map(group => {
      const point = plot.pointAt(options.agentId,group.anchorDate);
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.x > PERFORMANCE_PLOT.width || point.y < 0 || point.y > PERFORMANCE_PLOT.height) throw new Error('Investment trade point is outside the performance plot');
      const x = point.x / PERFORMANCE_PLOT.width * 100,y = point.y / PERFORMANCE_PLOT.height * 100;
      const below = point.y < PERFORMANCE_PLOT.height * .2;
      const kinds = new Set(group.events.map(event => event.kind)),kind = kinds.size === 1 ? group.events[0].kind : 'mixed';
      return `<div class="investment-trade-slot" data-group-x="${x.toFixed(5)}" data-group-y="${y.toFixed(5)}" data-anchor-date="${e(group.anchorDate)}" data-kind="${kind}" data-placement="${below ? 'below' : 'above'}" style="left:${x.toFixed(5)}%;top:${y.toFixed(5)}%"><span class="investment-trade-anchor" aria-hidden="true"></span><span class="investment-trade-stem" aria-hidden="true"></span>${markerButton(group,selected.has(group.id),'investment-trade-marker')}</div>`;
    }).join('');
  }

  function controls(options) {
    const { data,manager,kind,granularity } = selection(options);
    const filters = Object.entries(labels).map(([value,label]) => `<button id="investment-kind-${value}" data-action="investment-event-kind" data-kind="${value}" aria-pressed="${value === kind}">${e(label)}</button>`).join('');
    const grains = Object.entries(grainLabels).map(([value,label]) => `<option value="${value}" ${value === granularity ? 'selected' : ''}>${e(label)}${value === 'auto' ? ` · ${e(grainLabels[data.granularity])}` : ''}</option>`).join('');
    return `<div class="investment-timeline-heading"><div class="investment-timeline-title"><h3>${t('投资事件','Investment events')}</h3><span>${e(manager.name)}</span><small>${t('模拟','Simulated')}</small><span class="investment-event-total">${data.events.length} ${t('条','events')}</span></div><div class="investment-timeline-controls"><div class="investment-kind-filter" role="group" aria-label="${t('事件类型','Event type')}">${filters}</div><label class="investment-granularity"><span class="investment-sr-only">${t('报告聚合粒度','Report grouping')}</span><select id="investment-event-granularity" aria-label="${t('报告聚合粒度','Report grouping')}" ${kind === 'buy' || kind === 'sell' ? 'disabled' : ''}>${grains}</select></label></div></div>`;
  }

  function timeline(options) {
    const selectionData = selection(options),{ data,manager,kind } = selectionData;
    const allItems = selectionGroups(selectionData),selected = selectedGroups(options,allItems);
    const items = allItems.filter(group => group.lane === 'report');
    const empty = kind === 'buy' || kind === 'sell' ? '' : `<p class="investment-events-empty">${e(t('该区间暂无报告事件。','No report events in this period.'))}</p>`;
    return `<div id="investment-timeline" class="investment-timeline" data-agent="${e(manager.id)}" data-granularity="${e(data.granularity)}">${options.showControls === false ? '' : controls(options)}${items.length ? `<div class="investment-event-track" role="group" aria-label="${e(t('报告事件，按日期排列；点击查看','Report events by date; click to inspect'))}"><div class="investment-event-axis" aria-hidden="true"></div>${items.map(item => marker(item,selected.has(item.id))).join('')}</div>` : empty}</div>`;
  }

  function reportLink(event) {
    if (event.kind !== 'report') return '';
    if (!event.report) return `<span class="investment-event-report-gap">${t('尚未关联可读报告','No readable report linked')}</span>`;
    const { reportId,version } = event.report;
    const context = getReport(event.companyId,reportId,version);
    if (context.manager.id !== event.managerId) throw new Error('Investment event report belongs to another Agent');
    const route = formatRoute({ managerId:event.managerId,companyId:event.companyId,view:'report',reportId,version });
    return `<a id="investment-report-${e(event.id)}" class="investment-event-report-link" href="${e(route)}">${t('阅读报告','Read report')}<span>${e(version)} ↗</span></a>`;
  }

  function detail(options,groupId) {
    const selected = selection(options),{ manager } = selected;
    const group = selectionGroups(selected).find(item => item.id === groupId);
    if (!group) throw new Error('Investment event group is outside the current selection');
    const rows = group.events.map(event => {
      const company = getCompany(event.companyId).company;
      return `<li class="investment-event-entry" data-event-id="${e(event.id)}" data-kind="${e(event.kind)}"><div class="investment-event-entry-meta"><time datetime="${e(event.date)}">${e(event.date)}</time><span class="investment-event-kind">${e(labels[event.kind])} ${codes[event.kind]}</span></div><div class="investment-event-company">${companyIcon(company)}<span><strong>${e(company.name)}</strong><small>${e(company.ticker)}</small></span></div><p>${e(t(event.title,event.titleEn))}</p>${reportLink(event)}</li>`;
    }).join('');
    return `<div class="panel-title"><h2 id="panel-title" tabindex="-1">${t('投资事件','Investment events')}</h2><button id="close-panel" class="panel-close" data-action="close-panel" aria-label="${t('关闭事件详情','Close event details')}">×</button></div><div class="panel-body investment-event-detail"><div class="investment-event-summary"><strong>${e(manager.name)}</strong><span>${e(exactRange(group.start,group.end))}</span><small>${group.events.length} ${t('条模拟事件 · 非实盘','simulated events · not live trading')}</small></div>${group.clustered ? `<p class="investment-cluster-note">${t('相邻时间合并显示，以下保留每条事件的准确日期。','Nearby dates are grouped; each event retains its exact date below.')}</p>` : ''}<ol class="investment-event-entries">${rows}</ol></div>`;
  }

  function popover(options,groupId,eventId) {
    const selected = selection(options),{ manager } = selected;
    const group = selectionGroups(selected).find(item => item.id === groupId);
    if (!group) throw new Error('Investment event group is outside the current selection');
    const index = eventId === undefined ? 0 : group.events.findIndex(item => item.id === eventId);
    if (index < 0) throw new Error('Investment event is outside the selected group');
    const event = group.events[index],company = getCompany(event.companyId).company;
    const report = event.kind === 'report' && event.report ? getReport(event.companyId,event.report.reportId,event.report.version) : null;
    if (report && report.manager.id !== event.managerId) throw new Error('Investment event report belongs to another Agent');
    const reportBody = report ? `<div class="investment-popover-report"><h3>${e(report.report.title)}</h3>${reportLink(event)}</div>` : '';
    const tradeAnchor = event.kind !== 'report' && group.start !== group.end ? `<span class="investment-popover-anchor-note">${t('组合标记锚定','Grouped marker anchored to')} ${e(group.anchorDate)}。</span>` : '';
    const body = event.kind === 'report' ? reportBody || reportLink(event) : `<p class="investment-popover-action">${e(t(event.title,event.titleEn))}</p><p class="investment-popover-note">${tradeAnchor}${t('标记位置为组合收益，不代表成交价。模拟事件未提供成交价和数量。','The marker shows portfolio return, not an execution price. Simulated execution price and quantity are not provided.')}</p>`;
    const navigation = group.events.length > 1 ? `<footer class="investment-popover-pagination"><div><span>${t('同组事件','Grouped events')}</span><small>${e(exactRange(group.start,group.end))}</small></div><div class="investment-popover-pager"><button id="investment-popover-prev" data-action="investment-popover-step" data-step="-1" aria-label="${t('上一条事件','Previous event')}" ${index === 0 ? 'disabled' : ''}><span aria-hidden="true">‹</span></button><span class="investment-popover-count" aria-live="polite">${index + 1} / ${group.events.length}</span><button id="investment-popover-next" data-action="investment-popover-step" data-step="1" aria-label="${t('下一条事件','Next event')}" ${index === group.events.length - 1 ? 'disabled' : ''}><span aria-hidden="true">›</span></button></div></footer>` : '';
    return `<article class="investment-popover-content" data-event-id="${e(event.id)}" data-kind="${e(event.kind)}"><header class="investment-popover-heading"><div class="investment-popover-identity">${companyIcon(company)}<div><h2 id="investment-popover-title" tabindex="-1">${e(labels[event.kind])}<span class="investment-popover-kind-code" aria-hidden="true">${codes[event.kind]}</span></h2><p>${e(company.name)} <span>${e(company.ticker)}</span></p></div></div><button id="investment-popover-close" class="investment-popover-close" data-action="investment-popover-close" aria-label="${t('关闭事件','Close event')}">×</button></header><div class="investment-popover-body"><div class="investment-popover-provenance"><strong>${e(manager.name)}</strong><small>${t('模拟事件 · 非实盘','Simulated event · Not live')}</small></div><dl class="investment-popover-facts"><div><dt>${t('日期','Date')}</dt><dd><time datetime="${e(event.date)}">${e(event.date)}</time></dd></div></dl>${body}</div>${navigation}</article>`;
  }

  return { timeline,trades,controls,popover,detail,groups };
}
