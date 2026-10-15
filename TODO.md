# 当前动作：第五批第二步——运行控制与 T5/T6

核心文档：[DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md](docs/DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)；接口：[DATA_AGENT_API.zh-CN.md](docs/DATA_AGENT_API.zh-CN.md)。

| 工作 | 完成情况 |
|---|---|
| 开发环境可复现 | 已完成主环境/M0 分离与干净安装核验，14.12.8 |
| 第一批：原件存储与输入清单 | 已完成限定验收，14.12.9 |
| 第二批：目录、快照与发布恢复 | 已完成限定验收，14.12.10 |
| 第三批：官方 HTML/iXBRL 材料链 | 已完成两份真实材料、行为验收及文档收尾，14.12.11 |
| M0 两套 SDK 接入 | 离线部分完成；真实模型/网关/工具循环未验收 |
| 第四批：六工具与可追溯交付 | 原限定验收及 review 记录保留；R1–R4 已关闭，187 项测试与旧格式兼容核验通过，14.12.14 |
| 第五至七批 | 两套真实 Agent、配套与业务验收、迁移试用尚未完成；路线见 14.1.5 |

**当前唯一动作：**第五批第一步已完成限定验收与 review（14.12.15）；按用户连续推进授权，进入第二步 T5/T6：根运行/账本、明确终态、停止、澄清继续与恢复。先固定协议及反例，再实现并验收；不调用真实模型、不接生产。后续步骤按核心设计路线与用户剩余任务逐步 review，不一次启动。

**第五批第一步证据：**[verification-final.json](output/data-agent-sdk-20261015/verification-final.json)、[review-final.json](output/data-agent-sdk-20261015/review-final.json)。两侧实际 SDK；Claude 另运行原生 CLI 与本机合成 Messages 服务。7 项 SDK 单测、2 项 native 集成测试（5 场景）、140 项核心单测和 18 项 data-only 进程测试通过，48 个包文件与安装内容一致。主锁只新增 Claude SDK，原版本及 M0 锁未改。原失败全部保留；真实模型/OpenRouter 调用为 0。当前 fixture profile、原生消息边界及差异见 14.12.15，不当作真实业务或配套能力完成。

**本步 review 对下一步的约束：**Claude accepted deliver 后仍有一次原生终态交互，下一步需落实不追加模型调用的停止；SDK 原生配置、未知费用与业务运行状态不能相互替代。原生内置 Skills 仍可出现在 init 信息中，后续配套隔离须实际验证。

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
