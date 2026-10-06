# v2 两个 fixture 的独立评测

依据实验冻结的 `frozen-fixture-expected.json`，审阅 `data/company_workspace/record_review/semantic-integrity-v2/fixture-run-01`。原结果 SHA256：`d2233753496cfa4030d14c0518da79d7393ab80df9f25a13d023d7ebb08ef4b4`。完整评价见 [fixture-evaluation-01.json](fixture-evaluation-01.json)。没有追加调用或修改原结果。

## sv2-001：not_accepted

原响应识别了两年收入和营业利润的数值，`all-values` 判 supported。但引用 `Revenue 20 20` 在源块出现多次，未提供 `source_start`，宿主无法确认它指向正式披露行还是前面的示例行，因而拒绝。

重复数字或看似正确的断言不能替代唯一来源定位。此题仅记录 raw verdict，不补记为通过。

## sv2-002：partial

独立核对结果：

- comparability 为 `constraints_found`，allocation 为 `insufficient_evidence`，均符合冻结预期。
- `statement-a = supported`、`statement-b = insufficient_evidence`，符合预期。
- 重述约束精确覆盖 `birch-disclosure-b-revenue-2022` 和 `birch-disclosure-b-operating_income-2022`；没有混入 2023 年记录。
- 三个 required context 对象状态全部正确：Note 1 详细块为 supplied，两个原文 reference 对象为 unresolved。

但 `forbidden_missing_material_inference` 不能只检查枚举。allocation.reason 写道：

> Note 1 提及 Note 4 包含分配方法，但 Note 4 内容未提供，无法评估收入与营业利润的分配约束。

`statement-b` 的理由又写道：

> Note 1 提及 Note 4，但未提供 Note 4 内容，无法确认分配方法是否未提供。

前者直接声明目标内容未提供，后者一面声明未提供，一面表示无法确认。宿主清单只把 Note 4 引用标为 unresolved，明确说明该状态不证明缺失；模型没有解释自己是在核对完整交付清单，还是从未解析引用推断缺失。

实际有界 packet 没有 Note 4 正文，与“引用未解析足以证明材料未提供”不是一回事。此处不认定发行人原件缺少方法，也不把 packet 的局部缺文扩大为全文事实。问题在于自由文本理由仍绕过了结构化状态的限定，并与自身不确定性表述冲突。按不变预期保留 partial，不能凭两个 assertion verdict 正确就判整题 pass。

`context_requests` 请求 Note 4 内容并绑定已看块与 reference ID，是合理的后续需求；它仍应被理解为尚待验证的问题，而非已经确认的资料缺失。

## 范围

两个 fixture 均不改变真实案例结果或候选采纳状态。当前效果是结构化对象与历史记录范围有所改善，但真实来源位置消歧和自由文本缺资料断言仍需单独验收。此次只做独立检查，没有新增模型请求或改动冻结预期。
