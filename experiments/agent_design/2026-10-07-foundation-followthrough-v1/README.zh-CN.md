# TODO 02–04：获取配置统一与新版出处定位适配

本轮完成两个受限交付：五家公司可显式选择同一套官方获取配置入口；新版 HTML 底稿的数值出处能按正确字符位置读取。**02、03、04 仍未整项完成。** 本轮无网络请求、无模型调用，未修改任何历史原件、数据集或解析包。

## 02：五家公司使用显式来源配置

新目录为 [annual-pilot-catalog-v2.json](../../../../config/company_sources/annual-pilot-catalog-v2.json)。调用者必须显式选择这个目录及公司；没有默认公司，也不会改变既有 v1 调用。配置由同一 `resolve_company_profile` 和获取配置校验器处理。

| 公司 | 选定年报范围 | 原件复核结果 |
|---|---|---|
| Microsoft | 10-K，2025-06-30 | 1 份 HTML，哈希与 SEC 身份通过 |
| Alphabet | 10-K，2025-12-31 | 1 份 HTML，哈希与 SEC 身份通过 |
| NVIDIA | 10-K，2025-01-26 | 配置合法；现存是 IR PDF，不能用 SEC inline 身份校验，仍缺该入口的已验证 HTML |
| TSMC | 原 v1 配置的 2023-01-01 至 2026-10-04 年报范围，20-F | 3 份 HTML，哈希与 SEC 身份通过 |
| AMD | 原 v1 配置的 2023-01-01 至 2026-10-04 年报范围，10-K/修订 | 4 份 HTML，哈希与 SEC 身份通过 |

所有日期来自显式配置与既有冻结材料，未推定最新期间。股票代码不代替 CIK 身份校验。文件哈希固定在目录中，未知公司被拒绝。实际运行仍使用本机已配置的 SEC 联系信息；本轮只做离线配置校验，校验用的假联系地址未发往任何网络。

[逐材料获取配置验收记录](acquisition/verification.json)包含配置、原件哈希、身份结果及缺口。这是配置与已有库存复核，**不是五次新的网络获取，也不证明所需官方材料齐全**。

## 04：新版换行之后，数值出处不再全部失联

上轮 v0.1.12 修复了 `Percentage<br>Change` 等词粘连，但数值出处消费者仍按旧规则计算偏移。只要表内有这样的换行，整个表格的 DOM 文本就与新版底稿不同，出处会被判为无法定位。

本轮：

1. 新 review 输入记录冻结 index 的 `parser_version`，并在 repack/语义检查中保留。
2. DOM 字符范围计算、表行与段落引用采用对应版本的换行规则。可见 `<br>` 是词边界，隐藏换行不制造字符；普通内联数字继续拼接。
3. 检查器把声明的解析版本与冻结 index 核对。新版包缺版本或版本被替换会拒绝；旧冻结输入保留旧行为。

四份真实原件中全部受换行影响、且包含可见 inline 数值的块已核验：

| 公司 | 受影响块 | 数值 DOM 定位检查 | 修复前成功 | 修复后成功 |
|---|---:|---:|---:|---:|
| AMD | 26 | 641 | 0 | 641 |
| TSMC | 7 | 159 | 0 | 159 |
| Microsoft | 4 | 130 | 0 | 130 |
| Alphabet | 7 | 173 | 0 | 173 |
| 合计 | 44 | 1,103 | 0 | 1,103 |

[每个定位的修复前后结果](parser/verification.json)记录原件身份、块、字符区间与完整表行上下文。这里的 DOM 探针只证明原文定位，**不是 1,103 条财务事实已被模型正确提取**。也不证明单位、脚注、期间或口径全部正确。

新增两家公司、两个期间的合成全链路检查：v0.1.12 底稿 → 数值数据集 → review 输入 → repack → 语义出处核验。两个独立来源均成功；缺失或篡改解析版本被拒绝。相关 83 项离线检查通过。没有调用模型，也没有用测试数量代替业务验收。

复核：

```sh
.venv/bin/python experiments/agent_design/2026-10-07-foundation-followthrough-v1/acquisition/verify.py
.venv/bin/python experiments/agent_design/2026-10-07-foundation-followthrough-v1/parser/verify.py
.venv/bin/python -m unittest tests.unit.test_versioned_anchor_pipeline tests.unit.test_semantic_anchors tests.unit.test_record_review tests.unit.test_record_review_repack tests.unit.test_semantic_review tests.unit.test_semantic_review_v2 tests.unit.test_semantic_review_v4 tests.unit.test_company_registry tests.unit.test_sec_line_breaks
```

## 仍未完成

- **02**：五个配置的统一实际获取/复用运行；NVIDIA 的 SEC HTML 或明确支持的 PDF 身份适配；季度/6-K、附件、发布稿、官方电话会材料覆盖。
- **03**：整文语义覆盖、单位/脚注、图片/PDF 与跨节引用的独立核查。上轮 DOM 文字覆盖检查仍有效，但不能代替这些检查。
- **04**：精确单位/脚注关联、跨节跟读、完整 PDF 解析。此次只解除 v0.1.12 数值出处消费的已知阻塞；生产默认解析版本未静默更改。

下一项：在明确材料清单内完成缺失原件的实际获取和验证，并对单位/脚注归属建立来源片段级验收。当前主线仍由 TODO 09 的业务完整性运行推进。
