"""Bridge: InsuranceProduct objects → insuranceiq PostgreSQL schema.

Maps the existing pipeline's InsuranceProduct model onto insuranceiq.insurers
and insuranceiq.products. Does NOT touch public.* tables.
"""

from __future__ import annotations

import json
import re

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct
from ganji_mtaani_agent.insurance.sources import INSURANCE_SOURCES


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def product_slug(insurer_slug: str, product_name: str) -> str:
    prefix = insurer_slug.replace("_", "-")
    return f"{prefix}-{_slugify(product_name)}"


def upsert_insurer(conn, insurer_slug: str) -> None:
    source = INSURANCE_SOURCES.get(insurer_slug)
    if not source:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO insuranceiq.insurers (insurer_slug, insurer_name, website)
            VALUES (%s, %s, %s)
            ON CONFLICT (insurer_slug) DO UPDATE SET
                insurer_name = EXCLUDED.insurer_name,
                website      = EXCLUDED.website
            """,
            (insurer_slug, source.display_name, source.base_url),
        )


def upsert_product(conn, product: InsuranceProduct) -> str:
    """Write one InsuranceProduct to insuranceiq.products. Returns the slug."""
    slug = product_slug(product.insurer_slug, product.product_name)

    extra = product.extra_data or {}
    faqs = extra.get("faqs") or []
    coverage_table = extra.get("coverage_table") or []

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO insuranceiq.products (
                insurer_slug, product_slug, product_name, product_type,
                tagline, description,
                min_age, max_age, who_is_it_for, who_can_be_covered, eligibility_notes,
                key_benefits, benefit_options, exclusions,
                waiting_period_days, waiting_period_notes,
                faqs, product_url, quote_url, quotable,
                created_at, updated_at
            ) VALUES (
                %s,%s,%s,%s, %s,%s,
                %s,%s,%s,%s,%s,
                %s::jsonb,%s::jsonb,%s::jsonb,
                %s,%s,
                %s::jsonb,%s,%s,%s,
                NOW(),NOW()
            )
            ON CONFLICT (insurer_slug, product_slug) DO UPDATE SET
                product_name         = EXCLUDED.product_name,
                product_type         = EXCLUDED.product_type,
                tagline              = EXCLUDED.tagline,
                description          = EXCLUDED.description,
                min_age              = EXCLUDED.min_age,
                max_age              = EXCLUDED.max_age,
                who_is_it_for        = EXCLUDED.who_is_it_for,
                eligibility_notes    = EXCLUDED.eligibility_notes,
                key_benefits         = EXCLUDED.key_benefits,
                benefit_options      = EXCLUDED.benefit_options,
                exclusions           = EXCLUDED.exclusions,
                waiting_period_notes = EXCLUDED.waiting_period_notes,
                faqs                 = EXCLUDED.faqs,
                product_url          = EXCLUDED.product_url,
                updated_at           = NOW()
            """,
            (
                product.insurer_slug,
                slug,
                product.product_name,
                product.product_type,
                product.tagline,
                product.description,
                product.min_age,
                product.max_age,
                product.target_audience,        # → who_is_it_for
                None,                           # who_can_be_covered (not in model)
                product.eligibility_notes,
                json.dumps(product.key_benefits or [], default=str),
                json.dumps(coverage_table, default=str),
                json.dumps(product.exclusions or [], default=str),
                None,                           # waiting_period_days (not parsed)
                product.waiting_period,         # → waiting_period_notes (plain text)
                json.dumps(faqs, default=str),
                product.product_url,
                None,                           # quote_url (not captured by these scrapers)
                False,
            ),
        )
    return slug
