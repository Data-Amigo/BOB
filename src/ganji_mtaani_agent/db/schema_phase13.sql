-- =============================================================================
-- gAnji Mtaani Phase 13 PostgreSQL Schema
-- =============================================================================
-- Telegram prototype / conversational bot foundation.
-- This schema adds:
-- 1. bot_users              -> channel identity and contact details
-- 2. bot_user_consents      -> terms / data / marketing consent tracking
-- 3. bot_user_preferences   -> onboarding and personalization fields
-- 4. bot_conversations      -> inbound/outbound message audit trail
-- 5. bot_slips              -> generated slip headers
-- 6. bot_slip_legs          -> fixture-level legs stored under each slip

CREATE TABLE IF NOT EXISTS bot_users (
    id BIGSERIAL PRIMARY KEY,
    channel TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    chat_id TEXT,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    pseudo_name TEXT,
    phone_number TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ,
    CONSTRAINT uq_bot_users_channel_user UNIQUE (channel, channel_user_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_users_channel ON bot_users (channel);
CREATE INDEX IF NOT EXISTS idx_bot_users_username ON bot_users (username);

CREATE TABLE IF NOT EXISTS bot_user_consents (
    user_id BIGINT PRIMARY KEY REFERENCES bot_users(id) ON DELETE CASCADE,
    terms_accepted BOOLEAN NOT NULL DEFAULT FALSE,
    terms_accepted_at TIMESTAMPTZ,
    data_processing_consent BOOLEAN NOT NULL DEFAULT FALSE,
    data_processing_consent_at TIMESTAMPTZ,
    marketing_consent BOOLEAN NOT NULL DEFAULT FALSE,
    marketing_consent_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_user_preferences (
    user_id BIGINT PRIMARY KEY REFERENCES bot_users(id) ON DELETE CASCADE,
    preferred_name TEXT,
    preferred_sports_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    betting_frequency TEXT,
    service_mode TEXT,
    preferred_slip_size INTEGER,
    risk_profile TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES bot_users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    chat_id TEXT,
    message_direction TEXT NOT NULL,
    message_text TEXT,
    intent TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_conversations_user_id ON bot_conversations (user_id);
CREATE INDEX IF NOT EXISTS idx_bot_conversations_created_at ON bot_conversations (created_at DESC);

CREATE TABLE IF NOT EXISTS bot_slips (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES bot_users(id) ON DELETE SET NULL,
    channel TEXT NOT NULL,
    chat_id TEXT,
    sport TEXT NOT NULL,
    slip_size INTEGER NOT NULL,
    stake_kes DOUBLE PRECISION,
    bucket_labels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_logic TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    event_date DATE,
    total_combined_odds DOUBLE PRECISION,
    predicted_payout_kes DOUBLE PRECISION,
    actual_payout_kes DOUBLE PRECISION,
    actual_net_pnl_kes DOUBLE PRECISION,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bot_slips_user_id ON bot_slips (user_id);
CREATE INDEX IF NOT EXISTS idx_bot_slips_created_at ON bot_slips (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_slips_status ON bot_slips (status);

CREATE TABLE IF NOT EXISTS bot_slip_legs (
    id BIGSERIAL PRIMARY KEY,
    slip_id BIGINT NOT NULL REFERENCES bot_slips(id) ON DELETE CASCADE,
    leg_no INTEGER NOT NULL,
    sport TEXT NOT NULL,
    event_date DATE,
    event_datetime_text TEXT,
    source_name TEXT,
    competition TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    match_url TEXT,
    pred_outcome TEXT,
    pred_probability DOUBLE PRECISION,
    probability_bucket TEXT,
    selected_odds DOUBLE PRECISION,
    bookmaker_source TEXT,
    result_outcome TEXT,
    won BOOLEAN,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bot_slip_leg UNIQUE (slip_id, leg_no)
);

CREATE INDEX IF NOT EXISTS idx_bot_slip_legs_slip_id ON bot_slip_legs (slip_id);
CREATE INDEX IF NOT EXISTS idx_bot_slip_legs_match_url ON bot_slip_legs (match_url);
