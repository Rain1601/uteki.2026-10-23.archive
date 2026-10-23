> **2026-10-06：旧页面已退役。** 本目录不再提供独立页面；旧页面及其专用代码、测试已删除。当前使用 [Swiss C 投研前台](../../docs/design/company-workspace-swiss-c/README.md) 和 真实数据工作台（已归档：`apps/review_workbench/README.md`，恢复方法见[归档说明](../../docs/REPOSITORY_RETENTION.zh-CN.md)）。以下文字保留为历史记录，其中旧启动命令与页面链接不再适用。保留的原始素材、来源记录和冻结版本仅用于追溯。

当前前台仍使用本目录的 `catalog.mjs`、`research.mjs`、`brands.mjs`、公司图标与注册表；相关数据测试及品牌导入工具继续维护。

# Uteki 报告工作台原型

本版按确认的双入口结构组织研究：公司与 Manager 多对多；每份报告只属于一家公司与一位 Manager，同一组合可以有主报告和多份专题，各自维护版本。公司入口按 Manager 分组，Manager 入口按公司分组。主入口保持不变；[第 1 阶段阅读样板](reader-v1.html)与[早期工作台](legacy.html)独立保留。

## 运行与入口

在仓库根目录运行：

```sh
python3 -m http.server 8768 --bind 127.0.0.1 --directory apps
```

打开 <http://127.0.0.1:8768/uteki_zero/>。已运行时直接刷新页面。需要 HTTP 服务加载本地图标注册表，不使用 file URL 预览。

首次打开进入明确配置的 Alphabet 公司研究目录，展示所有已覆盖 Manager；Manager 入口首次配置为 North。之后两种入口分别记住所选对象。完整 hash 优先于保存状态；报告路径明确 reportId、作者、公司、版本和入口对象，错误身份显示不可用。旧第 1 阶段链接只通过命名演示映射转换为原主报告，不任意挑选报告。

## 本轮操作

- 左侧在“公司 / Manager”两个入口间切换。公司目录按 Manager 分组；Manager 目录按公司分组，可筛选另一维度；同一分组展示独立主报告和专题。报告数量不把历史版本另算一份。
- 点击报告才进入完整阅读；左侧保留入口选择。回目录恢复筛选、列表位置和原报告焦点；阅读时切换入口仍保留同一份报告及正文位置。
- 六家公司与本地图标不变。报告正文只切换自身版本，主题和作者不会随版本号变化。
- 报告正文连续展开，默认 17px、1.85 行高，提供 16/17/18px 阅读字号和章节目录。滚轮、触控板和方向键保持浏览器原生阅读行为，到边界不换公司、标签或章节。
- “日间 / 夜间 / 跟随系统”切换保留当前对象与阅读位置。EN 只切界面，演示报告原文仍为中文，并有语言标记。
- “比较观点”显示同公司不同 Manager 的两份主报告，各栏选择自己的版本、独立滚动。窄布局依次排列并保留两栏。
- 正文引用进入当前阅读区；返回恢复原公司、Manager、版本、列、位置和引用焦点。直接打开证据链接时按原引用定位。
- 待复核的旧版本保留全部正文、原信息截止和受影响章节；研究中不显示内部草稿。
- 目录“变化”聚合当前公司或 Manager 关联的事件；阅读页“变化”限定到该报告和版本。同一事件影响多份报告只计一次；已读与问题是否解决独立。
- Manager 的“组合与表现”是独立维度，本轮明确显示未接入状态，没有借用旧版样例收益。
- 阅读位置自动保存；“标记此版本已读”需要主动点击，打开或滚动不会替你标记已读。

## 可检查的演示场景

| 操作 | 预期 |
| --- | --- |
| 公司 Alphabet → North 主报告 v2 → 章节 → 引用 → 返回 | 连续正文和正确引用；返回原位置与焦点 |
| Alphabet / North / v1 | 完整历史正文、待复核提示、可定位的受影响章节 |
| Alphabet 主报告 → 比较观点 → 两栏选 v1 | 两种独立判断及各自截止，版本不会被自动替换 |
| 对比页右栏 → 引用 → 刷新 → 返回 | 仍回到右栏原报告与阅读位置 |
| Microsoft / North / v1 → 客户续约引用 | 原文不可用，保留身份、定位和缺口，不补写引文 |
| 公司 Microsoft → Field 分组 | 研究中，无其他 Manager 或公司内容替代 |
| North → Google 筛选 → 云专题 v1 → 返回目录 | 保留筛选和目录位置；专题版本、已读状态不串入主报告 |
| 输入未知公司、版本或跨公司 evidence hash | 明确不可用，由用户主动返回或打开演示入口 |
| 禁用本机存储 → 标记已读 | 显示保存失败与重试；当前页状态保留，不假报持久保存 |

## 数据与边界

`catalog.mjs` 是新的显式命名虚构目录：六家公司、两位 Manager、12 个覆盖关系、5 份独立报告（8 个正文版本）、9 条证据、5 个变化事项。Alphabet North / Field 和 Microsoft North 各有一份主报告；North 的云业务专题有 v1/v2，Field 的产能专题有 v1。其余覆盖关系明确为研究中。三份主报告的旧正文从 `research.mjs` 精确引用，原文件不改。所有判断、引文、日期与发布身份均为演示；未接入真实研究、市场价格、账户或服务端发布。

本机状态键为 `uteki.workspace-prototype.v3`，保存主题、界面语言、字号、两种入口位置、reportId 对应的已读版本及各阅读位置。新 key 不存在时只从 v2 读取主题、语言、字号，不将旧 case 已读状态套到多份新报告；旧 key 保留。浏览器限制、存储满或拒绝访问会提示失败，状态仍在当前页内存中保留并可重试。上一版 `uteki.snap-workspace.v1` 不迁移、不覆盖。

本阶段没有任务执行、模型调用、真实交易、服务端报告修订或发布。Manager 真实组合/收益、行业、完整注意事项与个人笔记仍属于后续阶段；独立页面或旧版入口不代表这些功能已接通。

## 实现与检查

`reader.mjs` 负责页面交互；`workspace-state.mjs` 管理双入口路由与本机状态；`workspace-model.mjs` 校验归属和返回范围；`workspace-shell.mjs` 输出目录与外层导航；`workspace-reader-view.mjs` 输出报告与证据。`reader.css` 提供阅读样式与双主题，`workspace.css` 增加目录结构。`reader-theme.js` 在样式加载前应用主题。

```sh
node --test apps/uteki_zero/catalog.test.mjs apps/uteki_zero/workspace-state.test.mjs apps/uteki_zero/workspace-model.test.mjs apps/uteki_zero/workspace-controller.test.mjs apps/uteki_zero/brands.test.mjs
node --check apps/uteki_zero/reader.mjs
```

检查区分真实 fixture/路由/HTML 结构、VM 模拟的 controller 行为与浏览器视觉结果。自动检查不等同实际浏览器的滚动布局、焦点表现或美感验收；页面默认由用户查看。

## 公司标识与新增公司

**最新要求（2026-09-29）：必须是截图中 TradingView 风格的紧凑 icon，统一圆形容器，公司名称另列；不能缩小完整横向字标代替。** 批量任务及未来新增公司同样遵守 [icon 接入要求](tools/ICON_REQUIREMENTS.md)。当前六家使用对应证券页已核对的 TradingView 600 × 600 原版图标，保存本地并保留第三方来源；旧官方字标归档在 `wordmarks.json`。


公司记录通过 `website` 明确官网域名，名称和股票代码不参与猜测匹配。`brands.mjs` 按域名读取 `assets/companies/registry.json`：已核实的 Logo 标为 `reviewed-logo`，官网自动发现的图标标为 `official-site-icon`，保留下载地址、来源页面、时间和 SHA-256。注册表另用 `presentation: icon | wordmark` 区分展示形式，公司图标槽位只接受 icon。公司列表、详情标题和组合持仓共用这一机制。组合头像继续使用经理缩写，不作为公司 Logo。

新增公司在数据记录中提供例如 `website: 'https://www.example.com/'`，然后在接入流程运行：

```sh
python3 apps/uteki_zero/tools/import_company_brand.py --website https://www.example.com
```

这里的 example.com 是参数示例，并非可用品牌素材。导入工具从调用者指定的官网发现图标并保存本地；无法自动获取时可传入已经核对的官方素材地址和来源页，详见 [导入工具](tools/README.md)。无需修改公司的专属渲染分支。人工核实的 Logo 优先，自动刷新不会把它降级成网站图标。

缺失注册记录、图片加载失败或来源无效时显示中性公司图标，悬浮提示标识暂缺；不会挪用其他公司图标或把首字母包装成真实 Logo。网页运行时仅加载本地资源，不依赖第三方 Logo API 或密钥。

当前接入点是数据导入工具；自动发现不等于已核实品牌身份，也不保证所有官网都能获取成功。生产环境“新增公司”后台还未连接，完整搜索/新增公司 UI 仍是后续工作。当前六家图标的来源见 [素材记录](assets/companies/SOURCES.md) 和 [机器可读注册表](assets/companies/registry.json)。

公司标识检查：

```sh
node --test apps/uteki_zero/brands.test.mjs
python3 -m unittest discover -s apps/uteki_zero/tools -p 'test_*.py'
```
