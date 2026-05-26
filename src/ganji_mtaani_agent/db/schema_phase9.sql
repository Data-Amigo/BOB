-- =============================================================================
-- gAnji Mtaani Phase 9 PostgreSQL Schema
-- =============================================================================
-- This schema separates date and time components inside the canonical layer.

ALTER TABLE canonical_fixtures
    ADD COLUMN IF NOT EXISTS canonical_event_time_text TEXT;

ALTER TABLE fixture_source_links
    ADD COLUMN IF NOT EXISTS source_event_time_text TEXT;
