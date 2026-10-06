"""Resolve an explicitly selected catalog entry to its hash-pinned source profile.

This is a local registered-company lookup, not global company-name discovery.
The acquisition entry point still validates the effective contact and run scope.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


CATALOG_VERSION = 'company-profile-catalog-v1'
_MARKETS = {'US', 'NASDAQ', 'NYSE', 'NYSEAMERICAN', 'CBOE'}


def _name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('company name or alias must be a nonempty string')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('company name or alias contains control characters')
    return value.strip().casefold()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate catalog or profile JSON key')
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('invalid catalog or profile JSON') from error


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('catalog and profiles must be regular files, not symlinks')
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError('catalog or profile is unavailable') from error


def resolve_company_profile(catalog_path: Path, company: str) -> dict:
    """Return a fresh, unchanged profile for one unambiguous registered alias.

    Identity, policy, cutoff and resource limits come from the selected catalog
    and profile. Unknown companies never fall back to a sample or another file.
    """
    requested = _name(company)
    try:
        path = Path(catalog_path)
    except (TypeError, ValueError) as error:
        raise ValueError('explicit catalog path required') from error
    if '..' in path.parts:
        raise ValueError('catalog path must not contain parent traversal')
    catalog = _json(_read(path))
    if (not isinstance(catalog, dict) or set(catalog) != {'schema_version', 'profiles'}
            or catalog.get('schema_version') != CATALOG_VERSION
            or not isinstance(catalog.get('profiles'), list) or not catalog['profiles']):
        raise ValueError('unsupported or incomplete company catalog')
    matches, identities = [], set()
    for entry in catalog['profiles']:
        required = {'company_id', 'cik', 'symbol', 'market', 'aliases', 'profile'}
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError('invalid company catalog entry')
        cik = entry['cik']
        if not isinstance(cik, str) or not re.fullmatch(r'[0-9]{10}', cik) or int(cik) == 0:
            raise ValueError('catalog CIK must be a nonzero 10-digit SEC identifier')
        if entry['company_id'] != 'sec-' + cik or entry['company_id'] in identities:
            raise ValueError('inconsistent or duplicate catalog company identity')
        identities.add(entry['company_id'])
        if (not isinstance(entry['symbol'], str)
                or not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,14}', entry['symbol'])
                or not isinstance(entry['market'], str) or entry['market'] not in _MARKETS):
            raise ValueError('invalid catalog symbol or market')
        if not isinstance(entry['aliases'], list) or not entry['aliases']:
            raise ValueError('explicit catalog aliases required')
        aliases = [_name(alias) for alias in entry['aliases']]
        if len(aliases) != len(set(aliases)) or _name(entry['symbol']) not in aliases:
            raise ValueError('catalog aliases must be unique and include the symbol')
        profile = entry['profile']
        if not isinstance(profile, dict) or set(profile) != {'filename', 'sha256'}:
            raise ValueError('explicit profile filename and SHA256 required')
        filename, sha = profile['filename'], profile['sha256']
        if (not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.json', filename)
                or not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha)):
            raise ValueError('invalid profile filename or SHA256')
        if requested in aliases:
            matches.append(entry)
    if not matches:
        raise ValueError('company is not registered in the selected catalog')
    if len(matches) != 1:
        raise ValueError('company alias is ambiguous in the selected catalog')
    entry = matches[0]
    profile_path = path.parent / entry['profile']['filename']
    if profile_path.resolve().parent != path.parent.resolve():
        raise ValueError('profile must be in the catalog directory')
    raw = _read(profile_path)
    if hashlib.sha256(raw).hexdigest() != entry['profile']['sha256']:
        raise ValueError('company profile SHA256 mismatch')
    config = _json(raw)
    if not isinstance(config, dict):
        raise ValueError('company profile must be an object')
    if any(config.get(key) != entry[key] for key in ('cik', 'symbol', 'market')):
        raise ValueError('company profile identity disagrees with catalog')
    if 'company_id' in config and config['company_id'] != entry['company_id']:
        raise ValueError('company profile company_id disagrees with catalog')
    if not {'as_of', 'filing_selection', 'source_policy', 'limits'} <= config.keys():
        raise ValueError('company profile must declare its complete acquisition scope')
    return deepcopy(config)
