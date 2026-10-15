# 本地开发与资料恢复 / Local development and data recovery

当前 Python 环境安装以本页“从新检出仓库开始”和“M0 独立验证环境”为准。2026-10-08 的 [交接说明](MACHINE_HANDOFF.zh-CN.md) 保留历史私密状态迁移与资料恢复边界，不作为当前依赖安装入口。

## 当前交付状态

2026-09-22 更新：仓库已包含公司名单、部分完整公开材料与索引、研究数据发布，以及 Data Agent 查询快照和历史样例。后续开发顺序、已知边界和换机器交接见 [开发待办](../TODO.md)。凭据、费用账本和含本机路径的运行元数据不随 Git 同步。

2026-09-18 接手时部分资料尚未取得；下文保留恢复方法供实际缺失时使用，不表示列出的文件现在都缺失。新环境先运行工作区检查确认本次检出的状态。离线检查通过不代表 M0 验收、完整年报核验、模型质量达标或历史人工审核已恢复。

## 从新检出仓库开始

项目声明 Python 3.11+；本轮环境复现使用 Python 3.13。Node.js 20+ 仅在使用对应前端/开发规范工具时需要，Python 安装与 M0 探针不需要 Node。归档存储使用 POSIX 文件锁。

两套环境安装同一个 Uteki Python 包，但依赖锁分别管理：

| 环境 | 依赖声明 | 安装依据与边界 |
|---|---|---|
| 主开发环境 | 根 `pyproject.toml`，按需选择 analysis/data/mcp extras | 根 `uv.lock`；Data Agent 开发基线选这三个 extras，不包含 Claude M0 验证依赖 |
| M0 SDK 验证环境 | 根 `pyproject.toml` 的基础依赖 + `requirements/m0.in` | `requirements/m0.txt` 的 40 个固定版本，Python 3.13；独立环境保留已验证 SDK 组合，不与主锁混用 |

不提供 `m0` extra：该声明已迁到 `requirements/m0.in`，避免主项目元数据声明了一套未进入主锁的独立环境。两个锁允许共同包版本不同；升级须针对对应环境重新验证，不靠合并锁或整体升级消除差异。以下命令均从仓库根运行；首次安装依赖/构建工具可能联网，不请求模型、不需要 API 密钥。

```bash
uv sync --locked --python 3.13 --extra analysis --extra data --extra mcp
uv pip check --python .venv/bin/python
.venv/bin/python -I -c "import uteki, uteki_eval, agents, duckdb, pydantic, lxml.etree, mcp"
```

`uv sync` 默认把项目安装为 editable，适合日常改代码；依赖仍按锁安装，锁与声明不一致时 `--locked` 会报错。环境验收应使用全新目录和普通安装，不能只依赖已有 `.venv`：

```bash
uteki_env_root="$(mktemp -d "${TMPDIR:-/tmp}/uteki-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_env_root/main" uv sync --locked --python 3.13 --extra analysis --extra data --extra mcp --no-editable
uv pip check --python "$uteki_env_root/main/bin/python"
"$uteki_env_root/main/bin/python" -I -c "import uteki, uteki_eval, agents, duckdb, pydantic, lxml.etree, mcp; print(uteki.__file__)"
```

导入位置应在该新环境的 `site-packages`，不能指向仓库 `src/` 或旧虚拟环境；`-I` 排除环境变量、用户 site 和当前目录对 Python 导入的影响。保留实际 Python/平台、安装日志、包版本和未运行检查，不能把一台机器通过表述为所有平台已验证。安装数据依赖不等于存储草稿或业务功能通过验收。

现有离线检查可按需要运行，覆盖范围见 [OFFLINE_TESTS.md](OFFLINE_TESTS.md)：

```bash
.venv/bin/python scripts/run_offline_checks.py
.venv/bin/python scripts/smoke_research_workflow.py
.venv/bin/python scripts/check_workspace.py
```

上述检查不请求模型、不下载资料、不需要 API 密钥。测试和流程演练只向临时目录写审核状态。`analysis` 扩展用于离线假模型及报告契约测试；`data` 扩展提供 DuckDB/Pydantic，`mcp` 提供 MCP 入口依赖。

`check_workspace.py` 在资料缺失时返回 **2**，同时列出必需文件和可选功能缺口；以实际输出为准，不预设新检出一定失败。可用 `--json` 获取结构化清单，或 `--root /path/to/recovered-checkout` 只读检查另一份候选工作区。检查会核对研究发布清单里的文件指纹、材料索引指纹和原文整体指纹；它不替代真实页面验收。

资料恢复后启动：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/agent-results`。后台主导航只有“运行结果”和“运行过程”。根地址 `/`、`/companies` 和未选择材料的 `/data-workspace` 均以 HTTP 303 转到结果页。显式数据产物、原文、公司报告审核继续作为明细工具保留。启动会先检查必需输入；缺失或损坏时在绑定端口、迁移或初始化审核库之前退出。`--check` 即使检查通过也不启动服务、不写审核状态。完整来源、索引和分析扩展的缺口会单独报告。

完整本地回归的命令和覆盖边界见 [OFFLINE_TESTS.md](OFFLINE_TESTS.md)。`scripts/run_offline_checks.py --integration` 保留原测试失败与跳过结果，不会用占位资料补齐历史实验。

## M0 独立验证环境（2026-10-14）

选择尚不存在的环境路径，保留以前的运行结果。以下以 `output/m0-sdk/.venv` 为例；如已存在，显式更换路径，不覆盖旧环境或证据：

```bash
uv venv output/m0-sdk/.venv --python 3.13
uv pip sync requirements/m0.txt --python output/m0-sdk/.venv/bin/python
uv pip install --reinstall-package uteki-eval --no-deps . --python output/m0-sdk/.venv/bin/python
uv pip check --python output/m0-sdk/.venv/bin/python
output/m0-sdk/.venv/bin/python -I -c "import uteki, agents, openai, claude_agent_sdk, mcp; print(uteki.__file__)"
output/m0-sdk/.venv/bin/python -I scripts/run_sdk_probe.py --python output/m0-sdk/.venv/bin/python --fixture config/sdk_probe/fixture.json --profiles config/sdk_probe --output output/m0-sdk/probe.json
output/m0-sdk/.venv/bin/python -I -m unittest discover -s tests/unit -p test_sdk_probe.py -v
```

先同步锁定依赖，再以 `--no-deps` 普通安装当前项目，避免项目安装重新解析/升级已冻结依赖。源码修改后须用 `--reinstall-package uteki-eval` 强制重新构建并安装项目：本批曾观察到普通 sync 复用旧 wheel，安装成功本身不能证明测试的是当前源码。主环境使用普通安装验收时同样适用，替换 `--python` 为该环境解释器，并核对模块来源和文件 hash。`uv pip sync` 会移除未列在 requirements 中的包，因此每次重新同步后仍须重新安装 Uteki。不再用 `PYTHONPATH=src` 或入口脚本修改 `sys.path` 代替安装；独立 worker 使用 `-I` 从所选环境加载已安装包，父进程凭据/设置仍按原规则隔离。

M0 入口只接受合成 fixture/profile，并在场景内禁止网络与子进程；此命令不运行真实模型或原生 Claude CLI 循环。安装验证、15 项已有离线测试、9 个 SDK 合成场景与业务验收分别报告。输出路径已存在时会失败，须选新路径保留旧结果。

仅检查声明能否解析为现有 M0 锁、不升级版本时，可生成临时结果并比较包名/版本集合（不能覆盖原锁来消除差异）：

```bash
uv pip compile pyproject.toml requirements/m0.in --python-version 3.13 --constraint requirements/m0.txt --no-header --no-annotate --output-file output/m0-sdk/resolved-check.txt
```

有意升级 M0 时才重新生成 `requirements/m0.txt` 并复验；主锁仍由主项目维护。安装依赖的下载缓存可复用，旧虚拟环境的已安装包不能充当新环境验收结果。当前机制遵循 [uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/) 及 [requirements 锁定流程](https://docs.astral.sh/uv/pip/compile/)。

## 原件存储与输入清单的独立验收（2026-10-14）

此切片只需要主锁的 `data` extra；不另设依赖锁，也不改变主开发环境与 M0 的关系。使用普通安装、独立进程和合成数据验证；这组检查使用以下专用入口，未加入依赖源码路径注入的旧离线 runner。以下命令从仓库根运行，临时环境与数据根均显式指定：

```bash
uteki_content_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-content-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_content_env/venv" uv sync --locked --python 3.13 --extra data --no-editable
uv pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_content_env/venv/bin/python"
uv pip check --python "$uteki_content_env/venv/bin/python"
"$uteki_content_env/venv/bin/python" -I - <<'PY'
import hashlib
import importlib
from pathlib import Path
import sys

for name in ("uteki.data_platform.contracts.content", "uteki.data_platform.content.store"):
    origin = Path(importlib.import_module(name).__file__).resolve()
    source = Path("src").joinpath(*name.split(".")).with_suffix(".py")
    assert origin.is_relative_to(Path(sys.prefix).resolve()), origin
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(origin.read_bytes()).digest(), name
    print(name, origin)
PY
"$uteki_content_env/venv/bin/python" -I -m unittest discover -s tests/unit/data_platform -p test_content.py -v
"$uteki_content_env/venv/bin/python" -I -m unittest discover -s tests/integration/data_platform -p test_content_processes.py -v
uteki_content_root="$(mktemp -d "${TMPDIR:-/tmp}/uteki-content-data.XXXXXX")"
"$uteki_content_env/venv/bin/python" -I tests/fixtures/data_platform/store_worker.py example "$uteki_content_root"
```

示例写入合成 HTML、附图及一个明确缺失的附件，保存清单后重新打开存储并读回。完整契约、错误码、25 项测试的覆盖及未验证边界见核心设计 14.3.1、14.12.9；对象/清单可读不等于来源身份已核验或快照已发布。该切片要求支持硬链接和目录 fsync 的本地 POSIX 文件系统。

## Agent 执行监控（2026-10-06）

启动工作台后打开 [Agent 运行](http://127.0.0.1:8765/agent-runs)。默认可回看两次已登记真实历史运行：`amd-fy2023-main-agent-v2-parent`（6 个父步骤、1 个提取任务、7 次调用）和 `amd-fy2023-cash-flow-main-agent-v2-parent`（7 个父步骤、1 个提取任务、8 次调用，以 `no_progress_limit` 停止）。从步骤展开子任务、输入、候选与用量；查看不会调用模型或改变采纳状态。历史记录没有心跳，也不会补造未保存的工具耗时。

要观察新的本地执行，工作台启动时同时提供观测目录和允许读取的业务输出父目录：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app \
  --host 127.0.0.1 --port 8765 \
  --observation-root "$HOME/.local/state/uteki/observations" \
  --observation-output-root "$HOME/.local/state/uteki/runs"
```

`--observation-output-root` 可以重复指定；它是新运行目录的父目录，而非某个运行的目录。Data CLI 的 `agent query / extract / extract-batch` 使用同一个 `--observation-root`，输出例如 `--output "$HOME/.local/state/uteki/runs/query-001"`。具体请求、模型与批次参数见 [Data Agent CLI](DATA_AGENT_CLI.zh-CN.md#执行监控与历史导入2026-10-06)。这些执行命令仍按显式配置调用模型；开启工作台或读取历史本身不调用模型。

观测目录、业务输出和冻结数据须分开，输出必须是新目录，路径中不能含符号链接。观测目录保存本机运行位置，应放在仓库之外，或使用已忽略的 `data/agent_observability/local/`。每棵执行树只由一个本机进程写入；当前不支持跨进程续写同一执行树、多机调度或中断续跑。未加观测参数的执行不会自动成为实时运行。

页面可见时每 2 秒增量读取，隐藏时暂停。未结束运行的心跳超过 15 秒未更新，会显示连接中断、执行状态未知；已完成运行保持完成。只有开始记录或供应商用量未确认时，Token 和费用保留未知；界面分别显示本运行与含子任务的已知用量，估算费用不等于实际账单。

新增历史记录使用显式导入，不从实验目录自动选择：

```bash
./.venv/bin/python scripts/import_agent_run.py \
  --root "$PWD" --spec /absolute/path/new-run-spec.json
```

spec 的字段与适配范围见 [历史导入说明](DATA_AGENT_CLI.zh-CN.md#执行监控与历史导入2026-10-06)。导入只新增 `data/evaluation_views/agent-runs-v1.json` 的登记和展示摘要，保留原 manifest、产物和失败记录。来源、哈希、父子关系不匹配或 ID 已存在时拒绝；导入工程页也不代表已经登记到旧财务查看页。

## AiHubMix 最小连接测试

在项目根目录的 `.env` 中填写 `AIHUBMIX_API_KEY`，文件权限须为 `600`。也可通过环境变量配置；已有的 `AI_HUB_MIX_API_KEY` 别名仍受支持。脚本不会输出密钥，`.env` 已被 Git 忽略。

安装 `analysis` 扩展后，可显式指定模型和一个全新的结果目录：

```bash
.venv/bin/python scripts/smoke_aihubmix.py \
  --model gpt-5.4-mini \
  --output-dir /private/tmp/uteki-aihubmix-probe-001
```

此命令会调用真实模型。验收仅包含：模型调用一个本地工具取得随机校验码，再通过结构化字段返回同一校验码。最多两轮模型响应，每轮最多 1000 个输出 Token，总超时 90 秒；不会读取公司资料或运行研究任务。结果与请求费用记录写入指定目录，已有目录不可覆盖，失败返回非零退出码。

默认本地估算预算为 0.10 USD。当前登记的 `aihubmix/gpt-5.4-mini` 价格快照日期是 2026-09-13；估算不是实际账单，也不是服务商强制扣费上限。其他模型须先有明确价格记录。失败且用量未知时保留未知费用，不自动重试。离线脚本测试不能代替这次真实连接验证。

Claude 5.5 使用明确的版本名：`--model claude-opus-5-5` 或 `--model claude-sonnet-5-5`，每次使用新的输出目录。2026-10-06 核对的 AiHubMix 标价为：[Opus 5.5](https://aihubmix.com/model/claude-opus-5-5) 输入 4 USD / 百万 Token、输出 20 USD / 百万 Token；[Sonnet 5.5](https://aihubmix.com/model/claude-sonnet-5-5) 输入 2 USD / 百万 Token、输出 10 USD / 百万 Token。本地估算按普通输入/输出价格计算，不计缓存读折扣、缓存写费用或账户优惠。测试仍通过当前 OpenAI 兼容适配器执行，结果只说明指定端点的兼容性，不证明模型身份或研究质量。

2026-10-06 真实测试：两款 Claude 5.5 首次均调用了工具，但最终输出在 SDK 结构校验时出现 `ModelBehaviorError`。测试脚本补充明确的 JSON 格式及字段定义后，两款均通过随机工具值与结构化结果的一致性检查。该结果证明“明确格式提示 + 本地校验”链路可用，尚不能确认网关是否强制执行 `response_format=json_schema`。首次失败与复测共 8 次请求，按登记价格估算 0.014390 USD；不等于实际账单。每款只验证一个合成任务，没有评估财务研究质量或长期稳定性。

## 资料清单与恢复方式

路径均相对仓库根目录。恢复已有文件时保留原字节、版本目录、清单和审核记录，不重新赋予 frozen/adopted 状态。

| 内容 | 路径 | 用途与恢复方式 |
| --- | --- | --- |
| 原公司名单 | `data/company_universe/v0.1-candidate/companies.json` | 公司导航与报告审核必需；从原环境恢复，沿用原公司集合 |
| 材料目录 | `data/document_library/alphabet/catalog.json`，以及可选 `earnings.json` | Alphabet 所有正式子页都会加载；目录中的相对路径须保持可解析 |
| 已发布研究数据 | `data/research_data/alphabet_2025_10k/v0.2-candidate/` | 业务图、指标和公司页面必需；恢复 `manifest.json`、`evidence_bundle.json`、`business_map.json` 及清单声明的全部文件，例如 `query.json` |
| 完整年报及图片 | `data/source_documents/alphabet_2025_10k/source.html.gz`、`assets/` | 原文阅读、索引重建及独立验证；解压后的 HTML 须匹配现有来源清单 SHA-256 |
| 版本化索引 | 上述来源目录的 `indexes/`，以及材料目录各条记录指向的 `index_folder` | 目录导航和精确证据链接；保持 `manifest.json`、`index.json`、`blocks.jsonl`、`assets.json` 及引用图片一致 |
| 候选与审核决定 | `benchmarks/alphabet_2025_business_map/v0.2-candidate/`、`v0.3-candidate/` | 后续研究数据构建需要对应候选及 `review_decisions.json`；已提交的 v0.1 不能代替这些版本 |
| 历史报告及读取轨迹 | `experiments/analysis_comparison/`、`experiments/document_reader/` 及相应 Cloud 实验目录 | 恢复原报告、成本、校验与精确引用；没有实验时允许空报告列表，但历史回归不能据此通过 |
| PDF 资料 | `data/reading_library/alphabet/download_manifest.json` 及声明 downloaded 的文件 | 可选阅读功能；保持清单中的相对文件路径 |
| 个人审核历史 | `data/research_archive/state.json` | 可选；只从可信原状态恢复。没有该文件可以开始新的空档案，但无法据此还原过去的修订、采纳或撤回 |

建议先将原工作区恢复到单独目录，用 `check_workspace.py --root ... --json` 检查和比对；再按文件清单补齐当前工作区中缺失的路径。若同一路径已有不同字节，先核对版本和来源，保留两份以待审查。凭证不属于资料恢复包，模型执行前另行配置。

恢复后从运行结果进入已登记产物，明确选择公司、数据集和材料，核对原件、财务候选与证据。历史公司报告保留显式 `/companies/<company>/reports` 地址。真实人工采纳仍由研究者执行；离线演练的模拟采纳不会被导入。

## 历史恢复边界（2026-09-18 记录）

以下记录当时缺失输入带来的限制；部分输入现已提交，当前是否具备构建条件须检查实际文件及其指纹。已存在的产物不可覆盖，新构建使用显式配置和新目录。

- `build_alphabet_business_benchmark_v0_2.py` 可从已提交的 v0.1 候选生成后续候选文件，但不产生人工审核决定。
- `build_business_map_v03_candidate.py` 需要缺失的 v0.2 `review_decisions.json`。不能用空决定文件声称已还原原审核。
- `build_research_data_bundle.py` 需要 v0.3 候选和原 `indexes/v0.1/manifest.json`。当前公开文件不足以重建既有 v0.2 EvidenceBundle。
- `build_document_index.py` 需要完整、指纹一致的源 HTML 及图片。取得原始字节后可在**新的候选目录**重建索引；新构建不能冒充过去已审核的冻结版本。
- 公司名单、历史工具轨迹、模型输出和人的采纳意见不能从年报重新推导为原记录。资料找不回时，需要另行建立有明确来源的新研究版本。

## 已知证据完整性缺口

已提交摘录的第 **90** 段，其当前文本按项目 `sec.text_hash` 规则计算的指纹，与存储指纹不一致：

```text
stored:     2e86b1ceb5f574619bc1b27515bb8ac52df965b71257bae7dd0834bdf5ce9cc4
recomputed: 113296d3ee15d4cdb5ef858a780812ac2f8e7bafcd68608ae3cdd88d13e62cba
```

相关证据为 `e-platforms`，涉及 `spd-composition`、`spd-platforms`。尚未取得完整固定源文件，因此这次没有修改原文、摘录或指纹。恢复原资料后，应核对到底是文本、指纹还是版本混用问题，并通过新候选及复核解决。

默认 smoke 只验证明确选定的 `alphabet-definition → e-overview → paragraph 55`，并同时输出全集指纹缺口。检查全部候选链可运行：

```bash
.venv/bin/python scripts/smoke_research_workflow.py --strict-all
```

当前该命令因第 90 段问题返回 **1**；这个失败应保留。默认模式成功仅表示所选局部证据和临时存储的生命周期检查通过。

## 尚未随仓库发布的设计文档

旧 README 提及下列六组文档，每组均包含英文 `.md` 与中文 `.zh-CN.md` 两份。目前均未提供；应恢复原文件，再核对其批准状态和当前适用范围：

- `M1_10K_THESIS_SCOPE`
- `DATA_ANALYSIS_AGENT_CONTRACT`
- `GOOGLE_CLOUD_SPIKE`
- `CLOUD_ANALYSIS_A0`
- `CLOUD_ANALYSIS_A1`
- `GOOGLE_CLOUD_LLM_SPIKE`

旧 README 对 M1 与交接契约只直接链接了中文版本，因此共有十个失效链接。此清单记录缺失事实，不重建或代替原设计决定。
