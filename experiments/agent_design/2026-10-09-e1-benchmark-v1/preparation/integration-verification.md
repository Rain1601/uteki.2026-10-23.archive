# E1 来源限定查询与独立问题审核：工程核查

核查日期：2026-10-09。执行者：Codex 支持任务；未调用外部模型，未改动费用账本。本文件是代码与合成集成检查，**不代表真实取材质量通过**。真实题目结果以各自冻结运行及独立评分为准。

## 本次实现

1. 数字查询可由系统模型在 `Requirement.source_id` 指定调用者 scope 内的一份原件。未指定时保留原来的多源查询与歧义处理。一次 query action 的所有 query requirements 必须使用同一来源声明；比较两份版本需要分开查询。
2. 可选 `question_review_policy: independent-question-v2` 与完整 `question_reviewer` 必须成对。planner、worker、材料 reviewer、问题 reviewer 共用已有账本、累计上限、总请求限制和未知费用策略。
3. 材料审核仍使用原 `AnswerAssessment`。问题审核只接收原始问题、范围和 canonical 原文/记录投影，不接收作者 requirements、facts 摘要或之前的修订反馈。程序输出 `AuditedAnswerAssessment`，要求两份判断同时通过。
4. 原材料审核回复、问题投影、问题审核每次原始回复、机械协议修订输入与最终组合分别保存。最终结果标记 `program-composed-independent-question-v2`。
5. 允许针对 `QuestionReviewProtocolError` 使用同一问题 reviewer 做一次机械协议修订。修订输入只由原投影、被拒原回复和程序静态规则组成；不注入评测答案、不指定应引用的段落。普通引用/身份错误不默认为可修订；具体适用规则由版本化 question review 模块定义。
6. 问题审核失败时禁止外层重跑整个材料审核来扩大修订次数。传输故障仍由既有角色内的有限网络重试处理，每次保留计费证据。取消关闭两个角色并封存失败/取消结果，不放行 Analysis。

## 只读边界审查

| 风险 | 已核查路径 | 结论 |
| --- | --- | --- |
| 来源越界、跨公司、未来材料 | `ScopedQueryDataPort.for_query_source` → 派生 scope → `grounded_query` | 指定来源只缩小 caller 权限；来源必须属于原 scope，issuer 必须匹配，cutoff 保留。未来来源明确拒绝。 |
| 版本混选或同报告冲突 | query requirement、action、receipt、completion 与 canonical replay | action 混用来源声明拒绝；单份报告内部多个冲突数值仍为 ambiguous，不自动任选。 |
| 伪造来源声明 | completion 与 `prepare_review_packet` | receipt 来源需匹配 requirement；canonical 查询重新核查 record 与来源绑定；更换声明并重封 manifest 不能把别的来源记录冒充本来源。 |
| 只凭原材料审核通过 | `compose_audited_assessment` → `validate_saved_assessment` | 新 policy 缺问题投影/原始回复即拒绝。程序组合必须与两份 raw 的严格重新验证结果完全一致。 |
| 伪造修订历史 | `validate_saved_assessment` | 初次 raw、修订输入、替换 raw 由 manifest 绑定；修订输入由原投影/被拒 raw 重新计算；最终 raw 必须等于对应最后一次保存回复。 |
| Analysis 绕过 | `load_reviewed_data` | 重建上游 packet，校验 manifest、两原回复、最终组合、执行 origin 与 eligible；任何缺件或未通过关闭入口。 |
| 不完整审核反馈注入 | `coordinator._verify_review_feedback` | 同原问题、scope、dataset、query/review hash 严格绑定；新 policy 的反馈由已封存两原始判断重新组合，不能仅传自行编写的 assessment。 |
| 费用与取消 | 同一 `SdkRecordReviewer`、共享 `RunBudget`，两个 role 的 finally | source 与 question 各有 usage；一次机械修订复用 Q 实例与总请求限制。取消后关闭并保留原回复/usage，不生成可用交付。 |
| 旧流程无意升级 | policy/factory 配对及旧 schema 分支 | 未配置新 policy 的旧三角色、packet、response 形状保持原协议。旧 CLI 明确拒绝新字段；不默默跳过独立审核。 |
| 换机时覆盖预算掩盖分歧 | `make_replay_config.py` | 重定位前检查原模板四角色预算一致；恢复原账本，不能因路径改写把分叉账本或不同额度隐藏。 |

`data_review_delivery` 支持新 policy，重新验证后展示并提供各份原始审核文件。旧 `evaluation_artifacts` 注册导入器面向旧全文/claims 协议，明确拒绝新 policy；本次不扩写该旧导入器。

## 实际检查

- 先前分组回归：61 项旧调用链通过；双审、一次协议修订及旧链相关 69 项通过。
- 新双审合成集成文件：12 项通过，覆盖双通过、Q 缺口、原审核缺口、缺 Q factory/raw、重新封存后篡改投影/组合/raw、一次修订及耗尽、错误引用不盲修订、取消封存、页面和 Analysis 入口、旧 shape。
- 配置/重定位独立检查：新增 5 项，连同旧 replay 4 项共 9 项通过。
- 本次接入相关检查合并运行：**199 项通过**，包含来源限定、多公司 scope、决策协议、源材料回放、独立审核、恢复、页面、Analysis gate 和旧适配器。
- 曾误把不存在的 `tests.unit.test_query_completion` 加入测试命令，产生一个 unittest 模块加载错误；未改代码掩盖。移除错误模块名称并运行实际存在的 `test_source_pinned_numeric_query` 后，以上最终 199 项全部通过。

最终合并命令：

```sh
PYTHONPATH=src:. .venv/bin/python -m unittest \
  tests.unit.test_source_pinned_numeric_query \
  tests.unit.test_scoped_query_service \
  tests.unit.test_independent_question_handoff \
  tests.unit.test_retrieval_cycle \
  tests.unit.test_retrieval_resume_provenance \
  tests.unit.test_question_coverage_review \
  tests.unit.test_source_review_policy \
  tests.unit.test_answer_handoff \
  tests.unit.test_data_review_delivery \
  tests.unit.test_data_handoff_driver \
  tests.unit.test_evaluation_artifacts \
  tests.unit.test_data_evaluation_view \
  tests.unit.test_analysis_evidence_runtime \
  tests.unit.test_decision_protocol \
  tests.unit.test_autonomous_model \
  tests.unit.test_question_reviewer_config \
  tests.unit.test_e1_replay_config -q
```

## 使用与限制

配置显式添加以下两个字段，Q 角色内容复制已审核的 reviewer 配置，再按实验计划显式选择模型与推理参数；不得另建账本。

```json
{
  "question_review_policy": "independent-question-v2",
  "question_reviewer": "完整模型角色配置对象，不是字符串；同原 ledger/cap/request limit/unknown policy"
}
```

上段只说明字段位置，不是可执行配置。实际可执行模板由主任务维护在实验 `configs-v5/`。

- 结构合法、引用准确与语义充分是不同检查。独立 reviewer 仍是模型意见，可能遗漏或误判，必须用冻结评测和 Codex 原件审查判定真实质量。
- 费用消费者必须同时读取 `usage` 与 `question_usage`，或使用共用费用账本；只汇总旧的 `usage` 字段会漏掉问题审核成本。
- 检查不证明底层模型逐字确定，也不证明材料集合在数学意义上最小。
- Hash/manifest 是相对于受信调用者给定的 hash 进行完整性校验，不是供应商签名。能同时篡改全部文件和可信 hash 的攻击者不在此本地评测机制的防护声明内。
- 新 policy 保持可选。旧 policy 仍可走旧链；这不代表旧链已接受独立问题审核。
- 旧冻结运行若来自不同 reading-group/运行协议版本，不保证当前实现能逐字重建旧 payload；需保留其原代码版本和运行指纹。未改写历史产物。
- 本文 199 项对应本次双审接入与最初静态枚举组合 repair。随后 typed 诊断已增加原问题 quote/subject 非精确子串错误；该模块 17 项及双审集成 13 项再做聚焦验证，**30 项通过**，包括真实同类问题的合成一次修订闭环。未再次运行整个 199 项集合，亦不宣称真实 E1-06 成功。

当前结论：未发现阻止已授权受限真实实验的新增来源隔离或审核放行漏洞。下一步以真实调用验证独立缺口是否能进入系统自主补材，并检查最终材料覆盖和额外成本。
