# AMD / TSMC 官方年报获取验收

2026-10-04。使用 Uteki 正式 `agent acquire` 入口，从公司配置自动发现 SEC 年报地址、下载、校验并冻结原件。**没有手工传入报告 URL，没有调用模型。**

此前用户在 2026-09-24 提供的 SEC 联系身份已恢复到被 Git 忽略的本地私有配置。两轮运行均记录 `sec_contact_origin=local_env_file`；本报告不包含邮箱。独立进程再次运行可读取同一配置，无需重新询问。

| 公司 | 首轮 HTTP 请求 | 原件 | 再次运行 | 最终状态 |
|---|---:|---:|---|---|
| AMD | 5 | 3 份 10-K + 1 份 10-K/A | 1 次目录请求，4 份核验后复用 | completed |
| TSMC | 4 | 3 份 20-F | 1 次目录请求，3 份核验后复用 | completed |

所有原件 HTTP 200，CIK、类型、期间与 SEC 清单匹配，哈希与保存字节一致。复用保留原获取时间和 HTTP 记录，本轮验证时间另存。这里验证的是资料获取，不是财务内容提取或研究质量。

首轮两个运行仍记录 `completed_with_gaps`：范围外的股东大会/其他文件日期被旧检查计入年报缺口。已修为先限定任务表单，再检查期间；保留首轮原记录，第二轮零缺口。没有修改原件或把失败状态改写成成功。

## 实际文件

| 公司 | 类型 | 报告期末 | 披露日期 | 官方地址 | 冻结文件 |
|---|---|---|---|---|---|
| AMD | 10-K | 2023-12-30 | 2024-01-31 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/2488/000000248824000012/amd-20231230.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808.bin) |
| AMD | 10-K | 2024-12-28 | 2025-02-05 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/2488/000000248825000012/amd-20241228.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/9271e18e8a627c99f3b23bc12315b21d42b43f00da0cebdc49cf0dd1c84616ac.bin) |
| AMD | 10-K | 2025-12-27 | 2026-02-04 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/2488/000000248826000018/amd-20251227.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/cae93803a296092cfa058c43a986242ed03a12499affb67198d543afb1c4f6a9.bin) |
| AMD | 10-K/A | 2025-12-27 | 2026-02-04 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/2488/000000248826000021/amd-20251227.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/be20df7976f0a218fa7b7a10c183402aa82cbeb61ea175dd743a74d42b3124e4.bin) |
| TSMC | 20-F | 2023-12-31 | 2024-04-18 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/1046179/000119312524099840/d592628d20f.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1.bin) |
| TSMC | 20-F | 2024-12-31 | 2025-04-17 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/1046179/000119312525083423/d896993d20f.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/7113daf400e9a4c1ac99538bda88a5d4b46f456f7419802f48accc8727a0e1a2.bin) |
| TSMC | 20-F | 2025-12-31 | 2026-04-16 | [SEC 原件](https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm) | [本地原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/official-filings/sources/objects/8a7ec012c800f49329b4fe35821a58ceb09d306945f92fc5e25be2d4e259846b.bin) |

## 检查材料

- [AMD 首轮](amd-run-01.json)、[再次运行](amd-run-02.json)。
- [TSMC 首轮](tsmc-run-01.json)、[再次运行](tsmc-run-02.json)。
- [独立字节及范围核验](verification.json)、[工程回归输出](offline-checks.txt)。
- [能力说明与执行命令](../../../docs/design/UTEKI_REPORT_ACQUISITION_v1.zh-CN.md)。

本次结果不能证明所有未来网络和所有发行人都稳定可用。服务器部署出口、连续更新、PDF/非 inline HTML、官方 IR 后备与多进程共享限速仍待分别验收。当前两家公司按顺序执行；SEC 旧总表/人工下载出现过的 403 不被删除，本次正规入口的响应以回执为准。

下一步：先把这条真实获取路径接入后台任务，再继续七份原件的提取与独立 Review。
