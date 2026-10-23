"""Source-backed document extraction and calculation through query_records.

Code checks observed quotes, numeric parsing, identity and arithmetic. The
semantic interpretation of those quotes remains explicit, not auto-certified.
"""
from copy import deepcopy
from decimal import Decimal, DecimalException, localcontext
import re
import unicodedata

from ..contracts.common import CatalogError, canonical, digest
from ..contracts.document_query import DocumentRef
from ..contracts.run import ResultRef
from ..application.evidence import result_item
from ..application.session import ref_key
from .calculations import decimal_value


def validate_request(executor):
    request = executor.request
    if request.select.concepts or request.select.fields or request.filters != type(request.filters)():
        raise CatalogError('CAPABILITY_UNSUPPORTED','document records use explicit source extractions and record IDs, not XBRL concepts/filters')
    if request.cursor:
        raise CatalogError('CAPABILITY_UNSUPPORTED','split document extractions/calculations into explicit bounded requests')
    for spec in request.calculations:
        for operand in spec.operands:
            if canonical(operand.asset_ref.model_dump(mode='json')) not in executor.bindings:
                raise CatalogError('SCOPE_DENIED','calculation operand version outside context')
            selector = operand.record_selector
            if not selector.record_id or any(getattr(selector,k) is not None for k in ('concept_id','period','unit','dimensions')):
                raise CatalogError('INVALID_REQUEST','document calculation operands require an observed record_id only')


def numeric(raw, scale):
    text = unicodedata.normalize('NFKC',raw).strip()
    negative = text.startswith('(') and text.endswith(')')
    if negative: text = text[1:-1].strip()
    text = re.sub(r'^[$€£¥]\s*','',text)
    if not re.fullmatch(r'[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?',text):
        raise CatalogError('VALUE_NOT_NUMERIC','read the exact numeric cell/range; unsupported source number format')
    if negative and text.startswith(('-','+')):
        raise CatalogError('VALUE_NOT_NUMERIC','ambiguous numeric sign')
    with localcontext() as context:
        context.prec = 60
        value = Decimal(text.replace(',','')) * (Decimal(10) ** scale)
        if negative: value = -value
        if not value.is_finite() or len(value.as_tuple().digits)>50 or abs(value.adjusted())>30:
            raise CatalogError('VALUE_NOT_NUMERIC','number outside supported precision/magnitude')
        return format(value,'f')


def source_strings(item):
    content = item.get('content',{})
    values = [content.get('text','')]
    values += [c['text'] for c in (content.get('table') or {}).get('cells',[])]
    return values


def require_source_unit(unit, quotes):
    """Require a source label, not an inferred currency normalization.

    Every explicitly quoted code works without a currency/company mapping.
    When no code is printed, retain the unambiguous original full name. This
    proves label presence only, not that the quoted statement applies to a fact.
    """
    def normalize(value):
        return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    label = normalize(unit)
    if label in {'$', '¥', '£', '¤', 'dollar', 'dollars', 'pound', 'pounds',
                 'yen', 'yuan', 'rupee', 'rupees', 'peso', 'pesos', 'franc',
                 'francs', 'won', 'krone', 'krona', 'thousand', 'thousands',
                 'million', 'millions', 'billion', 'billions'}:
        raise CatalogError('UNIT_EVIDENCE_REQUIRED',
            'ambiguous currency label; read and quote an explicit currency code or unambiguous full name, or leave a gap; do not infer a currency from a bare symbol')
    # ASCII boundaries reject USD inside USDC, while leaving source labels in
    # other scripts readable. Do not join separate quotes into invented text.
    pattern = r'(?<![a-z0-9_])' + re.escape(label) + r'(?![a-z0-9_])'
    if not any(re.search(pattern, normalize(quote)) for quote in quotes):
        raise CatalogError('UNIT_EVIDENCE_REQUIRED',
            'unit must literally occur in a cited support.unit quote. Read the original currency statement; if it prints a full name instead of an ISO code, use that full source name as unit. Ambiguous symbols and search snippets cannot supply a missing currency confirmation; otherwise leave a gap.')
    return 'explicit_source_label'


def execute_records(executor):
    session, request = executor.session, executor.request
    copied, records, outputs = {}, {}, []

    def copy_result(reference):
        key = ref_key(reference)
        if key in copied: return copied[key]
        old = session.lookup(reference)
        ref = ResultRef.model_validate(old['result_ref'])
        if ref.kind not in {'evidence','record'}:
            raise CatalogError('RESULT_REF_INVALID','extraction requires source evidence or records')
        asset = old.get('asset_ref')
        if not asset or canonical(asset) not in executor.bindings or asset.get('kind')!='document_parse':
            raise CatalogError('SCOPE_DENIED','result is not from an admitted document version')
        value = deepcopy(old);value.pop('result_ref')
        dependencies = [copy_result(r)['result_ref'] for r in old.get('dependency_refs',[])]
        value['dependency_refs'] = dependencies
        if value.get('support'):
            for claims in value['support'].values():
                for claim in claims:
                    claim['evidence_ref'] = copy_result(claim['evidence_ref'])['result_ref']
        item = result_item(session,executor.operation,ref.kind,value)
        copied[key] = item
        return item

    def quoted(proof, field):
        old = session.lookup(proof.result_ref)
        if proof.result_ref.kind!='evidence' or old.get('asset_ref')!=request.asset_ref.model_dump(mode='json'):
            raise CatalogError('RESULT_REF_INVALID','field support must be source evidence from the selected document')
        if not any(proof.quote in text for text in source_strings(old)):
            raise CatalogError('QUOTE_NOT_FOUND',f'{field} quote is absent from the cited evidence')
        item = copy_result(proof.result_ref)
        return dict(evidence_ref=item['result_ref'],quote=proof.quote), dict(locator=old['locator'],quote=proof.quote)

    for extraction in request.document_records:
        executor.check('document_record_extraction')
        old = session.lookup(extraction.value_evidence)
        if (extraction.value_evidence.kind!='evidence' or old.get('asset_ref')!=request.asset_ref.model_dump(mode='json')
                or old.get('content',{}).get('text')!=extraction.raw_value):
            raise CatalogError('VALUE_SOURCE_MISMATCH','raw_value must equal previously observed numeric evidence text')
        support, stable_support = {}, {}
        for field in ('metric','period','unit','entity','scope'):
            pairs = [quoted(proof,field) for proof in getattr(extraction.support,field)]
            support[field] = [p[0] for p in pairs]
            stable_support[field] = [p[1] for p in pairs]
        unit_basis = require_source_unit(extraction.unit, [p['quote'] for p in support['unit']])
        if not any(re.search(r'(?<![0-9])'+str(extraction.fiscal_year)+r'(?![0-9])',p['quote']) for p in support['period']):
            raise CatalogError('PERIOD_SOURCE_MISMATCH','fiscal year must appear in the period evidence')
        unit_quotes = ' '.join(p['quote'] for p in support['unit']).casefold()
        scales = {exponent for word,exponent in (('thousand',3),('million',6),('billion',9))
                  if re.search(r'\b'+word+r's?\b',unit_quotes)}
        # A statement may say amounts in millions, shares in thousands. The
        # selected multiplier must occur; interpreting which measure it applies
        # to remains an explicit source interpretation, not lexical proof.
        if scales and extraction.scale not in scales:
            raise CatalogError('SCALE_SOURCE_MISMATCH','declared scale conflicts with the quoted source unit')
        if extraction.scale and not scales:
            raise CatalogError('SCALE_UNPROVEN','nonzero scale requires an explicit supported source multiplier')
        observed = copy_result(extraction.value_evidence)
        value = dict(asset_ref=request.asset_ref.model_dump(mode='json'),record_id=extraction.record_id,
            metric=extraction.metric,value=numeric(extraction.raw_value,extraction.scale),raw_value=extraction.raw_value,
            status='parsed',unit={'measures':[extraction.unit]},unit_basis=unit_basis,scale=extraction.scale,
            period=dict(label=extraction.period_label,fiscal_year=extraction.fiscal_year,kind=extraction.period_kind),
            entity_identifier=extraction.entity,entity_scope=extraction.entity_scope,
            locator=deepcopy(old['locator']),source_object=old['source_object'],source_url=old['source_url'],
            support=support,interpretation=extraction.interpretation,semantic_verification='not_performed',
            dependency_refs=list({canonical(r):r for r in [observed['result_ref']]+[
                p['evidence_ref'] for proofs in support.values() for p in proofs]}.values()))
        stable = {k:v for k,v in value.items() if k not in {'support','dependency_refs'}}
        value['record_fingerprint'] = digest(canonical(stable | {'support':stable_support}))
        key = (canonical(value['asset_ref']),value['record_id'])
        previous = [r for r in session.data['results'].values() if r.get('record_id')==value['record_id'] and r.get('asset_ref')==value['asset_ref']]
        if any(r.get('record_fingerprint')!=value['record_fingerprint'] for r in previous):
            raise CatalogError('RECORD_ID_CONFLICT','record_id already identifies different extracted content; use a new explicit ID')
        item = result_item(session,executor.operation,'record',value)
        records[key] = item; outputs.append(item)

    for spec in request.calculations:
        operands = []
        for operand in spec.operands:
            key = (canonical(operand.asset_ref.model_dump(mode='json')),operand.record_selector.record_id)
            if key not in records:
                previous = [r for r in session.data['results'].values() if r.get('asset_ref')==operand.asset_ref.model_dump(mode='json')
                            and r.get('record_id')==operand.record_selector.record_id and 'record_fingerprint' in r]
                if not previous:
                    raise CatalogError('OPERAND_UNRESOLVED','document record ID has not been extracted in this run')
                if len({r['record_fingerprint'] for r in previous})!=1:
                    raise CatalogError('OPERAND_AMBIGUOUS','record ID has conflicting observed content')
                records[key] = copy_result(previous[-1]['result_ref'])
            operands.append(records[key])
        result = calculate_document(spec,operands)
        result['operand_refs'] = [r['result_ref'] for r in operands]
        outputs.append(result_item(session,executor.operation,'calculation',result))
    if not outputs:
        # Explicitly list already extracted records only; absence does not trigger semantic extraction.
        for old in session.data['results'].values():
            if old.get('asset_ref')==request.asset_ref.model_dump(mode='json') and old.get('record_fingerprint'):
                key = (canonical(old['asset_ref']),old['record_id'])
                if key not in records: records[key] = copy_result(old['result_ref'])
        outputs = list(records.values())
    all_items = {canonical(item['result_ref']):item for item in [*copied.values(),*outputs]}
    if len(records)>request.limit:
        raise CatalogError('OUTPUT_LIMIT','reduce explicit record requests; records and dependencies are not truncated')
    return executor.response(list(all_items.values()),issues=[dict(code='CALCULATION_INCOMPLETE',message=reason)
        for item in outputs for reason in item.get('limitations',[])])


def calculate_document(spec, records):
    formula = {'difference':'operand[0] - operand[1]','ratio':'operand[0] / operand[1]',
               'growth':'(operand[0] - operand[1]) / operand[1]','sum':'sum(operands)'}[spec.op]
    result = dict(calc_id=spec.calc_id,formula=formula,value=None,unit=spec.output_unit,
        comparison_basis=spec.comparison_basis,period_policy=spec.period_policy,limitations=[],
        period_basis='explicit_source_reporting_labels_not_invented_calendar_dates',
        semantic_verification='source_interpretations_not_independently_verified')
    def fail(reason):
        result['limitations'].append(reason);return result
    if len(records)!=len(spec.operands): return fail('OPERAND_UNRESOLVED')
    if len({(r['entity_identifier'],r['entity_scope']) for r in records})!=1: return fail('ENTITY_SCOPE_MISMATCH')
    if len({canonical(r['unit']) for r in records})!=1: return fail('UNIT_MISMATCH')
    if spec.op in {'growth','sum'} and len({r['metric'] for r in records})!=1: return fail('METRIC_MISMATCH')
    if spec.op in {'growth','ratio'}:
        if spec.output_unit!='ratio': return fail('OUTPUT_UNIT_MISMATCH')
    elif canonical(spec.output_unit)!=canonical(records[0]['unit']): return fail('OUTPUT_UNIT_MISMATCH')
    periods = [r['period'] for r in records]
    if spec.period_policy=='same':
        if len({canonical(p) for p in periods})!=1: return fail('PERIOD_MISMATCH')
        if spec.op=='growth': return fail('GROWTH_REQUIRES_DISTINCT_PERIODS')
    else:
        # Only explicit annual source-column interpretations are supported here;
        # fiscal years are not invented as calendar start/end dates or instants.
        if any(p['kind']!='annual' for p in periods): return fail('ANNUAL_COMPARISON_REQUIRED')
        years = [p['fiscal_year'] for p in periods]
        if len(set(years))!=len(years): return fail('PERIOD_OVERLAP')
        if spec.op=='growth' and years[0]<=years[1]: return fail('GROWTH_OPERAND_ORDER')
    if spec.op=='sum' and len({canonical([r['metric'],r['entity_identifier'],r['entity_scope'],r['period'],r['unit']]) for r in records})!=len(records):
        return fail('DUPLICATE_FACT_IN_SUM')
    try: result['value'] = decimal_value(spec.op,[r['value'] for r in records])
    except (ValueError,DecimalException) as error: return fail(str(error) or 'NUMERIC_OPERATION_UNSUPPORTED')
    return result
