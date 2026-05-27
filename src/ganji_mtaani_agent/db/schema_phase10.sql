-- =============================================================================
-- gAnji Mtaani Phase 10 PostgreSQL Schema
-- =============================================================================
-- Unified evaluation layer built on sport + normalized teams + event_date.

CREATE TABLE IF NOT EXISTS fixture_evaluations (
    id BIGSERIAL PRIMARY KEY,
    canonical_fixture_id BIGINT NULL REFERENCES canonical_fixtures(id) ON DELETE SET NULL,
    sport TEXT NOT NULL,
    event_date DATE NOT NULL,
    normalized_home_team TEXT NOT NULL,
    normalized_away_team TEXT NOT NULL,
    display_home_team TEXT,
    display_away_team TEXT,
    display_league TEXT,
    prediction_source TEXT,
    prediction_row_id BIGINT,
    prediction_match_url TEXT,
    pred_outcome TEXT,
    pred_probability DOUBLE PRECISION,
    predicted_home_score INTEGER,
    predicted_away_score INTEGER,
    result_source_used TEXT,
    result_row_id BIGINT,
    actual_home_score INTEGER,
    actual_away_score INTEGER,
    actual_outcome TEXT,
    pred_hit BOOLEAN,
    bookmaker_row_count INTEGER NOT NULL DEFAULT 0,
    bookmaker_sources_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    available_sources_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    evaluation_status TEXT NOT NULL,
    evaluation_confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sport, event_date, normalized_home_team, normalized_away_team)
);

CREATE INDEX IF NOT EXISTS idx_fixture_evaluations_sport_date
    ON fixture_evaluations (sport, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_fixture_evaluations_sources
    ON fixture_evaluations USING GIN (available_sources_json);
