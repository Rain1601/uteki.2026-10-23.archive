# TODO 03/04：财报原文换行丢失修复与解析缺口

本轮修复一个已在真实原件复现的通用缺陷：HTML `<br>` 原本被当作空串，表头和段落中的词因此粘连。`sec-source-blocks-v0.1.12` 将可见 `<br>` 保留为词边界，再执行现有空白正规化。原文、表格结构和普通内联标签不改写。

这项修复不是整个 TODO 03/04 完成。模型调用 **0 次**，网络调用 **0 次**。既有历史包未修改。

## 实际前后对照

| 冻结材料 | 原件片段 | 原解析 | 新解析 | 变化范围 |
|---|---|---|---|---|
| Microsoft FY2025 10-K | `Percentage<br>Change` | `PercentageChange` | `Percentage Change` | 9 块 / 20 格 |
| Alphabet FY2025 10-K | `Accumulated<br>Other<br>Comprehensive<br>Income (Loss)` | `AccumulatedOtherComprehensiveIncome (Loss)` | `Accumulated Other Comprehensive Income (Loss)` | 13 块 / 25 格 |
| AMD FY2023 10-K | `Notional<br>Amount` | `NotionalAmount` | `Notional Amount` | 31 块 / 73 格 |
| TSMC FY2023 20-F | `Year of<br>commencement<br>of commercial<br>production` | `Year ofcommencementof commercialproduction` | `Year of commencement of commercial production` | 28 块 / 52 格 |

原文归一化为单行，因此新解析的可见换行用空格表示，不保留版面行高。没有在每一个 span 前后机械加空格；`<span>1</span><span>,200</span>` 仍是 `1,200`。隐藏换行不制造空格，隐藏文字不进入产物。

## 可查看的新底稿

- [Microsoft：Percentage Change 表头](packages/msft/document.html#block-000572-59a607cb)
- [Alphabet：完整新底稿](packages/googl/document.html)
- [AMD：完整新底稿](packages/amd/document.html)
- [TSMC：完整新底稿](packages/tsmc/document.html)
- [完整来源身份、SHA-256、全部变化和验收记录](verification.json)

页面链接是程序渲染的解析底稿，不是模型精编。报告中全部变化保留原值、结果值、DOM、行列和新旧块 ID。以当前 JSON 中的 block ID 为精确定位依据。

## 已检查什么

四份材料逐块对照旧版和新版：块数、DOM 路径、印刷页码、表格行列数、合并格跨度与单元格坐标均不变。新旧原件哈希相同。全部新块正文与对应 DOM 的新版可见文本规则一致。各新包通过 15 文件完整性/结构校验。DocumentReader 对每份新包真实执行了改后短语的搜索，能够找到对应原文块。

| 材料 | 块数 | 表数 | 可见 DOM 文本段 | 无块包含的文本段 |
|---|---:|---:|---:|---:|
| AMD | 1,184 | 76 | 5,131 | 0 |
| TSMC | 1,929 | 506 | 14,727 | 0 |
| Microsoft | 1,401 | 85 | 6,316 | 0 |
| Alphabet | 1,338 | 185 | 6,708 | 0 |

这里“可见”依据现有 HTML 内联可见性规则；不等于浏览器计算过所有 CSS。DOM 包含检查不证明阅读顺序、表格含义、单位归属或完整金融语义正确。

46 项相关离线测试通过。其中新增独立 Lyra 2030 合成材料验证表头、单位、脚注文字、隐藏换行、普通内联数字、目录标题、页码误识别边界、旧版本行为、新包重建、原文读取，以及缺 company/document/snapshot/period 时拒绝输出。程序测试不代表模型提取质量。

复核：

```sh
.venv/bin/python -m unittest tests.unit.test_sec_line_breaks tests.unit.test_sec_parser_versions tests.unit.test_parsed_package tests.unit.test_sec_inherited_page_markers tests.unit.test_sec_navigation_stages tests.unit.test_sec_anchor_ownership tests.unit.test_document_reader tests.unit.test_sec_index_tables
.venv/bin/python experiments/agent_design/2026-10-07-foundation-parallel-v1/parser/verify.py --check
```

## 发布与消费者边界

`v0.1.12` 是显式可选新版本。生产 prepare 默认版本仍保留 `v0.1.11`，未静默替换既有输入。新版本受影响块的正文哈希和 block ID 会改变；index/package ID 与 manifest 也重新产生。历史证据必须继续绑定原来的包，不可把旧字符偏移直接套在新文本上。

目前数值记录的 `semantic_anchors.py` 使用旧版 `_visible_text` 和独立 DOM 字符范围恢复。将新包用于该消费者之前，需要让其明确识别解析版本，并用包含 `<br>` 的事实/表行回归验证偏移。本文验证了 DocumentReader，尚未验证新文本到数值记录/SQL 的全链路。这个适配问题不应以丢失原文换行为长期方案。

## 仍需完成的解析工作（按依赖）

1. **单位与脚注的归属验收。** 当前读取器仅把邻近标题/单位与紧随表格的带标记段落组合为上下文；它不证明某个数值关联了全部适用脚注。脚注跨页、脚注本身为 table、远处附注、币种/每股单位例外仍须专门验证。文字保留不等于语义关联已完成。
2. **跨节引用解析。** TSMC 原文 block 1047 明确说使用 Item 18 代替 Item 17；目前保留了这句话与章节导航，但没有提供该声明到财务附表的自动解析关系。不能把有目录/锚点等同于能自动跟读引用。
3. **NVIDIA PDF 路径。** 现有原件是官方 IR PDF，已有派生 HTML 是实验输入，不能当作新的整文 PDF 解析验收。需独立验证 PDF 原页、完整表格、坐标、页眉页脚与文本/图像内容边界。
4. **整文语义覆盖。** 四份 HTML 的全部可见 DOM 文本段均有块覆盖，只是结构证据。尚未逐节建立需读取/可排除/无法解析清单，也没有独立确认每张财务表及附注语义完整。

因此本轮只把“财报换行不再粘连”的受限缺陷标为修复。TODO 03/04 继续保留未完成，五家公司独立 Agent 端到端提取仍不是本报告的完成条件。
