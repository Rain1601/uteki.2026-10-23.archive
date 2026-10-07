# 阶段 B 验收：sec-source-blocks-v0.1.10

状态：本地实现和程序验收完成；没有模型或网络请求。全文件结构扫描不等于逐段金融语义核验。

| 材料 | 标记导航块 | 实际搜索命中 旧→新 | Item 节点 | 保留块 / 单元格 |
|---|---:|---:|---:|---:|
| AMD | 105 | 105 → 0 | 23 | 1184 / 7429 |
| TSMC | 163 | 164 → 1 | 29 | 1929 / 67764 |

## 算法与消费者

A：完整短 Table of Contents 链接必须回到唯一、可见、已核对的目录位置，并按相同目标、标签和版式重复至少两次。字体大小/行高不参与版式分组，不推断 em/px 换算。目录本身、叙事句、单次链接、带页码变体、未知/隐藏/重复目标与整文 wrapper 回链保守保留。原文仅增 repeated_navigation 角色；块 ID、表格、单元格与锚点不变。

默认 DocumentReader search/read 实际省略这些块。search 返回省略总数及最多 12 个 ID；read 返回本页全部省略 ID。单块导航读取返回空正文，不自动改读其他块。Scoped Query 返回 layout_only、not_disclosed=false 和来源遍历 cursor；不计入已读正文。原始 document.html、reader.blocks 和显式提取 packet 仍保留全部块，不宣称所有模型入口均过滤。

B：v0.1.10 保留表格 type/ID/cells，只将单行两格的短 ITEM 编号/拉丁字母标题，与当前 Part、唯一目录身份、目录标题及准确源锚点共同核对。目录空 spacer 不再当成标题/页码；已核对目录锚点和页码用于新节点。嵌套、非拉丁标题、未知 Part、复杂财务表与冲突不发布 Item；正确目录标题但错误锚点仍留下边界，避免前一章吞入未确认内容。非表格长叙事中的 Item 引用不作为新版本边界。

Part/Item 范围只表示源文件连续导航区间，尾部布局块可收缩。TSMC Item 17 引用 Item 18，Item 18 引向 F-1；Item 19 后的签名、财务索引及 F 页不因落在连续范围内就属于 Exhibits 语义。

## 验证与复跑

本脚本执行 112 项聚焦离线检查。独立合成 Orion/2031 与 Acme/2031–2032 验证正反例、空导航、末尾/跨节点、cursor、另一公司作用域，以及版本拒绝。真实 AMD/TSMC 对照独立原 DOM oracle；每个新包 15 文件验证并在临时目录完整字节重建。

v0.1.7 和 v0.1.8 的 blocks、anchors、toc、index 四项按旧输入重放一致。旧包和原始 HTML 全部保持原哈希。旧完整 manifest 含当时实现指纹，完整字节重建仍需当时代码/环境；新包使用本轮最终共享实现指纹。两个新阶段分别选 .9 与 .10，不覆盖旧产物。

```sh
.venv/bin/python experiments/agent_design/2026-10-07-parser-navigation-v1/verify_stages.py --check
```

细节、样例响应、逐节点边界和文件 SHA-256 见 [stage-b-verification.json](stage-b-verification.json)。

[AMD document.html](stage-b-amd/document.html) · [TSMC document.html](stage-b-tsmc/document.html)

下一步：用户查看阶段验收页和源文件位置；之后再评估简报/结构化抽取。未覆盖格式应保留缺口，不根据这两份材料宣称所有发行人通用。
