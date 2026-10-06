# T3：MSFT 真实资料与受控工具闭环

2026-09-24。T3 工程闭环已通过：统一协调器和 CLI、获取/物化回调、累计请求限制、取消与不可变重跑；MSFT 官方资料实际获取并入库，数字与 Business 原文通过同一协调器取得。**规划器是 `scripted_fixture`，真实模型调用 0；三家公司 13 道模型 benchmark 仍未运行。**

## 输入、动作与返回

输入为版本化 MSFT/NASDAQ 配置、截止日 2026-09-24，以及用户提供的 SEC 请求身份。未在代码/配置中写入该邮箱。公司 ID 由 SEC symbol 映射解析为 `sec-0000789019`。

| 实际运行 | HTTP 请求 | 原件与派生结果 | 状态 |
|---|---:|---|---|
| [基线准备](/tmp/uteki-t3-msft-prepare-20260924-01/result.json) | 40 | 30 份原件；初次只有 2 个可查询来源、0 条事实 | prepared_with_gaps；原报告保留 |
| [基线原件重新物化](/tmp/uteki-t3-msft-rematerialized-20260924-02/manifest.json) | 0 | 修复 XHTML MIME、HtmlComment 后，13 来源、100 条事实 | 仍有格式/日期/范围缺口；这是中间快照 |
| [指定 FY2025 年报](/tmp/uteki-t3-msft-fy2025-prepare-20260924-01/result.json) | 3 | 按 SEC 发现的 `reportDate=2025-06-30` 取得 1 份 10-K；初次 99 条事实 | 旧解析模式缺 Business 节点 |
| [新解析版本重处理](/tmp/uteki-t3-msft-fy2025-reprocessed-20260924-02/result.json) | 0 | 1 来源、102 条候选事实及出处；1,401 个块、24 个唯一目录节点 | prepared_with_gaps |
| [联合脚本查询](/tmp/uteki-t3-msft-fy2025-scripted-20260924-02/result.json) | 0 | 5 步：计划 → 数字查询 → 目录 → Business 摘录 → 完成 | evidence_ready；语义充分性未评估 |

总计 **43 次真实官方 HTTP 请求，0 次真实模型请求**。获取清单、失败与限额均保留，不将其解释为完整收齐。机器摘要见 [verification.json](verification.json)。本机 `/tmp` 原件和运行目录不会随 Git 分发；换机器需重新获取/验证，不能仅凭本报告当作本机验收。

实际问题：`Provide FY2025 revenue and operating margin plus a Business source excerpt.`

- FY2025：**2024-07-01 至 2025-06-30**，来自原件财年标记和 XBRL context。
- 收入：**281,724,000,000 USD**。
- 营业利润：**128,528,000,000 USD**。
- 营业利润率：**45.62%**，由注册 Decimal 公式计算。
- 数字返回 6 处披露记录和核验引用；相同值的重复披露不会相加。SQL、操作数、计算结果与原文位置见 [query-receipt.json](/tmp/uteki-t3-msft-fy2025-scripted-20260924-02/query/turn-002/query-receipt.json)。
- Business 返回 12 个原文块（含标题/页码），有公司技术业务、AI、产品及服务说明。原文示例："Microsoft is a technology company committed to making digital technology and artificial intelligence…"，定位为 `block-000041-958a7c27`。完整内容见 [读取回执](/tmp/uteki-t3-msft-fy2025-scripted-20260924-02/query/turn-004/feedback.json)。这只是摘录，**未执行 Business 全文阅读或研究结论验收**。

原件：[SEC MSFT FY2025 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)，2025-07-30 披露，SHA-256 `0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。原件表头标为 In millions，引用保留 scale=6；源码包含 2025/2024/2023 列，查询只取 FY2025 的 context。原件字节及旧运行均未改写。

## 真实问题推动的修复

1. XML 声明和注释后的 XHTML 识别为 HTML；旧 MIME 标记保留，新解析类型另存。普通 XML 不冒充 HTML。
2. `HtmlComment` 跳过非内容节点；DOM 原始路径保留。
3. 显式 `sec-source-blocks-v0.1.6` 排除隐藏 XBRL 内容，按真实正文标题建立目录，处理重复页眉和包装容器锚点。Business 范围为块 39–282；Risk Factors 正式标题在块 286，风险页眉不混入前章。其他标题歧义不发布节点，也不并入前章。旧解析版本保持可用。
4. `prepare --from-run` 用冻结原件生成新快照，0 HTTP。解析器/标准化/协议实现指纹参与复用判断。
5. 获取与物化分步提交；新增资料不完整则保留旧 scope。旧未解析附件继续记录缺口，不阻止有效新年报加入。

最终 FY2025 数据集仍有 **4 个其他 Item 标题歧义、1,449 条 unmapped_concept 诊断**，及 SEC 清单的 6 条 invalid_filing_date。只支持已声明的通用 US GAAP 概念、USD 和支持的日期类型，原始分部维度不推测为具名业务。未知概念和资料覆盖保持缺口，候选事实不自动采纳。

## 复现与检查

已有冻结准备目录时，使用 [CLI](../../../docs/DATA_AGENT_CLI.zh-CN.md) 的 `prepare --from-run` 在新目录重处理，再运行：

```bash
.venv/bin/python experiments/data_agent_query/company-coordinator-v1/run_scripted_smoke.py \
  --prepared-run /tmp/uteki-t3-msft-fy2025-reprocessed-20260924-02 \
  --workspace /tmp/uteki-t3-msft-source-store \
  --output /tmp/msft-scripted-new-run --fiscal-year 2025
```

[脚本](run_scripted_smoke.py) 不内置财务答案、company/source/node ID；它按限定目录读取财年，再按脚本步骤调用工具，不能称为自主模型评测。旧失败的 [partial 运行](/tmp/uteki-t3-msft-fy2025-scripted-20260924-01/result.json) 继续保留。

最终全量离线回归 **828 项 Python + 7 项 JavaScript 通过**，[日志](/tmp/uteki-t3-final-offline-checks-20260924.log)。E1–E8 的 57 条 benchmark 命令全部通过，[报告](/tmp/uteki-data-agent-benchmark-v01-t3-20260924-01/report.md)；随后解析修复及协调器增量包含在最终全量回归中。没有做页面视觉验收、真实模型评测、提交或 push。

## 下一步

1. T4 先补 benchmark 的题目/来源/模型绑定导出、初始和最终 scope 及累计逐请求证据；当前通用运行不能直接被评测 runner 接受。
2. 准备好可审核的模型输入和预算配置后，明确新的模型调用额度，先 MSFT 单题，再三家公司 13 题。历史 DeepSeek 46/48 账本不挪用；估算费用与未知真实账单分开记录。
