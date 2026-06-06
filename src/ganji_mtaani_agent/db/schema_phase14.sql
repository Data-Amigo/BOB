-- =============================================================================
-- gAnji Mtaani Phase 14 PostgreSQL Schema
-- =============================================================================
-- Adds per-user daily stake preference to bot_user_preferences so the
-- Mini App can save and restore each user's stake setting.

ALTER TABLE bot_user_preferences
    ADD COLUMN IF NOT EXISTS stake_kes DOUBLE PRECISION;
