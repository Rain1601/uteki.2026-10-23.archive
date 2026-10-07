# 执行历史换机与路径恢复

历史 descriptor 内的 `output_root` 是旧机器的绝对路径。不要改写它，也不要修改历史 request、response、manifest、result、事件或它们的 hash。新机器使用独立本机 receipt 声明旧仓库根目录到新根目录的对应关系。

先恢复 Git 文件和私密迁移包，保留原相对目录。当前业务图后续复核还依赖被 Git 忽略的预算 SQLite、原观测事件及更早的 inventory。缺少这些时不得创建空预算或伪造历史。

在新仓库执行（替换新机器路径）：

```bash
.venv/bin/python scripts/relocate_observation_history.py create \
  --root /absolute/new/uteki.beta \
  --old-root /Users/rain/Documents/ChatGPT/uteki.beta

.venv/bin/python scripts/relocate_observation_history.py check \
  --root /absolute/new/uteki.beta
```

可重复传入 `--trace run-...`，只登记明确选择的历史运行。默认扫描旧根目录下的观测运行；缺少原stage或发表事件会拒绝。旧根目录外的运行不自动迁移。已有receipt不会被覆盖。create后的核验失败会删除本次新建的receipt，方便补齐资料后重试；check失败不删除已有receipt。

本机文件是 `.local/observation-relocation.json`，权限600，不提交Git。它绑定旧根、新根、观测相对目录、每个trace、原descriptor SHA-256和精确stage相对路径。验证仍检查原trace/generation和artifact.published的SHA；receipt不豁免文件完整性，也不是新的语义验收。生成receipt是在声明所恢复的本机来源，不能把不可信迁移包变成可信记录。

来源根目录、时期和公司仍由原实验显式选择。路径恢复不会改这些业务范围。原实现hash继续表示当时版本；新版本验证器不得改写旧代码hash。当前调用方重新校验原请求、模型原答和补丁合并链。

## 已做验证

2026-10-08，把当前Microsoft完整11个运行及依赖复制到另一个临时根目录：11个descriptor原字节保留，200个发表artifact通过原hash校验。新目录的`run_critic.py`成功重放最新`critic-revision-02`历史依赖并生成Opus04预检：160926字节，使用`--max-tokens 16000 --target-format pointers-v1`，预留估算1.027704美元、同账本余额0.311528美元，预算不足，未发送请求。相关43项离线测试通过；覆盖无receipt、错误根/suffix/trace/hash、篡改产物和原路径兼容。

边界：本能力接入`business_map.coverage_run.verify_published_artifacts`，供当前业务图历史续接使用；不是所有旧工作台或其他Agent绝对路径的通用迁移。`fact_completion`自己的旧descriptor校验未改。图页及来源包本来使用仓库相对路径。
