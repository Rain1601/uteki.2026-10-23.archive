# 第三轮残留问题：证据与最小契约建议

本次只读检查实际请求、输入 packet、原响应及验证代码，没有调用模型或内部系统，也未修改生产代码。对象为 `data/company_workspace/record_review/semantic-quality-v1/real-run-03`。

- 实际输入：`real-inputs-03/packets/001.json`，packet ID `semantic-adfbc9928037dd3e58803a45`，文件 SHA256 `e3f4cfd0b3af72a922339fdd4eb698a4f15fabacfbaf2960d936ace7851e4542`。
- 原结果 SHA256：`6321346134d531850ea5ae682cde73d3826d443912f526485618fb6f75dd1cee`。
- 本文补充排因，不改写此前独立评测或模型原响应。

## 1. Total 引用遗漏

维度轴第四条覆盖六条无维度 Total，声明它们为合并口径，却仅引用：

> Total Revenue $ 281,724 $ 245,122 $ 211,915

其中三条是营业利润记录：`obs-d471c9f3d1f12b167e1eb773`、`obs-0ccf6d30b99cfa01728074db`、`obs-58b8edcdb583d0c1df1a56d7`。相同输入块 `block-001217-90dfc72b` 已完整包含对应利润行：

> Operating Income $ 128,528 $ 109,433 $ 88,523

实际 prompt 也明确要求跨收入/利润记录的约束引用两类行。因此不是来源正文遗漏，也不是没有提示；模型未满足引用覆盖要求，而输出验证器未将该要求落实为可检查的数据关系。

现有 `SemanticConstraint` 只有 `record_ids / statement / citations`。验证器检查 ID 范围、唯一性、来源及连续原文，但没有“哪条引用支持哪个 record”的结构。一个真实收入引用可以合法挂在包含利润的六条 ID 上。这里是引用覆盖缺口，不应误称六条金额本身错误。

## 2. 错称 Note 1 详细说明未提供

响应 limitations 写道：

> 未提供Note 1中关于重述的详细说明。

实际输入已经加入：

- `block-000816-8d9f4520`：Recast of Certain Prior Period Information 标题。
- `block-000817-00ca3208`：2024 年 8 月分部调整、Microsoft 365 商业组成变动、FY2025 起历史分部信息重编的详细段落。
- `block-000818-3a2e0b27`：合并报表不受本次重述影响。

同一响应的 comparability 第一条还引用了 `block-000817` 的详细说明，因而“相关详细说明没有提供”与实际输入和自身引用冲突。“完整 Note 1 没有全部提供”仍可能成立，但不是同一缺口。

同时，输入继承的元数据仍是：

```json
{
  "context_gaps": ["note_exceeds_120_blocks; only its opening and target neighborhood supplied"],
  "unresolved_note_references": ["NOTE 18", "Note 1"],
  "context_completeness": "bounded; cross-note references not automatically resolved"
}
```

新增正文没有相应细化这些粗粒度标签。它们不必然为假——整份附注确实没有自动展开——但无法区分“相关小节已供”和“整份附注未全供”。这一输入表达歧义是有证据的诱因；无法仅凭产物断言它就是模型错误的唯一心理原因。

`limitations` 与 `unresolved_questions` 又都是自由文本列表，验证器既不能核对其指向的资源，也不能拒绝否认已提供内容的声明。模型过度推断和缺少输出契约共同使错误被接受。

## 最小通用契约

### 宿主提供结构化上下文清单

在冻结 packet 中添加小型 `context_inventory`，按稳定资源 ID 区分原文中的引用目标与实际交付片段。每项记录来源 ID、目标定位、`delivery = absent / partial / complete`、实际 `supplied_block_ids`，以及截断或未解析原因。附注整体与其中小节使用不同资源粒度。

新增上下文后根据实际选择更新清单。只有能从标题/定位或显式调用方选择建立关系时才绑定引用目标；无法确定的关联保留 `unresolved`，不能根据关键词猜“整份附注已读”。业务名字与预期判断不应硬编码进通用逻辑。

### 缺资料声明引用清单，不能只写自由文本

新增 `context_claims`，最少包含 `resource_id`、`claim = not_supplied / partially_supplied / cannot_determine`、受影响轴/record IDs，以及解释。宿主核验：

- `resource_id` 必须存在于冻结上下文清单；record/axis 必须在任务范围内。
- `not_supplied` 不能指向已交付片段，或否认本响应正在引用的同一资源。
- `partially_supplied` 必须与清单状态一致，并具体指出仍缺的范围，不能把“完整附注缺失”表述为“已供小节缺失”。
- `cannot_determine` 表示推理或定义不足，不得伪装成可核实的“宿主没给文件”。

自由文本可以保留一般审慎说明，但不作为机器认可的资源缺失结论。机器能验证存在与交付范围，不能仅凭上述枚举证明缺失信息对业务判断确实重要。

### 约束提供逐记录支持映射

为每条约束增加 `record_support`：将每个 affected record ID 关联到原始 fact 定位/表格行或单元格锚点，以及适用的限定语 citation ID。要求其覆盖集合与约束 `record_ids` 完全相同，无未知或重复 ID。

宿主从既有原始 fact DOM 和 table cell 建立锚点，验证被引范围真实覆盖该 record 的来源定位。数值/表行判断检查对应行/值；重述、分配等上下文约束同时绑定相关限定语，不能机械要求限定句本身重复所有数字。不要用“相同 source/block”或“quote 含同一数字”代替对应关系——同一表格可能有多行相同数字。

这一变化可以阻止仅一条收入行引用覆盖利润记录，但仍不能机械证明限定语语义正确；语义独立评测继续保留。

## 最小验收反例

1. 收入与利润六条 IDs 只提供收入支持锚点：拒绝；补齐利润锚点后通过结构校验。
2. 在同一表格引用另一行相同数字：定位不匹配，拒绝。
3. 已供重述小节被声称 `not_supplied`：拒绝；其父附注 `partial` 的准确声明允许。
4. 同一响应引用资源正文，同时声称该资源未提供：拒绝。
5. 资源缺失但模型请求缺口 ID 不存在、串来源或越界 record：拒绝。
6. 补入正文后只复制旧缺口字符串：清单必须更新或标识尚未确定的关联，不得默认为整份已完整。

建议先完成上述离线契约反例，再评估是否需要新模型实验；本次不追加模型调用，不修改历史 packet、原结果或评测标准。
