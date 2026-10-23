"""Read-only checks for a financial delivery; never a semantic/gold evaluator."""
import argparse
import json
from pathlib import Path


def check(value, requirements):
    # Accept the package, DataService response, or run_query wrapper.
    for _ in range(2):
        if isinstance(value, dict) and 'needs' not in value and isinstance(value.get('delivery'), dict):
            value = value['delivery']
    errors, gaps = [], []
    if not isinstance(value, dict):
        return dict(valid=False, complete=False, errors=['delivery must be an object'], gaps=[], business_semantics_verified=False)
    def key(ref):
        if not isinstance(ref, dict) or set(ref) != {'run_id', 'operation_id', 'kind', 'item_id'}:
            raise ValueError('invalid result_ref shape')
        if not all(isinstance(v, str) and v for v in ref.values()):
            raise ValueError('empty result_ref field')
        return json.dumps(ref, sort_keys=True)
    try:
        expected = {n['need_id']: set(n['required_result_kinds']) for n in requirements['needs']}
        if not expected or len(expected) != len(requirements['needs']):
            raise ValueError('requirements need IDs must be nonempty and unique')
        if any(not kinds or not kinds <= {'record', 'calculation', 'evidence'} for kinds in expected.values()):
            raise ValueError('invalid required result kinds')
        needs = {n['need_id']: n for n in value['needs']}
        if len(needs) != len(value['needs']) or set(needs) != set(expected):
            raise ValueError('delivery needs differ from task requirements')
        index = {}
        for group, kind in [('records', 'record'), ('calculations', 'calculation'), ('evidence', 'evidence')]:
            for item in value[group]:
                ref = item['result_ref']
                if ref['kind'] != kind or ref['run_id'] != value['run_id']:
                    raise ValueError('result kind or run differs from package')
                k = key(ref)
                if k in index:
                    raise ValueError('duplicate result_ref')
                index[k] = item
                if kind != 'calculation':
                    if not all(item.get(f) for f in ('asset_ref', 'locator', 'source_object')):
                        raise ValueError('source result lacks asset, locator or original object')
        def closure(ref, active=None):
            active = set() if active is None else active
            k = key(ref)
            if k not in index or k in active:
                raise ValueError('missing or cyclic result dependency')
            item = index[k]
            kind = item['result_ref']['kind']
            usable = (kind == 'evidence' or
                      kind == 'record' and item.get('value') is not None and item.get('unit') and item.get('period') or
                      kind == 'calculation' and item.get('value') is not None and not item.get('limitations')
                      and item.get('formula') and item.get('unit') and len(item.get('operand_refs', [])) >= 2)
            found = {kind} if usable else set()
            for dependency in item.get('dependency_refs', []) + item.get('operand_refs', []):
                found |= closure(dependency, active | {k})
            return found
        for item in index.values():
            closure(item['result_ref'])
        for need_id, need in needs.items():
            kinds = set()
            for ref in need['result_refs']:
                kinds |= closure(ref)
            if need['status'] == 'supported':
                if need['gaps'] or not expected[need_id] <= kinds:
                    errors.append(need_id + ': supported lacks required result kinds or has gaps')
            elif need['status'] in {'partial', 'unresolved'}:
                if not need['gaps'] or not all(isinstance(g, str) and g.strip() for g in need['gaps']):
                    errors.append(need_id + ': partial/unresolved requires explicit gaps')
                gaps.append(dict(need_id=need_id, reasons=need['gaps']))
            else:
                errors.append(need_id + ': unknown status')
        if value.get('business_status') != ('partial' if gaps else 'completed'):
            errors.append('package business_status differs from needs')
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    return dict(valid=not errors, complete=not errors and not gaps, errors=errors, gaps=gaps,
                business_semantics_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', type=Path, required=True)
    parser.add_argument('--requirements', type=Path, required=True)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    result = check(json.loads(args.delivery.read_text()), json.loads(args.requirements.read_text()))
    print(json.dumps(result, ensure_ascii=False))
    return 1 if not result['valid'] else 2 if args.require_complete and not result['complete'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
