-- =============================================================================
-- gAnji Mtaani Phase 6 PostgreSQL Schema
-- =============================================================================
-- This schema adds:
-- 1. forebet_match_analyses -> saved summaries from Forebet match detail pages
-- 2. forebet_match_history_rows -> structured historical rows around one match

CREATE TABLE IF NOT EXISTS forebet_match_analyses (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    sport TEXT NOT NULL,
    match_url TEXT NOT NULL,
    competition TEXT,
    league_code TEXT,
    event_datetime_text TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    pred_outcome TEXT,
    predicted_score_text TEXT,
    actual_score_text TEXT,
    actual_status TEXT,
    home_form_sequence TEXT,
    away_form_sequence TEXT,
    confidence DOUBLE PRECISION NOT NULL,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forebet_match_analyses UNIQUE (source_name, sport, match_url)
);

CREATE TABLE IF NOT EXISTS forebet_match_history_rows (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    sport TEXT NOT NULL,
    match_url TEXT NOT NULL,
    section_name TEXT NOT NULL,
    section_team TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    event_date_text TEXT,
    competition_tag TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    score_text TEXT,
    extra_score_text TEXT,
    result_outcome TEXT,
    result_class TEXT,
    active_side TEXT,
    detail_url TEXT,
    raw_text TEXT,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_forebet_match_history_rows UNIQUE (
        source_name,
        sport,
        match_url,
        section_name,
        section_team,
        sequence_no
    )
);

CREATE INDEX IF NOT EXISTS idx_forebet_match_analyses_sport ON forebet_match_analyses (sport);
CREATE INDEX IF NOT EXISTS idx_forebet_match_analyses_teams ON forebet_match_analyses (home_team, away_team);
CREATE INDEX IF NOT EXISTS idx_forebet_match_history_rows_lookup ON forebet_match_history_rows (sport, match_url, section_name);
