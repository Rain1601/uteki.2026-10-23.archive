# 当前动作：瘦身与技术方案队列 S1 已完成，待用户 review（2026-10-23）

本页其余部分的“核心设计 14.x”等章节号指冻结的 `docs/DATA_AGENT_DESIGN_HISTORY_2026-10-23.zh-CN.md`，不指重写后的核心设计。

## 前项：共享协议规则从文档专属分支上移到共同层（2026-10-21 开始，2026-10-23 收口提交）

**现象（离线复现，2026-10-21）：**同一 DataService/六工具下，HTML/iXBRL 路径与 PDF 文档路径靠 `context.request.documents` 分叉（6 文件 15 处）。前几批针对真实失败的通用修复只落在文档路径。复用 `DataToolTests` 真实 Catalog/HTML 构建复现：①`required_securities` 在 HTML 上下文被契约直接拒绝（`currently requires an explicit document scope`）；②`find_assets` 只传 company_id 返回 ok；③交付自由 `note` 被接受并原样冻结。文档路径对应测试（`test_required_security_lookup_cannot_be_replaced_or_bypassed`、`test_document_delivery_rejects_unquoted_note_and_metadata_source_claim`）通过。SDK 边界 `agent/binding.py` 仅在 document_mode 投影增量状态 / `rr_` 短句柄 / 交付自动派生状态。复现脚本为临时脚本，未入库。

**本步范围（用户 2026-10-21 授权“写进TODO然后开始改”）：**在共同层实现、两种后端共用：(a) 调用方指定证券——契约不再限定文档范围；`ToolExecution` 统一要求 find_assets 显式按该证券过滤，后续读取的资产须来自该次发现的 symbol 匹配；HTML 发现结果补 symbol_matches。(b) 交付禁止自由 note，原文说明走已有 source_claims 逐字校验（旧持久化交付可读，不改写）。(c) binding 对所有模式统一增量状态、短句柄、交付派生状态及错误时返回已提交状态；文档专属的仅保留后端能力投影（PDF 请求字段裁剪、data_root 隐藏、分页覆盖说明）。

**当前进展（2026-10-21）：**(a)(b)(c) 已实现。HTML 复现全部翻转（证券缺失/错误→SECURITY_FILTER_REQUIRED，未发现即读→ASSET_DISCOVERY_REQUIRED，自由 note→DELIVERY_NOTE_UNSUPPORTED，SDK 边界增量状态+短句柄+派生交付可用）；unit 352 项、gateway 集成 32 项通过。claude-agent-sdk 0.2.167 在 in-process MCP 按公布的 inputSchema 做 jsonschema 校验（已安装源码 `__init__.py:630`），故共享夹具 `sdk_fixture.Script` 改为输出模型协议（增量状态、`rr_` 句柄、交付不带 state），`test_financial_skill` 的合成交付改经 ToolBinding。agent 集成 125 项：49→12→剩余 8 项失败：5 项为改动前已有（`claude_mcp_output`/`live_capture` 的 stub binding 缺 `envelopes`，源于此前未提交的 `claude_runtime.make_options` 变化）；3 项为 Claude 缺账单恢复场景（G05，期望 recovery_required，实得 RequestIdentityConflict→MODEL_ERROR），代码路径在此前未提交的网关改动中，是否与本步相关尚未用基线证实。未调用模型。

**S0 归属核对（2026-10-22）：**主 `.venv` 未装 agent extra，在里面跑出的 165 项失败全是环境问题（缺 claude_agent_sdk、SDK 版本不等于冻结 profile），不作为判断依据。按 LOCAL_DEVELOPMENT 重建非 editable 的 SDK 环境（openai-agents 0.24.0 / claude-agent-sdk 0.2.167）后，125 项中恰好是原记录的 8 项失败，均不由本步引起。①5 项 stub：`claude_runtime`/`openai_runtime` 改为读 `binding.envelopes`（按后端投影工具集，HEAD 时读的是模块级 ENVELOPES），而 `test_live_capture`、`test_claude_mcp_output` 的 SimpleNamespace binding 没有这个属性，要更新测试夹具。②3 项 G05（含批量用例）：未跟踪的 `providers/gateway_claude.py` 中，`exchange` 只在 CatalogError 时写 `journal.failure_code`。缺 generation id（`gateway_http` 抛 ValueError `observed_generation_identity_required`）和缺账单（`openrouter_evidence` 抛 RequestIdentityConflict）都不是 CatalogError，不会写入 failure_code，于是 CLI 只拿到 assistant error，被归类为 MODEL_ERROR/failed。结果是未知费用的预留仍在，却没有进入恢复。失败发生在第一次请求、任何工具执行之前（operations 为空），本步改动的工具/交付/binding 分类代码不在这条路径上。修复应在 Claude 网关层，把响应已收但身份或账单不能核实的情况统一归为 RECOVERY_REQUIRED（与 OpenAI 路径语义对齐），不放宽测试断言。

**S0 修复与基线（2026-10-23，已完成）：**`gateway_claude.exchange` 在 `observe_bill` 抛出非 CatalogError 时改为抛 RECOVERY_REQUIRED（错误信息只带异常类型），由原有逻辑写入 failure_code。live_capture 和 mcp_output 的 stub 补上 `envelopes`，并复用 ToolBinding 的真实 schema 和描述投影；mcp_output 的合成参数改用增量状态协议。此外复跑全部测试组时又暴露 2 项过时测试，已同步：①时钟集成测试的 `domain_version` 2→3，因为当前写入方和单元测试都是 3；②no_progress 停止用例。按 14.21 的设计，新元数据算进展，所以新增 `repeat_discovery` 场景显式重复同一发现，断言第 2 轮停止且不再调用模型。在 SDK 环境（非 editable 安装）中：agent 集成 125、agent 单元 40、核心单元 352 项全部通过；data_platform 集成 101 项中，`test_content_processes` 按设计要求无 agent SDK 的环境，已在只装 data 依赖的非 editable 环境单独通过，其余通过（3 项需显式旧环境，跳过）；`run_offline_checks` 中 Python 与 JS 均通过。未调用模型。基线按主题分组提交，清理基线为 main `29b09245`，已推到 origin。

**Git 整理（2026-10-23，用户确认后执行）：**远端只保留 `main`。原先只在本地、且不在 main 历史中的 3 个提交改为推送到远端的 annotated 标签：`archive/2026-10-09-pre-upload`（bbb3b86e）、`archive/2026-10-13-before-api-publish`（828a92fc）、`archive/2026-09-29-codex-brand-snapshot`（bedca949）。已删除本地 ref：3 个备份分支、`refs/backup/*`、Codex snapshot，以及 7 个 Codex turn-diff tree 快照（这些中间状态从此不可恢复）。REPOSITORY_RETENTION 的恢复命令改用基线 SHA `a4595ba8`；归档清单 JSON 和其他历史文档里的旧分支名保持原样，作为当时的记录。没有重写历史。之后 S1–S4 每步在各自分支上完成，验证后再合入 main 并推送。

**验收：**原复现三项在 HTML 路径翻转为拒绝/强制；文档路径原测试不变通过；受影响的 HTML/SDK 接线测试按新契约核对（不放宽断言）。**未授权：**真实模型复验（HTML 路径同题需新预算与执行契约，另行确认）；本步不调用模型、不改费用账本。

## 后续有序队列：瘦身与技术方案（用户 2026-10-22 确认）

**用户决定：**先收口当前动作再清理；旧代码把新核心所需部分迁入后整体归档；技术方案限 Data Agent 主线（分析 Agent、前端只写边界和接口）。每步单独提交，完成后核对下一步；不删除 `output/` 冻结证据、不重写 Git 历史、不重置费用。

**盘点事实（2026-10-22）：**核心设计 854KB/4,694 行，§14 约占一半且混入运行记录（14.12 约 191KB、14.17 约 129KB、14.21 约 74KB）；docs 顶层约 40 份日期化/已取代文档，FRONTEND_DESIGN 302KB、LOCAL_DEVELOPMENT 93KB。跟踪文件 experiments 19,297（agent_design 15,433）、docs/design/data-agent-acceptance 2,535、data 1,547。旧代码 agents 20.5k、infrastructure 14.7k、domain 2.6k 行；data_platform 11.8k 行，只依赖 `infrastructure.run_budget` 与 `document_sources`（prepare_sources、validate_sec_filing、resolve_sec_contact），`uteki-data` 入口仍在旧 query_cli。tests/unit 顶层 234 个旧测试、约 57 个脚本及 review_workbench 14 个文件引用旧模块。未跟踪磁盘 output 16G、archive 5.3G 不在本队列删除范围。

- **S0 收口当前动作：**确认上文 8 项失败的归属，修复本步引起的，按主题分组提交现有改动，建备份分支作清理基线。
- **S1 核心设计瘦身并写明技术方案：**重写为当前态设计（目标 ≤1,500 行）：职责边界、分层与目录、契约、存储、Agent 运行与双 SDK 适配、验收与费用机制、阶段路线草案。§12–14 的运行记录、review 和已作废方案原文移入一份日期化历史记录（不改写失败/费用/hash），核心文档只留结论与证据入口。
  - **结果（2026-10-23，分支 `slim/s1-core-design`）：**v1.30 原文（4,694 行）用 git mv 整体移到 `docs/DATA_AGENT_DESIGN_HISTORY_2026-10-23.zh-CN.md`，放在同一目录，文中相对链接不受影响；开头加了冻结说明，正文未改。新核心设计 v2.0 约 480 行，共 13 节：目标与范围、职责、架构决定、数据模型、建设管线、查询与交付、运行时、代码组织（按实际文件）、验收方法、实现状态表（附历史章节证据入口）、技术选型、已知技术债、路线草案、待决事项。AGENTS/CLAUDE/README/接口文档的入口引用已更新，旧章节号统一指向历史记录。只改了文档，没有改代码或调用模型。待用户 review 后合入 main。
- **S2 文档归档：**顶层日期化/已取代文档按 2026-10-09 方法归档（清单 + SHA256 + 备份分支）；LOCAL_DEVELOPMENT、FRONTEND_DESIGN 精简为当前入口。
- **S3 解除新核心对旧代码依赖：**run_budget、SEC 取数与 `agent acquire` 迁入 data_platform，`uteki-data` 指向新入口；原测试随迁并通过，真实 acquire 经原入口重放一次（不调用模型）。
- **S4 旧代码与历史材料归档：**agents/infrastructure/domain/presentation/evaluation 及对应旧测试、脚本；review_workbench 依赖旧模块的部分（届时确认是否需改用新交付产物作审阅入口）；experiments、data-agent-acceptance 中不被保留测试或冻结材料引用的目录。逐项核对依赖闭包，fixture 来源不删。
- **S5 技术方案定稿：**按瘦身后的实际结构，在核心设计写定 Data Agent 到生产的阶段路线，以及每阶段的验收、所需授权与费用。

## 前项：计划/状态与记录预算通用简化、同题 OpenAI 真实复验 — 已完成，停止 review

**本批完成：**文档模型工具采用增量状态，宿主维护未变化需求、版本和当前工具名；新需求保留未核验，最终完成仍需Agent逐项明确判断。query_records省略预算时使用已有200000字节硬上限，显式小预算不放宽，超限报告所需字节，不截断依赖。旧完整状态接口保持严格校验。修复后安装包39+37项工程检查通过。

**真实结果：**原query/材料/模型/路由保持，OpenAI+Flash一会话，21→16次请求、19→12次业务调用、429.587→114.489秒，业务错误4→0。6个需求各新增一次，无重抄计划/版本；记录与计算一次成功，完整约33.7KB依赖保留。原件独立核对证券、币种、期间、合并总营收及增长率6.4255%均一致，四种导出hash一致，126个冻结文件无漂移。本题业务通过，非跨公司或缺证据场景泛化证明。

**仍需review：**Skill阶段2次命令形式被拒，随后直接cat成功，均计入16次请求；不能称所有原生工具零错误。请求间耗时也下降，但单次实跑不能归因全部延迟或证明稳定加速。下一小步如获授权，可只检查Skill工具给出的读取指引与实际允许命令是否一致；本轮不继续改或实跑。

**费用与停止：**新增全额未核账预留$0.9453198／$3，实际账单未取得；原根累计546/787，已报告收费$6.15119187、全额未核账预留$25.06190776、剩余$8.78690037／$40，未知/在途0。Claude未运行、旧goal不恢复，不扩额/充值或释放旧费用。证据：核心设计14.21.9、output/data-agent-loop-20261020/review.json，以及runs/LOOP-flash-openai/{review,call-trace}.json、deliveries/LOOP-flash-openai/。本批结束即停止。

**前项 2026-10-20 结果：**原 query、原 PDF/解析，新增调用方明确 AAPL/XNAS 约束。Flash/OpenAI 一条会话 21 次真实请求、19 次业务调用、429.587 秒。实际按 symbol 查找；含糊单位被拒后自主读取 U.S. dollars 原文，正确登记 FY2025/FY2024 合并营收、期间、单位并代码计算增长率 6.4255%。原 PDF、引用位置、五条声明上下文及四种导出一致；本题业务通过，不宣称跨公司泛化或缺证据场景的完成判断已通过。

**review 问题：**相比前次 14 次/150.337 秒，效率下降。4 次错误：计划版本、含糊单位、遗漏需求状态、输出预算；均同会话修正。18 次调用重复提交计划（17 次正文相同），以及记录依赖闭包触发默认输出预算问题，值得下一小步定位；不自动开始修复。一个短摘录未包含同块内的完整财政年度规则，交付原件保留，不改写历史结果。

**费用与停止：**新增全额未核账预留 $1.8522156／$3，实际账单未取得；根累计 530/787，已报告收费 $6.15119187、全额未核账预留 $24.11658796、剩余 $9.73222017／$40，未知/在途 0。Claude 未运行，未扩额、充值或恢复旧 goal。下一步建议仅 review 状态/计划维护与输出预算的通用简化，不新增模型或题目。

**证据：**核心设计 14.21.8；output/data-agent-revenue-guards-20261020/review.json；runs/GUARD-flash-openai/{review,call-trace}.json；deliveries/GUARD-flash-openai/{delivery.json,delivery.md,records.csv,calculations.csv}。真实复验前已安装源码验证 35+37 项通过；125 个冻结运行文件无漂移。最新指令要求本轮到此停止。

## 前项：营收链路真实运行，symbol 与币种证据两处未通过

**本轮真实结果（2026-10-20）：**源码重装成功（6.23 秒构建），当前安装包的提取记录→代码增长率→两种 CSV/JSON/Markdown 导出定向行为检查 1 项通过，11 个必要模块源码/安装内容一致，123 个运行文件 hash 无漂移。原问题与原件/解析不变；Flash/OpenAI 一条会话完成，14 次模型请求、14 次业务工具调用、150.337 秒，生成两条营收记录和代码增长率，导出四文件。FY2025/FY2024 为 416,161/391,035 百万，期间、合并口径、位置和增长率 0.064255117828327388 与原 PDF 独立核对一致；原始记录/计算 CSV 与 JSON/Markdown、全部导出 hash 一致。真实提交了 5 条 source_claims，逐字摘录存在，但部分语义支持不足。一次 VALUE_SOURCE_MISMATCH 和一次 OUTPUT_LIMIT 在原会话内修正；没有网络失败或追加会话。

**严格业务门槛未过：**实际 find_assets 只传 company_id，未传要求的 AAPL/XNAS；完整 Skill 在首次业务调用前已可见，材料选对不能替代 symbol 映射核验。单位记录写 USD，但只引用“$”及 millions，并把 USD 推断披露为 limitation；确认币种这一必需项仍标 supported，一条声明还把表头概括成“数百万美元”。模型确实搜索到涉及 U.S. dollar 的候选（含 texts-393），却未读取该块。验收侧在原 PDF 物理页 30 找到明确 U.S. dollars 表述，这只作失败定位，没有替模型补进原交付或改为通过。按本批先 OpenAI 业务通过再 Claude 的约定，Claude **0 次、未运行**。

**费用、证据与停止：**本批新增 14 次，未取得供应商实际账单，全额未核账预留 $0.9503964／$3，未释放预留。根累计 509/787、已报告收费 $6.15119187、全额未核账预留 $22.26437236、剩余 $11.58443577／$40，未知/在途 0。`output/data-agent-revenue-20261020/review.json`、`runs/REV-flash-openai/{review,call-trace}.json` 和 `deliveries/REV-flash-openai/` 保留真实结果与独立核对；安装中断与重试现场均保留。已停止新增调用，未扩额、充值、重解析或恢复旧 goal。

**下一小步建议（未启动）：**review 两个通用边界：调用方显式要求的证券条件在查找/绑定层强制遵守；必需币种核验区分明确原文与含糊符号/推断，缺证据须读取或留 gap。两处分别检查契约约束与来源支持，不添加公司特例或让宿主补答案；确定修复范围后再决定新的真实复验。

**恢复（2026-10-20）：**用户要求“retry一下链路呢”。继续本批原问题、两路顺序及原账本/限额，先重试源码安装与必要导出检查，再幂等完成冻结准备；不重新创建账本或丢弃先前中断记录。Flash/OpenAI 业务核对通过后才运行 Flash/Claude，最后 review 停止。旧平台 goal 仍不恢复。

**暂停现场（2026-10-20）：**用户要求“稍等 hold一下这个窗口”。本批尚未发起模型调用，未新增模型费用。冻结任务已保存于 `output/data-agent-revenue-20261020/`；首次准备在本地对象回读等待时温和中断，恢复准备因新导出源码尚未安装被一致性检查拒绝，原账本未重置。`application/exports.py` 已补通用 calculations.csv，现有数值交付测试已增加对应检查；源码重装在构建阶段等待，已按暂停指令中断，新增改动尚未完成安装或测试，不能记作通过。原 PDF 已取出并渲染供验收侧核对，未向模型传入答案。恢复时先检查构建/安装现状和原账本，再完成必要安装、定向检查、幂等准备，之后才可按原顺序真实验收；不自动恢复。

**2026-10-20 新批授权与目标：**用户在下一批方案后回复“OK”。复用原 Apple 2025 Form 10-K / 冻结解析，按 AAPL/XNAS 查找，提取 FY2025/FY2024 合并总营收、期间、币种和单位，保留原文摘录与精确出处；由现有代码登记、计算增长率并导出 JSON/CSV/Markdown。先 Flash/OpenAI 一条真实会话，经独立原 PDF 业务核对通过后再跑 Flash/Claude 同题一条，结束 review 停止。沿用原 $40/787 次根账本及全部费用/预留，宿主收紧本批 $3（含全额预留）、每路最多 24 次；不扩额、充值、重新解析或恢复旧 goal。缺证据明确留 gap；若共同工程能力阻塞，先定位，不耗费另一条路线。当前实现已有提取、Decimal 计算和三格式导出，优先复用；真实接口、独立验收及契约入口为 `output/data-agent-revenue-20261020/`。

## 前项：代码生成分页范围、原文声明绑定证据；同 query 复验 Flash 两路 — 已交付

**2026-10-20 本轮授权：**用户要求继续修复前批两处说明问题，保持泛化性；原 query、原材料及解析不变，只真实复验 Flash/OpenAI 与 Flash/Claude 各一次，然后停止 review。分页覆盖由已交付的 section_page 计算；文档 deliver 不接受自由 note，原文说明改为有逐字摘录和精确引用的 source_claims。代码只验证摘录存在，不把模型解释自动认证为语义正确。先做正常链与必要失败边界，再按原 $40/787 次根账本冻结本轮；保留费用/预留，不重新解析或恢复旧 goal。

**本轮结果：**当前源码普通安装后 68 项必要检查通过，原真实失败输入重放通过；121 个运行文件 hash 未漂移。两路各一次真实会话均加载完整 Skill，经 AAPL/XNAS 找到资产，取得五个子目录，沿同父路径＋游标读完并交付四页 107 块；正文、出处、导出与冻结解析一致，均 completed、0 工具错误、0 额外读取。最终 JSON/Markdown 的范围由代码生成，统一为零起始半开区间 [0,107)，末页 [98,107)，未重现旧 note 的越界说明或期间/合并口径已从原文核验的虚假声明。Flash/Claude 请求 8→8、耗时 39.8→120.6 秒；Flash/OpenAI 9→9、46.0→111.9 秒，没有效率改善证据。

**review 保留：**两路仍在 limitations 中混入成功执行/元数据说明；OpenAI 的公开过程文字仍写“0–32”等未明示右端不含的范围。最终文件的 code coverage 正确，不等于任意模型文字均受机械约束。两路 source_claims 均为空，符合本题只读取而不新增事实核验的范围；正向带摘录声明与拒绝边界由安装包测试及真实保存输入重放验证，尚无本题真实模型正向声明实例。逐字摘录存在不证明解释语义正确，原 PDF 全篇质量仍未认证。额外耗时出现在请求期间及请求间，尚无隔离诊断，不直接归咎模型。

**证据与停止：**核心设计 **14.21.6**；`output/data-agent-claims-20261020/review.json`、`runs/<lane>/call-trace.json`、`deliveries/<lane>/delivery.json/.md`；只读查看入口见 LOCAL_DEVELOPMENT。新增 17 次请求；本轮已核账收费未取得，全额未核账预留 $1.2782166（非实付）／本轮 $3 限制。根累计 495/787，已报告收费 $6.15119187、全额未核账预留 $21.31397596、剩余 $12.53483217／$40；未知/在途为 0。没有扩额、充值或释放预留。已停止新增调用，旧 goal 仍暂停。

**下一小步建议（未启动）：**先 review 交付与自由说明边界；若继续收口，可将读取/目录状态展示统一由已有结构化字段生成，limitations 只保留缺口与限制；不自动启动其他 query、模型对照或性能重构。

## 前项：元数据引用与完成状态修复，同 query 四路真实复验

**2026-10-20 用户授权：**修复元数据引用和完成状态，再按原 query、原材料/解析版本、原四路模型/SDK 各真实复验一次，比较轮次和效果。沿用原 $40/787 次根账本与旧费用/预留，不重新解析、不交叉 GPT/Claude SDK 与 Sonnet/OpenAI SDK。独立元数据引用、任务 gaps 与来源 limitations 分离，不自动把 partial 改为 completed。完成 review 后停止。

**本轮结果：**元数据快照可直接引用并与正文分型；交付新增 limitations，gaps 继续表示未完成工作，原校验未放宽。普通安装当前源码后 65 项必要工程检查通过。四路各一次真实会话均加载完整 Skill，经 AAPL/XNAS 找到资产，取得五个子目录，以同父路径＋游标读完并交付四页 107 块；正文/出处/导出精确一致，元数据引用均来自实际可见快照。全部 0 工具错误、0 额外封面读取，117 个运行文件 hash 未漂移。Flash/Claude 请求 12→8、77.5→39.8 秒；Flash/OpenAI 13→9、81.5→46.0 秒；Luna/OpenAI 12→9、87.9→68.0 秒；Sonnet/Claude 8→8、61.8→59.0 秒。四路当前声明 completed，原解析质量限制仍保留，没有把“原 PDF 无缺口”改判为已验证。

**review 保留问题：**Flash/Claude 的 note 声称期间与合并口径已从原文读取，但引用的登记元数据不能支撑该声明；Flash/OpenAI 的 note 把末页编号写成 98–107，而实际零起始闭区间为 98–106（规范 coverage 为 [98,107)）。两者属于说明准确性问题，未改写原交付；正文完整读取通过，不把所有业务说明也记作全通过。Luna/Sonnet 在本题限定说明核对通过；一次同题实跑不能证明稳定模型排名或其他问题质量。

**证据、费用与停止：**核心设计 **14.21.5**；`output/data-agent-metadata-20261020/review.json`、`runs/<lane>/call-trace.json`、`deliveries/<lane>/delivery.json/.md`。新增 34 次（原对照 45 次）；OpenRouter 已报告收费 $0.52659292，DeepSeek 全额未核账预留 $1.2660519（非实付），本批占用 $1.79264482／$3。根累计 478/787、已报告收费 $6.15119187、全额未核账预留 $20.03575936、剩余 $13.81304877／$40；未知/在途 0。未扩额、未充值、未释放预留。当前已停止新增调用，旧平台 goal 仍暂停。

**下一小步建议（未启动）：**review 本轮原始交付后，优先把块数/分页范围等可计算说明交给代码生成；针对期间/口径等“已核验”声明明确所需原文证据，保留无法机械核验的模型说明边界。此建议不自动扩展为新开发或模型回归。

## 前项：短引用与单次交付状态、四路父目录对照

**2026-10-19 结果：**按用户要求比较 Flash×OpenAI、Flash×Claude、Luna×OpenAI、Sonnet×Claude，没有 GPT/Claude SDK 或 Sonnet/OpenAI SDK 的交叉。先完成短证据句柄和文档 deliver 单次状态声明，再冻结相同问题/业务 prompt/Skill/工具 schema。四路均通过 AAPL/XNAS 定位材料、取得五个子目录，按同一父路径＋游标读完四页 107 块，并全部保存到真实交付；已核对实际模型输入、原解析、交付与导出 hash。无需重新解析。

**不能合并的结论：**Flash/Claude 为 completed（12 次）；Flash/OpenAI、Luna/OpenAI、Sonnet/Claude 为 partial（13/12/8 次）。后三路也完整交付正文，但分别受元数据无引用入口、原解析质量限制或二者影响。Luna 有 3 次参数错误，Sonnet 有 1 次未知资产句柄错误；两条 Flash 额外读取封面，严格只读父路径条件未通过。短句柄已消除本题最终交付的多字段拼接失败，不能宣称所有业务问题解决或单次对照证明模型稳定排名。

**证据与费用：**核心设计 **14.21.4**；`output/data-agent-subtree-compare-20261019/review.json`、`runs/<lane>/call-trace.json`、`deliveries/<lane>/delivery.json/.md`。62 项不同工程检查通过（包含首跑 fixture 失败后的定向修正，非一次全绿）；一次启动配置类型错误为 0 模型调用，原失败保留。新增 45 次真实请求，已报收费 $0.50580247，新增全额未核账预留 $2.3501232；根累计 444/787、已报收费 $5.62459895、全额未核账预留 $18.76970746、剩余 $15.60569359／$40。未知/在途 0；未扩额、未充值，旧费用与失败保留。

**下一小批建议（未启动）：**补齐资产、目录、解析状态的可追溯元数据引用与任务状态语义；区分“已读取并披露限制”和“原解析质量已完全验证”，避免模型为满足状态约束重复搜索或借用无关正文引用。仍保持正文证据、元数据与模型判断分开，不直接放宽验收。完成本轮 review 后再确定实施；当前停止新增模型调用，不自动恢复旧 goal 或其他 query。

前次 12 次 Flash/Claude 读取成功但交付引用拼错的原记录、费用及拒绝重放仍保留于核心设计 **14.21.3** 和 `output/data-agent-subtree-20261019`；本次没有把旧失败改为成功。

## 前项：目录 → 完整内容组 → 交付修复与真实复验

**2026-10-19 本轮结果：**按用户要求实现并重新测试：完整紧凑目录、PDF 实际能力对应的工具参数、明确 direct/subtree、完整 passage 组级引用与依赖展开交付；共享业务 Skill 升级为 1.1.0。原件、解析版本和业务标准不变。当前源码普通安装后 60 项必要工程检查通过；Q1 三条原失败路线真实复验 **2 条通过、1 条失败**，已停止新增调用。具体实现、证据及剩余机制问题见核心设计 **14.21.2**。

**真实效果与停止位置：**Flash/OpenAI 从原 13 次请求、错选章节，变为 10 次、原文与两组范围通过，仍有 2 次参数/状态错误和额外读取。Flash/Claude 从原 10 次、遗漏补充段，变为 5 次请求／4 次业务工具、0 错误，两组 5 块完整交付。Luna/Claude 新增 8 次后仍失败：正确找到 Business Risks，整节 41 块两次完整进入模型输入；三次交付拼错 run_id/operation_id，第四次引用正确但遗漏需求状态。该路线累计 24/24，随后两次本地准入拦截未发往供应商，SDK 外层显示 unknown；不是网络或正文未传入。Alphabet 独立章节完成真实存储回读与原 PDF 核对，未运行独立 Agent。Q2 原问题、本批其他未运行路线不变，不自动恢复矩阵。

**证据与费用：**`output/data-agent-sdk-matrix-20261019/business-review.json` 的 `navigation_fix` 保存本轮判断，`execution-metrics.json` 保存请求/耗时/费用，原失败保留。可看 `deliveries/MX-Q1-flash-claude-navigation-v1/delivery.md` 及同目录 JSON。本轮新增 23 次，本批累计 120 次、原账本累计 387/787；原账本已报告收费 $5.11879648、全额未核账预留 $15.44064046，未知/在途为 0。本轮已报告收费 $0.03180068、DeepSeek 未核账全额预留 $0.7415556；预留不是实际支出。未扩额、未充值。

**下一小批建议（未启动）：**优先简化会话内证据引用和重复需求状态：模型选择已展示证据的短句柄，由代码还原不可变完整引用；需求是否满足/缺口仍由模型明确判断一次，宿主维护唯一状态；错误指出具体字段，不自动修补任意引用或放宽可见性。整节读取提供已有内容组的入口，减少重新拼装范围。先做原失败参数的无付费重放，再决定真实复验；Luna/Claude 的 24 次原上限已用尽。数值提取、精确行位置、全篇解析质量另保留，不扩成新框架。平台 goal 仍暂停。

## 前项：Flash/Luna × OpenAI/Claude SDK 多题真实对照 — 已授权，现停止

**2026-10-19 用户转向：**扩展 query，比较 DeepSeek Flash、GPT-5.6 Luna 在两套官方 SDK 下的真实效果、请求轮次、耗时和费用；复杂问题用 Sonnet 对照，batch 仅讨论。冻结候选见核心设计 **14.21** 和 `output/data-agent-sdk-matrix-20261019/comparison-plan.json`：四题 × 四条基础路线共 16 会话；Sonnet 两 SDK 跑 Q4，Q2 基础路线业务失败时再跑两条，最多 20 会话/480 新请求。旧平台 goal 仍 paused；不恢复旧 File Search 工作。

**已准备：**六套独立 profile/prompt，共同业务正文与 Skill 主体；Claude OpenRouter 适配仅补冻结的 provider 路由，原生/实际上游请求均保留；真实运行入口拒绝含祖先项目指导的 Claude 工作目录，并按 profile 设置输出额度。新对照输出上限 8192，旧 400KB 测试门槛改为 8MiB 传输保护，提供方真实上下文限制仍适用。当前源码重新安装后 7 项必要工程检查通过（真实 SDK/CLI＋合成服务，**不是模型业务验收**）；最初沙盒禁止监听/子沙盒的失败另存，未记作通过。六套配置、Skill 加载及安装源码一致性核验完成。准备结果见同目录 `verification.json`。

**执行授权：**用户回复“批准，按上述边界执行”，本批 $20（含全额未核账预留）、累计 $40、累计最多 787 次。已通过原扩额机制记录 `authorization-money.json`、`authorization-scopes.json` 和 `manifest.json`，原 267 条请求及费用/预留保留。开始前已收费 $4.97365957、全额未核账预留 $11.55058336；未充值。本批在仓库外私有工作目录串行执行，结果与证据回收至 `output/data-agent-sdk-matrix-20261019/`。共有工程失败先定位，不能归咎模型并耗费其他路线。结果逐条核对原 PDF，报告成功/失败/未运行，结束后 review 停止。File Search 凭据和路线问题保留在下方，不阻塞本批。

## 前项：加入 OpenAI File Search 对照 — 接入边界已核对，真实对照未启动

**2026-10-19 用户补充：**同时比较官方 File Search；随后询问能否继续用 OpenRouter。已核对官方文档、安装的 Agents SDK 0.24.0 和实际 OpenRouter 工具目录：SDK `FileSearchTool` 是 Responses 托管工具，现有 Chat Completions 转换会在网络发送前明确拒绝；OpenRouter `GET /api/v1/tools` 返回 200、列出 11 项工具，没有 `file_search`。这不等于 OpenRouter 不能调用普通 function，也不把未来或未公开兼容性说成已验证。

**当前缺口与对照安排：**环境及项目 `.env` 未发现 `OPENAI_API_KEY`；现有 provider/网关也尚未接 OpenAI 官方 Responses 和托管工具计费。原生对照建议固定 Terra、同一 SDK/官方 Responses 路由、同题同原件，A 为现有数据工具，B 为官方原生 File Search，业务 prompt/验收一致，仅替换必要的工具说明；旧 OpenRouter 结果保留为历史参照。若要五模型继续沿用原路由，可将官方 `vector_stores.search` 包装成普通 function，但这是 Retrieval 后端对照，仍需 OpenAI 凭据，不能冒称原生 File Search。详细差异及核验口径写回核心设计 **12.1**。本轮只做只读核对和本地 SDK 最小复现；未上传、未创建索引、未调用付费模型、未改原账本或业务实现。真实接入待凭据/路线确定，不能标为已测。

## 前批：同一 OpenAI Agents SDK 的五模型对照 — 已完成实跑与 review

**最新转向（2026-10-19）：**用户要求保留 Data Agent，以同一 OpenAI Agents SDK 比较 GPT-5.6 Sol/Terra/Luna、DeepSeek V4 Pro/Flash。本轮先固定原 C2“两年合并营收＋代码增长率”一题，每模型一个独立连续会话、最多 24 次物理请求。GPT 走 OpenRouter/OpenAI，DeepSeek 官网直连；同一问题、原件/解析包、工具和业务标准，保留各模型独立 prompt 与厂商 Skill 指导。细节及停止点在核心设计 **14.20**；Claude 指令隔离保留为未完成项，本轮不展开。

**准备记录：**五套 profile/prompt、显式 Skill 映射及价格/版本只读预检已完成；安装环境为 openai-agents 0.24.0 / openai 3.31.0。准备期 `comparison-plan.json` / `verification.json` 的未授权、0 次调用字段保留为历史快照；随后授权和真实结果分别见同目录 `authorization-*.json`、`manifest.json`、`review.json`，不以准备检查代替业务验收。

**本轮交付：**五路各一条真实会话，共 **84 次请求**；Terra 17 次、DeepSeek Pro 21 次、Flash 11 次均完成交付并通过独立原 PDF 核验；Sol 12 次、Luna 23 次均在本地 400000 字节请求限制处失败，不能据此判定模型能力排序。五路完整 Skill 均进入实际模型输入；实际业务请求和工具 schema 相同，五份 prompt 与两厂商指导主体逐字一致，运行前后 86 个源码/安装文件未变。Pro 两次参数 JSON 截断对应输出达到 4096 token；各路都有不支持参数或返回体过大带来的恢复。准入前两处账本扩展机制修复已通过 15 项行为检查；推理期间未改业务代码、prompt、工具或限额。详见核心设计 **14.20** 与 [review.json](output/data-agent-model-ab-20261019/review.json)。

**费用与停止点：**本轮 OpenRouter 已报告 $1.51617391；DeepSeek 未返回账单，全额保留 $6.48325986（不是实付），合计占用 $7.99943377／$15。原账本累计 267／307 次，已报告 $4.97365957、全额未核账预留 $11.55058336，剩余 $7.47575707／$24；未知传输/在途为 0，旧费用和预留保留，未充值。Terra/Pro/Flash 的 JSON、Markdown、CSV 已导出到本轮同目录 `*-delivery/`。当前停止待 review，不追加模型调用；旧平台 goal 仍 paused。**下一步建议（未启动）：**先收敛工具返回体与引用操作，保留完整证据、压缩模型可见重复内容，并让文档工具公开 schema 与实际能力一致，再冻结同题复验；不自动切换 Codex/MCP 或修 Claude。

## 前批：新版文档库接入 Agent（历史状态，未完成项保留）

**恢复决定（2026-10-19）：**用户批准累计 $12／本批 $6，随后批准两条营收路线各追加最多 12 次（各累计 24、根账本 163→187）。原 159 条请求、全额预留及其他 scopes/停止状态保持。金额与次数新契约分别为 `manifest-money-v2.json`、`manifest-requests-v3.json`（均在 `output/data-agent-documents-20261019/`）。OpenAI C1、C3 已独立核对原件通过；两条 C2 首次各 12 次仍 partial。已修正共享表格、搜索与上下文机制并复验两条 C2；本轮停止，已通过项未重跑。平台 goal 当时仍 paused，用户恢复指令允许本轮执行，不将平台标记冒称 active。

**新目标（2026-10-19）：**用户要求重新制定目标，并在完成后 review。上一批原生目录＋passages 的组织方式已获用户认可；下一批在已入库的 Apple/Alphabet 两份 PDF 上，接通材料发现 → 版本 schema/目录 → passage/表格读取 → 有来源的记录提取 → 代码计算 → JSON/Markdown/适用 CSV 交付。复用两套官方 SDK、共享工具、证据/计算/交付与累计账本；详细范围、三个冻结 case、实现落点、运行限制与 review 标准只维护在核心设计 **14.19**。

**扩额前状态（2026-10-19 首次收尾）：**共享文档版本引用、材料发现、原生目录/passage/表格读取、有来源的记录提取、代码计算和 JSON/Markdown/适用 CSV 导出已接入。安装包上的 9 项文档行为、37 项旧查询、10 项账本扩展检查通过；真实材料的直接工具链也已走通，后者是宿主指定操作的工程检查。OpenAI Agents SDK＋DeepSeek 的 C1 已完成 12 次真实请求，独立核对原 PDF 后通过：前两项 Business Risks 的主题及完整说明保留，包括第二项的第二自然段。OpenAI C2、C3 和 Claude C2 均未运行，整批目标未完成。

**前批 review 建议（上方已调整优先级）：**先修复 Claude 指令隔离：实际请求中完整 Skill 正文已加载，但同时混入仓库开发用 AGENTS.md；当前 project 设置与仓库内 cwd 未做到隔离。再收敛文档工具公开能力，避免 any_terms/issuer 等不支持参数消耗轮次。详细证据与后续准入见核心设计 14.19，不新增平行任务。两条 C2 最新复验各又用 12 次、累计各 24，均未完成记录/代码计算；C1/C3 保持通过，整批 2/4。原表格/搜索/上下文错误已修复；新发现的读游标预算矛盾也已修复并回放，但未在真实 Agent 再验。14 项文档行为、14 项额度修订检查通过，相关旧查询回归见 [review.json](output/data-agent-documents-20261019/review.json)。根账本 183/187 次，已报告收费 $3.45748566、全额未核账预留 $5.0673235、累计剩余 $3.47519084；本批剩余 $2.3687901。金额未耗尽，但两条 C2 次数已用满，本轮无更多模型调用；goal 未完成。

**扩额前费用快照：**未重解析或切默认版本。新问题、版本、独立 prompt/Skill 与每路 12 次、四路共 48 次、本批 $1 上限已冻结到原账本，累计 $6/163 次上限不变。收尾为 124 次、已报告收费 $3.45748566、未核账全额保留 $2.0498272、累计剩余 $0.49268714；未知费用和在途均为 0。C1 新增保留 $0.6137136，本批剩余 $0.3862864；完整 token 用量的峰值非缓存估算 $0.1529787 只是参考，未当作账单或释放预留。用户明确维持原全额预留规则，不扩额、不继续其余三条、不把暂停写成完成。恢复入口见 LOCAL_DEVELOPMENT“新版文档库的 Agent 交付与只读复核”。

## 已 review：原生目录与 passages 的重新解析结果


**本轮约定与范围（2026-10-19，用户确认）：**可靠的 PDF 原生书签作为唯一目录，不再将正文主题句扩成目录；目录内用 `passages[index]` 表示主题句及其全部连续说明，跨页不拆散，保留原始块、表格单元格与位置。仅重跑原 Apple/Alphabet 两份全文，本地 Docling，不接入远程付费模型、不恢复旧 goal。发布新版本、不覆盖旧包、不切默认；核对 Business Risks 的前两组、Macro 风险分组、原生 iPhone 路径、跨页内容与旧引用后交付。前述“正文标题补目录”的记录为历史版本，不再是本轮策略。

**已完成与停止点：**两份真实本地全文解析及导出完成：`apple-2025-native-passages-v1` 为 80 页/102 原生目录节点/229 passages，`alphabet-2025-native-passages-v1` 为 99 页/103 节点/276 passages。两份目录 node/parent/title/order 与原生书签一致；旧版 970/1,427 块的文字、类型、坐标及表格结构逐块未变。用户两张图对应 Business_Risks.passages[0]（主题＋一段）/[1]（主题＋两段）；Macro 3 组、iPhone 原生路径保留，Apple/Alphabet 的跨页内容抽查见原件证据。25 项工程检查通过，12 份旧冻结包字节与默认版本不变。结果位于 `reviews/<parse_id>/passages.json`，同目录 sections.md 为阅读视图，package.json 含完整行/单元格定位；CLI 见 LOCAL_DEVELOPMENT 新节。无远程付费调用，未恢复旧 goal。

**仍未完成的质量项：**两版保持 partial；Apple/Alphabet 各有 3/12 个原生书签未匹配正文标题（目的地保留），123/172 条文字行未唯一对齐正文字符范围（原始行与矩形保留），Alphabet 签字表 `tables-73` 结构失败沿用明确状态。原文核对中的引号规范化、列表符号分离保留差异记录：列表 marker/orig 在原始 Docling 输出，规范 block.text 未保留符号/嵌套层级；未改原件、未以删词放宽校验。Apple 两处财务索引表过滤、全篇分组语义/全部定位及扫描件 OCR 未完成。本轮停下供用户 review，不继续扩大修复或解析范围。

**继续范围（2026-10-17）：**用户要求继续，本轮将已指定 Apple 80 页和 Alphabet 99 页扩到全文，在原 data 根发布新解析版本、不切默认。顺序运行现有本地 Docling；先检查完整页覆盖、未匹配书签/层级疑点，再重放前轮九个小节与表格/过滤原例。发现共同机制问题后作范围内修正；全文转换完成不等于全篇业务语义验收。无付费调用，不进入无书签、复杂合订 PDF、Agent 联调或旧 goal。完成可查看结果及差异说明后停止。

**全文结果与当前停止点（2026-10-17）：**Apple 80 页、970 块、248 目录节点；Alphabet 99 页、1,427 块、309 目录节点，已真实运行并分别发布 `apple-2025-full-sections-v2` / `alphabet-2025-full-sections-v2`。原九个小节回查一致，两张财务表的表头、单位、附注和全部结构化单元格与此前核对版一致；7 项小节测试、16 项存储测试通过，12 份冻结包可按原字节读回，未切默认。真实本地推理、远程/付费模型调用 0。结果入口为 `data/data_agent_documents/reviews/<parse_id>/sections.md`，证据为同根 `reviews/full-source-checks.json`。以下局部页结果保留为前轮记录，不再代表当前覆盖范围。

**仍需 review：**两份全文均为 partial：Apple / Alphabet 分别有 3 / 12 个书签尚未匹配正文标题、3 / 16 个父子关系候选；书签和目的地仍保留。Alphabet 第 99 页签字表模型输出单元格重叠，初版发布失败；新版明确记录表格结构失败并保留原始输出与截图，没有修成成功网格。Apple 第 31、57 页财务索引表尚未从正文视图排除。全文覆盖不代表全文质量通过。当前与用户一起审阅，不继续扩大解析或恢复旧 goal。

**本次代码 review：**当前标准 Docling 链没有业务 prompt；使用本地布局/表格/OCR 模型和章节规则。虽开启官方 HeadingHierarchyOptions，但适配器没有将 SectionHeaderItem.level 传给目录构建；原始输出仍保存该字段。应先比较官方层级与当前规则，不能直接认定替换后更好：实际 Alphabet 的 Google Services / Serving Our Users 均为 level 6。此处记录发现，不自动改变解析策略或启动 VLM。

**最新输入（2026-10-16）：**用户明确指定 Alphabet 2025 10-K 与 Apple 2025 As-Filed PDF，并要求同一标题下的正文不要拆散，先明确最小一级标题。本批以这两份 PDF 为准；上一轮 HTML 路径不作为当前实施输入。已下载并检查原生书签、文字和相关页面：Alphabet 99 页/103 个书签，Apple 80 页/102 个书签。Apple Business 的书签有 Products/Services，但没有其下 iPhone/Advertising/AppleCare 等正文小标题，不能把书签末级等同于正文末级。

**最新约定（2026-10-17）：**用户认可书签骨架＋正文标题补齐＋完整小节的解析方向，并要求过滤无效信息。按经确认的最小正文标题保存多段/跨页正文，父目录可聚合读取；长风险标题也可作为叶子。过滤先覆盖有证据的页眉页脚、独立页码和重复导航；目录条目用于索引，不混入章节正文；单位、脚注、表头、风险披露保留。封面/签字默认隐藏的偏好未收到答复，本批先保留，不阻塞排版噪声过滤。核心设计见 14.18.2 第九、十部分。

**本批结果（2026-10-17）：**已实现并真实运行书签＋正文标题补齐、父子 code 路径、完整小节读取和正文过滤。选定 Apple 物理页 4–5/11–12/32–33、Alphabet 4–7，共 10 个不同页面，真实本地 Docling 布局/表格，付费/远程模型调用 0。Services → AppleCare、Business Risks 下长风险标题、Google Services → Serving Our Users 均恢复；九个小节的段落范围与原 PDF 文字层核对一致，两处跨页连续；两张报表单位、列头、附注及抽查数值保留。18 个噪声块从正文视图排除、原引用仍可取回。细节/失败修正/边界见核心设计 **14.18.2 第十二部分**。

**审阅入口：**`data/data_agent_documents/reviews/` 中的 `apple-2025-business-sections-v1`、`apple-2025-risks-sections-v1`、`alphabet-2025-business-sections-v2`、`apple-2025-financial-sections-v3`；分别打开 sections.md 看目录/正文/表格/过滤对照，schema.json / package.json 看实际结构。CLI 见 `docs/LOCAL_DEVELOPMENT.md`“带书签 10-K”一节；查询不重新解析。产物在现有 data 根，不在 output。

**验证和当前停止点：**当前源码普通重装，五个安装模块字节核对；4 项小节/兼容边界＋16 项存储测试通过，现有九份冻结包原字节可读，财务最终版复跑 reused，不改默认版本。新解析均保留 partial。全文、纸面目录页分离、无书签/扫描件、复杂合订材料及模型消歧没有完成；OCR auto 本轮使用文字层，不冒充扫描件 OCR 验收。此处停下，先 review 最小标题、父子关系和正文边界；是否扩到这两份全文留待审阅，不自动恢复旧 goal 或进入 Agent 联调。

## 前序：SEC HTML 10-K 路径核对

**最新范围（2026-10-16）：**用户提出先从 SEC 提供的 10-K 开始。本轮只读核对源码和新文档库，不启动实现；复杂合订 PDF、按页 OCR、多目录作用域方案保留待后续，不作为当前主链的前置要求。

**现状与下一小批：**旧 `sec_index.py` 已有 Part/Item 目录、锚点核对及 `build_legal_outline`；`build/html.py` 已有正文/表格/Inline XBRL/来源定位，但未把上述目录结果传入其 sections，新文档库尚无 HTML 适配。普通 h1–h6 支持父子关系，样式标题目前无父节点；新查询路径仍按原文 title 数组，没有 code。只读确认新库仍仅有 Alphabet 业绩稿，不能称 SEC 10-K 已接入。下一步建议以一份明确 SEC 10-K HTML 完成目录 → 正文小标题 → code 路径 → 内容/表格 → 原文出处，复用已有实现并在真实原文验收；具体边界见核心设计 14.18.2 第八部分。当前没有运行新的解析或测试。

## 前序：目录定位与层级恢复方案调研

**本轮范围（2026-10-16）：**用户确认目录需有独立 code、父子层级与拼接路径，要求先调研目录页定位、跨页和无目录的实现方式。本轮核对官方资料与已安装源码，方案写入核心设计 **14.18.2**；只更新设计和状态，没有修改解析实现、重跑模型或恢复旧 goal。

**结论与下一步：**优先复用 Docling 的布局/OCR/标题层级与 PDFium 的书签/目的地/页标签；补齐目录候选检测、跨页条目合并、正文定位及统一树构建。现有适配虽启用标题层级恢复，但新存储目录仍只用书签。先以 Apple 原 HTML 的目录锚点、正文小标题和 `Business.Company_Background` 路径贯通原案例，再用真实跨页目录 PDF、无目录材料验证公共机制；不以 Alphabet 平面书签代替原案例。具体流程是拟议方案，跨页识别质量及扫描件效果尚未实测；真实补充材料尚待选定。

**用户补充样本与处理顺序（2026-10-16）：**已下载用户指定 NVIDIA 2026 合订年报并作真实 PDFium 结构检查，175 页、223 个书签；第 21 页为 Proxy 部分目录，第 90 页为 10-K 目录，第 14 页有前置叙述的小标题。用户确认这类材料先拆：按物理页建立处理单元，再识别文档部分及目录作用域，融合原目录和全文正文标题，跨页拼接；原件仍是一份，不逐页创建资产。已将证据、书签质量筛选和 DeepSeek-OCR 候选边界补入核心设计 14.18.2 第七部分。尚未运行该年报的 Docling/DeepSeek 模型解析，没有完成目录行为验收；本例两处目录不等于已取得跨页续目录样本。此轮仍停在设计，不启动实施或旧 goal。

## 上一轮：纠正验收材料错配，Apple 原文目录尚未验收

**用户 review 纠正：**用户讨论和截图是 Apple FY2024 Form 10-K；本轮实际选用的是 Alphabet 2024 Q4 业绩稿。此前“查看原文目录”链接与用户材料不对应，不能用 Alphabet 的 9 个一级书签解释 Apple 的 Part → Item 目录，也不能据此宣称原案例验收通过。已核对库中只有 Alphabet 一份原件、两版解析，未发现把 Apple 绑定到 Alphabet 的存储记录；问题是验证材料选择/说明错误。目录、块、单元格展示补材料名称，表格概览补内容，块补目录路径。**Apple 目录解析、正文范围映射与原图逐项验收仍未完成**；正文小标题组织、完整目录语义覆盖亦未完成。本轮不以手工填写截图目录冒充解析。

**结果（2026-10-16）：**真实 Alphabet 2024 Q4 release（10 页）已用 Docling 本地模型执行并写入 `data/data_agent_documents/documents.sqlite`。同一原件保留两版：auto 为默认（约 24 秒，文字层 90 块）；full_page 为 OCR 对照（约 41 秒，1,125 条真实识别记录，90 块）。每版 76 文本＋14 表格、9 个原生目录节点；没有检测到独立图片块。原件与模型权重长期存放于 data，不以 output 为数据根。复跑同输入/版本返回 reused，不再推理；原件字节、重开后旧引用、同页两项目录和目录定位利润表已核对。

**效果与缺口：**首张表 11 行×5 列、48 个含合并信息的单元格；收入行 4 数值与原件一致。强制 OCR 把部分 CEO 引语和脚注识别成乱码，auto 读取文字层后恢复；不把一份/局部核对当作整篇质量通过。正式标签词表未配置，图表语义描述未生成，PDF 全部链接/印刷目录尚未验证；本例 Docling 未提供 caption/footnote 关联，`block_relations` 为 0，邻近正文仍可通过 neighbors 读取。两版均标 partial。旧 Agent 工具尚未切换到新存储；当前不进入 Agent 联调或完整业务验收。

**展示入口：**Datasette 0.65.5 仅监听 `127.0.0.1:8001`，使用 `inspect_materials / inspect_directory / inspect_blocks / inspect_table_cells`；按 parse_id 选择版本。真实接口已核对默认版 90 块、9 目录、首表 48 单元格。用户截图已打开该工具；空的 block_relations 是关联缺口，不是正文未入库。源码入口 `documents/pdf.py`；安装、解析、查询及查看命令见 LOCAL_DEVELOPMENT，细节见核心设计 14.18.1。

**验收与停止点：**原 14 项存储行为＋OCR 来源区分通过；展示材料身份、日期、字符串行号筛选、路径和表格预览的新增定向回归通过，共 16 项。4 个相关安装模块与当前源码逐字节一致。首次规范化因 PDFium 页面不支持 context manager 失败，按实际 API 改为显式 close 后，以同一原件和 full_page 模式重放成功；不删除失败事实。新增 PDF 可选依赖与锁一致，旧依赖版本未变。真实本地推理已执行，远程付费调用 0。此批收尾后停止，下一步先 review 解析质量与关系/标签缺口，不自动恢复旧 goal。

## 上一批：文档查询存储（只通过合成存储验收，真实接入未完成）

**目标与授权（2026-10-16）：**用户确认材料—解析版本—内容块模型，以及从目录、标签、关键词定位内容的存储方案，要求实现且不背历史包袱。本轮完成通用存储及可复制 Python 入口：材料筛选、版本固定、目录树/路径/子树、标签交并、类型筛选、全文、上下文、旧引用读取。解析包单向发布到 SQLite 查询投影；复用不可变对象存储，正常查询不重新解析。

**范围与停止点：**新入口接收规范解析结果；不虚构正式业务词表、不新增 PDF/OCR/模型打标器、不替换旧 SDK 会话或迁移历史账本。采用合成材料验收正常链、版本/关联错误、重复路径、原件损坏、发布中断和索引重建。只有存储与引用正确不代表解析/OCR/业务标注质量已通过。实现细化见核心设计 14.18；保留现有未提交改动与原失败记录。

**结果（2026-10-16）：**新契约、SQLite 查询存储、Python/CLI 和合成示例已实现。14 项行为测试通过；CLI 跑通材料发布 → schema → 目录子树＋标签交集定位表格 → 读取标题/脚注 → 导出和同包幂等重放。原件字节一致、重开后旧引用不变；schema 区分未打标、失败和完成但无匹配。6 个安装模块与当前源码逐字节一致，使用 `python -I`，无导入路径注入。未升级依赖，真实模型/OCR 调用 0。首次损坏测试因合成 CAS 文件只读失败，已修正故障注入后复跑；未改变生产文件权限。命令见 [LOCAL_DEVELOPMENT](docs/LOCAL_DEVELOPMENT.md#文档解析结果的查询存储)，实现与限制见核心设计 14.18。

**下一小批（未启动）：**确定首个 PDF 解析/OCR 提供方与能力边界，再将真实文本、表格、图片、链接及位置转换为本轮解析包，持久化后重复查询不重新解析；核对原文位置和缺失状态。固定业务词表尚待定义，不能自行造标签。旧 Agent 工具接入和历史材料迁移另外实施，本轮在存储交付后停止。

## 上一批：通用 Harness 卡点修复（已完成限定离线验收）

**本轮（2026-10-16）：**按用户要求把可确定修复的问题交给工程机制。Skill 读取允许显式指定同一工作目录，继续拒绝其他目录、符号链接、包外文件、篡改和任意命令；区分工具调用结束与完整正文返回。资产/schema 新信息按来源及内容去重计为进展，重复内容仍累计 no_progress；重开、旧状态升级、澄清和中断不重置已见历史。没有公司、指标、金额或样本路径特例。

**验收：**12 项相关行为检查通过。Luna 原失败的相对/绝对文件路径＋合法 workdir 均通过真实 SDK 的合成正常链；Sol 原 4 页 151 个新概念的计数从 1/2/3/4 改为 0/0/0/0，重放原 13 个已接受操作不再触发错误停止，重复页仍计数。首次 SDK 检查受外层沙盒阻止，获准本机执行后通过；原失败保留。普通重装源码后核对安装内容；真实模型新增 0 次，原账本和结果未改。

**边界与入口：**本轮修复不保证模型选对指标、主动补齐口径或完整遵循 Skill；定向概念发现、游标续页便利接口、交付双份引用简化仍未实现。本轮交付后停止，不自行修改业务验收或追加模型调用。核心设计 14.17.13 第 9 项新增清晰的 query/预期答案/原件位置，第 10 项记录机制修复；验证命令见 [LOCAL_DEVELOPMENT](docs/LOCAL_DEVELOPMENT.md#通用-harness-修复的离线验收)，证据追加至现有 `configured-verification.json.harness_fix`。下一步是 review 修复和案例，再以同题验证真实模型效果。

## 上一批记录：Luna、Sol、Sonnet 真实 Skill 业务对照与循环定位

**已授权（2026-10-16）：**用户要求扩大轮次比较 Luna、Sol、Sonnet，并明确原账本累计上限提高至 $6；同时要求定位效果差和轮次多的卡点。三条均使用 OpenAI Agents SDK 0.24.0 / OpenRouter、同一原问题和材料、相同验收要求，各自独立 prompt 与 Skill 指导。各最多新增 30 请求，串行各一条，不自动用满或扩展 40 query 基线。

**本轮已结束：**原 73 次请求逐项摘要未变；新增 E/F/G 共 39 次真实请求。Luna 15 次 / $0.03397973，程序 completed，但两次正文读取均被 `workdir` 限制拒绝，未完整执行 Skill，合并口径证据链不足；Sol 12 次 / $0.6199860，正文与工具指南已读，连续新增概念页却计为 no_progress，在取数前被宿主停止；Sonnet 12 次 / $1.539366，正文已读、工具指南未读，收入/计算完成但主动 partial，尚未尝试可用的合并标题补查。独立原件核对确认 Luna/Sonnet 数值、日期、币种、计算正确；三条均不记为完整业务验收通过。操作状态 completed 不等于 Skill 正文读取成功，已按实际后续请求纠正该判断。

**循环定位及下一动作（待 review 后实施）：**先修 Skill 对合法工作目录的误拒绝和 schema 新信息的进展判定，保留越界拒绝及真正重复查询的停止机制；再处理定向概念发现、游标参数说明、交付双份引用和未尝试补查造成的开销。各模型本轮实现保持冻结，没有中途调 prompt 或追加重跑；一例且 Skill 暴露不同，不能据此排名模型能力。原账本累计已报告 $3.45748566，旧未核账保留 $1.4361136，剩余 $1.10640074，无在途/未知传输，不充值。当前停在本轮对照与定位交付，不自动进入下一批或 40 query 基线。

**工程与证据：**9 项相关行为检查通过，4 个已安装相关模块与源码相同；新增独立比较 scope 使用精确配置指纹和同一账本。旧 B/Claude 已有进程退出及 8 个操作完成证据，但跨时钟域无法走原关闭入口；仅在新增独立比较时只读确认旧失败进程无活动，不伪造关闭、不恢复旧会话，保留未决传输/费用拦截。旧 recovery_required 及失败记录不改写。结果和逐轮诊断追加至 [configured-verification.json](output/data-agent-skill-20261016/configured-verification.json) 的 `model_comparison`，三条原始 `result.json/evidence.json` 位于同目录 `{luna,sol,sonnet}-live/`；设计 14.17.13 第 9 项，查看命令见 LOCAL_DEVELOPMENT。未修改业务工具、Skill 读取规则或进展判定，未升级依赖。

## 已完成：Sandbox Skills＋OpenRouter 本机协议链

**本轮（2026-10-16）：**按用户要求补齐 OpenRouter 协议链验证。生产 runtime 已能复用现有官方 Chat 适配器，本轮新增合成 peer 的原生 Skill 动作、配置和恢复入口，以及 3 项针对性测试；未重复实现适配器。review 未发现需要修改生产代码的问题。

**验证范围：**原生 Skill 工具以 function tools 通过实际 HTTP 序列化，所选正文进入后续请求，model/provider/reasoning 参数与冻结配置一致，store/parallel_tool_calls 按配置省略，reasoning_details 保留。正常链及中断恢复均以 10 次本机 HTTP 完成交付；越界读取明确拒绝，外部文件内容没有进入请求。补跑旧网关正常链检查兼容。8 个已安装生产模块与源码相同，20 份旧配置/prompt 未改。

**证据与停止点：**设计 14.17.13 第 7 项；结果追加至现有 [configured-verification.json](output/data-agent-skill-20261016/configured-verification.json) 的 `gateway_skill_integration`。[可复制测试入口](docs/LOCAL_DEVELOPMENT.md#正式-runtime-的-skill-装配与恢复)。模型响应为本机脚本，真实模型调用 **0**；没有恢复旧 goal、改账本或升级依赖。本轮收尾后停止。实际 OpenRouter 服务、具体模型效果及 40 条自主选择基线仍待后续；批量采集入口和运行组合尚未完成，不将本机协议通过记为实网通过。

## 已完成：Skill runtime 接入限定验收


**本轮（2026-10-16）：**按用户“实现然后测试”接通两套正式 runtime。profile 可配置 Skill 名称与 model_version；宿主按模型/SDK 选择并冻结包，OpenAI 使用官方 Sandbox Skills，Claude 使用隔离项目发现及 Skill 工具。恢复读取原内容快照，不重新套用已改变的模板；原有 16 份模型配置/prompt 文件逐字节保持不变，没有切换旧四路或恢复 goal。

**验证：**13 项限定检查通过（5 加载器＋7 runtime 集成/恢复/失败边界＋1 旧 Claude 正常链，旧 OpenAI 链在 7 项内）。两套真实 SDK 均完成按需加载、正文进入输入、8 次业务工具调用、代码计算与交付；模型响应为脚本，真实模型调用 **0**。OpenAI 中断恢复保留精确原生工具文本；Claude 正常恢复通过，篡改 Skill 正文在发出下一请求前被拒绝。6 个相关已安装模块与源码相同，不依赖 PYTHONPATH。

**修正与证据：**OpenAI 的原生字典输出在持久化排序后转文本不一致，已保存首次精确文本；Claude 官方会话接口过滤 isMeta，已分别检查公开会话和实际请求中的冻结展开。原失败摘要与最终核验追加至现有 [configured-verification.json](output/data-agent-skill-20261016/configured-verification.json) 的 `runtime_integration`，设计见 14.17.13 第 6 项。[可复制测试命令](docs/LOCAL_DEVELOPMENT.md#正式-runtime-的-skill-装配与恢复)。

**停止点与缺口：**本轮实现和限定测试完成后停止。40 条 query（30 正/10 负）的真实自主选择基线仍为 not_run，批量采集入口尚待实现；SDK/模型组合和本批运行限制尚未确认，不把脚本化加载通过作为选择准确率。后续先 review 本次接入，再推进该独立基线；不自动运行旧四路或新增付费请求。

## 已完成：Skill 自动选择基线的用例与离线评分准备


**本轮（2026-10-16）：**澄清 `get_skill` 只生成完整适配包，SDK 自动发现才负责 available skills；项目未新增统一 `list_skills`，两者不能互相替代。按用户要求配置 [40 条 query](tests/fixtures/data_platform/skill_trigger_queries.json)：30 条预期加载、10 条预期不加载，正反例交错，包含财务领域近似反例。规则写回核心设计 14.17.14。

**可检查入口：**`scripts/data_agent/skill_trigger_baseline.py --cases tests/fixtures/data_platform/skill_trigger_queries.json --show` 可查看全部用例和预期；同一入口支持对版本匹配的观察记录评分。2 项离线测试通过，异常和缺失不当作正确不加载，选择成功与加载成功分别统计。测试中的类别数误写已修正为必要类别检查，未调整用例标签。

**待完成：**已询问基线使用两套 SDK＋DeepSeek 官网还是先跑 OpenAI 一套；真实 SDK 批量观察采集尚未接通，真实基线 **not_run**，调用 0。下一动作是确定运行组合与本批额度后接通原生采集并跑冻结用例，不自动恢复旧四路 goal。未把此前脚本化加载测试算成 40 条模型选择基线。

## 已完成：Skill 原生发现与按需加载补充核验

**发现环节补充（2026-10-16）：**按用户要求先核对两套官方 SDK 的适配：OpenAI 原生 `list_skill_metadata` / `Skills` 提供 available skills，再由模型调用 `load_skill` 并读取正文；Claude 原生项目发现＋精确 `skills` 白名单展示目录，再由模型调用 `Skill`。不新增重复的模型 FunctionTool 或描述注册表。职责与接入顺序已写核心设计 14.17.13。

**本次验证：**只增强并复跑 2 条受影响的原生 SDK 测试，均通过：首个实际模型输入含名称＋描述，不含完整正文；原生加载后读到配置选中的正文并执行检查脚本。另验证 OpenAI 按需 materialize、Claude 未启用的合成 Skill 不进入可见目录。脚本化模型响应、真实调用 0。`skills.py` 安装包与源码一致，加载器/profile/runtime 未修改；证据追加至现有 [configured-verification.json](output/data-agent-skill-20261016/configured-verification.json) 的 `discovery_followup`，保留先前记录。

**停止点：**发现/加载的 SDK 机制已核验，正式 Data Agent profile/runtime 自动装配和恢复绑定仍待下一批，不自动启用旧四路或恢复 goal。

## 已完成：配置化 Skill 加载器及原生加载限定验收

**本轮范围（2026-10-16）：**用户认可简化方案并同意实现。已按核心设计 14.17.13 完成 default＋template＋映射＋参数＋`get_skill`、可复制示例，以及两套 SDK 加载动态包的限定离线验证。旧四路配置、生产 runtime、源码依赖和费用记录未改，未恢复旧 goal。

**结果：**5 项加载器测试＋3 项原生/交付检查通过。四级选择、参数、确定性、未选指导隔离与必要失败边界已验；两套 SDK 均实际读到所选正文并执行检查脚本。DataService 8 工具合成链在测试准备阶段执行，模型决策为脚本，真实调用 0，不称自主业务效果通过。当前包已普通重装，实际导入的 `skills.py` 与源码逐字节一致。OpenAI 新生成目录最初未被 SDK 发现，按官方本地源规则添加仅该包的只读 grant 后原失败复跑通过。[验证记录](output/data-agent-skill-20261016/configured-verification.json)。

**入口与停止点：**`examples/data_platform/skill.py` 可直接渲染/输出完整 Skill，调用与复跑命令见 LOCAL_DEVELOPMENT 的“配置化 Skill 获取与限定离线验证”。本批完成后停止；下一步是将 Skill 名称绑定到正式 profile/runtime、核对快照恢复，再另做真实效果调优。当前没有启用原四路新 Skill，不自动切换生产或续跑旧 goal。

## 已完成：交付契约与 Skill 加载/执行检查

**本批授权（2026-10-16）：**只完成 review 路径 1＋2：补清财务取数/比较的交付要求，编写对应业务 Skill，并测试加载和执行。沿用现有 DataService/交付 JSON；不进入 state/deliver 接口简化，不启用原四路生产配置的新 Skill，不追加真实模型调用。原 goal 保持 blocked。

**实现位置：**核心设计 14.17.12；`config/data_platform/skills/financial-data-query/`（正文、工具使用参考、只读交付检查脚本）；`tests/integration/data_platform_agent/test_financial_skill.py`（现有 Data 工具合成链、交付边界及两套 SDK 原生加载/脚本执行）。

**已完成并停止：**3 项限定测试通过：交付正常/合法 partial/文字冒充计算/缺失依赖/partial CLI 非零；OpenAI 官方 Sandbox Skills 的发现→加载→正文进入输入→检查脚本执行；Claude 官方 CLI 的 Skill 调用→正文进入下一请求→检查脚本输出进入下一请求。skill-creator 格式校验通过，7 个相关已安装生产模块与当前源码逐字节一致。只使用合成材料和脚本化模型响应，真实模型调用 0；不宣称模型自主业务效果通过，不代表原四路生产 runtime 已启用 Skill。OpenAI 本机测试按官方 Manifest 配置只读 Python 环境路径，未关闭 sandbox。[验证记录](output/data-agent-skill-20261016/verification.json)。

**该批停止点：**路径 1＋2 已完成并停止；本轮仅继续架构设计，不自动进入路径 3（工具接口简化）、生产 Skill 装配、模型 prompt 调优或真实四路续跑。

## 此前四路真实验收记录（截至 2026-10-15）

**Goal 状态：blocked（受阻，未完成）。**同一 A/C 次数上限阻塞已连续三轮复核，必要的非付费修正、验收与只读定位已收尾；没有在途 worker/请求。本轮未新增调用。待用户 review 候选改法并决定后续次数，不自动重试或扩大范围。

**当前结果（2026-10-15）：**用户批准的累计 $3 / 每路 20 次 / 整批 80 次已应用到原账本；未新开账本、充值或更换模型。本次授权后新增 40 次物理请求，四条路径均已真实执行，但 **0 条完整功能链通过**。已停止重复实跑，不进入来源发现、PDF、工作台或生产。

| 路径 | 累计次数 | 最新业务结果 |
|---|---:|---|
| A：OpenAI Agents＋DeepSeek | 20/20 | 能找到、搜索及读取材料；先前在本地 200 KB 请求上限失败，未计算/交付，次数已用尽。 |
| B：Claude Agent SDK＋DeepSeek | 17/20 | 能查询 typed records；SDK API 错误被误分类为身份错误。分类已离线修正，真实新版本未复验；剩 3 次，不盲重启整链。 |
| C：OpenAI Agents＋Luna/OpenRouter | 20/20 | 新执行追加 5 次、未触发字节限制，但遇到参数/记录字段错误后耗尽次数；未计算/交付。 |
| D：OpenAI Agents＋Sonnet/OpenRouter | 16/20 | 两次新执行均给 partial JSON；最新未调用记录提取/代码计算，营收数值正确不等于完整通过。 |

**已修正：**显式新执行请求上限（本轮设 512,000 字节，费用/次数仍累计）；Claude 合成 API 错误保留与分类；展开概念标识及记录字段的可见契约/错误反馈；追加授权后单会话请求计数。A 的旧 immutable result 曾将累计 20 写成当次请求数，原文件保留，核对后当次实际为 10。12 项受影响行为检查通过，记录字段补充后同一项复跑通过；当前 7 个相关生产模块与普通安装包逐字节一致。大于 200 KB 的准入修复已离线验证，本轮 C/D 真实复验尚未发送大于该值的请求，因此不声称实网边界已证明。四份独立 system prompt 未改。

**费用与剩余边界：**同账本累计 73/80 次；响应报告收费 $1.26415393、未核账保留 $1.4361136，可用 $0.29973247；没有在途或未知传输。A/C 均无剩余调用次数，B/D 分别剩 3/4 次；这些余量不足以据现有证据安排完整的新四路验收，不自动用满。原 33 个历史请求未改。

**证据与下一步：**[统一复核](output/data-agent-live-20261015/continuation-fix/extended-verification.json)；[Sonnet 最新部分交付](output/data-agent-live-20261015/D-sonnet-openai/request-bound-run/result.json)；可运行入口见 [本地开发说明](docs/LOCAL_DEVELOPMENT.md)。先 review 模型为何跳过 schema/记录/计算、state 与 deliver 重复提交造成的多轮校验失败，再决定下一批修改和实跑；这属于待评审项，尚未批准简化契约、放宽验收或增加次数。Goal 未标完成。

**只读定位补充：**Sonnet 最新 6 次实际 HTTP 请求均带 8 个工具，实际 system prompt 明确要求 `query_records` 计算；均 HTTP 200、tool_calls 正常结束且输出未达到 4096 上限。最早偏差是只调用 find_assets/search_asset 后便提交 partial，随后 3 次纠正 state/deliver 消耗 $0.311986，占该次实跑报告费用约 59.3%。首请求 59,585 字节中工具定义占 55,553（93.2%），公共状态定义在各工具中共重复 27,832 字节；这是接口开销的直接证据，不是模型质量下降的因果证明。验收侧从同一原件取两条记录调用当前计算器，得到 2.02%；未把答案/记录选择传给产品 Agent，也不计自主链通过。建议 review 的具体方案已写核心设计 14.17.11，尚未修改生产契约或 prompt。本次新增真实调用 0，账本仍为 73 次。

以下为此前记录，仅保留当时状态、原失败和证据入口，不代表当前仍可按旧额度/目录重新执行。

**最新授权与执行（2026-10-15）：**用户明确选择“允许调整，继续完成四路验收”：原批次累计 $3、每路 20 次、整批 80 次，不自动用满或充值。追加入口已通过 4 项行为检查（含两处受控中断）和 14 项既有批次回归，保存授权与旧额度/停止记录；新上下文复用唯一账本，旧 33 个请求逐项与原证据相同。额度变更后已报告费用/预留不变、剩余 $2.16029964。当前从 A 开始串行运行，未标任何路径完成。新 manifest：[extended-batch.json](output/data-agent-live-20261015/extended-batch.json)；授权与复核：[allowance-extension-verification.json](output/data-agent-live-20261015/continuation-fix/allowance-extension-verification.json)。同时补清模型可见的元数据短语 query、成功空结果也提交计划、AssetRef 不可拼成 ResultRef；未改变检索/引用校验语义或四份 system prompt。

**恢复执行（2026-10-15）：**当前源码普通重装，7 个修复模块与安装包逐字节一致；验收后新增注释的语法树与原通过版本相同。按恢复的原 goal 串行执行 A、D，新增 7 次真实请求且全部 HTTP 200。A（OpenAI Agents＋DeepSeek）新增 5 次：能根据反馈修正材料类型并找到年报，但重复提交旧计划版本，随后把资产 ID 拼成未登记的证据 ResultRef，被明确拒绝；达到累计 10 次，未取数、计算或交付。D（OpenAI Agents＋OpenRouter Sonnet/Anthropic）新增 2 次：没有工具错误，第二次找到年报；第三次请求在派发前因费用预留不足被拒绝。两路首次自然语言资产 query 都未命中，实际 find_assets 仅对元数据作短语检索，query 字段尚未说明该边界。当前真实执行未到 search_asset，因此不能把分页离线验收升级为真实业务通过。

**费用与下一步：**A/B/C/D 累计 10/10/10/3，共 33 次；无在途或未知传输。响应报告累计收费 $0.16685756，未核账全额预留 $0.6728428，剩余 $0.16029964；本轮 Sonnet 响应收费 $0.109454，DeepSeek 用量保守估算 $0.032616（非实际账单，原预留未释放）。A/B/C 请求上限已用尽，D 下一请求所需预留超过余额。未重置账本、扩大次数或增加额度。下一动作是确认是否追加本批原累计上限，并在再次实跑前处理已定位的资产 query/引用类型说明缺口；原 goal 不标完成、不进入来源/PDF/工作台。最新证据：[恢复实跑复核](output/data-agent-live-20261015/continuation-fix/resume-verification.json)、[A 结果](output/data-agent-live-20261015/A-deepseek-openai/tool-contract-run/result.json)、[D 结果](output/data-agent-live-20261015/D-sonnet-openai/tool-contract-run/result.json)。

以下为此前限定修复及原运行记录，保留当时的验收范围和费用状态。

**本次 fix（2026-10-15）：**按用户“优先 fix”完成共享工具必要修正。两套 SDK 的 schema/工具说明明确 next_action、需求完整覆盖、计划何时提交；错误反馈返回真实已提交计划及该操作是否受理。material_types 现在指出错误字段/值并列出注册名；已确认原输入 10-K 与目录 official-annual-html 不同。as_of 说明与解释时钟分开：原 Luna 请求自行填入 clock，原任务并无截止日；显式历史截止日的缺证明与越界校验仍保持。

search_asset 新增完整响应 max_bytes（默认 24,000），整条命中及依赖分页，单条放不下返回 ITEM_TOO_LARGE/target/required_bytes 和原位置 cursor，可调整预算继续；改查询仍拒绝、索引变化仍过期。原失败搜索离线重放：摘要模式 13,902 字节返回 8 个命中；原完整上下文首条需约 66 KB，默认页明确返回缺口，按所需预算逐页读完 10 个命中，无重复遗漏；旧响应原样重放、88 个旧引用可读。大结果问题不再靠默认返回约 158 KB（本次按 canonical UTF-8 计）的整页处理；单页控制不保证整个模型历史一定低于传输上限。

**验收与下一步：**30 项不同检查通过（24 项受影响既有查询检查、4 项本轮行为检查、两套当前 SDK 各一条本机合成功能链）；原 Luna 6 次工具调用原参数离线重放，非法输入仍拒绝，错误说明/实际计划状态正确。7 个生产模块普通安装后与源码 hash 一致。真实模型新增 0 次、费用新增 0，原账本未改；模型能否利用新说明完成业务尚未实测。下一步只做一条真实功能回归，再决定其他路径；原次数/总额度本批未调整，四路 goal 不标完成。不进入来源/PDF、工作台或生产。证据：[修复验证](output/data-agent-live-20261015/continuation-fix/tool-contract-verification.json)、[原案例离线重放](output/data-agent-live-20261015/continuation-fix/tool-contract-replay-final.json)；命令见 docs/LOCAL_DEVELOPMENT.md。

**本次结果（2026-10-15）：**用户明确要求预算处理从简并放行。已在原账本将两笔完整 404 记为“保留全额预留后继续”，$0.0921616 未释放、实际收费仍未核实，不再阻塞新请求；没有新账本、额度或通用绕过开关。9 项必要检查通过，包括当前 OpenAI Agents SDK 的本地完整工具链；当前安装包与源码一致。随后 Luna 新会话真实执行 6 次，全部 HTTP 200 / OpenAI 上游，响应报告费用 $0.00783161。实际执行到 find_assets（partial，历史截止日缺证明）及 get_asset_schema（ok）；未完成取数、计算或交付。前 4 轮分别在 next_action、需求覆盖、筛选名称和未提交计划上报错，随后原 lane 累计达到 10 次而停止；不把连接成功当业务通过。

**上一轮停止位置（历史）：**当时待补齐模型可见的任务状态/工具参数契约及搜索分页，当前限定修复见顶部。原批次累计 A/B/C/D=5/10/10/1，共 26 次；已核费 $0.05740356，未核费保留预留 $0.5298799，剩余 $0.41271654，无在途。证据：[预算放行及复核](output/data-agent-live-20261015/continuation-fix/reservation-retention.json)、[Luna 实际结果](output/data-agent-live-20261015/C-luna-openai/current-sdk-run/result.json)、[请求和工具记录](output/data-agent-live-20261015/C-luna-openai/current-sdk-run/evidence.json)。四路完整功能验收仍未完成。

**本轮实现（2026-10-15）：**用户要求继续后，已增加 `live_function.py prepare-attempt`：保留原批次/原会话，登记当前 profile 的新会话；复用原账本、原 lane 和计数，不迁移旧 SDK 状态、不新建额度。新版配置仅允许既已确认的 SDK 版本、并行调用参数省略及 Claude 工具结果阈值变化，问题、材料范围、prompt、模型路由及限额保持。5 项新增行为检查及 14 项既有批次检查通过；两套当前 SDK 各完成 8 请求合成工具链和有效计算交付，旧结果、旧请求及累计费用保留，单一账本不增加。初版合成历史响应缺少 object/Content-Type，被正确判为不完整，修正 fixture 后受影响 4 项通过；原失败日志保留。

Luna 新会话已准备：[current-sdk-manifest.json](output/data-agent-live-20261015/C-luna-openai/current-sdk-manifest.json)。实际批次的当前 profile 准入通过；旧 manifest、旧 C 会话及账本原始字节均未改变。`run` 在读取凭据、创建 worker/工作目录前明确拒绝两笔未核账的 404，因此本轮新增真实模型调用 0。原累计 20 次及剩余额度 $0.42054815 不变，B 仍停止。普通重装后 6 个变更模块与安装包 hash 一致；证据：[new-session-verification.json](output/data-agent-live-20261015/continuation-fix/new-session-verification.json)。完整真实业务验收未完成；共享搜索分页仍未实施，原件/PDF 不在本轮。

**最新决定（2026-10-15）：**用户确认保持并使用新版 SDK。已核对主环境、主锁及四份当前 profile 一致：OpenAI Agents 0.24.0、OpenAI Python 3.31.0、Claude Agent SDK 0.2.167；无需再次升级或兼容恢复旧 SDK 会话。后续按当前配置启动新会话，旧运行仅保留追溯，费用和请求次数继续累计。当前阻拦来自项目的冻结批次绑定，不能称为已证实的官方 SDK 跨版本不兼容；新会话接入原账本的入口尚待实现。本次确认及核对未新增模型调用，未增加预算或次数。

**停止位置复核（2026-10-15）：**上一轮完成 Claude 阈值实现及验证，属于实际进展；本轮重新读取原 goal，并通过现有 `live_function.py inspect` 及只读准入检查确认：累计 A/B/C/D 为 5/10/4/1，共 20 次，全部已响应、无在途，任务剩余额度 $0.42054815；四条路径均无完整业务验收通过。四份当前 profile 仍被旧冻结批次拒绝为 `RECOVERY_REQUIRED`，B 另有 `native_max_turns` 停止状态。阈值验证对应源码 hash 未变，两个既有独立审计 Agent 均已结束，无需等待运行中的任务。此前提出的搜索分页及同账本新执行版本决定连续未解决；可独立完成的范围内修复已交付，未获该决定前不扩大实现或追加实跑。goal 进入受阻待决策状态，不标完成、不重置额度、不转入来源/PDF；现有证据与命令入口见下方。

**本次范围内交付（2026-10-15）：**依用户选择，通过官方 SDK 的 `ToolAnnotations(maxResultSizeChars=...)` 为当前 B profile 显式设置 **200,000 字符**（默认 50,000；官方最高 500,000）。普通安装包中配置/装配模块与源码 hash 一致；4 项本轮检查及 1 项既有 Claude 正常链回归通过。实际 SDK/CLI 对接本机合成服务：69,085 字符结果默认转文件预览，调高后逐值完整回传；210,085 字符仍转文件。初版测试遗漏 CLI 的 token 计数辅助端点而超时，补齐独立端点处理后原对照通过，原失败保留。证据：[claude-inline-verification.json](output/data-agent-live-20261015/continuation-fix/claude-inline-verification.json)；命令见 [本地开发说明](docs/LOCAL_DEVELOPMENT.md#四路径真实接入的运行与复核2026-10-15)。这是本地传输验证，新增真实模型调用 0；不等于 B 业务完成。整请求 200,000 字节限制、原次数/费用上限和旧冻结批次均未修改；B 已用完 10 次，未追加实跑。当前仅调整已授权阈值，下述两项续跑扩展仍待确认。

**本次续接（2026-10-15）：**已按原 goal 核对唯一账本及旧冻结批次。补齐 OpenRouter Chat 的 `reasoning_details` 原样回传：从同一会话已消费请求的持久 HTTP 回执恢复，绑定模型/profile 与完整工具调用，最终字节经过原网关准入、预留及 hash/replay 校验；保留官方 Runner，不覆盖 SDK 私有方法。普通安装后 7 项本地检查通过，其中一项覆盖 3 个进程中断位置；每个恢复案例均完成 8 次合成工具链，签名/密文块完整，未重复 HTTP 或旧工具。新增真实请求 0，累计仍 20 次，余额仍 $0.42054815。真实 Sonnet 多轮推理与完整业务交付未验证。代码：[薄适配](src/uteki/data_platform/agent/providers/openrouter_reasoning.py)；证据：[verification.json](output/data-agent-live-20261015/continuation-fix/verification.json)。

**前次剩余动作（历史，最新结果见顶部）：**新会话接原账本的接线已完成，当时仍需处理两笔完整 404 的未核费续跑准入；本次已按用户决定放行并保留 $0.0921616。共享搜索的显式返回字节预算/分页仍为待确认提案，具体方案见核心设计 14.17.11；A 的 167 KB 搜索结果问题仍在。B/C 已达原 10 次上限，A/D 分别余 5/9 次。未扩大预算、放宽验收或进入来源/PDF。

**前次测试（2026-10-15）：**用户要求测试其他模型，本轮按已有配置串行测试 OpenAI Agents SDK + Sonnet 5.5/OpenRouter/Anthropic、OpenAI Agents SDK + DeepSeek 官网直连，各 1 次真实 POST，无重试。两侧均 HTTP 200、返回 find_assets、实际工具参数通过契约 schema 校验，原生 Runner 停在审批点；业务工具执行数 0，不记完整功能链通过。Sonnet 使用省略 parallel_tool_calls 的候选参数，已同步当前 D profile；DeepSeek 保留原参数。独立 prompt、8 个工具和严格路由均保留。Claude SDK + DeepSeek 已耗尽原 10 次上限，本轮未新增；Terra/Sol 未纳入本轮。证据：[本轮测试](output/data-agent-live-20261015/other-model-probes/verification.json)。

Sonnet 本次响应报告费用 $0.047068；DeepSeek 按峰值非缓存价估算 $0.0049845（非账单，完整保留 $0.0243918 预留）。原账本累计 20 POST，已核实 $0.04957195、未知预留 $0.0921616、完整 usage 未核费预留 $0.4377183，剩余 $0.42054815。Sonnet 本次没有返回 reasoning_details，旧多轮回传反例仍未解决。**下一动作：**review 后沿用原额度继续一条真实工具→结果→交付链；不得将首轮或 schema 通过记作工具已执行、业务已完成，旧冻结 SDK/profile/批次不改写。

**前次修复（2026-10-15）：**按用户要求结合 OpenAI/OpenRouter 官方文档，用原 prompt、原业务输入、8 个工具、同一模型和 OpenAI 严格上游做两次对照：仅省略 `store` 仍在参数筛选返回 404；再仅省略 `parallel_tool_calls=false` 后 HTTP 200，真实模型返回 `find_assets`，官方 Runner 正常停在工具审批点。已将省略参数显式冻结到 Luna profile（`parallel_tool_calls: null`），使用 SDK 原生 `ToolExecutionConfig(max_function_tool_concurrency=1)` 保持本地串行；没有关闭 `require_parameters` 或切换上游。普通重装源码后请求与成功请求逐字段一致，29 项相关检查最终通过。**请求兼容已修复，完整真实业务链仍未验收**；没有执行该真实工具或追加第三次请求。证据：[原请求修复](output/data-agent-live-20261015/C-luna-openai/agent-request-fix/verification.json)；代码：[请求装配及原生串行执行](src/uteki/data_platform/agent/openai_runtime.py)。

本轮成功请求报告 $0.00249595；新增 404 未知费用保留 $0.075。原账本累计 18 次 POST，已核实 $0.00250395、未知预留 $0.0921616、DeepSeek 完整 usage 未核费预留 $0.4133265，剩余 $0.49200795。旧 batch/profile、失败及账本不改写；下一步是 review 后按当前 profile 接续 Luna 工具→结果→交付验证，沿用原账本，不能直接恢复不匹配的旧 SDK 会话或重开额度。

**前次最小诊断（2026-10-15，用户单独授权一次）：**官方 OpenAI SDK 直接向 OpenRouter 发 `openai/gpt-5.6-luna` 最小请求（短消息、max_tokens=64，无工具/推理/provider 筛选），**HTTP 200、2.793 秒、返回 OK，实际上游 OpenAI**。输入 10 / 输出 5 tokens，响应报告费用 $0.000008，已计入原账本；当时累计 16 次 POST。当前网络、凭据和基础模型接入通过，当时原完整参数组合的 404 仍待逐项隔离，不标为业务链修复。原 404 第二次核费仍无记录，$0.0171616 继续未知并保留；其余路径未恢复。代码：[最小探针](scripts/data_agent/probe_openrouter_minimal.py)；[结果](output/data-agent-live-20261015/C-luna-openai/minimal-probe/result-reconciled.json)。下方保留这次诊断前的批次状态。

**本轮目标（2026-10-15）：**四条 SDK/模型路径使用同一官方材料完成真实功能链；整批 $1 硬上限、$0.80 预警，每路最多 10 次/总共 40 次物理请求。本批已执行 15 次外部推理 POST，其中 DeepSeek 14 次返回模型响应、OpenRouter 1 次路由 404；没有完整业务案例通过。按用户停止点交付，不自动进入 Prompt 5/PDF 或重开实跑账本。

**实际结果：**A（OpenAI + DeepSeek）4 次响应后，本地拒绝 231,228 字节的下一请求（上限 200,000）；B（Claude + DeepSeek）10 次后达到原生轮数限制，宿主收尾为 partial，未完成计算及有效交付；C（OpenAI + Luna/OpenRouter）路由参数筛选 404，账单查询仍未确认；D（OpenAI + Sonnet/OpenRouter）0 次，受同批未知账单阻塞。认证有效，现有余额足够，无需为本轮充值。完整证据和边界见核心设计 **14.17.11**、[verification-final.json](output/data-agent-live-20261015/verification-final.json)。

**版本与官方依据：**依用户要求先查官方文档/发布，再升级主环境至 Agents SDK 0.24.0、openai 3.31.0、Claude Agent SDK 0.2.167 / CLI 2.1.300，同步主锁及当前 profile。升级后 32 项本地行为检查通过，但两轮合成探针仍观察到 OpenRouter `reasoning_details` 丢失，兼容检查未通过，不当作 SDK 升级已修复。M0 保持原独立锁用于历史复现；旧批次、版本、原始失败与费用保留。

**暂停后的下一动作：**先 review 本批实现与结果，再确定一小批修复：工具结果大小/契约可发现性、OpenRouter 参数路由及推理字段原样回传。C 的未知核费和剩余预留继续沿用同一账本；不得以换 SDK、新 profile 或新 goal 重置费用与请求数。下一阶段来源发现和 PDF 仍未开始。

核心文档：[DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md](docs/DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)；接口：[DATA_AGENT_API.zh-CN.md](docs/DATA_AGENT_API.zh-CN.md)。

**后续执行原则（2026-10-15）：**用户要求功能跑通优先、验收轻量，提供可直接运行的 Python 命令和结果；默认一条正常链及必要反例，按变更影响回归、复用环境。规则已写入 AGENTS.md；当前可运行入口见 [本地功能 review](docs/LOCAL_DEVELOPMENT.md#data-agent-轻量功能-review2026-10-15)。本次复跑存储示例及两侧正常 SDK 链均通过，仍为合成响应、真实模型调用 0。

**模型与费用方向（按最新要求修正）：**用户已确认 OpenAI Agents SDK + DeepSeek、Claude Agent SDK + DeepSeek 均走 DeepSeek 官网直连；OpenAI Agents SDK → OpenRouter → GPT-5.6 与 Claude Sonnet 5.5。Sonnet 不再被默认分配给 Claude SDK。GPT 默认候选为 `openai/gpt-5.6-luna`，Terra/Sol 按需验证，不默认全部齐跑；各模型/SDK/角色使用独立 prompt/profile。当前已补 DeepSeek 直连薄适配并实跑；两个供应商账户分别核算，任务总预算不按供应商或模型组合倍增。DeepSeek 不支持的可选能力明确跳过，核心工具调用/结果回传/有效交付不可跳过后仍记整条路径通过。当前全部真实路径仍未完整验收；规划矩阵、跳过边界见核心设计 14.17.10，实跑结果见 14.17.11。$1 总上限、$0.80 预警已由本轮 goal 授权；两家现有余额可用，无需为本轮充值。

**剩余任务 review：**核心设计 14.1.8 已按“业务 → 原子能力 → 当前缺口 → 最小完成观察 → 分工”整理 Prompt 4–14。建议恢复时采用一个主 Agent + 最多两个开发 subagent：主 Agent 先固定必要共用接口并负责 SDK/预算/最终集成，来源 subagent 做 P5.1，PDF subagent 做 P6.1，再分别补 API 和表格。当前 HTML Locator/reader 与旧模型契约是需要先处理的接入点；不从头重写。此次只完成评审与文档更新，未启动 subagent、付费调用或后续业务开发；下一动作仍由用户 review 后确定。

| 工作 | 完成情况 |
|---|---|
| 开发环境可复现 | 已完成主环境/M0 分离与干净安装核验，14.12.8 |
| 第一批：原件存储与输入清单 | 已完成限定验收，14.12.9 |
| 第二批：目录、快照与发布恢复 | 已完成限定验收，14.12.10 |
| 第三批：官方 HTML/iXBRL 材料链 | 已完成两份真实材料、行为验收及文档收尾，14.12.11 |
| M0 两套 SDK 接入 | 离线部分完成；真实模型/网关/工具循环未验收 |
| 第四批：六工具与可追溯交付 | 原限定验收及 review 记录保留；R1–R4 已关闭，187 项测试与旧格式兼容核验通过，14.12.14 |
| 第五批：双 SDK 离线绑定及运行控制 | 已完成 Prompt 1–2 限定离线验收，七项收尾审计见 14.12.15–14.12.16；真实网关未验收 |
| 第五批：OpenRouter 验证准备 | Prompt 3 的具体契约、独立 profile、请求捕获及合成输入准备已完成；仍不可实跑，见 14.12.17 |
| 第五至七批 | 两套真实 Agent、配套与业务验收、迁移试用尚未完成；路线见 14.1.5 |

**此前暂停位置（本轮已由上方新 goal 接续）：**Prompt 4 本轮非付费工程、限定验收与差异核验已收尾，按用户约定暂停供 review，不进入 Prompt 5；完整 goal 不缩小，完整 Prompt 4 不记通过。宿主监督及同批十场景本机功能检查已完成，但 Claude 实际请求未携带已配置的 `thinking.disabled`，反而携带 `output_config.effort=high`，真实路由兼容性仍有明确缺口。已在真实发送前拒绝此参数偏差，未偷偷改请求、模型或依赖。冻结契约仍不可执行，授权、实际上游和账单未验证。下一动作由用户 review 后决定，不自动恢复。

**Prompt 4 检查点 7：**复用既有 ObservedWorker 和唯一 RunBudget，补齐 DNS/响应头阻塞、宿主总截止与取消监督；九个真实 SDK 故障场景观察到所属进程组清空。双 SDK 的 G01–G05 在一个冻结批次/账本中串行运行，共 40 次合成模型 POST、21 次合成核费 GET，合成收费 $0.40，真实模型调用/费用为 0。66 项不同测试通过，3 项需旧安装包的时钟兼容测试跳过，不计通过。最终两个复用环境各 70 个安装文件与源码一致、依赖检查通过；最后仅增加真实来源的推理参数拒绝检查，重放 20 个已捕获 Claude 请求确认发送前拒绝，其余未受影响证据保留。证据与六项审计见核心设计 14.12.18 和 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-7/verification.json)。四项历史偶发问题、原生配套隔离与真实模型效果仍未关闭。

**验收环境约束：**隔离普通安装用于防止旧包/源码路径假通过；不要求每个检查点新建环境。当前复用检查点 4 的 core-env/sdk-env，只按检查点新增日志、hash 和必要证据。此前重复环境保留待审阅，未删除原失败或兼容性证据；`output` 不是产品代码入口，也不要求正式运行复制该目录。

以下为历史检查点记录；其中“下一动作”“未完成”以各检查点当时状态解释，此前非付费结论以检查点 7 为准；本次真实接入结论以上方及 14.17.11 为准。

**Prompt 4 检查点 6：**Claude 官方 SDK/CLI 已接入同一 HTTP 与持久业务绑定；正常 8 次合成请求、8 次合成 generation GET 完成合法交付，原生工具后真实退出恢复仍为 8 次。未知派发不重发；核费响应落盘后退出只从原字节结算，没有新 GET/模型请求，缺失原生历史仍要求恢复核对。缺身份/账单、工具错误与核费后取消均有证据。同账本观察次数在网络前持久化，最多两次，不重置预留或模型请求计数。111 项不同检查通过（新增 14 项；两类测试侧错误修正后只重放原失败），两套复用环境各 69 个安装文件一致、依赖检查通过。见核心设计 14.12.18 与 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-6/verification.json)。仍是独立合成场景，宿主整体监督、同批十场景和真实网关未验收；真实模型调用/费用为 0，未到约定暂停点。原失败和四项历史偶发问题保留。

**Prompt 4 检查点 5：**OpenAI 官方 Runner/Chat 客户端已接入同一持久绑定和 HTTP 账本。正常场景 8 次合成 HTTP 完成共享工具与合法交付；准备、原响应落盘、工具完成后三处退出恢复仍共 8 次请求。工具错误、取消、usage 缺失/扣留、核费不重发、未知派发、SDK 对象丢失、重建字节改变与未授权入口均有检查。锁定 SDK 包装应用错误导致误记普通失败的反例已按官方资料/版本源码修正并重放。共 71 项不同检查通过（新增 10 项；最终适配器修正后重放其 10 项，61 项未受影响回归保留），两套复用环境各 68 个安装文件一致。见 14.12.18 与 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-5/verification.json)。这些是独立合成场景批次，实际只运行 OpenAI；不等于双侧十场景共用批次验收。Claude、宿主监督和真实网关仍未完成，尚未到约定暂停点；真实模型调用/费用为 0。

**Prompt 4 检查点 4：**持久批次与业务根绑定已完成限定验收：独立业务根/原生 session 共用同一账本；启用后缺失或损坏不重建；初始化和派发后真实退出沿原身份恢复，自己的收尾不改写其他 scope 在途请求。交付层旧路径假设导致的失败已复现修正；合成收费、整批累计与本场景请求数明确区分。累计 323 项不同检查通过，最后交付修正后重放受影响的 310 项；两套复用环境各 67 个安装文件一致，新增 17 项行为/进程测试，原失败保留。见 14.12.18 与 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-4/verification.json)。当前验证的是持久绑定和旧 SDK 回归，尚未完成网关上的 SDK 业务循环及 G01–G05；L2/L3 不记整体通过，未到约定暂停点。真实模型调用与费用为 0，原四项历史偶发问题未关闭。

**Prompt 4 检查点 3：**实际 HTTP 边界与两套 SDK 本机接线已完成限定验收：74 项不同检查通过，66 个普通安装包文件一致。修复关闭连接后隐式重连、HTTP/1.0 响应取消和 EOF 误判；按官方 SDK 实现允许精确的 Claude beta Messages 路径。两侧各一请求、独立 prompt/八个工具 schema/原始字节和同一合成账本核对通过，原失败保留。证据见 14.12.18 与 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-3/verification.json)。未执行业务工具、未调用真实模型；持久 RuntimeJournal/scope 绑定和 G01–G05 尚未完成，L2/L3 不记整体通过。**下一动作：持久绑定批次 scope 与业务根身份，完成两侧规定场景，再按顶部用户约定暂停供 review。**

**Prompt 4 检查点 2：**已补齐检查点 1 缺失的验证报告，并完成原始响应/收费记录模块。HTTP 完整、协议终态和收费分别判断；部分响应在核费后仍保持未知，补回同次完整响应保留原事件；generation 身份冲突与同一账单重复归属明确拒绝。HTTP 长度/编码反例也已修正；本检查点累计 71 项不同检查通过（新增 27 项，最终改动影响的 27 项已重放），65 个包文件匹配，原失败保留，详见核心设计 14.12.18 与 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-2/verification.json)。只使用合成账单和本机 HTTP，未调用真实模型；实际 transport/SDK/RuntimeJournal 接线未完成，L2/L3 不记通过。**下一动作：接入实际 HTTP 请求边界与宿主批次/scope 绑定，再验证两侧 SDK。**

**Prompt 4 检查点 1：**同一 RunBudget 已增加冻结场景清单、场景独立停止、串行派发和按场景恢复；费用/请求总额仍只有原账本。修正首版场景归属缺失可能绕过停止的边界，原反例保留。当前普通安装包 44 项不同检查通过，64 个包文件一致，详见核心设计 14.12.18 与 [verification.json](output/data-agent-gateway-runtime-20261015/checkpoint-1/verification.json)。真实 transport、收费证据及 SDK/RuntimeJournal 接线尚未完成，L2/L3 不记通过；下一动作先实现原始响应与费用证据捕获。未调用模型，原四项历史偶发故障仍未关闭。

**Prompt 3 准备结果：**两侧候选均为 DeepSeek V4.1 Flash，经 OpenRouter；Claude 非 Anthropic 模型路径仍为兼容性实验。全新普通安装的实际 OpenAI SDK 与 Claude SDK/CLI 请求捕获各 1 次，模型名、独立 prompt、八个工具 schema 与 4,096 输出限制核对通过；仅合成响应，未验证网关或真实选工具。冻结五场景/侧、最多 52 个物理请求、十份上下文模板及完整合成原件/附件/处理配置。$3 仅是未授权的停止上限提案；字节估算约 $2.56 不作为硬预留，保守端点上限预留与无法跑完整组时的停止规则已另列。当前进程无 OpenRouter 凭据，余额及是否需要充值未知，认证账户查询与真实推理均为 0。证据：[verification.json](output/data-agent-gateway-20261015/verification.json)，具体限制与原失败见 14.12.17。

**第五批第一步证据：**[verification-final.json](output/data-agent-sdk-20261015/verification-final.json)、[review-final.json](output/data-agent-sdk-20261015/review-final.json)。两侧实际 SDK；Claude 另运行原生 CLI 与本机合成 Messages 服务。7 项 SDK 单测、2 项 native 集成测试（5 场景）、140 项核心单测和 18 项 data-only 进程测试通过，48 个包文件与安装内容一致。主锁只新增 Claude SDK，原版本及 M0 锁未改。原失败全部保留；真实模型/OpenRouter 调用为 0。当前 fixture profile、原生消息边界及差异见 14.12.15，不当作真实业务或配套能力完成。

**第一步 review 对本步的约束：**Claude accepted deliver 后追加一次原生终态交互的问题，已在第二步局部实现中用原生 PostToolUse hook 修正并回归：同一正常 fixture 由 9 次降到 8 次合成请求。SDK 原生配置、未知费用与业务运行状态不能相互替代；原生内置 Skills 仍可出现在 init 信息中，后续配套隔离须实际验证。

**第二步限定离线验收完成：**T5/T6 协议及七项逐项审计见 14.12.16 末尾检查点 16。下方早期检查点保留当时的结果、失败及未完成状态，当前结论以检查点 16 为准；真实网关、账单、完整配套和业务验收仍未完成。

**检查点 16 收尾：**共享 RuntimeJournal 修正持久根取消未被普通恢复/业务动作继承，以及迟到响应/超时覆盖原停止原因的问题；缺少退出观察仍保留 recovery_required，原已接受交付不被后来取消撤销。原安装包四项反例失败及中间修正一项失败均保留。最终包 325 项不同测试通过，新增 6 项；两个普通安装环境各 64 个源码/SQL 文件匹配，旧对象/交付/原生格式、时钟兼容及依赖检查通过。逐项审计和差异见 [checkpoint-16.json](output/data-agent-runtime-20261015/checkpoint-16.json)。四项历史偶发故障未获得原现场因果证明，仍保留；本批结论只覆盖原 Prompt 2 的合成离线、macOS arm64/Python 3.13 本地 POSIX 范围。真实模型/OpenRouter 调用 0，未接生产。下一步只做 Prompt 3 准备，付费准入未通过。

**检查点 4 更新：**普通工具新增返回前持久响应意图，索引 head 发布前保存 generation/manifest 与结果候选；副作用事件写回所属操作。显式 recover=True 可确认原响应/引用，或校验并确认已经可见的同一索引，不重建、不覆盖不同 head。目录同步结果不确定改为 RECOVERY_REQUIRED，避免交给模型当普通可重试错误。真实进程退出覆盖索引意图、head 已切换但 receipt 未保存、发布后、响应意图及响应提交五处；两套 SDK 都能协调原普通响应/索引效果，不新增模型请求，之后仍返回 recovery_required，不冒充原生会话已续跑。246 项测试通过，56 个安装文件匹配，Claude 19 个原生场景，真实调用 0：[checkpoint-4.json](output/data-agent-runtime-20261015/checkpoint-4.json)。下一步继续官方获取/发布的未确认副作用、非终态原生续跑及执行时间核对；完整 T5/T6 和付费准入尚未完成。

**检查点 5 更新：**官方 acquire 现在在请求前保存计划/source-run 身份，逐次保存 receipt，再登记完整输入清单和发布身份。显式恢复只核对本次已移入最终目录的原 snapshot/build，补齐提交确认，保留同一 job/AssetRef、附件缺口与用量，不下载、不重建、不处理其他运行的暂存对象。两套真实 SDK 都通过发布提交前后退出的恢复，保持 1 次合成模型请求及 2 次合成下载。当前包本轮 244 项测试通过（新增 8 项；9 个核心获取退出位置、Claude 21 个原生场景），两环境 57 个包文件一致，旧安装格式读回相同：[checkpoint-5.json](output/data-agent-runtime-20261015/checkpoint-5.json)。检查点 4 的 10 项旧预算/重试回归未重跑，不重复计入本轮。真实模型/网络调用 0。**下一动作：**补齐执行时间核对与非终态继续；已取得但未发布的中断操作仍保留 recovery_required，不能用当前拒绝继续代替完整恢复。完整 API/Catalog 终态与辅助请求覆盖也尚未完成，付费准入仍未通过。

**检查点 6 更新：**原生运行保存单调时钟起点与累计基数；宿主 ObservedWorker 持有真实进程句柄，确认所属组退出后才登记观察。恢复核对归属和同一启动周期，按保守耗时上界扣预算并保留已知下界/依据；退出观察后的人工等待不计时，重复核对不重复扣。两套 SDK 均已验证澄清中断后恢复原问题并继续子任务，根请求共 9 次且预算/时间依据继承。宿主超时可清理本组并强制部分交付；普通运行在无权读取启动元数据时仍可执行，只关闭缺少依据的跨进程时间核对。本轮 252 项测试（新增 8 项）、Claude 22 个原生场景、两环境 58 个安装文件匹配及旧确定性/原生格式兼容通过：[checkpoint-6.json](output/data-agent-runtime-20261015/checkpoint-6.json)。真实模型调用 0。**下一动作：**使用锁定 SDK 的持久状态/原生会话落实一般非终态续跑；未发布获取的继续/关闭、完整 API/Catalog 终态与辅助请求覆盖仍未完成，不把当前澄清后继通过扩大为整个 T5/T6 完成。

**检查点 7 更新：**OpenAI 已接入公共 RunState/approval interruption 的持久状态恢复，SDK 仍拥有循环和轮次；同一请求的已存完整响应可精确读回，prepared 沿原键继续，未知响应不得重发。新执行段归档旧时钟/观察并累计原预算。10 个真实中断位置恢复完成同一工具链，连续两次中断仍共 8 个物理请求；最后工具在 8 次请求上限处完成且不新增请求。本轮 259 项测试、Claude 22 个原生场景、两环境 59 个安装文件及旧格式兼容核验通过：[checkpoint-7.json](output/data-agent-runtime-20261015/checkpoint-7.json)。原 SDK 字段别名/未提供字段的序列化失败已按原例修正；fixture 空参数和请求数断言失败保留。**仍有一项未解释：**openai-resume-3 的 index_after_head 曾拒绝时间观察，三次带现场记录的定点复现及最终整组未重现，不能称该失败已解决。**下一动作：**继续核对该时间失败及 Claude 原生非终态续跑；未发布获取的继续/关闭、完整 API/Catalog 终态和辅助请求覆盖仍未完成。真实模型/OpenRouter 调用 0，付费准入仍未通过。

**检查点 8 更新：**Claude 通过公共 session resume 继续已完整保存工具结果的原生会话，绑定隔离目录、SDK/CLI 和原输入；SDK 实际 assistant 消息、原工具 ID/参数/结果及首个转发请求均核对。第 1、3、5、7 个工具后真实退出均能恢复交付，总物理请求仍为 8，已完成操作不重复；缺失/篡改历史、待执行工具、未知响应和额外 assistant 文本不发新请求，恢复保留根请求上限。首轮误拒原生固定分隔标记的失败及定点诊断保留，现只识别该控制标记，不扩大业务证据。时钟失败新增具体原因与不可变现场，上界不足反例不会清零或降低耗时；早期偶发失败仍未解释。本轮 265 项不同测试、35 个 Claude 原生场景通过；两个普通安装环境各 60 个源码/SQL 文件一致，旧格式兼容核验通过，真实模型/OpenRouter 调用 0。证据：[checkpoint-8.json](output/data-agent-runtime-20261015/checkpoint-8.json)。**下一动作：**补齐原生历史不完整及部分获取/未发布操作的继续或关闭协议；随后统一 API/Catalog 生命周期和辅助请求边界。完整 T5/T6、真实网关与付费准入仍未通过，不重开已完成批次。

**检查点 9 更新：**宿主新增 `resolve_update`：完整冻结输入可沿原计划/recipe/snapshot/build/job 继续本地处理；部分获取可明确关闭，保留原件、收据、用量与在途未知。传输阶段和用量逐次落盘，修正进程退出绕过 finally 的记录缺口。中断恢复不下载、不补造原生历史；封存损坏拒绝重建，已存在最终发布不能被关闭撤销。再次中断、响应提交、旧收据及旧同步耗时下界均有行为证据。两侧真实 SDK 各验证继续/关闭，仍各保留原 1 次合成模型请求、2 次合成下载；Claude 原生工具历史未被伪造。本轮 278 项不同测试、37 个 Claude 原生场景通过；两环境各 61 个源码/SQL 文件与当前普通安装包一致，旧格式兼容通过。证据：[checkpoint-9.json](output/data-agent-runtime-20261015/checkpoint-9.json)。仅合成数据、本地受控传输，真实模型/OpenRouter 调用为 0，未接生产。**下一动作：**继续补齐原生历史不完整时的运行关闭/恢复、统一 RunQueryResult 与 Catalog 生命周期，并核对宿主全流程的计时、取消和辅助请求边界；早期偶发时钟失败仍保留。完整 T5/T6 与付费准入未通过，不据本次宿主操作完成宣称整个原生会话已恢复。

**检查点 10 更新：**普通失败现在先保存不可变运行结果/提交意图，再确认 Session、Catalog 与原生结果，修正中断后原失败结果丢失的问题。新增带版本的 RunQueryResult、只读结果检查和宿主 close_run；原生成功与业务成功分别报告。真实观察退出后可明确关闭缺失历史/未知响应的运行，保留未知费用、传输及 SDK 历史；已有响应或副作用须先协调，不能用关闭掩盖。关闭中断、只读操作放弃、已关闭运行重放和两套实际 SDK 均有证据。迟到的退出观察可核对当前时间并允许澄清后继，原结果对象不改写、根请求数累计为 9。共 299 项不同测试通过；最后的局部时间核对修正单独重放反例及 9 项终态回归，其他检查所覆盖实现未变。两个普通安装环境各 62 个源码/SQL 文件一致，旧格式与依赖检查通过。证据：[checkpoint-10.json](output/data-agent-runtime-20261015/checkpoint-10.json)。真实模型/OpenRouter 调用 0，未接生产。**下一动作：**继续完成宿主启动、恢复及最终收尾的全流程计时/取消和辅助请求覆盖，核对全部 T5/T6 准入；早期偶发时钟失败仍未解释，不据本轮迟到观察修正宣称它已解决。完整 T5/T6、真实网关和后续业务批次尚未完成。

**检查点 11 更新：**真实退出＋延迟恢复＋迟到观察稳定复现了耗时归属错误；现在原进程与恢复宿主分别计时，共同扣入累计时间。恢复宿主在三个提交位置再次退出须有自己的观察；恢复准备超时/取消不发新请求，监督超时停止原根账本；已有终态/提交意图可核对原进程收尾时间，冻结结果字节不变。观察绑定错误拒绝且不改写 head，旧响应确认不降低已记时间。共 305 项不同测试通过（本轮新增 6 项）；SDK 初跑中诊断包装器未透传新增参数导致的六项失败已修正，并在最终安装包上完成 18 项受影响集成复验，原失败保留。两个普通安装环境各 63 个源码/SQL 文件一致，旧格式兼容与依赖检查通过。证据：[checkpoint-11.json](output/data-agent-runtime-20261015/checkpoint-11.json)。仅合成数据/本地传输，真实模型与 OpenRouter 调用为 0，未接生产。**下一动作：**核对运行初始化中断、正常启动/收尾的完整计时与取消，以及当前 SDK 压缩/辅助请求的统一计量或显式禁用；早期偶发索引时钟失败仍没有原现场的因果证明，不能因本轮同类反例修正而关闭。完整 T5/T6 与付费准入仍未通过。

**检查点 12 更新：**原包在保存 native 身份或根描述后退出，恢复均因账本尚未创建失败；现在未启用的新根先冻结空账本发布输入，再禁止覆盖地发布唯一可写账本。显式恢复核对实际退出，保持原 native/root 身份并累计原执行与恢复耗时；已确认启用、损坏或已有本上下文请求的账本不重建。8 个初始化退出位置、受控发布失败、再次中断、确定性澄清后的首个 SDK 子任务和旧格式拒绝重建均有证据；两侧真实 SDK 各通过三个初始化恢复位置，原工具链仍各为 8 次合成请求。当前包本轮 294 项不同测试通过，其中新增 13 项；核心进程初跑中一个测试误把已链接账本别名当独立残留并修改，代码正确拒绝，现已区分未发布残留与账本破坏并完成 9 项定点复验，原失败保留。两个普通安装环境各 64 个源码/SQL 文件匹配，旧交付/原生格式与依赖检查通过。证据：[checkpoint-12.json](output/data-agent-runtime-20261015/checkpoint-12.json)。未重跑的其他历史 SDK 场景不计本轮通过数；真实模型/OpenRouter 调用 0，未接生产。**下一动作：**继续核对 SDK 入口预检、首次运行及最终持久化收尾的完整计时/取消，以及压缩/辅助请求的计量或显式禁用；早期偶发索引时钟失败仍未确认根因。完整 T5/T6 与付费准入仍未通过。

**检查点 13 更新：**旧安装包复现入口预检超时后仍请求、SDK 装配异常未保存结果、结果提交耗时未计入当前时间。现在有效调用从公开入口计时，装配异常纳入收尾；原业务结果保持不可变，提交后另记当前累计时间。计时确认 pending 时只读原结果仍可用，但 SDK 运行须显式恢复、澄清后继不能跳过核对；真实退出观察可确认 pending 及结果后的尾部，结果意图前退出不编造原错误。早期取消原本通过，保留回归。当前包通过证据合计 315 项不同测试，新增 10 项，两环境各 64 个源码/SQL 文件匹配，旧格式与依赖检查通过。核心进程初跑 1 项失败、SDK 集成初跑 3 项失败保留；6 项核心和 3 项 SDK 定点复验通过。其中一项旧 SDK 用例已改为区分只读结果与启动运行；一次核心恢复错误、一次观察归属失败、一次监督超时仍未取得原现场根因，不能因复验通过关闭。证据：[checkpoint-13.json](output/data-agent-runtime-20261015/checkpoint-13.json)。真实模型/OpenRouter 调用 0，未接生产。**下一动作：**补齐宿主全流程准入/取消与辅助/压缩请求审计，并追踪上述观察/时钟不确定性；早期偶发索引时钟失败继续保留。完整 T5/T6 和付费准入未通过。

**检查点 14 更新：**原包复现适配器吞掉取消后仍完成工具链，以及重复取消打断宿主收尾。现在宿主先停止同一根账本，再向原 SDK 任务发送一次取消；重复取消和加入同一运行的调用者等待同一持久结果。Claude 原生自动压缩的实际 Messages 请求已验证共用额度；压缩完成后耗尽、压缩响应处重复取消均不追加请求。传输反例覆盖重试、错误模型/输出限制、非允许端点和取消后的迟到响应。当前包 268 项不同测试通过，新增 7 项；两环境各 64 个安装文件匹配，旧格式与依赖检查通过。一个新增测试误取顶层 usage，已按既有 delivery.usage 契约修正；探索探针及全部失败记录保留。证据：[checkpoint-14.json](output/data-agent-runtime-20261015/checkpoint-14.json)。只验证当前离线装配及物理请求边界，不代表压缩后的业务质量或原生配套完成，真实模型/OpenRouter 调用 0。**下一动作：**完成正式宿主准入、监督退出及断连/显式取消的接入验收，继续诊断原观察/时钟不确定性；不能把本轮恢复回归通过当成历史故障已解决。完整 T5/T6 与付费准入仍未通过。

**检查点 15 更新：**DataService 新增显式注入的异步 run_query；两套真实 SDK 共用既有运行、取消、澄清与恢复机制，无默认模型或新循环。宿主入口计时、并发等待者取消、进程退出和监督超时均通过；超时 fixture 在派发登记后、实际 HTTP 发送前阻塞，保留原未知请求并强制部分交付，不声称已发送真实请求。另由旧安装包稳定复现 macOS 父子进程时区不同导致合法时钟观察被拒绝；新 clock 用版本化数字启动信息，原生及恢复宿主跨时区可核验。旧 worker、旧宿主写出的观察仍按 v1 读取，不改写旧 clock；不可核验的旧跨时区记录及未知版本拒绝。当前包 297 项不同测试通过，新增 18 项；两环境各 64 个安装文件匹配，旧格式及依赖检查通过，Claude 13 个原生报告会话。证据：[checkpoint-15.json](output/data-agent-runtime-20261015/checkpoint-15.json)。真实模型/OpenRouter 调用 0，未接生产。**下一动作：**按原 T5/T6 七项要求完成逐项收尾审计，明确已验证范围和仍阻塞准入的缺口；正式 CLI/MCP 信号映射留对应入口批次。四项历史偶发故障仍缺原现场因果证明，本次时区修正不自动关闭。完整 T5/T6、真实网关及业务验收尚未宣告通过。

| 收尾项 | 已验证结果 |
|---|---|
| R1：同步时限与取消 | 共用剩余 deadline，覆盖预检、查询、获取、索引与发布；原 1 秒慢获取案例不再请求附件或发布。已提交/不确定副作用显式保留。 |
| R2：有效标题修订 | 发现展示和 FTS 使用当前标题；candidate/conflict 不采用；原件、修订历史与旧交付保留。 |
| R3：上下文创建恢复 | 使用现有 Catalog 登记与 ContentStore 保存创建意图，显式 recover=True 完成创建；第一控制文件/head/映射写入失败及四个真实进程退出位置（含原子写入临时文件残留）恢复原身份，未确认目录同步会重做确认，损坏已完成状态不重置。 |
| R4：相关性排序与分页 | 两种 FTS5 分词器按各自排名合并，同分按完整引用；硬过滤保持，分页无重复遗漏。目录候选/排序冻结，readiness 是读取时实时状态。 |

**验收证据：**[verification-final.json](output/data-agent-review-fix-20261015/verification-final.json)、[review-final.json](output/data-agent-review-fix-20261015/review-final.json)。新建主锁 data-only 环境并强制普通安装当前源码；140 项 Data 单测、18 项进程测试、29 项旧获取链回归通过，共 187 项（本批新增 16 项，其中一个进程测试覆盖四个创建中断位置）。49 个源码/SQL 文件与安装内容一致；旧安装包生成的合成上下文、引用与交付由新包读回，交付内容相同。仅合成数据与受控传输，模型/真实网络调用为 0；未提交、推送或部署。

**后续准入：**第五批先接入两套官方 SDK 原生工具/运行机制并做离线契约测试；保留各模型独立 prompt/profile。强制部分交付、澄清继续、SDK 取消/恢复、T5/T6 与费用对账仍需后续实现/冻结；真实模型/网关准入未通过，须另行明确模型、路由、上限及额度。其他平台、真实网络/断电、M0 重跑和完整业务效果本批未验证。

- **第四批原限定验收记录（2026-10-15，后续 review 见上方）：**六工具、原文/表格上下文依赖、记录/Decimal 计算、实际返回登记和不可变交付通过限定验收。171 个不同测试通过（125 Data 单测、17 进程测试、29 旧获取链回归），48 个源码/SQL 文件与普通安装包 hash 一致。两份冻结真实材料核对 71 项返回证据、36 条数值记录、27 个必选表格单元格及交付闭包；M25 无 inline facts，未补造记录。证据：[verification-final.json](output/data-agent-tools-20261014/verification-final.json)、[review-final.json](output/data-agent-tools-20261014/review-final.json)；程序示例：[data_tools.py](examples/data_platform/data_tools.py)。
- **第四批边界：**acquire 仅通过合成受控传输验证权限、获取、发布、403/附件缺失、取消与幂等；实际模型与新增真实网络请求均为 0。无明确 th 的真实表格保留 HEADER_ASSOCIATION_UNCONFIRMED，原表读回通过不替代口径充分性判断。未接生产、提交/推送或部署；其他平台、真实断电、网络文件系统、完整历史业务回归及本批 M0 重跑未验证。任务前副本、原件、失败及各版 gold 保留，未升级依赖或改变前三批存储/解析契约。

- **已确认：**2026-10-14 采纳“重建 Data 核心、底层复用、外围升级”，计入旧代码适配/回归/兼容/退役成本；新 Agent 重新生成数据，首期仅官方来源。D1–D9 原则见 14.16.1；最新检查失败时可返回注明日期和“未确认最新”的旧版本并保留缺口，不重复询问已定方向。
- **最新方向：**用户再次确认保留 OpenRouter 适配以便换模型；OpenAI Agents SDK 与 Claude Agent SDK 及各自原生配套继续保留。优先用 DeepSeek 验证链路/功能，业务效果验收另行冻结。官方直连兼容不等于经 OpenRouter 已接通，结论与独立 prompt/模型配置边界见 14.17.8。共享 Data 核心，不重写通用 Agent 框架。
- **新增确认：**不同模型各自维护、调优并冻结 system prompt 正文与版本；业务规则共用，不把 A 模型优化后的同一份提示词直接套到 B 模型。模型切换缺少对应 profile 时显示未配置/未验证，不静默复用。设计细则及比较约束见核心设计 14.17.6。
- **按任务选模核对（2026-10-14）：**用户要求强模型/性价比模型分工，并要求立即验证。原生 Claude SDK/CLI 对本地合成网关的 12 个请求已验证：`opusplan` 会切模型但沿用同一 system prompt；独立模型/会话可分别装配 prompt。直接网关模型 ID 会在本次案例丢失 effort，官方 `modelOverrides` 配置已恢复推理参数并回归原例。证据与策略见核心设计 14.17.7；0 个真实 OpenRouter/模型调用，不当作网关或业务验收通过，不自动扩展混合模型实跑。
- **已完成准备：**核心设计 7.8 已将 BC01–BC14 逐组对应到真实材料或明确缺口，形成 8 条正常问题草稿、验收侧候选事实/出处及离线核验记录。9 份目标原件/响应的 hash、8 项 API/iXBRL 数值、12 处 HTML 上下文及 5 项计算已核对；这不是正式 gold、Agent 成绩或完整业务通过。
- **用户 review 结论（2026-10-14）：**单独看问题的案例表达与交互方向 OK；工作台整体仍需优化/设计，后续单独调整，本轮不继续扩展界面。该认可不扩大为完整工作台定稿、全部业务标准冻结或真实系统验收通过。
- **证据入口：**[问题草稿](output/data-agent-acceptance-20261014/questions.v1.json)、[验收侧证据](output/data-agent-acceptance-20261014/candidate-evidence.v1.json)、[检查记录](output/data-agent-acceptance-20261014/checks.v1.json)。SEC 原两个失败 URL 已通过现有入口恢复，旧错误页和记录保留（7.7.7）；未修改生产下载器。原型及检查留在 7.7.6。
- **M0 离线完成：**[sdk_probe](src/uteki/agents/sdk_probe/)＋[独立 worker 入口](scripts/run_sdk_probe.py)已实现，共同只读 fixture、独立 prompt 草稿及版本/模型匹配、原生事件与交付校验均有代码。OpenAI Agents SDK 0.22.2 / openai 3.13.0，Claude Agent SDK 0.2.166 / 随包 CLI 2.1.299；完整依赖锁定在 [requirements/m0.txt](requirements/m0.txt)。15 项测试和 9 个 SDK 场景通过，证据与运行方式见核心设计 14.12.5。
- **已验证边界：**原 M0 离线场景中，OpenAI 跑实际 Runner＋脚本模型响应；Claude 跑实际 SDK/MCP＋脚本 CLI Transport。新增 14.17.7 运行原生 CLI 并捕获本地合成请求，覆盖模型/提示词/推理装配，未跑真实模型或完整业务工具循环。共享只读工具、错误/非法终态、取消、费用未知、第二条记录和配置边界的原记录保留。只使用合成 fixture/临时账本，未加载真实财报验收答案或修改旧生产运行时。
- **真实接入草案保留：**[live-contract.draft.v1.json](config/sdk_probe/live-contract.draft.v1.json) 与 14.12.6 保留 Sonnet 4.6 候选、两侧独立 prompt/hash、最多 6 个物理请求及 $3 总额度提案；付费未授权/启用。DeepSeek 不复用该草案的 prompt、上游或计价；新增协议核对见 14.17.8。当前进程未配置可用凭据，真实余额未查，不能据此要求充值。
- **完整文件清单已整理：**用户要求开发前列明目录、文件及功能；核心设计 14.1.1–14.1.5 已覆盖共同核心、两套 runtime/OpenRouter、独立模型 prompt、原生 Skills/Memory、配置、测试、验收脚本、旧代码处理与七批开发准入。首批五个 Python 文件现已按 14.3.1 完成契约、实现与限定验收（14.12.9），未接生产；其他文件仍按各自批次推进。
- **前批环境任务（已完成）：**已解决主 pyproject 的 m0 extra 与主锁不一致，以及 M0 通过源码路径注入绕过项目安装的问题；四个 SDK 直接依赖迁至 requirements/m0.in，原 uv.lock 与 m0.txt 字节/版本保持。两套全新环境分别普通安装，依赖、版本、隔离导入检查通过；主环境 42 包，M0 41 包；M0 现有 15 项测试及独立 worker 9 个合成场景通过，模型调用 0。核验平台为 macOS arm64 / Python 3.13.15 / uv 0.12.15；其他平台、完整历史回归及业务验收未运行。证据见核心设计 14.12.8 和 output/data-agent-env-20261014/verification.json，安装入口见 docs/LOCAL_DEVELOPMENT.md。
- **第一批完成与证据：**原件存储/输入清单八项条件已按核心设计 14.12.9 验收。修正显式根、实例重验、I/O 错误和目录同步重试边界；21 项单测、4 项独立进程集成测试与合成示例通过。普通安装仅使用主锁 data extra，五个包文件与当前源码 hash 一致，测试从仓库外以 `-I` 运行，未安装 Agent SDK，依赖检查通过。证据：[verification-final.json](output/data-agent-content-20261014/verification-final.json)。原始失败、旧测试日志和草稿备份保留。普通 sync 曾复用旧 wheel，安装说明已增加强制重装及 hash 核对；未升级依赖、读取生产数据或调用模型。
- **第一批验收边界：**macOS arm64 / Python 3.13.15 / uv 0.12.15；其他平台、真实断电、网络文件系统、恶意并发目录替换及完整历史回归未验证。未实现目录/快照发布、Agent 联调，不把本批完成写成完整 M1 或业务通过。
- **第二批完成：**最小登记/修订目录、不可变快照、build 发布及显式恢复已按 14.5.1 实现；十项条件与 A–I 案例逐项证据见 14.12.10。32 项单测、4 项独立进程集成测试通过；第一批 21+4 项回归通过。修正未知时效被当成确定匹配、恢复遗漏目录同步、JSON 重复 key 被覆盖等机制问题，原失败保留。当前普通安装包 13 个源码/SQL 文件 hash 一致；主锁 data-only 环境 9 包，锁及依赖检查通过，第一批源码/测试和两套依赖锁未变。证据：[verification-final.json](output/data-agent-catalog-20261014/verification-final.json)、[review-final.json](output/data-agent-catalog-20261014/review-final.json)、[合成示例](output/data-agent-catalog-20261014/example-final.json)。未调用模型、接生产、提交或部署。
- **第二批边界与停止点：**仅 macOS arm64 / Python 3.13.15 的本地 POSIX、单 Catalog 排他持有、合成四文件发布格式；真实断电、网络文件系统、其他平台、完整历史业务回归和本轮 M0 重跑未验证。真实解析/业务 Locator、搜索/结构化查询、模型运行恢复及 Agent 联调尚未实现，不记作完整 M1 或业务通过。本批交付后停止。
- **第三批完成：**八项条件及 A–G 案例通过，契约/边界见 14.6.1，逐项验收见 14.12.11。两份官方 HTML 与各两张图片实际取得并冻结；解析、发布、关闭重开和真实出处读回通过。4 处正文、3 张表、12 处数值出现位置的冻结核验点全过；另核对全篇覆盖、13,201 个 Locator、953 个规范化数值及 166 个表格链接，未解释遗漏 0。A24 的 963 个事实中 2 个 nil、8 个 unsupported 明确保留；M25 无 inline facts，不称 iXBRL 回归或盲测。证据：[verification-final.json](output/data-agent-html-20261014/verification-final.json)、[review-final.json](output/data-agent-html-20261014/review-final.json)、[真实材料示例](examples/data_platform/official_html.py)。
- **第三批安装、回归与边界：**34 项本批行为/进程测试及 90 项相关回归通过，32 个普通安装源码/SQL 文件与当前源码一致；原件、旧 v1 产物和原失败保留。只改 3 个已有代码文件并增加本批必要实现，SQL 迁移、前两批测试、依赖声明/锁未变。未接生产或调用模型，未提交/推送/部署。仅 macOS arm64/Python 3.13 本地 POSIX；其他平台、真实断电、网络文件系统、完整历史业务回归及本批 M0 重跑未验证。PDF/OCR、图片理解、搜索/结构化查询、六工具全集与 Agent 联调不在本批；不标为完整 M2 或业务通过。

此前第 2.1–2.2 节的研报解读与持仓风险需求仍保留；风险 Agent 形态、持仓数据来源暂不展开。发现报告 MCP 是已有入口，第三方研报接入按首期官方来源决定后置。

DA-01 获取与储存、DA-02 解析与索引、DA-03 查询与材料交付保留为设计中的模块 ID（对应见第 3.1 节 A8），当前不形成三个并行执行任务。其他历史任务、失败、费用和验收记录不因本次收敛而完成或清零；仅在具体任务需要时读取。
