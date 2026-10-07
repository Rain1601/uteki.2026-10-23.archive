"""Render an explicitly selected new-schema candidate without editing its facts."""
import argparse
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('baseline',ROOT/'experiments/agent_design/2026-10-07-microsoft-clean-reextract-v1/build_view.py')
view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)


def notice(result, paths, output, audit_path=None):
    run = paths['request.json'].parent
    links = [view.link('实际模型请求 / Request',view.href(paths['request.json'],output)),
             view.link('本轮方案 / Plan',view.href(Path(__file__).parent/'PLAN.zh-CN.md',output))]
    for name, label in [('response.txt','模型原答 / Raw response'),('projection.json','索引处理记录 / Index projection'),
                        ('patch.json','模型修改 / Model patch'),('diff.json','逐项差异 / Changes'),
                        ('critic.json','本次修订所据模型复核 / Input model review'),
                        ('configuration.json','调用配置 / Configuration'),('result.json','执行记录 / Run receipt')]:
        if (run/name).is_file(): links.append(view.link(label,view.href(run/name,output)))
    audit_note = ''
    if audit_path is not None:
        audit_path = audit_path.resolve()
        receipt = view.read(audit_path/'result.json')
        request = view.read(audit_path/'request.json')
        payload = view.parse_json_object(request['messages'][0]['content'])
        if (receipt['source_packet_sha256'] != result['source_packet_sha256']
                or receipt['skill_sha256'] != result['skill_sha256']
                or receipt['request_sha256'] != view.sha(audit_path/'request.json')
                or payload.get('own_candidate') != view.read(run/'draft.json')):
            raise ValueError('audit_notice_candidate_binding_mismatch')
        if receipt['status'] == 'failed':
            metadata = view.read(audit_path/'response_metadata.json') or {}
            reason = '输出触及上限并被截断 / Output truncated' if metadata.get('stop_reason')=='max_tokens' else '未通过输出契约 / Output contract failed' if receipt.get('validation_error') else '调用未完成 / Call incomplete'
            audit_note = ('<p><strong>系统自审未被接受：' + reason + '。</strong> '
                '原始审核保留；程序未将它计为覆盖通过。后续修订仍须重新审核。 '
                + view.link('审核原答 / Audit response',view.href(audit_path/'response.txt',output)) + ' · '
                + view.link('审核执行记录 / Audit receipt',view.href(audit_path/'result.json',output)) + '</p>')
        elif receipt['status'] == 'completed':
            label = '系统自审发现待修订项 / Self-audit needs revision' if receipt.get('self_check_status')!='pass' else '系统自审未报告缺口 / No self-reported gaps'
            audit_note = ('<p><strong>' + label + '</strong>。模型自审不能替代独立内容验收。 '
                + view.link('自审结果 / Self-audit',view.href(audit_path/'audit.json',output)) + ' · '
                + view.link('审核执行记录 / Audit receipt',view.href(audit_path/'result.json',output)) + '</p>')
    repair = ('<p>当前候选由系统 Agent 读取原文和自己的失败答复后修复；输入仅增加程序校验错误。'
              '原失败记录保留。Codex 的内容评审没有进入该请求。</p>'
              if result.get('execution_mode')=='business_products_protocol_repair' else '')
    if result.get('execution_mode')=='business_products_revision_from_failed_audit':
        repair = '<p>本次由系统 Agent 根据完整原文、自己的候选及未通过程序校验的自审原答进行修订；自审原答只是待核实建议，未被接受。Codex 的内容评审没有进入请求，修订后必须重新审核。</p>'
    if result.get('execution_mode')=='business_critic_revision':
        repair = '<p>本次由系统 Sonnet 根据完整原文、自己的候选及独立 Opus 的复核建议生成对象修改。工程保留未修改对象并验证新候选；Codex 没有代写业务事实。修改及逐项差异可查，复核建议不等于问题已经解决，内容状态以独立验收为准。</p>'
    return ('<div class="notice"><strong>系统 Agent · 业务身份与产品详情 / Business identities and product details</strong>'
        '<p>采用 business-products-v1，业务身份与产品详情分层，逐项引用可查。总览是确定性投影，事实内容由系统模型输出。'
        '本页为待验收候选：协议校验通过，不代表引用充分、关系正确或内容完整。</p>' + repair + audit_note + '<p>'
        + ' · '.join(links) + '</p></div>')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);ap.add_argument('--review',type=Path)
    ap.add_argument('--audit',type=Path,help='Explicit audit of this exact candidate; no selection fallback.')
    ap.add_argument('--with-svg',action='store_true');args=ap.parse_args()
    view.execution_notice=lambda result,paths,output:notice(result,paths,output,args.audit)
    view.build(args.run,args.output,args.review,args.with_svg,graph_stage=False,overview=True)

if __name__=='__main__':main()
