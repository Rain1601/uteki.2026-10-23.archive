# Microsoft 独立 Agent 运行：参考对照页

此目录的 `build_comparison.py` 只用于**运行结束后的读取、渲染与比较**。它不调用模型，不修复提取内容。不要将本脚本、`reference-freeze.json`、参考产物或差异审阅文件加入提取请求。

## 参考版

参考运行是 `../2026-10-07-microsoft-clean-reextract-v1/completed-candidate-v2/`。这是 Sonnet 多轮生成、Codex 原文审阅与工程恢复后的 42 节点、45 关系结果。用户已认可本版图的表达；这不表示全部财务事实采纳或稳定自动提取验收。

冻结文件哈希见 `reference-freeze.json`。不改写旧运行、旧页、旧 Skill 快照。输入为 103 个已冻结块（含全部三个 Operating Segments 分部及主体元信息），不是整份 10-K。

## 新版展示

比较页：`docs/design/data-agent-acceptance/microsoft-agent-independent-v1/`。

左右各自使用本运行的 Mermaid 与证据映射；复用已认可的固定渲染基线，保留原始尺寸 / 适合宽度和节点跳转。新运行若失败或没有合法候选，右侧明确列出状态与原始文件入口，不借用参考图、不从参考补内容。结构通过、语义通过、视觉验收分别表示。

未交付状态可先生成：

```sh
.venv/bin/python experiments/agent_design/2026-10-07-microsoft-agent-independent-v1/build_comparison.py \
  --reference-run experiments/agent_design/2026-10-07-microsoft-clean-reextract-v1/completed-candidate-v2 \
  --reference-page docs/design/data-agent-acceptance/microsoft-clean-business-v1 \
  --output docs/design/data-agent-acceptance/microsoft-agent-independent-v1
```

候选交付后，先用 `build_agent_view.py --summary <新运行 summary.json> --output <新详情页目录>` 为**新运行**制作单独详情页并渲染 Mermaid。渲染后以相同参数追加 `--with-svg`。该适配器复用已有固定渲染器；根据真实账本区分首次生成与自动修订，显示全部尝试、费用和实际请求配置，不改旧页面或产物。

然后对比较页命令追加：

```text
--candidate-run <实际新运行目录>
--candidate-page <已核验的新详情页目录>
--execution-record <本轮真实执行记录 JSON>
--review <运行结束后的对照复核 JSON>
```

这些参数必须明确给出，不从目录猜测“最新运行”。对照页会核对运行、原文、输入、请求、产物与详情页哈希；`verification.json` 记录实际展示的版本。`--candidate-run` 没有对应图页时只交付未交付状态。

可选差异审阅格式：

```json
{
  "bindings": {
    "reference_business_map_sha256": "实际参考哈希",
    "candidate_business_map_sha256": "实际新候选哈希；无候选时为 null"
  },
  "summary": "本轮整体结论及边界",
  "checks": [
    {
      "topic": "业务覆盖 / 整体与子集 / 关系含义 / 引用支持等",
      "status": "实际复核状态",
      "reference": "参考版观察",
      "agent": "Agent 版观察",
      "evidence": "精确块或节点编号",
      "note": "差异原因与限制"
    }
  ]
}
```

节点数、中文译名或与参考完全相同不作为正确性标准。已有参考经过不同过程，故这是参考对照，不能标为严格模型 A/B。模型输入隔离与独立运行检查由执行侧保存；本展示程序不冒称能凭图证明输入独立。

本轮按项目约定检查数据、链接、SVG 节点映射及页面绑定，不进行浏览器视觉验收。
