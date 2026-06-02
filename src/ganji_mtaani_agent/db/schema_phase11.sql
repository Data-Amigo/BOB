-- =============================================================================
-- gAnji Mtaani Phase 11 PostgreSQL Schema
-- =============================================================================
-- This schema adds a transparent fixture-level feature layer for the first
-- historical-form model pass.

CREATE TABLE IF NOT EXISTS fixture_model_features (
    id BIGSERIAL PRIMARY KEY,
    evaluation_id BIGINT NOT NULL UNIQUE REFERENCES fixture_evaluations (id) ON DELETE CASCADE,
    canonical_fixture_id BIGINT REFERENCES canonical_fixtures (id) ON DELETE SET NULL,
    sport TEXT NOT NULL,
    event_date DATE NOT NULL,
    normalized_home_team TEXT NOT NULL,
    normalized_away_team TEXT NOT NULL,
    display_home_team TEXT,
    display_away_team TEXT,
    display_league TEXT,
    prediction_source TEXT,
    prediction_match_url TEXT,
    pred_outcome TEXT,
    pred_probability DOUBLE PRECISION,
    actual_outcome TEXT,
    pred_hit BOOLEAN,
    home_overall_matches_used INTEGER NOT NULL DEFAULT 0,
    away_overall_matches_used INTEGER NOT NULL DEFAULT 0,
    home_home_matches_used INTEGER NOT NULL DEFAULT 0,
    away_away_matches_used INTEGER NOT NULL DEFAULT 0,
    home_overall_points_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    away_overall_points_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    home_home_points_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    away_away_points_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    home_overall_form_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    away_overall_form_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    home_home_form_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    away_away_form_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    overall_form_edge_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    venue_form_edge_5 DOUBLE PRECISION NOT NULL DEFAULT 0,
    predicted_side_form_5 DOUBLE PRECISION,
    opponent_side_form_5 DOUBLE PRECISION,
    model_confidence_v1 DOUBLE PRECISION,
    history_coverage_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fixture_model_features_sport_date
    ON fixture_model_features (sport, event_date DESC);

CREATE INDEX IF NOT EXISTS idx_fixture_model_features_matchup
    ON fixture_model_features (normalized_home_team, normalized_away_team, event_date DESC);
