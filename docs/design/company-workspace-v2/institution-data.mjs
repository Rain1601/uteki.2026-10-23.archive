// Explicitly selected, versioned UI fixture. These are illustrative values, not
// market observations, live accounts, trading records or backtested performance.
// The institution portfolio is independent of the agent examples. It is NOT
// reconstructed by adding their holdings or averaging their returns.
export const INSTITUTION_DEMO_SCOPE = Object.freeze({ institutionId: 'uteki', view: 'overview' });

const indexHistory = [
  ['2025-09-30', 100, 100],
  ['2025-10-31', 100.6, 100.4],
  ['2025-11-30', 101.4, 101.2],
  ['2025-12-31', 102, 102],
  ['2026-01-31', 102.8, 102.4],
  ['2026-02-28', 101.6, 101.8],
  ['2026-03-31', 103.1, 102.5],
  ['2026-04-30', 104.8, 103.3],
  ['2026-05-31', 105.4, 102.9],
  ['2026-06-30', 104.9, 103.5],
  ['2026-07-31', 106.2, 104.2],
  ['2026-08-31', 108, 105],
  ['2026-09-07', 108.6, 105.4],
  ['2026-09-14', 108.1, 105.9],
  ['2026-09-21', 109.3, 106.6],
  ['2026-09-30', 110.16, 107.1],
];

// Rebase the same illustrative path for each explicitly named display period.
// This keeps overlapping chart dates and headline returns internally consistent.
function period(id, label, labelEn, start) {
  const points = indexHistory.filter(([date]) => date >= start);
  const first = points[0];
  const series = points.map(([date, value, benchmarkValue]) => ({
    date, value: value / first[1] * 100, benchmarkValue: benchmarkValue / first[2] * 100,
  }));
  const last = series.at(-1);
  return { id, label, labelEn, start, end: last.date,
    returnPct: last.value - 100, benchmarkReturnPct: last.benchmarkValue - 100, series };
}

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

// Preserve the first approved data snapshot verbatim. The active v2 fixture below
// adds illustrative Agent histories without rewriting this historical record.
export const institutionFixtureV1 = freeze({
  institution: {
    id: 'uteki', name: 'Uteki 投资', nameEn: 'Uteki Investment',
    description: '从机构组合出发，理解配置、表现与研究依据。',
    descriptionEn: 'Understand allocation, performance and research from the institution portfolio.',
  },
  simulation: {
    id: 'uteki-institution-ui-2026-09-30', version: 'v1', isSimulated: true,
    asOf: '2026-09-30', currency: 'USD', label: '模拟展示', labelEn: 'Illustrative data',
    benchmarkLabel: '示意基准', benchmarkLabelEn: 'Illustrative benchmark',
    disclosure: '收益、净值路径和持仓均为界面设计模拟数据，不代表实盘或回测。机构组合与各 Agent 示例独立；机构收益不是 Agent 收益的平均值。',
    disclosureEn: 'Returns, index paths and holdings are UI examples, not live or backtested results. The institution portfolio is independent of the agent examples; its return is not an average of agent returns.',
  },
  defaultPeriod: 'ytd',
  periods: [
    period('1m', '近 1 月', '1 month', '2026-08-31'),
    period('ytd', '年初至今', 'Year to date', '2025-12-31'),
    period('1y', '近 1 年', '1 year', '2025-09-30'),
  ],
  portfolio: {
    totalValue: 1000000, cashValue: 100000, cashWeightPct: 10,
    holdings: [
      { companyId: 'alphabet', marketValue: 240000, weightPct: 24 },
      { companyId: 'microsoft', marketValue: 200000, weightPct: 20 },
      { companyId: 'nvidia', marketValue: 160000, weightPct: 16 },
      { companyId: 'costco', marketValue: 120000, weightPct: 12 },
      { companyId: 'arista', marketValue: 100000, weightPct: 10 },
      { companyId: 'eaton', marketValue: 80000, weightPct: 8 },
    ],
  },
  agents: [
    {
      managerId: 'north', returns: { '1m': 1.6, ytd: 9.7, '1y': 12.4 },
      portfolio: {
        totalValue: 600000, cashValue: 60000, cashWeightPct: 10,
        holdings: [
          { companyId: 'alphabet', marketValue: 180000, weightPct: 30 },
          { companyId: 'microsoft', marketValue: 150000, weightPct: 25 },
          { companyId: 'nvidia', marketValue: 120000, weightPct: 20 },
          { companyId: 'costco', marketValue: 90000, weightPct: 15 },
        ],
      },
    },
    {
      managerId: 'field', returns: { '1m': -0.6, ytd: 4.2, '1y': 6.1 },
      portfolio: {
        totalValue: 400000, cashValue: 60000, cashWeightPct: 15,
        holdings: [
          { companyId: 'alphabet', marketValue: 80000, weightPct: 20 },
          { companyId: 'microsoft', marketValue: 60000, weightPct: 15 },
          { companyId: 'costco', marketValue: 60000, weightPct: 15 },
          { companyId: 'arista', marketValue: 80000, weightPct: 20 },
          { companyId: 'eaton', marketValue: 60000, weightPct: 15 },
        ],
      },
    },
  ],
});

// Explicit mock paths, aligned to the dates of this named fixture. Anchor values
// preserve the already shown 1 month / YTD / 1 year returns. Irregular intervening
// values are authored examples, never sourced or inferred market history.
const agentIndexHistories = {
  north: [100, 100.7, 101.8, 112.4 / 1.097, 103.8, 101.9, 104.1, 106.3, 105.7, 107.5, 108.9, 112.4 / 1.016, 111.2, 110.8, 112, 112.4],
  field: [100, 100.9, 100.4, 106.1 / 1.042, 102.5, 103.8, 102.7, 103.9, 104.8, 104.2, 105.4, 106.1 / 0.994, 106.4, 105.7, 106.6, 106.1],
};

function agentSeries(managerId) {
  const history = indexHistory.map(([date], index) => ({ date, value: agentIndexHistories[managerId][index] }));
  return Object.fromEntries(institutionFixtureV1.periods.map(period => {
    const points = history.filter(point => point.date >= period.start && point.date <= period.end);
    const first = points[0].value;
    return [period.id, points.map(point => ({ date: point.date, value: point.value / first * 100 }))];
  }));
}

export const institutionFixtureV2 = freeze({
  ...institutionFixtureV1,
  simulation: { ...institutionFixtureV1.simulation, version: 'v2' },
  defaultAgentId: 'north',
  agents: institutionFixtureV1.agents.map(agent => ({ ...agent, series: agentSeries(agent.managerId) })),
});

export const institutionFixture = institutionFixtureV2;
