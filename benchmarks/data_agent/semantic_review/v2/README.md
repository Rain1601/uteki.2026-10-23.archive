# 语义协议 v2 定向合成案例

`cases.json` 只包含模型可见材料和明确选择的 packet；`expected.json` 只供独立评测。两题分别检查同值/重复行的逐记录证据覆盖，以及已提供重述详情与未解析附注引用的区别。公司、日期和数字均为显式合成数据，不进入产品默认值。

准备时只读取 `cases.json`，逐个验证 `packet` 并写入新的 `packets/NNN.json`；生成包含 `case_id / path / sha256 / packet_id / record_ids` 的引用和 `source_origin=synthetic_fixture` 的 input manifest，最后封存目录 manifest。使用 `scripts/review_data_semantics.py run` 执行。不要用 v1 benchmark.prepare 重写 v2 packet，也不要将 expected 发给模型。

评测先检查运行契约，再按固定检查轴、断言、受影响记录集合和上下文状态复核；自由 reason/statement 仍需独立源文审核。脚本结构通过不能代替语义验收。实际运行与限制见 [v2 报告](../../../../experiments/data_agent_query/semantic-review-v2/README.md)。
