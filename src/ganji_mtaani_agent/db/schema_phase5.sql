-- =============================================================================
-- gAnji Mtaani Phase 5 PostgreSQL Schema
-- =============================================================================
-- This schema adds:
-- 1. flashscore_results -> finished-match result rows from Flashscore date-aware boards

CREATE TABLE IF NOT EXISTS flashscore_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES source_runs(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    sport TEXT NOT NULL,
    page_date_text TEXT,
    country_or_region TEXT,
    league TEXT NOT NULL,
    match_status TEXT NOT NULL,
    event_time_text TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    raw_text TEXT,
    confidence DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_flashscore_results_fixture UNIQUE (
        source_name,
        sport,
        page_date_text,
        league,
        home_team,
        away_team,
        event_time_text
    )
);

CREATE INDEX IF NOT EXISTS idx_flashscore_results_run_id ON flashscore_results (run_id);
CREATE INDEX IF NOT EXISTS idx_flashscore_results_sport ON flashscore_results (sport);
CREATE INDEX IF NOT EXISTS idx_flashscore_results_league ON flashscore_results (league);
CREATE INDEX IF NOT EXISTS idx_flashscore_results_teams ON flashscore_results (home_team, away_team);
