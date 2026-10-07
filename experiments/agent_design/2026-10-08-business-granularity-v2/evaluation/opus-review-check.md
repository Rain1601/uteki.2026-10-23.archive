# Opus 16 项意见的独立核查

结论：主要缺陷判断有依据，尤其整体/云子集、Defender宿主、长声明缺引文。部分建议把 customers 收窄为“明确付费客户”、把 products_services 收窄为“对外出售产品”，比冻结 Skill 更严格，不宜直接机械照改。

本次只对照 revision-01、103块冻结原文、冻结Skill与Opus原意见；未读取正在执行的新补丁。逐项编号为原 issues 数组顺序（1起）。仅评审侧，禁止进入执行输入；未改事实，未调用模型。

| 意见 | 判断 | 依据与边界 |
|---|---|---|
| 01 | 基本合理，避免过度删除 | 竞争句不能单独证明Commercial宿主，Windows整体范围需保留。EMS和Windows在101又明确是平台组成，因此可合并重复条目、补足引用；不能由此判定所有平台组件关联错误。 |
| 02 | 合理 | Defender已被提取，但Commercial宿主与候选自身归属未知相冲突。PBP章节位置不能自动推导Commercial所属。 |
| 03 | 合理 | Office条目当前摘录没有Office主语；一般Office竞争提及也不应缩成Commercial版本。补主语和范围，不能丢掉该提及。 |
| 04 | 部分合理；歧义不是已证明错误 | 093确实显示组与平台可能不同，101定义用于整组应注明范围。但原文在同名业务标题下交替使用简称，不能仅凭列表嵌套认定全部定义/收入一定属于不同独立对象。organizations译为企业较窄，可改为组织。 |
| 05 | 合理 | 安装量、ARPU、盗版、库存等是收入驱动，不是收费方式。Dynamics用户授权/应用消费、OEM授权购买具有机制信息；应保留有据机制及其他信息的可定位去向，不能全删。 |
| 06 | 引用问题合理；代词歧义不宜夸大 | which片段缺主语，完整句应纳入。完整103句将订阅/广告与Consumer cloud收入及Outlook/OneDrive需求联系起来；代词有解释空间，但不因此否认全部关联，应保守转述。 |
| 07 | 基本合理 | 增长子句未引用且不是收费机制。广告投放是业务活动，不能仅凭投放句推导按点击/展示计费或明确付费人；保留原文所述广告与搜索变现即可。 |
| 08 | 合理，但字段定义需一致 | 广告受众不等于付费客户；当前值自称广告投放对象，应保留为受众/用户语义或明确未知，不能补造广告主类别。 |
| 09 | 伙伴判断合理；玩家部分偏严 | 178把开发者/伙伴与customer base区分，混为客户需改。对玩家要求原文必须明说付费客户，超过冻结Skill中“issuer-specific customer categories”的明确程度；玩家是有据目标用户，可作明确角色限定，不能无声丢失。 |
| 10 | 偏严，实际是角色边界待定义 | IT人员和开发者是原文明示目标用户，不能假定为购买决策者或付费人；但Skill没有定义customers只允许付费主体，也未禁止目标用户。可保留用户身份限定/相应缺口，而非称事实不成立。 |
| 11 | 伙伴项合理；工作室项需限定 | 芯片伙伴是支撑关系，不是出售的服务。Skill同时允许product/capability/feature详情保留于products_services，因此明确标作内部内容生产能力的工作室不必仅因“非出售产品”而机械删除；仍应避免冒充独立对外业务。 |
| 12 | 合理 | Azure AI归属的前置句未进入claim摘录；完整128支持讨论关联，但当前摘录自身缺主体。应补充分段证据而不是以词串出现即算通过。 |
| 13 | 合理 | 七处长描述各含当前摘录未涵盖的子句；原文已经存在充分句子。补齐对应claim引用即可，不需靠外部知识。 |
| 14 | 合理且关键 | GitHub/Nuance整体端点不可由边上“仅云部分”文字缩小。应由模型据源处理子集或将整体归属留未知；源文未明确不能用other on-premises补猜。 |
| 15 | 合理 | 132的Nuance对话/环境智能不等于130的Nuance Healthcare全部/部分，不能仅同品牌就挂Healthcare。保留有据企业服务关系与身份歧义。 |
| 16 | 确有遗漏；主语与时态需保留 | 183明确一些设备制造商也是微软当前或潜在伙伴/客户，且包括Windows OEMs。应保留关系角色重叠，但不能写成所有厂商均为当前客户，也不能直接指定为Devices业务的付费客户。 |

当前复核区分引用不全、身份范围错误、字段定义未明确三类；不以顾问说法代替独立验收。既有字段不支持准确表达时，应保留事实及明确缺口，不靠删除未能放置的信息获得通过。下一步核查Sonnet真实补丁的源文支持及改动边界。

## 文件绑定

- `experiments/agent_design/2026-10-08-business-granularity-v2/microsoft/opus-critic-02-envelope-recovery.json`：`5f899f3e934a9d16f442ee75587842347db4785f130e3e331c3ca78417107855`
- `experiments/agent_design/2026-10-08-business-granularity-v2/microsoft/revision-01/draft.json`：`698ec1f53c20017743a7a1e684c0247f1a97b910a2ed2e3fc796a24a66317edd`
- `experiments/agent_design/2026-10-08-business-granularity-v2/microsoft/revision-01/source_packet.json`：`3ffff553e0ca5f4c982cc0e5d9befcef986158343b949980e32791095e2610e1`
- `experiments/agent_design/2026-10-08-business-granularity-v2/microsoft/revision-01/skill.md`：`9baa6616f36095abc27b5de81cd6e9070beb509c97d6add7fade888b743904d0`

Opus recovered review已重新通过validate_review（153个check key完整、candidate hash一致、issues摘录存在）；这是契约校验，不是对16项意见全部语义背书。原API阶段failed和恢复记录均保持原样。
