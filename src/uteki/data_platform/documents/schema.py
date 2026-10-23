"""Queryable projection of frozen document packages (SQLite schema version 1)."""

SCHEMA = """
CREATE TABLE store_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL);
INSERT INTO store_meta VALUES(1,0);
CREATE TABLE materials (
 material_id TEXT PRIMARY KEY, name TEXT NOT NULL, material_type TEXT NOT NULL,
 published_lower TEXT, published_upper TEXT, report_label TEXT, payload TEXT NOT NULL
);
CREATE INDEX material_filter ON materials(material_type,report_label,published_lower,published_upper);
CREATE TABLE material_entities (
 material_id TEXT NOT NULL REFERENCES materials, entity_id TEXT NOT NULL, role TEXT NOT NULL,
 PRIMARY KEY(material_id,entity_id,role)
);
CREATE INDEX entity_material ON material_entities(entity_id,role,material_id);
CREATE TABLE sources (
 source_version_id TEXT PRIMARY KEY, material_id TEXT NOT NULL REFERENCES materials,
 payload TEXT NOT NULL, UNIQUE(material_id,source_version_id)
);
CREATE TABLE taxonomies (
 taxonomy_id TEXT NOT NULL, version TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(taxonomy_id,version)
);
CREATE TABLE parses (
 parse_id TEXT PRIMARY KEY, material_id TEXT NOT NULL, source_version_id TEXT NOT NULL,
 status TEXT NOT NULL, completed_at TEXT NOT NULL,
 package_ref TEXT NOT NULL, payload TEXT NOT NULL,
 FOREIGN KEY(material_id,source_version_id) REFERENCES sources(material_id,source_version_id),
 UNIQUE(material_id,parse_id)
);
CREATE INDEX material_parses ON parses(material_id,completed_at,parse_id);
CREATE TABLE defaults (
 material_id TEXT PRIMARY KEY REFERENCES materials, parse_id TEXT NOT NULL,
 FOREIGN KEY(material_id,parse_id) REFERENCES parses(material_id,parse_id)
);
CREATE TABLE directory_nodes (
 parse_id TEXT NOT NULL REFERENCES parses, node_id TEXT NOT NULL, parent_id TEXT,
 title TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(parse_id,node_id),
 FOREIGN KEY(parse_id,parent_id) REFERENCES directory_nodes(parse_id,node_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX directory_children ON directory_nodes(parse_id,parent_id,ordinal,node_id);
CREATE INDEX directory_title ON directory_nodes(parse_id,parent_id,title);
CREATE TABLE blocks (
 parse_id TEXT NOT NULL REFERENCES parses, block_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
 type TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 PRIMARY KEY(parse_id,block_id), UNIQUE(parse_id,ordinal)
);
CREATE INDEX block_type ON blocks(parse_id,type,ordinal);
CREATE TABLE directory_blocks (
 parse_id TEXT NOT NULL, node_id TEXT NOT NULL, block_id TEXT NOT NULL,
 PRIMARY KEY(parse_id,node_id,block_id),
 FOREIGN KEY(parse_id,node_id) REFERENCES directory_nodes(parse_id,node_id) ON DELETE CASCADE,
 FOREIGN KEY(parse_id,block_id) REFERENCES blocks(parse_id,block_id) ON DELETE CASCADE
);
CREATE INDEX block_directory ON directory_blocks(parse_id,block_id,node_id);
CREATE TABLE block_tags (
 parse_id TEXT NOT NULL, tag_id TEXT NOT NULL, block_id TEXT NOT NULL,
 PRIMARY KEY(parse_id,tag_id,block_id),
 FOREIGN KEY(parse_id,block_id) REFERENCES blocks(parse_id,block_id) ON DELETE CASCADE
);
CREATE INDEX block_tag_refs ON block_tags(parse_id,block_id,tag_id);
CREATE TABLE block_relations (
 parse_id TEXT NOT NULL, block_id TEXT NOT NULL, target_id TEXT NOT NULL, relation TEXT NOT NULL,
 PRIMARY KEY(parse_id,block_id,target_id,relation),
 FOREIGN KEY(parse_id,block_id) REFERENCES blocks(parse_id,block_id) ON DELETE CASCADE,
 FOREIGN KEY(parse_id,target_id) REFERENCES blocks(parse_id,block_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE block_text (
 id INTEGER PRIMARY KEY, parse_id TEXT NOT NULL, block_id TEXT NOT NULL,
 origin TEXT NOT NULL, body TEXT NOT NULL, folded TEXT NOT NULL,
 UNIQUE(parse_id,block_id,origin),
 FOREIGN KEY(parse_id,block_id) REFERENCES blocks(parse_id,block_id) ON DELETE CASCADE
);
CREATE INDEX text_scope ON block_text(parse_id,origin,block_id);
CREATE VIRTUAL TABLE text_terms USING fts5(body,tokenize='unicode61');
CREATE VIRTUAL TABLE text_trigrams USING fts5(body,tokenize='trigram');
-- Read-only inspection views: no duplicate persisted data or application dependency.
CREATE VIEW inspect_materials AS
SELECT m.material_id, m.name, m.material_type, json_extract(m.payload,'$.published_at.value.value') AS published_at,
       m.report_label, d.parse_id, p.status, p.completed_at,
       json_extract(p.payload,'$.issues') AS issues
FROM materials m LEFT JOIN defaults d USING(material_id) LEFT JOIN parses p USING(parse_id);
CREATE VIEW inspect_directory AS
WITH RECURSIVE paths(parse_id,node_id,path) AS (
 SELECT parse_id,node_id,json_array(title) FROM directory_nodes WHERE parent_id IS NULL
 UNION ALL
 SELECT n.parse_id,n.node_id,json_insert(p.path,'$[#]',n.title)
 FROM directory_nodes n JOIN paths p ON n.parse_id=p.parse_id AND n.parent_id=p.node_id
)
SELECT m.material_id, m.name AS material_name,
       n.parse_id, n.node_id, n.parent_id, n.title, n.ordinal, p.path AS directory_path,
       json_extract(n.payload,'$.basis') AS basis,
       CAST(json_extract(n.payload,'$.locations[0].page_number') AS INTEGER) AS page,
       CAST(json_extract(n.payload,'$.locations[0].y') AS REAL) AS top_pt,
       (SELECT count(*) FROM directory_blocks b WHERE b.parse_id=n.parse_id AND b.node_id=n.node_id) AS blocks
FROM directory_nodes n JOIN paths p USING(parse_id,node_id)
JOIN parses v USING(parse_id) JOIN materials m ON m.material_id=v.material_id;
CREATE VIEW inspect_blocks AS
WITH RECURSIVE paths(parse_id,node_id,path) AS (
 SELECT parse_id,node_id,json_array(title) FROM directory_nodes WHERE parent_id IS NULL
 UNION ALL
 SELECT n.parse_id,n.node_id,json_insert(p.path,'$[#]',n.title)
 FROM directory_nodes n JOIN paths p ON n.parse_id=p.parse_id AND n.parent_id=p.node_id
)
SELECT m.material_id, m.name AS material_name,
       b.parse_id, b.block_id, b.ordinal, b.type,
       json_extract(b.payload,'$.role') AS role,
       CAST(json_extract(b.payload,'$.locations[0].page_number') AS INTEGER) AS page,
       json_extract(b.payload,'$.text_origin') AS text_origin,
       (SELECT json_group_array(json(p.path)) FROM paths p
        JOIN directory_blocks d ON p.parse_id=d.parse_id AND p.node_id=d.node_id
        WHERE d.parse_id=b.parse_id AND d.block_id=b.block_id) AS directory_paths,
       CASE WHEN b.type='table' THEN (
         SELECT group_concat(row_text,char(10)) FROM (
           SELECT 'row ' || row_index || ': ' || group_concat(cell_text,' | ') AS row_text
           FROM (
             SELECT CAST(json_extract(c.value,'$.row') AS INTEGER) AS row_index,
                    CAST(json_extract(c.value,'$.column') AS INTEGER) AS column_index,
                    json_extract(c.value,'$.text') AS cell_text
             FROM json_each(b.payload,'$.table.cells') c ORDER BY row_index,column_index
           ) GROUP BY row_index ORDER BY row_index
         )
       ) ELSE json_extract(b.payload,'$.text') END AS content_preview,
       CAST(json_extract(b.payload,'$.table.row_count') AS INTEGER) AS table_rows,
       CAST(json_extract(b.payload,'$.table.column_count') AS INTEGER) AS table_columns,
       json_extract(b.payload,'$.ocr.status') AS ocr_status,
       json_extract(b.payload,'$.description.status') AS description_status,
       json_extract(b.payload,'$.tagging.status') AS tagging_status,
       json_extract(b.payload,'$.directory_assignment') AS directory_assignment,
       json_extract(b.payload,'$.locations') AS locations
FROM blocks b JOIN parses v USING(parse_id) JOIN materials m ON m.material_id=v.material_id;
CREATE VIEW inspect_table_cells AS
SELECT m.material_id, m.name AS material_name, b.parse_id, b.block_id,
       CAST(json_extract(b.payload,'$.locations[0].page_number') AS INTEGER) AS page,
       CAST(json_extract(c.value,'$.row') AS INTEGER) AS row_index,
       CAST(json_extract(c.value,'$.column') AS INTEGER) AS column_index,
       CAST(json_extract(c.value,'$.row_span') AS INTEGER) AS row_span,
       CAST(json_extract(c.value,'$.column_span') AS INTEGER) AS column_span,
       json_extract(c.value,'$.text') AS text,
       CAST(json_extract(c.value,'$.is_header') AS INTEGER) AS is_header,
       json_extract(c.value,'$.locations') AS locations
FROM blocks b JOIN parses v USING(parse_id) JOIN materials m ON m.material_id=v.material_id,
     json_each(b.payload,'$.table.cells') c WHERE b.type='table';
PRAGMA user_version=1;
"""
