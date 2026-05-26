-- =============================================================================
-- gAnji Mtaani Phase 8 PostgreSQL Schema
-- =============================================================================
-- This schema adds the canonical fixture layer:
-- 1. canonical_fixtures    -> one standardized real-world match record
-- 2. fixture_source_links  -> links raw source rows back to that canonical match

CREATE TABLE IF NOT EXISTS canonical_fixtures (
    id BIGSERIAL PRIMARY KEY,
    sport TEXT NOT NULL,
    canonical_league TEXT,
    canonical_home_team TEXT NOT NULL,
    canonical_away_team TEXT NOT NULL,
    canonical_event_date DATE NOT NULL,
    canonical_event_datetime_utc TIMESTAMPTZ,
    canonical_event_datetime_text TEXT,
    canonical_status TEXT,
    result_home_score INTEGER,
    result_away_score INTEGER,
    primary_result_source TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_canonical_fixtures_identity
        UNIQUE (sport, canonical_event_date, canonical_home_team, canonical_away_team)
);

CREATE INDEX IF NOT EXISTS idx_canonical_fixtures_sport_date
    ON canonical_fixtures (sport, canonical_event_date DESC);

CREATE INDEX IF NOT EXISTS idx_canonical_fixtures_teams
    ON canonical_fixtures (canonical_home_team, canonical_away_team);

CREATE TABLE IF NOT EXISTS fixture_source_links (
    id BIGSERIAL PRIMARY KEY,
    fixture_id BIGINT NOT NULL REFERENCES canonical_fixtures(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_row_id BIGINT NOT NULL,
    source_run_id BIGINT REFERENCES source_runs(id) ON DELETE SET NULL,
    source_match_url TEXT,
    source_sport TEXT NOT NULL,
    source_league TEXT,
    source_home_team TEXT NOT NULL,
    source_away_team TEXT NOT NULL,
    source_event_date DATE,
    source_event_datetime_text TEXT,
    link_method TEXT NOT NULL,
    link_confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fixture_source_links_source_row
        UNIQUE (source_table, source_row_id)
);

CREATE INDEX IF NOT EXISTS idx_fixture_source_links_fixture_id
    ON fixture_source_links (fixture_id);

CREATE INDEX IF NOT EXISTS idx_fixture_source_links_source
    ON fixture_source_links (source_name, source_table);
