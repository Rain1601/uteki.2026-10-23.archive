import { getAllocationHistory } from './allocation-history.mjs';
import { catalog, getCompany, getManager } from './model.mjs';
import { DEFAULT_ALLOCATION_PALETTE, getAllocationPalette } from './allocation-palettes.mjs';

const e = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[character]));
const day = date => Date.parse(`${date}T00:00:00Z`);
const shortDate = date => `${Number(date.slice(5,7))}/${Number(date.slice(8,10))}`;
const percentage = value => `${Number(value.toFixed(2))}%`;
const weight = (point,id) => id === 'cash' ? point.cashWeightPct : point.holdings.find(item => item.companyId === id).weightPct;
const rounded = value => Number(value.toFixed(2));

export function createAllocationHistoryViews({ t, companyIcon }) {
  function selection(options) {
    const { institutionId,managerId,period,paletteId = DEFAULT_ALLOCATION_PALETTE } = options ?? {};
    const palette = getAllocationPalette(paletteId);
    const data = getAllocationHistory({ institutionId,managerId,start:period?.start,end:period?.end });
    const manager = getManager(managerId).manager;
    const holdings = data.companyIds.map(companyId => {
      const company = getCompany(companyId).company;
      const colorIndex = catalog.companies.findIndex(item => item.id === companyId);
      if (colorIndex < 0) throw new Error('Allocation history company has no palette identity');
      return { id:companyId,company,color:`var(--holding-${colorIndex % palette.light.length})` };
    });
    holdings.push({ id:'cash',company:null,color:'var(--holding-cash)' });
    // One common vertical scale keeps the small charts comparable across rows.
    const maxWeight = Math.max(...data.snapshots.flatMap(point => holdings.map(holding => weight(point,holding.id))));
    const trendMax = Math.max(10,Math.ceil(maxWeight / 10) * 10);
    return { data,manager,holdings,palette,trendMax };
  }

  function selectedSnapshot(data,date) {
    const selected = data.snapshots.find(item => item.date === date);
    if (!selected) throw new Error('Allocation history date must identify a snapshot in the selected period');
    return selected;
  }

  function trend(context,holding,date) {
    const { data,trendMax } = context;
    const duration = day(data.end) - day(data.start);
    const x = point => 6 + (day(point.date) - day(data.start)) / duration * 148;
    const y = point => 34 - weight(point,holding.id) / trendMax * 28;
    const name = holding.company?.name ?? t('现金','Cash');
    const dots = data.snapshots.map(point => `<circle class="allocation-history-trend-dot${point.date === date ? ' is-selected' : ''}" data-history-point="${e(point.date)}" data-point-weight="${weight(point,holding.id)}" cx="${rounded(x(point))}" cy="${rounded(y(point))}" r="${point.date === date ? 3.3 : 1.8}"><title>${e(point.date)} · ${percentage(weight(point,holding.id))}</title></circle>`).join('');
    const guides = data.snapshots.slice(1).map((point,index) => `<line class="allocation-history-trend-connector" x1="${rounded(x(data.snapshots[index]))}" y1="${rounded(y(data.snapshots[index]))}" x2="${rounded(x(point))}" y2="${rounded(y(point))}"/>`).join('');
    const values = data.snapshots.map(point => `${point.date}: ${percentage(weight(point,holding.id))}`).join('; ');
    return `<svg class="allocation-history-trend" viewBox="0 0 160 40" role="img" data-trend-company="${e(holding.id)}" data-scale-max="${trendMax}" aria-label="${e(`${name} · ${t('已记录占比','Recorded allocation')} · ${values}`)}"><line class="allocation-history-trend-baseline" x1="6" y1="34" x2="154" y2="34"/>${guides}${dots}</svg>`;
  }

  function snapshotContent(context,date) {
    const { data,holdings,trendMax } = context;
    const selected = selectedSnapshot(data,date);
    const previous = data.snapshots[data.snapshots.indexOf(selected) - 1] ?? null;
    const total = selected.holdings.reduce((sum,holding) => sum + holding.weightPct,selected.cashWeightPct);
    const rows = holdings.map(holding => {
      const value = weight(selected,holding.id),name = holding.company?.name ?? t('现金','Cash');
      const prior = previous ? weight(previous,holding.id) : null;
      const delta = previous ? rounded(value - prior) : null;
      const change = delta === null ? '—' : delta === 0 ? t('不变','Unchanged') : `${delta > 0 ? '+' : '−'}${Math.abs(delta)} ${t('个百分点','pp')}`;
      const comparison = previous ? `${t('较上次记录','Since previous record')} ${previous.date}: ${percentage(prior)} → ${percentage(value)}` : t('所选区间首条记录，无前序比较','First record in this period; no earlier comparison');
      const previousMark = previous ? `<i class="allocation-history-previous-mark" style="left:${prior}%" title="${e(`${previous.date} · ${percentage(prior)}`)}" aria-hidden="true"></i>` : '';
      return `<tr class="allocation-history-holding" data-history-company="${e(holding.id)}" data-weight="${value}" data-previous-date="${e(previous?.date ?? '')}" data-delta-pp="${delta ?? ''}" style="--history-color:${holding.color}"><th scope="row"><span class="allocation-history-company">${holding.company ? companyIcon(holding.company) : '<span class="allocation-history-cash-icon" aria-hidden="true">¤</span>'}<span class="allocation-history-holding-name"><strong>${e(name)}</strong><small>${e(holding.company?.ticker ?? t('保留资金','Uninvested'))}</small></span></span></th><td><div class="allocation-history-weight"><strong>${percentage(value)}</strong><span class="allocation-history-weight-track" aria-hidden="true"><i class="allocation-history-weight-fill" style="width:${value}%"></i>${previousMark}</span></div></td><td class="allocation-history-change" title="${e(comparison)}"><span${delta !== null && delta !== 0 ? ' class="has-change"' : ''}>${e(change)}</span></td><td>${trend(context,holding,date)}</td></tr>`;
    }).join('');
    const comparison = previous ? `${t('较上次记录','Since previous record')} ${previous.date}` : t('区间首条记录 · 暂无前序比较','First record in period · No earlier comparison');
    return `<div class="allocation-history-snapshot" data-snapshot-date="${e(selected.date)}" data-previous-date="${e(previous?.date ?? '')}"><div class="allocation-history-snapshot-heading"><div><time datetime="${e(selected.date)}">${e(selected.date)}</time><span>${e(t('的持仓配置','allocation'))}</span><small>${e(comparison)}</small></div><strong>${e(t('合计','Total'))} ${percentage(total)}</strong></div><div class="allocation-history-table-wrap"><table class="allocation-history-holdings"><thead><tr><th scope="col">${e(t('公司 / 资产','Company / asset'))}</th><th scope="col">${e(t('配置占比','Allocation'))}</th><th scope="col">${e(t('占比变化','Weight change'))}</th><th scope="col"><span>${e(t('区间记录','Period records'))}</span><small>0–${trendMax}%</small></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }

  function snapshot(options,date) {
    return snapshotContent(selection(options),date);
  }

  function main(options,state = {}) {
    const context = selection(options),{ data,manager,holdings,palette } = context;
    const date = state.date === undefined ? data.snapshots.at(-1)?.date : state.date;
    const selected = selectedSnapshot(data,date);
    const dates = data.snapshots.map(point => {
      const bands = holdings.map(holding => `<i data-timeline-company="${e(holding.id)}" data-weight="${weight(point,holding.id)}" style="width:${weight(point,holding.id)}%;background:${holding.color}"></i>`).join('');
      return `<button id="allocation-history-date-${e(point.date)}" class="allocation-history-date" data-action="allocation-history-snapshot" data-date="${e(point.date)}" aria-pressed="${point.date === date}" aria-controls="allocation-history-detail" aria-label="${e(t('查看配置记录','View allocation record') + ' · ' + point.date)}"><span class="allocation-history-date-node" aria-hidden="true"></span><time datetime="${e(point.date)}"><strong>${e(shortDate(point.date))}</strong><small>${e(point.date.slice(0,4))}</small></time><span class="allocation-history-date-band" aria-hidden="true">${bands}</span></button>`;
    }).join('');
    return `<section id="allocation-history" class="allocation-history" data-manager="${e(manager.id)}" data-selected-date="${e(selected.date)}" data-allocation-palette="${e(palette.id)}"><header class="allocation-history-heading"><button id="allocation-history-back" class="allocation-history-back" data-action="allocation-history-close" aria-label="${e(t('返回投资表现','Back to performance'))}"><span aria-hidden="true">←</span>${e(t('返回','Back'))}</button><h3>${e(manager.name)} <span>${e(t('持仓变化','Allocation history'))}</span></h3><span class="allocation-history-simulation">${e(t('模拟配置记录 · 非实盘','Simulated allocations · Not live'))}</span></header><div class="allocation-history-timeline-heading"><span>${e(t('选择记录日期','Select a record'))}<small>${data.snapshots.length} ${e(t('次记录','records'))}</small></span><span>${e(data.start)} — ${e(data.end)}</span></div><div class="allocation-history-dates" role="group" aria-label="${e(t('选择配置记录日期','Select an allocation record date'))}">${dates}</div><div id="allocation-history-detail">${snapshotContent(context,date)}</div><p class="allocation-history-note">${e(t('占比变化与上一次已记录日期比较，单位为百分点；圆点为明确日期的记录，虚线仅辅助阅读，不代表连续观测或买卖。','Weight changes compare with the previous recorded date, in percentage points. Dots are dated records; dotted connectors are reading guides, not continuous observations or trades.'))}</p></section>`;
  }

  return { main,snapshot };
}
