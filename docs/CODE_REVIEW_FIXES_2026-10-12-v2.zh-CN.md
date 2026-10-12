# Review 五项根因修复 · 2026-10-12

针对基线 `07f05f07` 的五个确认问题，完成共同责任层修复与离线回归。未调用模型、未修改冻结运行和账本。历史报告保持；原两张图片包和 v5 dataset 不在本机，未声称真实原图重新验收。

| ID / 级别 | 原现象与根因证据 | 机制修复 | 回归结果 |
|---|---|---|---|
| R25 / P1 | pyproject 加入 Pillow，uv.lock 未同步；文档中的 --locked 安装命令直接拒绝 | 锁定 Pillow 12.3.0，保留既有其他包与锁格式 | 实际 uv sync --locked 安装成功，再次 dry-run 无变更 |
| R26 / P2 | 获取入口绕过既有 SEC 私密配置解析器，将真实联系人写进追踪源码 | 获取时显式 CLI / 环境 / mode-600 .env 解析；缺少身份先拒绝，纯重放不读取联系人 | 两公司实际调用配置、三种入口、无日志/summary 泄漏、缺失前置拒绝和 acquisition 原件重放通过 |
| R27 / P2 | 消费者只验证选中 OCR 命中存在，生产端判断全部角度候选歧义与物理位置复用；合法重封包可得到矛盾状态 | 生产与 v3 消费共同调用全库存确定性定位机制；v1/v2 继续明确较弱历史状态 | 原多位置反例、其他角度歧义和位置复用均拒绝；合法多角度和历史兼容通过 |
| R28 / P2 | retrieval cycle 人工组件清单漏掉 selection_contract / output_limit，行为改变未改变运行指纹 | 将两个实际行为依赖加入实现封存 | 实际 cycle fixture 含两文件 hash；独立临时源码变动分别改变绑定，无生产文件变动 |
| R29 / P2 | unknown reserved_usd 直接进入 Decimal；异常越过 ValueError 单记录边界，拖垮完整列表 | 金额必须合法、有限、非负；Decimal 聚合异常统一转换为 ValueError，保留严格加载 | invalid、NaN、Infinity、负数与结构错误隔离；有效邻记录继续可查，0 和有效预留保持 |

本次整合：118 项定向 Python 检查通过；portable core 576 Python + 37 JavaScript 通过；git diff --check 通过。检查有覆盖重叠，不作为业务验收分数。定向命令：

```bash
.venv/bin/python -m unittest tests.unit.test_preparation_acceptance_entrypoint tests.unit.test_sec_settings tests.unit.test_figure_grounding tests.unit.test_figure_materials tests.unit.test_figure_acquisition tests.unit.test_claude_vision tests.unit.test_retrieval_cycle tests.unit.test_agent_runs_e6 tests.unit.test_agent_result_routes tests.unit.test_agent_results_page
.venv/bin/python scripts/run_offline_checks.py
uv sync --locked --extra analysis --extra data --extra mcp
```

R26 移除当前源码联系人，不重写 Git 历史；私密配置和原始获取记录不上传。OCR 回归验证原 review 工程反例及独立合成输入，不替代 Codex 原图内容核验。预算/原包缺失仍显式保留。

下一项 **03-M3**：按需图片消费。先接入有 scope/hash 校验的 discovery/read，再完成显式图片选择、最终交付和双审引用契约；不能把读取图片等同于旧文字阅读要求完成，不能自动把探索转录加入交付。真实回归依赖原图片包、v5 dataset、累计费用证据迁移。本机图片生产端仍选 AiHubMix，与用户既有禁用约束不符；本轮不执行该入口，不用重新转录或新账本冒充恢复。
