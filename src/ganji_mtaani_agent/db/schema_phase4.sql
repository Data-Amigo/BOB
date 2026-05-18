-- =============================================================================
-- gAnji Mtaani Phase 4 PostgreSQL Schema
-- =============================================================================
-- This schema adds:
-- 1. forebet_results -> finished-match result rows from Forebet yesterday pages

CREATE TABLE IF NOT EXISTS forebet_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES source_runs(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    sport TEXT NOT NULL,
    league TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    event_datetime_text TEXT,
    prob_1 INTEGER,
    prob_x INTEGER,
    prob_2 INTEGER,
    pred_outcome TEXT,
    predicted_home_score INTEGER,
    predicted_away_score INTEGER,
    predicted_score_text TEXT,
    actual_home_score INTEGER,
    actual_away_score INTEGER,
    actual_score_text TEXT,
    actual_outcome TEXT,
    status TEXT,
    pred_hit BOOLEAN,
    pred_indicator_class TEXT,
    raw_text TEXT,
    confidence DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forebet_results_fixture UNIQUE (source_name, sport, event_datetime_text, home_team, away_team)
);

CREATE INDEX IF NOT EXISTS idx_forebet_results_run_id ON forebet_results (run_id);
CREATE INDEX IF NOT EXISTS idx_forebet_results_sport ON forebet_results (sport);
CREATE INDEX IF NOT EXISTS idx_forebet_results_league ON forebet_results (league);
CREATE INDEX IF NOT EXISTS idx_forebet_results_teams ON forebet_results (home_team, away_team);
