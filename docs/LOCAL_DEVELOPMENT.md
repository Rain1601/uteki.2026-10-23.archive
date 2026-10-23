# 本地开发 / Local development

日期：2026-10-23。本页只写当前环境、测试和真实运行的命令。各批次的独立验收步骤、历次真实运行的查看命令保留在[历史记录](LOCAL_DEVELOPMENT_HISTORY_2026-10-23.md)；设计与实现状态见[核心设计](DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)。

所有命令都从仓库根目录运行。凭据、费用账本和含本机路径的运行记录不随 Git 同步。

## 1. 环境

Python 3.11+（当前复现用 3.13），依赖由 `uv` 按根 `uv.lock` 安装。Node.js 20+ 只在前端检查和 OpenSpec 工具时需要。

| 环境 | 用途 | 安装 |
|---|---|---|
| 主开发环境 `.venv` | 日常开发、核心离线检查（editable） | 见下方第一条命令 |
| SDK 验收环境 | agent 单元/集成测试、真实运行；**必须非 editable** | 见“SDK 验收环境” |
| 只装 data 的环境 | `test_content_processes`（要求没有 agent SDK） | 见“只装 data 的环境” |
| M0 独立环境 | 只用于复现 M0 历史探针，锁在 `requirements/m0.txt` | 见历史记录“M0 独立验证环境” |

**主开发环境：**

```bash
uv sync --locked --python 3.13 --extra analysis --extra data --extra mcp
```

```bash
uv pip check --python .venv/bin/python
```

需要 Agent SDK 路径时加 `--extra agent`，需要 PDF 解析时加 `--extra pdf`。主环境默认不装 agent extra，所以 **agent 测试不要在 `.venv` 里跑**：缺 `claude_agent_sdk`、SDK 版本也和冻结 profile 不一致，会出现大量与代码无关的失败。

**SDK 验收环境（非 editable）：**

```bash
uteki_sdk_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-sdk.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_sdk_env/venv" uv sync --locked --python 3.13 --extra data --extra agent --no-editable
uv pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_sdk_env/venv/bin/python"
uv pip check --python "$uteki_sdk_env/venv/bin/python"
"$uteki_sdk_env/venv/bin/python" -I -c "import importlib.metadata as m, uteki; print(m.version('openai-agents'), m.version('claude-agent-sdk'), uteki.__file__)"
```

应输出 `0.24.0 0.2.167`，且 `uteki.__file__` 位于该环境的 `site-packages`。**源码改动后必须重跑第二行 `--reinstall-package`**，否则测试的是旧代码；`uv sync` 可能复用旧 wheel。

**只装 data 的环境：**

```bash
uteki_data_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-data.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_data_env/venv" uv sync --locked --python 3.13 --extra data --no-editable
```

**规则：**

- 运行 Python 一律加 `-I`，不用 `PYTHONPATH=src` 或改 `sys.path` 代替安装。
- 升级 SDK 先核对官方发布说明，再同步主锁、`config/data_platform/model-profiles/` 里的 `sdk_version` 和必要回归；不用浮动版本。
- 当前版本：OpenAI Agents SDK 0.24.0、openai 3.31.0、Claude Agent SDK 0.2.167（CLI 2.1.300）、MCP 2.2.0、DuckDB 1.5.5、Docling 2.139.0。

## 2. 测试

测试用标准库 `unittest`。测试目录没有 `__init__.py`，用 `discover -s` 运行。覆盖范围和 core / `--integration` 的划分见 [OFFLINE_TESTS.md](OFFLINE_TESTS.md)。

**核心离线回归（主环境，不调用模型、不下载）：**

```bash
.venv/bin/python scripts/run_offline_checks.py
```

```bash
.venv/bin/python scripts/check_workspace.py
```

`run_offline_checks.py --list` 列出选择器，`--integration` 运行集成组；`check_workspace.py` 在本地资料缺失时返回 2。

**新核心测试（SDK 验收环境）：** 在临时目录里运行，避免从仓库根误导入源码。

```bash
uteki_repo="$PWD"
cd "$uteki_sdk_env"
./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_repo/tests/unit/data_platform" -p 'test_*.py'
./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_repo/tests/unit/data_platform_agent" -p 'test_*.py'
./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_repo/tests/integration/data_platform" -p 'test_*.py'
./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_repo/tests/integration/data_platform_agent" -p 'test_*.py'
cd "$uteki_repo"
```

- `integration/data_platform_agent`（125 项）会启动本机回环服务和随包 Claude CLI，需要允许监听 127.0.0.1 和子进程；全组约 16 分钟。全部使用合成响应，`real_model_calls=0`，只验证接线。
- `integration/data_platform` 里的 `test_content_processes` 在 SDK 环境中**按设计会失败**（它断言 agent SDK 未安装），改在只装 data 的环境里运行：

```bash
(cd "$uteki_data_env" && ./venv/bin/python -I -m unittest discover -s "$OLDPWD/tests/integration/data_platform" -p test_content_processes.py)
```

**单个文件或单个用例：**

```bash
.venv/bin/python -I -m unittest discover -s tests/unit/data_platform -p test_catalog.py
```

```bash
"$uteki_sdk_env/venv/bin/python" -I -m unittest discover -s tests/integration/data_platform_agent -p test_gateway_claude.py -k test_missing_generation_or_bill -v
```

**前端与规范检查：**

```bash
npm run spec:check
```

## 3. 真实运行

真实模型调用会计入共享账本，**每批都需要用户事先授权金额和次数**（AGENTS.md）。入口是 `examples/data_platform/live_function.py`，在 SDK 验收环境中运行；官方 SDK 负责循环，不接受答案、脚本响应或隐式数据根。

| 子命令 | 作用 | 是否调用模型 |
|---|---|---|
| `inspect --manifest M` | 查看批次、各 lane 状态、根账本累计次数与费用、未核账预留 | 否 |
| `prepare` | 为已授权批次冻结业务 context、profile、限额，复制指定数据根 | 否 |
| `prepare-attempt --manifest M --lane L --attempt-key K --output N` | 在原账本下为某 lane 登记新会话（同 key 幂等，换 key 也不重置次数） | 否 |
| `extend-allowance --manifest M --authorization A --output N` | 按用户显式授权文件修订原账本金额或次数 | 否 |
| `run --manifest M --lane L --work W --env-file .env` | 执行一条 lane；`W` 必须是尚不存在的私密目录 | **是** |
| `reconcile --manifest M --lane L --env-file .env --output O` | 只查询既有 OpenRouter 请求的账单，不发模型请求 | 否 |
| `retain-reservation` | 记录用户确认保留某个完整响应的未核账预留 | 否 |
| `export --manifest M --lane L --output O` | 从已提交交付重新导出 JSON/Markdown/CSV，不重跑 Agent | 否 |

**规则：**

- 运行前先 `inspect`，确认剩余金额、次数和未知费用；不要凭新的 `--work` 目录判断还有额度。
- 凭据只放在本机 `.env`（权限 600）：`DEEPSEEK_API_KEY`、`OPENROUTER_API_KEY`；不在命令行传密钥。
- 网络临时故障每阶段最多一次已授权重试；格式或内容错误不当网络故障重试。存在未知费用时先对账。
- 已有运行目录和已有导出目录都会被拒绝覆盖；不要删目录或改 manifest 强行重跑。
- 当前根账本：上限 $40 / 787 次（以 `inspect` 的实时输出为准）。历次批次的 manifest 在 `output/data-agent-*/` 下。

**SEC 原件取数**只用 `query_cli agent acquire` / `prepare_sources`，联系信息由 `resolve_sec_contact` 从私密配置读取；用法见 [DATA_AGENT_CLI.zh-CN.md](DATA_AGENT_CLI.zh-CN.md)（S3 迁移后更新）。

## 4. 文档库与 PDF

文档库存储在显式数据根下的 `documents.sqlite` 和 `objects/`；本机当前数据根是 `data/data_agent_documents/`（不随 Git）。普通查询不导入 Docling、不重新解析、不调用模型。

```bash
uteki_py="$uteki_sdk_env/venv/bin/python"
"$uteki_py" -I -m uteki.data_platform.documents --data-root "$PWD/data/data_agent_documents" find
```

```bash
"$uteki_py" -I -m uteki.data_platform.documents --data-root "$PWD/data/data_agent_documents" schema --parse-id apple-2025-native-passages-v1
```

```bash
"$uteki_py" -I -m uteki.data_platform.documents --data-root "$PWD/data/data_agent_documents" passage --parse-id apple-2025-native-passages-v1 --path 'PART_I.Risk_Factors.Business_Risks.passages[0]'
```

- 其他子命令：`browse`、`query --request <json>`、`read --reference <json>`、`section --parse-id … --code-path …`、`export`、`reindex`（从冻结包重建投影）、`init`、`put-object`、`publish`。`--data-root` 必须是已存在的绝对目录。
- 当前 Agent 使用的解析版本：`apple-2025-native-passages-v1`、`alphabet-2025-native-passages-v1`（非默认版本，需按 parse_id 显式指定）。
- 合成示例（临时目录，无网络）：`examples/data_platform/documents.py --data-root <空的绝对目录>`。

**解析新 PDF**：入口 `python -m uteki.data_platform.documents.pdf`，需要 `pdf` extra 和预下载的本地权重（`data/model_cache/docling`，转换时禁止联网）。材料元数据显式提供，不从文件名推断；页范围或策略变化必须用新 parse_id。权重下载与参数见历史记录“真实 PDF 本地解析”一节。

**浏览数据库**（独立工具环境，只监听本机）：

```bash
UV_TOOL_DIR=/tmp/uteki-viewer-tools uv tool run --from datasette==0.65.5 datasette serve data/data_agent_documents/documents.sqlite --host 127.0.0.1 --port 8001 --metadata data/data_agent_documents/viewer.json
```

打开 `http://127.0.0.1:8001/documents/inspect_materials`（另有 `inspect_directory`、`inspect_blocks`、`inspect_table_cells`）。

## 5. HTML/iXBRL 程序入口

| 入口 | 作用 |
|---|---|
| `examples/data_platform/official_html.py` | 从冻结获取结果建设并发布官方 HTML/iXBRL 材料 |
| `scripts/data_agent/verify_html_material.py` | 用验收侧冻结文件独立核对发布结果 |
| `examples/data_platform/data_tools.py` | 用显式请求调用六工具并输出结果 |
| `scripts/data_agent/verify_tool_delivery.py` | 独立读回原件、核对引用与计算 |

都需要显式的隔离数据根和请求文件；验收用的 gold 只给验证脚本，不给产品入口。完整参数示例见历史记录对应章节。

## 6. 工作台与资料恢复

旧审阅工作台（依赖旧代码，计划在 S4 处理）：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
```

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
```

`--check` 只检查必需输入，不启动服务。启动后打开 `http://127.0.0.1:8765/agent-results`。

**资料清单与恢复。** 路径相对仓库根。恢复时保留原字节、版本目录、清单和审核记录，不重新赋予 frozen/adopted 状态。

| 内容 | 路径 | 用途与恢复方式 |
| --- | --- | --- |
| 公司名单 | `data/company_universe/v0.1-candidate/companies.json` | 公司导航与报告审核必需；从原环境恢复 |
| 材料目录 | `data/document_library/alphabet/catalog.json`（可选 `earnings.json`） | Alphabet 子页加载；目录里的相对路径须可解析 |
| 已发布研究数据 | `data/research_data/alphabet_2025_10k/v0.2-candidate/` | 业务图、指标和公司页面必需；恢复清单声明的全部文件 |
| 完整年报及图片 | `data/source_documents/alphabet_2025_10k/source.html.gz`、`assets/` | 原文阅读与索引重建；解压后须匹配来源清单 SHA-256 |
| 版本化索引 | 来源目录的 `indexes/`，及材料目录记录的 `index_folder` | 目录导航和精确证据链接 |
| 候选与审核决定 | `benchmarks/alphabet_2025_business_map/v0.2-candidate/`、`v0.3-candidate/` | 后续构建需要对应候选及 `review_decisions.json` |
| PDF 资料 | `data/reading_library/alphabet/download_manifest.json` 及声明 downloaded 的文件 | 可选阅读功能 |
| 个人审核历史 | `data/research_archive/state.json` | 可选；只从可信原状态恢复 |
| 新核心文档库 | `data/data_agent_documents/`、`data/model_cache/docling/` | 已入库的 Apple/Alphabet 2025 10-K 原件、解析包和本地解析权重 |

建议先把原工作区恢复到单独目录，用 `check_workspace.py --root <目录> --json` 比对，再补齐缺失路径；同一路径已有不同字节时先核对版本和来源，两份都保留。

**已知证据完整性缺口：** 已提交摘录第 90 段按 `sec.text_hash` 规则重算的指纹与存储值不一致（证据 `e-platforms`）。在取得完整固定源文件前不修改原文、摘录或指纹；`scripts/smoke_research_workflow.py --strict-all` 因此返回 1，这个失败应保留。

**仓库归档与恢复**：见 [REPOSITORY_RETENTION.zh-CN.md](REPOSITORY_RETENTION.zh-CN.md)。
