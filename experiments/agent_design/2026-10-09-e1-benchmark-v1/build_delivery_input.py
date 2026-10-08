"""Assemble human-readable evaluation, never imported by runtime agents."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = '../../../../experiments/agent_design/' + ROOT.name + '/'
NARRATIVES = {
 'E1-01': ('从 FY2024 原年报获取全年公司总收入。', '交付245,122百万美元、2023-07-01至2024-06-30的原始XBRL期间、利润表及两个标题。'),
 'E1-02': ('从 FY2025 年报获取 FY2024 比较数，不能冒充已读取旧年报。', '交付245,122百万美元及对应期间，清楚绑定FY2025原件中的FY2024比较列。'),
 'E1-03': ('对照两份独立原件，验证同一年度收入是否相同，保留两个出处，不相加。', '两个版本各自提供一条FY2024总收入记录和利润表。两者均为245,122百万美元，属于同一观察期间。'),
 'E1-04': ('以资料可得日为边界，既要最终结果正确，也不能在中间读取未来报告正文。', '仅交付2024-07-30公开的FY2024原件。完整过程已检查；FY2025仅出现允许的身份和排除元数据。原r2审核协议失败，独立恢复审核成功，原取材未改。'),
 'E1-05': ('列出三个分部及核心业务组合，保留所属关系，不要求罗列每个产品。', '交付三个分部及九组核心业务；Windows Commercial/OEM等归属有原文。初版仍附带本题不需要的重组历史和管理说明。'),
 'E1-06': ('区分跨分部Cloud口径、Intelligent Cloud分部和Azure产品；数字的单位、期间、金额与增速不能混同。', '实际覆盖与遗漏按下方独立核对逐项显示；不把模型自审放行当作正确证明。'),
 'E1-07': ('比较两份报告对同一FY2024的分部披露，并解释口径重列；不能把重列当业务增长或把版本相加。', '实际各版本金额、重列依据与遗漏按下方逐项核对。')}


def load(path): return json.loads(path.read_text())
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def case(case_id, run_name):
    folder = ROOT / 'evaluation-only/reviews' / run_name
    review, score, gold = (load(folder / name) for name in ('review.json','score.json','gold-projection.json'))
    runtime = ROOT / 'runs' / run_name
    required = gold['required']
    missing = [r['id'] + '：' + r['reason'] for r in review['requirements'] if r['status'] != 'supported']
    extra = []
    cats = score['characters']['categories']
    for key,label in [('irrelevant','无关'),('duplicate','重复或可删冗余'),('table_structure','原表附带、本题不需要的其他行和比较列')]:
        if cats[key]['numerator']:
            extra.append(str(cats[key]['numerator']) + ' 字符：' + label + '。这部分不计为必需支持。')
    extra.append(review['checks']['focus']['reason'])
    evidence, seen = [], set()
    for requirement in review['requirements']:
        for citation in requirement.get('citations',[]):
            if citation.get('kind') == 'metadata' or not citation.get('block_id'):
                continue
            sid,bid = citation['source_id'],citation['block_id']
            key = (sid,bid,citation['quote'])
            if key in seen: continue
            seen.add(key)
            candidates = list((ROOT/'datasets').glob('msft-acquired-*/indexes/'+sid+'/document.html'))
            if len(candidates) != 1: raise ValueError('ambiguous source link')
            evidence.append({'label': requirement['id']+' · 原文定位', 'quote':citation['quote'],
                             'url':PREFIX+str(candidates[0].relative_to(ROOT))+'#'+bid})
    n,d = score['required_coverage']['numerator'],score['required_coverage']['denominator']
    limits = ['固定评测标准在运行前冻结，没有交给运行模型。原件优先的独立复核有历史摘要暴露，不称完全盲审。',
              '这是特定题目和材料版本的单次或修复后验证；不能证明重复稳定性或全公司、全材料泛化。',
              '完整表格粒度允许一些表内附带数据；固定标准通过也不等于达到用户的最小充分材料目标。',
              '数字费用包含该运行所有失败调用，是估算，不是供应商账单。修复前的其他运行另列总账。']
    provided = NARRATIVES[case_id][1]
    recovery_links = []
    if run_name=='E1-04-sonnet-r2': limits.append('本页评分费用仅为原r2的$0.728260；恢复审核另花$0.062252，合计$0.790512。更早失败r1的$0.527150也计入本轮总费用。原r2仍标为流程失败。')
    elif case_id=='E1-04':
        provided = '本次系统重新执行截止日期查询；实际交付、全过程来源隔离及独立验收见下方。历史失败与恢复保留在总账。'
    if run_name=='E1-05-sonnet-focus-recovery-r1':
        provided = '系统自行删去490字符的重组历史，保留三个分部及九组核心业务。独立验收4/4、聚焦通过；后续复用完全相同的17块材料，单独补审成功。'
        limits.append('本页评分绑定取材修复运行，其原系统状态仍是attempts_exhausted。后续context-review-r1只补审、不重新取材，费用$0.094822；本题三轮累计$2.493072。短过渡句不改变原冻结标准，320字符块内管理说明仍可压缩。')
        recovery_links = [
            {'label':'同一材料补审与hash核对','url':PREFIX+'evaluation-only/reviews/'+run_name+'/context-review-recovery.json'},
            {'label':'后续补审成功状态','url':PREFIX+'runs/E1-05-sonnet-context-review-r1/result.json'}]
    base='evaluation-only/reviews/'+run_name+'/'
    return {'case_id':case_id,'status':'finished','question':review['question'],
        'gold_sha256':digest(ROOT/'evaluation-only/frozen'/f'{case_id}-v1.json'),
        'run_sha256':digest(runtime/'manifest.json'), 'review':review,'score':score,'required':required,
        'reference_explanation':NARRATIVES[case_id][0], 'provided_explanation':provided,
        'coverage_explanation':f'必需项完整支持 {n}/{d}。'+('缺失或不完整项见下方；不能用可选材料抵消。' if missing else '本次未发现必需项缺失；精简性另行判断。'),
        'missing':missing,'extra':extra,'limitations':limits,'evidence':evidence,
        'process_links':[{'label':'独立核对详细说明','url':PREFIX+base+'README.zh-CN.md'},
                         {'label':'原件核验','url':PREFIX+base+'original-check.json'},
                         {'label':'预先冻结标准','url':PREFIX+'evaluation-only/frozen/'+case_id+'-v1.json'},
                         {'label':'实际系统运行状态','url':PREFIX+'runs/'+run_name+'/result.json'}] + recovery_links}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--selection',required=True,type=Path,help='JSON list of [case_id, run_name]')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    selected=load(args.selection)
    value={'schema_version':'evidence-benchmark-page-v1','title':'E1 · 独立材料验收 / Evidence benchmark',
        'introduction':'先看问题、实际交付、遗漏和多余内容。覆盖正确、流程成功、最小材料是三件不同的事。原文与过程折叠在各题末尾。',
        'back_link':{'label':'上一阶段 / Previous delivery','url':'../data-agent-evidence-v1/'},
        'cases':[case(cid,name) for cid,name in selected]}
    with args.output.open('x') as stream: json.dump(value,stream,ensure_ascii=False,indent=2)
