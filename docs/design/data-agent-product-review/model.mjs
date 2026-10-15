// Authored fiction for design review only. Never use this file as a production
// prompt, an execution-agent input, or an independently verified gold dataset.
export const L = (zh, en) => ({ zh, en });
export const views = {
  query: L('数据问答', 'Ask data'),
  materials: L('资料与资产', 'Materials'),
  corrections: L('纠错与修订', 'Corrections'),
  compare: L('两套方案对照', 'Compare stacks'),
};
export const scenarios = {
  financial: {code:'BC03 · BC14', name:L('完整回答', 'Complete answer'), question:L('给出 FY2024、FY2025 合并收入、合并净利润、各自同比变化，以及公司披露的变化说明和出处。', 'Show consolidated revenue and net income for FY2024 and FY2025, their year-over-year changes, and the company’s explanations with sources.')},
  gap: {code:'BC05', name:L('缺数据时', 'Missing data'), question:L('FY2025 合并收入同比增长了多少？', 'How much did consolidated revenue grow in FY2025?')},
  latest: {code:'BC09a', name:L('最新检查失败', 'Freshness unknown'), question:L('给我最新年度报告的合并收入。', 'Show consolidated revenue from the latest annual report.')},
  clarify: {code:'BC04', name:L('先澄清再回答', 'Clarify first'), question:L('这家公司去年增长怎么样？', 'How much did this company grow last year?')},
};
export const assets = [
  {id:'annual25', title:L('FY2025 年度报告', 'FY2025 Annual report'), period:'FY2025', published:'2026-02-10', format:'PDF', pages:96, source:'S25', category:'annual'},
  {id:'earnings25', title:L('FY2025 年度业绩材料', 'FY2025 Earnings release'), period:'FY2025', published:'2026-02-10', format:'HTML', pages:null, source:'E25', category:'earnings'},
  {id:'annual24', title:L('FY2024 年度报告', 'FY2024 Annual report'), period:'FY2024', published:'2025-02-12', format:'PDF', pages:88, source:'S24', category:'annual'},
  {id:'earnings24', title:L('FY2024 年度业绩材料', 'FY2024 Earnings release'), period:'FY2024', published:'2025-02-12', format:'HTML', pages:null, source:'E24', category:'earnings'},
];
export const sources = {
  S25: {asset:'annual25', locator:L('第 42 页 · 合并利润表', 'Page 42 · Consolidated income statement'), heading:L('合并利润表', 'Consolidated income statement'), text:L('单位：百万美元。FY2025 合并收入为 120，合并净利润为 8。', 'USD millions. FY2025 consolidated revenue is 120; consolidated net income is 8.'), table:true, period:'FY2025', revenue:120, profit:8},
  S24: {asset:'annual24', locator:L('第 38 页 · 合并利润表', 'Page 38 · Consolidated income statement'), heading:L('合并利润表', 'Consolidated income statement'), text:L('单位：百万美元。FY2024 合并收入为 100，合并净利润为 10。', 'USD millions. FY2024 consolidated revenue is 100; consolidated net income is 10.'), table:true, period:'FY2024', revenue:100, profit:10},
  M25: {asset:'annual25', locator:L('第 18 页 · 经营讨论', 'Page 18 · Management discussion'), heading:L('管理层对本年度变化的说明', 'Management’s explanation of the year'), text:L('订阅客户增加促进了收入增长；新增合规支出压低了净利润。', 'Growth in subscription customers supported revenue growth; additional compliance expenses reduced net income.'), table:false, period:'FY2025'},
  E25: {asset:'earnings25', locator:L('年度业绩 · 财务摘要', 'Annual results · Financial highlights'), heading:L('FY2025 年度业绩摘要', 'FY2025 Financial highlights'), text:L('FY2025 合并收入 120 百万美元，合并净利润 8 百万美元。', 'FY2025 consolidated revenue: USD 120 million; consolidated net income: USD 8 million.'), table:true, period:'FY2025', revenue:120, profit:8},
  E24: {asset:'earnings24', locator:L('年度业绩 · 财务摘要', 'Annual results · Financial highlights'), heading:L('FY2024 年度业绩摘要', 'FY2024 Financial highlights'), text:L('FY2024 合并收入 100 百万美元，合并净利润 10 百万美元。', 'FY2024 consolidated revenue: USD 100 million; consolidated net income: USD 10 million.'), table:true, period:'FY2024', revenue:100, profit:10},
};
export const periods = {FY2024:'2023-10-01 — 2024-09-30', FY2025:'2024-10-01 — 2025-09-30'};
export const calculations = [
  {metric:'revenue', before:100, after:120, delta:20, growth:20, refs:['S24','S25']},
  {metric:'profit', before:10, after:8, delta:-2, growth:-20, refs:['S24','S25']},
];
export const profiles = {
  A: {sdk:'OpenAI Agents SDK', model:'GPT', id:'data-gpt-openai-draft-01', version:'draft-01',
    content:`# Role\nYou are a data research agent. Complete every explicit information need using the available evidence tools.\n\n# Working sequence\n1. Identify the requested entity, periods, financial definitions and source boundaries. Clarify only unresolved constraints.\n2. Find and read the evidence. Keep source locations and versions attached to each fact.\n3. Use the calculation tool for arithmetic with evidence-backed operands. Check the complete request before delivery.\n\n# Delivery\nReturn the requested data, disclosed explanations, citations and any unresolved needs. Attribute management statements. If a latest-source check fails, label older eligible material as freshness unconfirmed with its publication date.\n\n# Boundaries\nDo not invent facts, turn null into zero, silently change scope, or use memory as current financial evidence. Corrections must preserve old versions. Follow the host-enforced permissions and budget.`,
  },
  B: {sdk:'OpenAI Agents SDK', model:'Claude', id:'data-claude-openai-draft-01', version:'draft-01',
    content:`<role>Fulfill data requests with traceable source evidence.</role>\n<task_contract>Resolve entity, fiscal periods, definitions and allowed sources from the request and verified metadata. Ask one focused clarification when these remain ambiguous.</task_contract>\n<evidence_workflow>Use the registered Data functions to find and read materials. Associate each figure with its precise source version, period and unit. Submit cited operands to the calculation tool. Audit coverage of every requested item before returning.</evidence_workflow>\n<delivery>Provide figures, calculations, attributed management explanations, citations and explicit gaps. An older eligible report may be returned after a failed freshness check only with its publication date and an unconfirmed-latest label.</delivery>\n<limits>Do not supply missing facts from memory, treat null as zero, broaden scope, overwrite earlier evidence, or bypass host permissions and budget.</limits>`,
  },
  C: {sdk:'Claude Agent SDK', model:'Claude', id:'data-claude-native-draft-01', version:'draft-01',
    content:`<role>Fulfill data requests with traceable source evidence.</role>\n<task_contract>Resolve entity, fiscal periods, definitions and allowed sources from the request and verified metadata. Ask one focused clarification when these remain ambiguous.</task_contract>\n<evidence_workflow>Use the registered Data MCP tools to find and read materials. Associate each figure with its precise source version, period and unit. Submit cited operands to the calculation tool. Audit coverage of every requested item before returning.</evidence_workflow>\n<delivery>Provide figures, calculations, attributed management explanations, citations and explicit gaps. An older eligible report may be returned after a failed freshness check only with its publication date and an unconfirmed-latest label.</delivery>\n<limits>Do not supply missing facts from memory, treat null as zero, broaden scope, overwrite earlier evidence, or bypass host permissions and budget.</limits>`,
  },
};
// Wording above illustrates independent ownership, not a tested claim that
// a particular model prefers headings or XML. No actual model is configured.
export function initialState() {
  return {view:'query', scenario:'financial', lang:'zh', theme:'paper', tab:'result', gapPolicy:'local', gapResolved:false, clarified:false, build:0, correction:0, correctionVersion:'current', source:null, panel:'review', compare:'AC', specimen:{A:'complete',B:'complete',C:'complete'}, prompt:null, materialFilter:'all', review:{}};
}
export function transition(state, action) {
  const next={...state};
  switch(action.type) {
    case 'view': if(!views[action.value]) throw Error('Unknown view'); next.view=action.value;next.source=null;next.prompt=null;next.panel='review';break;
    case 'scenario': if(!scenarios[action.value]) throw Error('Unknown scenario');next.view='query';next.scenario=action.value;next.tab='result';next.source=null;next.panel='review';break;
    case 'gapPolicy': if(!['local','expand'].includes(action.value)) throw Error('Unknown policy');next.gapPolicy=action.value;next.gapResolved=false;break;
    case 'supplement': if(state.gapPolicy!=='expand') throw Error('Supplement outside allowed scope');next.gapResolved=true;break;
    case 'clarify': next.clarified=true;break;
    case 'build': next.build=Math.min(3,state.build+1);break;
    case 'source': if(!sources[action.value]) throw Error('Unknown evidence');next.source=action.value;next.prompt=null;next.panel='source';break;
    case 'checkCorrection': if(state.source!=='S25'||state.correction!==0) throw Error('Read the original before confirming');next.correction=1;break;
    case 'correct': if(state.correction!==1) throw Error('Correction needs source verification');next.correction=2;next.correctionVersion='current';break;
    case 'prompt': if(!profiles[action.value]) throw Error('Unknown prompt profile');next.prompt=action.value;next.source=null;next.panel='prompt';break;
    case 'set': {
      const allowed={lang:['zh','en'],theme:['paper','night'],tab:['result','process','config'],panel:['review','source'],compare:['AC','BC'],materialFilter:['all','annual','earnings'],correctionVersion:['current','old']};
      if(!allowed[action.key]?.includes(action.value)) throw Error('Invalid state update');next[action.key]=action.value;break;
    }
    default: throw Error('Unknown action');
  }
  return next;
}
export function reviewKey(state) { return `${state.view}:${state.view==='query'?state.scenario:state.view==='compare'?state.compare:'main'}`; }
export function delivery(state) {
  const gap = state.scenario==='gap'&&!state.gapResolved;
  const clarify = state.scenario==='clarify'&&!state.clarified;
  const latest=state.scenario==='latest';
  return {status:clarify?'clarification':gap||latest?'partial':'complete',revenue:clarify?null:120,previous:gap||latest||clarify?null:100,growth:gap||latest||clarify?null:20,refs:clarify?[]:gap||latest?['S25']:state.scenario==='financial'?['S24','S25','M25']:['S24','S25'],gap:latest?'freshness':gap?'prior-period':null};
}
