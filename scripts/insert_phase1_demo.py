"""This is the insert_phase1_demo.py file.

Author: Data-Amigo
Date: 2026-05-06
Description:
This script is the first end-to-end database insertion demo for phase 1. It can
insert TheSportsDB result rows into sports_results, and it can also fetch one
bookmaker page, parse normalized odds rows, and insert them into bookmaker_odds.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Callable, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ganji_mtaani_agent.db import (
    get_postgres_connection,
    insert_bookmaker_odds,
    insert_source_run,
    update_source_run,
    upsert_sports_results,
)
from ganji_mtaani_agent.models.thesportsdb import TheSportsDBEventResult
from ganji_mtaani_agent.parsers.betika import parse_betika_basketball, parse_betika_football
from ganji_mtaani_agent.parsers.mozzart import parse_mozzart_basketball, parse_mozzart_football
from ganji_mtaani_agent.parsers.sportpesa import (
    parse_sportpesa_basketball,
    parse_sportpesa_football,
)
from ganji_mtaani_agent.parsers.thesportsdb import normalize_event_results
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target
from ganji_mtaani_agent.scrapers.thesportsdb import fetch_events_day, fetch_lookup_event


# =============================================================================
# Parser Registry
# =============================================================================
BOOKMAKER_PARSERS: dict[tuple[str, str], Callable[[str], list[object]]] = {
    ("betika", "football_today"): parse_betika_football,
    ("betika", "basketball_today"): parse_betika_basketball,
    ("sportpesa", "football_today"): parse_sportpesa_football,
    ("sportpesa", "basketball_today"): parse_sportpesa_basketball,
    ("mozzart", "football_today"): parse_mozzart_football,
    ("mozzart", "basketball_today"): parse_mozzart_basketball,
}


# =============================================================================
# CLI Helpers
# =============================================================================
def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command line interface for the phase 1 insert demo."""

    parser = argparse.ArgumentParser(
        description="Insert phase 1 source data into PostgreSQL for validation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    results_parser = subparsers.add_parser(
        "results",
        help="Fetch TheSportsDB results and insert them into sports_results.",
    )
    results_parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Event date in YYYY-MM-DD format.",
    )
    results_parser.add_argument(
        "--sport",
        type=str,
        default="Soccer",
        help="TheSportsDB sport filter such as Soccer or Basketball.",
    )
    results_parser.add_argument(
        "--event-id",
        type=str,
        default=None,
        help="Optional TheSportsDB event id to inspect one specific event.",
    )
    results_parser.add_argument(
        "--league-id",
        type=str,
        default=None,
        help="Optional TheSportsDB league id filter for events/day queries.",
    )
    results_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of normalized result rows to insert and preview.",
    )

    bookmaker_parser = subparsers.add_parser(
        "bookmaker",
        help="Fetch one bookmaker page, parse it, and insert bookmaker odds rows.",
    )
    bookmaker_parser.add_argument(
        "--source",
        choices=["betika", "sportpesa", "mozzart"],
        required=True,
        help="Bookmaker source name.",
    )
    bookmaker_parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Optional target override such as football_today or basketball_today.",
    )
    bookmaker_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of parsed bookmaker rows to insert and preview.",
    )
    bookmaker_parser.add_argument(
        "--settle-ms",
        type=int,
        default=None,
        help="Override extra wait after page load.",
    )
    bookmaker_parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60000,
        help="Maximum page load timeout.",
    )
    bookmaker_parser.add_argument(
        "--headed",
        action="store_true",
        help="Force a visible browser window.",
    )
    bookmaker_parser.add_argument(
        "--headless",
        action="store_true",
        help="Force a hidden browser window.",
    )

    return parser


# =============================================================================
# Preview Helpers
# =============================================================================
def print_results_preview(rows: Sequence[TheSportsDBEventResult]) -> None:
    """Print a short preview of inserted sports result rows."""

    print(f"normalized_results: {len(rows)}")
    for index, row in enumerate(rows, start=1):
        print("---")
        print(f"result_{index}:")
        print(f"  event_id: {row.event_id}")
        print(f"  league: {row.league}")
        print(f"  event_name: {row.event_name}")
        print(f"  event_date: {row.event_date}")
        print(f"  home_team: {row.home_team}")
        print(f"  away_team: {row.away_team}")
        print(f"  home_score: {row.home_score}")
        print(f"  away_score: {row.away_score}")
        print(f"  status: {row.status}")
        print(f"  winner: {row.winner}")


def print_bookmaker_preview(rows: Sequence[object]) -> None:
    """Print a short preview of inserted bookmaker rows."""

    print(f"normalized_bookmaker_rows: {len(rows)}")
    for index, row in enumerate(rows, start=1):
        print("---")
        print(f"row_{index}:")
        print(f"  source: {getattr(row, 'source', None)}")
        print(f"  sport: {getattr(row, 'sport', None)}")
        print(f"  league: {getattr(row, 'league', None)}")
        print(
            "  event_datetime_text: "
            f"{getattr(row, 'event_datetime_text', getattr(row, 'event_datetime', None))}"
        )
        print(f"  home_team: {getattr(row, 'home_team', None)}")
        print(f"  away_team: {getattr(row, 'away_team', None)}")
        print(f"  home_odds: {getattr(row, 'home_odds', None)}")
        print(f"  draw_odds: {getattr(row, 'draw_odds', None)}")
        print(f"  away_odds: {getattr(row, 'away_odds', None)}")
        print(f"  confidence: {getattr(row, 'confidence', None)}")


# =============================================================================
# Result Insertion Flow
# =============================================================================
def insert_results_flow(args: argparse.Namespace) -> None:
    """Fetch, normalize, and insert TheSportsDB results into PostgreSQL."""

    started_at = datetime.now(UTC)
    timer_start = perf_counter()

    with get_postgres_connection(autocommit=True) as connection:
        run_id = insert_source_run(
            connection,
            source_name="thesportsdb",
            target_name="results",
            source_type="api",
            status="running",
            started_at=started_at,
            metadata_json={
                "date": args.date,
                "sport": args.sport,
                "event_id": args.event_id,
                "league_id": args.league_id,
                "limit": args.limit,
            },
        )

        try:
            if args.event_id:
                payload = fetch_lookup_event(args.event_id)
            else:
                payload = fetch_events_day(args.date, sport=args.sport, league_id=args.league_id)

            normalized_rows = normalize_event_results(payload)[: args.limit]
            inserted_count = upsert_sports_results(
                connection,
                run_id=run_id,
                rows=normalized_rows,
            )

            finished_at = datetime.now(UTC)
            duration_ms = int((perf_counter() - timer_start) * 1000)
            update_source_run(
                connection,
                run_id,
                status="success",
                finished_at=finished_at,
                duration_ms=duration_ms,
                records_found=inserted_count,
                warnings_count=0,
                metadata_json={
                    "date": args.date,
                    "sport": args.sport,
                    "event_id": args.event_id,
                    "league_id": args.league_id,
                    "limit": args.limit,
                    "inserted_count": inserted_count,
                },
            )
        except Exception as exc:
            finished_at = datetime.now(UTC)
            duration_ms = int((perf_counter() - timer_start) * 1000)
            update_source_run(
                connection,
                run_id,
                status="failed",
                finished_at=finished_at,
                duration_ms=duration_ms,
                warnings_count=0,
                error_message=str(exc),
                metadata_json={
                    "date": args.date,
                    "sport": args.sport,
                    "event_id": args.event_id,
                    "league_id": args.league_id,
                    "limit": args.limit,
                },
            )
            raise

    print("source_run_created: success")
    print(f"run_id: {run_id}")
    print(f"inserted_results: {inserted_count}")
    print_results_preview(normalized_rows)


# =============================================================================
# Bookmaker Insertion Flow
# =============================================================================
def insert_bookmaker_flow(args: argparse.Namespace) -> None:
    """Fetch, parse, and insert bookmaker rows into PostgreSQL."""

    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    source = get_source_config(args.source)
    target = get_source_target(source, args.target)
    settle_ms = args.settle_ms if args.settle_ms is not None else source.default_settle_ms
    headless = source.default_headless
    if args.headed:
        headless = False
    elif args.headless:
        headless = True

    with get_postgres_connection(autocommit=True) as connection:
        run_id = insert_source_run(
            connection,
            source_name=source.name,
            target_name=target.name,
            source_type="browser",
            status="running",
            started_at=started_at,
            metadata_json={
                "url": target.url,
                "sport": target.sport,
                "limit": args.limit,
                "headless": headless,
                "settle_ms": settle_ms,
            },
        )

        try:
            result = fetch_page(
                target.url,
                timeout_ms=args.timeout_ms,
                wait_until=source.default_wait_until,
                settle_ms=settle_ms,
                headless=headless,
            )
            if result.error:
                raise RuntimeError(result.error)

            parser_key = (source.name, target.name)
            try:
                parser_fn = BOOKMAKER_PARSERS[parser_key]
            except KeyError as exc:
                raise ValueError(f"No parser registered for {parser_key!r}") from exc

            normalized_rows = parser_fn(result.html)[: args.limit]
            inserted_count = insert_bookmaker_odds(
                connection,
                run_id=run_id,
                rows=normalized_rows,
            )

            finished_at = datetime.now(UTC)
            duration_ms = int((perf_counter() - timer_start) * 1000)
            update_source_run(
                connection,
                run_id,
                status="success",
                finished_at=finished_at,
                duration_ms=duration_ms,
                records_found=inserted_count,
                warnings_count=len(result.warnings),
                metadata_json={
                    "url": target.url,
                    "sport": target.sport,
                    "limit": args.limit,
                    "headless": headless,
                    "settle_ms": settle_ms,
                    "title": result.title,
                    "html_length": result.html_length,
                    "inserted_count": inserted_count,
                    "warnings": result.warnings,
                },
            )
        except Exception as exc:
            finished_at = datetime.now(UTC)
            duration_ms = int((perf_counter() - timer_start) * 1000)
            update_source_run(
                connection,
                run_id,
                status="failed",
                finished_at=finished_at,
                duration_ms=duration_ms,
                warnings_count=0,
                error_message=str(exc),
                metadata_json={
                    "url": target.url,
                    "sport": target.sport,
                    "limit": args.limit,
                    "headless": headless,
                    "settle_ms": settle_ms,
                },
            )
            raise

    print("source_run_created: success")
    print(f"run_id: {run_id}")
    print(f"inserted_bookmaker_rows: {inserted_count}")
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"- {warning}")
    print_bookmaker_preview(normalized_rows)


# =============================================================================
# Main Entry Point
# =============================================================================
def main() -> None:
    """Dispatch the selected phase 1 database insertion flow."""

    parser = build_argument_parser()
    args = parser.parse_args()

    if args.command == "results":
        insert_results_flow(args)
        return

    if args.command == "bookmaker":
        insert_bookmaker_flow(args)
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
