# NVIDIA FY2025：真实响应的语义审阅

NVIDIA 候选已区分报告分部、市场和具名产品，三张收入图的年份、金额及独立分母正确。原调用因单一外层JSON围栏未通过格式检查；派生恢复不改变内容。仍需修正GeForce产品分组、补直接引用，并让推断关系可被程序识别。

由参与输入选择、PDF几何适配和验收标准准备的Codex代理审阅；不是盲评，也不是独立外部裁判。读取实际模型响应中的JSON，对照冻结官方PDF及其原文包逐项核查；只读去除唯一外层围栏后核对schema与金额，未改原始run或语义内容。NVIDIA曾用于人工参考图，因此本次属于跨公司迁移小试。

| ID | 检查 | 结果 | 实际观察 |
|---|---|---|---|
| NV-01 | 财年、原件与调用一致 | 通过 | 响应明确 company_id=nvidia、document_id=nvidia-fy2025-annual-report-10k、period_end=2025-01-26。三图都选择原表 Jan 26, 2025 表头。 |
| NV-02 | 报告分部与市场维度分开 | 通过 | seg_compute_networking、seg_graphics 标 reportable_segment；四个 mkt_* 节点标 business + role=market。没有创建 All Other 报告分部，也没有用市场收入反推分部金额。 |
| NV-03 | 具名业务身份与分组范围 | 需改善 | AI Enterprise、DGX Cloud、Jetson、DRIVE、GeForce NOW、RTX工作站、vGPU、Omniverse等已独立建对象。但 geforce_gpus 的 products_services 同时包含“游戏主机 SoC 与开发服务”。 |
| NV-04 | Omniverse、自动驾驶与信息娱乐的关系 | 通过 | Omniverse只有一个节点，reported_under→Graphics、supports→DRIVE。DRIVE与auto_infotainment分别关联Compute & Networking和Graphics。dc_compute→DRIVE的训练支持也有原文。 |
| NV-05 | 逐条声明的证据与收费口径 | 需改善 | 付费AI Enterprise/vGPU、DGX Cloud托管服务、Omniverse企业订阅/个人免费有依据。但nvidia的CUDA和客户清单、mkt_gaming的主播/广播者等、mkt_professional_visualization的Omniverse没有直接绑定对应支持块。dc_compute的客户清单也未绑000864。 |
| NV-06 | 报告分部收入勾稽 | 通过 | rev_reportable_segments_fy2025 选择133页表的2025列c002；Compute & Networking 116,193、Graphics 14,304，合并总额130,497。 |
| NV-07 | 终端市场与Data Center子层分母 | 通过 | rev_end_markets_fy2025：115,186 + 11,350 + 1,878 + 1,694 + 389 = 130,497，保留OEM and Other。rev_data_center_split_fy2025：102,196 + 12,990 = 115,186。 |
| NV-08 | 未知项与推断的机器消费边界 | 需改善 | unknowns正确保留具名产品收入、完整市场/分部映射和未读范围。但DRIVE→Compute & Networking、RTX工作站→专业可视化、Omniverse→专业可视化三条边在description写“推断”，仍作为普通 reported_under/part_of 输出。 |
| NV-09 | 原始格式失败与派生恢复的可追溯性 | 需改善 | run-02-model-view 的真实API已完成，HTTP200/end_turn；但正文唯一外层 ```json 围栏导致 StrictJSONError。仅去掉外层围栏后原对象通过validate_draft，19节点/24关系/3图；该恢复不再调用模型。 |

## 可核对的具体问题

### NV-01 财年、原件与调用一致

本轮使用原包的阅读视图；62块与100单元格的正文、ID、DOM/hash和网格不变，只去掉重复溯源元数据。所引用 source_sha256 指派生HTML；原官方PDF有单独指纹，不能混为一谈。

原文：`pdf-block-000818-e9d259bf`、`pdf-block-001430-b4b615e6`、`pdf-table-pdf133-revenue`、`pdf-table-pdf172-markets`。

### NV-02 报告分部与市场维度分开

同一产品可以有报告归属和市场用途。模型通过不同节点角色保留两种口径，并在 unk_market_segment_mapping 说明市场到分部的完整映射未确认。

原文：`pdf-block-000857-8c01a130`、`pdf-block-000858-fd83bcde`、`pdf-block-000859-b8b15350`、`pdf-block-000860-b924449f`、`pdf-block-001687-e27532ac`。

### NV-03 具名业务身份与分组范围

pdf-block-000873 把 GeForce GPU、GeForce NOW 和主机 SoC/开发服务列为游戏市场下的并列产品。内容真实，但当前聚合到名为 GeForce GPU 的节点会让消费方误以为主机方案属于 GeForce。宜分开，或用明确更宽的游戏产品组承接。节点总数19不等于这类身份问题已解决。CUDA仅在公司清单中出现，未单独建节点，不应冒称已验证共享CUDA对象的独立查询。

原文：`pdf-block-000845-97f1689d`、`pdf-block-000862-54188d9a`、`pdf-block-000869-03a707ef`、`pdf-block-000873-d85d83ed`、`pdf-block-000877-3df8e1b3`。

### NV-04 Omniverse、自动驾驶与信息娱乐的关系

归属和支持的主要业务含义合理，有具体段落。CUDA没有被复制成各市场的独立公司；当前只是公司产品清单，并非已生成共享技术节点。本项不把下面NV-08的推断标记缺口当成事实错归属。

原文：`pdf-block-000845-97f1689d`、`pdf-block-000858-fd83bcde`、`pdf-block-000859-b8b15350`、`pdf-block-000877-3df8e1b3`、`pdf-block-000879-67e00e9c`、`pdf-block-000880-4bf3817c`、`pdf-block-000881-d5b542b2`。

### NV-05 逐条声明的证据与收费口径

这些多数是绑定缺口：文字存在于输入，不是凭空编造。具体应核000845与000850–000855（公司产品/客户）、000854（游戏客户）、000877（专业可视化节点列出的Omniverse）、000864（计算客户）。AI Enterprise 的付费许可有产品直接证据；其“永久或订阅”来自公司软件许可总政策，宜明确标为一般政策，不据此保证该产品同时出售两种许可。DGX Cloud 已把一般云政策与自身未单列收费分开，这是合理谨慎。

原文：`pdf-block-000845-97f1689d`、`pdf-block-000850-f6b22599`、`pdf-block-000851-425ff406`、`pdf-block-000853-c123a33a`、`pdf-block-000854-17bf479f`、`pdf-block-000855-e28b83db`、`pdf-block-000864-baf70751`、`pdf-block-000869-03a707ef`、`pdf-block-000877-3df8e1b3`、`pdf-block-001440-6cf2f47b`、`pdf-block-001441-0f5d011a`。

### NV-06 报告分部收入勾稽

总额与两项直接由原表单元格读取，未误选2024、金额变化或百分比变化列。均非负且构成完整，环图适用；这是所选表的勾稽，不等于完整财报解析通过。

原文：`pdf-table-pdf133-revenue`、`pdf-block-001450-f7fcd32e`。

### NV-07 终端市场与Data Center子层分母

三图各自分母和年份准确。分部图与市场图是同一总收入的不同观察维度；Data Center内部图是子层，不能跨图加总，也不能把Compute/Networking子项再加入市场总图。未虚构单产品金额。

原文：`pdf-table-pdf172-markets`、`pdf-block-001450-f7fcd32e`。

### NV-08 未知项与推断的机器消费边界

模型没有隐藏推断，这一点有价值；也不据此认定三条归属事实错误。缺口在结构化消费：契约没有relation basis，消费方只看kind会将它们当确定关系。需新增可校验的推断标记与消费策略，或按当前Skill先保留unknown，而非让下游自行理解描述中的限定。

原文：`pdf-block-000855-e28b83db`、`pdf-block-000858-fd83bcde`、`pdf-block-000875-e91d2b93`、`pdf-block-000877-3df8e1b3`、`pdf-block-000879-67e00e9c`。

### NV-09 原始格式失败与派生恢复的可追溯性

原run保持失败，正文保持原样，恢复数据另存derived-01-single-fence；没有修改节点、关系、引用或收入选择。本次调用95.274秒，输入54,286/输出15,702 Token，估价$0.265592，非实付账单。图的实际渲染和链接检查由页面verification另记；本语义review不冒称视觉验收。

## 记录

- [原始响应，含外层围栏](../run-02-model-view/response.txt)
- [原run的StrictJSONError与调用用量](../run-02-model-view/result.json)
- [模型实际收到的原文阅读视图](../run-02-model-view/source_packet.json)
- [完整原文包](../input/source_packet.json)
- [预先验收标准](acceptance.zh-CN.md)
- [围栏恢复后的独立候选结果](../derived-01-single-fence/result.json)
- [只恢复外层格式的证明](../derived-01-single-fence/manifest.json)
- [机器可读审阅及产物指纹](semantic-review.json)

## 限制

- 本次为选段，不能据此认定全部10-K、PDF自动解析或其他公司已通过。
- 输入表格使用显式PDF几何适配；本审阅者参与输入准备，不称盲留出或独立第三方评价。
- 没有原生CUDA独立节点；没有重复造身份不等于共享技术对象的独立查询已验证。
- JSON围栏是实际格式违约；派生恢复只处理外壳，不能把原始run状态改成首次通过。
- 模型响应完整不等于全部语义正确；机器校验与三图勾稽不能替代逐声明证据审核。
- 未做浏览器视觉验收或多次稳定性测试；费用为本次成功API响应的估价，首次传输失败费用另记。

## 下一步

先固定“并列产品不能错并到狭义产品”“每条声明有自身引用”“推断关系有机器可识别状态”的契约与验收，再用同一冻结材料验证修正；保留本次原始和派生候选供对照。
