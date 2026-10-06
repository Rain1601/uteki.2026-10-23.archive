"""Opt-in SEC inline identity checks and atomic, immutable byte publication.

Identity and basic document completeness do not establish financial correctness.
Transport status and Content-Length must still be checked by the downloader.
"""
from __future__ import annotations

from datetime import date
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from lxml import etree

VALIDATION_VERSION = 'sec-inline-identity-v1'
_INLINE = {'http://www.xbrl.org/2013/inlineXBRL', 'http://www.xbrl.org/2008/inlineXBRL'}
_FORMS = {'10-K', '10-K/A', '20-F', '20-F/A', '10-Q', '10-Q/A', '8-K', '8-K/A'}


def _directory(path):
    """Open/create each directory without following symlinks, retaining a stable fd."""
    absolute = Path(os.path.abspath(path))
    fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            try:
                os.mkdir(part, mode=0o755, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _same_bytes(fd, name, raw):
    original = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(original, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != len(raw) or stream.read(len(raw) + 1) != raw:
            raise ValueError('immutable_artifact_conflict')


def atomic_write_new(path, raw):
    """Publish bytes atomically without replacement; equal existing bytes are reused.

    Leftover temporary files from a killed process are never treated as published
    artifacts. No symlink in the target directory chain or final name is followed.
    Returns ``created`` or ``reused``. Does not repair an existing corrupt object.
    """
    if not isinstance(raw, bytes):
        raise ValueError('artifact_bytes_required')
    try:
        path = Path(path)
    except (TypeError, ValueError) as error:
        raise ValueError('invalid_artifact_path') from error
    if path.name in ('', '.', '..') or '..' in path.parts:
        raise ValueError('invalid_artifact_path')
    fd, temporary = None, None
    try:
        fd = _directory(path.parent)
        try:
            _same_bytes(fd, path.name, raw)
            return 'reused'
        except FileNotFoundError:
            pass
        temporary = '.' + path.name + '.' + uuid.uuid4().hex + '.tmp'
        writable = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(writable, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path.name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        except FileExistsError:
            _same_bytes(fd, path.name, raw)
            return 'reused'
        os.fsync(fd)
        return 'created'
    except OSError as error:
        raise ValueError('artifact_publication_failed:' + type(error).__name__) from error
    finally:
        if fd is not None:
            try:
                if temporary:
                    try:
                        os.unlink(temporary, dir_fd=fd)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(fd)


def _cik(value):
    text = str(value)
    if not re.fullmatch(r'\d{1,10}', text) or not 0 < int(text) < 10**10:
        raise ValueError('invalid_cik')
    return f'{int(text):010d}'


def _iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid_report_period')
    return date.fromisoformat(value).isoformat()


def _namespace(node, prefix):
    for ancestor in (node, *node.iterancestors()):
        namespace = ancestor.get('xmlns:' + prefix)
        if namespace:
            return namespace
    return None


def _period(text, format_name):
    local = (format_name or '').split(':')[-1].replace('-', '').lower()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        if local not in {'', 'dateyearmonthday', 'dateyearmonthdayen'}:
            raise ValueError('unsupported_inline_date_format')
        return _iso_day(text)
    if local not in {'datemonthdayyear', 'datemonthdayyearen', 'datemonthnamedayyearen'}:
        raise ValueError('unsupported_inline_date_format')
    numeric = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', text)
    if numeric:
        month, day, year = map(int, numeric.groups())
    else:
        named = re.fullmatch(r'([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})', text)
        months = ('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                  'september', 'october', 'november', 'december')
        if not named or named[1].lower() not in {*months, *(m[:3] for m in months)}:
            raise ValueError('invalid_inline_report_period')
        month = next(i for i, m in enumerate(months, 1) if named[1].lower() in (m, m[:3]))
        day, year = int(named[2]), int(named[3])
    return date(year, month, day).isoformat()


def validate_sec_filing(raw, expected_cik, expected_form, expected_period_end):
    """Validate modern SEC inline HTML identities; reject unsupported/unknown data.

    Every occurrence of each required DEI identity must agree. This checks the
    document's declared identities, not the correctness of financial statements.
    """
    cik, period = _cik(expected_cik), _iso_day(expected_period_end)
    if not isinstance(expected_form, str) or expected_form not in _FORMS:
        raise ValueError('unsupported_expected_form')
    if not isinstance(raw, bytes) or not raw:
        raise ValueError('empty_or_nonbytes_filing')
    if raw.lstrip().startswith(b'%PDF-'):
        raise ValueError('unsupported_pdf_filing_identity')
    stripped = re.sub(rb'<!--.*?-->|<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>', b'', raw, flags=re.I | re.S)
    if not re.search(rb'<html\b', stripped, re.I) or not re.search(rb'</body\s*>\s*</html\s*>\s*$', stripped, re.I):
        raise ValueError('incomplete_or_unsupported_html_filing')
    parser = etree.HTMLParser(no_network=True, recover=True)
    try:
        root = etree.fromstring(raw, parser)
    except (etree.LxmlError, ValueError) as error:
        raise ValueError('invalid_html_filing') from error
    if root is None or any(entry.level_name == 'FATAL' for entry in parser.error_log):
        raise ValueError('invalid_or_truncated_html_filing')
    headlines = [' '.join(x.itertext()).strip().casefold() for x in root.xpath('//title | //h1')]
    error_markers = ('access denied', 'request rate threshold exceeded', 'undeclared automated tool',
                     'verify you are human', 'just a moment', 'attention required', 'captcha')
    if any(marker in text for text in headlines for marker in error_markers):
        raise ValueError('http_error_or_challenge_document')
    wanted = {'entitycentralindexkey': cik, 'documenttype': expected_form, 'documentperiodenddate': period}
    found = {key: [] for key in wanted}
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        prefix, _, tag = node.tag.lower().rpartition(':')
        if tag != 'nonnumeric' or _namespace(node, prefix) not in _INLINE:
            continue
        name_prefix, sep, concept = node.get('name', '').partition(':')
        key = concept.lower()
        if not sep or key not in wanted:
            continue
        if not re.fullmatch(r'https?://xbrl\.sec\.gov/dei/\d{4}(?:-\d{2}-\d{2})?', _namespace(node, name_prefix) or ''):
            continue
        if node.get('continuedat') or any(str(child.tag).lower().endswith(':exclude') for child in node.iterdescendants()):
            raise ValueError('unsupported_inline_identity_structure')
        text = ' '.join(''.join(node.itertext()).split())
        actual = _cik(text) if key == 'entitycentralindexkey' else _period(text, node.get('format')) if key == 'documentperiodenddate' else text
        if actual != wanted[key]:
            raise ValueError('filing_identity_mismatch:' + key)
        found[key].append({'text': text, 'normalized': actual, 'context_ref': node.get('contextref'), 'format': node.get('format')})
    if any(not facts for facts in found.values()):
        raise ValueError('missing_inline_filing_identity:' + ','.join(k for k, v in found.items() if not v))
    return {'validation_version': VALIDATION_VERSION, 'status': 'identity_validated',
            'cik': cik, 'form': expected_form, 'period_end': period,
            'content_sha256': hashlib.sha256(raw).hexdigest(), 'content_bytes': len(raw),
            'evidence': found, 'financial_semantics': 'not_evaluated',
            'completeness': 'html_envelope_checked_transport_validation_still_required'}
