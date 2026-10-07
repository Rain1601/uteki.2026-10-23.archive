# 财报精编契约提案 v1

状态：**设计提案，未实现、未接入生产；本文件不是已生成的完整年报精编。**

目标：将显式选定的一份报告忠实浓缩为中英文可读版本。固定结构、保留重要限定条件、逐项回到原文。用户和后续分析 Agent 应能分清报告披露、管理层解释、程序加工与材料缺口。

本提案遵从[已有产物约定](../../../docs/design/UTEKI_DATA_PRODUCTS_v1.zh-CN.md)。报告范围不是公司截至今天的全部信息；正文默认不加入外部知识、投资论点、估值、自行生成的预测或研究推断。原报告内的管理层预测可以保留，但须明确归属和条件。

## 1. 对 Claude C2 的修正

[本轮 Claude 原回答 C2](runs/opus55/answer.md)提出复用 narrative 并增加四项。经源码核对，需要作以下修正：

1. **AnnualNarrative 不能原样复用。** [当前契约](../../../src/uteki/agents/analysis/narrative_contract.py)含 thesis、industry、valuation、watch 及 fact/inference/unknown，服务于分析叙事。精编应新增独立的业务载荷；复用固定章节呈现方式、运行身份和证据契约，不建立第二套来源身份。
2. **单元格定位已存在。** [SourceLocator](../../../src/uteki/domain/research_data/evidence_package.py)已有 `cell: {row, column}`，要求零基坐标；也已有块、字符范围、页码、DOM 路径和图片区域定位。可能需要补齐解析与校验流程，但不能将 cell 字段称为新能力。
3. **忠实精编不接受 inference。** 给推断增加 depends_on 仍不能把它变成报告披露。研究推断应进入独立分析产物。
4. **ComputedScalar 不是通用事实模型。** 它仅用于已登记公式的计算结果，要求 normalized_record 父项和 operand_record_ids。结构化披露应使用 ResearchRecord 及其源候选；禁止把所有事实塞入 ComputedScalar。

## 2. 最小报告载荷（全部拟议）

| 字段 | 含义与约束 |
|---|---|
| `schema_version` | 固定为显式发布的精编协议版本；禁止未知版本自动降级 |
| `template_version` | 固定章节、标题、显示顺序、双语标签和渲染规则的版本 |
| `artifact_id` | 宿主分配的报告工件 ID；文件哈希、路径、大小沿用工件登记 |
| `status` | 首版只能为 `candidate`；结构校验通过不代表内容已核验或已采用 |
| `scope` | 复用 ExecutionScope；显式公司、来源、数据快照、截止日和候选访问策略 |
| `primary_source_snapshot_id` | 必须属于 scope；v1 一份报告对应一家已核对公司 |
| `reporting_period` | 来源确定的实际起止日期及期间类型；不猜财年、币种或日历规则 |
| `evidence_package_refs` | 引用已冻结 EvidencePackage 工件及哈希，沿用既有工件访问契约 |
| `generation` | 引用已有 root_run_id、run_id、step_id、call_id 和 model_call_record_ref |
| `sections` | 下节八个命名字段，各出现一次；模板控制显示顺序 |
| `gaps` | 复用 EvidenceGap 形状的报告缺口；ID 唯一、范围有效、原因明确 |

参照：[ExecutionScope](../../../src/uteki/domain/research_data/execution_scope.py)、[ArtifactRef](../../../src/uteki/domain/research_data/run_artifacts.py)、[运行事件及发布引用](../../../src/uteki/agents/runtime/observation.py)。

`generation.model_call_record_ref` 沿用实际发布引用，指向包含 `configuration_snapshot` 的[模型调用记录](../../../src/uteki/agents/runtime/call_costs.py)。不重造模型参数对象或 trace_id；缺失字段保持未知，并记录缺口。宿主运行记录不由模型填写。

报告内的较早年度比较列可以保留，但必须来自同一显式来源，并保留各列实际期间。20-F 不得强行转换为 10-K。多公司、多主报告合编属于后续独立协议范围。

## 3. 固定八章与稳定呈现

| 章节键 | 固定标题 | 内容范围 |
|---|---|---|
| `scope` | 材料身份及范围 | 来源、报告类型、公司、实际期间、版本、截止日、处理范围 |
| `business` | 业务与收入来源 | 产品、服务、客户、收入方式及原文限定条件 |
| `segments_kpis` | 披露分部与经营指标 | 原披露分部及公司特有 KPI，不强塞统一指标目录 |
| `financials_liquidity` | 财务表现与资金情况 | 财务报表、资金、债务、现金流及比较期间 |
| `management_explanations` | 管理层解释 | 变动原因、展望及预测，明确归属和不确定性 |
| `risks_events` | 风险与重大事项 | 报告披露的风险、诉讼、交易及其他重大事项 |
| `policies_notes` | 重要会计政策与附注 | 影响理解的政策、估计、口径和附注条件 |
| `gaps` | 材料缺口 | 汇总各章缺口及未处理内容，不重复生成新的结论 |

每章字段：`coverage`、`statements[]`、`table_refs[]`、`image_refs[]`、`gap_ids[]`。列表允许为空；八章均保留。身份章从冻结元数据渲染，缺口章从相同 gap_ids 汇总。

固定显示顺序：标题与覆盖状态 → 陈述 → 有出处的表图 → 本章缺口 → 引用。公司可有不同条目，不能改变核心章节键或为填满模板编造内容。标题由模板给出，不由模型写成结论。

首版 table_refs、image_refs 只展示被引用的原始证据内容或明确的图片未解析状态。新制图、删列重排表和计算指标须另有显式转换契约及父项；不能由模型自由填数。

## 4. 陈述性质与表达方式分开

| 字段 | 允许值或规则 |
|---|---|
| `statement_id` | 报告内唯一，中英文共用 |
| `statement_kind` | `source_fact` 或 `management_attribution`；没有 inference |
| `attribution` | 管理层陈述必填，保留说话主体；其他陈述为 null |
| `texts` | 固定 zh-CN 与 en 两个版本；每版含 text、form、translated |
| `texts.*.form` | `quote` 或 `paraphrase` |
| `texts.*.translated` | 布尔值；译文与原语言逐字引文不同 |
| `evidence_refs` | 非空的 `{package_artifact_id, evidence_artifact_id}` 引用 |
| `record_refs` | 可选 ResearchRecord 引用；含数字不等于必须先完成事实库入库 |

每条陈述只表达一个可核对的主要命题，连同主体、期间、口径、条件和不确定性保存。管理层预测即使逐字引用也仍是管理层陈述。`source_fact` 表示“原报告披露”，不表示已独立证明真实。

非翻译 quote 必须与对应 SourceQuote 原文一致；翻译 quote 必须标记译文，原始引文保存在证据链中。paraphrase 必须经过忠实性检查；结构校验不能证明转述无遗漏。

数字沿用[ResearchRecord](../../../src/uteki/domain/research_data/query_contract.py)的主体、metric、实际期间、value_kind、value_relation、单位、会计口径、维度及限定证据。其当前 status 只有 candidate，精编引用不改变该状态。

[BusinessMap](../../../src/uteki/domain/business_map/models.py)只能提供候选业务结构。其 derived 赚钱方式、未采用关系或研究重要性判断，不能直接改标为原文事实；必须回读具体披露并核对审核状态。

## 5. 证据、覆盖与缺口

引用解析流程：报告 evidence_refs → 已冻结 EvidencePackage → 包内 artifact_id → derived_from → 原文根的 SourceLocator。

原文根为 source_text、source_table 或 image_reference；模型摘要不能独自充当原文根。页码、URL、原件哈希、block_id、cell 等取自已有定位，不让模型另填一份。正文事实必须有可核对的文本或表格依据；仅图片元数据不能证明图片内容。

引用必须满足包内闭合、无环及来源范围约束。原文缺字段继续采用现有 EvidenceGap 约定，不以新工具名、HTML 链接或伪造页码补齐出处。生成的 HTML/Markdown 只是阅读投影，不是新证据根。

每章 `coverage` 包含 `status`、`coverage_refs`、`method_record_ref`；后两项引用实际阅读证据和方法记录，不由模型虚构。

- `covered`：声明的处理范围有返回正文依据；不等于重要信息全部保留。
- `partial`：只处理了部分相关正文，保留剩余范围及原因。
- `not_covered`：未读或未处理；不能称未披露。
- `not_found_by_method`：某次明确的方法未找到；记录方法及检索范围，不能称未披露。
- `unresolved_error`：解析、定位、读取或核验错误尚未解决。

`not_disclosed` 不是搜索空结果的替代词。它只能作为经过显式披露核查规则确认的缺口结论，关联核查范围、方法和审核记录；首版缺少该规则时不得自动产出。`not_applicable` 同样需要来源或适用性依据。

EvidencePackage 当前 semantic_completeness 固定为 `not_evaluated`。导航命中、覆盖行数、解析成功、schema 通过和候选入库，均不得自动升级成“整份年报完整覆盖”。图像未 OCR、重要附注未读、冲突和截断必须留下缺口。

## 6. 合成单章片段

**以下是虚构数据和虚构引用，仅说明结构。它缺少报告顶层字段及其余七章，作为完整报告必须校验失败。它不代表真实披露或已生成成品。**

```json
{
  "management_explanations": {
    "coverage": {"status": "partial", "coverage_refs": ["synthetic-read-01"], "method_record_ref": "synthetic-method-01"},
    "statements": [{
      "statement_id": "synthetic-st-01",
      "statement_kind": "management_attribution",
      "attribution": "公司管理层",
      "texts": {
        "zh-CN": {"text": "管理层称，收入下降主要受到产品 A 销量减少影响。", "form": "paraphrase", "translated": true},
        "en": {"text": "Management attributed the revenue decline mainly to lower sales volumes of Product A.", "form": "paraphrase", "translated": false}
      },
      "evidence_refs": [{"package_artifact_id": "synthetic-package", "evidence_artifact_id": "synthetic-mdna-text-01"}],
      "record_refs": []
    }],
    "table_refs": [], "image_refs": [], "gap_ids": ["synthetic-gap-01"]
  },
  "gaps": [{
    "gap_id": "synthetic-gap-01", "reason": "not_covered",
    "artifact_ids": [], "source_snapshot_ids": ["synthetic-report-01"],
    "detail": "汇率影响相关附注尚未返回正文；不能据此认定未披露或影响为零。"
  }]
}
```

## 7. 最小验收与下一步

1. 先发布 schema 与 template 的显式版本，校验八章、状态、引用和双语 statement_id 一致。
2. 用真实单章核对原文事实、管理层归属、数值限定和缺口；再扩展到整份报告。独立原文答案不能进入提取输入。
3. 同一冻结 JSON 经固定模板再次渲染，应得到相同内容与文件字节。再次调用模型可能产生不同措辞或选材；配置快照只提供追查依据，不保证逐字重现。
4. 分开报告格式有效性、引用定位准确性、忠实性与重要内容遗漏。没有完成内容审核及整份覆盖验收时，只交付候选或局部精编，不宣称完整报告完成。

本轮仅交付以上设计说明；没有修改运行时代码，也没有为本说明调用模型或生成完整精编报告。
