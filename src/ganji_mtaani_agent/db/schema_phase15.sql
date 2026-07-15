-- =============================================================================
-- BOB Phase 15: Quote Questions Table
-- =============================================================================
-- Stores the step-by-step questions from each insurer's "Get a Quote" flow.
-- Products and rate tables already exist in the products / rate_tables tables.

CREATE TABLE IF NOT EXISTS quote_questions (
    id            SERIAL PRIMARY KEY,
    product_slug  TEXT    NOT NULL,
    step_number   INTEGER NOT NULL,
    total_steps   INTEGER,
    question_text TEXT    NOT NULL,
    field_type    TEXT,          -- number / select / radio / choice_buttons / text
    min_value     TEXT,
    max_value     TEXT,
    default_value TEXT,
    options       JSONB,         -- [{value, label}, ...]
    is_required   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_slug, step_number)
);

CREATE INDEX IF NOT EXISTS idx_quote_questions_product ON quote_questions(product_slug);
