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
import ganji_mtaani_agent.etl.fixture_evaluations as fixture_evaluations_module
import ganji_mtaani_agent.etl.fixture_model_features as fixture_model_features_module
from ganji_mtaani_agent.scrapers import forebet as forebet_scraper_module
from ganji_mtaani_agent.models.polymarket_fetch import PolymarketFetchConfig
from ganji_mtaani_agent.parsers.betika import parse_betika_basketball, parse_betika_football
from ganji_mtaani_agent.parsers.forebet import (
    parse_forebet_basketball,
    parse_forebet_basketball_historical_page,
    parse_forebet_basketball_yesterday,
    parse_forebet_football,
    parse_forebet_football_historical_page,
    parse_forebet_football_yesterday,
)
from ganji_mtaani_agent.parsers.flashscore import parse_flashscore_basketball, parse_flashscore_football
from ganji_mtaani_agent.parsers.mozzart import parse_mozzart_basketball, parse_mozzart_football
from ganji_mtaani_agent.parsers.sportpesa import parse_sportpesa_basketball, parse_sportpesa_football
from ganji_mtaani_agent.parsers.thesportsdb import normalize_event_results
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.flashscore import fetch_flashscore_scoreboard
from ganji_mtaani_agent.scrapers.polymarket import fetch_polymarket_markets, fetch_polymarket_raw
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target
from ganji_mtaani_agent.scrapers.thesportsdb import fetch_events_day
from ganji_mtaani_agent.settlement import settle_slips


postgres_module = importlib.reload(postgres_module)
repositories_module = importlib.reload(repositories_module)
forebet_scraper_module = importlib.reload(forebet_scraper_module)
fixture_evaluations_module = importlib.reload(fixture_evaluations_module)
fixture_model_features_module = importlib.reload(fixture_model_features_module)

get_postgres_connection = postgres_module.get_postgres_connection
insert_bookmaker_odds = repositories_module.insert_bookmaker_odds
insert_forebet_predictions = repositories_module.insert_forebet_predictions
insert_ingestion_batch = repositories_module.insert_ingestion_batch
insert_source_run = repositories_module.insert_source_run
update_ingestion_batch = repositories_module.update_ingestion_batch
update_source_run = repositories_module.update_source_run
fetch_forebet_history_candidates = repositories_module.fetch_forebet_history_candidates
upsert_forebet_match_analysis = repositories_module.upsert_forebet_match_analysis
upsert_forebet_match_history_rows = repositories_module.upsert_forebet_match_history_rows
upsert_forebet_results = repositories_module.upsert_forebet_results
upsert_flashscore_results = repositories_module.upsert_flashscore_results
upsert_polymarket_markets = repositories_module.upsert_polymarket_markets
upsert_sports_results = repositories_module.upsert_sports_results
build_forebet_collection_urls = forebet_scraper_module.build_forebet_collection_urls
FixtureEvaluationBuildConfig = fixture_evaluations_module.FixtureEvaluationBuildConfig
build_fixture_evaluations = fixture_evaluations_module.build_fixture_evaluations
FixtureModelFeatureBuildConfig = fixture_model_features_module.FixtureModelFeatureBuildConfig
build_fixture_model_features = fixture_model_features_module.build_fixture_model_features


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

FOREBET_RESULTS_PARSERS: dict[str, Callable[[str], list[object]]] = {
    "football_yesterday": parse_forebet_football_yesterday,
    "basketball_yesterday": parse_forebet_basketball_yesterday,
}

FLASHSCORE_RESULTS_PARSERS: dict[str, Callable[[str], list[object]]] = {
    "football_yesterday_results": parse_flashscore_football,
    "basketball_yesterday_results": parse_flashscore_basketball,
}

DAILY_TASK_CATALOG: tuple[tuple[str, str], ...] = (
    ("betika_football", "Betika · Football"),
    ("betika_basketball", "Betika · Basketball"),
    ("sportpesa_football", "SportPesa · Football"),
    ("sportpesa_basketball", "SportPesa · Basketball"),
    ("mozzart_football", "Mozzart · Football"),
    ("mozzart_basketball", "Mozzart · Basketball"),
    ("forebet_football", "Forebet · Football Predictions"),
    ("forebet_basketball", "Forebet · Basketball Predictions"),
    ("forebet_football_yesterday_results", "Forebet · Football Yesterday Results"),
    ("forebet_basketball_yesterday_results", "Forebet · Basketball Yesterday Results"),
    ("flashscore_football_yesterday_results", "Flashscore · Football Yesterday Results"),
    ("flashscore_basketball_yesterday_results", "Flashscore · Basketball Yesterday Results"),
    ("polymarket_markets", "Polymarket · Markets"),
    ("results_soccer", "TheSportsDB · Soccer Results"),
    ("results_basketball", "TheSportsDB · Basketball Results"),
)


@dataclass(frozen=True, slots=True)
class DailyIngestionConfig:
    batch_date: date
    triggered_by: str = "streamlit_manual"
    bookmaker_limit: int | None = None
    forebet_limit: int | None = None
    forebet_history_limit: int = 50
    polymarket_limit: int = 500
    polymarket_scan_limit: int = 2_000
    results_limit: int | None = None
    results_days_back: int = 7
    results_days_forward: int = 3
    flashscore_days_back: int = 7
    notes: str | None = None
    selected_tasks: tuple[str, ...] | None = None


def get_daily_task_catalog() -> list[dict[str, str]]:
    """Return ordered task metadata for selective ingestion controls."""

    catalog = [{"task_name": task_name, "display_name": display_name} for task_name, display_name in DAILY_TASK_CATALOG]
    catalog.insert(10, {"task_name": "forebet_football_history", "display_name": "Forebet Football Historical Enrichment"})
    catalog.insert(11, {"task_name": "forebet_basketball_history", "display_name": "Forebet Basketball Historical Enrichment"})
    return catalog


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


def _dedupe_forebet_results(rows: list[object]) -> list[object]:
    """Deduplicate Forebet finished-result rows by fixture identity."""

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
                click_selector_before_capture="#mrows span",
                click_selector_max_times=12 if target.name == "football_yesterday" else 6,
                click_wait_ms=2_000,
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


def _run_forebet_results_task(
    connection: Connection,
    *,
    batch_id: int,
    target_name: str,
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
            "headless": source.default_headless,
            "settle_ms": source.default_settle_ms,
            "result_scope": "yesterday_finished",
        },
    )

    try:
        parser_fn = FOREBET_RESULTS_PARSERS[target.name]
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
            raise RuntimeError("Forebet yesterday collection returned no parseable rows across all configured URLs.")

        normalized_rows = _dedupe_forebet_results(collected_rows)
        inserted_count = upsert_forebet_results(connection, run_id=run_id, rows=normalized_rows)
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
                "raw_rows_collected": len(collected_rows),
                "unique_rows_collected": len(normalized_rows),
                "inserted_count": inserted_count,
                "failed_urls": failed_urls,
                "page_summaries": page_summaries,
                "result_scope": "yesterday_finished",
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
                "result_scope": "yesterday_finished",
            },
        )
        raise


def _run_forebet_history_enrichment_task(
    connection: Connection,
    *,
    batch_id: int,
    sport: str,
    limit: int,
) -> dict[str, Any]:
    """Enrich stored Forebet match URLs with detail-page history for modelling."""

    source = get_source_config("forebet")
    target_name = f"{sport}_history"
    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name=source.name,
        target_name=target_name,
        source_type="browser",
        status="running",
        started_at=started_at,
        metadata_json={
            "sport": sport,
            "history_limit": limit,
            "headless": source.default_headless,
            "settle_ms": source.default_settle_ms,
        },
    )

    try:
        candidates = fetch_forebet_history_candidates(connection, sport=sport, limit=limit)
        if not candidates:
            _finalize_source_run(
                connection,
                run_id,
                status="success",
                started_counter=timer_start,
                records_found=0,
                warnings_count=0,
                metadata_json={
                    "sport": sport,
                    "history_limit": limit,
                    "candidate_count": 0,
                    "enriched_count": 0,
                    "history_rows_saved": 0,
                },
            )
            return {
                "source_name": source.name,
                "target_name": target_name,
                "status": "success",
                "records_found": 0,
                "run_id": run_id,
            }

        parser_fn = (
            parse_forebet_basketball_historical_page
            if sport == "basketball"
            else parse_forebet_football_historical_page
        )

        page_summaries: list[dict[str, Any]] = []
        failed_urls: list[dict[str, str]] = []
        total_warning_count = 0
        enriched_count = 0
        history_rows_saved = 0

        for candidate in candidates:
            match_url = str(candidate["match_url"])
            result = fetch_page(
                match_url,
                timeout_ms=60_000,
                wait_until=source.default_wait_until,
                settle_ms=source.default_settle_ms,
                headless=source.default_headless,
            )
            total_warning_count += len(result.warnings)

            if result.error:
                failed_urls.append({"match_url": match_url, "error": result.error})
                page_summaries.append({"match_url": match_url, "status": "failed", "error": result.error})
                continue

            analysis, history_rows = parser_fn(result.html, match_url=match_url)
            if analysis is None:
                error_message = "The historical parser could not extract a match summary."
                failed_urls.append({"match_url": match_url, "error": error_message})
                page_summaries.append({"match_url": match_url, "status": "failed", "error": error_message})
                continue

            analysis_id = upsert_forebet_match_analysis(connection, analysis=analysis)
            saved_count = upsert_forebet_match_history_rows(connection, rows=history_rows)
            enriched_count += 1
            history_rows_saved += saved_count
            page_summaries.append(
                {
                    "match_url": match_url,
                    "status": "success",
                    "analysis_id": analysis_id,
                    "home_team": analysis.home_team,
                    "away_team": analysis.away_team,
                    "history_rows_saved": saved_count,
                    "warnings": result.warnings,
                }
            )

        if enriched_count == 0 and failed_urls:
            raise RuntimeError("Forebet historical enrichment failed for all queued match URLs.")

        final_status = "partial_success" if failed_urls else "success"
        _finalize_source_run(
            connection,
            run_id,
            status=final_status,
            started_counter=timer_start,
            records_found=enriched_count,
            warnings_count=total_warning_count + len(failed_urls),
            metadata_json={
                "sport": sport,
                "history_limit": limit,
                "candidate_count": len(candidates),
                "enriched_count": enriched_count,
                "history_rows_saved": history_rows_saved,
                "failed_urls": failed_urls,
                "page_summaries": page_summaries,
            },
        )
        return {
            "source_name": source.name,
            "target_name": target_name,
            "status": final_status,
            "records_found": enriched_count,
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
                "sport": sport,
                "history_limit": limit,
            },
        )
        raise


def _run_flashscore_results_task(
    connection: Connection,
    *,
    batch_id: int,
    target_name: str,
    days_back: int,
) -> dict[str, Any]:
    source = get_source_config("flashscore")
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
            "days_back": days_back,
            "finished_only": True,
            "headless": source.default_headless,
            "settle_ms": source.default_settle_ms,
        },
    )

    try:
        result = fetch_flashscore_scoreboard(
            target.url,
            days_back=days_back,
            finished_only=True,
            timeout_ms=60_000,
            settle_ms=max(source.default_settle_ms, 12_000),
            headless=source.default_headless,
        )
        if result.error:
            raise RuntimeError(result.error)

        parser_fn = FLASHSCORE_RESULTS_PARSERS[target.name]
        normalized_rows = parser_fn(result.html)
        inserted_count = upsert_flashscore_results(connection, run_id=run_id, rows=normalized_rows)
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
                "days_back": days_back,
                "finished_only": True,
                "title": result.title,
                "html_length": result.html_length,
                "page_date_text": getattr(normalized_rows[0], "page_date_text", None) if normalized_rows else None,
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
                "days_back": days_back,
                "finished_only": True,
            },
        )
        raise


def _run_fixture_evaluation_rebuild_task(
    connection: Connection,
    *,
    batch_id: int,
) -> dict[str, Any]:
    """Rebuild the unified fixture evaluation layer after raw ingestion completes."""

    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name="bob",
        target_name="fixture_evaluations",
        source_type="transform",
        status="running",
        started_at=started_at,
        metadata_json={"task": "fixture_evaluations_rebuild"},
    )

    try:
        summary = build_fixture_evaluations(FixtureEvaluationBuildConfig())
        records_found = int(summary.get("rows_upserted") or 0)
        _finalize_source_run(
            connection,
            run_id,
            status="success",
            started_counter=timer_start,
            records_found=records_found,
            warnings_count=0,
            metadata_json=summary,
        )
        return {
            "source_name": "bob",
            "target_name": "fixture_evaluations",
            "status": "success",
            "records_found": records_found,
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
            metadata_json={"task": "fixture_evaluations_rebuild"},
        )
        raise


def _run_fixture_model_feature_rebuild_task(
    connection: Connection,
    *,
    batch_id: int,
) -> dict[str, Any]:
    """Rebuild the transparent model-feature layer after evaluations complete."""

    started_at = datetime.now(UTC)
    timer_start = perf_counter()
    run_id = insert_source_run(
        connection,
        batch_id=batch_id,
        source_name="bob",
        target_name="fixture_model_features",
        source_type="transform",
        status="running",
        started_at=started_at,
        metadata_json={"task": "fixture_model_features_rebuild"},
    )

    try:
        summary = build_fixture_model_features(FixtureModelFeatureBuildConfig())
        records_found = int(summary.get("rows_upserted") or 0)
        _finalize_source_run(
            connection,
            run_id,
            status="success",
            started_counter=timer_start,
            records_found=records_found,
            warnings_count=0,
            metadata_json=summary,
        )
        return {
            "source_name": "bob",
            "target_name": "fixture_model_features",
            "status": "success",
            "records_found": records_found,
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
            metadata_json={"task": "fixture_model_features_rebuild"},
        )
        raise


def build_daily_task_specs(
    connection: Connection,
    *,
    batch_id: int,
    config: DailyIngestionConfig,
) -> list[tuple[str, Callable[[], dict[str, Any]]]]:
    """Return the ordered daily ingestion task list."""

    return [
        ("betika_football", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="betika", target_name="football_today", limit=config.bookmaker_limit)),
        ("betika_basketball", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="betika", target_name="basketball_today", limit=config.bookmaker_limit)),
        ("sportpesa_football", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="sportpesa", target_name="football_today", limit=config.bookmaker_limit)),
        ("sportpesa_basketball", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="sportpesa", target_name="basketball_today", limit=config.bookmaker_limit)),
        ("mozzart_football", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="mozzart", target_name="football_today", limit=config.bookmaker_limit)),
        ("mozzart_basketball", lambda: _run_bookmaker_task(connection, batch_id=batch_id, source_name="mozzart", target_name="basketball_today", limit=config.bookmaker_limit)),
        ("forebet_football", lambda: _run_forebet_task(connection, batch_id=batch_id, target_name="football_today", limit=config.forebet_limit)),
        ("forebet_basketball", lambda: _run_forebet_task(connection, batch_id=batch_id, target_name="basketball_today", limit=config.forebet_limit)),
        ("forebet_football_yesterday_results", lambda: _run_forebet_results_task(connection, batch_id=batch_id, target_name="football_yesterday")),
        ("forebet_basketball_yesterday_results", lambda: _run_forebet_results_task(connection, batch_id=batch_id, target_name="basketball_yesterday")),
        ("forebet_football_history", lambda: _run_forebet_history_enrichment_task(connection, batch_id=batch_id, sport="football", limit=config.forebet_history_limit)),
        ("forebet_basketball_history", lambda: _run_forebet_history_enrichment_task(connection, batch_id=batch_id, sport="basketball", limit=config.forebet_history_limit)),
        ("flashscore_football_yesterday_results", lambda: _run_flashscore_results_task(connection, batch_id=batch_id, target_name="football_yesterday_results", days_back=config.flashscore_days_back)),
        ("flashscore_basketball_yesterday_results", lambda: _run_flashscore_results_task(connection, batch_id=batch_id, target_name="basketball_yesterday_results", days_back=config.flashscore_days_back)),
        ("polymarket_markets", lambda: _run_polymarket_task(connection, batch_id=batch_id, limit=config.polymarket_limit, scan_limit=config.polymarket_scan_limit)),
        ("results_soccer", lambda: _run_results_task(connection, batch_id=batch_id, batch_date=config.batch_date, sport="Soccer", limit=config.results_limit, days_back=config.results_days_back, days_forward=config.results_days_forward)),
        ("results_basketball", lambda: _run_results_task(connection, batch_id=batch_id, batch_date=config.batch_date, sport="Basketball", limit=config.results_limit, days_back=config.results_days_back, days_forward=config.results_days_forward)),
    ]


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
                "forebet_history_limit": config.forebet_history_limit,
                "polymarket_limit": config.polymarket_limit,
                "polymarket_scan_limit": config.polymarket_scan_limit,
                "results_limit": config.results_limit,
                "results_days_back": config.results_days_back,
                "results_days_forward": config.results_days_forward,
                "flashscore_days_back": config.flashscore_days_back,
                "selected_tasks": list(config.selected_tasks or ()),
            },
        )

        tasks = build_daily_task_specs(connection, batch_id=batch_id, config=config)
        if config.selected_tasks:
            selected = set(config.selected_tasks)
            tasks = [(task_name, task_fn) for task_name, task_fn in tasks if task_name in selected]

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

        try:
            evaluation_result = _run_fixture_evaluation_rebuild_task(connection, batch_id=batch_id)
            evaluation_result["task_name"] = "fixture_evaluations_rebuild"
            outcomes.append(evaluation_result)
        except Exception as exc:
            outcomes.append(
                {
                    "task_name": "fixture_evaluations_rebuild",
                    "status": "failed",
                    "records_found": 0,
                    "error": str(exc),
                }
            )

        try:
            model_feature_result = _run_fixture_model_feature_rebuild_task(connection, batch_id=batch_id)
            model_feature_result["task_name"] = "fixture_model_features_rebuild"
            outcomes.append(model_feature_result)
        except Exception as exc:
            outcomes.append(
                {
                    "task_name": "fixture_model_features_rebuild",
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
                "forebet_history_limit": config.forebet_history_limit,
                "polymarket_limit": config.polymarket_limit,
                "polymarket_scan_limit": config.polymarket_scan_limit,
                "results_limit": config.results_limit,
                "results_days_back": config.results_days_back,
                "results_days_forward": config.results_days_forward,
                "flashscore_days_back": config.flashscore_days_back,
                "selected_tasks": list(config.selected_tasks or ()),
                "outcomes": outcomes,
            },
        )

    # Settle pending slips now that fresh results have been ingested
    settlement_summary: dict[str, Any] = {}
    try:
        settlement_summary = settle_slips()
    except Exception as exc:
        settlement_summary = {"error": str(exc)}

    return {
        "batch_id": batch_id,
        "batch_date": config.batch_date.isoformat(),
        "status": final_status,
        "total_sources": total_sources,
        "successful_sources": successful_sources,
        "failed_sources": failed_sources,
        "outcomes": outcomes,
        "settlement": settlement_summary,
    }
