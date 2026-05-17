"""Insert Forebet and Polymarket data into PostgreSQL for phase 2 validation."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ganji_mtaani_agent.db import (
    get_postgres_connection,
    insert_forebet_predictions,
    insert_source_run,
    update_source_run,
    upsert_polymarket_markets,
)
from ganji_mtaani_agent.models.polymarket_fetch import PolymarketFetchConfig
from ganji_mtaani_agent.parsers.forebet import parse_forebet_basketball, parse_forebet_football
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.forebet import build_forebet_collection_urls
from ganji_mtaani_agent.scrapers.polymarket import fetch_polymarket_markets, fetch_polymarket_raw
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Insert Forebet and Polymarket rows into PostgreSQL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    forebet_parser = subparsers.add_parser("forebet", help="Fetch Forebet HTML, parse predictions, and insert them.")
    forebet_parser.add_argument("--target", choices=["football_today", "basketball_today"], default="football_today")
    forebet_parser.add_argument("--limit", type=int, default=0, help="0 means no artificial row cap.")
    forebet_parser.add_argument("--headed", action="store_true")
    forebet_parser.add_argument("--headless", action="store_true")
    forebet_parser.add_argument("--timeout-ms", type=int, default=60000)
    forebet_parser.add_argument("--settle-ms", type=int, default=None)

    poly_parser = subparsers.add_parser("polymarket", help="Fetch Polymarket Gamma markets and upsert them.")
    poly_parser.add_argument("--limit", type=int, default=50)
    poly_parser.add_argument("--scan-limit", type=int, default=200)
    poly_parser.add_argument("--category", type=str, default=None)
    poly_parser.add_argument("--include-closed", action="store_true")

    return parser


def _parse_forebet_target(target_name: str, html: str):
    if target_name == "basketball_today":
        return parse_forebet_basketball(html)
    if target_name == "football_today":
        return parse_forebet_football(html)
    raise ValueError(f"No parser configured for Forebet target {target_name!r}")


def _normalized_text(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _dedupe_forebet_predictions(rows: list[object]) -> list[object]:
    deduped: dict[tuple[str, str, str, str, str], object] = {}

    for row in rows:
        key = (
            _normalized_text(getattr(row, "sport", None)),
            _normalized_text(getattr(row, "league", None)),
            _normalized_text(getattr(row, "home_team", None)),
            _normalized_text(getattr(row, "away_team", None)),
            _normalized_text(getattr(row, "event_datetime", None)),
        )
        deduped.setdefault(key, row)

    return list(deduped.values())


def insert_forebet_flow(args: argparse.Namespace) -> None:
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    source = get_source_config("forebet")
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
            batch_id=getattr(args, "batch_id", None),
            metadata_json={
                "url": target.url,
                "sport": target.sport,
                "limit": args.limit,
                "headless": headless,
                "settle_ms": settle_ms,
            },
        )

        try:
            collection_urls = build_forebet_collection_urls(target.name, target.url)
            collected_rows: list[object] = []
            page_summaries: list[dict[str, object]] = []
            warning_count = 0

            for url in collection_urls:
                result = fetch_page(
                    url,
                    timeout_ms=args.timeout_ms,
                    wait_until=source.default_wait_until,
                    settle_ms=settle_ms,
                    headless=headless,
                )
                warning_count += len(result.warnings)

                if result.error:
                    page_summaries.append({"url": url, "status": "failed", "error": result.error})
                    continue

                parsed_rows = _parse_forebet_target(target.name, result.html)
                collected_rows.extend(parsed_rows)
                page_summaries.append(
                    {
                        "url": url,
                        "status": "success",
                        "title": result.title,
                        "html_length": result.html_length,
                        "parsed_rows": len(parsed_rows),
                    }
                )

            if not collected_rows:
                raise RuntimeError("Forebet collection returned no parseable rows across all configured URLs.")

            normalized_rows = _dedupe_forebet_predictions(collected_rows)
            if args.limit > 0:
                normalized_rows = normalized_rows[: args.limit]
            inserted_count = insert_forebet_predictions(connection, run_id=run_id, rows=normalized_rows)

            finished_at = datetime.now(UTC)
            duration_ms = int((perf_counter() - timer_start) * 1000)
            update_source_run(
                connection,
                run_id,
                status="success",
                finished_at=finished_at,
                duration_ms=duration_ms,
                records_found=inserted_count,
                warnings_count=warning_count,
                metadata_json={
                    "url": target.url,
                    "collection_urls": collection_urls,
                    "sport": target.sport,
                    "limit": args.limit,
                    "headless": headless,
                    "settle_ms": settle_ms,
                    "raw_rows_collected": len(collected_rows),
                    "unique_rows_collected": len(normalized_rows),
                    "inserted_count": inserted_count,
                    "page_summaries": page_summaries,
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

    print(f"run_id: {run_id}")
    print(f"inserted_forebet_predictions: {inserted_count}")
    print(f"warnings: {len(result.warnings)}")
    return {
        "run_id": run_id,
        "source_name": source.name,
        "target_name": target.name,
        "records_found": inserted_count,
    }


def insert_polymarket_flow(args: argparse.Namespace) -> None:
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    config = PolymarketFetchConfig(
        result_limit=args.limit,
        scan_limit=args.scan_limit,
        active_only=not args.include_closed,
        category=args.category,
    )

    with get_postgres_connection(autocommit=True) as connection:
        run_id = insert_source_run(
            connection,
            source_name="polymarket",
            target_name="markets",
            source_type="api",
            status="running",
            started_at=started_at,
            batch_id=getattr(args, "batch_id", None),
            metadata_json={
                "limit": args.limit,
                "scan_limit": args.scan_limit,
                "category": args.category,
                "active_only": not args.include_closed,
            },
        )

        try:
            raw_response = fetch_polymarket_raw(config)
            normalized_rows = fetch_polymarket_markets(config)
            inserted_count = upsert_polymarket_markets(connection, run_id=run_id, rows=normalized_rows)

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
                    "limit": args.limit,
                    "scan_limit": args.scan_limit,
                    "category": args.category,
                    "active_only": not args.include_closed,
                    "raw_markets": len(raw_response.markets),
                    "raw_events": len(raw_response.events),
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
                    "limit": args.limit,
                    "scan_limit": args.scan_limit,
                    "category": args.category,
                    "active_only": not args.include_closed,
                },
            )
            raise

    print(f"run_id: {run_id}")
    print(f"raw_markets: {len(raw_response.markets)}")
    print(f"raw_events: {len(raw_response.events)}")
    print(f"upserted_polymarket_markets: {inserted_count}")
    return {
        "run_id": run_id,
        "source_name": "polymarket",
        "target_name": "markets",
        "records_found": inserted_count,
    }


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    if args.command == "forebet":
        insert_forebet_flow(args)
        return

    if args.command == "polymarket":
        insert_polymarket_flow(args)
        return

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
