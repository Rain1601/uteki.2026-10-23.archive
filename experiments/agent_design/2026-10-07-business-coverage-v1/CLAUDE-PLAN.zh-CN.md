# 第14轮：09 业务图覆盖账本方案审阅

**当前行动：** 在不灌入答案的前提下，让系统先自己列出"原文里有哪些对象"，再逐项核对候选图，减少 B2 那类遗漏和过强断言。以下是顾问建议，需要 Codex 对照源码审核后再落地。

## 先说关键诊断

评审记录写着："block134 再次写仅竞争语境未建节点"。这说明 Azure Security 并不是没被读到，而是被归错了类：
- 现在的 block_disposition 是按整块归类的。
- 但同一块里既有竞对类别，也有自有对象。

所以只加一次 inventory 调用还不够。分类必须细到"一次提及"，而不是"一个块"。

## Codex 设想中的漏洞

1. **盲点相关。** inventory 和候选图出自同一模型、同一 Skill，容易漏掉同样的东西。需要一项程序侧检查来兜底。
2. **"material/重要性"留了删减口子。** 模型可以用"不重要"为由丢掉对象。这一判断应改成确定性规则。
3. **pass 由模型自己声明。** v1 的状态取决于 issues 是否为空，模型漏审也会显示通过。状态应改由程序计算。
4. **修订会让旧 mapping 失效，也可能删内容来"通过"。** 必须对修订稿重新映射并做回归比较。
5. **"引用缺主语"本可以由程序发现**，不必全靠模型审。

## 1. 程序与模型的分工

| 步骤 | 程序 | 模型 |
|---|---|---|
| inventory | 生成提及 ID；校验 span 是否逐字出现；检查每个非版式块都有条目；用通用规则抽出未覆盖的专名 span，作为待处置清单 | 逐条列出提及，判定语境类别 |
| mapping | 检查一一对应；找出"无来源节点"；做回归比较 | 为每条提及给出去向 |
| claim 审阅 | 生成全部 claim 键；检查枚举完整；检查描述引文是否含主语；计算 status | 逐条判定是否成立 |
| 修订 | 校验新稿；让旧审阅失效 | 输出完整新稿 |

专名抽取规则举例："Our/We offer + 大写短语"。这条规则只依赖语言形式，不包含公司词表。抽出的结果只作待处置清单，不作答案。它依赖英文写法，所以要在其他公司样本上验证。

## 2. inventory 的粒度与处置

- **粒度：** 一条记录是一次提及，包括 block_id、逐字 span 和表面名称。程序把同名提及聚合成候选对象。
- **去重：**
  - 整体与子集不合并。例如"X"与"X cloud services"分成两个对象，并记一条关系候选。
  - 同名但位于不同分部列表的，由模型给出合并理由，程序记录下来。
- **语境类别（完整枚举）：** issuer_offering、issuer_grouping、generic_capability、competitor_or_category、partner_customer_mention、cross_reference、layout。
  - 判定依据是这次提及的主语是谁，而不是它出现在哪个小节。
- **用确定性规则代替"重要性"：** 下列 issuer 提及必须建为节点，其余可延后作为属性：
  - 出现在分部构成列表中；
  - 有定义句；
  - 以 "Our … offerings" 自述。
- **不穷尽声明：** inventory 只覆盖所选块。账本保留"可能未列全"，覆盖率由独立评审测量，不由 inventory 自证。

## 3. 最小 schema

**mapping**：每条 inventory 提及恰好一条。

```json
{"mention_id":"m-017","disposition":"node","node_id":"…","rationale":"…"}
```

- disposition 取值：node、merged_into_node、attribute_deferred、context_only、competitor、generic_capability、unresolved。
- 程序检查四点：
  - 提及集合与 mapping 集合一一对应；
  - 每个节点至少由一条提及支持；
  - 出现 unresolved 时，进入候选图的 unknown 列表；
  - unresolved 不能作为"通过"。

**claim 审阅**：每个已填字段的 claim、每条边，各一条审阅。

- 键：
  - 节点字段：candidate_sha256 + node_id + field。
  - 边：candidate_sha256 + edges[i] + (source, target, relation)。三元组用来发现索引错位。
- verdict 取值：supported、missing_subject、missing_qualifier、partial、overstated_basis、scope_mismatch、unsupported。
- 边另填 proposed_basis（explicit / derived / unknown）。
- 每条都要附 block_ids 和一句说明。
- 程序要求键集合与候选图完全相等，多一条或少一条都判阶段失败。
- 只有全部 supported 且没有 unresolved，status 才为 pass，并且由程序计算。

## 4. 输入隔离与失效

- **inventory：**
  - 输入：packet + inventory 指令 + 通用对象规则（抽自现有 Skill）。
  - 不给候选图，也不给评审结果。
  - 指令 hash 单独记录。
- **审阅：** 输入为 packet + inventory + 原始候选。
- **修订：** 输入为以上全部 + mapping + 审阅结果。
- **修订后：**
  - 旧 mapping 和旧审阅绑定旧 candidate_sha，自动作废。
  - inventory 绑定的是 source_sha，保持有效，不允许修订。修订方如有异议，记为 inventory_dispute。
- **最终复查：** 对新稿重新做 mapping 和 claim 审阅。
- **回归比较：** 原稿已映射为节点的提及，在新稿中失去节点的，自动列出。
- **门控产物：** 必须写明它门控哪个 candidate_sha，程序逐一比对。

## 5. 调用策略与失败安全

- **调用次数：** inventory 1 次（与现有初稿无依赖，可以并行）、审阅 1 次、修订最多 1 次、最终复查 1 次。
- **输出过大时：** 审阅可以按程序预先划分的键分片。每片都看完整原文，所有分片合起来必须等于全集。
- **失败处理：**
  - 截断、未知费用、枚举不全或非 end_turn，都让该阶段失败，不修补 JSON。
  - 最终复查不通过时，两份候选都保留，状态为 revision_failed_self_check。
- **统一标注：** 最终状态仍是 candidate，并注明"同模型自检，非独立评审"。

## 6. 首轮验收

**流程验收**
- 各阶段 hash 链完整；
- 枚举一一对应；
- status 由程序计算；
- 旧 v1 回放结果不变。

**Microsoft 样本**
- 沿用 criteria_sha 冻结的独立检查表。
- 原 pass 项不退化。
- C10、C12、C03 必须由 fail/partial 转为 pass。
- C22 中缺主语的引文必须全部被程序或审阅标出。
- 节点数不作为指标。

**合成反例**（以下每条都应得到对应结果）

| 合成情形 | 应得结果 |
|---|---|
| 自有 "Our X offerings" 只出现在 Competition 段 | 建为节点 |
| 同段有大写的竞对类别 | 不建为节点 |
| 整体与云子集并列 | 分开建节点 |
| 描述引文无主语 | 被标出 |
| 审阅漏掉一个键 | 阶段失败 |
| 修订删掉已映射的对象 | 回归告警 |
| 原文中嵌入指令 | 被忽略 |

**另一家公司 holdout**
- 选一份已冻结的 Item 1。
- 运行前写好检查表，不用于调提示。
- 泄漏扫描：共享 Skill 和提示中不得出现 fixture 里的公司名或节点名。

## 7. 本轮不做

客户、收费、收入属性；竞对产物；Query；独立模型裁判；第二次修订；Mermaid 改版；修改 B1/B2。

## 我无法确认的上下文缺口

1. claim_evidence 是否按"节点 + 字段"有稳定位置，还是只是列表索引。
2. 现有 kind/role 枚举能否表达"服务子集"。
3. 现有 25 项检查表是在看过 B1 之后才写的，对 Microsoft 有过拟合风险。所以 holdout 不可省略。
4. 103 块全量审阅的输出规模，是否必然需要分片。

---

**本轮解决：** 定下 inventory、mapping 和 claim 审阅的分工、枚举规则、失效规则与验收。

**下一个 To-Do：** Codex 对照 product_contract 和 self_review 源码，审核第 3、4 节能否落地，并列出分歧。

| ID | 状态 |
|---|---|
| 01 | 完成 |
| 02–05、07 | 部分完成 |
| 06 | 本阶段排除 |
| 08 | 草稿 |
| **09** | **当前位置：覆盖账本方案待 Codex 审核** |
| 10–16 | 后置 |
