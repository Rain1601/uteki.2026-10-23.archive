"""Continue this task with model-generated semantic feedback, never reference data."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


async def main():
    from uteki.agents.business_map import self_review
    from uteki.agents.runtime.local_credentials import load_provider_key

    initial = json.loads((HERE / 'run-01/summary.json').read_text())
    if (initial['status'] != 'candidate' or initial['unknown_requests']
            or initial['in_flight_requests'] or not initial['candidate_path']):
        raise ValueError('settled_own_candidate_required')
    source = (ROOT / initial['candidate_path']).resolve()
    if not source.is_relative_to(HERE / 'run-01'):
        raise ValueError('candidate_must_belong_to_this_task')
    output = HERE / 'self-review-01'
    if output.exists():
        raise ValueError('frozen_review_exists_no_resubmission')
    remaining = Decimal('3') - Decimal(initial['estimated_spent_usd'])
    if remaining <= 0:
        raise ValueError('task_budget_exhausted')
    print(json.dumps({'stage': 'own_model_semantic_review',
                      'prior_task_estimated_usd': initial['estimated_spent_usd'],
                      'remaining_task_usd': str(remaining),
                      'reference_input': False}), flush=True)
    if '--execute' not in sys.argv:
        return
    load_provider_key(ROOT, 'aihubmix')
    result = await self_review.execute(root=ROOT, input_run=source, output=output,
        observation_root=ROOT / 'data/agent_observability/local',
        budget_limit_usd=str(remaining))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
