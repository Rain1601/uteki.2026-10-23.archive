# 这份 10-K 已有的全部 111 条财务候选记录

本表按来源 `googl-2025-10k` 从冻结 `records.json` 完整导出；没有混入同库的 10-Q，没有重新调用模型。
**这些是此前程序映射 XBRL 标签的结果，不是本次 Data Agent 新抽出的 111 条事实。** 111 条中有 39 条无维度、72 条带尚未解释的原始维度；包含多期间、重复披露及维度记录，不能当成 111 个不同指标，也不能全部相加。
金额按存储单位原样展示；PPE 正值表示支出幅度。源记录全部仍为 candidate。只有标为“本题已核验”的 4 条属于本次内容核验范围；其余 107 条仅表示未在本题审阅，并非已判错。
[返回验收样本](/Users/bytedance/Documents/ChatGPT/uteki/docs/design/data-agent-acceptance/README.zh-CN.md)

| 指标 | 记录数 |
| --- | ---: |
| 购建固定资产现金支出 | 3 |
| 净利润 | 24 |
| 经营现金流 | 3 |
| 营业利润 | 18 |
| 营收 | 63 |

## 购建固定资产现金支出

| 原始记录 | 期间 | 数值 | 单位 | 口径／维度 | 本次核验 |
| --- | --- | ---: | --- | --- | --- |
| [obs-1e9dde34a9eb293e847e48a6](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1097) | 2023-01-01 → 2023-12-31 (year) | 32,251,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-a0343ddc7aedd6ae4e071851](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1142) | 2024-01-01 → 2024-12-31 (year) | 52,535,000,000 | USD | reported_consolidated；无维度标签 | 本题已核验 |
| [obs-56ba2c019c541769c0cce851](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1187) | 2025-01-01 → 2025-12-31 (year) | 91,447,000,000 | USD | reported_consolidated；无维度标签 | 本题已核验 |

## 净利润

| 原始记录 | 期间 | 数值 | 单位 | 口径／维度 | 本次核验 |
| --- | --- | ---: | --- | --- | --- |
| [obs-13e9b082a34439876745c00f](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:594) | 2023-01-01 → 2023-12-31 (year) | 73,795,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-282fe9e798956592009f5816](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:410) | 2023-01-01 → 2023-12-31 (year) | 73,795,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-6a45cb5d800325a00c413898](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:827) | 2023-01-01 → 2023-12-31 (year) | 73,795,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-a89b84e94cdb6fee0e79a3f7](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3890) | 2023-01-01 → 2023-12-31 (year) | -954,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-b97e1a2c4031b3dc0bd2b65a](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:275) | 2023-01-01 → 2023-12-31 (year) | 73,795,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-c3991ade4c8dea1f98fcb836](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3737) | 2023-01-01 → 2023-12-31 (year) | 214,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-cbdd99d903307bb19fc21312](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:545) | 2023-01-01 → 2023-12-31 (year) | 73,795,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-e02dc4235a75f3ee9bc0e1be](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3431) | 2023-01-01 → 2023-12-31 (year) | -1,168,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-2a821611ddfda95061df599f](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:320) | 2024-01-01 → 2024-12-31 (year) | 100,118,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-5a6c7c812ab085d699ea2fc5](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:872) | 2024-01-01 → 2024-12-31 (year) | 100,118,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-83ae5411af97610a5a90f226](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3788) | 2024-01-01 → 2024-12-31 (year) | 166,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-ae12ba7f7b0b60d7f85aa445](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3939) | 2024-01-01 → 2024-12-31 (year) | -616,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-d22dfbe1f6e4e60dc46db94a](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3482) | 2024-01-01 → 2024-12-31 (year) | -782,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-e16c5381d740131793acb58b](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:639) | 2024-01-01 → 2024-12-31 (year) | 100,118,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-f61238c74d771b814a6f6c66](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:688) | 2024-01-01 → 2024-12-31 (year) | 100,118,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-fb2c1a8b95de16e7904de947](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:455) | 2024-01-01 → 2024-12-31 (year) | 100,118,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-13440de747726866aef4df7a](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3533) | 2025-01-01 → 2025-12-31 (year) | 169,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-188a82d971e23921c8f01040](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:733) | 2025-01-01 → 2025-12-31 (year) | 132,170,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-497255ab58612f6ef99d8b37](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:365) | 2025-01-01 → 2025-12-31 (year) | 132,170,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-571aa7a1cdc8ea98c932348f](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3839) | 2025-01-01 → 2025-12-31 (year) | -164,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-6bf77b1c2410acd61eadddbf](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:782) | 2025-01-01 → 2025-12-31 (year) | 132,170,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-7ecf9fd8c22ae3e9179202d4](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3988) | 2025-01-01 → 2025-12-31 (year) | 5,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-8b4668e2144473472883c984](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:500) | 2025-01-01 → 2025-12-31 (year) | 132,170,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-8ce6128310428f4f674ea4f6](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:917) | 2025-01-01 → 2025-12-31 (year) | 132,170,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |

## 经营现金流

| 原始记录 | 期间 | 数值 | 单位 | 口径／维度 | 本次核验 |
| --- | --- | ---: | --- | --- | --- |
| [obs-f0a4f387e3c26cbe538110ac](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:962) | 2023-01-01 → 2023-12-31 (year) | 101,746,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-1ee7bb58b50f03e0f72b12e6](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1007) | 2024-01-01 → 2024-12-31 (year) | 125,299,000,000 | USD | reported_consolidated；无维度标签 | 本题已核验 |
| [obs-b8d3ac73ea8cbbe84ae10f92](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1052) | 2025-01-01 → 2025-12-31 (year) | 164,713,000,000 | USD | reported_consolidated；无维度标签 | 本题已核验 |

## 营业利润

| 原始记录 | 期间 | 数值 | 单位 | 口径／维度 | 本次核验 |
| --- | --- | ---: | --- | --- | --- |
| [obs-710f7b85a7c8a888baabfe86](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:140) | 2023-01-01 → 2023-12-31 (year) | 84,293,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-9f446296f00e6fe8c40bb51e](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4919) | 2023-01-01 → 2023-12-31 (year) | -4,095,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-b20d9fb4858df3c6cac22d65](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4766) | 2023-01-01 → 2023-12-31 (year) | 1,716,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-c6b419a041d374216e5f09bc](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5072) | 2023-01-01 → 2023-12-31 (year) | -9,186,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-cd97dfc923b68daa20cdef03](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4613) | 2023-01-01 → 2023-12-31 (year) | 95,858,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-ec8ceb54b7b223d996c19f43](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5219) | 2023-01-01 → 2023-12-31 (year) | 84,293,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-32bae6775bdd7b4e94577053](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5121) | 2024-01-01 → 2024-12-31 (year) | -10,541,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-4a55beea0261db162609fcff](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4817) | 2024-01-01 → 2024-12-31 (year) | 6,112,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-5f3f638647c09604cdfc5dae](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5264) | 2024-01-01 → 2024-12-31 (year) | 112,390,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-5fe12050f06deb3bc7d391b6](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4970) | 2024-01-01 → 2024-12-31 (year) | -4,444,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-87087f716af89f789b3a18cd](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4664) | 2024-01-01 → 2024-12-31 (year) | 121,263,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-e7cac2b213dbcfdd8e97980f](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:185) | 2024-01-01 → 2024-12-31 (year) | 112,390,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-11378d726557267c02976945](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4715) | 2025-01-01 → 2025-12-31 (year) | 139,404,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-7d0e07a5801a30f7a1ee729e](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4868) | 2025-01-01 → 2025-12-31 (year) | 13,910,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-80b45c659e999fa58a1cd81d](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:230) | 2025-01-01 → 2025-12-31 (year) | 129,039,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-a8f154d5ecd727781698a1de](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5170) | 2025-01-01 → 2025-12-31 (year) | -16,760,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-d3859903ef4f4af286db0acd](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5021) | 2025-01-01 → 2025-12-31 (year) | -7,515,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-f95cdc0b4d6e8f9cd69dea2b](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5309) | 2025-01-01 → 2025-12-31 (year) | 129,039,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |

## 营收

| 原始记录 | 期间 | 数值 | 单位 | 口径／维度 | 本次核验 |
| --- | --- | ---: | --- | --- | --- |
| [obs-215f20dc63ba63e23b43b719](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4331) | 2023-01-01 → 2023-12-31 (year) | 1,527,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-26cba680e5eb6e5a918b13a7](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1385) | 2023-01-01 → 2023-12-31 (year) | 31,510,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-2b139436bafa0130560bddc2](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1691) | 2023-01-01 → 2023-12-31 (year) | 237,855,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-435edc3e18d433dde7d47341](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2144) | 2023-01-01 → 2023-12-31 (year) | 33,088,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-5bd0af923b590de1310e0151](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1997) | 2023-01-01 → 2023-12-31 (year) | 272,543,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-73a33a6bec12114e78e31278](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2291) | 2023-01-01 → 2023-12-31 (year) | 1,527,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-86f72381077d03452b094c0d](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1232) | 2023-01-01 → 2023-12-31 (year) | 175,033,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-89660efd38b9da9a60c51ff4](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2573) | 2023-01-01 → 2023-12-31 (year) | 146,286,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-8c88b73a8deaa7198aae5d0e](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1844) | 2023-01-01 → 2023-12-31 (year) | 34,688,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-9916690c89843e3f87c240c6](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1538) | 2023-01-01 → 2023-12-31 (year) | 31,312,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-a52ba08be60b2a45760d17d3](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2867) | 2023-01-01 → 2023-12-31 (year) | 51,514,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-c682a55072e5819594b9683d](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3161) | 2023-01-01 → 2023-12-31 (year) | 307,394,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-c9b0fb357a4b33cf7b3601d9](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:5) | 2023-01-01 → 2023-12-31 (year) | 307,394,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-cdd7668876fb8b413d93eb87](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3014) | 2023-01-01 → 2023-12-31 (year) | 18,320,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-d306e7bb69940bea11d5aa06](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4184) | 2023-01-01 → 2023-12-31 (year) | 33,088,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-d74edb12fef9d50c253e5a08](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2438) | 2023-01-01 → 2023-12-31 (year) | 307,394,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-d7c8b32a5a804536a9d7f36b](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3296) | 2023-01-01 → 2023-12-31 (year) | 307,394,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-dcaefc39b4e5752c251392ec](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2720) | 2023-01-01 → 2023-12-31 (year) | 91,038,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-ea6815a7daa2643d5400e0b7](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3584) | 2023-01-01 → 2023-12-31 (year) | 213,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-f15ff79d11b5ee8cfc6d597b](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4037) | 2023-01-01 → 2023-12-31 (year) | 272,543,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-fe0e432a303aef3417fe8628](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4478) | 2023-01-01 → 2023-12-31 (year) | 307,394,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-100bfa7bd19358ae9689e181](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2622) | 2024-01-01 → 2024-12-31 (year) | 170,447,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-147f43d45f01f0017614da48](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3206) | 2024-01-01 → 2024-12-31 (year) | 350,018,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-1f1b3c5136f5628abd5a3a4d](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1589) | 2024-01-01 → 2024-12-31 (year) | 30,359,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-2209ddb81b2a5887df37c1e8](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2769) | 2024-01-01 → 2024-12-31 (year) | 102,127,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-2428da16a2fc8f88e593b8ac](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4086) | 2024-01-01 → 2024-12-31 (year) | 304,930,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-3f02b24fcceb9bea41612515](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1283) | 2024-01-01 → 2024-12-31 (year) | 198,084,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-50273d029ebc21c954183436](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2483) | 2024-01-01 → 2024-12-31 (year) | 350,018,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-57d4f7351ec09947538252b0](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1436) | 2024-01-01 → 2024-12-31 (year) | 36,147,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-580b8bc7f74002f5cf8dcaca](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4380) | 2024-01-01 → 2024-12-31 (year) | 1,648,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-5ac65848692e1a9fc71573c1](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4523) | 2024-01-01 → 2024-12-31 (year) | 350,018,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-5e6234bfa7788956174674c2](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2916) | 2024-01-01 → 2024-12-31 (year) | 56,815,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-69743ad934adf4dc061de505](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1895) | 2024-01-01 → 2024-12-31 (year) | 40,340,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-73819aa11873777c8f906e94](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2193) | 2024-01-01 → 2024-12-31 (year) | 43,229,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-8fb279f0334f2ea7e2fac7a8](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2340) | 2024-01-01 → 2024-12-31 (year) | 1,648,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-9f25d41353e9a567c9661bed](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4233) | 2024-01-01 → 2024-12-31 (year) | 43,229,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-ad75c0c7957cffc9e820efda](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3341) | 2024-01-01 → 2024-12-31 (year) | 350,018,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-b2fb8a30e5ea8e590a7a9782](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2046) | 2024-01-01 → 2024-12-31 (year) | 304,930,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-b5db8f0949bc70a4e8bc553f](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:50) | 2024-01-01 → 2024-12-31 (year) | 350,018,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-c414fb962c3342f09597addf](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1742) | 2024-01-01 → 2024-12-31 (year) | 264,590,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-c685a2205a31b98db8481054](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3635) | 2024-01-01 → 2024-12-31 (year) | 174,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-ff0321c0f0edd7c2e2dd6b06](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3063) | 2024-01-01 → 2024-12-31 (year) | 20,418,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-0918c3382591381449bc60b2](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2965) | 2025-01-01 → 2025-12-31 (year) | 67,680,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-164aa244596edccd220ce883](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4282) | 2025-01-01 → 2025-12-31 (year) | 58,705,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-1d64ca0a314b659fbadbd78b](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3686) | 2025-01-01 → 2025-12-31 (year) | -233,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-40d784fee700543ced098847](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1487) | 2025-01-01 → 2025-12-31 (year) | 40,367,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-4afa0ed7f2b1e54cff658afb](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:95) | 2025-01-01 → 2025-12-31 (year) | 402,836,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-4e2738a4af47a2020a07e13c](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1946) | 2025-01-01 → 2025-12-31 (year) | 48,030,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-5856c594a179ecdafa0fa1b9](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2095) | 2025-01-01 → 2025-12-31 (year) | 342,721,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-6470d70dcc61dcfe6b49d095](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2242) | 2025-01-01 → 2025-12-31 (year) | 58,705,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-753c2f6512a48da0c51ae888](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2818) | 2025-01-01 → 2025-12-31 (year) | 117,152,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-84ae9954dfcf642c6f47213b](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3386) | 2025-01-01 → 2025-12-31 (year) | 402,836,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-a73fbe15d50d5e6e8239abcd](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3251) | 2025-01-01 → 2025-12-31 (year) | 402,836,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-a7e2d712698e3ca3004478ee](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1793) | 2025-01-01 → 2025-12-31 (year) | 294,691,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-ab82c06adc157e8c5294acf9](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1640) | 2025-01-01 → 2025-12-31 (year) | 29,792,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-ad7a06e0ebccdbb06e4f93e6](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2528) | 2025-01-01 → 2025-12-31 (year) | 402,836,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-b84843586955ac5c81b4eaa4](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2671) | 2025-01-01 → 2025-12-31 (year) | 194,229,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-cfe3743029f5da10d21403ae](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4568) | 2025-01-01 → 2025-12-31 (year) | 402,836,000,000 | USD | reported_consolidated；无维度标签 | 未在本题审阅 |
| [obs-d025d44a18a74e2cf918bb09](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1334) | 2025-01-01 → 2025-12-31 (year) | 224,532,000,000 | USD | reported_dimensioned；2 项原始维度，未解释 | 未在本题审阅 |
| [obs-d16d248a1d275ca3e0befeae](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4135) | 2025-01-01 → 2025-12-31 (year) | 342,721,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-d46c704d220431dc964ab83c](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:2389) | 2025-01-01 → 2025-12-31 (year) | 1,537,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-f05e644693bc05e615aa5ffd](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:4429) | 2025-01-01 → 2025-12-31 (year) | 1,537,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |
| [obs-f7a7355371a56ab95e8e55f1](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:3112) | 2025-01-01 → 2025-12-31 (year) | 23,902,000,000 | USD | reported_dimensioned；1 项原始维度，未解释 | 未在本题审阅 |

导出依据 `records.json` 的 SHA256（文件同时含 10-K 与 10-Q，本表已明确只筛选 10-K）：`cc2d57b86845a105e2c996b8f2fae6cba71c6d88cddbe7011724ecf7f8ddfabd`。此表只是只读展示，不修改、去重或采纳源记录。
