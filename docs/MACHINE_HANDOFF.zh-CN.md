# 当前接续摘要 · 2026-10-13

**本轮交付：** 用户已授权提交与上传 DS-03-A01。主窗口复核两家公司原件hash、公司／期间、原文证据及模型发现链通过；228项受影响回归及便携离线核心检查通过。代码与相关文档共12件随本轮交付，无关页面改动、私密运行和费用账本不纳入。后台结束时的“未提交上传／不自动提交”边界由本轮明确授权衔接；准确提交号及上传状态以Git和远端核验为准。

**当前重点：DS-03-A01，模型自主发现公司官网材料并调用工具下载、校验、归档。** 用户已授权单个[后台任务](codex://threads/01a130ae-731b-7b53-8d3d-7abee9f4c9bb)，已完成有限交付：可调用获取入口、受影响离线回归及两家公司各1件真实 HTML 独立检查通过。[交付/证据/限制](research/2026-10-12-ds03-a01-delivery.zh-CN.md)。新增估算 $0.0916740＋未知预留 $0.0183402，沿用旧 $3 账本；未提交上传。标准 SEC 披露沿用程序化获取，官网材料按任务有界发现，两条路径复用下载及重复／版本记录。最小任务卡统一放在 [TODO 顶部](../TODO.md)；真实执行先每家公司1–2件、两家公司验证，DeepSeek 任务费用最多 $3，不扩派、不采购、不自动提交。旧 T01 不因本任务自动通过，T02 解析仍未开始。

**保留获取基线：DS-03-T01，台积电 FY2025 年度合并财务包。** 用户要求由公司参数化方法取得材料并重复校验，获取验收通过后再做文本解析。

输入：TSM／CIK 0001046179、FY2025／2025-12-31、截至2026-10-12、显式官方来源配置。范围：SEC 20-F及修订／目录附件／XBRL、官方年报、年度合并财报和20-F镜像。不扩展母公司报表、季度、PPT、OCR。

**已完成：** 冻结官方目录31/31件取得，每件三次真实HTTP200、hash一致；93条不同URL＋请求时刻的原件成功记录，独立hash复核通过。原件公司／期间及主表／附注范围已检查，财务事实逐项正确性未验收。参数化方法支持SHA绑定续取部分记录、错误响应隔离留证、单附件失败不阻断其它材料、显式目录快照；工程回归119项通过。

**403证据：** 原PDF地址同请求方式诊断返回200；旧403无正文，不能确定其服务端机制。r4金融报告／SEC镜像目录403保存Cloudflare managed browser challenge正文。未绕过挑战、改身份或代理；r5仅使用经SHA绑定的原官方目录快照选择和补取，快照不冒充实时发现。

**验收边界：** 冻结目录文件获取与重复已通过，T01整体验收未通过。实时目录穷尽性与IR首次发布日期仍有缺口；文件数、PDF打印日／修改日不能替代这些证据。合并财报前6页为图片型审计／封面页面，未来文本解析须保留格式缺口，未做OCR。T02未开始；获取通过后文本解析已授权，不能跳过前置。

证据：`output/ds03-tsmc-fy2025-method-20261012-r1/verification-r5/verification.json`，SHA `00540ba63df942529a9e543b5cb4651db69f61c3aec4142c05b14f5e53a5c8d7`；`independent-file-review.v2.json`。累计115次尝试／127,181,944响应字节，含DNS失败与诊断；零模型调用，旧失败／原字节／代码快照保留。

**可迁移公开材料：** [台积电FY2025原件包](../data/material_packages/tsmc-fy2025-v1/README.zh-CN.md)，31件原件＋3份官方目录快照、93条原件成功HTTP记录、验收及失败历史；约42MB，原字节与hash不改。公开投影不含本机路径／私密配置，不能冒充原验证文件用于CLI续取。拉取后在包目录运行 `shasum -a 256 -c SHA256SUMS`；原私密运行保留本机。获取代码回归：`.venv/bin/python -m unittest -q tests.unit.test_annual_package tests.unit.test_company_acquisition tests.unit.test_acquisition_transport tests.unit.test_acquisition_recovery tests.unit.test_acquisition_cli tests.unit.test_acquisition_catalog_coverage tests.unit.test_acquisition_explicit_proxy tests.unit.test_quarterly_acquisition tests.unit.test_filing_integrity tests.unit.test_acquisition_replay`。

入口：[方法与验收](research/2026-10-12-tsmc-annual-package-method.v3.zh-CN.md) · [公司配置](../config/company_sources/tsmc-annual-package-v1.json) · [获取方法](../src/uteki/infrastructure/document_sources/annual_package.py) · [TODO](../TODO.md)。CLI显式传公司／财年／期末／截止日；续取传父验证文件与SHA。`--use-frozen-directories`须显式选择，当前目录仍标未验证，非默认兜底。

**当前下一步：** 完成本轮授权的 A01 代码提交与远端核验。后续 T01 仍须独立收尾实时目录及材料可用时刻核验，按原标准通过后才能进入T02。不给无变化的403增加重试，也不重取已经三次一致的材料。

**保留：** 微软Q01／既有原包与协议暂停；台积电IFRS／20-F为独立范围，不追认原US GAAP DS-02完成。历史五年／二十季、FMP Free、E6/E7等在TODO，不自动恢复。Codex直接对接人工，PM为协作方式，轻量任务不委派。

历史入口：[之前摘要](MACHINE_HANDOFF_HISTORY_2026-10-12.zh-CN.md) · [微软Q01](research/2026-10-12-profit-cashflow-query01-contract.v1.zh-CN.md)。
