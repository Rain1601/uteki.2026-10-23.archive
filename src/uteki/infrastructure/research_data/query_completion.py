"""Stateless numeric requirement checks over host-verified query receipts.

Callers must authenticate scope and construct receipts with the evidence packager.
This evaluates record, citation and registered-calculation bindings, not prose.
"""
from .financial_records import digest
from .query_service import QueryDataPort


def check(key, status, reason, detail, **refs):
    return dict(check_id=key, status=status, reason=reason, detail=detail, **refs)


class QueryCompletionEvaluator:
    def evaluate_query(self, requirement, receipts):
        return self._query(requirement, receipts)

    def _query(self, req, receipts):
        queries = [r for r in receipts if r['request']['action'] == 'query']
        if not queries:
            return [check('query_execution', 'missing_evidence', 'query_not_returned', '尚无本要求的成功查询与已校验证据包。')]
        receipt = queries[-1]
        if receipt['request']['query'] != req.query.model_dump(mode='json'):
            raise ValueError('Query receipt differs from declared requirement')
        value, package = receipt['result'], receipt['package']
        artifacts = {a['artifact_id']: a for a in package['artifacts']}
        records = {r['record_id']: r for r in value['records']}
        calculations = list({digest(c.model_dump(mode='json')): c for c in req.query.calculations}.values())
        needs = {digest(r.model_dump(mode='json')): r.model_dump(mode='json') for r in req.query.records}
        for calc in calculations:
            needs.update({digest(r.model_dump(mode='json')): r.model_dump(mode='json') for r in QueryDataPort._dependencies(calc)})
        selections = {digest(s['request']): s for s in value['selections']}
        if len(selections) != len(value['selections']) or set(selections) != set(needs):
            raise ValueError('Query selections do not match the declared records/calculation dependencies')
        checks, cited = [], set()
        for key, need in needs.items():
            selection = selections[key]
            ids = selection['record_ids']
            matching = bool(ids) and all(rid in records and all(records[rid].get(k) == v for k, v in need.items()) for rid in ids)
            status = selection['status']
            ok = matching and status in ('matched', 'listed')
            blocked = status in ('unsupported', 'ambiguous', 'quality_filtered', 'not_available_at_cutoff')
            refs = [aid for rid in ids for aid in package['bindings'].get('record:' + rid, [])]
            if ok and any(not self._bound(package, artifacts, 'record:' + rid, 'normalized_record', 'record', records[rid]) for rid in ids):
                raise ValueError('Query record has no matching verified artifact')
            checks.append(check('records:' + key[:24], 'satisfied' if ok else 'blocked' if blocked else 'missing_evidence',
                'records_returned' if ok else 'record_mismatch' if status in ('matched', 'listed') else 'record_' + status,
                f"{need['entity_id']} / {need['metric_id']} / {need['period']['start']} — {need['period']['end']}："
                + ('取得匹配记录。' if ok else '尚未取得无冲突的匹配记录。'),
                record_ids=ids, artifact_ids=refs, event_sequences=[receipt['sequence']]))
            if not ok:
                continue
            for rid in ids:
                if rid in cited:
                    continue
                cited.add(rid)
                checks.append(self._citations(records[rid], package, artifacts, receipt['sequence']))
        for calc in calculations:
            payload = calc.model_dump(mode='json')
            facts = [f for f in value['computed_facts'] if f['formula_id'] == calc.formula_id + '-v1'
                     and f['entity_id'] == calc.entity_id and f['periods'] == payload['periods']]
            facts = list({digest(f): f for f in facts}.values())
            deps = [selections[digest(r.model_dump(mode='json'))] for r in QueryDataPort._dependencies(calc)]
            expected_ids = {rid for s in deps for rid in s['record_ids']}
            ok = len(facts) == 1 and all(s['status'] == 'matched' and s['record_ids'] for s in deps)
            ok = ok and set(facts[0]['operand_record_ids']) == expected_ids
            ok = ok and self._bound(package, artifacts, 'computed:' + facts[0]['computed_id'], 'computed_scalar', 'fact', facts[0])
            checks.append(check('calculation:' + digest(payload)[:24], 'satisfied' if ok else 'missing_evidence',
                'calculation_verified' if ok else 'calculation_or_operands_missing',
                calc.formula_id + (' 的输入完整，结果已由注册计算核验。' if ok else ' 缺少成功计算或完整、匹配的输入记录。'),
                record_ids=sorted(expected_ids), computed_ids=[f['computed_id'] for f in facts],
                artifact_ids=[aid for f in facts for aid in package['bindings'].get('computed:' + f['computed_id'], [])],
                event_sequences=[receipt['sequence']]))
        return checks

    @staticmethod
    def _bound(package, artifacts, key, kind, field, expected):
        ids = package['bindings'].get(key, [])
        return bool(ids) and all(aid in artifacts and artifacts[aid]['kind'] == kind
            and artifacts[aid]['payload'][field] == expected
            and artifacts[aid]['provenance']['verification'] in ('snapshot_verified', 'source_verified') for aid in ids)

    @staticmethod
    def _citations(record, package, artifacts, sequence):
        evidence_ids = set(record['evidence_ids'] + record['qualifier_evidence_ids'] + record['question_evidence_ids'])
        missing, refs = [], set()
        for eid in sorted(evidence_ids):
            ids = package['bindings'].get('evidence:' + eid, [])
            quotes = [artifacts[aid] for aid in ids]
            ok = bool(quotes) and all(a['kind'] == 'source_quote' and a['payload']['evidence']['evidence_id'] == eid
                and a['provenance']['verification'] == 'source_verified' and a['derived_from']
                and all(artifacts[p]['kind'] in ('source_text', 'source_table')
                        and artifacts[p]['provenance']['verification'] == 'source_verified' for p in a['derived_from'])
                and all(loc.get('source_sha256') and loc.get('source_url') and loc.get('available_at')
                        and loc.get('index_id') and loc.get('block_id') for loc in a['locators']) for a in quotes)
            refs.update(ids)
            if not ok:
                missing.append(eid)
        return check('citations:' + record['record_id'], 'missing_evidence' if missing else 'satisfied',
            'source_citation_missing' if missing else 'source_citations_verified',
            ('以下引用未能核验到原文：' + ', '.join(missing)) if missing else '记录及其条件、问答引用均已核验到原文。',
            record_ids=[record['record_id']], artifact_ids=sorted(refs), event_sequences=[sequence], remaining_count=len(missing))
