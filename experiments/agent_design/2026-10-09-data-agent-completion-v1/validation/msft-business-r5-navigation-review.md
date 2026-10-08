# Microsoft business r5 · attempt 01 导航复查

结论：未发现“正文已返回但没有送给模型”的传输缺陷。失败由模型反复选错旧 artifact，叠加已读目录与短期正文窗口轮换放大。该诊断不改变最终内容验收，不修改运行代码、输入或原件。

本次 attempt 01 最终以 `no_progress_limit` 结束；它不属于成功交付。attempt 02 继续自动处理。本检查只读冻结 attempt 01 的实际请求/响应。

## 具体证据

| 实际时点 | 请求/响应事实 | 判断 |
|---|---|---|
| turn 014 输入 | 上一轮 observation 完整含 112–123，其中 IC 的 117/118/120/122 均有 text；`preview_truncated=false`；retained_body 同样保留 | IC 正文和 ID 确实曾送达 |
| turn 014 动作 | 读取 MPC context `/blocks`，17/19 项返回，明确给出 offset 17 的 next_cursor | 有界分页，不是静默截断 |
| turn 015 动作及 turn 016 输入 | 正确补读 offset 17 的 149/150；下一轮 observation 明确包含末项 Search and news advertising 全文 | MPC 列表末项也已送达 |
| turn 017 输入/动作 | catalog 36 条、omitted 20；IC 只剩标题 117，118/120/122 被轮换出去。模型说找 IC，却读 `art-002...`（124–131），正确对象应是已读 `art-4da...`（112–123） | 选错旧 artifact |
| turn 018 动作 | 再读 `art-e4e...`（100–111）寻找 IC | 仍选错 |
| turn 019 动作 | 读 `art-1abaa...`（132–148），下一轮拿到了 MPC，但没有 IC | 读错范围 |
| turn 020 动作 | 读 `art-3722...` 的 offset 7，即 PBP 93–99；再次声称需要 IC | 无进展保护正常触发 |

`evidence_index` 仍列出了所有五个 context 的 artifact ID、source ID 与 evidence ID，但没有稳定 block 范围或主题预览。`read_body_catalog` 只对当前显示条目给精确回读指针，省略部分没有可分页入口。`run_state()` 中也没有完整的已读 catalog。模型采用无历史、宿主持有状态的决策协议，因而最近一次大范围重读容易把另一组所需 ID 挤出两处窗口。

模型并非没有其他路径：它可以在 IC 全文可见时先选择证据，也可以重新通过目录或 `read_source` 定位同一原文。故不能把本失败全归于宿主；也不能把这些重读称作仍然必要的正文补齐。它是导航错误和可发现性不足共同造成的效率问题，不是允许错误事实通过的缺口。

## 最小通用修复建议（未实施）

首选：把完整“已读位置目录”作为新的 `run-artifact-v1` 导航 artifact 注册，行只含 source/context/block 身份、ordinal、短预览、已读标记及精确 read_request，不存整段正文。packet 继续只显示预算内第一页，并在省略时给出该目录的 artifact ID、hash 和现有 `read_artifact` next_cursor。模型通过现成的 items 分页读取后续目录；正文仍通过原来的精确 pointer 获取。

- 目录采用稳定 source/context/ordinal 排序，避免重读导致整目录重排；新已读材料发生变化时产生新的版本/hash，旧 cursor 仍绑定旧快照。
- 读取目录只是导航，不能触发 `delivered_blocks` 或把存盘未读正文算成已读。
- 可将当前已选 block 标识置于目录行，方便做增量选择；不改选择替换语义，不插入公司答案。
- 小型替代/辅助方案：context 的 evidence_index 增加可核对的 first/last block ID、ordinal 范围、block count，以及按原件派生的短 heading/preview。它能减少猜错 artifact，但不能单独解决目录省略后无法枚举全部已读块的问题。
- 不增加原文输入上限、不强制全章阅读、不放入特定公司/产品关键词。

验收建议：独立合成至少 60 块、正文窗口及目录窗口均装不下，往返阅读 A/B/C 三组后，模型/脚本仍可用固定导航 artifact 与分页 cursor 找回 A 的精确 ID；导航读取不计正文已读；旧 cursor 对新 hash 拒绝；不同 scope 隔离。无需为了该诊断增加模型调用。

## 冻结证据 SHA-256

- [result.json](../runs/msft-business-r5/attempt-01/data-query/query/result.json)：`288ceabb3d3c9e562b8da0614c84fd5d59f0a666209b3b0c176c1cc4ef1092f0`
- [turn-014/input.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-014/input.json)：`90138bd432136d6996783d05f09c31777e72d84fc9c41f72d0b137efe44f4393`
- [turn-015/input.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-015/input.json)：`97370e1b79a8449117ff5177df5c503f90098cea23c6661e462db9cdb640ade4`
- [turn-016/input.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-016/input.json)：`b8e6e81a825cc898c7474510521b354dcd06bd806b1c9c0043eb4c30ce7a505b`
- [turn-017/input.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-017/input.json)：`4de5c07831f3d13a5c3bad68da91f7fe7934c88b06583c3f6c68902664fd7ffa`
- [turn-017/decision.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-017/decision.json)：`42b55c93280cdcaac99be58c7b0d711cc18860f36e6aa8b7af920f6768d3a82f`
- [turn-018/decision.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-018/decision.json)：`7b0d32e848971541e3f232f600473cf9e94f0edfda7dafad8a481182f24962ad`
- [turn-019/decision.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-019/decision.json)：`5c69e86db068fd296940d46d38de1167e7d71782f08fba84e6c4f3bc9f7b066d`
- [turn-020/decision.json](../runs/msft-business-r5/attempt-01/data-query/query/turn-020/decision.json)：`898eb65cbe363de7f94c17cc33a690e5c0739f664958dfcb47778264c1a739e6`
