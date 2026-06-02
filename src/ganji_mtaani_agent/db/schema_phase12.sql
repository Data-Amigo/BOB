-- =============================================================================
-- gAnji Mtaani Phase 12 PostgreSQL Schema
-- =============================================================================
-- This schema extends the informative history layer with explicit prior
-- win/draw/loss counts and percentages for the home and away teams.

ALTER TABLE fixture_model_features
    ADD COLUMN IF NOT EXISTS home_prev_matches INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS home_prev_wins INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS home_prev_draws INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS home_prev_losses INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS home_prev_win_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS home_prev_draw_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS home_prev_loss_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_matches INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_wins INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_draws INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_losses INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_win_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_draw_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS away_prev_loss_pct DOUBLE PRECISION NOT NULL DEFAULT 0;
