# E5 本轮：双公司准备完成，真实取材待恢复原账本

2026-10-10。本轮完成 E5-P1/B1/G1：完整材料准备、独立答案标准、查询工具预检。修复 R17 财历元数据丢失。**尚未执行系统模型取材，不能称 E5 已通过；新增模型调用和费用均为 0。**

## 问题与验收对象

以 2026-02-06 为截止，仅用所选 Microsoft 与 Alphabet FY2025 完整 10-K，分别提供各公司 FY2025/FY2024 合并总收入，保留准确日期、币种单位和精确出处。微软的 6 月财年与 Alphabet 的自然年要分别绑定；不计算增长或跨公司合计。

Codex 直接阅读原件中的合并损益表、上下文和等价披露，另由独立 Codex 子代理复核。下表是评测参考，不是 Agent 产物，也不会传入运行配置。

| 必需项 | 原件收入，百万 USD | 完整期间 | 工具预检 |
|---|---:|---|---|
| Microsoft FY2025 | 281,724 | 2024-07-01—2025-06-30 | 值、单位、来源及财历一致 |
| Microsoft FY2024 | 245,122 | 2023-07-01—2024-06-30 | 值、单位、来源及财历一致 |
| Alphabet FY2025 | 402,836 | 2025-01-01—2025-12-31 | 值、单位、来源及财历一致 |
| Alphabet FY2024 | 350,018 | 2024-01-01—2024-12-31 | 值、单位、来源及财历一致 |

验收按必要覆盖、范围/真实性/出处、聚焦分别判定。允许原件等价出处，不要求唯一块 ID。完整表格必要背景可保留，无目的地重复交付等价表不通过。精确标准见[冻结标准](evaluation-only/standard.v1.json)与[独立原件复核](evaluation-only/INDEPENDENT_ORIGINAL_REVIEW.zh-CN.md)。截止日依赖 hash 固定的本地来源元数据，本轮未重新联网核对 SEC acceptance。

## 本轮 bug：有记录，不代表能够正确查询

最早偏差在 `build_dataset → extract_inline_records` 的调用边界：旧调用漏传报告类型 `form`。解析器先生成金额记录，再读取报告类型以建立财年映射；`KeyError` 被记录为 normalization gap，因此表面上“有收入数据”，后续却拿不到 FY 标签对应的日期。

修复只传递已核验来源的 `form`，不添加任何公司、金额或财年终点。两个虚构公司分别采用自然年和跨自然年财历；修复前各有记录、映射均为 0，修复后各自映射保留。错误公司、来源、期间、缺范围、超截止及文件篡改仍拒绝。原件与历史运行未修改。

[修复前复现](validation/builder-form-before.json) · [修复后证据](validation/builder-form-after.json) · [通用修复方法](../../../docs/DATA_AGENT_BUGFIX_PROTOCOL.zh-CN.md)。这次缺陷说明模块间元数据契约也必须验收，不能只检查行数或 JSON 合法。通用修复的独立反例与真实模型稳定性是不同证据，后者仍未测。

## 准备与工具实际结果

- 复用现有 `build_dataset`；实验适配器只接收整份来源及身份/hash，不允许章节、块 ID、参考答案参数。
- 两份全文与导航索引共 2,739 块全部保留；52 个原输入文件前后 hash 一致。没有 Codex 预选语义片段。
- 213 条候选记录，四项必要值通过工具核验。每个微软金额有 4 个等价候选出处，每个 Alphabet 金额有 5 个；它们不相加，也不是新增事实数。
- 每家公司单独收窄后，另一家公司查询被拒绝；早于披露日的范围看不到相应来源和财历。
- 2,970 个未映射概念记录继续显式保留，状态为 `prepared_with_gaps`，不将完整财报解析标成完成。这些诊断数量不等于本题遗漏数量。
- 最终准备使用 `preparation-v2`。v1 的结果摘要未明确列出 normalization gap 数量和状态，已保留历史；v2 补全状态，不覆盖 v1。

本机详细产物位于 `output/e5-multi-company-20261010/`，目录受 Git 忽略；公开摘要见 [工具预检](validation/prepared-query-check.json)。完整原件和准备输出没有随本轮文档重复上传。

离线检查：64 项查询/范围/Agent 工具测试、56 项材料准备/通用 builder 测试通过；实验适配器 4 项检查通过。测试分工中的另 3 项定向测试与上述套件重叠，不再相加。原件工具预检也是脚本执行，不是模型规划质量评测。

## 继续执行的入口与唯一当前外部缺口

有本轮选定原始 datasets 的机器可用新输出路径重建完整准备，无模型和网络调用：

```bash
PYTHONPATH=src:. .venv/bin/python experiments/agent_design/2026-10-10-e5-multi-company-v1/build_preparation.py \
  --input experiments/agent_design/2026-10-10-e5-multi-company-v1/selected-inputs.v1.json \
  --repository "$PWD" --output "$PWD/output/e5-multi-company-new/preparation"
```

`question.v1.json` 与 `selected-inputs.v1.json` 是运行侧可用输入；`evaluation-only/` 全部仅供验收，不能进入模型上下文。冻结清单绑定输入、标准、原件复核和本次准备/实现 hash。

当前机器没有另一台机器 E2–E4 的原共享 `costs.sqlite`，也没有交接所列 `private-state-v1.tar.gz`。不能用 E1 账本、文档中的历史费用估算或新空账本冒充继承。[本机检查](local-preflight.json)记录了检查的明确路径。

紧接着：恢复并核验原共享账本及相应配置，再创建新机 E5 运行配置，先本地检查，再真实运行系统 Agent，最后按冻结标准独立验收。API 未发出，因此当前不存在新的调用失败或未知费用。没有调用 Analysis，也没有承诺多次运行稳定或任意公司泛化。

路线位置：E1 受限基线 → E2/E3/E4 指定案例通过 → **E5 离线准备完成、真实执行待恢复** → E6 扩容质量/成本 → E7 公司关系。原 R2–R7 未修项仍保留；没有用本轮通过覆盖历史缺口。
