"""Opaque, stored cursors. Parameters and material/index revisions cannot drift."""
from __future__ import annotations

from ..contracts.common import CatalogError, canonical, digest, new_id


# 字节预算不改变候选、顺序或读取目标，可在相同游标位置调整。
def fingerprint(context_ref, tool, request, *, legacy_read=False):
    parameters = request.model_dump(mode='json')
    parameters.pop('cursor', None)
    if tool == 'search_asset' or (tool == 'read_evidence' and not legacy_read):
        # Output size changes neither the frozen candidates nor their order.
        # In particular an oversized item can be retried at the SAME position.
        # 查询条件和上下文仍须一致；大项可在原位置增加预算后重读。
        parameters.pop('max_bytes', None)
    return digest(canonical(dict(context_ref=context_ref, tool=tool, parameters=parameters)))


# 首请求从零开始；续页必须匹配原查询及材料/索引版本，否则拒绝使用过期偏移。
def position(session, tool, request, version):
    if request.cursor is None:
        return 0
    saved = session.data['cursors'].get(request.cursor)
    expected = fingerprint(session.data['context']['context_ref'], tool, request)
    legacy = (fingerprint(session.data['context']['context_ref'],tool,request,legacy_read=True)
              if tool == 'read_evidence' else expected)
    if saved is None or saved['fingerprint'] not in (expected,legacy):
        raise CatalogError('CURSOR_MISMATCH', 'cursor belongs to different parameters or context')
    if saved['version'] != version:
        raise CatalogError('CURSOR_EXPIRED', 'material or derived index view changed')
    return saved['offset']


# 生成不透明游标，并把下一位置连同查询指纹、版本保存到当前运行状态。
def advance(session, tool, request, version, offset):
    cursor = new_id('cur')
    session.data['cursors'][cursor] = dict(fingerprint=fingerprint(session.data['context']['context_ref'],tool,request),
        version=version, offset=offset)
    return cursor
