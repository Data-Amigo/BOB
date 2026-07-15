-- =============================================================================
-- InsuranceIQ Schema
-- =============================================================================
-- Completely isolated from the public.* Jubilee AI project tables.
-- All future insurers (Mamabima, Old Mutual, CIC, Sanlam, Britam, etc.)
-- go here. Jubilee stays in public.* untouched.

CREATE SCHEMA IF NOT EXISTS insuranceiq;

-- ---------------------------------------------------------------------------
-- insurers: registry of all insurance companies
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insuranceiq.insurers (
    id           SERIAL PRIMARY KEY,
    insurer_slug TEXT        NOT NULL UNIQUE,
    insurer_name TEXT        NOT NULL,
    website      TEXT,
    logo_url     TEXT,
    active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- products: master product catalogue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insuranceiq.products (
    id                   SERIAL PRIMARY KEY,
    insurer_slug         TEXT        NOT NULL,
    product_slug         TEXT        NOT NULL,
    product_name         TEXT        NOT NULL,
    product_type         TEXT,
    tagline              TEXT,
    description          TEXT,

    min_age              INTEGER,
    max_age              INTEGER,
    who_is_it_for        TEXT,
    who_can_be_covered   TEXT,
    eligibility_notes    TEXT,

    key_benefits         JSONB,
    benefit_options      JSONB,
    exclusions           JSONB,
    waiting_period_days  INTEGER,
    waiting_period_notes TEXT,
    faqs                 JSONB,

    product_url          TEXT,
    quote_url            TEXT,
    quotable             BOOLEAN     NOT NULL DEFAULT FALSE,
    active               BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (insurer_slug, product_slug)
);

CREATE INDEX IF NOT EXISTS idx_iq_products_insurer
    ON insuranceiq.products(insurer_slug);

-- ---------------------------------------------------------------------------
-- rate_tables: premium / coverage tiers (where published by insurer)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insuranceiq.rate_tables (
    id             SERIAL PRIMARY KEY,
    insurer_slug   TEXT        NOT NULL,
    product_slug   TEXT        NOT NULL,
    plan_name      TEXT,
    member_type    TEXT,
    age_band_min   INTEGER,
    age_band_max   INTEGER,
    sum_insured    BIGINT,
    annual_premium INTEGER,
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_iq_rate_tables_product
    ON insuranceiq.rate_tables(insurer_slug, product_slug);

-- ---------------------------------------------------------------------------
-- quote_questions: step-by-step quote flow per product
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insuranceiq.quote_questions (
    id            SERIAL PRIMARY KEY,
    insurer_slug  TEXT        NOT NULL,
    product_slug  TEXT        NOT NULL,
    step_number   INTEGER     NOT NULL,
    total_steps   INTEGER,
    question_text TEXT        NOT NULL,
    field_type    TEXT,
    min_value     TEXT,
    max_value     TEXT,
    default_value TEXT,
    options       JSONB,
    is_required   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (insurer_slug, product_slug, step_number)
);

CREATE INDEX IF NOT EXISTS idx_iq_quote_questions_product
    ON insuranceiq.quote_questions(insurer_slug, product_slug);
