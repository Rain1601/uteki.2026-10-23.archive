"""Publish immutable parser output once; read the SQL projection without parsing.

Objects precede the database transaction. A failed/interrupted publication may
leave unreferenced CAS objects, but never a partially queryable parse. Retrying
the same package ID is idempotent. No automatic deletion or source acquisition.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat

from ..content.store import ContentStore, _fsync_directory
from ..contracts.common import canonical, digest
from ..contracts.content import ObjectRef
from ..contracts.documents import DocumentPackage, SourceVersion
from .schema import SCHEMA
from .query import DocumentQueries, DocumentStoreError


class DocumentStore(DocumentQueries):
    """Explicit data root, immutable packages, one transactional query database.

    Initialize once; later callers use open(). Old catalog.sqlite and SDK runs
    are neither opened nor modified. Public ingestion accepts DocumentPackage.
    """

    def __init__(self, data_root, *, initialize=False):
        self.content = ContentStore(data_root)
        self.root = self.content.data_root
        self.path = self.root / 'documents.sqlite'
        for path in (self.path, Path(str(self.path)+'-journal'), Path(str(self.path)+'-wal'), Path(str(self.path)+'-shm')):
            if path.exists() or path.is_symlink():
                if not stat.S_ISREG(path.lstat().st_mode):
                    raise DocumentStoreError('UNSAFE_PATH', 'database files must be regular files')
        if initialize:
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                raise DocumentStoreError('ALREADY_EXISTS', 'open the existing store instead') from None
            os.close(fd)
        elif not self.path.is_file():
            raise DocumentStoreError('STORE_MISSING', 'explicit initialization is required')
        self._db = sqlite3.connect(self.path.as_uri()+'?mode=rw', uri=True, timeout=5, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute('PRAGMA foreign_keys=ON')
            self._db.execute('PRAGMA synchronous=FULL')
            if initialize:
                self._db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')
                _fsync_directory(self.root)
            if self._db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise DocumentStoreError('UNSUPPORTED_SCHEMA', 'unrecognized document store version')
            if self._db.execute('SELECT count(*) FROM store_meta').fetchone()[0] != 1:
                raise DocumentStoreError('STORE_CORRUPT', 'store metadata missing')
        except BaseException:
            self._db.close()
            raise

    @classmethod
    def initialize(cls, data_root):
        return cls(data_root, initialize=True)

    @classmethod
    def open(cls, data_root):
        return cls(data_root)

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def _transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise

    def _immutable_row(self, table, key, identity, payload, columns):
        # table/key/columns come only from this module, never caller input.
        old = self._db.execute(f'SELECT payload FROM {table} WHERE {key}=?', (identity,)).fetchone()
        if old:
            if old['payload'] != payload:
                raise DocumentStoreError('IDENTITY_CONFLICT', table+' identity already has different content')
            return
        data = {key: identity, **columns, 'payload': payload}
        names = ','.join(data)
        self._db.execute(f'INSERT INTO {table} ({names}) VALUES ({",".join("?" for _ in data)})', tuple(data.values()))

    def _register(self, package):
        m, source, parse = package.material, package.source, package.parse
        bounds = m.published_at.value.bounds() if m.published_at.value else (None, None)
        self._immutable_row('materials', 'material_id', m.material_id, m.canonical_bytes().decode(),
            dict(name=m.name, material_type=m.material_type, published_lower=bounds[0], published_upper=bounds[1],
                 report_label=m.reporting_period.label if m.reporting_period else None))
        for e in m.related_entities:
            self._db.execute('INSERT OR IGNORE INTO material_entities VALUES (?,?,?)', (m.material_id,e.entity_id,e.role))
        if source.revision_of:
            old = self._db.execute('SELECT material_id FROM sources WHERE source_version_id=?', (source.revision_of,)).fetchone()
            if old is None or old['material_id'] != m.material_id:
                raise DocumentStoreError('INVALID_REFERENCE', 'revised source must exist in the same material')
        self._immutable_row('sources', 'source_version_id', source.source_version_id, source.canonical_bytes().decode(),
                            dict(material_id=m.material_id))
        if parse.taxonomy:
            taxonomy = parse.taxonomy
            payload = taxonomy.canonical_bytes().decode()
            old = self._db.execute('SELECT payload FROM taxonomies WHERE taxonomy_id=? AND version=?',
                                   (taxonomy.taxonomy_id,taxonomy.version)).fetchone()
            if old and old['payload'] != payload:
                raise DocumentStoreError('IDENTITY_CONFLICT', 'taxonomy version already has different definitions')
            self._db.execute('INSERT OR IGNORE INTO taxonomies VALUES (?,?,?)', (taxonomy.taxonomy_id,taxonomy.version,payload))

    def _write_projection(self, package, checkpoint):
        parse_id = package.parse.parse_id
        for node in package.parse.directory_schema.nodes:
            self._db.execute('INSERT INTO directory_nodes VALUES (?,?,?,?,?,?)',
                (parse_id,node.node_id,node.parent_id,node.title,node.order,node.canonical_bytes().decode()))
        for block in package.blocks:
            payload = block.canonical_bytes()
            self._db.execute('INSERT INTO blocks VALUES (?,?,?,?,?,?,?)',
                (parse_id,block.block_id,block.order,block.type,block.status,payload.decode(),digest(payload)))
            for node_id in block.directory_node_ids:
                self._db.execute('INSERT INTO directory_blocks VALUES (?,?,?)', (parse_id,node_id,block.block_id))
            for tag in block.tagging.tag_ids:
                self._db.execute('INSERT INTO block_tags VALUES (?,?,?)', (parse_id,tag,block.block_id))
            for relation in block.related_blocks:
                self._db.execute('INSERT INTO block_relations VALUES (?,?,?,?)',
                    (parse_id,block.block_id,relation.block_id,relation.relation))
            source_text = block.text if block.text is not None else '\n'.join(c.text for c in block.table.cells) if block.table else ''
            texts={block.text_origin:source_text}
            if block.ocr.text:
                texts['ocr']='\n'.join(dict.fromkeys(filter(None,(texts.get('ocr'),block.ocr.text))))
            texts['description']=block.description.text
            for origin, body in texts.items():
                if not body:
                    continue
                row = self._db.execute('INSERT INTO block_text(parse_id,block_id,origin,body,folded) VALUES (?,?,?,?,?)',
                    (parse_id,block.block_id,origin,body,body.casefold()))
                self._db.execute('INSERT INTO text_terms(rowid,body) VALUES (?,?)', (row.lastrowid,body))
                self._db.execute('INSERT INTO text_trigrams(rowid,body) VALUES (?,?)', (row.lastrowid,body.casefold()))
            checkpoint('block_written')

    def publish(self, package: DocumentPackage, *, make_default=True, checkpoint=lambda phase: None):
        package = DocumentPackage.model_validate(package)
        if type(make_default) is not bool:
            raise DocumentStoreError('INVALID_ARGUMENT', 'make_default must be boolean')
        # Verify actual original/resource bytes once at ingestion, not on navigation.
        self.content.read_object(package.source.object_ref)
        if package.parse.parser_output_ref is not None:
            self.content.read_object(package.parse.parser_output_ref)
        for block in package.blocks:
            for resource in block.resources:
                self.content.read_object(resource.object_ref)
        package_ref = self.content.put_object(package.canonical_bytes())
        checkpoint('package_stored')
        parse = package.parse
        with self._transaction():
            old = self._db.execute('SELECT package_ref FROM parses WHERE parse_id=?', (parse.parse_id,)).fetchone()
            if old:
                if ObjectRef.model_validate_json(old['package_ref']) != package_ref:
                    raise DocumentStoreError('IDENTITY_CONFLICT', 'parse ID already has different output')
                # Exact replay does not unexpectedly change the current default.
                return dict(material_id=parse.material_id,parse_id=parse.parse_id,package_ref=package_ref.model_dump(mode='json'),reused=True)
            self._register(package)
            self._db.execute('INSERT INTO parses VALUES (?,?,?,?,?,?,?)',
                (parse.parse_id,parse.material_id,parse.source_version_id,parse.status,parse.completed_at.isoformat(),
                 package_ref.model_dump_json(),parse.canonical_bytes().decode()))
            self._write_projection(package, checkpoint)
            checkpoint('projection_written')
            if make_default:
                self._db.execute('INSERT INTO defaults VALUES (?,?) ON CONFLICT(material_id) DO UPDATE SET parse_id=excluded.parse_id',
                    (parse.material_id,parse.parse_id))
            self._db.execute('UPDATE store_meta SET revision=revision+1')
            checkpoint('before_commit')
        # If this callback/process fails, the caller must inspect or replay the
        # SAME parse ID. No second version is invented to hide an uncertain result.
        checkpoint('after_commit')
        return dict(material_id=parse.material_id,parse_id=parse.parse_id,package_ref=package_ref.model_dump(mode='json'),reused=False)

    def export_package(self, parse_id):
        row = self._parse_row(parse_id)
        raw = self.content.read_object(ObjectRef.model_validate_json(row['package_ref']))
        package = DocumentPackage.model_validate_json(raw)
        if package.parse.parse_id != parse_id or package.parse.material_id != row['material_id']:
            raise DocumentStoreError('STORE_CORRUPT', 'package identity differs from catalog')
        return package

    def get_source_version(self, source_version_id):
        row = self._db.execute('SELECT payload FROM sources WHERE source_version_id=?', (source_version_id,)).fetchone()
        if row is None:
            raise DocumentStoreError('NOT_FOUND', 'source version does not exist')
        return SourceVersion.model_validate_json(row['payload'])

    def reindex(self, parse_id, *, checkpoint=lambda phase: None):
        """Explicitly recreate this parse's query projection from its frozen package."""
        package = self.export_package(parse_id)
        with self._transaction():
            ids = [r[0] for r in self._db.execute('SELECT id FROM block_text WHERE parse_id=?',(parse_id,))]
            for identity in ids:
                self._db.execute('DELETE FROM text_terms WHERE rowid=?',(identity,))
                self._db.execute('DELETE FROM text_trigrams WHERE rowid=?',(identity,))
            self._db.execute('DELETE FROM block_relations WHERE parse_id=?',(parse_id,))
            self._db.execute('DELETE FROM blocks WHERE parse_id=?',(parse_id,))
            self._db.execute('DELETE FROM directory_nodes WHERE parse_id=?',(parse_id,))
            self._write_projection(package, checkpoint)
            checkpoint('before_commit')
        return dict(parse_id=parse_id,status='rebuilt',blocks=len(package.blocks))

    def read_source(self, parse_id):
        row = self._parse_row(parse_id)
        source = self._db.execute('SELECT payload FROM sources WHERE source_version_id=?',(row['source_version_id'],)).fetchone()
        return self.content.read_object(ObjectRef.model_validate(json.loads(source['payload'])['object_ref']))

    def read_resource(self, reference, resource_id):
        block = self._block(reference)
        for resource in block['resources']:
            if resource['resource_id'] == resource_id:
                return self.content.read_object(ObjectRef.model_validate(resource['object_ref']))
        raise DocumentStoreError('NOT_FOUND', 'resource not registered on this block')
