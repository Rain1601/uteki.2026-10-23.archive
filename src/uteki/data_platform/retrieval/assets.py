"""Read-only catalog filtering and the same hard scope checks for all tools."""
from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import json
import sqlite3

from ..contracts.assets import AssetRef
from ..contracts.common import CatalogError, SourceTime, canonical, digest
from ..contracts.query import Entities, ReadPolicy, parse


def resolve_entities(catalog, entities, clock):
    groups, securities = [], []
    if entities.company_ids:
        ids = set(entities.company_ids)
        if any(catalog.get_company(i)['status'] != 'confirmed' for i in ids):
            raise CatalogError('ENTITY_NOT_FOUND', 'entity identity is not confirmed')
        groups.append(ids)
    try:
        if entities.company_names:
            groups.append({catalog.resolve_company(n, as_of=clock.date())['company_id'] for n in entities.company_names})
        if entities.securities:
            securities = [catalog.resolve_security(s.ticker,s.exchange_mic,as_of=clock.date()) for s in entities.securities]
            groups.append({s['company_id'] for s in securities})
    except CatalogError as error:
        code = 'ENTITY_AMBIGUOUS' if error.code == 'AMBIGUOUS_ENTITY' else 'ENTITY_NOT_FOUND'
        raise CatalogError(code, str(error)) from error
    if not groups or any(g != groups[0] for g in groups[1:]):
        raise CatalogError('ENTITY_MISMATCH', 'names, securities and IDs do not resolve to the same registered companies')
    return sorted(groups[0]), securities


def metadata(catalog, reference):
    reference = parse(AssetRef, reference)
    build = catalog.get_build(reference.build_id)
    if catalog.asset_ref(build) != reference:
        raise CatalogError('VERSION_MISMATCH', 'reference components do not belong to one build')
    if build['status'] != 'published':
        raise CatalogError('BUILD_NOT_READY', 'build is not published')
    snapshot = catalog.get_snapshot(reference.snapshot_id)
    if snapshot['status'] != 'frozen':
        raise CatalogError('BUILD_NOT_READY', 'snapshot is not frozen')
    asset = catalog.get_asset(reference.asset_id)
    source = catalog._get('sources','source_id',snapshot['source_id'])
    representation = catalog._get('snapshot_representations','representation_id',reference.representation_id)
    # The payload is the original registration, not the current revision view.
    effective = json.loads(asset['payload']) | {'title': asset['title']}
    return dict(asset=asset, asset_data=effective, snapshot=snapshot,
        acquisition=json.loads(snapshot['payload'])['acquisition'], source_id=snapshot['source_id'],
        source=json.loads(source['payload']), format=representation['format'], build=build,
        relations=catalog.snapshot_relations(reference.snapshot_id))


def cutoff(context, requested=None):
    value = context['request'].get('as_of')
    bound = datetime.fromisoformat(value) if value else None
    if requested is not None:
        if bound is not None and requested > bound:
            raise CatalogError('SCOPE_DENIED', 'requested as_of widens the context')
        bound = requested
    return bound.astimezone(timezone.utc) if bound else None


def check_scope(catalog, context, reference, *, requested_as_of=None, roles=('issuer','subject')):
    meta = metadata(catalog, reference)
    allowed = set(context['company_ids'])
    relations = [r for r in meta['relations'] if r['company_id'] in allowed and r['role'] in roles
        and r['status']=='confirmed' and r['evidence']['content_check']=='confirmed']
    if not relations:
        raise CatalogError('SCOPE_DENIED', 'no confirmed snapshot relation to requested entities')
    policy = parse(ReadPolicy, context['read_policy'])
    if meta['source']['source_kind'] not in policy.source_kinds or (policy.source_ids and meta['source_id'] not in policy.source_ids):
        raise CatalogError('SCOPE_DENIED', 'source is outside the frozen read policy')
    bound = cutoff(context, requested_as_of)
    if bound:
        available = parse(SourceTime, meta['acquisition']['available_at'])
        if available.value is None:
            raise CatalogError('SCOPE_TIME_UNKNOWN', 'source availability is unknown; historical cutoff not proven')
        if datetime.fromisoformat(available.value.bounds()[1]) > bound:
            raise CatalogError('SCOPE_DENIED', 'source availability exceeds or straddles cutoff')
    return meta


def view_token(catalog):
    """Material view excludes read-run bookkeeping, includes metadata revisions."""
    tables = ('assets','asset_snapshots','snapshot_representations','asset_builds','asset_relations',
        'snapshot_company_relations','companies','company_aliases','company_securities','sources','policies','metadata_revisions')
    rows = {t:[dict(r) for r in catalog._db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in tables}
    # A saved offset from the former ID-only sort must never resume in a new
    # relevance ordering, even when the catalog rows themselves are unchanged.
    return digest(canonical(dict(catalog_id=catalog.view().catalog_id, tables=rows,
        discovery_version='effective_metadata_rrf_v1')))


def period_match(period, wanted):
    if period is None:
        return None
    if period.get('basis') == 'unknown':
        return None
    for key in ('label','fiscal_year','fiscal_quarter','start','end'):
        value = wanted.get(key)
        if value is not None:
            if period.get(key) is None:
                return None
            if period[key] != value:
                return False
    return True


def candidates(catalog, context, request, *, limit=None):
    filters = request.filters
    cutoff(context, request.as_of)  # Invalid expansion fails even in an empty catalog.
    company_ids = set(context['company_ids'])
    if filters and (filters.company_ids or filters.company_names or filters.securities):
        clock = datetime.fromisoformat(context['clock'])
        selected, _ = resolve_entities(catalog, Entities(company_ids=filters.company_ids,
            company_names=filters.company_names,securities=filters.securities), cutoff(context,request.as_of) or clock)
        if not set(selected) <= company_ids:
            raise CatalogError('SCOPE_DENIED', 'entity filters widen the context')
        company_ids = set(selected)
    if filters:
        for name in filters.material_types:
            catalog._get('material_types','name',name)
    # Rank only the most recent published build of each representation. Scope
    # checks precede content loading, so denied sources are never read as evidence.
    rows = catalog._db.execute("""SELECT b.* FROM asset_builds b JOIN assets a USING(asset_id)
        WHERE b.status='published' AND a.status!='retired'
        ORDER BY b.asset_id,b.snapshot_id,b.representation_id,b.published_at DESC,b.build_id DESC""").fetchall()
    groups = {}
    for row in rows:
        key = (row['asset_id'],row['snapshot_id'],row['representation_id'])
        groups.setdefault(key, []).append(dict(row))
    items, issues, search_text = [], [], []
    narrowed = context | {'company_ids':sorted(company_ids)}
    for builds in groups.values():
        if limit is not None:
            limit.check('asset_candidates')
        reference = catalog.asset_ref(builds[0])
        try:
            meta = check_scope(catalog,narrowed,reference,requested_as_of=request.as_of,
                roles=filters.roles if filters else ('issuer','subject'))
        except CatalogError as error:
            if error.code == 'SCOPE_TIME_UNKNOWN':
                issues.append(dict(code=error.code,message=str(error),asset_ref=reference.model_dump(mode='json')))
                continue
            if error.code == 'SCOPE_DENIED':
                continue
            raise
        asset = meta['asset_data']
        unresolved = []
        periods = context['request']['periods']
        if periods:
            matches = [period_match(asset['reporting_period'],p) for p in periods]
            if not any(m is True for m in matches):
                if any(m is None for m in matches):
                    unresolved.append('reporting_period')
                else:
                    continue
        if filters:
            if any(values and value not in values for value,values in (
                (asset['asset_kind'],filters.asset_kinds), (asset['material_type'],filters.material_types), (meta['format'],filters.formats))):
                continue
            if filters.reporting_periods:
                period = asset['reporting_period']
                if period is None or period.get('label') is None:
                    unresolved.append('reporting_period')
                elif period['label'] not in filters.reporting_periods:
                    continue
            if filters.content_periods:
                # No fiscal label is invented from numeric source dates.
                unresolved.append('content_periods')
            if filters.published_at:
                time = parse(SourceTime,meta['acquisition']['published_at'])
                if time.value is None:
                    unresolved.append('published_at')
                else:
                    lower, upper = map(datetime.fromisoformat,time.value.bounds())
                    bounds = filters.published_at
                    if (bounds.gte and upper < bounds.gte) or (bounds.lt and lower >= bounds.lt):
                        continue
                    if (bounds.gte and lower < bounds.gte) or (bounds.lt and upper >= bounds.lt):
                        unresolved.append('published_at')
        if unresolved:
            issues.append(dict(code='METADATA_UNRESOLVED',message='requested metadata could not be confirmed',
                asset_ref=reference.model_dump(mode='json'),unresolved_fields=unresolved))
        entities = [dict(company_id=r['company_id'],role=r['role'],name=catalog.get_company(r['company_id'])['canonical_name'])
            for r in meta['relations'] if r['status']=='confirmed']
        item = dict(asset_ref=reference.model_dump(mode='json'),asset_kind=asset['asset_kind'],title=asset['title'],
            metadata=dict(entity_refs=entities,material_type=asset['material_type'],format=meta['format'],
                reporting_period=asset['reporting_period'],published_at=meta['acquisition']['published_at'],
                available_at=meta['acquisition']['available_at'],source_urls=[v for v in [meta['acquisition']['final_url']] if v]),
            versions=dict(other_builds=len(builds)-1,revision_relations=[json.loads(r['payload']) for r in meta['asset']['relations']]),
            match=dict(status='unresolved' if unresolved else 'matched',unresolved_fields=unresolved),
            freshness=dict(status='not_confirmed_latest',acquired_at=meta['acquisition']['acquired_at']),issues=[])
        items.append(item)
        aliases = []
        for entity in entities:
            aliases += [r[0] for r in catalog._db.execute('SELECT alias FROM company_aliases WHERE company_id=?',(entity['company_id'],))]
            aliases += [r[0] for r in catalog._db.execute('SELECT ticker FROM company_securities WHERE company_id=?',(entity['company_id'],))]
        search_text.append(' '.join([asset['title'],asset['material_type'],*[e['name'] for e in entities],*aliases]))
    if request.query:
        db = sqlite3.connect(':memory:')
        if limit is not None:
            db.set_progress_handler(lambda:int(limit.stopped()),1000)
        try:
            db.execute("CREATE VIRTUAL TABLE terms USING fts5(i UNINDEXED, body, tokenize='porter unicode61')")
            db.execute("CREATE VIRTUAL TABLE grams USING fts5(i UNINDEXED, body, tokenize='trigram')")
            values = list(enumerate(search_text))
            db.executemany('INSERT INTO terms VALUES (?,?)',values)
            db.executemany('INSERT INTO grams VALUES (?,?)',[(i,t.casefold()) for i,t in values])
            phrase = '"'+request.query.replace('"','""')+'"'
            ranked = [db.execute('SELECT i, bm25(terms) FROM terms WHERE terms MATCH ? ORDER BY bm25(terms), i', (phrase,)).fetchall()]
            folded_phrase = '"'+request.query.casefold().replace('"','""')+'"'
            ranked.append(db.execute('SELECT i, bm25(grams) FROM grams WHERE grams MATCH ? ORDER BY bm25(grams), i', (folded_phrase,)).fetchall())
            if len(request.query)<3:
                ranked.append(sorted((i,-t.casefold().count(request.query.casefold()))
                    for i,t in enumerate(search_text) if request.query.casefold() in t.casefold()))
            # BM25 values from distinct tokenizers are not directly comparable.
            # Equal scores share a dense rank; fuse ranks with exact fractions.
            scores = {}
            for matches in ranked:
                ranks = {score:rank for rank,score in enumerate(sorted({s for _,s in matches}),1)}
                for i,score in matches:
                    scores[i] = scores.get(i,Fraction()) + Fraction(1,60+ranks[score])
            selected = [(i,item) for i,item in enumerate(items) if i in scores]
            selected.sort(key=lambda pair:(-scores[pair[0]],canonical(pair[1]['asset_ref'])))
            items = []
            for i,item in selected:
                item['match']['ranking'] = dict(method='fts5_dense_rrf_v1',score=str(scores[i]))
                items.append(item)
        except sqlite3.Error:
            if limit is not None:
                limit.check('asset_ranking')
            raise
        finally:
            db.close()
    else:
        items.sort(key=lambda item:canonical(item['asset_ref']))
    return items, issues, view_token(catalog)
