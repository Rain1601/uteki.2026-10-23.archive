"""Decimal calculations over explicitly selected, source-bound operands."""
from __future__ import annotations

from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from datetime import date, datetime

from ..contracts.common import canonical, digest
from ..retrieval.index import concept_id, dimensions
from ..contracts.query import validate_period, validate_unit


def decimal_value(op, values):
    """Shared arithmetic for typed source records, independent of their source format."""
    values = [Decimal(v) for v in values]
    if any(not v.is_finite() or len(v.as_tuple().digits)>50 or abs(v.adjusted())>30 for v in values):
        raise ValueError('NUMERIC_MAGNITUDE_UNSUPPORTED')
    if op in {'ratio','growth'} and values[1] == 0:
        raise ValueError('ZERO_DENOMINATOR')
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        if op == 'difference': value = values[0] - values[1]
        elif op == 'ratio': value = values[0] / values[1]
        elif op == 'growth': value = (values[0] - values[1]) / values[1]
        elif op == 'sum': value = sum(values,Decimal(0))
        else: raise ValueError('CALCULATION_UNSUPPORTED')
        if op in {'ratio','growth'}:
            value = value.quantize(Decimal('0.000000000000000001'))
        return format(value,'f')


# 用概念、实体、期间、显式维度和单位定义事实身份，用于阻止求和重复累计同一事实。
def identity(record):
    return [concept_id(record), record['entity_scheme'], record['entity_identifier'],
            record['period'], dimensions(record), record['unit']]


# 仅对已明确选中的事实做确定性 Decimal 运算；无法证明口径可比时返回限制及空值。
def calculate(spec, records):
    formula = {'difference':'operand[0] - operand[1]', 'ratio':'operand[0] / operand[1]',
        'growth':'(operand[0] - operand[1]) / operand[1]', 'sum':'sum(operands)'}[spec.op]
    result = dict(calc_id=spec.calc_id, formula=formula, value=None, unit=spec.output_unit,
        comparison_basis=spec.comparison_basis, period_policy=spec.period_policy,
        arithmetic=dict(precision=50, rounding='ROUND_HALF_EVEN', division_decimal_places=18), limitations=[])

    # 保留公式、比较依据和失败原因，不用零值或其他占位数掩盖计算未完成。
    def fail(code):
        result['limitations'].append(code)
        return result

    # 先检查解析状态和业务可比性，再做算术；有数字并不意味着实体、维度和单位相同。
    if len(records) != len(spec.operands):
        return fail('OPERAND_UNRESOLVED')
    if any(r['status'] != 'parsed' or r['value_decimal'] is None for r in records):
        return fail('OPERAND_NOT_PARSED')
    if any(not r['entity_scheme'] or not r['entity_identifier'] for r in records):
        return fail('ENTITY_UNKNOWN')
    if len({(r['entity_scheme'],r['entity_identifier']) for r in records}) != 1:
        return fail('ENTITY_MISMATCH')
    if len({canonical(dimensions(r)) for r in records}) != 1:
        return fail('DIMENSION_MISMATCH')
    if any(any(d['kind'] != 'explicit' for d in r['dimensions']) for r in records):
        return fail('DIMENSION_UNSUPPORTED')
    units = {canonical(r['unit']) for r in records}
    try:
        for record in records:
            validate_unit(record['unit'])
            validate_period(record['period'])
    except (ValueError,TypeError):
        return fail('OPERAND_METADATA_UNSUPPORTED')
    if len(units) != 1:
        return fail('UNIT_MISMATCH')
    if spec.op in {'ratio','growth'}:
        if spec.output_unit != 'ratio':
            return fail('OUTPUT_UNIT_MISMATCH')
    elif canonical(spec.output_unit) != canonical(records[0]['unit']):
        return fail('OUTPUT_UNIT_MISMATCH')
    # 增长和求和要求同一概念；差值/比值可比较不同概念，但仍受单位、实体和期间约束。
    if spec.op in {'growth','sum'} and len({concept_id(r) for r in records}) != 1:
        return fail('CONCEPT_MISMATCH')
    periods = [r['period'] for r in records]
    # 把来源期间转换为可比较边界，时点的上下界相同，不推导财年或补齐日期。
    def bounds(period):
        values = [period.get('start',period.get('instant')),period.get('end',period.get('instant'))]
        return tuple((datetime.fromisoformat(v) if 'T' in v else date.fromisoformat(v)) for v in values)
    intervals = [bounds(p) for p in periods]
    if len({type(v) for interval in intervals for v in interval})!=1:
        return fail('PERIOD_KIND_MISMATCH')
    if spec.period_policy == 'same':
        if len({tuple(sorted(p)) for p in periods})!=1 or len(set(intervals))!=1:
            return fail('PERIOD_MISMATCH')
        if spec.op == 'growth':
            return fail('GROWTH_REQUIRES_DISTINCT_PERIODS')
    else:
        if len({tuple(sorted(p)) for p in periods}) != 1 or set(periods[0]) not in ({'instant'}, {'start','end'}):
            return fail('PERIOD_KIND_MISMATCH')
        ordered = sorted(intervals)
        # 非重叠期间按闭区间比较，端点相接也视为重叠；时点值不能跨时间相加。
        if any(ordered[i][1] >= ordered[i+1][0] for i in range(len(ordered)-1)):
            return fail('PERIOD_OVERLAP')
        if spec.op == 'sum' and 'instant' in periods[0]:
            return fail('INSTANT_VALUES_NOT_ADDITIVE_ACROSS_TIME')
        # 增长公式固定为第一个减第二个再除第二个，要求第一个操作数确为较晚期间。
        if spec.op == 'growth' and intervals[0][1] <= intervals[1][1]:
            return fail('GROWTH_OPERAND_ORDER')
    # 求和按事实口径去重，而不是按记录 ID；同一事实重复披露不应被重复累计。
    keys = [digest(canonical(identity(r))) for r in records]
    if spec.op == 'sum' and len(keys) != len(set(keys)):
        return fail('DUPLICATE_FACT_IN_SUM')
    try:
        result['value'] = decimal_value(spec.op,[r['value_decimal'] for r in records])
    except ValueError as error:
        return fail(str(error))
    except DecimalException:
        return fail('NUMERIC_OPERATION_UNSUPPORTED')
    return result
