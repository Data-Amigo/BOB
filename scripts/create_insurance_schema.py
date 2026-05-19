from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.db.postgres import get_postgres_connection


DDL = """
CREATE TABLE IF NOT EXISTS insurance_products (
    id                SERIAL PRIMARY KEY,
    insurer_name      TEXT        NOT NULL,
    insurer_slug      TEXT        NOT NULL,
    product_name      TEXT        NOT NULL,
    product_type      TEXT        NOT NULL,
    product_url       TEXT        NOT NULL,
    description       TEXT,
    tagline           TEXT,
    target_audience   TEXT,
    premium_min_kes   NUMERIC,
    premium_max_kes   NUMERIC,
    premium_frequency TEXT,
    premium_notes     TEXT,
    coverage_min_kes  NUMERIC,
    coverage_max_kes  NUMERIC,
    coverage_notes    TEXT,
    min_age           INTEGER,
    max_age           INTEGER,
    eligibility_notes TEXT,
    key_benefits      JSONB       NOT NULL DEFAULT '[]',
    exclusions        JSONB       NOT NULL DEFAULT '[]',
    waiting_period    TEXT,
    claims_process    TEXT,
    how_to_apply      TEXT,
    contact_phone     TEXT,
    contact_email     TEXT,
    extra_data        JSONB       NOT NULL DEFAULT '{}',
    raw_text          TEXT,
    confidence        NUMERIC     NOT NULL DEFAULT 0.0,
    scraped_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (insurer_slug, product_url)
);
"""


def main() -> None:
    print("Creating insurance_products table...")
    with get_postgres_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
    print("Done.")


if __name__ == "__main__":
    main()
