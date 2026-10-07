# NVIDIA FY2025：系统 Agent 跨公司迁移

[查看业务图](http://127.0.0.1:8769/docs/design/data-agent-acceptance/nvidia-business-revenue-v1/?view=business) · [查看收入图](http://127.0.0.1:8769/docs/design/data-agent-acceptance/nvidia-business-revenue-v1/?view=revenue)

本轮把已在 Alphabet 使用的 Uteki 业务/收入执行入口迁移到 NVIDIA 官方 FY2025 年报。实际调用 Sonnet 5.5，加载冻结 Skill v0.4。原始模型响应保留；工程格式恢复、语义复核与图页另存。当前只覆盖明确选定的业务原文及两张完整收入表，不是整份年报自动解析验收。

## 输入与执行边界

- 公司：NVIDIA；FY2025，截至 2025-01-26；收入单位 USD / million。
- 来源：[官方年度报告 PDF](https://s201.q4cdn.com/141608511/files/doc_financials/2025/annual/NVIDIA-2025-Annual-Report.pdf)，本地原件 181 个物理页；PDF 与派生 HTML 各有独立指纹。[选段与处理说明](input/README.zh-CN.md)。
- 62 个来源块，含 60 段文字和 2 张完整收入表，100 个派生单元格。选入期间、单位和收入确认说明，原表保留其他年度和变化列；验收答案不进入模型输入。
- PDF 表格由本次明确选择的几何适配器处理；全文文字和原始 word 坐标已核对。它是当前原件的受审适配，不是通用 PDF 解析器。
- NVIDIA 曾用于人工参考；本轮不称盲测。与 Alphabet 同时改变公司、来源形态和 Skill 版本，不称纯模型 A/B 或 Skill 单变量试验。

## 两次真实请求

| 项目 | 首次请求 | 精简元数据后的恢复请求 |
|---|---|---|
| 目录 | `run-01` | `run-02-model-view` |
| 请求字节 | 162,352 | 128,691，减少 20.73% |
| 模型配置 | Sonnet 5.5，adaptive / high，max_tokens=16,000，stream=true，600 秒，零重试 | 相同 |
| 传输结果 | 240.744 秒，RemoteProtocolError，完整响应头未收到 | HTTP 200，33.427 秒收到头，95.274 秒完成，end_turn |
| 用量 | 未收到 | 输入 54,286 / 输出 15,702；缓存读写均为 0 |
| 原始格式 | 无正文，不能评价 | JSON 外有 Markdown 代码围栏；严格解析拒绝 |
| 费用 | 未知；$0.555766 预留保留，不能记零 | API 用量按保存价格估算 $0.265592 |
| Trace | `run-ac67332798be4628ba67f66a89d3bfbc` | `run-f617470683d846e4919e31a7794405ed` |

第二次删去重复 PDF 路径/hash 及逐词几何数组，保留全部文字、表格、ID、期间、单位、DOM/hash 和标签缩进。完整溯源仍在原包。[逐字段等价检查](input/source_packet-model-view.manifest.json)与[恢复前冻结协议](protocol-recovery.json)可查。成功接收不能证明体量是第一次断连原因，也没有证明长请求重复稳定。

[两次请求与费用汇总](attempt-accounting.json)：新增模型请求共 2 次；已知估算 $0.265592，另有 1 次未知费用及 $0.555766 预留，已知与预留合计 $0.821358。宿主为恢复选择的合计估算上限 $1.10 不是供应商硬账单上限，也不代表用户曾逐字报出该数字。原 $2 顾问会话账本没有改动。本轮不再追加模型调用。

## 格式恢复与交付

原 [response.txt](run-02-model-view/response.txt) 和 [StrictJSONError 回执](run-02-model-view/result.json)不改写。工程处理只移除整个回答最外层唯一的 JSON 代码围栏，不修字段、不改节点、不补数、不替模型作语义判断。围栏内的内容保持字节一致，之后仍须通过严格 JSON、输出 Schema、范围、证据、目标年度、金额和勾稽校验。

离线核验及派生物化已完成：19 个业务节点、24 条关系、3 张收入图、48 个证据片段、4 个未知项。派生候选由 [derived-01-single-fence](derived-01-single-fence/result.json) 单独保存，并绑定原响应和失败回执。派生处理不调用模型、不新增费用；页面必须明确“模型原始格式失败，工程格式恢复后候选”。模型 Trace 仍指向原失败过程，不伪造一次成功调用。

三张收入图应分别回答：两报告分部的收入、终端市场的收入，以及 Data Center 内 Compute / Networking 的构成。它们是不同维度或不同分母，不能跨图相加。宿主从模型所选原单元格读取金额，财务勾稽不替代业务语义审阅。

## 验收与下一步

[事前验收标准](evaluation/acceptance.zh-CN.md)在模型调用前冻结；[实际语义复核](evaluation/semantic-review.zh-CN.md)另存。原始格式、工程校验、业务证据充分性及用户视觉认可分别评价。

优先收敛本轮业务归组、共享对象和逐声明证据缺口；再把有边界的格式处理接入正式执行流程。Microsoft 的[官方输入准备清单](../2026-10-07-microsoft-business-revenue-preparation-v1/README.zh-CN.md)已经完成，下一轮先冻结正式输入与费用，再真实执行。整文底稿和 Query 保持主线，不用更多模型调用代替这些验收。

实际语义结论：三个收入口径正确；业务图已区分两报告分部、市场及具名产品，Omniverse 的归属和汽车仿真支持保留同一身份。GeForce 节点错并并列产品、多处声明漏绑直接依据、推断关系缺少机器可读状态仍需改善。CUDA 仅在公司清单出现；这不等于事实错误，但尚未验证独立共享对象的查询。审阅者参与了输入准备，不称盲评。

## 实际交付检查

[交付检查记录](evaluation/delivery-check.json)与[图页内容验证](../../../docs/design/data-agent-acceptance/nvidia-business-revenue-v1/verification.json)已保存。7 项格式恢复边界、16 项原页面回归通过；62 条本地链接和精确锚点、实际 Mermaid/SVG 的节点/关系映射、脚本语法、静态 DOM 中切换视图及 19 个节点的点击检查通过。页面 HTTP 200，收到的内容指纹与落盘文件一致。

独立代码审查发现恢复校验器原先未锁定派生产物的语义/采纳状态，现已收紧，另校验 validation.json 完整内容；不会通过修改状态把候选伪装成已采纳。原派生 manifest 的生成代码指纹保留，图页另记后续验证代码指纹。原模型 Trace 仍实际返回 failed / StrictJSONError，派生图没有覆盖它。未做浏览器视觉验收，以上检查也不等于三类业务缺口已修正。
