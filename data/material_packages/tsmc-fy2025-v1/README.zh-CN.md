# 台积电 FY2025 年度合并财务原件包 v1

这是公司参数化获取方法的公开、可迁移交付：TSM／CIK 0001046179，FY2025／2025-12-31，截至2026-10-12。材料来自 SEC 和台积电官方 IR。

## 包含什么

- 31件已发现原件：SEC 20-F主文、申报索引、附件和XBRL；官方年报网页／完整PDF、年度合并财报PDF、20-F镜像PDF。
- 3份已取得的官方目录快照。它们不是本批次新取得的实时目录。
- 93条原件成功HTTP记录，每件3条、HTTP200、hash一致。继承的历史记录保留原请求时刻，本地复制不计远程取得。
- 来源、角色、公司／期间、披露日期已知或未知状态、原件hash、获取历史及独立验收结果。

原件存储在 `sources/objects/<SHA-256>.bin`。文件后缀是存储约定；真实类型在 `materials.json` 的 `mime_type` 中。原字节不改写，跨URL重复／变化不静默合并。

## 当前验收

**冻结目录的文件获取和三次重复校验已通过；整体验收尚未通过。** 实时目录复核受Cloudflare浏览器挑战阻断，IR首次发布日期仍有缺口。主表／附注逐项解析、财务事实完整性、SQL可查询及长期稳定性均未通过。本包未运行解析或模型。

`acceptance.json` 保存独立核验；`acquisition-history.json` 保留此前DNS、请求额度耗尽和403失败。原PDF 403没有错误正文，不能追认与后续目录挑战同因。错误挑战正文、完整本机运行、私密配置及本机路径未纳入公开包；它们保留在原机器。

`materials.json` 是公开投影，**不能传给获取CLI的 `--resume-verification`**；原验证文件没有被改写，原hash为 `00540ba63df942529a9e543b5cb4651db69f61c3aec4142c05b14f5e53a5c8d7`。完整私密运行的迁移须单独处理，不能用公开投影冒充原运行。

## 离线复核

在本目录运行：

```bash
shasum -a 256 -c SHA256SUMS
```

它核验公开包字节，不证明财务事实语义正确。原件与原冻结存储的hash已逐件比对。

## 方法和接续入口

[方法／原标准／实际缺口](../../../docs/research/2026-10-12-tsmc-annual-package-method.v3.zh-CN.md) · [获取代码](../../../src/uteki/infrastructure/document_sources/annual_package.py) · [来源配置](../../../config/company_sources/tsmc-annual-package-v1.json) · [TODO](../../../TODO.md)

重新获取需显式输入公司、财年、期末、截止日和版本化配置；SEC联系身份由调用者私密配置提供，不包含在材料包。公司目录配置只有TSMC经过真实获取，独立合成公司用于工程验证。
