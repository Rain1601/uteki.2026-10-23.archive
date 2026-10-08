"""Exact block-relative Unicode character ranges across frozen evidence versions."""


def character_span(evidence, *, text=None):
    """Normalize declared coordinate aliases; never locate by quote search.

    Ranges use zero-based Python/Unicode character offsets and exclusive ends in
    the indexed block text, not bytes or HTML-source offsets. Historical start/end
    and direct-normalization source_start/source_end remain supported.
    """
    ranges = []
    for start_key, end_key in (('source_start', 'source_end'), ('start', 'end'), ('char_start', 'char_end')):
        start, end = evidence.get(start_key), evidence.get(end_key)
        if start is None and end is None:
            continue
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError('Evidence character bounds require explicit nonnegative integer start and exclusive end')
        ranges.append((start, end))
    if not ranges:
        return None
    if any(span != ranges[0] for span in ranges[1:]):
        raise ValueError('Evidence character coordinate aliases conflict')
    start, end = ranges[0]
    if text is not None:
        if end > len(text) or (evidence.get('quote') is not None and text[start:end] != evidence['quote']):
            raise ValueError('Evidence quote character offsets disagree with indexed original')
    return start, end
