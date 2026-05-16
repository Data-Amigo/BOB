-- =============================================================================
-- gAnji Mtaani Phase 2 PostgreSQL Schema
-- =============================================================================
-- This schema extends phase 1 with:
-- 1. forebet_predictions  -> structured football and basketball prediction rows
-- 2. polymarket_markets   -> structured Polymarket market rows

CREATE TABLE IF NOT EXISTS forebet_predictions (
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
    correct_score_text TEXT,
    avg_goals DOUBLE PRECISION,
    avg_points DOUBLE PRECISION,
    weather TEXT,
    coef_1 DOUBLE PRECISION,
    coef_x DOUBLE PRECISION,
    coef_2 DOUBLE PRECISION,
    coef_3 DOUBLE PRECISION,
    coef_extra DOUBLE PRECISION,
    remaining_tokens_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_text TEXT,
    confidence DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forebet_predictions_run_id ON forebet_predictions (run_id);
CREATE INDEX IF NOT EXISTS idx_forebet_predictions_sport ON forebet_predictions (sport);
CREATE INDEX IF NOT EXISTS idx_forebet_predictions_league ON forebet_predictions (league);
CREATE INDEX IF NOT EXISTS idx_forebet_predictions_teams ON forebet_predictions (home_team, away_team);

CREATE TABLE IF NOT EXISTS polymarket_markets (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES source_runs(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    market_id TEXT NOT NULL,
    event_id TEXT,
    question TEXT NOT NULL,
    slug TEXT,
    category TEXT,
    subcategory TEXT,
    tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    closed BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    outcomes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome_prices_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    liquidity DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    open_interest DOUBLE PRECISION,
    market_type TEXT,
    raw_record_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_polymarket_markets_source_market UNIQUE (source_name, market_id)
);

CREATE INDEX IF NOT EXISTS idx_polymarket_markets_run_id ON polymarket_markets (run_id);
CREATE INDEX IF NOT EXISTS idx_polymarket_markets_event_id ON polymarket_markets (event_id);
CREATE INDEX IF NOT EXISTS idx_polymarket_markets_category ON polymarket_markets (category);
CREATE INDEX IF NOT EXISTS idx_polymarket_markets_active ON polymarket_markets (active);
