# Microsoft 已读目录分页修复：真实运行独立验收

结论：**r6 原文交付通过独立验收，真实目录翻页路径也已走通。** 系统自行取得 FY2025 三个报告分部的完整主要业务列表及必要限定，最终 19 块、3,738 字符。未用上一轮通过结论代替本轮检查。

## 封存版本

- [实际运行 msft-business-r6](../runs/msft-business-r6/result.json)：两次交付后 reviewed_data_ready。
- [最终原文包](../runs/msft-business-r6/attempt-02/review-packet.json)：19 个原文事实。
- [最终审阅](../runs/msft-business-r6/attempt-02/review-01/result.json)：reviewed，analysis_eligible=true。
- Packet SHA-256：`0ef0e19513ca30edbf450d0714d55ac90f7d78ac8dbb6bf3e9931025aaa89402`。
- Query manifest：`f554ff9cdd3c01c580ea799823e09d216e422d29ab52f0574837ac8e0762cee5`。
- Review manifest：`b37d2405bf249b3b2d4ef205749836d4188042bf593bc040f0ea0a16783934a8`。
- [冻结 Microsoft FY2025 原件](../datasets/msft/raw/msft-2025-10k.html) SHA-256：`0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。
- [机器核验记录](msft-business-navigation-v1-review.json)：全部原文、精确引用、DOM 路径、结果绑定及真实分页轨迹。

## 原题覆盖

| 要求 | 实际交付与独立判断 |
| --- | --- |
| 报告分部与年度口径 | 原文 86 列三个分部；87 保留 2024 年 8 月调整和 FY2025 生效的限定。通过。 |
| Productivity and Business Processes | Commercial、Consumer、LinkedIn、Dynamics 四项完整；保留商业云子项、本地软件与云的区别及其他明确子列表。通过。 |
| Intelligent Cloud | Server products/cloud 与 Enterprise/partner services 两大项完整；Azure and other cloud services、GitHub cloud、Nuance Healthcare cloud、虚拟桌面、本地服务器和服务清单均有原文。通过。 |
| More Personal Computing | Windows and Devices、Gaming、Search/news advertising 三项及组件清单完整。通过。 |
| 列表层级 | 三个 reading group 均有完整 item bodies 和必要 context。原件中单独拆出的 bullet 标记不影响已完整交付的正文。通过。 |

19 段正文及 19 条引用均逐字匹配冻结块与原始 HTML DOM，引用字符范围正确。原件、数据集文件、最终 query/review manifest、审阅输入与 packet 的哈希全部一致。

## 最小性与修订

首轮 35 块包含具体产品发展、收入驱动和竞争定位叙述。修订后仅保留分部定义、主要组成清单、年度口径及短标题／引言，共 19 块。最终没有扩成详细产品目录，也没有依赖金额或收入驱动替代业务定义。短标题与引言帮助保留分组；本次称有界充分，不声称数学最小字节数。

## 实际目录分页证据

[attempt-01 turn-011](../runs/msft-business-r6/attempt-01/data-query/query/turn-011/decision.json) 的模型自行调用 read_artifact，沿已读目录返回的 cursor 从 offset 33 继续读取。

- 目录总数 57；本次返回索引 33 至 56，共 24 条；next_cursor=null。
- [工具回执](../runs/msft-business-r6/attempt-01/data-query/query/turn-011/receipt.json) 显示 tool_returned、progress_delta=true、preview_truncated=false。
- [反馈](../runs/msft-business-r6/attempt-01/data-query/query/turn-011/feedback.json) 标记 navigation_only=true，reads=[]。目录翻页没有冒充原文阅读。
- 两次执行均 evidence_ready、host_reference_checks_passed，均未以 no_progress 结束。

这证明本次真实运行的一个 57 项目录续页被正确使用，不代表所有分页路径均在线验证。另有离线 87 项边界测试，应作为不同证据保留。

## 职责和边界

系统独立 plan、检索、阅读、翻页和选择；调用方只给原问题、数据集、范围、目的及资源限制。本次 Codex 在封存后核验，不参与选材，未调用 API 或修改原件／生产代码。

当前完成数据交付和本次导航回归，不等于分析报告已验收。下一步由主任务汇总封存证据、账本、代码与换机交接，不再为此验收增加付费调用。
