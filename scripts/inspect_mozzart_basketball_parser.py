"""This is the inspect_mozzart_basketball_parser.py file.

Author: Data-Amigo
Date: 2026-05-02
Description:
This script fetches the Mozzart basketball prematch page with the shared browser
layer, parses the stable basketball fields, and prints a structured preview for
development and verification.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.parsers.mozzart import parse_mozzart_basketball
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


# =============================================================================
# Main Inspection Function
# =============================================================================
def main() -> None:
    """Fetch the Mozzart basketball prematch page and inspect parsed rows."""

    parser = argparse.ArgumentParser(description="Inspect the Mozzart basketball parser output.")
    parser.add_argument("--limit", type=int, default=5, help="Number of parsed rows to print.")
    parser.add_argument("--settle-ms", type=int, default=None, help="Override extra wait after page load.")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Maximum page load timeout.")
    parser.add_argument("--headed", action="store_true", help="Force a visible browser window.")
    parser.add_argument("--headless", action="store_true", help="Force a hidden browser window.")
    args = parser.parse_args()

    source = get_source_config("mozzart")
    target = get_source_target(source, "basketball_today")
    settle_ms = args.settle_ms if args.settle_ms is not None else source.default_settle_ms

    headless = source.default_headless
    if args.headed:
        headless = False
    elif args.headless:
        headless = True

    result = fetch_page(
        target.url,
        timeout_ms=args.timeout_ms,
        wait_until=source.default_wait_until,
        settle_ms=settle_ms,
        headless=headless,
    )

    print(f"source: {source.display_name}")
    print(f"target: {target.display_name}")
    print(f"sport: {target.sport}")
    print(f"url: {result.url}")
    print(f"status: {result.status}")
    print(f"title: {result.title}")
    print(f"html_length: {result.html_length}")
    print(f"headless: {headless}")

    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.error:
        print(f"error: {result.error}")
        return

    parsed_rows = parse_mozzart_basketball(result.html)
    print(f"parsed_rows: {len(parsed_rows)}")

    for index, row in enumerate(parsed_rows[: args.limit], start=1):
        print("---")
        print(f"row_{index}:")
        print(f"  league: {row.league}")
        print(f"  game_id: {row.game_id}")
        print(f"  event_datetime_text: {row.event_datetime_text}")
        print(f"  home_team: {row.home_team}")
        print(f"  away_team: {row.away_team}")
        print(f"  extra_market_count: {row.extra_market_count}")
        print(f"  home_odds: {row.home_odds}")
        print(f"  draw_odds: {row.draw_odds}")
        print(f"  away_odds: {row.away_odds}")
        print(f"  confidence: {row.confidence}")


if __name__ == "__main__":
    main()
