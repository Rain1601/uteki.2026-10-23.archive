# 公司输入 → 官方原件 → 文档解析验收

2026-10-04。限定范围：已登记 AMD / 台积电，FY2023 起、披露截止 2026-10-04，年度报告及修订。

## 验收口径

输入为公司名称及明确选定的公司目录，入口为正式 `agent prepare`；目录中的公司身份、日期和材料类型取自版本化配置，不包含逐份财报 URL。验证脚本中的预计数量只用于执行后的判定，不参与发现或提取。

- 先在全新原件库自动查 SEC、下载、核对发行人/期间/类型并解析。
- 从索引实际执行字面搜索和全文块读取，核对每份来源归属和所有文件 hash。
- 再由 `agent refresh` 重新检查披露清单，核验并复用原件和解析产物；原缺口须保留。
- 正文解析、表格结构、财务提取、语义核验分别记账。块数与表格数不表示财务完整性。

## 已发现并修正的问题

公司原先只能通过配置路径选择；新增 hash 绑定的登记目录与名称入口，未知名称/身份冲突拒绝。解析器 v0.1.7 修复嵌套表格所属行及混合文字容器中的表格/图片候选；旧版 v0.1.6 不改。数值记录验证失败时不再先写入悬空 evidence。refresh 复用数据集时保留原有解析缺口和阶段状态。

v1 基线已保留：AMD 4 sources / 0 records / 85 orphan evidence，TSMC 3 / 0 / 0。两个 v1 输出均为 prepared_with_gaps；不得当作完成财务提取。

## 尚未验收的能力

AMD 周制年度、TSMC IFRS/TWD 不属于当前通用 inline 财务映射的完整支持范围。TSMC FY2023/FY2024 仍有 item_unresolved，FY2025 仍有 item_heading_ambiguous；全文块搜索可用不等于章节识别完整。图片内容和财务语义没有在本次解析中判定。

限流、损坏副本及部分失败通过故障注入检验；不会主动对 SEC 制造限流。服务器长时间运行、多进程共享限速、任意公司自动登记及后台任务按钮尚未验收。本次调用模型 0 次。

## 真实运行结果

正式名称入口在全新 `official-filings-e2e-v2` 原件库完成下载和解析，无手工报告 URL、无原件缓存输入。两家公司均自动读取已有本地 SEC 联系身份。

| 公司 | 原件 | 首轮 HTTP | 再运行 HTTP | 原文块 | HTML 表格节点 | 财务候选记录 |
|---|---:|---:|---:|---:|---:|---:|
| AMD | 3 份 10-K + 1 份 10-K/A | 5 | 1 | 3,656 | 235 | 0 |
| 台积电 | 3 份 20-F | 4 | 1 | 8,676 | 1,214 | 0 |

两家获取均 `completed`，解析均 `prepared_with_gaps`。所有原件 hash、冻结索引、来源归属和实际搜索/阅读调用通过核验；再次运行原件均为 `reused_verified`，数据集为 `reused`，解析缺口与阶段状态保留。AMD 旧 85 条悬空 evidence 在新版本为 0，旧快照未改写。表格节点包含排版用途，不代表 1,449 张已识别的财务报表。

- [逐公司及逐材料核验](verification-v2.json)。
- [AMD 准备输出](amd-prepare-v2.json)、[AMD 刷新输出](amd-refresh-v2.json)。
- [TSMC 准备输出](tsmc-prepare-v2.json)、[TSMC 刷新输出](tsmc-refresh-v2.json)。
- [验收入口](verify_registered_chain.py)：每个运行的 `.command.json` 保存实际调用与退出码。
- [152 项聚焦工程检查](offline-checks.txt)：合成故障测试、解析/来源范围与评估页读取边界；单独于上述真实 HTTP 证据。

## 查看真实产物

两个 v2 数据集已登记，既有 GOOGL/MSFT 与回放记录保留。服务已在 127.0.0.1:8765 启动。

- [AMD FY2025 现金流表](http://127.0.0.1:8765/evaluation?dataset=amd-annual-v2&tab=blocks&source=source-6df13eb1f493c24b0b041858&type=table&block=block-000685-72f74a2c#block-detail)。
- [台积电 FY2025 现金流表](http://127.0.0.1:8765/evaluation?dataset=tsmc-annual-v2&tab=blocks&source=source-21e60e05a9bf4605d86293e7&type=table&block=block-003360-5036aaf1#block-detail)。
- [页面读取回执](viewer-verification-v2.json)：27 项 HTTP 检查，含 7 个原件响应与哈希、材料/块/数据/运行页、4 个跨公司非法请求拒绝。未执行浏览器视觉验收。

财务行仍为 0。运行页当前只接受 query/review 回放，本次登记没有把 acquire/prepare 变成 UI 任务或完整 trace。服务预检仍保留原有 Alphabet 段落 90 片段 hash 缺口，不影响已独立核验的两份新数据包；未在此任务改写旧片段。

下一步：以真实 DeepSeek 从当前原件发现证据并提取财务候选，独立核验后才判断核心财务包是否完整。
