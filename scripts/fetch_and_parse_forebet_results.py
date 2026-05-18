"""Fetch and preview Forebet yesterday results for football or basketball."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ganji_mtaani_agent.parsers.forebet import (
    parse_forebet_basketball_yesterday,
    parse_forebet_football_yesterday,
)
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


RESULT_PARSERS = {
    "football_yesterday": parse_forebet_football_yesterday,
    "basketball_yesterday": parse_forebet_basketball_yesterday,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and parse Forebet yesterday results.")
    parser.add_argument("--target", choices=["football_yesterday", "basketball_yesterday"], default="football_yesterday")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    source = get_source_config("forebet")
    target = get_source_target(source, args.target)
    result = fetch_page(
        target.url,
        wait_until=source.default_wait_until,
        settle_ms=source.default_settle_ms,
        headless=source.default_headless,
    )

    print(f"source: {source.display_name}")
    print(f"target: {target.display_name}")
    print(f"status: {result.status}")
    print(f"title: {result.title}")
    print(f"html_length: {result.html_length}")
    print(f"warnings: {result.warnings}")
    print(f"error: {result.error}")

    if result.error:
        return

    parser_fn = RESULT_PARSERS[target.name]
    rows = parser_fn(result.html)
    print(f"parsed_rows: {len(rows)}")

    for index, row in enumerate(rows[: args.limit], start=1):
        print("---")
        print(f"row_{index}:")
        print(f"  league: {row.league}")
        print(f"  home_team: {row.home_team}")
        print(f"  away_team: {row.away_team}")
        print(f"  event_datetime: {row.event_datetime}")
        print(f"  pred_outcome: {row.pred_outcome}")
        print(f"  predicted_score_text: {row.predicted_score_text}")
        print(f"  actual_score_text: {row.actual_score_text}")
        print(f"  actual_outcome: {row.actual_outcome}")
        print(f"  status: {row.status}")
        print(f"  pred_hit: {row.pred_hit}")
        print(f"  pred_indicator_class: {row.pred_indicator_class}")
        print(f"  confidence: {row.confidence}")


if __name__ == "__main__":
    main()
