"""Render measured findings; never supplies Agent inputs."""
from pathlib import Path
import json,os
R=Path(__file__).resolve().parents[4];E=Path(__file__).resolve().parents[1];O=R/'output/e6-repeatability-20261010-r1'
def read(p):return json.loads(p.read_bytes())
def link(p):return os.path.relpath(p,E)
def usd(x):return f'${float(x):.7f}' if x is not None else '未定义'
def make():
 c=read(E/'evaluation-only/comparison.v1.json');m={r['slot_id']:r for r in read(O/'all-metrics.v1.json')};budget=read(E/'evaluation-only/cost-reconciliation.v1.json')
 assert c['completed_runs']==9 and c['assessed_runs']==9
 lines=['# E6-V1：同题三档重复执行结果','',f"**本组尚不能称全链稳定：S3出现1次交付失败，S1费用未集中。** 已完成新鲜执行 **9/9**。最终独立内容与加载通过 **{c['quality_passes']}/9**；全程无恢复首次通过 **{c['no_recovery_first_passes']}/9**。全部调用估算 **{usd(c['total_known_estimated_usd'])}**，包含审核与修订。",'', '## 问题与答案范围','', '截止 2026-02-06，仅根据 Microsoft、Alphabet FY2025 10-K，提供各自 FY2025/FY2024 公司整体收入、日期、单位和精确出处。完整材料库分别为 2/3/4 份年报，2,739/4,289/5,636 导航块。Agent 从零自主检索，答案隔离。','', '| 公司 | 财年 | 精确期间 | 收入（USD million） | 原件示例定位 |','|---|---|---|---:|---|','| Microsoft | FY2025 | 2024-07-01—2025-06-30 | 281,724 | 合并利润表 Total revenue；DOM /html/body/div[150]/table，原行12 |','| Microsoft | FY2024 | 2023-07-01—2024-06-30 | 245,122 | 同上，FY2024列 |','| Alphabet | FY2025 | 2025-01-01—2025-12-31 | 402,836 | 合并利润表 Revenues；DOM /html/body/div[816]/table，原行4 |','| Alphabet | FY2024 | 2024-01-01—2024-12-31 | 350,018 | 同上，FY2024列 |','', '这些是独立验收对照，未传入运行。其他等价原文出处也可通过；不是唯一块白名单。逐次评测保留实际选取位置、原文与语义判断。','', '## 三档重复结果','', '| 档位 | 最终通过 | 无恢复首次通过 | 费用中位数 | min—max | 样本CV | max/min | 冻结观察阈值 |','|---|---:|---:|---:|---:|---:|---:|---|']
 for t in c['tiers']:
  verdict='本组费用集中' if t['fee_flag']=='concentrated_under_predeclared_observation_threshold' else '未满足集中阈值'
  lines.append(f"| {t['tier_id']} | {t['quality_passes']}/3 | {t['no_recovery_first_passes']}/3 | {usd(t['fee_estimate_median_usd'])} | {usd(t['fee_estimate_min_usd'])}—{usd(t['fee_estimate_max_usd'])} | {t['sample_cv']:.1%} | {t['max_min_ratio']:.3f} | {verdict} |")
 lines += ['', '三档各3次。CV采用样本标准差 ddof=1，预定 CV≤20% 且 max/min≤1.5 才称本组费用集中。该阈值是本轮工程观察口径；3/3不能证明统计稳定性。费用为冻结无缓存折扣峰值价估算，实际账单未核验。旧 E6-B1 三次排除于本轮分母。','', '## 每次发生了什么','', '| 次序 | 内容与加载 | 无恢复 | 请求/步骤 | 估算费用 | 正文/收入表/导航表 | 恢复事件 | 原始结果 / 独立验收 |','|---|---|---|---|---:|---|---|---|']
 for r in c['runs']:
  d=m[r['slot_id']];reviews=[v for a in d['attempts'] for v in a['reviews']];v=reviews[-1] if reviews else {};events=d['recovery_events'];desc=[]
  for key,label in [('rejected_or_error_tool_decisions','工具拒绝'),('decision_repair_events','决策修订/重试'),('review_model_repair_events','审核调用修订/重试'),('review_program_validation_failures','审核程序校验失败'),('question_protocol_repair_inputs','审核协议修订'),('failed_network_or_provider_calls','调用失败')]:
   if events[key]:desc.append(f'{label}{len(events[key])}次')
  if events['retrieval_attempt_count']>1:desc.append(f"取材重做{events['retrieval_attempt_count']-1}次")
  passed='通过4/4' if r['final_quality_and_load_pass'] else '未通过，见验收'
  nav=v.get('selected_navigation_tables',0);table=v.get('selected_tables',0)
  lines.append(f"| {r['slot_id']} | {passed} | {'是' if r['no_recovery_first_pass'] else '否'} | {r['calls']}/{r['steps']} | {usd(r['estimated_usd'])} | {v.get('selected_blocks','?')}/{table-nav}/{nav} | {'；'.join(desc) or '无'} | [结果]({link(R/r['run']/'result.json')}) · [验收]({link(R/r['assessment'])}) |")
 recovery_case=read(E/'evaluation-only/R2-S1-assessment.v1.json')
 lines += ['', '### R2-S1 的首稿失败与自主恢复', '', '首稿四项金额、期间、单位和出处正确，独立覆盖4/4；聚焦和实际正文读取不通过。turn-016选中一个源自Alphabet地理拆分表924的FY2024记录，却在理由中称主利润表753。原件组装器按真实记录引用补交923/924/925，成为第3张金融表；这些补交正文也未进入首稿query模型输入。审核明确要求去掉冗余，Agent在新的取材attempt自行选择主表记录。', '', '首稿22请求/$0.2674440，恢复额外22请求/$0.3093201，最终7块/2张收入表、4/4与完整阅读及加载通过，总44请求/$0.5767641。首稿失焦与读取缺口保留。证据支持记录选择与理由不一致导致额外表及重做成本；通用工程根因仍待契约和状态路径核验，不把一次模型错误直接当根因。', '', '[首末稿独立对照](evaluation-only/R2-S1-assessment.v1.json)']
 lines += ['', '### R3-S1 的独立反例', '', '相同冗余再次出现，但首稿已完整读过地理表：turn-011承认两张Alphabet表，却认为没有重复。它仍同时交付主表与地理表的等价总额，独立聚焦失败，读取通过。因此“只是没读到原文”不足以解释两例。真实审核的irrelevant body_checks触发重新取材，最终2收入表、4/4、读取与加载通过。首稿17请求/$0.2140581，恢复16/$0.2214093，共33/$0.4354674。', '', '[第二个首末稿对照](evaluation-only/R3-S1-assessment.v1.json)']
 lines += ['', '### R3-S3 的材料正确、审核失败', '', '独立内容4/4、范围/真实性/出处与完整读取通过，交付8块：2张收入表加30字导航页眉；但两次来源审核都被严格原文引用校验拒绝，无法形成合法合并审核，加载失败，整体交付不能算通过。', '', '零API原稿回放定位：第一次将单位caption引用到收入表753，实际caption在752；第二次将原文连续的“202320242025”改写成带空格年份，quote未存在于引用块。分别3处/5处错引。另有被拒工具决策和一次非法JSON。原审核与第二次有界审核费用全部计入22请求/$0.2923674，失败不替换。', '', '[失败原稿及原件验收](evaluation-only/R3-S3-assessment.v1.json)']
 lines += ['', '每次评测分别解释四项覆盖、公司/来源/日期/合并口径/单位真实性、可定位出处、真实完整阅读、聚焦与严格加载。结构性原子表背景允许；恢复前错误和导航冗余仍保留，不用可选材料抵消遗漏。','', '## 费用、完整性与执行边界','',f"共享原账本从 {budget['requests_before']} 请求 / {usd(budget['estimated_usd_before'])} 增至 {budget['total_calls']} 请求 / {usd(budget['total_estimated_usd'])}。本轮新增 {budget['new_calls']} 请求 / {usd(budget['new_estimated_usd'])}；unknown/在途均0。所有新增reservation与封存call ends一一对应，价格快照逐次重算一致。用户E6增加10授权保留，累计硬上限仍$13，未清零或分叉账本。",'', '首样本运行时独立预审发现外层终态停止检查缺口，旧外层暂停，首样本完成一次并保留；余下八次使用经过反例检查的 v3 调度。v1/v2草稿与冻结记录保留，v2未执行。修正只涉及实验外层停止分类，全部业务实现、Skill、问题、原件、验收、每次资源配置保持冻结值；不能称九次同一调度版本。','', '完整材料仍为 prepared_with_gaps。已知收入题、短时三次、供应商缓存/模型变化限制长期成功率结论。材料量与旧年度/第三公司共同增加，不能把费用差异归因于纯字节增长；未验收第二问题、更大规模、更多格式、完整财务包或真实 Analysis。','', '[冻结方案](PLAN.zh-CN.md) · [逐次比较](evaluation-only/comparison.v1.json) · [费用对账](evaluation-only/cost-reconciliation.v1.json) · [最终冻结核验](evaluation-only/final-verification.v1.json)']
 (E/'DELIVERY.zh-CN.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':make()
