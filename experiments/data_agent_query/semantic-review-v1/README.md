# 语义检查与 system prompt 的实际迭代

后续排因与 v2 协议实跑见 [新报告](../semantic-review-v2/README.md)。本文保留上一轮 18 次调用的历史结果。

2026-09-24。已实现独立的语义检查协议、system prompt、来源绑定和 benchmark，并实际调用 DeepSeek `deepseek-v4-pro` **18 次，18 次返回**。同一真实输入重跑后，重述期间、分摊对象和 Total 的错误解释得到修正；Cloud 收入重叠已经明确。但分部结果仍存在引用覆盖和缺资料声明问题，**本轮语义验收为 partial**，未自动改值或采纳。

## 输入与实际结果

真实案例使用原 MSFT FY2025 冻结数据：分部表 24 条、Microsoft Cloud 3 条。调用方显式选择记录、检查轴和同源补充段落；补充 Note 1 的重述说明及“合并报表不受本次重述影响”例外。这是经过 Codex 选定范围的质量检查，不是自主发现或全文漏提验收。

独立合成 benchmark 使用 Cedar Instruments 的 12 个小案例，包含 6 个正确断言、5 个错误断言、1 个证据不足断言。模型输入与 [评分标准](../../../benchmarks/data_agent/semantic_review/v1/expected.json) 分文件，评分标准在真实调用前冻结，未根据结果修改。

| 运行 | 请求数 | 实际结果 |
|---|---:|---|
| prompt 01：两个真实问题 | 2 | Cloud pass；分部 partial，发现记录范围过宽、分摊未拆分和 Total 的排他表述错误 |
| prompt 01：12 个合成案例 | 12 | **11/12 pass**；12 条断言的判断均正确，缺资料例的检查轴状态不符合协议 |
| prompt 02：相同两个真实输入 | 2 | 历史 12 条、合并 6 条、收入 9 条、利润 9 条绑定修正；Total 错误消失；分部仍 partial，Cloud 保持 pass |
| prompt 02：相同缺资料输入 | 1 | **1/1 pass**，检查轴及断言都明确为证据不足 |
| prompt 03：相同分部输入 | 1 | 过强历史断言和多余业务细目已去除；引用不充分和错误缺资料声明仍在，保持 partial |

后两版重跑保留相同 packet ID、模型、输出 schema 和输出上限，仅修改模型收到的 system prompt。这里只对已暴露问题做定向迭代；**没有用 prompt 02/03 重跑完整 12 题，不能声称最新版全套 12/12 通过或证明泛化能力**。Cloud 最新 pass 来自 prompt 02，prompt 03 未重跑 Cloud。

## system prompt 中具体改了什么

从笼统的“检查限定条件”改为先检查再作结论：每个请求轴单独返回结果；每条约束必须附精确的受影响记录和原文。比较、分摊、可加总性、维度、地理、数值口径分别处理。

- 限定的期间和指标必须与每个 record ID 一致，历史重述不能套到当年记录；收入分配和公司费用分摊分别表达。
- 不能把不同口径写成互斥类别，例如合并总额也可以等于表内分部汇总。
- “本次重述没有影响”不能扩写成“仍为原始报告金额”，除非确实提供并核对了当年的原始报告。
- 缺失的关键资料阻止判断时，检查轴必须为 `insufficient_evidence`，同时保留已知约束和具体未解决问题。
- 每个结论中的事实都要由该条引用支持；数字相同不等于口径、独立经营属性或可加总性正确。

实际发送的三版文本保存在本机档案的 `system-prompt-01.txt` 至 `system-prompt-03.txt`；当前运行时使用 [SEMANTIC_PROMPT](../../../src/uteki/infrastructure/research_data/semantic_review.py)。每次运行的模型配置也保存完整 prompt 与指纹。

## 仍未解决的真实问题

1. prompt 03 的 Total 约束关联六条收入/营业利润记录，却只引用了 Total Revenue 行。表格本身包含营业利润，但该条证据没有完整覆盖被关联记录。
2. prompt 03 在比较结论中引用了已提供的 Note 1 重述详细段，随后又声称未提供该详细说明。不能将模型自己生成的“缺资料”句子直接当作真实资料缺口。

这两点说明仅增加自然语言约束仍不足以保证输出质量。下一步需要把维度/数值归属的逐记录引文覆盖、以及“资料缺失”声明的来源对象做成可检查条件；通过后再接入 prepare 和下游查询的语义状态。完整来源发现、细粒度补提、全文漏提和跨公司稳定性仍未完成。

独立审查与机器判定均保留版本：[第一轮](real-review.md)、[第二轮](real-review-02.md)、[第三轮](real-review-03.md)，以及对应的 `real-evaluation*.json`。这些是限定范围的独立源文复核，不是全量金融 Gold 标注。

## 工程验证、版本与费用

**52 项定向测试通过**：语义协议/来源绑定、执行器、benchmark 判分及复用的模型/输入重组边界。包含重算所有自有哈希后伪造记录、表格或原 DOM，仍需被真实数据集绑定拒绝的反例。真实运行输入也已按增强的 DOM/原件规则核验；未修改原数据集。没有为这个独立增量重跑全仓回归或页面验收。

18 个响应的上游模型均为 `deepseek-v4-pro`，输入 260,290 tokens，输出 15,995 tokens，保存价目表估算 **USD 0.40692300**。本轮用量均已取得，实际账单未知；前一轮取消请求的未知费用继续保留。本轮独立质量任务的 18 次额度已用完，未挪用历史账本。

机器摘要：[summary.json](summary.json)。完整本机档案：[semantic-quality-v1](../../../data/company_workspace/record_review/semantic-quality-v1/)，包含输入、原片段、评测标准快照、prompt、实现指纹、全部原始响应和失败/部分通过结果。该目录被 Git 忽略，本机保存不等于远端备份。

使用方式见 [CLI](../../../docs/DATA_AGENT_CLI.zh-CN.md#独立语义检查与-system-prompt)，benchmark 准备与评分见 [fixtures README](../../../benchmarks/data_agent/semantic_review/v1/README.md)。这些案例与三家公司 13 道 query benchmark 分开记录，后者仍未运行。
