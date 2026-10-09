# 离线关口执行历史

全部版本0模型/0HTTP/费用$0，原件和preparation-v1未改写。目录依次保留，未把失败版本改成成功。

| 版本 | 结果与原因 |
|---|---|
| 脚本初始启动 | tests模块不在脚本导入路径；无工具运行产物。改用脚本自身的显式ScriptedPlanner，未修改系统实现 |
| gates-v1 | 查询和读取通过；合法1000000包配额在宿主派生ArtifactReadRequest max_bytes=125000，超过100000上限而中断。已登记R8；后续改为常规640000，R8未修 |
| gates-v2 | 系统查询与交接成功；审计脚本错误假定query_evidence_v1引用内嵌original_block，实际正文位于source_documents，断言KeyError。仅修审计引用解析 |
| gates-v3 | 系统查询与交接成功；审计脚本把字符串JSON digest误当正文UTF8字节hash，断言失败。仅修审计hash核验 |
| gates-v4 | 原件四事实、期间/单位、重复出处、范围/截止、完整与紧凑cells、脚本宿主查询/选记录及封存交接均通过 |

gates-v4是确定性工具fixture，保留全部16个occurrences用于出处核验。没有验证模型自主发现/读取/选材，也没有判定模型最终聚焦。原件必需信息仍以独立语义核验为准；测试或脚本通过不能抵消后续缺项。
