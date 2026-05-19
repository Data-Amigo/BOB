"""Inspect the Flashscore football parser output."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.parsers.flashscore import parse_flashscore_football
from ganji_mtaani_agent.scrapers.flashscore import fetch_flashscore_scoreboard
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


def main() -> None:
    """Fetch the Flashscore football page and inspect parsed rows."""

    parser = argparse.ArgumentParser(description="Inspect the Flashscore football parser output.")
    parser.add_argument("--limit", type=int, default=5, help="Number of parsed rows to print.")
    parser.add_argument("--settle-ms", type=int, default=None, help="Override extra wait after page load.")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Maximum page load timeout.")
    parser.add_argument("--days-back", type=int, default=0, help="How many days back to move from the current board.")
    parser.add_argument("--finished-only", action="store_true", help="Switch the Flashscore board to finished matches.")
    parser.add_argument("--headed", action="store_true", help="Force a visible browser window.")
    parser.add_argument("--headless", action="store_true", help="Force a hidden browser window.")
    args = parser.parse_args()

    source = get_source_config("flashscore")
    target = get_source_target(source, "football_today")
    settle_ms = args.settle_ms if args.settle_ms is not None else source.default_settle_ms

    headless = source.default_headless
    if args.headed:
        headless = False
    elif args.headless:
        headless = True

    result = fetch_flashscore_scoreboard(
        target.url,
        days_back=args.days_back,
        finished_only=args.finished_only,
        timeout_ms=args.timeout_ms,
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
    print(f"days_back: {args.days_back}")
    print(f"finished_only: {args.finished_only}")

    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.error:
        print(f"error: {result.error}")
        return

    parsed_rows = parse_flashscore_football(result.html)
    print(f"parsed_rows: {len(parsed_rows)}")

    for index, row in enumerate(parsed_rows[: args.limit], start=1):
        print("---")
        print(f"row_{index}:")
        print(f"  page_date_text: {row.page_date_text}")
        print(f"  country_or_region: {row.country_or_region}")
        print(f"  league: {row.league}")
        print(f"  match_status: {row.match_status}")
        print(f"  event_time_text: {row.event_time_text}")
        print(f"  home_team: {row.home_team}")
        print(f"  away_team: {row.away_team}")
        print(f"  home_score: {row.home_score}")
        print(f"  away_score: {row.away_score}")
        print(f"  confidence: {row.confidence}")


if __name__ == "__main__":
    main()
