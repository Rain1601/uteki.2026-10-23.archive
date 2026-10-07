"""Bind Codex's post-run review to the materialized candidate; no model input."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stage = args.candidate.resolve()
    read = lambda name: json.loads((stage / name).read_text())
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = read('manifest.json')
    draft = read('draft.json')
    nodes = {node['id']: node for node in draft['businesses']}
    checks = []

    def claim(node_id, blocks, observation):
        node = nodes[node_id]
        checks.append(dict(label=node['name'] + ' · 逐声明依据', status='needs_improvement',
            source_block_ids=blocks, observation=observation,
            inspected_claim=node['description'],
            inspected_excerpts=next(c['excerpts'] for c in node['claim_evidence'] if c['field']=='description'),
            note='已读完整原文并区分“原文有信息”和“此字段引用已覆盖”。本记录仅事后验收，未作为执行输入。'))

    claim('linkedin', ['block-000108-ec73690d'],
          '描述包含免费服务。完整原文支持，但该字段两段精确引文均略去 free services，字段依据不完整。')
    claim('windows', ['block-000152-fc098ac9', 'block-000101-67803298', 'block-000093-7018adaa'],
          '描述还声明商业整合与 OEM 分部归属；所绑定引文仅解释跨设备体验，没有支持这两项归属。')
    claim('surface', ['block-000171-f62e3835'],
          '描述含 Copilot+ PC，但 description 的引文仅解释生产力用途；完整源块和 name 的引用不能代替该字段缺少的引用。')
    claim('nuance_professional', ['block-000122-c07a987e'],
          '描述声明企业与合作伙伴服务组归属，精确引文只有列表中间三个名称，缺少列表主语。完整原文可支持，当前引用不足。')
    for source, target, observation in [
        ('windows', 'm365_commercial_platform', '关系端点是 Windows 整体，说明却仅指商业部分。标记推断和在解释中限缩，仍不能消除图上整体属于子平台的范围冲突。'),
        ('nuance_professional', 'nuance_healthcare', '原文描述整个企业服务组的用途，当前关系把用途分配给具体子服务，又把 Nuance 对话式 AI/环境智能对应到 Healthcare。两层推断缺少充分依据；引用索引补齐没有修复此语义问题。'),
    ]:
        edge = next(e for e in draft['relationships'] if e['source_id']==source and e['target_id']==target)
        checks.append(dict(label=source + ' → ' + target, status='needs_improvement',
            source_block_ids=edge['evidence_block_ids'], observation=observation, inspected_relationship=edge))
    for ids, label, blocks in [
        (['azure_ai', 'azure_security'], '原先遗漏的 Azure AI 与 Azure Security 已有节点', ['block-000128-edef168d', 'block-000134-9ca2b5c6']),
        (['github', 'github_cloud', 'nuance_healthcare', 'nuance_healthcare_cloud'], '整体与云子集分开', ['block-000120-c34f7245', 'block-000130-8d7ff1f7']),
    ]:
        # Only the narrow observed improvement is marked pass, not all node claims.
        if not all(i in nodes for i in ids):
            raise ValueError('reviewed_improvement_node_missing:' + ','.join(ids))
        checks.append(dict(label=label, status='pass', source_block_ids=blocks,
            observation='已核对相关节点身份及原文。此项只表示已出现且区分身份，不代表每条属性和关系均已验收。'))
    binding = {key: manifest[key] for key in ('trace_id', 'source_packet_sha256', 'skill_sha256')}
    binding.update({key: sha(stage/name) for key, name in [('business_map_sha256','business_map.json'), ('result_sha256','result.json'), ('request_sha256','request.json')]})
    report = dict(schema_version='business-map-independent-review-v1', status='needs_revision', binding=binding,
        criteria_sha256=sha(Path(__file__).with_name('criteria.json')),
        summary='系统自主修订为76个节点、81条关系，原先遗漏和整体/云子集表达已有改善。仍有字段引用不完整、整体/子集端点冲突和父组能力下放，因此09内容验收未通过。',
        review_method='Codex 事后回读冻结原文与实际模型原答。检查节点/边及重点引文；这是开发回归，不是盲测，也不是全图逐子句独立认证。',
        separate_statuses=dict(execution_ownership='system_agent', structural_contract='passed', selected_stage_semantic_fidelity='needs_revision'),
        checks=checks, limitations=['本次列出可证实的缺口，不将其解释为全部缺口。', '未验收所有声明；产品、客户及赚钱方式详细属性仍为空。', '未执行浏览器视觉检查。', '本评审只用于事后验收，没有回传给执行模型。'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
