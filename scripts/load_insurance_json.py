from __future__ import annotations

"""Load insurance products from one or more JSON files into insurance_products.

This script is for environments where the scraper (Playwright) and the database
(psycopg) live in different Python installations. Scrape to JSON first:

    python scripts\scrape_insurance.py --source jubilee --target health --output-json data\jubilee_health.json

Then load into the database using the venv Python which has psycopg:

    .venv\Scripts\python.exe scripts\load_insurance_json.py data\jubilee_health.json data\jubilee_life.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.db.postgres import get_postgres_connection
from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


def _from_dict(d: dict) -> InsuranceProduct:
    return InsuranceProduct(
        insurer_name      = d["insurer_name"],
        insurer_slug      = d["insurer_slug"],
        product_name      = d["product_name"],
        product_type      = d["product_type"],
        product_url       = d["product_url"],
        description       = d.get("description", ""),
        tagline           = d.get("tagline"),
        target_audience   = d.get("target_audience"),
        premium_min_kes   = d.get("premium_min_kes"),
        premium_max_kes   = d.get("premium_max_kes"),
        premium_frequency = d.get("premium_frequency"),
        premium_notes     = d.get("premium_notes"),
        coverage_min_kes  = d.get("coverage_min_kes"),
        coverage_max_kes  = d.get("coverage_max_kes"),
        coverage_notes    = d.get("coverage_notes"),
        min_age           = d.get("min_age"),
        max_age           = d.get("max_age"),
        eligibility_notes = d.get("eligibility_notes"),
        key_benefits      = d.get("key_benefits") or [],
        exclusions        = d.get("exclusions") or [],
        waiting_period    = d.get("waiting_period"),
        claims_process    = d.get("claims_process"),
        how_to_apply      = d.get("how_to_apply"),
        contact_phone     = d.get("contact_phone"),
        contact_email     = d.get("contact_email"),
        extra_data        = d.get("extra_data") or {},
        raw_text          = d.get("raw_text", ""),
        confidence        = d.get("confidence", 0.0),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load insurance JSON files into insurance_products.")
    parser.add_argument("files", nargs="+", type=Path, metavar="JSON_FILE")
    args = parser.parse_args()

    all_products: list[InsuranceProduct] = []
    for path in args.files:
        if not path.exists():
            print(f"[warn] file not found: {path}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        products = [_from_dict(d) for d in data]
        print(f"[load] {path.name} - {len(products)} products")
        all_products.extend(products)

    if not all_products:
        print("[done] nothing to insert.")
        return

    from ganji_mtaani_agent.db.repositories import upsert_insurance_products
    with get_postgres_connection() as conn:
        saved = upsert_insurance_products(conn, all_products)
        conn.commit()

    print(f"[db] {saved} products upserted into insurance_products.")


if __name__ == "__main__":
    main()
