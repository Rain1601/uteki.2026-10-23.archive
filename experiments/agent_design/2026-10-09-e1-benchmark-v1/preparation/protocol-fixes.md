# E1 通用协议提示修复

日期：2026-10-09。协议版本：`data-agent-decision-v4-payload-guidance`。
本记录是工程诊断和离线检查，不是新一轮模型实测。冻结的第一题结果保持原样。

## 观察到的失败

来源：`runs/E1-02-sonnet-r1/attempt-01/data-query/model/`。
两次均 HTTP 200、`end_turn`、完整响应；不是网络超时或输出截断。

| 决策 | 模型输出问题 | 严格校验结果 | 已知费用估算 |
| --- | --- | --- | --- |
| 1 | `load_skill.payload_json` 编码了 `{"skill":"query"}` 对象；协议要求编码字符串值 `"query"` 本身 | skill 字段类型拒绝；未执行 | $0.046798 |
| 3 | `kind=query` requirement 多带 `source_id` | requirement 字段互斥规则拒绝；未执行 | $0.068948 |

已知费用合计 $0.115746。对应第 2、4 次决策分别自行修正，保留所有原始失败记录。
调用证据：

- `calls/e673ac85-afeb-419a-8386-d597c3c23d95-end.json`
- `calls/edd87cb1-7ead-4c43-9879-ca430140b723-end.json`
- `decision-0001-01-output.json`
- `decision-0003-01-output.json`

## 根因与已实施的通用修复

1. 基础提示给的是主机内部 action/skill 对象示例，原生适配器又要求四字段外层 envelope。
   原生提示虽然已有“只编码 payload 值”的文字，缺少可直接核对的标量例子。
   现在原生模式移除那条主机格式示例，加入真正的标量、数组和无 payload 外层 JSON 示例。
   非原生主机格式继续保留原示例。示例只说明协议形状，没有公司、期间、金额或业务答案。
2. requirement 的字段互斥来自 Pydantic after-validator，不能假设模型从自动 JSON Schema
   得到全部条件。此前错误后已有明确反馈，但首次计划前说明不够集中。
   现在首次协议提示明确每种 kind 所需和禁用的 source_id、node_id、query、
   financial_task_id、batch_index。数字 query 的来源范围由不可变 active scope 约束。

没有放宽任何校验，没有自动剥离包装、删除来源字段、补写查询条件或绕过拒绝。
所有变化作用于新运行；协议版本和请求指纹会记录变化。

## 离线验证

针对性测试读取真实准备请求中的 wire 示例并进行解码和原主机 Schema 校验。
错误的旧包装形状仍被拒绝。独立合成 query 验证多带 source_id/node_id 仍被拒绝，
source_evidence/source_answer 的合法来源字段仍可用。

`tests.unit.test_decision_protocol` 与 `tests.unit.test_claude_decision_envelope`：14 项通过。
这证明提示例子符合工程协议与严格边界保留，不证明模型首次有效率已提高。
后续尚未运行题可观察真实效果，无须仅为此重复付费运行已通过的第一题。

## 上下文体积：只读诊断，未实施缩减

同一旧运行共有 10 次 planner 决策和 1 次 reviewer 调用：

- Planner 输入总计 336,774 tokens，10 次实际请求共 868,769 bytes。
- Reviewer 输入 20,181 tokens；合计输入 356,955 tokens。
- Planner 基础提示 13,672 bytes；完整主机 Schema 紧凑序列化 21,323 bytes，逐请求重复。
- 10 份动态 input 的 catalog 累计 126,320 bytes；loaded_skill 累计 95,112 bytes。
- catalog 每轮约 12,632 bytes，其中 schema 约 7,436 bytes；loaded_skill 含约 11,754 bytes 内容。
- 第 3 轮同时含 loaded_skill 与加载工具观察结果，存在一轮内容重复。
- review-packet 文件 98,118 bytes 是缩进后的磁盘表示；普通紧凑前 JSON 序列化为
  30,083 bytes，实际 reviewer 请求 42,793 bytes。不能把 98 KB 文件大小当实际请求大小。

以上是字节组成诊断，不能按字节比例直接分摊 token；外层 JSON 转义和其他字段也占空间。
主要开销是逐轮重发协议、Schema、目录和 Skill，不能用最终交付 957 字符推断此前搜索成本。

建议顺序：

1. 先用本轮明确的协议提示减少纯格式失败，保持材料质量。
2. 在后续专项中，先消除同一请求里 Skill 本文与工具观察的重复，保持读取记录和指纹。
3. 再评估小目录入口加按需 schema 探查，减少每轮重发无关说明；必须保留公司、期间、
   来源范围与必要字段，验证召回没有退化。
4. 完整主机校验始终保留。若缩小发给模型的动作协议，先做独立协议实验，不一并更改业务规则。
5. 不将 Skill 仅替换为 hash：当前每次决策是无状态请求，hash 本身不能传达规则。
   Prompt cache 可另行评估，但当前计价并未支持任意 cache-writing/server-tool 费用，
   不应为了降本静默开启或假定命中。

这些缩减建议尚未实现，也未产生新的模型费用。

## 后续协议 v5：数字查询现在可显式选择来源

以上 v4 字段限制和14项检查是历史记录。E1-07 暴露多报告同期间数据需要保留版本差异；仅靠全局 scope 不足以分别查询两个披露版本。因此后续 v5 明确允许数字 query requirement 带 `source_id`，并通过目录、活动范围、查询执行、结果封装和最终复核逐层核对；不允许同一行动混合不同来源选择。未指定来源时，原冲突保护仍保留，不能自动挑选一个版本。

E1-07-sonnet-r2 已由系统自行创建两个来源限定查询，一轮交付六条分部数据并通过独立4/4验收。旧运行和冲突记录保留。这是显式选择能力的新增，不是忽略原字段错误或放宽跨来源保护。
