# Microsoft Cloud 口径题 · v4 独立验收

**结论：最终 Data 原文交付通过。** msft-cloud-r2 经一次系统审阅修订，交付 18 块、4,741 字符，足以区分三个披露口径。不是同一指标的三个名称，也不是可以相加的三个并列分部。

| 口径 | 原始定义与财务披露 | 原文块 |
|---|---|---|
| Microsoft Cloud | 包括 Microsoft 365 Commercial cloud、Azure and other cloud services、LinkedIn 的商业部分、Dynamics 365；收入已包含于多个产品服务收入行。FY2025/2024/2023 为 $168.9/$137.7/$111.6 billion | 1227；PBP归属见91/93/97/99 |
| Intelligent Cloud | 三个报告分部之一，包含 Server products and cloud services，以及 Enterprise and partner services；FY2025/2024 分部收入 $106,265/$87,464 million | 86、118、120、122、587 |
| Azure and other cloud services | 属于 Server products and cloud services，保留云/AI消费、GitHub cloud、Nuance Healthcare cloud、虚拟桌面等组成；FY2025 披露增长34% | 120、613 |

`34%` 是增长率，不是收入金额。产品表中的 $98,435/$79,828 million 是 **Server products and cloud services**，不能标成 Azure 收入。本包没有单列 Azure 金额；这句话只覆盖本次交付表格/段落，不能扩展为公司所有渠道从未披露。

## 原件与引用核验

18 块文本和18条整块引用均与冻结索引及原 HTML 对应 DOM 一致。两个表格的全部 cell、row/column、rowspan/colspan 也按冻结 parser v0.1.11 从原 DOM 重建核对；不是仅核对几个数字字符串。

587表的行1保留单位和年份，行14标明 Intelligent Cloud，行16是 Revenue，列3/7分别为2025/2024金额。1226表保留 millions、Year Ended June 30 及2025/2024/2023表头。515保留2025相对2024的财年比较引言。财务金额与同比均有对应原文范围。

## 最小性、修订与边界

第一次模型审阅要求补 PBP 归属及比较引言，并删去多余毛利/重复说明。系统第二次自行补查、选择原文；其反馈与第一次封存模型 assessment 一致。最终保留 PBP 完整主要列表作为边界上下文，两个完整表格带有其他行，517还保留 Cloud 增长说明。它是有界充分包，不声称数学最小字数；没有全章或详细产品全集。

模型自己提出的毛利率及明确“非分部指标”原话不属于用户原题必要条件。最终审阅没有为此继续扩张范围。Cloud跨分部口径应由 Analysis 根据原始定义与分部归属归纳，不能冒充原件里的逐字结论。

本轮只检验 Data 交付，没有调用 Analysis、没有写分析报告，也不是人工用户验收或新公司泛化证明。Codex 没有替运行模型指定章节、block或补写事实。本独立审查未调用 API，未修改原件或运行代码；被审查系统运行的真实模型调用见运行日志。

## 冻结入口

- [本次运行结果](../runs/msft-cloud-r2/result.json)
- [最终原文包](../runs/msft-cloud-r2/attempt-02/review-01/input.json)
- [最终模型审阅](../runs/msft-cloud-r2/attempt-02/review-01/result.json)
- [逐块、逐表及hash记录](msft-cloud-v4-review.json)
- [SEC FY2025原件](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)

Packet ID：`data-review-d4d9db01ea4da442525cb814`。Packet 文件 SHA-256：`e26bd59f608ef085cdaab574511eb313d5ded8d58f2a261aa0877ff5fe23d21f`。

Final review manifest SHA-256：`4f84d4a70a80d37e9a5fbf459e5517f5876e48c16f7264365713d0fefaac6447`。Cycle、两次 query/coordinator/review 与 dataset manifest 均已验证。

下一步：修复此前微软业务题暴露的已读目录分页导航缺口，再对原题做针对性回归；无需为此无差别重跑六题。
