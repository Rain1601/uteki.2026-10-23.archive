"""A bounded Inline XBRL numeric subset, with every fact and failure retained."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re

from ..contracts.common import canonical, digest
from ..contracts.evidence import InlineRecord
from .dom import SourceDOM, normalize, tag

INSTANCE = 'http://www.xbrl.org/2003/instance'
DIMENSIONS = 'http://xbrl.org/2006/xbrldi'
INLINE = {'http://www.xbrl.org/2013/inlineXBRL', 'http://www.xbrl.org/2008/inlineXBRL'}
TRANSFORMS = {
    'http://www.xbrl.org/inlineXBRL/transformation/2015-02-26': {'numdotdecimal'},
    'http://www.xbrl.org/inlineXBRL/transformation/2020-02-12': {'num-dot-decimal','fixed-zero'},
}


# 沿当前节点和祖先查找命名空间声明，适配 HTML 解析后保留为属性的 xmlns。
def namespace(node, prefix):
    key = 'xmlns:' + prefix.lower() if prefix else 'xmlns'
    for item in (node, *node.iterancestors()):
        if key in item.attrib:
            return item.attrib[key]
    return None


# 把有效 QName 展开成 {命名空间}局部名，拒绝未绑定前缀或非法名称。
def expanded(node, value):
    if not value or not re.fullmatch(r'(?:[A-Za-z_][\w.\-]*:)?[A-Za-z_][\w.\-]*', value):
        raise ValueError('invalid QName')
    prefix, local = value.split(':', 1) if ':' in value else ('', value)
    uri = namespace(node, prefix)
    if not uri:
        raise ValueError('unbound QName namespace')
    return '{' + uri + '}' + local


# 同时匹配命名空间和局部名，避免只按标签后缀误认 XBRL 元素。
def is_element(node, uri, local):
    name = tag(node)
    if not name:
        return False
    prefix, tail = name.split(':', 1) if ':' in name else ('', name)
    return tail == local.lower() and namespace(node, prefix) == uri


# 返回指定 XBRL instance 元素，包括父节点自身及其后代。
def instance_nodes(parent, local):
    return [n for n in parent.iter() if is_element(n, INSTANCE, local)]


# 解析唯一上下文的实体、期间及维度；typed 维度保留原结构，不推断其语义值。
def context_values(dom, ref):
    nodes = dom.by_id.get(ref, [])
    if len(nodes) != 1 or not is_element(nodes[0], INSTANCE, 'context'):
        raise ValueError('missing, ambiguous or invalid context')
    context = nodes[0]
    identifiers = instance_nodes(context, 'identifier')
    if len(identifiers) != 1 or not identifiers[0].get('scheme') or not normalize(identifiers[0].text_content()):
        raise ValueError('context must have one identified entity')
    periods = instance_nodes(context, 'period')
    if len(periods) != 1:
        raise ValueError('context must have one period')
    period = {}
    for node in periods[0]:
        if not tag(node):
            continue
        local = tag(node).split(':')[-1]
        key = {'startdate': 'start', 'enddate': 'end', 'instant': 'instant', 'forever': 'forever'}.get(local)
        if key is None or key in period or not is_element(node, INSTANCE, local):
            raise ValueError('invalid period children')
        value = normalize(node.text_content())
        if key == 'forever':
            if value:
                raise ValueError('forever period must be empty')
            period[key] = None
        else:
            if 'T' in value:
                datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                date.fromisoformat(value)
            period[key] = value
    if set(period) not in ({'start', 'end'}, {'instant'}, {'forever'}):
        raise ValueError('invalid duration/instant/forever period')
    if 'start' in period and period['start'] > period['end']:
        raise ValueError('reversed context period')
    # 维度必须具有唯一展开名称；typed 维度留原始 HTML，交给事实状态标明 unsupported。
    dimensions = []
    dimension_names = set()
    for node in context.iter():
        if not (is_element(node, DIMENSIONS, 'explicitMember') or is_element(node, DIMENSIONS, 'typedMember')):
            continue
        dimension = expanded(node, node.get('dimension'))
        if dimension in dimension_names:
            raise ValueError('duplicate dimension in context')
        dimension_names.add(dimension)
        typed = is_element(node, DIMENSIONS, 'typedMember')
        dimensions.append({'dimension': dimension, 'kind': 'typed' if typed else 'explicit',
                           'value': dom.snippet(node) if typed else expanded(node, normalize(node.text_content())),
                           'status': 'raw_only' if typed else 'parsed', 'path': dom.path(node)})
    return context, normalize(identifiers[0].text_content()), identifiers[0].get('scheme'), period, tuple(dimensions)


# 解析普通或分式单位并展开 measure 的 QName，拒绝空单位及分式外额外 measure。
def unit_values(dom, ref):
    nodes = dom.by_id.get(ref, [])
    if len(nodes) != 1 or not is_element(nodes[0], INSTANCE, 'unit'):
        raise ValueError('missing, ambiguous or invalid unit')
    node = nodes[0]
    divide = instance_nodes(node, 'divide')
    if divide:
        numerators = instance_nodes(node, 'unitNumerator')
        denominators = instance_nodes(node, 'unitDenominator')
        if len(divide) != 1 or len(numerators) != 1 or len(denominators) != 1:
            raise ValueError('invalid divided unit')
        unit = {'numerator': tuple(expanded(n, normalize(n.text_content())) for n in instance_nodes(numerators[0], 'measure')),
                'denominator': tuple(expanded(n, normalize(n.text_content())) for n in instance_nodes(denominators[0], 'measure'))}
        if len(instance_nodes(node, 'measure')) != sum(map(len, unit.values())):
            raise ValueError('unit has measures outside its divide')
    else:
        unit = {'measures': tuple(expanded(n, normalize(n.text_content())) for n in instance_nodes(node, 'measure'))}
    if any(not values for values in unit.values()):
        raise ValueError('unit has no measures')
    return node, unit


# 仅执行白名单数值变换，再用 Decimal 应用 scale/sign；超出范围与格式非法分别报错。
def numeric(node, raw):
    transform = node.get('format')
    if transform:
        full = expanded(node, transform)
        uri, local = full[1:].split('}', 1)
        if local not in TRANSFORMS.get(uri, set()):
            raise NotImplementedError('unsupported numeric transformation: ' + full)
        if local == 'fixed-zero':
            raw = '0'
        else:
            raw = raw.replace('\u00a0', ' ')
            # Registry 4 deliberately permits digit separators anywhere in the
            # integer part; Registry 3 uses three-digit groups. Do not conflate
            # similarly named transformations from different namespaces.
            pattern = r'[, 0-9]*(\.[ 0-9]+)?' if local == 'num-dot-decimal' else r'[0-9]{1,3}([, ]?[0-9]{3})*(\.[0-9]+)?'
            if not re.fullmatch(pattern, raw) or not re.search('[0-9]',raw):
                raise ValueError('invalid dot-decimal representation')
            raw = raw.replace(',', '').replace(' ', '')
    elif not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', raw):
        raise ValueError('invalid untransformed decimal')
    scale_raw = node.get('scale', '0')
    if not re.fullmatch(r'[+-]?\d+', scale_raw) or len(scale_raw) > 6:
        raise ValueError('invalid scale')
    scale = int(scale_raw)
    if abs(scale) > 4096 or len(raw) > 10000:
        raise NotImplementedError('numeric magnitude exceeds supported bound')
    sign = node.get('sign')
    if sign not in (None, '-'):
        raise ValueError('invalid sign')
    # decimals 在这里校验并保留精度声明，不据此重新舍入或改写源事实值。
    decimals = node.get('decimals')
    if decimals is not None and not re.fullmatch(r'[+-]?\d+|INF', decimals):
        raise ValueError('invalid decimals')
    # 按原字符串长度和缩放幅度设足够十进制精度，避免默认精度造成无意舍入。
    with localcontext() as ctx:
        ctx.prec = max(28, len(raw) + abs(scale) + 8)
        value = Decimal(raw).scaleb(scale)
        if sign == '-':
            value = -value
        return format(value, 'f')


# 逐个保留 nonfraction 数值事实及失败原因，再按显式语义维度标注重复组，不删除重复事实。
def parse_inline(dom: SourceDOM, *, legacy_v1=False):
    records = []
    for node in dom.nodes:
        if tag(node).split(':')[-1] != 'nonfraction':
            continue
        path = dom.path(node)
        issues, invalid, unsupported = [], False, False
        context = unit_node = None
        identifier = scheme = None
        period, dimensions, unit = {}, (), {}
        concept, concept_ns = node.get('name'), None
        try:
            prefix = tag(node).split(':')[0] if ':' in tag(node) else ''
            if namespace(node, prefix) not in INLINE:
                raise ValueError('unbound Inline XBRL element')
            concept_ns = expanded(node, concept)[1:].split('}', 1)[0]
            if node.get('id') and len(dom.by_id[node.get('id')]) != 1:
                raise ValueError('duplicate fact ID')
        except ValueError as error:
            invalid = True; issues.append(str(error))
        # 身份、上下文、单位分别核验并累积问题，某项无效仍保留该条源事实及其定位。
        try:
            context, identifier, scheme, period, dimensions = context_values(dom, node.get('contextref'))
            if any(d['kind'] == 'typed' for d in dimensions):
                unsupported = True; issues.append('typed dimensions retained as raw structure')
        except ValueError as error:
            invalid = True; issues.append(str(error))
        try:
            unit_node, unit = unit_values(dom, node.get('unitref'))
        except ValueError as error:
            invalid = True; issues.append(str(error))
        raw = normalize(node.text_content())
        nil_values = [v for k,v in node.attrib.items() if k.split(':')[-1]=='nil' and ':' in k and namespace(node,k.split(':')[0])=='http://www.w3.org/2001/XMLSchema-instance']
        nil = nil_values == ['true'] or nil_values == ['1']
        if nil_values and nil_values not in (['true'], ['1'], ['false'], ['0']):
            invalid = True; issues.append('invalid xsi:nil')
        complex_content = node.get('continuedat') or any(tag(n).split(':')[-1] in {'exclude','continuation','fraction'} for n in node.iterdescendants())
        if complex_content:
            unsupported = True; issues.append('continuation/exclude/fraction numeric content unsupported')
        value = None
        if nil and raw:
            invalid = True; issues.append('nil fact contains a value')
        if not nil and not invalid and not unsupported:
            try:
                value = numeric(node, raw)
            except NotImplementedError as error:
                unsupported = True; issues.append(str(error))
            except (ValueError, InvalidOperation) as error:
                invalid = True; issues.append(str(error))
        # 状态优先级为非法、不支持、显式 nil、解析成功；仅 parsed 输出解释后的十进制值。
        status = 'invalid' if invalid else 'unsupported' if unsupported else 'nil' if nil else 'parsed'
        records.append(InlineRecord(id='record-'+digest(path.encode())[:24],fact_id=node.get('id'),concept=concept,
            concept_namespace=concept_ns,context_ref=node.get('contextref'),unit_ref=node.get('unitref'),
            raw_value=raw,value_decimal=value if status=='parsed' else None,format=node.get('format'),scale=node.get('scale'),
            sign=node.get('sign'),decimals=node.get('decimals'),entity_identifier=identifier,entity_scheme=scheme,
            period=period,dimensions=dimensions,unit=unit,status=status,issues=tuple(issues),locator=dom.locator(node,raw=True),
            context_path=dom.path(context) if context is not None else None,unit_path=dom.path(unit_node) if unit_node is not None else None,
            duplicate_group=None))
    # 重复分组按概念、实体、期间、维度与单位判定，故意不含数值，便于保留同口径冲突事实。
    groups = defaultdict(list)
    for i, record in enumerate(records):
        # Context IDs and DOM paths do not define semantic equality. Retain all
        # occurrences, grouping only by explicit entity/period/dimensions/unit.
        dims = sorted(({k:v for k,v in d.items() if k!='path'} for d in record.dimensions),key=lambda d:d['dimension'])
        key = digest(canonical([record.concept_namespace,record.concept.split(':')[-1] if record.concept else None,
                                record.entity_identifier,record.entity_scheme,record.period,dims,
                                {k:sorted(v) for k,v in record.unit.items()}]))
        if legacy_v1:
            key = digest(canonical([record.concept_namespace,record.concept,record.entity_identifier,record.entity_scheme,
                                    record.period,dims,record.unit]))
        groups[key].append(i)
    for key, indices in groups.items():
        if len(indices) > 1:
            for i in indices:
                records[i] = records[i].model_copy(update={'duplicate_group':key})
    return tuple(records)
