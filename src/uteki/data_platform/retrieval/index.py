"""Explicitly built, integrity-checked FTS5/DuckDB generations for HTML builds."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import sqlite3
import threading

import duckdb

from ..catalog.database import ensure_directory, read_regular, write_control
from ..content.store import _fsync_directory
from ..contracts.common import CatalogError, canonical, digest, new_id, utc_now
from ..contracts.content import ObjectRef

INDEX_VERSION = 'uteki-derived-html-v2'
FILES = {'fts.sqlite', 'records.duckdb'}


# 把来源前缀化概念展开为 {命名空间}本地名，避免不同前缀或同名概念发生混淆。
def concept_id(record):
    name = record['concept']
    namespace = record['concept_namespace']
    return '{'+namespace+'}'+name.split(':')[-1] if name and namespace else None


# 提取显式维度成员用于精确匹配；typed 等未支持维度仍须由调用处另行排除。
def dimensions(record):
    return {d['dimension']:d['value'] for d in record['dimensions'] if d['kind'] == 'explicit'}


# 创建受限 DuckDB 连接，禁用外部访问/自动扩展并限制资源；超时或取消会中断查询。
@contextmanager
def sql_connection(path, *, readonly=True, timeout=20, limit=None):
    if limit is not None:
        timeout = min(timeout,limit.remaining())
    connection = duckdb.connect(str(path), read_only=readonly, config={
        'enable_external_access': False, 'autoinstall_known_extensions': False,
        'autoload_known_extensions': False, 'threads': 1, 'memory_limit': '128MB'})
    # 计时器处理中途超时，watcher 处理共享取消；finally 会停止线程并关闭连接，避免后台残留。
    timer = threading.Timer(timeout, connection.interrupt)
    timer.daemon = True
    timer.start()
    done = threading.Event()
    # 运行期间观察共享限制，一旦任务停止就中断正在执行的 SQL，而不是等结果全部生成。
    def watch():
        while not done.wait(0.02):
            if limit.stopped():
                connection.interrupt()
                return
    watcher = threading.Thread(target=watch,daemon=True) if limit is not None else None
    if watcher is not None:
        watcher.start()
    try:
        yield connection
        if limit is not None:
            limit.check('sql_complete')
    except duckdb.Error:
        if limit is not None:
            limit.check('sql_interrupted')
        raise
    finally:
        done.set()
        if watcher is not None:
            watcher.join()
        timer.cancel()
        timer.join()
        connection.close()


# 管理每个 HTML 构建的派生索引代次：写入由目录独占锁保护，读取只验证且不自动修复。
class DerivedIndex:
    """Catalog's exclusive lock owns writes. Reads never repair an index."""
    # 把索引绑定到读取器的固定构建与共享资源限制，不在此隐式创建或刷新索引。
    def __init__(self, catalog, reader, *, limit=None):
        self.catalog = catalog
        self.reader = reader
        self.reference = reader.reference
        self.base = catalog.root/'derived'/self.reference.build_id
        self.limit = limit

    # 在处理阶段边界检查取消/时间限制，避免已经停止的任务继续做索引工作。
    def check(self):
        if self.limit is not None:
            self.limit.check('derived_index')

    # 重新读取已发布清单并求摘要，作为索引与源构建绑定的校验依据。
    def _source_hash(self):
        manifest = self.catalog.read_published(self.reference)
        return digest(manifest.canonical_bytes())

    # 检查目录安全、head、清单、源版本以及每个文件的字节摘要；返回当前代次和游标版本 token。
    def current(self):
        self.check()
        source = self._source_hash()
        try:
            parent = self.catalog.root/'derived'
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise CatalogError('BUILD_NOT_READY', 'unsafe derived root')
            if not self.base.exists():
                raise CatalogError('BUILD_NOT_READY', 'derived index has not been built')
            if self.base.is_symlink() or not self.base.is_dir():
                raise CatalogError('BUILD_NOT_READY', 'unsafe derived directory')
            head_raw = read_regular(self.base/'head.json')
            head = json.loads(head_raw)
            # 控制文件必须是规范字节且字段集合固定，不能接受含混或多余内容后继续使用索引。
            if canonical(head) != head_raw or set(head) != {'generation', 'manifest'}:
                raise ValueError('invalid index head')
            generation = head['generation']
            if not isinstance(generation, str) or not generation.startswith('idx_') or len(generation) != 30 or not generation[4:].isalnum():
                raise ValueError('invalid index generation')
            directory = self.base/generation
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError('unsafe index generation')
            manifest = json.loads(self.catalog.content.read_object(ObjectRef.model_validate(head['manifest'])))
            if (manifest['schema_version'] != INDEX_VERSION or manifest['generation'] != generation
                    or manifest['asset_ref'] != self.reference.model_dump(mode='json')
                    or manifest['source_manifest_sha256'] != source or set(manifest['files']) != FILES):
                raise ValueError('index source/version mismatch')
            if set(p.name for p in directory.iterdir()) != FILES:
                raise ValueError('unexpected index files')
            # 每次取当前索引都核验两个文件，文件存在或数据库可打开并不足以证明属于此源版本。
            for name, meta in manifest['files'].items():
                raw = read_regular(directory/name)
                if len(raw) != meta['bytes'] or digest(raw) != meta['sha256']:
                    raise ValueError('index file hash mismatch: '+name)
            return directory, manifest, digest(head_raw)
        except (OSError, ValueError, KeyError, TypeError) as error:
            if isinstance(error, CatalogError) and error.code == 'BUILD_NOT_READY':
                raise
            raise CatalogError('BUILD_NOT_READY', 'derived index missing, corrupt or stale; explicit processing required') from error

    # 将索引未就绪转换为显式状态供能力查询使用，其他错误继续上抛。
    def availability(self):
        try:
            _, manifest, token = self.current()
            return dict(status='ready', generation=manifest['generation'], token=token, issue=None)
        except CatalogError as error:
            if error.code != 'BUILD_NOT_READY':
                raise
            return dict(status='not_ready', generation=None, token=None, issue=str(error))

    # 恢复时只确认中断操作已可见的同一代次，核验通过后重新持久化 head，不激活别的版本。
    def confirm_head(self, intent):
        """Confirm only this already-visible generation; never activate another."""
        expected = dict(generation=intent['generation'],manifest=intent['manifest'])
        if intent['asset_ref'] != self.reference.model_dump(mode='json'):
            raise CatalogError('RECOVERY_REQUIRED','index intent belongs to a different asset')
        try:
            _,manifest,token = self.current()
            if token != digest(canonical(expected)):
                raise CatalogError('RECOVERY_REQUIRED','current index head differs from the interrupted publication')
            # A visible rename may have preceded its directory fsync. Reconfirm
            # identical bytes only after full source/manifest/file validation.
            write_control(self.base/'head.json',canonical(expected),replace=True)
            return manifest
        except (OSError,ValueError) as error:
            raise CatalogError('RECOVERY_REQUIRED','cannot confirm interrupted index publication: '+str(error)) from error

    # 在新代次目录构造全文和记录索引，先持久化文件与意图，再切换 head 发布。
    def build(self, *, checkpoint=lambda phase: None, on_effect=lambda **value: None, on_prepare=lambda intent: None):
        """Build a new generation. Failure leaves old generations and head intact."""
        source_hash = self._source_hash()
        inventory = self.reader.inventory()
        self.check()
        generation = new_id('idx')
        directory = ensure_directory(self.catalog.root, 'derived/'+self.reference.build_id+'/'+generation)
        checkpoint('index_started')
        # 全文侧分别保存词干索引和大小写折叠的三元索引，后者另保留原文以映射字符位置。
        connection = sqlite3.connect(directory/'fts.sqlite')
        if self.limit is not None:
            connection.set_progress_handler(lambda:int(self.limit.stopped()),1000)
        try:
            connection.execute("CREATE VIRTUAL TABLE terms USING fts5(id UNINDEXED, body, tokenize='porter unicode61')")
            connection.execute("CREATE VIRTUAL TABLE grams USING fts5(id UNINDEXED, body, source UNINDEXED, tokenize='trigram')")
            values = [(b['id'], b['text']) for b in inventory['blocks']]
            connection.executemany('INSERT INTO terms VALUES (?,?)', values)
            connection.executemany('INSERT INTO grams VALUES (?,?,?)',[(identity,body.casefold(),body) for identity,body in values])
            connection.commit()
            assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        except sqlite3.Error:
            self.check()
            raise
        finally:
            connection.close()
        checkpoint('index_fts_written')
        with sql_connection(directory/'records.duckdb', readonly=False,limit=self.limit) as db:
            db.execute('CREATE TABLE blocks (id VARCHAR PRIMARY KEY, body VARCHAR)')
            if values:
                db.executemany('INSERT INTO blocks VALUES (?,?)', values)
            # 记录侧把期间、维度和单位存为规范 JSON 字符串，实现精确结构匹配而非模糊语义匹配。
            db.execute('''CREATE TABLE records (id VARCHAR PRIMARY KEY, concept VARCHAR, status VARCHAR,
                period VARCHAR, period_end VARCHAR, dimensions VARCHAR, unit VARCHAR, payload VARCHAR)''')
            rows = []
            for record in inventory['records']:
                self.check()
                period = record['period']
                rows.append((record['id'], concept_id(record), record['status'], canonical(period).decode(),
                    period.get('end', period.get('instant', '')), canonical(dimensions(record)).decode(),
                    canonical(record['unit']).decode(), canonical(record).decode()))
            if rows:
                db.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?)', rows)
            db.execute('CHECKPOINT')
        checkpoint('index_records_written')
        # 先刷盘索引文件及目录，再把摘要清单写入内容存储；head 是最终可见版本入口。
        files = {}
        for name in sorted(FILES):
            raw = read_regular(directory/name)
            with (directory/name).open('rb') as stream:
                os.fsync(stream.fileno())
            files[name] = dict(sha256=digest(raw), bytes=len(raw))
        _fsync_directory(directory)
        _fsync_directory(self.base)
        manifest = dict(schema_version=INDEX_VERSION, asset_ref=self.reference.model_dump(mode='json'),
            generation=generation, source_manifest_sha256=source_hash, files=files,
            blocks=len(values), records=len(rows), created_at=utc_now())
        reference = self.catalog.content.put_object(canonical(manifest))
        # 发布前记录意图，使 head 切换附近发生中断时能确认同一代次，而不是盲目重建。
        on_prepare(dict(asset_ref=self.reference.model_dump(mode='json'),generation=generation,manifest=reference.model_dump(mode='json')))
        checkpoint('index_intent_prepared')
        checkpoint('index_before_head')
        self.check()
        try:
            write_control(self.base/'head.json', canonical(dict(generation=generation, manifest=reference.model_dump(mode='json'))), replace=True)
        # head 写入报错时可能已发生可见切换，记录 uncertain 留给恢复流程判断，不能声称未生效。
        except OSError:
            on_effect(kind='index_head',status='uncertain',asset_ref=self.reference.model_dump(mode='json'),generation=generation)
            raise
        on_effect(kind='index_head',status='committed',asset_ref=self.reference.model_dump(mode='json'),generation=generation)
        checkpoint('index_after_head')
        return manifest

    # 根据匹配方式在已验证索引中选出块 ID，可同时返回原文字符范围及索引版本。
    def text_candidates(self, request, *, with_ranges=False):
        directory, manifest, token = self.current()
        text = request.value
        if request.match == 'regex':
            try:
                with sql_connection(directory/'records.duckdb',limit=self.limit) as db:
                    # 用不透明标记替换首个 RE2 命中，从替换前后长度求原文范围；不执行调用方 Python 正则。
                    marker = '__'+new_id('match')+'__'
                    flag = 'c' if request.case_sensitive else 'i'
                    rows = db.execute('SELECT id, body, regexp_replace(body, ?, ?, ?) FROM blocks WHERE regexp_matches(body, ?, ?) ORDER BY id',
                        [text,marker,flag,text,flag]).fetchall()
            except duckdb.Error as error:
                raise CatalogError('INVALID_REQUEST', 'invalid or unsupported RE2 expression') from error
            if with_ranges:
                ranges = {}
                for identity,body,marked in rows:
                    if marker in body or marker not in marked:
                        raise CatalogError('INDEX_INVALID','regex match range could not be mapped to source')
                    start = marked.index(marker)
                    ranges[identity] = (start,start+len(body)-len(marked)+len(marker))
                return [r[0] for r in rows], token, ranges
            return [r[0] for r in rows], token
        terms = text.split()
        if not terms:
            raise CatalogError('INVALID_REQUEST', 'empty search terms')
        # Quoted literals never expose FTS's boolean/column query language.
        # 用户词项始终作为引用后的字面值进入 FTS，不向用户开放 FTS 的布尔/列选择语法。
        quote = lambda s: '"'+s.replace('"', '""')+'"'
        if request.match == 'phrase':
            query = quote(text.casefold())
            table = 'grams'
        else:
            query = (' AND ' if request.match == 'all_terms' else ' OR ').join(map(quote, terms))
            table = 'terms'
        db = sqlite3.connect((directory/'fts.sqlite').as_uri()+'?mode=ro&immutable=1', uri=True)
        if self.limit is not None:
            db.set_progress_handler(lambda:int(self.limit.stopped()),1000)
        ranges = {}
        try:
            # 短语少于三个字符时无法依靠 trigram 索引，先扫描块文本，再执行同样的字面匹配。
            if request.match == 'phrase' and len(text) < 3:
                rows = db.execute('SELECT id, body FROM terms ORDER BY id').fetchall()
            else:
                column = 'source' if table=='grams' else 'body'
                rows = db.execute('SELECT id, '+column+' FROM '+table+' WHERE '+table+' MATCH ? ORDER BY id', (query,)).fetchall()
            if with_ranges and request.match != 'phrase':
                before,after = '__'+new_id('start')+'__','__'+new_id('end')+'__'
                highlighted = db.execute("SELECT id, body, highlight(terms,1,?,?) FROM terms WHERE terms MATCH ? ORDER BY id",(before,after,query)).fetchall()
                for identity,body,marked in highlighted:
                    if before in body or after in body or before not in marked:
                        raise CatalogError('INDEX_INVALID','term match range could not be mapped to source')
                    start = marked.index(before)
                    end = marked.index(after,start+len(before))-len(before)
                    ranges[identity] = (start,end)
        except sqlite3.Error:
            self.check()
            raise
        finally:
            db.close()
        self.check()
        # Phrase means a literal substring. FTS term matching uses the declared
        # unicode61/porter semantics; case-sensitive matching also checks source.
        # 索引只生成候选；短语最终必须满足字面子串条件，大小写敏感搜索也需回看原文。
        if request.match == 'phrase':
            target = text if request.case_sensitive else text.casefold()
            rows = [(i,b) for i,b in rows if target in (b if request.case_sensitive else b.casefold())]
        elif request.case_sensitive:
            check = all if request.match == 'all_terms' else any
            rows = [(i,b) for i,b in rows if check(t in b for t in terms)]
        if with_ranges:
            if request.match=='phrase' or request.case_sensitive:
                for identity,body in rows:
                    target_terms = [text] if request.match=='phrase' else terms
                    original = body if request.case_sensitive else body.casefold()
                    # casefold 可能把一个原字符展开成多个字符，显式保存索引映射，才能返回正确的原文字符范围。
                    origins = list(range(len(body))) if request.case_sensitive else [i for i,char in enumerate(body) for _ in char.casefold()]
                    matches = [(original.find(term if request.case_sensitive else term.casefold()),len(term if request.case_sensitive else term.casefold())) for term in target_terms]
                    lower,length = min((p,n) for p,n in matches if p>=0)
                    ranges[identity] = (origins[lower],origins[lower+length-1]+1)
            return [r[0] for r in rows],token,{identity:ranges[identity] for identity,_ in rows}
        return [r[0] for r in rows], token

    # 将明确的概念、期间、维度、单位等选择器编成参数化 SQL，返回原始记录与索引 token。
    def record_rows(self, *, concepts=(), filters=None, selector=None, order=None):
        identifiers=list(concepts)
        if selector is not None and selector.concept_id is not None:
            identifiers.append(selector.concept_id)
        if any(re.fullmatch(r'\{[^{}\s]+\}[^{}:\s]+',value) is None for value in identifiers):
            raise CatalogError('INVALID_REQUEST',
                'concept_id must be the exact expanded {namespace}local-name returned by '
                'get_asset_schema facets=["concepts"]. A prefix:local-name is not a stored identifier; '
                'do not infer that records are unavailable from this rejected query.')
        # 存在维度并不能证明“分部”，没有维度也不能证明“合并”，当前能力显式拒绝这一口径推断。
        if filters is not None and filters.entity_scope:
            raise CatalogError('CAPABILITY_UNSUPPORTED','dimension presence does not prove consolidated or segment scope')
        directory, _, token = self.current()
        clauses, params = [], []
        if concepts:
            clauses.append('concept IN ('+','.join('?' for _ in concepts)+')')
            params.extend(concepts)
        if selector is not None:
            for field, value in [('id', selector.record_id), ('concept', selector.concept_id)]:
                if value is not None:
                    clauses.append(field+'=?'); params.append(value)
            for field, value in [('period',selector.period), ('dimensions',selector.dimensions), ('unit',selector.unit)]:
                if value is not None:
                    clauses.append(field+'=?'); params.append(canonical(value).decode())
        if filters is not None:
            for field, values in [('period',filters.periods), ('unit',filters.units), ('status',filters.statuses)]:
                if values:
                    clauses.append(field+' IN ('+','.join('?' for _ in values)+')')
                    params.extend(v if field=='status' else canonical(v).decode() for v in values)
            if filters.dimensions is not None:
                clauses.append('dimensions=?'); params.append(canonical(filters.dimensions).decode())
        # 排序字段来自契约白名单，并以记录 ID 打破同分；用户提供的值全部通过参数绑定。
        field = {'record_id':'id', 'concept_id':'concept', 'period_end':'period_end'}[order.field] if order else 'id'
        direction = ' DESC' if order and order.direction=='desc' else ' ASC'
        query = 'SELECT payload FROM records'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY '+field+direction+', id ASC'
        with sql_connection(directory/'records.duckdb',limit=self.limit) as db:
            rows = db.execute(query, params).fetchall()
        records = [json.loads(r[0]) for r in rows]
        if (filters is not None and filters.dimensions is not None) or (selector is not None and selector.dimensions is not None):
            # A typed/unsupported dimension cannot be reduced to an empty set
            # of explicit members and then match an undimensioned selector.
            # 不能把 typed/不支持维度过滤掉后当作空维度命中，否则会将未知维度事实误当成无维度事实。
            records = [r for r in records if all(d['kind']=='explicit' for d in r['dimensions'])]
        return records, token
