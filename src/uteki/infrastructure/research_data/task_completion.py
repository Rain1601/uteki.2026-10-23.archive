"""Evaluate host-owned progress against verified receipts; never query a model.

Constructed by TaskProgressSession with its frozen node inventories. Receipts
must have passed that session's canonical evidence packager. External callers
use the session (or hash-pinned replay), never submit self-declared completion.
"""
from copy import deepcopy

from uteki.domain.research_data.task_completion import CompletionAssessment, aggregate
from uteki.domain.research_data.task_plan import TaskPlan, ProgressSnapshot
from .financial_records import digest
from .query_completion import QueryCompletionEvaluator


def check(key, status, reason, detail, **refs):
    return dict(check_id=key, status=status, reason=reason, detail=detail, **refs)


class TaskCompletionEvaluator(QueryCompletionEvaluator):
    def __init__(self, plan, inventories):
        self._plan = TaskPlan.model_validate(plan).model_copy(deep=True)
        self._inventories = deepcopy(inventories)

    def evaluate(self, progress, receipts, *, step_limit):
        state = ProgressSnapshot.model_validate(progress).model_dump(mode='json')
        plan = self._plan
        if (state['plan_id'] != plan.plan_id or state['plan_sha256'] != digest(plan.model_dump(mode='json'))
                or state['snapshot_id'] != plan.scope.snapshot_id):
            raise ValueError('Completion input differs from the bound plan/snapshot')
        if [t['task_id'] for t in state['tasks']] != [t.task_id for t in plan.tasks]:
            raise ValueError('Completion input cannot omit, reorder or introduce tasks')
        if not 0 <= state['sequence'] <= step_limit:
            raise ValueError('Completion progress exceeds the original execution limit')
        known = {(t.task_id, r.requirement_id) for t in plan.tasks for r in t.requirements}
        if any((r['request']['task_id'], r['request']['requirement_id']) not in known
               or not 0 < r['sequence'] <= state['sequence'] for r in receipts):
            raise ValueError('Completion receipt is not bound to this task history')
        if len({r['sequence'] for r in receipts}) != len(receipts):
            raise ValueError('Duplicate completion receipts')
        local = {}
        for task, tracked in zip(plan.tasks, state['tasks']):
            if [r['requirement_id'] for r in tracked['requirements']] != [r.requirement_id for r in task.requirements]:
                raise ValueError('Completion input cannot omit or introduce requirements')
            requirements = []
            for req, observed in zip(task.requirements, tracked['requirements']):
                if req.kind != observed['kind']:
                    raise ValueError('Completion requirement kind changed')
                own = [r for r in receipts if r['request']['task_id'] == task.task_id
                       and r['request']['requirement_id'] == req.requirement_id]
                if req.kind == 'read_node':
                    checks = self._read(task, req, observed, own)
                elif req.kind == 'query':
                    checks = self._query(req, own)
                else:
                    checks = [check('clarification', 'blocked', 'caller_clarification_required', req.question)]
                requirements.append(dict(requirement_id=req.requirement_id, condition=req.condition,
                    status=aggregate(c['status'] for c in checks), checks=checks, retained_issues=observed['issues']))
            local[task.task_id] = dict(task_id=task.task_id, requirements=requirements)
        evaluated = {}

        def visit(task):
            if task.task_id in evaluated:
                return evaluated[task.task_id]
            dependencies = []
            for parent_id in task.depends_on:
                parent = visit(next(t for t in plan.tasks if t.task_id == parent_id))
                ok = parent['status'] == 'satisfied'
                dependencies.append(check('dependency:' + parent_id, 'satisfied' if ok else 'blocked',
                    'dependency_satisfied' if ok else 'dependency_unsatisfied',
                    '前置任务 ' + parent_id + (' 的取证条件已满足。' if ok else ' 的取证条件尚未满足。')))
            row = local[task.task_id]
            row.update(dependency_checks=dependencies,
                       status=aggregate([r['status'] for r in row['requirements']] + [d['status'] for d in dependencies]))
            evaluated[task.task_id] = row
            return row

        tasks = [visit(t) for t in plan.tasks]
        status = aggregate(t['status'] for t in tasks)
        remaining = step_limit - state['sequence']
        return CompletionAssessment(plan_id=plan.plan_id, plan_sha256=state['plan_sha256'],
            progress_sha256=digest(state), sequence=state['sequence'], step_limit=step_limit,
            steps_remaining=remaining, conditions_status=status,
            status='limited' if not remaining and status != 'satisfied' else status,
            finish_allowed=status == 'satisfied', tasks=tasks).model_dump(mode='json')

    def _read(self, task, req, state, receipts):
        inventory = self._inventories[(task.task_id, req.requirement_id)]
        if state['availability'] != inventory['status'] or state['required_body'] != inventory['body']:
            raise ValueError('Completion reading inventory differs from frozen node')
        if inventory['status'] != 'available':
            return [check('read_scope', 'blocked', inventory['status'], '指定正文范围不可用，不能按零未读判定完成。')]
        if not inventory['body']:
            return [check('read_scope', 'blocked', 'no_body_blocks', '该范围没有可核验正文；图片或布局块不能替代正文要求。')]
        seen, aids, sequences = set(), set(), []
        for receipt in receipts:
            value = receipt['result']
            if receipt['request']['action'] != 'read_source' or value['status'] != 'read':
                continue
            if value['source_snapshot_id'] != req.source_snapshot_id or value['node_id'] != req.node_id:
                raise ValueError('Read receipt differs from requirement')
            sequences.append(receipt['sequence'])
            package = receipt['package']
            roots = [a for a in package['artifacts'] if a['kind'] in ('source_text', 'source_table')
                     and a['provenance']['verification'] == 'source_verified']
            for block in value['blocks']:
                entry = inventory['blocks'][block['block_id']]
                if entry['mode'] != 'body':
                    continue
                matches = [a for a in roots if a['payload']['block'] == block and any(
                    loc['source_snapshot_id'] == req.source_snapshot_id and loc['index_id'] == entry['ref']['index_id']
                    and loc['block_id'] == block['block_id'] for loc in a['locators'])]
                if not matches:
                    raise ValueError('Read receipt has no verified source artifact')
                seen.add(digest(entry['ref']))
                aids.update(a['artifact_id'] for a in matches)
        unread = [ref for ref in inventory['body'] if digest(ref) not in seen]
        if ({digest(ref) for ref in state['returned_body']} != seen or state['unread_body'] != unread
                or len(state['returned_body']) != len(seen)):
            raise ValueError('Reading progress differs from actual verified receipts')
        return [check('read_scope', 'satisfied', 'scope_available', '正文范围已绑定冻结来源和章节。'),
                check('body_coverage', 'missing_evidence' if unread else 'satisfied',
                      'unread_body_remaining' if unread else 'all_body_returned',
                      f"正文已返回 {len(seen)} / {len(inventory['body'])} 块；仍缺 {len(unread)} 块。",
                      artifact_ids=sorted(aids), event_sequences=sequences, remaining_count=len(unread))]
