"""Offline accounting of independent evidence reviews; never infers semantic truth.

The caller must verify the frozen corpus manifest and original-to-block mapping.
``corpus`` is {source_id: {company_id, sha256, blocks: {block_id: text},
metadata: {field: value}}}. Metadata and its original-source binding must also
be verified by the caller. A metadata fact is not invented as a body quote.
Offsets are half-open Python Unicode character offsets, not UTF-8 bytes.
Gold/reference annotations must never be included in the production Agent input.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import re


CATEGORIES = ('required', 'optional', 'necessary_context', 'duplicate',
              'irrelevant', 'unassessed', 'table_structure')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, name):
    _require(isinstance(value, str) and bool(value.strip()), name + ' must be nonblank')
    return value


def _rows(rows, name):
    _require(isinstance(rows, list), name + ' must be a list')
    result = {}
    for row in rows:
        _require(isinstance(row, dict), name + ' entry must be an object')
        identity = _text(row.get('id'), name + ' id')
        _require(identity not in result, name + ' duplicate id')
        result[identity] = row
    return result


def _interval(start, end, length):
    _require(type(start) is int and type(end) is int and 0 <= start < end <= length,
             'invalid or out-of-bounds character interval')


def _money(value):
    _require(isinstance(value, str), 'costs must be decimal strings')
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError('invalid cost') from error
    _require(amount.is_finite() and amount >= 0, 'invalid cost')
    return amount


def _ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'ratio': numerator / denominator if denominator else None}


def evaluate(gold, review, corpus):
    """Validate annotations and count them. Invalid contracts raise ValueError.

    A pass is explicitly conditional on the recorded independent human/Codex
    judgments, including the case-specific focus gate (no universal waste ratio).
    Location verification alone does not verify semantic claims or prove that a
    metadata field answers the stated requirement; those are reviewer judgments.
    Equivalent citations may use any block in a pinned, in-scope source.
    """
    _require(gold.get('schema_version') == 'evidence-gold-v1', 'unsupported gold schema')
    _require(review.get('schema_version') == 'evidence-review-v1', 'unsupported review schema')
    for field in ('case_id', 'question'):
        _text(gold.get(field), field)
        _require(review.get(field) == gold[field], field + ' differs from gold')
    _text(review.get('reviewer'), 'reviewer')
    companies = gold.get('company_ids')
    _require(isinstance(companies, list) and companies and
             all(isinstance(c, str) and c.strip() for c in companies) and
             len(set(companies)) == len(companies), 'explicit unique company scope required')
    _require(isinstance(gold.get('sources'), list) and gold['sources'], 'sources required')
    allowed = {}
    for source in gold['sources']:
        sid = _text(source.get('source_id'), 'source_id')
        _require(sid not in allowed, 'duplicate source_id')
        _require(source.get('company_id') in companies, 'source company outside scope')
        _require(isinstance(source.get('sha256'), str) and
                 re.fullmatch('[0-9a-f]{64}', source['sha256']), 'source SHA256 required')
        supplied = corpus.get(sid, {})
        _require(all(supplied.get(k) == source[k] for k in ('company_id', 'sha256')),
                 'source identity or fingerprint differs')
        _require(isinstance(supplied.get('blocks'), dict), 'source blocks required')
        allowed[sid] = supplied
    _require(set(companies) == {s['company_id'] for s in allowed.values()},
             'every scoped company requires a pinned source')
    required = _rows(gold.get('required'), 'required')
    optional = _rows(gold.get('optional'), 'optional')
    _require(required and not set(required) & set(optional), 'required/optional IDs must be distinct')
    for row in [*required.values(), *optional.values()]:
        _text(row.get('description'), 'requirement description')
        _require(row.get('kind', 'text') in {'text', 'metadata'}, 'invalid requirement kind')

    def metadata_location(item):
        sid, field = item.get('source_id'), item.get('field')
        _require(sid in allowed and isinstance(field, str) and field.strip(), 'invalid metadata source/field')
        metadata = allowed[sid].get('metadata', {})
        _require(field in metadata and type(item.get('value')) is type(metadata[field])
                 and item.get('value') == metadata[field], 'metadata value differs from pinned corpus')
        return sid, field

    metadata_deliveries = _rows(review.get('metadata_deliveries', []), 'metadata deliveries')
    delivered_metadata = {metadata_location(item) for item in metadata_deliveries.values()}

    def location(item):
        sid, bid = item.get('source_id'), item.get('block_id')
        _require(sid in allowed and bid in allowed[sid]['blocks'], 'citation outside pinned corpus')
        body = allowed[sid]['blocks'][bid]
        _require(isinstance(body, str), 'block text must be a string')
        start, end = item.get('start'), item.get('end')
        _interval(start, end, len(body))
        _require(item.get('quote') == body[start:end], 'quote differs from exact source interval')
        return sid, bid, start, end

    # A source character is counted once, even when several delivered excerpts
    # overlap. Conflicting classification of that character requires adjudication.
    occupied, links = {}, {}
    output_chars = 0
    deliveries = _rows(review.get('deliveries'), 'deliveries')
    for delivery in deliveries.values():
        sid, bid, first, last = location(delivery)
        output_chars += last - first
        segments = delivery.get('segments')
        _require(isinstance(segments, list) and segments, 'complete segment annotation required')
        cursor = 0
        for segment in sorted(segments, key=lambda s: s.get('start', -1)):
            start, end = segment.get('start'), segment.get('end')
            _interval(start, end, last - first)
            _require(start == cursor, 'segments overlap or omit characters; annotate unassessed explicitly')
            cursor = end
            category = segment.get('category')
            _require(category in CATEGORIES, 'unknown segment category')
            ids = segment.get('requirement_ids')
            _require(isinstance(ids, list) and all(isinstance(i, str) for i in ids) and
                     len(ids) == len(set(ids)), 'unique requirement_ids required')
            permitted = required if category == 'required' else optional
            _require((bool(ids) and set(ids) <= set(permitted))
                     if category in {'required', 'optional'} else not ids,
                     'segment requirement IDs differ from category')
            for offset in range(first + start, first + end):
                key = sid, bid, offset
                _require(key not in occupied or occupied[key] == category,
                         'overlapping deliveries have conflicting annotations')
                occupied[key] = category
                links.setdefault(key, set()).update(ids)
        _require(cursor == last - first, 'segments omit trailing characters')

    assessments = _rows(review.get('requirements'), 'requirement assessments')
    _require(set(assessments) == set(required), 'assess every required ID exactly once')
    statuses = Counter()
    for identity, assessment in assessments.items():
        status = assessment.get('status')
        _require(status in {'supported', 'partial', 'missing'}, 'invalid requirement status')
        statuses[status] += 1
        _text(assessment.get('reason'), 'assessment reason')
        citations = assessment.get('citations')
        _require(isinstance(citations, list), 'citations must be a list')
        _require(status == 'missing' or citations, 'supported/partial assessments require citations')
        _require(status != 'missing' or not citations, 'missing assessment cannot claim support citations')
        for citation in citations:
            if required[identity].get('kind', 'text') == 'metadata':
                _require(citation.get('kind') == 'metadata', 'metadata requirement needs metadata citation')
                _require(metadata_location(citation) in delivered_metadata,
                         'metadata support must be delivered')
            else:
                _require(citation.get('kind', 'text') == 'text', 'text requirement needs text citation')
                sid, bid, start, end = location(citation)
                _require(all(identity in links.get((sid, bid, pos), set()) for pos in range(start, end)),
                         'support citation must be delivered and linked to this requirement')

    checks = review.get('checks')
    _require(isinstance(checks, dict) and set(checks) == {'scope', 'truth', 'provenance', 'focus'},
             'explicit scope/truth/provenance/focus checks required')
    for check in checks.values():
        _require(check.get('status') in {'pass', 'fail', 'unassessed'}, 'invalid hard-check status')
        _text(check.get('reason'), 'hard-check reason')
    cost = review.get('cost', {})
    known, held = _money(cost.get('known_usd')), _money(cost.get('unknown_reserved_usd'))
    counts = Counter(occupied.values())
    unique_chars = len(occupied)
    optional_covered = {i for key, ids in links.items() if occupied[key] == 'optional' for i in ids}
    gates = {name: check['status'] for name, check in checks.items()}
    gates.update(required_coverage='pass' if statuses['supported'] == len(required) else 'fail',
                 all_characters_assessed='pass' if not counts['unassessed'] else 'unassessed')
    verdict = ('fail' if 'fail' in gates.values() else
               'unassessed' if 'unassessed' in gates.values() else 'pass')
    return {'schema_version': 'evidence-score-v1', 'case_id': gold['case_id'],
            'status': verdict, 'semantic_verification': 'recorded_independent_review_not_machine_proven',
            'location_verification': 'exact_offsets_in_caller_verified_frozen_corpus',
            'gates': gates, 'required_coverage': _ratio(statuses['supported'], len(required)),
            'required_status_counts': {s: statuses[s] for s in ('supported', 'partial', 'missing')},
            'optional_annotated_coverage': _ratio(len(optional_covered), len(optional)),
            'metadata_delivery_count': len(delivered_metadata),
            'characters': {'unique_source_characters': unique_chars,
                'delivered_character_occurrences': output_chars,
                'repeated_location_occurrences': output_chars - unique_chars,
                'categories': {c: _ratio(counts[c], unique_chars) for c in CATEGORIES},
                'non_table_structure_characters': unique_chars - counts['table_structure']},
            'cost': {'known_estimated_usd': str(known), 'unknown_reserved_usd': str(held),
                     'committed_estimated_usd': str(known + held), 'actual_billed_usd': None},
            'reviewer': review['reviewer']}
