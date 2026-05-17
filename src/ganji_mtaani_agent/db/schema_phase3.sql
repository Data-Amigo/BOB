-- =============================================================================
-- gAnji Mtaani Phase 3 PostgreSQL Schema
-- =============================================================================
-- This schema adds daily ingestion orchestration support:
-- 1. ingestion_batches -> one logical daily ETL batch
-- 2. source_runs.batch_id -> links each source run to its batch

CREATE TABLE IF NOT EXISTS ingestion_batches (
    id BIGSERIAL PRIMARY KEY,
    batch_name TEXT NOT NULL,
    batch_date DATE NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    triggered_by TEXT,
    total_sources INTEGER NOT NULL DEFAULT 0,
    successful_sources INTEGER NOT NULL DEFAULT 0,
    failed_sources INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_batches_batch_date
    ON ingestion_batches (batch_date DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_batches_status
    ON ingestion_batches (status);

ALTER TABLE source_runs
    ADD COLUMN IF NOT EXISTS batch_id BIGINT REFERENCES ingestion_batches(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_source_runs_batch_id
    ON source_runs (batch_id);
