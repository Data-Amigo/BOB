from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import perf_counter
from typing import Any, Callable

from psycopg import Connection

from ganji_mtaani_agent.db import postgres as postgres_module
from ganji_mtaani_agent.db import repositories as repositories_module
from ganji_mtaani_agent.models.polymarket_fetch import PolymarketFetchConfig
from ganji_mtaani_agent.parsers.betika import parse_betika_basketball, parse_betika_football
from ganji_mtaani_agent.parsers.forebet import parse_forebet_basketball, parse_forebet_football
from ganji_mtaani_agent.parsers.mozzart import parse_mozzart_basketball, parse_mozzart_football
from ganji_mtaani_agent.parsers.sportpesa import parse_sportpesa_basketball, parse_sportpesa_football
from ganji_mtaani_agent.parsers.thesportsdb import normalize_event_results
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.forebet import build_forebet_collection_urls
from ganji_mtaani_agent.scrapers.polymarket import fetch_polymarket_markets, fetch_polymarket_raw
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target
from ganji_mtaani_agent.scrapers.thesportsdb import fetch_events_day


postgres_module = importlib.reload(postgres_module)
repositories_module = importlib.reload(repositories_module)

get_postgres_connection = postgres_module.get_postgres_connection
insert_bookmaker_odds = repositories_module.insert_bookmaker_odds
insert_forebet_predictions = repositories_module.insert_forebet_predictions
insert_ingestion_batch = repositories_module.insert_ingestion_batch
insert_source_run = repositories_module.insert_source_run
update_ingestion_batch = repositories_module.update_ingestion_batch
update_source_run = repositories_module.update_source_run
upsert_polymarket_markets = repositories_module.upsert_polymarket_markets
upsert_sports_results = repositories_module.upsert_sports_results


BOOKMAKER_PARSERS: dict[tuple[str, str], Callable[[str], list[object]]] = {
    ("betika", "football_today"): parse_betika_football,
    ("betika", "basketball_today"): parse_betika_basketball,
    ("sportpesa", "football_today"): parse_sportpesa_football,
    ("sportpesa", "basketball_today"): parse_sportpesa_basketball,
    ("mozzart", "football_today"): parse_mozzart_football,
    ("mozzart", "basketball_today"): parse_mozzart_basketball,
}

FOREBET_PARSERS: dict[str, Callable[[str], list[object]]] = {
    "football_today": parse_forebet_football,
    "basketball_today": parse_forebet_basketball,
}


@dataclass(frozen=True, slots=True)
class DailyIngestionConfig:
    batch_date: date
    triggered_by: str = "streamlit_manual"
    bookmaker_limit: int | None = None
    forebet_limit: int | None = None
    polymarket_limit: int = 200
    polymarket_scan_limit: int = 500
    results_limit: int | None = None
    results_days_back: int = 7
    results_days_forward: int = 3
    notes: str | None = None


def _normalized_text(value: str | None) -> str:
    """Return a comparable lowercase text value for dedupe keys."""

    return " ".join((value or "").split()).casefold()


def _apply_optional_limit(rows: list[object], limit: int | None) -> list[object]:
    """Return rows unchanged when no artificial limit is configured."""

    if limit is None or limit <= 0:
        return rows
    return rows[:limit]


def _dedupe_forebet_predictions(rows: list[object]) -> list[object]:
    """Deduplicate Forebet prediction rows by fixture identity."""

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

    return sorted(
        deduped.values(),
        key=lambda row: (
            _normalized_text(getattr(row, "event_datetime", None)),
            _normalized_text(getattr(row, "league", None)),
            _normalized_text(getattr(row, "home_team", None)),
            _normalized_text(getattr(row, "away_team", None)),
        ),
    )


def _build_results_dates(batch_date: date, *, days_back: int, days_forward: int) -> list[date]:
    """Build a rolling window of dates to fetch around the batch date."""

    return [batch_date + timedelta(days=offset) for offset in range(-days_back, days_forward + 1)]


def _dedupe_results_by_event(rows: list[object]) -> list[object]:
    """Deduplicate TheSportsDB event rows by event id."""

    deduped: dict[str, object] = {}

    for row in rows:
        event_id = str(getattr(row, "event_id", "") or "")
        if not event_id:
            continue
        deduped[event_id] = row

    return sorted(
        deduped.values(),
        key=lambda row: (
            _normalized_text(getattr(row, "event_date", None)),
            _normalized_text(getattr(row, "event_time", None)),
            _normalized_text(getattr(row, "league", None)),
            _normalized_text(getattr(row, "home_team", None)),
            _normalized_text(getattr(row, "away_team", None)),
        ),
    )


def _finalize_source_run(
    connection: Connection,
    run_id: int,
    *,
    status: str,
    started_counter: float,
    records_found: int | None = None,
    warnings_count: int = 0,
    error_message: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    update_source_run(
        connection,
        run_id,
        status=status,
        finished_at=datetime.now(UTC),
        duration_ms=int((perf_counter() - started_counter) * 1000),
        records_found=records_found,
        warnings_count=warnings_count,
        error_message=error_message,
        metadata_json=metadata_json,
    )


def _run_bookmaker_task(
    connection: Connection,
    *,
    batch_id: int,
    source_name: str,
    target_name: str,
    limit: int,
) -> dict[str, Any]:
    source = get_source_config(source_name)
    target = get_source_target(source, target_name)
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name=source.name,
        target_name=target.name,
        source_type="browser",
        status="running",
        started_at=started_at,
        metadata_json={
            "url": target.url,
            "sport": target.sport,
            "limit": limit,
            "headless": source.default_headless,
            "settle_ms": source.default_settle_ms,
        },
    )

    try:
        result = fetch_page(
            target.url,
            timeout_ms=60_000,
            wait_until=source.default_wait_until,
            settle_ms=source.default_settle_ms,
            headless=source.default_headless,
        )
        if result.error:
            raise RuntimeError(result.error)

        parser_fn = BOOKMAKER_PARSERS[(source.name, target.name)]
        normalized_rows = parser_fn(result.html)[:limit]
        inserted_count = insert_bookmaker_odds(connection, run_id=run_id, rows=normalized_rows)
        _finalize_source_run(
            connection,
            run_id,
            status="success",
            started_counter=timer_start,
            records_found=inserted_count,
            warnings_count=len(result.warnings),
            metadata_json={
                "url": target.url,
                "sport": target.sport,
                "limit": limit,
                "title": result.title,
                "html_length": result.html_length,
                "inserted_count": inserted_count,
                "warnings": result.warnings,
            },
        )
        return {
            "source_name": source.name,
            "target_name": target.name,
            "status": "success",
            "records_found": inserted_count,
            "run_id": run_id,
        }
    except Exception as exc:
        _finalize_source_run(
            connection,
            run_id,
            status="failed",
            started_counter=timer_start,
            warnings_count=0,
            error_message=str(exc),
            metadata_json={
                "url": target.url,
                "sport": target.sport,
                "limit": limit,
            },
        )
        raise


def _run_forebet_task(
    connection: Connection,
    *,
    batch_id: int,
    target_name: str,
    limit: int | None,
) -> dict[str, Any]:
    source = get_source_config("forebet")
    target = get_source_target(source, target_name)
    collection_urls = build_forebet_collection_urls(target.name, target.url)
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name=source.name,
        target_name=target.name,
        source_type="browser",
        status="running",
        started_at=started_at,
        metadata_json={
            "url": target.url,
            "collection_urls": collection_urls,
            "sport": target.sport,
            "limit": limit,
            "headless": source.default_headless,
            "settle_ms": source.default_settle_ms,
        },
    )

    try:
        parser_fn = FOREBET_PARSERS[target.name]
        page_summaries: list[dict[str, Any]] = []
        collected_rows: list[object] = []
        failed_urls: list[dict[str, str]] = []
        total_warning_count = 0

        for url in collection_urls:
            result = fetch_page(
                url,
                timeout_ms=60_000,
                wait_until=source.default_wait_until,
                settle_ms=source.default_settle_ms,
                headless=source.default_headless,
            )
            total_warning_count += len(result.warnings)

            if result.error:
                failed_urls.append({"url": url, "error": result.error})
                page_summaries.append({"url": url, "status": "failed", "error": result.error})
                continue

            parsed_rows = parser_fn(result.html)
            collected_rows.extend(parsed_rows)
            page_summaries.append(
                {
                    "url": url,
                    "status": "success",
                    "title": result.title,
                    "html_length": result.html_length,
                    "parsed_rows": len(parsed_rows),
                    "warnings": result.warnings,
                }
            )

        if not collected_rows:
            raise RuntimeError("Forebet collection returned no parseable rows across all configured URLs.")

        unique_rows = _dedupe_forebet_predictions(collected_rows)
        normalized_rows = _apply_optional_limit(unique_rows, limit)
        inserted_count = insert_forebet_predictions(connection, run_id=run_id, rows=normalized_rows)
        _finalize_source_run(
            connection,
            run_id,
            status="success",
            started_counter=timer_start,
            records_found=inserted_count,
            warnings_count=total_warning_count + len(failed_urls),
            metadata_json={
                "url": target.url,
                "collection_urls": collection_urls,
                "sport": target.sport,
                "limit": limit,
                "raw_rows_collected": len(collected_rows),
                "unique_rows_collected": len(unique_rows),
                "inserted_count": inserted_count,
                "failed_urls": failed_urls,
                "page_summaries": page_summaries,
            },
        )
        return {
            "source_name": source.name,
            "target_name": target.name,
            "status": "success",
            "records_found": inserted_count,
            "run_id": run_id,
        }
    except Exception as exc:
        _finalize_source_run(
            connection,
            run_id,
            status="failed",
            started_counter=timer_start,
            warnings_count=0,
            error_message=str(exc),
            metadata_json={
                "url": target.url,
                "collection_urls": collection_urls,
                "sport": target.sport,
                "limit": limit,
            },
        )
        raise


def _run_polymarket_task(
    connection: Connection,
    *,
    batch_id: int,
    limit: int,
    scan_limit: int,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name="polymarket",
        target_name="markets",
        source_type="api",
        status="running",
        started_at=started_at,
        metadata_json={
            "limit": limit,
            "scan_limit": scan_limit,
            "active_only": True,
        },
    )

    try:
        config = PolymarketFetchConfig(
            result_limit=limit,
            scan_limit=scan_limit,
            active_only=True,
            category=None,
        )
        raw_response = fetch_polymarket_raw(config)
        normalized_rows = fetch_polymarket_markets(config)
        inserted_count = upsert_polymarket_markets(connection, run_id=run_id, rows=normalized_rows)
        _finalize_source_run(
            connection,
            run_id,
            status="success",
            started_counter=timer_start,
            records_found=inserted_count,
            warnings_count=0,
            metadata_json={
                "limit": limit,
                "scan_limit": scan_limit,
                "active_only": True,
                "raw_markets": len(raw_response.markets),
                "raw_events": len(raw_response.events),
                "inserted_count": inserted_count,
            },
        )
        return {
            "source_name": "polymarket",
            "target_name": "markets",
            "status": "success",
            "records_found": inserted_count,
            "run_id": run_id,
        }
    except Exception as exc:
        _finalize_source_run(
            connection,
            run_id,
            status="failed",
            started_counter=timer_start,
            warnings_count=0,
            error_message=str(exc),
            metadata_json={
                "limit": limit,
                "scan_limit": scan_limit,
                "active_only": True,
            },
        )
        raise


def _run_results_task(
    connection: Connection,
    *,
    batch_id: int,
    batch_date: date,
    sport: str,
    limit: int | None,
    days_back: int,
    days_forward: int,
) -> dict[str, Any]:
    target_name = f"results_{sport.lower()}"
    fetch_dates = _build_results_dates(batch_date, days_back=days_back, days_forward=days_forward)
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name="thesportsdb",
        target_name=target_name,
        source_type="api",
        status="running",
        started_at=started_at,
        metadata_json={
            "date": batch_date.isoformat(),
            "fetch_dates": [item.isoformat() for item in fetch_dates],
            "sport": sport,
            "limit": limit,
        },
    )

    try:
        page_summaries: list[dict[str, Any]] = []
        collected_rows: list[object] = []
        failed_dates: list[dict[str, str]] = []

        for fetch_date in fetch_dates:
            try:
                payload = fetch_events_day(fetch_date.isoformat(), sport=sport)
                normalized_page_rows = normalize_event_results(payload)
                collected_rows.extend(normalized_page_rows)
                page_summaries.append(
                    {
                        "date": fetch_date.isoformat(),
                        "status": "success",
                        "records_found": len(normalized_page_rows),
                    }
                )
            except Exception as exc:
                failed_dates.append({"date": fetch_date.isoformat(), "error": str(exc)})
                page_summaries.append(
                    {
                        "date": fetch_date.isoformat(),
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        if not collected_rows:
            raise RuntimeError("TheSportsDB rolling window returned no normalized event rows.")

        unique_rows = _dedupe_results_by_event(collected_rows)
        normalized_rows = _apply_optional_limit(unique_rows, limit)
        inserted_count = upsert_sports_results(connection, run_id=run_id, rows=normalized_rows)
        _finalize_source_run(
            connection,
            run_id,
            status="success",
            started_counter=timer_start,
            records_found=inserted_count,
            warnings_count=len(failed_dates),
            metadata_json={
                "date": batch_date.isoformat(),
                "fetch_dates": [item.isoformat() for item in fetch_dates],
                "sport": sport,
                "limit": limit,
                "raw_rows_collected": len(collected_rows),
                "unique_rows_collected": len(unique_rows),
                "inserted_count": inserted_count,
                "failed_dates": failed_dates,
                "page_summaries": page_summaries,
            },
        )
        return {
            "source_name": "thesportsdb",
            "target_name": target_name,
            "status": "success",
            "records_found": inserted_count,
            "run_id": run_id,
        }
    except Exception as exc:
        _finalize_source_run(
            connection,
            run_id,
            status="failed",
            started_counter=timer_start,
            warnings_count=0,
            error_message=str(exc),
            metadata_json={
                "date": batch_date.isoformat(),
                "fetch_dates": [item.isoformat() for item in fetch_dates],
                "sport": sport,
                "limit": limit,
            },
        )
        raise


def run_daily_ingestion(config: DailyIngestionConfig) -> dict[str, Any]:
    """Run the current daily ingestion stack and return a batch summary."""

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

    batch_started_at = datetime.now(UTC)
    outcomes: list[dict[str, Any]] = []

    with get_postgres_connection(autocommit=True) as connection:
        batch_id = insert_ingestion_batch(
            connection,
            batch_name="daily_manual_ingestion",
            batch_date=config.batch_date,
            status="running",
            started_at=batch_started_at,
            triggered_by=config.triggered_by,
            notes=config.notes,
            metadata_json={
                "bookmaker_limit": config.bookmaker_limit,
                "forebet_limit": config.forebet_limit,
                "polymarket_limit": config.polymarket_limit,
                "polymarket_scan_limit": config.polymarket_scan_limit,
                "results_limit": config.results_limit,
                "results_days_back": config.results_days_back,
                "results_days_forward": config.results_days_forward,
            },
        )

        tasks: list[tuple[str, Callable[[], dict[str, Any]]]] = [
            ("betika_football", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="betika", target_name="football_today", limit=config.bookmaker_limit)),
            ("betika_basketball", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="betika", target_name="basketball_today", limit=config.bookmaker_limit)),
            ("sportpesa_football", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="sportpesa", target_name="football_today", limit=config.bookmaker_limit)),
            ("sportpesa_basketball", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="sportpesa", target_name="basketball_today", limit=config.bookmaker_limit)),
            ("mozzart_football", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="mozzart", target_name="football_today", limit=config.bookmaker_limit)),
            ("mozzart_basketball", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="mozzart", target_name="basketball_today", limit=config.bookmaker_limit)),
            ("forebet_football", lambda: _run_forebet_task(connection, batch_id=batch_id, target_name="football_today", limit=config.forebet_limit)),
            ("forebet_basketball", lambda: _run_forebet_task(connection, batch_id=batch_id, target_name="basketball_today", limit=config.forebet_limit)),
            ("polymarket_markets", lambda: _run_polymarket_task(connection, batch_id=batch_id, limit=config.polymarket_limit, scan_limit=config.polymarket_scan_limit)),
            ("results_soccer", lambda: _run_results_task(connection, batch_id=batch_id, batch_date=config.batch_date, sport="Soccer", limit=config.results_limit, days_back=config.results_days_back, days_forward=config.results_days_forward)),
            ("results_basketball", lambda: _run_results_task(connection, batch_id=batch_id, batch_date=config.batch_date, sport="Basketball", limit=config.results_limit, days_back=config.results_days_back, days_forward=config.results_days_forward)),
        ]

        for task_name, task_fn in tasks:
            try:
                task_result = task_fn()
                task_result["task_name"] = task_name
                outcomes.append(task_result)
            except Exception as exc:
                outcomes.append(
                    {
                        "task_name": task_name,
                        "status": "failed",
                        "records_found": 0,
                        "error": str(exc),
                    }
                )

        total_sources = len(outcomes)
        successful_sources = sum(1 for row in outcomes if row.get("status") == "success")
        failed_sources = total_sources - successful_sources
        final_status = "success"
        if failed_sources and successful_sources:
            final_status = "partial_success"
        elif failed_sources == total_sources:
            final_status = "failed"

        update_ingestion_batch(
            connection,
            batch_id,
            status=final_status,
            finished_at=datetime.now(UTC),
            total_sources=total_sources,
            successful_sources=successful_sources,
            failed_sources=failed_sources,
            metadata_json={
                "bookmaker_limit": config.bookmaker_limit,
                "forebet_limit": config.forebet_limit,
                "polymarket_limit": config.polymarket_limit,
                "polymarket_scan_limit": config.polymarket_scan_limit,
                "results_limit": config.results_limit,
                "results_days_back": config.results_days_back,
                "results_days_forward": config.results_days_forward,
                "outcomes": outcomes,
            },
        )

    return {
        "batch_id": batch_id,
        "batch_date": config.batch_date.isoformat(),
        "status": final_status,
        "total_sources": total_sources,
        "successful_sources": successful_sources,
        "failed_sources": failed_sources,
        "outcomes": outcomes,
    }
