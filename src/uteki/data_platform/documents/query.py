"""SQL-only navigation of versioned documents. Never imports a parser or SDK."""
from __future__ import annotations

import base64
import json
import re
from functools import wraps

from ..contracts.common import TemporalValue, canonical, digest, nonblank
from ..contracts.documents import BlockQuery, BlockRef, ContentBlock


class DocumentStoreError(ValueError):
    def __init__(self, code, message, *, details=None):
        self.code, self.details = code, details
        super().__init__(code+': '+message)


def _limit(value, maximum=100):
    if type(value) is not int or not 1 <= value <= maximum:
        raise DocumentStoreError('INVALID_ARGUMENT', 'limit outside supported range')
    return value


def _position(cursor, signature, version):
    if cursor is None:
        return 0
    try:
        if not isinstance(cursor,str) or len(cursor)>4096:
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if set(value) != {'query','version','offset'} or type(value['offset']) is not int or value['offset']<0:
            raise ValueError()
        if value['query'] != signature or value['version'] != version:
            raise DocumentStoreError('CURSOR_MISMATCH', 'continue with the same query and version')
        return value['offset']
    except (ValueError,TypeError,KeyError) as error:
        if isinstance(error,DocumentStoreError):
            raise
        raise DocumentStoreError('INVALID_CURSOR','malformed cursor') from error


def _cursor(signature, version, offset):
    return base64.urlsafe_b64encode(canonical(dict(query=signature,version=version,offset=offset))).decode()


def _snapshot(method):
    """One public read sees one SQLite snapshot, including its pagination token."""
    @wraps(method)
    def read(self,*args,**kwargs):
        if self._db.in_transaction:
            return method(self,*args,**kwargs)
        self._db.execute('BEGIN')
        try:
            return method(self,*args,**kwargs)
        finally:
            self._db.execute('ROLLBACK')
    return read


def _page(items, *, signature, version, offset, limit, max_bytes=24000):
    result, used = [], 0
    for item in items[:limit]:
        size = len(canonical(item))
        if used+size > max_bytes:
            if not result:
                raise DocumentStoreError('RESULT_TOO_LARGE','one result exceeds max_bytes; increase the byte limit')
            break
        result.append(item); used += size
    more = len(items)>len(result)
    return dict(items=result,next_cursor=_cursor(signature,version,offset+len(result)) if more else None,
                has_more=more,status='ok',returned=len(result))


class DocumentQueries:
    def _parse_row(self, parse_id):
        nonblank(parse_id)
        row = self._db.execute('SELECT * FROM parses WHERE parse_id=?',(parse_id,)).fetchone()
        if row is None:
            raise DocumentStoreError('NOT_FOUND','published parse does not exist')
        return row

    def default_parse(self, material_id):
        nonblank(material_id)
        row = self._db.execute('SELECT parse_id FROM defaults WHERE material_id=?',(material_id,)).fetchone()
        if row is None:
            raise DocumentStoreError('NOT_FOUND','material has no published default version')
        return row['parse_id']

    @_snapshot
    def find_materials(self, *, entity_id=None, entity_role='subject', material_type=None,
                       reporting_period=None, name=None, published_from=None, published_to=None,
                       limit=20, cursor=None):
        """Known publication intervals only; unknown dates do not satisfy date filters.

        Returns each material once, with its default parse explicitly identified.
        No filesystem traversal or parse validation occurs during discovery.
        """
        _limit(limit)
        args = dict(entity_id=entity_id,entity_role=entity_role,material_type=material_type,
                    reporting_period=reporting_period,name=name,published_from=published_from,published_to=published_to,limit=limit)
        for value in args.values():
            if value is not None and not isinstance(value,int):
                nonblank(value)
        if entity_role not in ('issuer','subject','mentioned','publisher'):
            raise DocumentStoreError('INVALID_ARGUMENT','unknown entity role')
        signature = digest(canonical(args))
        version = self._db.execute('SELECT revision FROM store_meta').fetchone()[0]
        offset = _position(cursor,signature,version)
        clauses, parameters = [], []
        if entity_id:
            clauses.append('EXISTS (SELECT 1 FROM material_entities e WHERE e.material_id=m.material_id AND e.entity_id=? AND e.role=?)')
            parameters += [entity_id,entity_role]
        for column,value in [('material_type',material_type),('report_label',reporting_period)]:
            if value is not None:
                clauses.append('m.'+column+'=?');parameters.append(value)
        if name is not None:
            clauses.append('instr(lower(m.name),lower(?))>0');parameters.append(name)
        lower = TemporalValue(value=published_from,precision='date').bounds()[0] if published_from else None
        upper = TemporalValue(value=published_to,precision='date').bounds()[1] if published_to else None
        if lower and upper and lower>=upper:
            raise DocumentStoreError('INVALID_ARGUMENT','inverted publication interval')
        if lower:
            clauses.append('m.published_lower>=?');parameters.append(lower)
        if upper:
            clauses.append('m.published_upper<=?');parameters.append(upper)
        sql = 'SELECT m.payload,d.parse_id FROM materials m JOIN defaults d USING(material_id)'
        if clauses:sql += ' WHERE '+' AND '.join(clauses)
        rows = self._db.execute(sql+' ORDER BY m.material_id LIMIT ? OFFSET ?',(*parameters,limit+1,offset)).fetchall()
        return _page([json.loads(r['payload'])|{'default_parse_id':r['parse_id']} for r in rows],
                     signature=signature,version=version,offset=offset,limit=limit)

    @_snapshot
    def resolve_directory(self, parse_id, path):
        self._parse_row(parse_id)
        if not isinstance(path,(tuple,list)) or not path:
            raise DocumentStoreError('INVALID_ARGUMENT','nonempty path segments required')
        parents = []
        for level, title in enumerate(path):
            nonblank(title)
            clause = 'parent_id IS NULL' if level==0 else 'parent_id IN ('+','.join('?' for _ in parents)+')'
            rows = self._db.execute('SELECT node_id FROM directory_nodes WHERE parse_id=? AND title=? AND '+clause+
                                    ' ORDER BY ordinal,node_id',(parse_id,title,*parents)).fetchall()
            parents = [r[0] for r in rows]
            if not parents:
                raise DocumentStoreError('NOT_FOUND','directory path not found')
        if len(parents)>1:
            candidates = [json.loads(self._db.execute('SELECT payload FROM directory_nodes WHERE parse_id=? AND node_id=?',
                           (parse_id,node_id)).fetchone()[0]) for node_id in parents]
            raise DocumentStoreError('AMBIGUOUS_PATH','use a node ID to disambiguate',details={'candidates':candidates})
        return parents[0]

    def _node(self, parse_id, node_id):
        row = self._db.execute('SELECT payload FROM directory_nodes WHERE parse_id=? AND node_id=?',(parse_id,node_id)).fetchone()
        if row is None:
            raise DocumentStoreError('NOT_FOUND','directory node not in this parse')
        return json.loads(row[0])

    @_snapshot
    def resolve_code_path(self, parse_id, path, *, scope_node_id=None):
        self._parse_row(parse_id)
        if not isinstance(path, str) or not path or any(not p for p in path.split('.')):
            raise DocumentStoreError('INVALID_ARGUMENT', 'nonempty dot-separated code path required')
        parent = scope_node_id
        if parent is not None:
            self._node(parse_id, parent)
        for code in path.split('.'):
            rows = self._db.execute("SELECT node_id FROM directory_nodes WHERE parse_id=? AND parent_id IS ? "
                "AND json_extract(payload,'$.code')=?", (parse_id,parent,code)).fetchall()
            if len(rows) != 1:
                raise DocumentStoreError('NOT_FOUND' if not rows else 'AMBIGUOUS_PATH', 'code path not uniquely resolved')
            parent = rows[0][0]
        return parent

    @_snapshot
    def browse_directory(self, parse_id, *, parent_id=None, limit=50, cursor=None):
        row = self._parse_row(parse_id);_limit(limit)
        if parent_id is not None:self._node(parse_id,parent_id)
        signature=digest(canonical(dict(parse_id=parse_id,parent_id=parent_id,limit=limit)))
        version=row['package_ref'];offset=_position(cursor,signature,version)
        nodes = self._db.execute('SELECT n.payload,(SELECT count(*) FROM directory_blocks d WHERE d.parse_id=n.parse_id AND d.node_id=n.node_id) AS block_count '
            'FROM directory_nodes n WHERE parse_id=? AND parent_id IS ? ORDER BY ordinal,node_id LIMIT ? OFFSET ?',
            (parse_id,parent_id,limit+1,offset)).fetchall()
        return _page([json.loads(n['payload'])|{'block_count':n['block_count']} for n in nodes],
                     signature=signature,version=version,offset=offset,limit=limit)

    @_snapshot
    def get_schema(self, parse_id, *, include_directory=True, max_bytes=1_000_000):
        """A current view from this immutable parse, not another editable schema."""
        _limit(max_bytes,1_000_000)
        if type(include_directory) is not bool:raise DocumentStoreError('INVALID_ARGUMENT','include_directory must be boolean')
        row = self._parse_row(parse_id);parse=json.loads(row['payload'])
        material=json.loads(self._db.execute('SELECT payload FROM materials WHERE material_id=?',(row['material_id'],)).fetchone()[0])
        source=json.loads(self._db.execute('SELECT payload FROM sources WHERE source_version_id=?',(row['source_version_id'],)).fetchone()[0])
        nodes={}
        if include_directory:
            for n in self._db.execute('SELECT payload FROM directory_nodes WHERE parse_id=? ORDER BY ordinal,node_id',(parse_id,)):
                value=json.loads(n[0]);value['children']=[];value['block_count']=0;value['content_types']=[];nodes[value['node_id']]=value
            for n in self._db.execute('SELECT d.node_id,b.type,count(*) AS n FROM directory_blocks d JOIN blocks b USING(parse_id,block_id) WHERE d.parse_id=? GROUP BY d.node_id,b.type',(parse_id,)):
                nodes[n['node_id']]['block_count']+=n['n'];nodes[n['node_id']]['content_types'].append(n['type'])
            roots=[]
            for node in nodes.values():
                if node['parent_id'] is None:roots.append(node)
                else:nodes[node['parent_id']]['children'].append(node)
            def paths(node, prefix, code_prefix):
                node['path']=[*prefix,node['title']]
                node['depth']=len(prefix)+1
                code_path = [*code_prefix,node['code']] if code_prefix is not None and node.get('code') else None
                node['code_path']='.'.join(code_path) if code_path is not None else None
                for child in node['children']:paths(child,node['path'],code_path)
            for root in roots:paths(root,[],[])
        else:roots=[]
        directory={k:v for k,v in parse['directory_schema'].items() if k!='nodes'}
        directory.update(nodes=roots,included=include_directory,block_counts_include_descendants=False)
        counts=dict.fromkeys(('text','table','image'),0)
        counts.update({r['type']:r['n'] for r in self._db.execute('SELECT type,count(*) AS n FROM blocks WHERE parse_id=? GROUP BY type',(parse_id,))})
        tag_counts={r['tag_id']:r['n'] for r in self._db.execute('SELECT tag_id,count(*) AS n FROM block_tags WHERE parse_id=? GROUP BY tag_id',(parse_id,))}
        taxonomy=parse['taxonomy']
        available=[dict(tag_id=t['tag_id'],name=t['name'],block_count=tag_counts[t['tag_id']]) for t in taxonomy['tags'] if t['tag_id'] in tag_counts] if taxonomy else []
        processing={}
        for field in ('ocr','description','tagging'):
            states=dict.fromkeys(('complete','partial','not_processed','failed','not_applicable'),0)
            for state in self._db.execute(
                "SELECT json_extract(payload,?) AS processing_status,count(*) AS n FROM blocks WHERE parse_id=? GROUP BY processing_status",
                ('$.%s.status'%field,parse_id)):
                states[state['processing_status']]=state['n']
            processing[field]=states
        no_match=self._db.execute(
            "SELECT count(*) FROM blocks WHERE parse_id=? AND json_extract(payload,'$.tagging.status')='complete' "
            "AND json_array_length(payload,'$.tagging.tag_ids')=0",(parse_id,)).fetchone()[0]
        value=dict(material=material,source=source,parse_id=parse_id,processors=parse['processors'],
            config_hash=parse['config_hash'],started_at=parse['started_at'],completed_at=parse['completed_at'],
            schema_version=parse['schema_version'],status=parse['status'],issues=parse['issues'],directory=directory,
            tags=dict(taxonomy=taxonomy,available=available,completed_without_match=no_match),
            content_summary=counts,processing=processing,
            capabilities=['browse_directory','query_blocks.directory','query_blocks.tags','query_blocks.text','read_block','read_source','read_resource'])
        if parse['schema_version'] in ('document-v2','document-v3'):
            value['capabilities'] += ['resolve_code_path','read_section','query_blocks.content_view']
        if parse.get('passages') is not None:
            value['capabilities'] += ['list_passages','read_passage','read_block.text_lines']
            value['content_summary']['passages']=len(parse['passages'])
            for node in nodes.values():
                node['passage_count']=sum(p['directory_node_id']==node['node_id'] for p in parse['passages'])
        if len(canonical(value))>max_bytes:
            raise DocumentStoreError('RESULT_TOO_LARGE','request include_directory=false, then browse_directory by parent')
        return value

    def _text_condition(self, query):
        clause='t.origin IN ('+','.join('?' for _ in query.text_origins)+')'
        parameters=list(query.text_origins)
        if query.text_match=='substring' and len(query.text.casefold())<3:
            return clause+' AND instr(t.folded,?)>0',parameters+[query.text.casefold()]
        name='text_terms' if query.text_match=='phrase' else 'text_trigrams'
        value=query.text if query.text_match=='phrase' else query.text.casefold()
        return clause+f' AND t.id IN (SELECT rowid FROM {name} WHERE {name} MATCH ?)', parameters+['"'+value.replace('"','""')+'"']

    @_snapshot
    def query_blocks(self, query: BlockQuery, *, cursor=None):
        query=BlockQuery.model_validate(query)
        row=self._parse_row(query.parse_id);parse=json.loads(row['payload'])
        signature=digest(query.canonical_bytes());version=row['package_ref'];offset=_position(cursor,signature,version)
        clauses=['b.parse_id=?'];parameters=[query.parse_id]
        if query.content_view == 'body':
            if parse['schema_version'] not in ('document-v2','document-v3'):
                raise DocumentStoreError('FILTER_NOT_AVAILABLE', 'this parse has no recorded body-selection policy; use all')
            clauses.append("json_extract(b.payload,'$.body_selection.decision') != 'exclude'")
        node_id=query.directory_node_id
        if query.directory_path is not None:node_id=self.resolve_directory(query.parse_id,query.directory_path)
        if node_id is not None:
            self._node(query.parse_id,node_id)
            if query.include_descendants:
                clause='''b.block_id IN (WITH RECURSIVE subtree(node_id) AS (
                  SELECT node_id FROM directory_nodes WHERE parse_id=? AND node_id=?
                  UNION SELECT n.node_id FROM directory_nodes n JOIN subtree s ON n.parent_id=s.node_id WHERE n.parse_id=?
                ) SELECT d.block_id FROM directory_blocks d JOIN subtree USING(node_id) WHERE d.parse_id=?)'''
                clauses.append(clause);parameters += [query.parse_id,node_id,query.parse_id,query.parse_id]
            else:
                clauses.append('EXISTS (SELECT 1 FROM directory_blocks d WHERE d.parse_id=b.parse_id AND d.block_id=b.block_id AND d.node_id=?)');parameters.append(node_id)
        if query.tags:
            known={t['tag_id'] for t in parse['taxonomy']['tags']} if parse['taxonomy'] else set()
            if not set(query.tags)<=known:raise DocumentStoreError('UNKNOWN_TAG','tag not in this parse taxonomy')
            placeholders=','.join('?' for _ in query.tags)
            clauses.append(f'(SELECT count(*) FROM block_tags g WHERE g.parse_id=b.parse_id AND g.block_id=b.block_id AND g.tag_id IN ({placeholders}))'+('=?' if query.tag_match=='all' else '>0'))
            parameters+=list(query.tags)
            if query.tag_match=='all':parameters.append(len(query.tags))
        if query.types:
            clauses.append('b.type IN ('+','.join('?' for _ in query.types)+')');parameters+=list(query.types)
        if query.text:
            text_clause,text_parameters=self._text_condition(query)
            clauses.append('EXISTS (SELECT 1 FROM block_text t WHERE t.parse_id=b.parse_id AND t.block_id=b.block_id AND '+text_clause+')')
            parameters+=text_parameters
        rows=self._db.execute('SELECT b.block_id,b.type,b.ordinal,b.status FROM blocks b WHERE '+' AND '.join(clauses)+
                              ' ORDER BY b.ordinal,b.block_id LIMIT ? OFFSET ?',(*parameters,query.limit+1,offset)).fetchall()
        items=[]
        for block in rows:
            item=dict(ref=dict(material_id=row['material_id'],parse_id=query.parse_id,block_id=block['block_id']),
                      type=block['type'],order=block['ordinal'],status=block['status'])
            if query.text:
                hits=self._db.execute('SELECT t.origin,t.body FROM block_text t WHERE t.parse_id=? AND t.block_id=? AND '+text_clause,
                                      (query.parse_id,block['block_id'],*text_parameters)).fetchall()
                matches=[]
                for hit in hits:
                    pos=hit['body'].casefold().find(query.text.casefold());start=max(0,pos-50)
                    matches.append(dict(origin=hit['origin'],snippet=hit['body'][start:start+220]))
                item['matches']=matches
            items.append(item)
        return _page(items,signature=signature,version=version,offset=offset,limit=query.limit,max_bytes=query.max_bytes)

    @_snapshot
    def read_section(self, parse_id, *, node_id=None, code_path=None, scope_node_id=None,
                     include_descendants=True, content_view='body', max_bytes=1_000_000):
        """Read one logical section without invoking a parser or cutting its paragraphs."""
        if (node_id is None) == (code_path is None):
            raise DocumentStoreError('INVALID_ARGUMENT', 'choose node_id or code_path')
        if node_id is not None and scope_node_id is not None:
            raise DocumentStoreError('INVALID_ARGUMENT', 'scope applies only to a code path')
        _limit(max_bytes,1_000_000)
        row = self._parse_row(parse_id)
        if code_path is not None:
            node_id = self.resolve_code_path(parse_id,code_path,scope_node_id=scope_node_id)
        node = self._node(parse_id,node_id)
        request = BlockQuery(parse_id=parse_id,directory_node_id=node_id,include_descendants=include_descendants,
                             content_view=content_view,limit=100,max_bytes=1_000_000)
        blocks, cursor = [], None
        while True:
            page = self.query_blocks(request,cursor=cursor)
            for item in page['items']:
                ref = BlockRef.model_validate(item['ref'])
                blocks.append(dict(ref=item['ref'],block=self._block(ref)))
            cursor = page.get('next_cursor')
            if cursor is None:
                break
            if len(canonical(blocks)) > max_bytes:
                raise DocumentStoreError('RESULT_TOO_LARGE','read child sections or increase max_bytes; no partial section returned')
        parse = json.loads(row['payload'])
        text = '\n\n'.join(b['block']['text'] for b in blocks if b['block']['type']=='text')
        result = dict(parse_id=parse_id,node=node,content_view=content_view,include_descendants=include_descendants,
            text=text,blocks=blocks,directory_status=parse['directory_schema']['status'],
            issues=parse['directory_schema']['issues'],truncated=False,
            source_completeness='not_verified',parse_status=parse['status'])
        if parse.get('passages') is not None:
            members={b['ref']['block_id'] for b in blocks}
            result['passages']=[p for p in parse['passages'] if set(p['block_ids']) <= members]
        if len(canonical(result)) > max_bytes:
            raise DocumentStoreError('RESULT_TOO_LARGE','read child sections or increase max_bytes; no partial section returned')
        return result

    @_snapshot
    def list_passages(self, parse_id, *, node_id=None, code_path=None):
        """List direct section groups; indices never flatten descendants."""
        if (node_id is None) == (code_path is None):
            raise DocumentStoreError('INVALID_ARGUMENT','choose node_id or code_path')
        row=self._parse_row(parse_id);parse=json.loads(row['payload'])
        if parse.get('passages') is None:
            raise DocumentStoreError('PASSAGES_NOT_AVAILABLE','this version has no frozen passage grouping')
        if code_path is not None:
            node_id=self.resolve_code_path(parse_id,code_path)
        self._node(parse_id,node_id)
        return [p for p in parse['passages'] if p['directory_node_id']==node_id]

    @_snapshot
    def read_passage(self, parse_id, *, path=None, passage_id=None, max_bytes=1_000_000):
        """Read <native code path>.passages[N] or a version-bound passage ID."""
        if (path is None) == (passage_id is None):
            raise DocumentStoreError('INVALID_ARGUMENT','choose path or passage_id')
        _limit(max_bytes,1_000_000)
        row=self._parse_row(parse_id);parse=json.loads(row['payload'])
        if parse.get('passages') is None:
            raise DocumentStoreError('PASSAGES_NOT_AVAILABLE','this version has no frozen passage grouping')
        if path is not None:
            match=re.fullmatch(r'(.+)\.passages\[(0|[1-9][0-9]*)\]',path) if isinstance(path,str) else None
            if match is None:
                raise DocumentStoreError('INVALID_ARGUMENT','expected native.code.path.passages[nonnegative index]')
            candidates=self.list_passages(parse_id,code_path=match[1])
            chosen=[p for p in candidates if p['index']==int(match[2])]
        else:
            chosen=[p for p in parse['passages'] if p['passage_id']==passage_id]
        if len(chosen)!=1:
            raise DocumentStoreError('NOT_FOUND','passage not found in this version')
        passage=chosen[0];blocks=[]
        for bid in passage['block_ids']:
            ref=BlockRef(material_id=row['material_id'],parse_id=parse_id,block_id=bid)
            blocks.append(dict(ref=ref.model_dump(mode='json'),block=self._block(ref)))
        result=dict(ref=dict(material_id=row['material_id'],parse_id=parse_id,passage_id=passage['passage_id']),
            passage=passage,node=self._node(parse_id,passage['directory_node_id']),blocks=blocks,
            text='\n\n'.join(b['block']['text'] for b in blocks if b['block']['type']=='text'),
            locations=[loc for b in blocks for loc in b['block']['locations']],truncated=False,
            source_completeness='not_verified',parse_status=parse['status'],issues=parse['issues'])
        if len(canonical(result))>max_bytes:
            raise DocumentStoreError('RESULT_TOO_LARGE','passage exceeds max_bytes; no partial passage returned')
        return result

    def _block(self, reference):
        reference=BlockRef.model_validate(reference)
        parse=self._parse_row(reference.parse_id)
        if parse['material_id']!=reference.material_id:
            raise DocumentStoreError('INVALID_REFERENCE','parse belongs to a different material')
        row=self._db.execute('SELECT payload,payload_sha256 FROM blocks WHERE parse_id=? AND block_id=?',
                             (reference.parse_id,reference.block_id)).fetchone()
        if row is None:raise DocumentStoreError('NOT_FOUND','block not in this parse')
        if digest(row['payload'].encode())!=row['payload_sha256']:
            raise DocumentStoreError('STORE_CORRUPT','block payload digest mismatch; use explicit reindex')
        block=ContentBlock.model_validate_json(row['payload'])
        if block.block_id!=reference.block_id:raise DocumentStoreError('STORE_CORRUPT','block identity mismatch')
        return block.model_dump(mode='json')

    @_snapshot
    def read_block(self, reference: BlockRef, *, include_context=True, neighbors=0, max_bytes=1_000_000):
        reference=BlockRef.model_validate(reference);_limit(max_bytes,1_000_000)
        if type(include_context) is not bool or type(neighbors) is not int or not 0<=neighbors<=5:
            raise DocumentStoreError('INVALID_ARGUMENT','invalid context/neighbor option')
        block=self._block(reference);context=[];seen={reference.block_id}
        targets=[(r['block_id'],r['relation']) for r in block['related_blocks']] if include_context else []
        if neighbors:
            for sign,direction in [('<','DESC'),('>','ASC')]:
                rows=self._db.execute(f'SELECT block_id FROM blocks WHERE parse_id=? AND ordinal{sign}? ORDER BY ordinal {direction} LIMIT ?',
                                      (reference.parse_id,block['order'],neighbors)).fetchall()
                targets += [(r['block_id'],'neighbor') for r in rows]
        for identity,relation in targets:
            if identity in seen:continue
            seen.add(identity)
            ref=BlockRef(material_id=reference.material_id,parse_id=reference.parse_id,block_id=identity)
            context.append(dict(relation=relation,ref=ref.model_dump(mode='json'),block=self._block(ref)))
        value=dict(ref=reference.model_dump(mode='json'),block=block,context=context)
        if len(canonical(value))>max_bytes:raise DocumentStoreError('RESULT_TOO_LARGE','block/context exceeds max_bytes; select narrower context or increase limit')
        return value
