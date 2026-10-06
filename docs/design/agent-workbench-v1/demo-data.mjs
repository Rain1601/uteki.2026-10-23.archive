// Named synthetic fixtures for interaction review. No financial fact or live run.
const b = (zh, en) => ({ zh, en });
const scope = b('虚构演示材料 · 数字为布局示例，不是公司财务数据', 'Synthetic demo material · numbers illustrate the layout, not company financial data');
const step = (id, actor, title, text, artifactIds = []) => ({ id, actor, title, text, artifactIds });
const artifact = (id, taskId, runId, kind, title, content, extra = {}) => ({ id, taskId, runId, kind, title, content, scopeLabel: scope, ...extra });
const criteria = [
  { id: 'scope', label: b('公司与期间是否正确', 'Correct company and period') },
  { id: 'evidence', label: b('原文是否支持产物', 'Source supports the output') },
  { id: 'coverage', label: b('缺口是否明确说明', 'Gaps are explicit') },
];

export const DEMO = {
  id: 'agent-workbench-synthetic-v1',
  label: b('交互 Demo · 虚构任务与产物 · 不连接模型', 'Interaction demo · synthetic tasks and outputs · no model connection'),
  initialTaskId: 'data-googl-cashflow',
  roles: [
    { id: 'data', label: b('Data Agent', 'Data Agent'), description: b('材料处理、数据抽取与证据核验', 'Material processing, extraction and evidence review') },
    { id: 'analysis', label: b('Analysis Agent', 'Analysis Agent'), description: b('研究问题、论点与报告候选', 'Research questions, theses and draft reports') },
  ],
  tasks: [
    {
      id: 'data-googl-cashflow', role: 'data', companyIds: ['alphabet'], symbols: ['GOOGL'],
      title: b('GOOGL · 年度现金流核验', 'GOOGL · annual cash-flow review'),
      goal: b('用虚构材料演示：核对现金流记录的期间、单位与原文定位。', 'Use synthetic material to demonstrate period, unit and source checks for a cash-flow record.'),
      status: 'review', trigger: b('Analysis Agent 请求补充证据（演示）', 'Evidence request from Analysis Agent (demo)'),
      inputs: [{ label: b('材料', 'Material'), value: b('GOOGL 演示年报 · 非真实财报', 'GOOGL sample annual report · not a real filing') }, { label: b('范围', 'Scope'), value: b('演示期间 FY-A / FY-B；不对应真实年份', 'Sample periods FY-A / FY-B; no real fiscal years') }],
      runs: [
        { id: 'googl-cashflow-r1', label: b('运行 1 · 缺少单位', 'Run 1 · missing unit'), model: 'Demo Model A', version: 'cashflow-demo-v1', status: 'gap', summary: b('找到数值 120，但没有保留表头单位。当前证据不足，不能作为正式事实。', 'Found the value 120, but did not retain the table-header unit. Evidence is insufficient for a formal fact.'), artifactIds: ['googl-record-v1'], steps: [
          step('g1-plan', 'Planner', b('确认问题与范围', 'Confirm question and scope'), b('仅处理 Alphabet 的虚构 FY-B 材料。', 'Use only Alphabet synthetic FY-B material.')),
          step('g1-extract', 'Worker', b('抽取候选记录', 'Extract a candidate record'), b('保留了数值，遗漏表头单位；这是刻意设置的演示缺陷。', 'Retained the number but omitted the header unit: an intentional demo defect.'), ['googl-record-v1']),
          step('g1-review', 'Reviewer', b('发现证据缺口', 'Find an evidence gap'), b('单位未核验，记录保持候选状态。', 'The unit is unverified; the record remains a candidate.'), ['googl-record-v1']),
        ] },
        { id: 'googl-cashflow-r2', label: b('运行 2 · 待人工评审', 'Run 2 · awaiting human review'), model: 'Demo Model B', version: 'cashflow-demo-v2', status: 'review', summary: b('演示记录已关联数值、期间和单位。请检查原文是否充分支持该记录；尚无真实评审结论。', 'The sample record links its number, period and unit. Check whether the source supports the record; no real review verdict exists.'), artifactIds: ['googl-record-v2', 'googl-source-v2', 'googl-table-v2'], steps: [
          step('g2-plan', 'Planner', b('明确核验清单', 'Define the verification checklist'), b('检查公司、期间、币种、单位与表格行列。', 'Check company, period, currency, unit and table coordinates.')),
          step('g2-read', 'Worker', b('读取表头与数据行', 'Read headers and data rows'), b('演示工具返回表头、单位和数据行，保持同一来源范围。', 'The simulated tool result contains headers, units and a data row from one source.'), ['googl-source-v2', 'googl-table-v2']),
          step('g2-extract', 'Worker', b('生成结构化记录', 'Create a structured record'), b('将 120 演示单位与 FY-B 绑定，不转换成真实美元金额。', 'Bind 120 demo units to FY-B without converting it into a real dollar amount.'), ['googl-record-v2']),
          step('g2-review', 'Reviewer', b('准备人工核验', 'Prepare for human review'), b('把候选记录与支持片段并排呈现。实际评价由评审者填写。', 'Present the candidate record with supporting excerpts. The reviewer supplies the actual assessment.'), ['googl-record-v2', 'googl-source-v2']),
        ] },
      ], relatedTaskIds: ['analysis-googl-investment', 'data-cross-company'], criteria,
    },
    {
      id: 'data-msft-report', role: 'data', companyIds: ['microsoft'], symbols: ['MSFT'],
      title: b('MSFT · 年报材料处理', 'MSFT · annual-report processing'), goal: b('检查材料如何变成文本块、表格与缺口记录。', 'Inspect how material becomes text blocks, tables and gap records.'), status: 'gap', trigger: b('材料入库任务（演示）', 'Material intake task (demo)'),
      inputs: [{ label: b('材料', 'Material'), value: b('MSFT 虚构年报片段；FY-B', 'Synthetic MSFT annual-report excerpt; FY-B') }],
      runs: [{ id: 'msft-report-r1', label: b('运行 1 · 有解析缺口', 'Run 1 · parsing gap'), model: 'Demo Model A', version: 'material-demo-v1', status: 'gap', summary: b('已产生文本块；一张示意图片没有文字内容，材料覆盖仍有缺口。', 'Text blocks are available. One illustrative image has no text content, leaving a coverage gap.'), artifactIds: ['msft-blocks', 'msft-gap'], steps: [
        step('m1-intake', 'Ingest', b('登记材料范围', 'Register material scope'), b('绑定 Microsoft、虚构 FY-B 与演示材料版本。', 'Bind Microsoft, synthetic FY-B and the demo source version.')),
        step('m1-parse', 'Parser', b('拆分文本与表格', 'Split text and tables'), b('输出三个示意文本块；没有将图像内容假装为已读取。', 'Output three sample blocks; image contents are not presented as read.'), ['msft-blocks']),
        step('m1-review', 'Reviewer', b('登记未解析图片', 'Register the unread image'), b('图片证据留空并进入待处理缺口。', 'Image evidence stays empty and is recorded as a gap.'), ['msft-gap']),
      ] }], relatedTaskIds: ['analysis-msft-research', 'data-cross-company'], criteria,
    },
    {
      id: 'data-cross-company', role: 'data', companyIds: ['alphabet', 'microsoft'], symbols: ['GOOGL', 'MSFT'],
      title: b('GOOGL / MSFT · 指标口径对比', 'GOOGL / MSFT · metric-scope comparison'), goal: b('演示多公司查询：各自保留公司、期间、单位和证据；无法对齐时明确说明。', 'Demonstrate a multi-company query that preserves company, period, unit and evidence, with explicit non-comparability.'), status: 'review', trigger: b('人工创建的对照任务（演示）', 'Manually created comparison task (demo)'),
      inputs: [{ label: b('公司列表', 'Company list'), value: 'GOOGL, MSFT' }, { label: b('指标', 'Metric'), value: b('演示现金流指标；不构成投资比较', 'Sample cash-flow metric; not an investment comparison') }],
      runs: [{ id: 'cross-company-r1', label: b('运行 1 · 保留差异', 'Run 1 · differences retained'), model: 'Demo Model B', version: 'comparison-demo-v1', status: 'review', summary: b('两家公司保持独立来源；演示财年范围不一致，暂不计算同比或排序。', 'Each company retains a separate source. Synthetic fiscal ranges differ, so growth rates and ranking are not calculated.'), artifactIds: ['cross-company-table'], steps: [
        step('c1-scope', 'Planner', b('解析两个公司范围', 'Resolve both company scopes'), b('显式指定 Alphabet 与 Microsoft；没有使用首家公司填补另一家。', 'Explicitly specify Alphabet and Microsoft; neither fills the other’s gaps.')),
        step('c1-query', 'Worker', b('分别获取记录', 'Retrieve each company separately'), b('按公司与来源保留两条演示记录。', 'Retain two sample records with separate company and source identities.'), ['cross-company-table']),
        step('c1-check', 'Reviewer', b('发现期间不可比', 'Find incompatible periods'), b('保留原始范围，不静默合并财年。', 'Retain original scopes rather than silently merging fiscal calendars.'), ['cross-company-table']),
      ] }], relatedTaskIds: ['data-googl-cashflow', 'data-msft-report'], criteria,
    },
    {
      id: 'analysis-googl-investment', role: 'analysis', companyIds: ['alphabet'], symbols: ['GOOGL'],
      title: b('GOOGL · 投入与回报研究', 'GOOGL · investment and returns research'), goal: b('演示研究任务如何组织问题、证据需求和报告候选。', 'Demonstrate research questions, evidence requests and a candidate report.'), status: 'review', trigger: b('持续研究计划（演示）', 'Ongoing research plan (demo)'),
      inputs: [{ label: b('研究窗口', 'Research horizon'), value: b('3–5 年；仅用于展示任务配置', '3–5 years; shown as task configuration only') }, { label: b('依赖', 'Dependency'), value: b('GOOGL 年度现金流核验任务', 'GOOGL annual cash-flow review task') }],
      runs: [{ id: 'analysis-googl-r1', label: b('运行 1 · 报告候选', 'Run 1 · report candidate'), model: 'Demo Research Model', version: 'research-demo-v1', status: 'review', summary: b('已形成示意报告结构。没有给出真实投资观点、估值或买卖建议。', 'An illustrative report structure is available. It contains no real thesis, valuation or trading recommendation.'), artifactIds: ['googl-report'], steps: [
        step('ag1-plan', 'Analyst', b('提出研究问题', 'Frame research questions'), b('投入增长与回报兑现之间，需要哪些可观察证据？这是示意问题。', 'What observable evidence connects investment growth to realized returns? This is an illustrative question.')),
        step('ag1-request', 'Analyst', b('申请补充数据', 'Request more evidence'), b('关联 Data Agent 的现金流任务；该关联用于导航演示。', 'Link the Data Agent cash-flow task as a navigation example.')),
        step('ag1-write', 'Analyst', b('组织报告候选', 'Organize a candidate report'), b('区分研究问题、支持与反向证据、待验证假设。', 'Separate questions, supporting and opposing evidence, and untested assumptions.'), ['googl-report']),
      ] }], relatedTaskIds: ['data-googl-cashflow'], criteria,
    },
    {
      id: 'analysis-msft-research', role: 'analysis', companyIds: ['microsoft'], symbols: ['MSFT'],
      title: b('MSFT · 研究框架检查', 'MSFT · research-framework check'), goal: b('检查材料覆盖不足时，研究产物如何说明限制。', 'Inspect how a research output describes limited source coverage.'), status: 'complete', trigger: b('研究模板演练（演示）', 'Research-template exercise (demo)'),
      inputs: [{ label: b('依赖', 'Dependency'), value: b('MSFT 年报材料处理任务；存在图像缺口', 'MSFT annual-report processing task; image coverage gap') }],
      runs: [{ id: 'analysis-msft-r1', label: b('运行 1 · 示例已准备', 'Run 1 · sample ready'), model: 'Demo Research Model', version: 'research-demo-v1', status: 'complete', summary: b('本次演示完成的是研究框架检查。材料缺口仍保留，没有发布真实报告。', 'The sample framework check is complete. Source gaps remain and no real report has been published.'), artifactIds: ['msft-report'], steps: [
        step('am1-check', 'Analyst', b('检查输入可用性', 'Check input availability'), b('识别依赖材料的图像缺口。', 'Identify the image gap in the source task.')),
        step('am1-result', 'Reviewer', b('检查限制说明', 'Review stated limitations'), b('示例报告明确标注未覆盖材料及不可下结论的部分。', 'The sample report explicitly lists uncovered material and unresolved conclusions.'), ['msft-report']),
      ] }], relatedTaskIds: ['data-msft-report'], criteria,
    },
  ],
  artifacts: [
    artifact('googl-record-v1', 'data-googl-cashflow', 'googl-cashflow-r1', 'record', b('候选记录 · 单位缺失', 'Candidate record · missing unit'), b('公司：Alphabet；期间：FY-B；指标：演示现金流；数值：120；单位：未取得。不能据此推断实际财务金额。', 'Company: Alphabet; period: FY-B; metric: sample cash flow; value: 120; unit: missing. No actual financial amount can be inferred.')),
    artifact('googl-record-v2', 'data-googl-cashflow', 'googl-cashflow-r2', 'record', b('候选记录 · 证据已关联', 'Candidate record · evidence linked'), b('公司：Alphabet；期间：FY-B；数值：120；单位：演示单位；来源：虚构年报表 A，行 2 / 列 FY-B。待人工核验，不进入真实数据底座。', 'Company: Alphabet; period: FY-B; value: 120; unit: demo units; source: synthetic annual-report table A, row 2 / column FY-B. Awaiting human review; never enters the real data store.')),
    artifact('googl-source-v2', 'data-googl-cashflow', 'googl-cashflow-r2', 'source', b('原文示意 · 表头与上下文', 'Source example · headers and context'), b('【虚构材料】Alphabet 演示现金流表 A\n所有数字均使用“演示单位”，不代表美元或实际公司财务。\n列标题：FY-A、FY-B。\n行标签：演示经营现金流；对应数值：100、120。\n阅读时需要同时保留公司、行名、期间和表头单位。', '[SYNTHETIC MATERIAL] Alphabet sample cash-flow table A\nAll numbers use “demo units”; they are neither dollars nor actual company financials.\nColumn headers: FY-A, FY-B.\nRow: sample operating cash flow; values: 100, 120.\nRead the company, row, period and header unit together.')),
    artifact('googl-table-v2', 'data-googl-cashflow', 'googl-cashflow-r2', 'table', b('解析表格 · 演示单位', 'Parsed table · demo units'), b('用于检查表头、行与列的对应关系。', 'Inspect the correspondence between headers, rows and columns.'), { columns: [b('项目', 'Item'), b('FY-A', 'FY-A'), b('FY-B', 'FY-B'), b('单位', 'Unit')], rows: [[b('演示经营现金流', 'Sample operating cash flow'), '100', '120', b('演示单位', 'Demo units')]] }),
    artifact('msft-blocks', 'data-msft-report', 'msft-report-r1', 'table', b('解析块列表', 'Parsed-block list'), b('以下是具名虚构解析结果，用于展示材料结构。', 'Named synthetic parsing results for reviewing document structure.'), { columns: [b('块 ID', 'Block ID'), b('类型', 'Type'), b('内容', 'Content')], rows: [['demo-msft-001', b('标题', 'Heading'), b('业务描述（示意）', 'Business description (sample)')], ['demo-msft-002', b('段落', 'Paragraph'), b('此处展示业务说明文本的结构，不包含真实结论。', 'Illustrative business-description structure without real conclusions.')], ['demo-msft-003', b('图片引用', 'Image reference'), b('文字未取得，保持缺口', 'Text unavailable; gap retained')]] }),
    artifact('msft-gap', 'data-msft-report', 'msft-report-r1', 'record', b('覆盖缺口 · 图片未解析', 'Coverage gap · unread image'), b('位置：demo-msft-003。状态：缺少图像文字。影响：不能声称材料已完整覆盖。下一步：补充图片读取后再评审；此 Demo 不执行该操作。', 'Location: demo-msft-003. Status: image text missing. Impact: full source coverage cannot be claimed. Next: read the image and review again; this demo does not execute that action.')),
    artifact('cross-company-table', 'data-cross-company', 'cross-company-r1', 'table', b('多公司范围对照', 'Multi-company scope comparison'), b('所有值均为虚构演示；保留不一致的期间，不计算财务优劣。', 'All values are synthetic. Different periods are retained; no financial ranking is calculated.'), { columns: [b('公司', 'Company'), b('来源', 'Source'), b('期间', 'Period'), b('值', 'Value'), b('限制', 'Limitation')], rows: [['GOOGL', 'demo-googl-A', b('演示财年 A', 'Sample fiscal year A'), b('120 演示单位', '120 demo units'), b('期间无法直接对齐', 'Periods cannot be aligned directly')], ['MSFT', 'demo-msft-B', b('演示财年 B', 'Sample fiscal year B'), b('80 演示单位', '80 demo units'), b('未按统一期间重算', 'Not recalculated for a common period')]] }),
    artifact('googl-report', 'analysis-googl-investment', 'analysis-googl-r1', 'report', b('研究报告候选 · 结构演示', 'Candidate research report · structure demo'), b('研究问题\n投入增长需要哪些收入、利润与现金流证据支持？\n\n证据需求\n调用关联 Data 任务查看口径与期间；不把缺少单位的数值纳入结论。\n\n反向证据与风险\n此处展示反证位置；没有生成真实公司的风险判断。\n\n结论状态\n仅为结构演示，不能作为投资建议。', 'Research question\nWhat revenue, profit and cash-flow evidence would support investment growth?\n\nEvidence requests\nInspect scope and periods in the linked Data task; exclude numbers with missing units.\n\nOpposing evidence and risks\nThis section shows where counterevidence belongs; no real company risk assessment has been generated.\n\nConclusion status\nStructure demo only, not investment advice.')),
    artifact('msft-report', 'analysis-msft-research', 'analysis-msft-r1', 'report', b('研究框架检查 · 限制说明', 'Research-framework check · limitations'), b('已检查：示意报告包含问题、证据与缺口栏位。\n尚未覆盖：年报图像引用的内容。\n对研究的影响：有关该图片的判断暂不能成立。\n本页不包含真实 MSFT 观点、估值或推荐。', 'Checked: the sample report has questions, evidence and gap fields.\nNot covered: the annual-report image reference.\nResearch impact: conclusions depending on that image remain unresolved.\nNo real MSFT thesis, valuation or recommendation appears here.')),
  ],
  experiment: {
    id: 'cashflow-synthetic-comparison', title: b('相同问题 · 两种配置', 'Same question · two configurations'), scope: b('虚构评测对照，分数与结论为预设演示，不代表模型实测效果。', 'Synthetic comparison; preset verdicts demonstrate the interface, not measured model quality.'),
    configurations: [
      { id: 'config-a', label: 'Demo A', description: b('抽取示例 v1 · 刻意缺失表头单位', 'Extraction sample v1 · intentionally missing header unit') },
      { id: 'config-b', label: 'Demo B', description: b('抽取示例 v2 · 包含单位与上下文', 'Extraction sample v2 · includes unit and context') },
    ], cases: [
      { id: 'case-unit', taskId: 'data-googl-cashflow', title: b('数值是否有单位与来源？', 'Does the value retain its unit and source?'), results: [
        { configurationId: 'config-a', verdict: 'insufficient', text: b('只有 120，缺少单位；预设演示判断。', 'Only 120 is retained; the unit is missing. Preset demo verdict.'), artifactId: 'googl-record-v1' },
        { configurationId: 'config-b', verdict: 'supported', text: b('120 演示单位与 FY-B 关联；预设演示判断。', '120 demo units is linked to FY-B. Preset demo verdict.'), artifactId: 'googl-record-v2' },
      ] },
      { id: 'case-context', taskId: 'data-googl-cashflow', title: b('能否返回完整上下文？', 'Can the full context be inspected?'), results: [
        { configurationId: 'config-a', verdict: 'insufficient', text: b('未提供表头上下文；预设演示判断。', 'Header context is unavailable. Preset demo verdict.'), artifactId: 'googl-record-v1' },
        { configurationId: 'config-b', verdict: 'supported', text: b('可展开虚构原文与表格；预设演示判断。', 'Synthetic source and table can be opened. Preset demo verdict.'), artifactId: 'googl-source-v2' },
      ] },
    ],
  },
};
