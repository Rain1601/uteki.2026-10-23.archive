"""Validate a frozen Skill trigger set and score observed native SDK decisions.

This read-only evaluator never invokes a model. Expected labels remain here;
only the ``query`` field may enter an isolated evaluated agent session.
"""
import argparse
import hashlib
import json
from pathlib import Path


def load_cases(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get('schema') != 'uteki-skill-trigger-cases-v1':
        raise ValueError('unsupported case schema')
    cases = data['cases']
    if len(cases) != 40 or len({c['id'] for c in cases}) != 40:
        raise ValueError('40 unique cases required')
    if len({c['query'] for c in cases}) != 40:
        raise ValueError('queries must be distinct')
    positive = 0
    for case in cases:
        if set(case) != {'id', 'query', 'expected_skills', 'category', 'reason'}:
            raise ValueError('unexpected case fields')
        if any(not isinstance(case[k], str) or not case[k].strip()
               for k in ('id', 'query', 'category', 'reason')):
            raise ValueError('case text must be nonempty')
        if case['expected_skills'] not in ([], [data['target_skill']]):
            raise ValueError('unexpected target Skill')
        positive += bool(case['expected_skills'])
    if positive != 30:
        raise ValueError('30 positive and 10 negative cases required')
    for offset in range(0, 40, 4):
        if sum(not c['expected_skills'] for c in cases[offset:offset+4]) != 1:
            raise ValueError('each consecutive block must interleave one negative')
    return data, hashlib.sha256(raw).hexdigest()


def model_input(case):
    """The only case-specific content passed to the evaluated SDK."""
    return case['query']


def score(data, observations):
    """Missing/error observations are unknown, never true negatives.

    An observation records SDK tool events, not a model's yes/no self-report.
    ``selected_skills`` counts requests, ``loaded_skills`` successful loads.
    """
    cases = {c['id']: c for c in data['cases']}
    indexed = {}
    for row in observations:
        name = row['id']
        if name not in cases or name in indexed:
            raise ValueError('unknown or duplicate observation id')
        if row.get('status') not in {'ok', 'error'}:
            raise ValueError('observation status must be ok or error')
        for key in ('selected_skills', 'loaded_skills'):
            if (not isinstance(row.get(key), list)
                    or any(not isinstance(s, str) or not s for s in row[key])
                    or len(set(row[key])) != len(row[key])):
                raise ValueError('Skill observations must be unique string lists')
        if not set(row['loaded_skills']) <= set(row['selected_skills']):
            raise ValueError('a loaded Skill must have a recorded selection')
        indexed[name] = row
    counts = dict(true_positive=0, false_negative=0, false_positive=0, true_negative=0,
                  unknown=0, load_failed=0, unexpected_skill=0)
    failures = []
    for name, case in cases.items():
        row = indexed.get(name)
        if row is None or row['status'] != 'ok':
            counts['unknown'] += 1
            failures.append(dict(id=name, outcome='unknown', error=(row or {}).get('error', 'not_run')))
            continue
        selected = data['target_skill'] in row['selected_skills']
        expected = bool(case['expected_skills'])
        outcome = ('true_positive' if selected else 'false_negative') if expected else (
            'false_positive' if selected else 'true_negative')
        counts[outcome] += 1
        failed_load = selected and data['target_skill'] not in row['loaded_skills']
        unexpected = bool(set(row['selected_skills']) - {data['target_skill']})
        counts['load_failed'] += failed_load
        counts['unexpected_skill'] += unexpected
        if outcome.startswith('false_') or failed_load or unexpected:
            failures.append(dict(id=name, outcome=outcome, load_failed=failed_load,
                unexpected_skill=unexpected, query=case['query'], expected_skills=case['expected_skills'],
                selected_skills=row['selected_skills'], loaded_skills=row['loaded_skills'], reason=case['reason']))
    tp, fn, fp, tn = (counts[k] for k in ('true_positive', 'false_negative', 'false_positive', 'true_negative'))
    ratio = lambda a, b: a/b if b else None
    return dict(total=40, observed=len(indexed), counts=counts, coverage=(40-counts['unknown'])/40,
        selection_recall=ratio(tp, tp+fn), false_positive_rate=ratio(fp, fp+tn),
        selection_precision=ratio(tp, tp+fp), selection_accuracy=ratio(tp+tn, tp+fn+fp+tn),
        complete=counts['unknown'] == 0, failures=failures,
        note='Rates use known native decisions only; always read coverage and load_failed alongside them.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--observations', type=Path, help='One frozen SDK/model run, with cases_sha256 and observations')
    parser.add_argument('--show', action='store_true', help='Print the reviewable 40-case list, including evaluator labels')
    args = parser.parse_args()
    data, digest = load_cases(args.cases)
    if args.observations:
        observed = json.loads(args.observations.read_text())
        if observed['cases_sha256'] != digest:
            raise ValueError('observations belong to a different frozen query set')
        if not all(observed.get(k) for k in ('sdk', 'sdk_version', 'model', 'route', 'prompt_sha256', 'skill_sha256')):
            raise ValueError('explicit SDK/model/route/prompt/Skill provenance required')
        result = score(data, observed['observations'])
    else:
        result = dict(cases_sha256=digest, queries=40, expected_load=30, expected_no_load=10,
            validation='passed', baseline='not_run', real_model_calls=0)
    if args.show:
        result['cases'] = data['cases']
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
