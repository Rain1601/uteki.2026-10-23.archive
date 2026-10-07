# 02：四家公司原件系统复用验收；NVIDIA 保留获取缺口

2026-10-08。**9 份已冻结年报经现有系统重新核对身份、复用并生成新底稿。在线 SEC 获取尚未执行：本机未配置真实 SEC 联系方式。** 本轮没有网络请求或模型调用，没有修改旧原件、旧清单或旧数据集。

本轮选用 [annual-pilot-catalog-v2](../../../config/company_sources/annual-pilot-catalog-v2.json)，所有输入清单、SHA256 和 source ID 固定在 [inputs.json](inputs.json)。不使用默认公司，不自动替换期间或格式。

| 公司 | 显式材料范围 | 真实系统处理 | 验收结果 |
|---|---|---|---|
| AMD | 2023-12-30、2024-12-28、2025-12-27 年报，含同期间修订，共 4 份 | 原获取 manifest → `prepare_acquisition` → 新冻结底稿 | 4 份身份、原件 hash、新产物 hash 通过；3,656 块 |
| TSMC | 2023、2024、2025 年末 20-F，共 3 份 | 原获取 manifest → `prepare_acquisition` → 新冻结底稿 | 3 份身份及 hash 通过；8,676 块 |
| Microsoft | 2025-06-30 的 10-K | 既有本地原件清单 → 身份核对 → `materialize_sources` | 1 份身份及 hash 通过；1,401 块 |
| Alphabet | 2025-12-31 的 10-K | 既有本地原件清单 → 按年报 profile 选择 → 身份核对 → `materialize_sources` | 1 份身份及 hash 通过；1,338 块；旧清单中的 10-Q 明确排除 |
| NVIDIA | 2025-01-26 的 SEC 10-K HTML | 所选原件不存在；已有官方 IR PDF 不属于本次 inline 身份适配器 | 缺件保留；未用 PDF 假装 SEC HTML 获取完成 |

**统一记录：** [verification.json](verification.json)。各公司 `selection.json` 包含原始地址、形式、期间、内容 hash 与身份验证回执；`verification.json` 包含新数据集位置、范围、遗留问题及完整性检查。AMD/TSMC 额外保留标准 Agent preparation/result/manifest。MSFT/GOOGL 是系统读取已知本地原件，不宣称它们有新网络获取回执。

**复用验收和内容验收分开。** 本轮重新产生 15,071 块；全部选定原件及所有新 manifest 引用文件的 hash 已核对。块数量不证明没有遗漏。底稿仍保留图片仅有引用、部分目录锚点、未适配数值概念、AMD 非日历期间等诊断。数值和语义是否正确由 03/04/07/08/09 继续核验。

## 在线获取的具体缺口

[live-preflight.json](live-preflight.json) 记录真实 resolver 返回 `unconfigured`。已查当前环境、私密 `.env`、显式 profiles 和现存工作区配置，没有可用的真实联系人。不能用离线测试邮箱访问 SEC。

下一步是在私密 `.env` 配置 `UTEKI_SEC_USER_AGENT`（应用名加真实联系邮箱，权限 600），然后用现有获取入口重新尝试 NVIDIA 的官方 SEC 原件。联系方式不会写入本验收页、公开配置或日志。历史 NVIDIA SEC 403 记录继续保留；本轮没有发生 HTTP 请求，不能声称又遇到 403。

02 仍是部分完成：季度/6-K/8-K、附件、业绩发布稿、电话会及 PDF 身份验证不在这组年报 profile 的已验收范围。未刷新 SEC 目录，也不以本次复用证明当前材料全部齐全。

## 05：真实产物、契约和读取入口

[artifact-samples.json](artifact-samples.json) 索引 10 类真实产物，分别给出文件 hash、契约、消费者和质量边界：

- 6 类新解析底稿：原件说明、原文块、目录、定位、资源、索引。使用新生成的 Microsoft 原件底稿，JSONL 按逐行 Schema 检查。
- 财务候选：历史 AMD 系统模型提取；逐条通过 ResearchRecord 类型校验，保留与整份覆盖的区别。
- 精编：Microsoft run-04 的真实修订候选，Schema 通过；最终内容审阅未完成，不能称整项验收通过。
- 业务图草稿：历史 Microsoft 独立版；Schema 通过，但已有内容漏项，不标为合格答案。
- 原文对象清单：run-05 的真实 148 条提及、103 块处置，含一次模型局部修复；精确定位不等于语义无遗漏。

新底稿占约 135 MB，保留在本机并由本目录 `.gitignore` 排除重复数据；可复查的输入、脚本、身份回执与 hash 清单仍保留在 Git 范围内。

这个索引只帮助查看现有真实例子和消费方式。没有新增模型执行，没有将字段合法、模型自检与内容正确合并为一个“通过”。

复查脚本：[run.py](run.py) 和 [catalog_samples.py](catalog_samples.py)。输出采用排他创建；再次实验应选新目录，不覆盖本次验收。
