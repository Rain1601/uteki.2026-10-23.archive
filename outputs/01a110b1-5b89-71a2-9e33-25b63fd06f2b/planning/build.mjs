import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = '/Users/rain/Documents/ChatGPT/uteki.beta';
const out = path.dirname(new URL(import.meta.url).pathname);
const commit = 'ce3f2af720a761a5e37f8f6772307db008289806';
const sources = {
  todo: 'TODO.md',
  map: 'docs/DATA_AGENT_EXTRACTION_TODO.zh-CN.md',
  scope: 'docs/research/2026-10-12-ds02-financial-coverage-contract.v1.zh-CN.md',
  plan: 'docs/research/2026-10-12-ds03-source-acquisition-validation-plan.zh-CN.md',
  a01: 'docs/research/2026-10-12-ds03-a01-delivery.zh-CN.md',
  t01: 'data/material_packages/tsmc-fy2025-v1/README.zh-CN.md',
  accept: 'data/material_packages/tsmc-fy2025-v1/acceptance.json',
  m3: 'experiments/agent_design/2026-10-12-m3-figure-query-v1/DELIVERY.zh-CN.md',
  r4: 'experiments/agent_design/2026-10-12-e6-r4-capacity-v1/DELIVERY.zh-CN.md',
  qp: 'experiments/agent_design/2026-10-12-revenue-stability-v1/DELIVERY-v4.zh-CN.md',
  review: 'docs/CODE_REVIEW_FIXES_2026-10-12-v2.zh-CN.md',
  history: 'docs/R22_HISTORY_RECOVERY_2026-10-12.zh-CN.md',
  source: 'docs/research/2026-10-12-data-sources-selection.zh-CN.md',
  q01: 'docs/research/2026-10-12-profit-cashflow-query01-contract.v1.zh-CN.md',
};
const tasks = [];
function add(id, priority, module, task, status, acceptance, deps, gap, source='todo') {
  tasks.push({ id, priority, module, task, status, arrangement: id==='PL-01'?'当前讨论':status==='已完成'?'封存':'暂停', acceptance, deps, gap, source, decision:'' });
}
add('PL-01','P0','业务决策','确定第一阶段的用户交付与停止边界','待讨论','用一个真实投资经理问题，写明交付什么、排除什么、如何验收；确认后才排开发顺序',[],'建议先收敛可信财务查数；是排序建议，不改 DS-02 已冻结范围');
add('DS-01','P3','已有基线','数据源选型调研','已完成','保留官方资料、覆盖与稳定性边界；调研不等同供应商实测',[],'已有调研；未采购、未测试专业源','source');
add('DS-02','P3','已有基线','首批财务范围冻结','已完成','保留 US GAAP 非金融、三家公司、五年二十季及财务披露范围 v1',[],'契约完成；数据覆盖未完成；TSMC 为独立 IFRS/20-F 范围','scope');
add('DS-03-A01','P3','已有基线','模型自主发现并归档官网 HTML','有限通过','显式官方根起点；两家公司各一件，模型发现、下载、公司/期间/hash/证据正确',[],'TSMC、Microsoft 各一次实跑通过；修后全链未新跑，非长期稳定','a01');
add('03-M3','P3','已有基线','图片证据接入自主取材与交付','有限通过','冻结双公司材料与原题，完整阅读、精确引用、独立内容核验及严格加载',[],'新批次最终 3/3；无纠错 1/3；新图与任意扫描件未验','m3');
add('E6-QP1','P3','已有基线','审核请求身份与范围契约','有限通过','原标准不变，完整公司/期间/原文身份，同题独立三次审核',[],'首审及终稿 3/3；无纠错 2/3；跨问题未验','qp');
add('E6-R4','P3','已有基线','输出容量不足的有界恢复','有限通过','原完整输入、共享预算、一次显式升档；压力与正常控制分开',[],'压力 3/3、正常 1/1；历史原例、自然 8192→16384 未验','r4');
add('R25-R29','P3','已有基线','锁文件、配置、图片校验、指纹与费用隔离修复','已完成','保留五项各自根因、原例及离线回归；不等同业务全链验收',[],'代码与离线回归已交付，细项沿用 R25–R29 原记录','review');
add('DS-03-T01-F','P3','已有基线','冻结目录中的台积电原件取齐','有限通过','冻结清单 31 件均取得，三次请求与 hash 一致，公开包可迁移',[],'31/31、93 条成功记录；不代表实时目录全集','t01');
add('DS-03-T01-C','P1','材料获取','核对台积电实时官方目录是否齐全','未通过','保存实际目录及应收清单，逐项对账；不能用冻结目录替代实时发现',[],'实时目录受 Cloudflare 挑战阻断；T01 总验收未通过','accept');
add('DS-03-T01-D','P1','材料获取','查明台积电 IR 材料首次公开时刻','未通过','有可核验首次公开依据；区分下载、修改、打印和发布日期',[],'publication_date_acceptance=incomplete；不得参与截止日可得性推断','accept');
add('DS-03-T02','P1','材料解析','验收台积电年度包的文本解析','未开始','逐项核对主表/附注、表头/单位/限定条件与原文定位；图片页显式留缺口',['DS-03-T01-C','DS-03-T01-D'],'不含新增 OCR；不能因文件取齐标记解析通过','todo');
add('DS-03-P0-INV','P1','材料获取','冻结三家公司首轮完整材料清单','部分完成','MSFT/Alphabet/Costco 的 FY2025、Q3、FY2024 及引用/补充披露逐项应收可查',['DS-02'],'已取得 19 个 filing 的目录/索引/主文首轮；完整附件与版本包未齐','plan');
add('DS-03-P0-GET','P1','材料获取','补齐首轮缺件并核验重复获取','部分完成','按冻结清单取齐原件、附件、补充披露与版本；三轮远程核对留原始失败',['DS-03-P0-INV'],'微软部分小包通过；全公司完整包尚未通过','plan');
add('DS-03-DEDUP','P1','材料获取','区分重复文件、重复披露和真实版本','部分完成','同内容不重复计数；修订保留版本；重复事实保留各出处与列报时间',['DS-03-P0-INV'],'已有 hash/版本与重列小样；跨完整材料包验收不足','map');
add('DS-03-DATE','P1','材料获取','保证历史查询只用当时可得的材料','部分完成','首次公开时刻、截止日与财务期间分开；未知可得时刻显式拒绝或留缺口',['DS-03-P0-INV'],'已有 scope/cutoff 机制；IR 未知日期缺口保留','a01');
add('DS-03-API','P2','数据来源','验证专业结构化接口是否适合作加速层','未开始','以 SEC/IR 原件对照覆盖、口径、出处、版本、权限与费用；先有限样本',['DS-02'],'FMP Free 契约暂置；未注册/调用/采购；不能替代全部附注','plan');
add('DS-03-P1','P2','材料获取','扩展五个财年与二十个财季','未开始','逐公司逐期间应收/实收/缺件清楚，版本与可得时刻可复核',['DS-03-P0-GET','DS-03-DATE'],'不以一份年报内比较列代替完整历史材料','scope');
add('DS-03-S10','P2','稳定运行','验收连续十交易日获取与恢复','未开始','按既有方案每日两次观察，记录新披露、延迟、故障与恢复；24小时目标另验',['DS-03-P0-GET'],'三次下载一致不等同连续稳定','plan');
add('03-PARSE','P1','材料解析','核验首轮全文、表格与目录无漏无重复','部分完成','系统独立构建；对原文节点、表格、目录、单位及重复定位逐项核验',['DS-03-P0-GET'],'双公司 FY2025 10-K 有受限基线；首轮全部类型未验','map');
add('04-SCHEMA','P1','索引与说明','给每种数据对象提供可消费说明','部分完成','公司/期间/类型目录、表 schema、字段/单位与读取方法齐全且互相一致',['03-PARSE'],'已有目录/指标/分页说明；新增数据类型仍需补齐','map');
add('04-ANCHOR','P1','索引与说明','从块、表格、图片定位并高亮原文','部分完成','每个索引回指冻结原字节与具体片段；表头、单位、图中文字可核验',['03-PARSE'],'HTML 与指定图片通过；新格式及全包定位未验','map');
add('DS-04-F01','P1','结构化财务','覆盖利润表全部披露行','部分完成','保留原列报、期间、单位、币种、来源与层级，逐行对账',['03-PARSE','04-SCHEMA'],'现有少数指标映射不能代表整表覆盖','scope');
add('DS-04-F02','P1','结构化财务','覆盖资产负债表全部披露行','部分完成','存量时点、单位、币种、原行及原文定位正确，逐行对账',['03-PARSE','04-SCHEMA'],'完整覆盖未独立验收','scope');
add('DS-04-F03','P1','结构化财务','覆盖现金流量表全部披露行','部分完成','期间与累计口径正确；现金/非现金、补充披露分开，逐行对账',['03-PARSE','04-SCHEMA'],'微软现金流小包审阅完成；完整接口与多公司未完成','scope');
add('DS-04-F04','P1','结构化财务','提取综合收益与权益变动表','未验收','原行、期初/变动/期末、归属及计量口径均可追溯',['03-PARSE','04-SCHEMA'],'冻结范围已包含；无完整覆盖验收','scope');
add('DS-04-F05','P1','结构化财务','提取股数、EPS、股权激励和股东回报','未验收','区分基本/稀释、时点/加权平均、拆股及实际回购/授权额度',['03-PARSE','04-SCHEMA'],'不能把同名字段当成同口径','scope');
add('DS-04-F06','P1','结构化财务','提取分部、产品与地区财务披露','未验收','忠于报告维度，保留分部对账与口径；不补造未披露交叉矩阵',['03-PARSE','04-SCHEMA'],'历史收入图不是完整财务事实库验收','scope');
add('DS-04-F07-INV','P1','结构化财务','建立全部财务附注定量事实清单','未开始','独立精读列出表格与正文数量/区间/条件；每条有原文位置与覆盖状态',['03-PARSE'],'先形成覆盖分母；不能只挑关键附注','scope');
add('DS-04-F07','P1','结构化财务','提取全部财务附注定量事实','未验收','按独立清单逐项覆盖，保留币种/单位/期间/条件；未支持项显式列出',['DS-04-F07-INV','04-SCHEMA'],'已知旧基线另有 2,970 条未映射；原文保留不等同可结构化查询','scope');
add('DS-04-F08','P1','结构化财务','提取财务补充披露、Non-GAAP 与指引','未验收','原文对账、调整项和公司定义齐全；实际/预测严格区分',['DS-03-P0-GET','04-SCHEMA'],'仅限冻结财务范围，非财务运营 KPI 后置','scope');
add('DS-04-F09','P1','结构化财务','保留财务定义、会计政策与重要限定','未验收','数据可回查相关定义、重列说明、审计与解释，不能截断必要条件',['03-PARSE','04-SCHEMA'],'结构化数字和文本说明必须可关联','scope');
add('DS-04-F10','P1','财务查询','实现可审计的季度、TTM、增速与比率计算','未验收','显式公式/定义、输入出处及期间一致；不支持的口径拒绝推算',['DS-04-F01','DS-04-F02','DS-04-F03'],'已有有限期间机制；全指标派生未验；FCF/净债务需定义','scope');
add('DS-04-Q01','P1','财务查询','落地微软利润与现金流问题的查询交付','方案完成','系统从显式范围自主取材，返回足够且聚焦的原始证据与缺口',['04-SCHEMA','04-ANCHOR'],'原包/文本审阅和协议候选保留；新接口未开发或模型实跑','q01');
add('10-DISCOVER','P1','自主查询','从问题找到公司、期间和合适数据源','部分完成','读取小型目录/schema 后选择源；缺失/歧义/越界拒绝，不默选公司',['04-SCHEMA'],'指定多公司与多期间案例通过；完整材料库泛化未验','map');
add('10-REVIEW','P1','自主查询','检查取材结果并有界补查','部分完成','判断问题是否被材料覆盖；补充/收窄查询，每轮依据和状态留存',['10-DISCOVER','04-ANCHOR'],'已有真实循环与双审；更多问题首次交付能力未验','map');
add('05-HANDOFF','P1','数据交付','交付最少充分证据包与明确缺口','部分完成','必要信息全、无大量无关材料、真实且精确出处；失败不能冒充就绪',['10-REVIEW'],'特定问题可严格加载；真实 Analysis 消费未验','map');
add('11-GOLD','P1','独立验收','建立多公司多问题独立评测集','部分完成','Codex 对原件冻结必需/可选/冗余与等价出处，答案不进入运行 Agent',['03-PARSE'],'已有有限题库；完整财务、更多新题覆盖不足','map');
add('11-GENERAL','P1','独立验收','验收新公司、新年份和混合材料查询','部分完成','单公司/多公司、相同/不同问题各有独立保留题；覆盖与聚焦分别判定',['11-GOLD','05-HANDOFF'],'指定 E2–E5 收入等案例通过；不等同任意公司通过','map');
add('11-STABLE','P1','独立验收','验收完整交付稳定性与纠错成本','部分完成','冻结问题与配置重复运行；首审/最终/无纠错分别统计，失败不替换',['11-GENERAL'],'若干小样成功；全链长期稳定仍无保证','todo');
add('DS-05','P1','整体关口','验收完整财务可查询、可追溯','未开始','按 DS-02 清单逐项验原件、事实、历史版本、计算、证据与自主交付',['DS-03-P1','DS-04-F01','DS-04-F02','DS-04-F03','DS-04-F04','DS-04-F05','DS-04-F06','DS-04-F07','DS-04-F08','DS-04-F09','DS-04-F10','11-STABLE'],'总验收关口；前置项各自通过才可关闭，不计为额外功能','scope');
add('E6-R5b','P2','保留缺陷','修复记录 ID 引用与分组动作契约','未开始','原误用与独立边界复现；合法共用保留，越来源/要求严格拒绝',[],'R5a 来源选择修复不代表记录分组已解决','todo');
add('R2','P2','保留缺陷','核查弃用探索来源阻断交付','待复核','对当前代码复现最早偏差，再按责任层修复并验原例',[],'历史列未修；当前机制已变化，不能预判仍存在','todo');
add('R3','P2','保留缺陷','允许无期末但合法的来源接受正确审核','未解决','财报期间与发布日期分开；8-K/官方更新可合法审核，未知范围不猜测',[],'8-K/官方更新扩展前解决','todo');
add('R4','P2','保留缺陷','补齐临时错误的有限重试分类','未解决','只恢复已定义临时故障；未知费用保留且同预算计入',[],'历史缺陷保留；新获取入口有局部机制，不自动关闭旧路径','todo');
add('R5','P2','保留缺陷','使精编复核使用显式输出额度','未解决','配置真实传到复核请求，边界与失败留证，不靠默认值',[],'filing_brief 历史缺陷','todo');
add('R6','P2','保留缺陷','业务图发布前复核原件 hash','未解决','原件被改/错绑则拒绝发布，合法原件与历史版本可验证',[],'business_map 历史缺陷','todo');
add('R7','P2','保留缺陷','修复历史阅读分组回放兼容','未解决','按绑定版本重放 reading_groups；旧原件/状态不改写',[],'需要相应原例/版本证据','todo');
add('R22-H','P3','历史验证','恢复历史运行包并重审可见性','缺材料','找回 12 次原运行与绑定 dataset，零 API 重审；不能用新运行替代',[],'E6-V3 九次、E6-R3 三次原包缺失；不阻断无关工作','history');
add('12-TRACE','P2','过程与结果','统一每步快照、模型配置与费用展示','部分完成','Request/Trace ID 串起输入、索引、查询、补查、审核和结果；unknown 保留',[],'已有后台和快照/账本；全链统一覆盖未验','map');
add('E6-UI2','P2','过程与结果','以问题、缺漏、冗余和费用展示验收','未开始','优先显示用户可读结论，过程记录可展开，失败与同次运行绑定',['11-GOLD','12-TRACE'],'已有独立评估页面；统一中文简明视图后置','todo');
add('12-TRANSFER','P2','工程交接','让验收运行包跨机器可核验','部分完成','按显式清单迁移配置说明、原件、运行及 hash；密钥/私密对话不自动提交',[],'原件包可迁移；本机 A01/M3 私密原运行包缺失','history');
add('16-CONSUME','P2','分析 Agent','真实消费数据包并反馈缺数','未验收','Analysis 独立读取 Data 交付，缺信息可要求补查，再产出带证据结论',['05-HANDOFF'],'角色边界已明确；真实分析消费未完成','map');
add('08-BRIEF','P2','分析产物','生成完整财报精编','部分完成','保留关键事实/必要限定/精确引用，以原件独立核验；不只做小节',['16-CONSUME','R5'],'已有历史小节候选；整份精编未验','map');
add('09-MAP','P2','分析产物','生成清晰完整的业务关系图','部分完成','Agent 自主取材；业务层级/产品/支撑关系分开，节点与边有出处',['16-CONSUME','R6'],'有已认可视觉参考和历史候选；通用独立生成验收未闭合','map');
add('09-REVENUE','P2','分析产物','单独展示收入结构与比例','部分完成','与业务关系图分开；金额、分母、分类、期间和出处可对账',['DS-04-F06','16-CONSUME'],'历史收入图存在；不能凭图证明完整财务提取','map');
add('09-SKILL','P2','技能复用','沉淀并验收通用业务制图 Skill','部分完成','冻结规则/输入/配置，用系统 Agent 在保留公司复跑；不写公司答案',['09-MAP','09-REVENUE'],'已有 Skill；好看参考不等同生产泛化通过','map');
add('13-LINKS','P2','官方补证','给产品和服务附可核验官网链接','部分完成','官方归属与页面内容有依据；可选 Skill 执行，链接不硬编码流程',['09-MAP'],'历史可选补充保留；系统化发现/更新未验','map');
add('E7','P2','公司关系','定义并提取公司竞争等关系','待定义','明确说话者、业务范围、日期、精确片段；披露/推断分开，不自动反向',['05-HANDOFF'],'company relations 类型与验收标准未冻结','todo');
add('14-WATCH','P3','观察与监控','从业务结论形成 To Watch 清单','待定义','每个观察项有目的、官方来源、触发条件和证据关联',['16-CONSUME','13-LINKS'],'不等同已经启动自动监控','map');
add('14-RUN','P3','观察与监控','持续跟踪官方更新与变化','未开始','来源先核验，再按频率采集、去重、识别变化并保存历史',['14-WATCH','DS-03-S10'],'官方 blog/新闻优先；非官方高质量数据另定范围','map');
add('15-INDUSTRY','P3','行业扩展','增加有明确适用边界的行业规则','待定义','行业规则显式选择，有证据要求/版本/不支持情况；不按公司名触发',[],'金融行业/特殊财历等不得静默套用当前范围','map');
add('06','P3','技术选项','对照 PageIndex 的适用性与成本','暂停','同冻结材料与问题比较覆盖、出处、聚焦和费用，再决定复用范围',[],'已有调研；同输入实测未完成，用户原先要求暂缓','map');
add('03-FORMATS','P3','材料扩展','支持更多 PDF 扫描页与图片类型','未验收','新样本逐图/页对照原件，OCR 坐标与语义独立校验、缺口可见',[],'已有两图基线；当前 T02 不自动扩大到 OCR','map');
add('02-CALLS','P3','材料扩展','获取并处理官方电话会文字稿','待定义','确认官方来源、时间、发言者与段落出处；Prepared/Q&A 边界明确',[],'历史需求保留；完整音频/Q&A 不在 DS-02 当前范围','scope');
add('02-BLOG','P3','材料扩展','获取官方产品、新闻与博客材料','待定义','公司官方归属先校验，按日期/类型入库、去重且可定位片段',[],'当前 A01 英文 HTML 年报不代表任意网页均支持','a01');
add('DS-X01','P3','数据扩展','加入行情、估值与指数数据','待定义','先定数据频率、权利、时点与复权/币种口径，再验来源',[],'明确放下一阶段，未选定生产数据源','scope');
add('DS-X02','P3','数据扩展','加入非财务运营与产业一手数据','待定义','每个指标定义、来源、更新时间与可信度可核验',[],'销量/订单/产品价格等属后续业务讨论，非既有覆盖承诺','scope');
add('DS-X03','P3','数据扩展','加入一致预期和其他报告制度','待定义','为不同制度/行业建立显式范围和验收，保留未支持项',[],'TSMC 独立分支不追认为 US GAAP 完成','scope');
add('11-MODELS','P3','模型比较','小步比较模型质量、稳定性与费用','部分完成','同输入/配置/标准独立运行；质量先行，计入失败/unknown，避免无变化重跑',['11-GOLD'],'已有对照；Qwen/DeepSeek 等后续先核对适配，不用 MiniMax','todo');
add('16-RISK','P3','后续 Agent','定义风险分析 Agent 的最小任务','待定义','明确用户问题、输入、输出与验收，再决定技术方案',[],'来自用户历史需求；当前未形成已验收实现','map');
add('16-PORTFOLIO','P3','后续 Agent','定义组合 Agent 与账户数据边界','待定义','明确分析/模拟/交易边界及数据权限；未授权不操作账户',[],'来自用户历史需求；雪盈账户接口调研不等于接入完成','source');

const ids = new Set(tasks.map(t=>t.id));
if(ids.size!==tasks.length) throw new Error('duplicate IDs');
for(const t of tasks) for(const d of t.deps) if(!ids.has(d)) throw new Error(`unknown dependency ${t.id}: ${d}`);
function walk(id, stack=[]) { if(stack.includes(id)) throw new Error('dependency cycle'); for(const d of tasks.find(t=>t.id===id).deps) walk(d,[...stack,id]); }
for(const t of tasks) walk(t.id);
for(const p of Object.values(sources)) await fs.access(path.join(root,p));
const rank = {P0:0,P1:1,P2:2,P3:3};
tasks.sort((a,b)=>rank[a.priority]-rank[b.priority]);
await fs.writeFile(path.join(out,'tasks.snapshot.json'),JSON.stringify({asOf:'2026-10-13',commit,mode:'development_paused',sources,tasks},null,2));

const wb = Workbook.create();
const sh = wb.worksheets.add('需求台账');
const close = wb.worksheets.add('阶段收尾');
const headers=['ID','建议优先级','业务模块','要完成的事情','验收状态','当前安排','完成条件','依赖 ID','现有证据与缺口','来源（固定提交）','讨论决定（可填）'];
const first=9,last=8+tasks.length;
sh.getRange('A2').values=[['Uteki 需求与验收台账']];
sh.getRange('A3').values=[['截至 2026-10-13 · 开发暂停，只做收尾与业务排序；不是自动执行队列。']];
sh.getRange('A4').values=[['P0 先讨论｜P1 核心数据闭环｜P2 能力完善｜P3 后置或封存。优先级为建议，可筛选修改。']];
sh.getRange('A5').values=[['状态按已提交证据整理，未统一重跑。新增子 ID 用于拆项；旧 ID 和失败历史保留。']];
sh.getRange('A6').values=[['条目数']];
sh.getRange('B6').formulas=[[`=COUNTA(A${first}:A${last})`]];
sh.getRange('D6').values=[['暂停项']];
sh.getRange('E6').formulas=[[`=COUNTIF(F${first}:F${last},"暂停")`]];
sh.getRange('G6').values=[['本表是讨论快照；确认的变更再写回 TODO.md。条目数不代表进度百分比。']];
const rows=tasks.map(t=>[t.id,t.priority,t.module,t.task,t.status,t.arrangement,t.acceptance,t.deps.join('、')||'—',t.gap,`https://github.com/Rain1601/uteki.beta/blob/${commit}/${sources[t.source]}`,t.decision]);
sh.getRange(`A8:K${last}`).values=[headers,...rows];
const tbl=sh.tables.add(`A8:K${last}`,true,'Requirements');
tbl.showFilterButton=true;
tbl.showBandedRows=false;
sh.freezePanes.freezeRows(8);
sh.freezePanes.freezeColumns(2);
sh.showGridLines=false;
sh.tabColor='#283F55';
sh.getRange(`A1:K${last}`).format.font={name:'Arial',size:11,color:'#243442'};
sh.getRange(`A8:K${last}`).format.wrapText=true;
sh.getRange(`A9:K${last}`).format.verticalAlignment='top';
const widths=[165,100,115,280,100,90,365,170,360,420,245];
widths.forEach((w,i)=>sh.getRangeByIndexes(0,i,last,1).format.columnWidthPx=w);
sh.getRange('A2').format.font={size:17,bold:true};
sh.getRange('A2:K2').format.rowHeight=30;
sh.getRange('A3:K5').format.rowHeight=22;
sh.getRange('A6:K6').format.rowHeight=28;
sh.getRange(`A9:K${last}`).format.rowHeight=64;
sh.getRange(`A9:K${last}`).format.fill='#FFFFFF';
tasks.forEach((t,i)=> { if(t.deps.length>4) sh.getRange(`A${i+9}:K${i+9}`).format.rowHeight=180; });
sh.getRange('A8:K8').format={fill:'#283F55',font:{bold:true,color:'#FFFFFF'},rowHeight:32,horizontalAlignment:'center',verticalAlignment:'center'};
sh.getRange(`J9:J${last}`).format.font={size:10,color:'#466A87'};
sh.getRange(`B9:B${last}`).format.fill='#FFF2D8';
sh.getRange(`K9:K${last}`).format.fill='#FFF2D8';
sh.getRange(`B9:B${last}`).dataValidation={rule:{type:'list',values:['P0','P1','P2','P3']}};
sh.getRange(`E9:E${last}`).dataValidation={rule:{type:'list',values:['待讨论','已完成','有限通过','部分完成','未通过','未开始','未验收','方案完成','待复核','未解决','缺材料','待定义','暂停']}};
sh.getRange(`F9:F${last}`).dataValidation={rule:{type:'list',values:['当前讨论','暂停','封存','待排期']}};
for(const [term,color] of [['未通过','#FBE3E1'],['未解决','#FBE3E1'],['有限通过','#FFF2D8'],['缺材料','#FFF2D8']]) {
  sh.getRange(`E9:E${last}`).conditionalFormats.add('containsText',{text:term,format:{fill:color}});
}
// Plain URLs preserve portable provenance; HYPERLINK calculation is unsupported by this renderer.
tasks.forEach((t,i)=> { sh.getRange(`J${i+9}`).values=[[`https://github.com/Rain1601/uteki.beta/blob/${commit.slice(0,8)}/${sources[t.source]}`]]; });

close.showGridLines=false;
close.getRange('A2').values=[['阶段收尾：可以封存什么，不能宣称什么']];
close.getRange('A3').values=[['结论：已有受限闭环；完整材料准备、完整财务查询与长期稳定尚未通过。']];
close.getRange('A4').values=[['本轮仅核对已提交材料与本机证据；未调用模型、未获取新材料、未开展功能开发。']];
close.getRange('A5').values=[['当前只讨论 PL-01：第一阶段交给投资经理的具体结果，以及做到哪里就停止。']];
const closure=[
 ['官网获取 / A01','有限通过','两家公司各一件 HTML，发现→下载→校验→归档；历史报告 228 项受影响回归。','首次发布日期、任意公司身份发现、长期稳定；修后全链未新跑。','已读提交报告；本机缺该私密原运行包，未重新实跑核验。','a01'],
 ['台积电原件 / T01','总体未通过','冻结目录 31/31 件，历史三次 HTTP/hash 一致；本机 SHA256SUMS 全部匹配。','实时目录完整性、IR 首次公开时刻。T02 解析未开始。','公开原件包在本机；acceptance.json 明确 not_passed。','accept'],
 ['图片查询 / 03-M3','限定问题通过','新批次最终 3/3；首个取材 attempt 合格 2/3，无纠错 1/3。','新图、扫描件、任意格式、全文财务语义及长期稳定。','已读提交报告；本机无这批私密原运行，不冒称本轮重新验图。','m3'],
 ['审核契约 / E6-QP1','限定问题通过','三次首审及最终 3/3，无纠错 2/3；公司/期间身份显式。','记录 ID 误写/分组契约及跨问题稳定性。','历史独立核验记录，未重跑。','qp'],
 ['容量恢复 / E6-R4','新批次有限通过','压力 256→8192 三次通过，正常控制一次通过。','原 V3 缺包；自然 8192→16384 触发与长期稳定未验。','历史交付报告，未用新样例替代旧失败。','r4'],
 ['财务范围 / DS-02','契约完成','US GAAP 三家公司；主表、全部财务附注与约定财务补充披露。','完整事实、五年/二十季、Query 与最终 DS-05 验收。','冻结范围保留；没有将计划写成实现。','scope'],
 ['迁移与历史','部分完成','代码及公开台积电原件随 Git 可迁移；可查源提交 ce3f2af7。','R22-H 的 12 次历史运行仍缺包；私密包不会自动上传。','本轮检查文件存在性与公开包完整性。','history'],
];
const cHead=['范围','收尾结论','已完成证据','仍未完成 / 不外推','本轮核验方式','出处'];
close.getRange('A7:F14').values=[cHead,...closure.map(r=>r.slice(0,5).concat([sources[r[5]]]))];
const ct=close.tables.add('A7:F14',true,'Closeout');
ct.showBandedRows=false;
closure.forEach((r,i)=>close.getRange(`F${i+8}`).values=[[`https://github.com/Rain1601/uteki.beta/blob/${commit.slice(0,8)}/${sources[r[5]]}`]]);
close.getRange('A17').values=[['接下来只讨论一件事']];
close.getRange('A18').values=[['PL-01']];
close.getRange('B18').values=[['首个交付']];
close.getRange('C18').values=[['建议：让投资经理输入一个财务问题，拿到可信、足够且聚焦的数据与精确出处。']];
close.getRange('D18').values=[['先确定典型问题、必要数据边界和验收；业务图/精编/更多来源保持队列，不同时展开。']];
close.getRange('E18').values=[['这是下一次讨论建议；不撤销 DS-02，不恢复开发。']];
close.getRange('A20').values=[['顺序建议']];
close.getRange('C20').values=[['业务边界 → 原件齐全 → 解析/索引可靠 → 财务事实可查 → 独立验收 → 分析产物与扩展。']];
close.getRange('A22').values=[['使用方法']];
close.getRange('C22').values=[['先在“需求台账”筛选建议优先级或模块；黄色单元格可改优先级、填写讨论决定。']];
close.getRange('D22').values=[['需要开发前再拆执行任务。当前条目是业务验收单元；不虚构工期、负责人或完成百分比。']];
close.getRange('A1:F22').format.font={name:'Arial',size:11,color:'#243442'};
[190,125,375,365,285,420].forEach((w,i)=>close.getRangeByIndexes(0,i,22,1).format.columnWidthPx=w);
close.getRange('A2').format.font={size:17,bold:true};
close.getRange('A2:F2').format.rowHeight=32;
close.getRange('A3:F5').format.rowHeight=24;
close.getRange('A7:F14').format.wrapText=true;
close.getRange('A8:F14').format.verticalAlignment='top';
close.getRange('A8:F14').format.rowHeight=85;
close.getRange('A8:F14').format.fill='#FFFFFF';
close.getRange('A7:F7').format={fill:'#283F55',font:{bold:true,color:'#FFFFFF'},rowHeight:32,horizontalAlignment:'center'};
close.getRange('A17:F22').format.wrapText=true;
close.getRange('A17:F22').format.verticalAlignment='top';
close.getRange('A18:F18').format.rowHeight=74;
close.getRange('A20:F20').format.rowHeight=60;
close.getRange('A22:F22').format.rowHeight=74;
close.getRange('A17').format.font={bold:true};
close.getRange('B8:B14').conditionalFormats.add('containsText',{text:'未通过',format:{fill:'#FBE3E1'}});
close.freezePanes.freezeRows(7);

wb.recalculate();
await fs.writeFile(path.join(out,'inspection.json'),(await wb.inspect({kind:'region',sheetId:'需求台账',range:'A6:K13',maxChars:5000,tableMaxRows:8,tableMaxCols:11})).ndjson);
await fs.writeFile(path.join(out,'formula-check.json'),(await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#N/A|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:100},maxChars:3000})).ndjson);
for(const [sheetName,range,name] of [['需求台账','A1:F16','register'],['需求台账','G8:K13','criteria'],['阶段收尾','A1:E14','closeout']]) {
  const img=await wb.render({sheetName,range,scale:1,format:'png'});
  await fs.writeFile(path.join(out,`${name}.png`),new Uint8Array(await img.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);
await file.save(path.join(out,'Uteki-需求与验收台账-2026-10-13.xlsx'));
const md=[
 '# 需求台账讨论快照 · 2026-10-13',
 '',
 '**开发暂停。当前只讨论 PL-01：首个用户交付与停止边界。** 本表按代码基线 `ce3f2af7` 的已提交报告及本机公开包整理，不代表本轮全部重新实跑。任务状态以最新证据为准，旧失败与范围不改写。',
 '',
 'Excel 是便于筛选的讨论副本。本 Markdown 保留可随 Git 迁移的完整清单；优先级均为建议，确认的变更再写回主 TODO，不凭此表自动启动开发。P0=先讨论，P1=核心数据闭环，P2=能力完善，P3=后置或已有基线。',
 '',
 '既有 ID 延用；后缀为本次拆出的业务验收单元。DS-05 是整体关口，不是新增功能；R25-R29 是完成记录索引，不作为待开发的合并大任务。未定义扩展需先讨论，不虚构工期。',
 '',
 '| ID | 建议 | 模块 / 具体需求 | 验收状态 / 安排 | 完成条件 | 依赖 | 现有证据与缺口 |',
 '|---|---|---|---|---|---|---|',
 ...tasks.map(t=>`| ${t.id} | ${t.priority} | ${t.module} / ${t.task} | ${t.status} / ${t.arrangement} | ${t.acceptance} | ${t.deps.join('、')||'—'} | ${t.gap}。[依据](https://github.com/Rain1601/uteki.beta/blob/${commit}/${sources[t.source]}) |`),
 '',
 '旧路线覆盖：01→DS-02，02→DS-03，03→03-PARSE/T02/M3，04→04-SCHEMA/ANCHOR，05→05-HANDOFF，06 保持暂停，07→DS-04-F01–F10，08/09 分别为精编与业务/收入图，10/11 为查询与评测，12 为运行可见性，13/14/15/16 为官网补证、监控、行业与分析。E1–E6 已完结轮次及 R1–R29 修复史保留主 TODO，不逐轮复制成新工作。',
 '',
 '范围说明：这份清单覆盖当前仓库主线、原 01–16 路线、保留缺陷和已表达的后续方向；不是对整个仓库或未表达产品需求的全面审计。历史 Risk/Portfolio 只记待定义，不宣称已实现。',
 ''
 ].join('\n');
await fs.writeFile(path.join(root,'docs/PROJECT_TASK_REGISTER_2026-10-13.zh-CN.md'),md);
console.log(JSON.stringify({taskCount:tasks.length,statusCounts:tasks.reduce((a,t)=>(a[t.status]=(a[t.status]||0)+1,a),{}),output:path.join(out,'Uteki-需求与验收台账-2026-10-13.xlsx')}));
