"""Opaque, stored cursors. Parameters and material/index revisions cannot drift."""
from __future__ import annotations

from ..contracts.common import CatalogError, canonical, digest, new_id


def fingerprint(context_ref, tool, request):
    parameters = request.model_dump(mode='json')
    parameters.pop('cursor', None)
    return digest(canonical(dict(context_ref=context_ref, tool=tool, parameters=parameters)))


def position(session, tool, request, version):
    if request.cursor is None:
        return 0
    saved = session.data['cursors'].get(request.cursor)
    expected = fingerprint(session.data['context']['context_ref'], tool, request)
    if saved is None or saved['fingerprint'] != expected:
        raise CatalogError('CURSOR_MISMATCH', 'cursor belongs to different parameters or context')
    if saved['version'] != version:
        raise CatalogError('CURSOR_EXPIRED', 'material or derived index view changed')
    return saved['offset']


def advance(session, tool, request, version, offset):
    cursor = new_id('cur')
    session.data['cursors'][cursor] = dict(fingerprint=fingerprint(session.data['context']['context_ref'],tool,request),
        version=version, offset=offset)
    return cursor
