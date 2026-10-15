CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE catalog_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1), catalog_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>=0), token TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE catalog_commits (
    revision INTEGER PRIMARY KEY CHECK(revision>=0), token TEXT NOT NULL UNIQUE,
    parent_token TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
    parent_run_id TEXT REFERENCES runs(run_id),
    root_run_id TEXT NOT NULL REFERENCES runs(run_id), purpose TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('build','read')),
    status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
    failure_code TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status!='failed' OR failure_code IS NOT NULL)
);
CREATE TABLE registrations (
    namespace TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
    result_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(namespace,request_key)
);
CREATE TABLE policies (
    policy_ref TEXT PRIMARY KEY, payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE material_types (
    name TEXT PRIMARY KEY, payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE companies (
    company_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('confirmed','pending_identity')),
    identity_basis_kind TEXT, identity_basis_value TEXT, payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK((identity_basis_kind IS NULL)=(identity_basis_value IS NULL)),
    CHECK(status!='confirmed' OR identity_basis_value IS NOT NULL),
    UNIQUE(identity_basis_kind,identity_basis_value)
);
CREATE TABLE company_aliases (
    alias_id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(company_id),
    alias TEXT NOT NULL, alias_kind TEXT NOT NULL,
    valid_from TEXT, valid_to TEXT, payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_from<=valid_to)
);
CREATE TABLE company_securities (
    security_id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(company_id),
    ticker TEXT NOT NULL, exchange_mic TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
    status TEXT NOT NULL CHECK(status IN ('confirmed','pending')), payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_from<=valid_to),
    UNIQUE(exchange_mic,ticker,valid_from)
);
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY, publisher_company_id TEXT REFERENCES companies(company_id),
    policy_ref TEXT NOT NULL REFERENCES policies(policy_ref), payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE assets (
    asset_id TEXT PRIMARY KEY, material_type TEXT NOT NULL REFERENCES material_types(name),
    asset_kind TEXT NOT NULL CHECK(asset_kind IN ('document','dataset')),
    title TEXT NOT NULL, natural_key TEXT UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('registered','has_snapshot','retired')),
    payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE asset_relations (
    from_asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    to_asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    kind TEXT NOT NULL CHECK(kind IN ('amends','same_material_other_form','supplements')),
    payload TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(from_asset_id!=to_asset_id), PRIMARY KEY(from_asset_id,to_asset_id,kind)
);
CREATE TABLE asset_snapshots (
    snapshot_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id), run_id TEXT NOT NULL REFERENCES runs(run_id),
    status TEXT NOT NULL CHECK(status IN ('collecting','frozen','failed')),
    revision_of_snapshot_id TEXT REFERENCES asset_snapshots(snapshot_id),
    payload TEXT NOT NULL, manifest_ref TEXT, failure_code TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status!='frozen' OR manifest_ref IS NOT NULL),
    CHECK(status!='failed' OR failure_code IS NOT NULL), UNIQUE(snapshot_id,asset_id)
);
CREATE TABLE snapshot_representations (
    representation_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES asset_snapshots(snapshot_id),
    format TEXT NOT NULL CHECK(format IN ('pdf','html','xbrl_instance','api_json')),
    input_ref TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(representation_id,snapshot_id)
);
CREATE TABLE source_records (
    record_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id),
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    snapshot_id TEXT NOT NULL UNIQUE REFERENCES asset_snapshots(snapshot_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id), acquired_at TEXT NOT NULL,
    published_at_value TEXT, published_at_precision TEXT, published_at_lower_utc TEXT, published_at_upper_utc TEXT,
    available_at_value TEXT, available_at_precision TEXT, available_at_lower_utc TEXT, available_at_upper_utc TEXT,
    source_revised_at_value TEXT, source_revised_at_precision TEXT, source_revised_at_lower_utc TEXT, source_revised_at_upper_utc TEXT,
    payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE snapshot_company_relations (
    snapshot_id TEXT NOT NULL REFERENCES asset_snapshots(snapshot_id),
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    role TEXT NOT NULL CHECK(role IN ('issuer','subject','mentioned')),
    payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id,company_id,role)
);
CREATE TABLE asset_builds (
    build_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL, representation_id TEXT NOT NULL,
    input_ref TEXT NOT NULL, recipe TEXT NOT NULL, build_key TEXT NOT NULL,
    job_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL REFERENCES runs(run_id),
    retry_of_build_id TEXT REFERENCES asset_builds(build_id),
    status TEXT NOT NULL CHECK(status IN ('staging','published','failed')),
    manifest_ref TEXT, readiness_json TEXT, failure_code TEXT, published_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id,asset_id) REFERENCES asset_snapshots(snapshot_id,asset_id),
    FOREIGN KEY(representation_id,snapshot_id) REFERENCES snapshot_representations(representation_id,snapshot_id),
    CHECK(status!='published' OR (manifest_ref IS NOT NULL AND readiness_json IS NOT NULL AND published_at IS NOT NULL)),
    CHECK(status!='failed' OR failure_code IS NOT NULL)
);
CREATE UNIQUE INDEX active_build_key ON asset_builds(build_key) WHERE status IN ('staging','published');
CREATE TABLE metadata_revisions (
    revision_id TEXT PRIMARY KEY, object_type TEXT NOT NULL CHECK(object_type IN ('company','asset')),
    object_id TEXT NOT NULL, field TEXT NOT NULL, value_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('current','superseded','candidate','conflict','rejected')),
    reason TEXT NOT NULL, evidence_json TEXT NOT NULL,
    supersedes_revision_id TEXT REFERENCES metadata_revisions(revision_id),
    created_by_run_id TEXT NOT NULL REFERENCES runs(run_id),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX current_revision ON metadata_revisions(object_type,object_id,field) WHERE status='current';
PRAGMA user_version=1;
