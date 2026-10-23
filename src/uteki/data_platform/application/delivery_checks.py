"""Deterministic delivery descriptions; source interpretations remain unverified."""
from ..contracts.common import CatalogError, canonical
from .session import ref_key


def section_coverage(evidence):
    """Summarize only frozen page roots actually included in this delivery.

    Keep asset/version, parent path and subtree scope distinct. Overlapping or
    repeated reads count each position once; conflicting inventories fail.
    """
    groups = {}
    for page in evidence:
        if page.get('kind') != 'section_page':
            continue
        loc, cov = page['locator'], page['coverage']
        identity = dict(asset_ref=page['asset_ref'], section_path=loc['section_path'],
                        include_descendants=loc['include_descendants'])
        key = canonical(identity)
        group = groups.setdefault(key, dict(**identity, total_blocks=cov['total_blocks'],
                                            positions={}, pages=[]))
        start, end, total = cov['block_start'], cov['block_end_exclusive'], cov['total_blocks']
        members = page['content']['member_block_ids']
        if (total != group['total_blocks'] or not 0 <= start <= end <= total
                or len(members) != end-start
                or start != loc['block_start'] or end != loc['block_end_exclusive']):
            raise CatalogError('COVERAGE_INCONSISTENT', 'cited section pages disagree with their frozen inventory')
        for position, block in enumerate(members, start):
            prior = group['positions'].setdefault(position, block)
            if prior != block:
                raise CatalogError('COVERAGE_INCONSISTENT', 'cited pages assign different blocks to one position')
        group['pages'].append(dict(block_start=start, block_end_exclusive=end,
                                   block_count=end-start, result_ref=page['result_ref']))
    result = []
    for key in sorted(groups):
        group = groups[key]
        positions = sorted(group.pop('positions'))
        ranges = []
        for position in positions:
            if ranges and position == ranges[-1][1]:
                ranges[-1][1] += 1
            else:
                ranges.append([position, position+1])
        missing, cursor = [], 0
        for start, end in ranges:
            if cursor < start:
                missing.append([cursor, start])
            cursor = end
        if cursor < group['total_blocks']:
            missing.append([cursor, group['total_blocks']])
        group['pages'].sort(key=lambda p: (p['block_start'], p['block_end_exclusive'], canonical(p['result_ref'])))
        result.append(group | dict(origin='code_from_cited_section_pages', index_base=0,
            range_convention='[start,end)', ranges=ranges, missing_ranges=missing,
            delivered_blocks=len(positions), stored_section_complete=not missing,
            source_completeness='not_verified'))
    return result


def checked_source_claims(need, closure):
    """Require exact source quotes in this need's evidence closure, not metadata.

    This check establishes text presence and provenance, never entailment of
    the model's statement. Reuse the extraction layer's source-text projection.
    """
    from ..structured.document_records import source_strings
    allowed = set()

    def visit(reference):
        key = ref_key(reference)
        if key in allowed:
            return
        allowed.add(key)
        item = closure[key]
        for child in item.get('dependency_refs', []) + item.get('operand_refs', []):
            visit(child)

    for reference in need.result_refs:
        visit(reference)
    claims = []
    for claim in need.source_claims:
        support = []
        for proof in claim.support:
            key = ref_key(proof.result_ref)
            if key not in allowed or proof.result_ref.kind != 'evidence':
                raise CatalogError('SOURCE_CLAIM_INVALID', 'source claim requires evidence included in this need; metadata, records and calculations are not source quotes')
            item = closure[key]
            if not item.get('source_object') or not item.get('locator'):
                raise CatalogError('SOURCE_CLAIM_INVALID', 'source quote lacks original source provenance')
            if not any(proof.quote in text for text in source_strings(item)):
                raise CatalogError('QUOTE_NOT_FOUND', 'source claim quote is absent from the cited source evidence; read the exact source or leave a gap')
            support.append(dict(result_ref=item['result_ref'], quote=proof.quote,
                asset_ref=item['asset_ref'], locator=item['locator'], source_object=item['source_object'],
                source_url=item.get('source_url'), quote_match='exact_substring'))
        claims.append(dict(statement=claim.statement, support=support,
            origin='model_interpretation', quote_presence_checked=True,
            semantic_verification='not_performed'))
    return claims
