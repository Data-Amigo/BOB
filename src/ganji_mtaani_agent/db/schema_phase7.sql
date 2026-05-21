-- =============================================================================
-- gAnji Mtaani Phase 7 PostgreSQL Schema
-- =============================================================================
-- This schema extends Forebet modelling support by persisting the original
-- match-detail URL on prediction and result rows. That URL becomes the pointer
-- for automatic historical enrichment later.

ALTER TABLE forebet_predictions
    ADD COLUMN IF NOT EXISTS match_url TEXT;

CREATE INDEX IF NOT EXISTS idx_forebet_predictions_match_url
    ON forebet_predictions (match_url);

ALTER TABLE forebet_results
    ADD COLUMN IF NOT EXISTS match_url TEXT;

CREATE INDEX IF NOT EXISTS idx_forebet_results_match_url
    ON forebet_results (match_url);
