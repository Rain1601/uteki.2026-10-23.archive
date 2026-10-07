# 未发布构建记录 1

状态：被最终阶段包替代。此处文件只保留核验过程，不作为交付或生产输入。

第一次构建通过真实 AMD/TSMC 输入与当时 111 项离线检查后，补充的独立合成反例发现：空 `script/style/noscript` 目标紧邻目录时，导航检测可能将它当成可见空锚点。修复增加源元素及祖先标签检查。两份真实材料的解析内容不受该反例影响，但实现指纹改变，因此重新构建最终包。

以下文件完整迁移到本目录。原件与回执没有改写。回执中的路径指向迁移之前的位置，不能用其旧路径误指现在的正式包。

| 原相对路径（本实验目录内） | 当前相对路径 |
|---|---|
| stage-a-amd/ | pre-publication-attempt-1/stage-a-amd/ |
| stage-a-tsmc/ | pre-publication-attempt-1/stage-a-tsmc/ |
| stage-b-amd/ | pre-publication-attempt-1/stage-b-amd/ |
| stage-b-tsmc/ | pre-publication-attempt-1/stage-b-tsmc/ |
| stage-a-verification.json / .zh-CN.md | pre-publication-attempt-1/ 下同名文件 |
| stage-b-verification.json / .zh-CN.md | pre-publication-attempt-1/ 下同名文件 |
| verification.json | pre-publication-attempt-1/verification.json |

`implementation/` 保存当时四个实现文件、阶段复跑脚本和新测试文件。`superseded.json` 保存迁移后各原文件哈希。归档中的复跑脚本仅是源码快照，其路径假设属于原工作区；不能在迁移目录直接运行并声称重建成功。

正式验收只使用父目录的最终 `stage-a-*`、`stage-b-*`、`verification.json`。更早的 v0.1.7 / v0.1.8 包、原始 HTML 和历史报告始终保留原路径、原字节。
