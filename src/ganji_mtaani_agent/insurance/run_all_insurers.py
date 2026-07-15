"""Scrape all registered insurers and write results to insuranceiq schema.

Excludes:
  - jubilee  (live in public.* Jubilee AI project — do not touch)
  - mamabima (dedicated scraper: scrapers/mamabima.py)
  - apa      (AWS WAF requires headed browser — skipped in CI / server context)

Run:
    python -m ganji_mtaani_agent.insurance.run_all_insurers

Or a single insurer:
    python -m ganji_mtaani_agent.insurance.run_all_insurers britam
    python -m ganji_mtaani_agent.insurance.run_all_insurers britam personal_protection
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from ganji_mtaani_agent.db.postgres import get_postgres_connection
from ganji_mtaani_agent.insurance.insuranceiq_writer import upsert_insurer, upsert_product
from ganji_mtaani_agent.insurance.pipeline import scrape_source_target
from ganji_mtaani_agent.insurance.sources import INSURANCE_SOURCES

# Insurers + targets to run. None → all targets defined in sources.py.
# APA is excluded: default_headless=False and AWS WAF blocks automated runs.
_RUN_MATRIX: list[tuple[str, list[str] | None]] = [
    ("britam",       None),   # personal_protection, personal_property, education, savings, investment, unit_trust, pension
    ("cic",          None),   # individual, business
    ("old_mutual",   None),   # personal_insure, save_invest, unit_trust
    ("sanlam",       None),   # all_products
    ("icea_lion",    None),   # all_products
    ("aar",          None),   # all_products (hardcoded URLs)
    ("ga_insurance", None),   # all_products (hardcoded URLs)
    ("geminia",      None),   # all_products (hardcoded URLs)
]


def _expand_targets(source_name: str, target_names: list[str] | None) -> list[str]:
    """Return the list of target names to run for this insurer."""
    source = INSURANCE_SOURCES[source_name]
    if target_names:
        return target_names
    return list(source.targets.keys())


def run_insurer(conn, source_name: str, target_name: str) -> dict:
    """Scrape one target for one insurer and write to DB. Returns a summary dict."""
    row: dict = {"insurer": source_name, "target": target_name, "products_written": 0, "errors": []}
    try:
        products = scrape_source_target(source_name, target_name, verbose=True)
        for p in products:
            try:
                slug = upsert_product(conn, p)
                print(f"    [db ok] {p.product_name} → {slug}", flush=True)
                row["products_written"] += 1
            except Exception as exc:
                msg = str(exc)[:150]
                row["errors"].append(f"db/{p.product_name}: {msg}")
                print(f"    [db err] {msg}", flush=True)
    except Exception as exc:
        msg = str(exc)[:200]
        row["errors"].append(f"scrape: {msg}")
        print(f"  [scrape error] {msg}", flush=True)
    return row


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    started = datetime.now(UTC)
    print(f"=== InsuranceIQ Scrape === {started.strftime('%Y-%m-%d %H:%M UTC')}", flush=True)

    # Allow single insurer / target override from CLI
    if args:
        source_name = args[0]
        target_override = [args[1]] if len(args) > 1 else None
        matrix: list[tuple[str, list[str] | None]] = [(source_name, target_override)]
    else:
        matrix = _RUN_MATRIX

    all_rows: list[dict] = []

    with get_postgres_connection(autocommit=True) as conn:
        for source_name, target_names in matrix:
            if source_name not in INSURANCE_SOURCES:
                print(f"\n[{source_name}] SKIP — not in INSURANCE_SOURCES", flush=True)
                continue

            upsert_insurer(conn, source_name)
            targets = _expand_targets(source_name, target_names)

            for target_name in targets:
                print(f"\n[{source_name} / {target_name}] starting...", flush=True)
                row = run_insurer(conn, source_name, target_name)
                all_rows.append(row)
                print(
                    f"[{source_name} / {target_name}] "
                    f"wrote {row['products_written']} products, "
                    f"{len(row['errors'])} errors",
                    flush=True,
                )

    duration = round((datetime.now(UTC) - started).total_seconds(), 1)
    total_products = sum(r["products_written"] for r in all_rows)
    total_errors   = sum(len(r["errors"]) for r in all_rows)

    print(f"\n=== Done in {duration}s | {total_products} products written | {total_errors} errors ===", flush=True)
    print(json.dumps(all_rows, indent=2))
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
