# 业务结构与收入结构 · 第二轮

[谷歌业务结构](http://127.0.0.1:8769/docs/design/data-agent-acceptance/business-revenue-v2/?view=business#alphabet) · [谷歌收入结构](http://127.0.0.1:8769/docs/design/data-agent-acceptance/business-revenue-v2/?view=revenue#alphabet)

用户指出：收入构成与产品包含关系不能仅靠颜色区分后并排。两者回答不同问题，应该分成两个图。本轮保留四家公司案例入口，谷歌完成两个维度，其余三家保留业务图，收入页明确显示尚未整理。上一版图、候选与回执不改写。

## 实际变化

| 阅读问题 | 交付内容 | 边界 |
|---|---|---|
| 公司经营什么业务？ | 业务结构使用 Mermaid，显示产品/服务、归属和共享支持 | 不含收入分类节点或 `revenue_component_of`；节点大小不表示金额 |
| 收入来自哪里？ | 谷歌独立收入页：集团收入条形图、Google Services 内部收入环图 | 每张图明确分母与期间；不将不同层级相加 |
| 产品如何对应收入？ | 节点说明和收入页范围提示 | YouTube 包含广告和订阅；收入表的 YouTube ads 仅为广告，不能假定一一对应 |

谷歌依据同一冻结 FY2025 10-K。业务图重新从原文整理 Search、YouTube、Network 广告服务等业务，不能仅把收入节点改名。Other Bets 的互联网服务活动保留；由活动归到业务组合的归组明确标记为归纳，不推断经营实体或独立分部。详见 [事实核对说明](alphabet/README.zh-CN.md)。

收入单位为百万美元。Google Services 为 342,721、Google Cloud 为 58,705、Other Bets 为 1,537，另有 −127 对冲调整，合计 402,836。因此集团层使用带符号条形和勾稽说明，不把正项重新归一化成完整饼图。

Services 环图以 342,721 为分母，组成是 Search & other 224,532、YouTube ads 40,367、Network 29,792，以及合并披露的订阅/平台/设备 48,030。广告 294,691 仅是前三项的小计，不再增加扇区；不向独立产品分摊合并收入。比例按这些原值即时计算，显示四舍五入至两位小数。

## 验证与限制

复用 BusinessMap 契约和既有来源核验。新增检查包括：业务图拒绝收入维度、明确收入公司/报告/期间/来源/单位、精确证据锚点、金额绑定原文单元格、含负调整的勾稽、广告小计、环图分母和类别要求。收入分类是否互斥、原表行/年度列/单位选择仍由本轮原文审阅确认，不声称已实现通用表格语义识别。

独立合成案例覆盖另一家公司、另一期间、错源、缺单位、未知或零分母、负调整、合计正确但金额错填、缺失/伪造单元格绑定。检查文件为 [test_build_view.py](test_build_view.py)。

本轮实际通过 12 项定向测试。最终图页的 59 个业务节点/66 条关系与输入对应，122 个本地链接及 96 个片段锚点有效，JavaScript 语法通过；页面和 8 份图形/源码文件均返回 HTTP 200。见 [交付回执](../../../docs/design/data-agent-acceptance/business-revenue-v2/delivery-check.json)。这些是数据与交付检查，未执行浏览器视觉或交互测试。

图页运行无外部依赖。三份未变的业务图按 Mermaid 内容完全相同复用 SVG，只重新渲染谷歌。新版本保留明确输入路径；未建立默认公司或默认财报。没有新增付费模型调用，Claude 此轮未参与，前轮失败记录保留。未进行浏览器视觉或交互验收；生产 Agent 尚未绑定本 Skill。

## 重建与交付

在仓库根目录执行，明确选择四份业务输入和一份收入输入：

```sh
PYTHONPATH=src .venv/bin/python experiments/agent_design/2026-10-07-business-revenue-v2/build_view.py \
  --maps experiments/agent_design/2026-10-07-business-map-mermaid-v1/tsmc/business_map.json \
    experiments/agent_design/2026-10-07-business-revenue-v2/alphabet/business_map.json \
    experiments/agent_design/2026-10-07-business-map-mermaid-v1/microsoft/business_map.json \
    experiments/agent_design/2026-10-07-business-map-mermaid-v1/nvidia/business_map.json \
  --revenues experiments/agent_design/2026-10-07-business-revenue-v2/alphabet/revenue.json \
  --output docs/design/data-agent-acceptance/business-revenue-v2
```

按目录内 Mermaid 配置渲染各 `assets/*.mmd` 为同名 SVG；只有源码逐字相同时可复用上一版 SVG。再用原命令加 `--with-svg` 生成图页。实际金额与候选记录见 [revenue.json](alphabet/revenue.json)、[business_map.json](alphabet/business_map.json)；程序回执见 [verification.json](../../../docs/design/data-agent-acceptance/business-revenue-v2/verification.json)。

## 下一步

1. 按这次分开的口径整理其他三家公司的收入结构，分别核定报告期和披露分类。
2. 将已整理的 Skill v0.2 显式接入系统 Agent，再验收其真实输出；同时保留主线解析质量与 Query 待办。
