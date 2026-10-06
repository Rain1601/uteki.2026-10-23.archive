
CREATE TABLE observations (
    record_id VARCHAR PRIMARY KEY, entity_id VARCHAR NOT NULL, metric_id VARCHAR NOT NULL,
    period_kind VARCHAR, period_start DATE, period_end DATE, value_kind VARCHAR NOT NULL,
    value_decimal DECIMAL(38,12), upper_decimal DECIMAL(38,12), value_relation VARCHAR NOT NULL,
    unit VARCHAR, accounting_basis VARCHAR NOT NULL, available_at DATE NOT NULL,
    source_snapshot_id VARCHAR NOT NULL, status VARCHAR NOT NULL, payload JSON NOT NULL
);
CREATE TABLE sources (source_snapshot_id VARCHAR PRIMARY KEY, company_id VARCHAR, form VARCHAR,
    period_end DATE, available_at DATE, payload JSON);
CREATE TABLE evidence (evidence_id VARCHAR PRIMARY KEY, source_snapshot_id VARCHAR, payload JSON);
CREATE TABLE metric_definitions (metric_id VARCHAR PRIMARY KEY, payload JSON);
