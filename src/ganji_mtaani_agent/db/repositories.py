from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Sequence

from psycopg import Connection
from psycopg.types.json import Jsonb

from ganji_mtaani_agent.models.thesportsdb import TheSportsDBEventResult


# =============================================================================
# Shared Conversion Helpers
# =============================================================================
def _as_record_dict(record: Any) -> dict[str, Any]:
    """Convert a dataclass or dict-like record into a plain dictionary."""

    if is_dataclass(record):
        return asdict(record)
    if isinstance(record, dict):
        return dict(record)
    raise TypeError(f"Unsupported record type: {type(record)!r}")


def _to_date(value: str | date | None) -> date | None:
    """Convert an ISO date string to a date object when possible."""

    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _infer_market_type(source_name: str, sport: str, row: dict[str, Any]) -> str | None:
    """Infer a readable market label when the source model does not provide one."""

    explicit_value = row.get("market_type")
    if explicit_value:
        return str(explicit_value)

    if source_name == "sportpesa" and sport == "football":
        return "multi_market_snapshot"
    if source_name == "sportpesa" and sport == "basketball":
        return "winner_incl_ot"
    if source_name == "betika" and sport == "football":
        return "1x2"
    if source_name == "betika" and sport == "basketball":
        return "winner_snapshot"
    if source_name == "mozzart" and sport == "football":
        return "1x2_live"
    if source_name == "mozzart" and sport == "basketball":
        return "winner_live"
    return None


# =============================================================================
# Source Run Repository
# =============================================================================
def insert_source_run(
    connection: Connection,
    *,
    source_name: str,
    target_name: str | None,
    source_type: str,
    status: str,
    started_at: datetime,
    batch_id: int | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> int:
    """Insert a new source run row and return its generated id."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO source_runs (
                batch_id,
                source_name,
                target_name,
                source_type,
                status,
                started_at,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                batch_id,
                source_name,
                target_name,
                source_type,
                status,
                started_at,
                Jsonb(metadata_json or {}),
            ),
        )
        return int(cursor.fetchone()[0])


def insert_ingestion_batch(
    connection: Connection,
    *,
    batch_name: str,
    batch_date: date,
    status: str,
    started_at: datetime,
    triggered_by: str | None = None,
    notes: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> int:
    """Insert a new ingestion batch row and return its generated id."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_batches (
                batch_name,
                batch_date,
                status,
                started_at,
                triggered_by,
                notes,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                batch_name,
                batch_date,
                status,
                started_at,
                triggered_by,
                notes,
                Jsonb(metadata_json or {}),
            ),
        )
        return int(cursor.fetchone()[0])


def update_ingestion_batch(
    connection: Connection,
    batch_id: int,
    *,
    status: str,
    finished_at: datetime | None = None,
    total_sources: int | None = None,
    successful_sources: int | None = None,
    failed_sources: int | None = None,
    notes: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    """Update the final status fields for an ingestion batch row."""

    metadata_payload = Jsonb(metadata_json) if metadata_json is not None else None

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_batches
            SET
                status = %s,
                finished_at = COALESCE(%s, finished_at),
                total_sources = COALESCE(%s, total_sources),
                successful_sources = COALESCE(%s, successful_sources),
                failed_sources = COALESCE(%s, failed_sources),
                notes = COALESCE(%s, notes),
                metadata_json = CASE
                    WHEN %s IS NULL THEN metadata_json
                    ELSE %s
                END
            WHERE id = %s
            """,
            (
                status,
                finished_at,
                total_sources,
                successful_sources,
                failed_sources,
                notes,
                metadata_payload,
                metadata_payload,
                batch_id,
            ),
        )


def update_source_run(
    connection: Connection,
    run_id: int,
    *,
    status: str,
    finished_at: datetime | None = None,
    duration_ms: int | None = None,
    records_found: int | None = None,
    warnings_count: int | None = None,
    error_message: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    """Update the final outcome fields for an existing source run row."""

    metadata_payload = Jsonb(metadata_json) if metadata_json is not None else None

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE source_runs
            SET
                status = %s,
                finished_at = COALESCE(%s, finished_at),
                duration_ms = COALESCE(%s, duration_ms),
                records_found = COALESCE(%s, records_found),
                warnings_count = COALESCE(%s, warnings_count),
                error_message = %s,
                metadata_json = CASE
                    WHEN %s IS NULL THEN metadata_json
                    ELSE %s
                END
            WHERE id = %s
            """,
            (
                status,
                finished_at,
                duration_ms,
                records_found,
                warnings_count,
                error_message,
                metadata_payload,
                metadata_payload,
                run_id,
            ),
        )


# =============================================================================
# Bookmaker Odds Repository
# =============================================================================
def insert_bookmaker_odds(
    connection: Connection,
    *,
    run_id: int,
    rows: Sequence[Any],
) -> int:
    """Insert normalized bookmaker rows into the shared bookmaker table."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        source_name = str(record["source"])
        sport = str(record["sport"])
        prepared_rows.append(
            (
                run_id,
                source_name,
                sport,
                record.get("league"),
                record.get("event_datetime_text") or record.get("event_datetime"),
                None,
                record.get("home_team"),
                record.get("away_team"),
                str(record.get("game_id")) if record.get("game_id") not in (None, "") else None,
                record.get("match_status"),
                record.get("score_text"),
                _infer_market_type(source_name, sport, record),
                record.get("home_odds"),
                record.get("draw_odds"),
                record.get("away_odds"),
                record.get("home_or_draw_odds"),
                record.get("draw_or_away_odds"),
                record.get("home_or_away_odds"),
                record.get("over_2_5_odds"),
                record.get("under_2_5_odds"),
                record.get("btts_yes_odds"),
                record.get("btts_no_odds"),
                record.get("extra_market_count"),
                record.get("raw_text"),
                record.get("confidence"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO bookmaker_odds (
                run_id,
                source_name,
                sport,
                league,
                event_datetime_text,
                event_datetime_utc,
                home_team,
                away_team,
                game_id,
                match_status,
                score_text,
                market_type,
                home_odds,
                draw_odds,
                away_odds,
                home_or_draw_odds,
                draw_or_away_odds,
                home_or_away_odds,
                over_2_5_odds,
                under_2_5_odds,
                btts_yes_odds,
                btts_no_odds,
                extra_market_count,
                raw_text,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            prepared_rows,
        )

    return len(prepared_rows)


# =============================================================================
# Sports Results Repository
# =============================================================================
def upsert_sports_results(
    connection: Connection,
    *,
    run_id: int,
    rows: Sequence[TheSportsDBEventResult],
) -> int:
    """Insert or update TheSportsDB event results in the sports_results table."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        prepared_rows.append(
            (
                run_id,
                record.get("source"),
                record.get("sport"),
                record.get("event_id"),
                record.get("league_id"),
                record.get("league"),
                record.get("season"),
                record.get("event_name"),
                _to_date(record.get("event_date")),
                record.get("event_time"),
                None,
                record.get("home_team_id"),
                record.get("away_team_id"),
                record.get("home_team"),
                record.get("away_team"),
                record.get("home_score"),
                record.get("away_score"),
                record.get("status"),
                record.get("progress"),
                record.get("venue"),
                record.get("winner"),
                Jsonb(record.get("raw_record") or {}),
                record.get("confidence"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO sports_results (
                run_id,
                source_name,
                sport,
                event_id,
                league_id,
                league,
                season,
                event_name,
                event_date,
                event_time,
                event_datetime_utc,
                home_team_id,
                away_team_id,
                home_team,
                away_team,
                home_score,
                away_score,
                status,
                progress,
                venue,
                winner,
                raw_record_json,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, event_id)
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                sport = EXCLUDED.sport,
                league_id = EXCLUDED.league_id,
                league = EXCLUDED.league,
                season = EXCLUDED.season,
                event_name = EXCLUDED.event_name,
                event_date = EXCLUDED.event_date,
                event_time = EXCLUDED.event_time,
                event_datetime_utc = EXCLUDED.event_datetime_utc,
                home_team_id = EXCLUDED.home_team_id,
                away_team_id = EXCLUDED.away_team_id,
                home_team = EXCLUDED.home_team,
                away_team = EXCLUDED.away_team,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                status = EXCLUDED.status,
                progress = EXCLUDED.progress,
                venue = EXCLUDED.venue,
                winner = EXCLUDED.winner,
                raw_record_json = EXCLUDED.raw_record_json,
                confidence = EXCLUDED.confidence
            """,
            prepared_rows,
        )

    return len(prepared_rows)


# =============================================================================
# Forebet Prediction Repository
# =============================================================================
def insert_forebet_predictions(
    connection: Connection,
    *,
    run_id: int,
    rows: Sequence[Any],
) -> int:
    """Insert normalized Forebet prediction rows into the shared predictions table."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        prepared_rows.append(
            (
                run_id,
                record.get("source"),
                record.get("sport"),
                record.get("league"),
                record.get("home_team"),
                record.get("away_team"),
                record.get("event_datetime"),
                record.get("prob_1"),
                record.get("prob_x"),
                record.get("prob_2"),
                record.get("pred_outcome"),
                record.get("predicted_home_score"),
                record.get("predicted_away_score"),
                record.get("correct_score_text"),
                record.get("avg_goals"),
                record.get("avg_points"),
                record.get("weather"),
                record.get("coef_1"),
                record.get("coef_x"),
                record.get("coef_2"),
                record.get("coef_3"),
                record.get("coef_extra"),
                Jsonb(record.get("remaining_tokens") or []),
                record.get("raw_text"),
                record.get("confidence"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO forebet_predictions (
                run_id,
                source_name,
                sport,
                league,
                home_team,
                away_team,
                event_datetime_text,
                prob_1,
                prob_x,
                prob_2,
                pred_outcome,
                predicted_home_score,
                predicted_away_score,
                correct_score_text,
                avg_goals,
                avg_points,
                weather,
                coef_1,
                coef_x,
                coef_2,
                coef_3,
                coef_extra,
                remaining_tokens_json,
                raw_text,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            prepared_rows,
        )

    return len(prepared_rows)


# =============================================================================
# Forebet Results Repository
# =============================================================================
def upsert_forebet_results(
    connection: Connection,
    *,
    run_id: int,
    rows: Sequence[Any],
) -> int:
    """Insert or update finished Forebet result rows."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        prepared_rows.append(
            (
                run_id,
                record.get("source"),
                record.get("sport"),
                record.get("league"),
                record.get("home_team"),
                record.get("away_team"),
                record.get("event_datetime"),
                record.get("prob_1"),
                record.get("prob_x"),
                record.get("prob_2"),
                record.get("pred_outcome"),
                record.get("predicted_home_score"),
                record.get("predicted_away_score"),
                record.get("predicted_score_text"),
                record.get("actual_home_score"),
                record.get("actual_away_score"),
                record.get("actual_score_text"),
                record.get("actual_outcome"),
                record.get("status"),
                record.get("pred_hit"),
                record.get("pred_indicator_class"),
                record.get("raw_text"),
                record.get("confidence"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO forebet_results (
                run_id,
                source_name,
                sport,
                league,
                home_team,
                away_team,
                event_datetime_text,
                prob_1,
                prob_x,
                prob_2,
                pred_outcome,
                predicted_home_score,
                predicted_away_score,
                predicted_score_text,
                actual_home_score,
                actual_away_score,
                actual_score_text,
                actual_outcome,
                status,
                pred_hit,
                pred_indicator_class,
                raw_text,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, sport, event_datetime_text, home_team, away_team)
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                league = EXCLUDED.league,
                prob_1 = EXCLUDED.prob_1,
                prob_x = EXCLUDED.prob_x,
                prob_2 = EXCLUDED.prob_2,
                pred_outcome = EXCLUDED.pred_outcome,
                predicted_home_score = EXCLUDED.predicted_home_score,
                predicted_away_score = EXCLUDED.predicted_away_score,
                predicted_score_text = EXCLUDED.predicted_score_text,
                actual_home_score = EXCLUDED.actual_home_score,
                actual_away_score = EXCLUDED.actual_away_score,
                actual_score_text = EXCLUDED.actual_score_text,
                actual_outcome = EXCLUDED.actual_outcome,
                status = EXCLUDED.status,
                pred_hit = EXCLUDED.pred_hit,
                pred_indicator_class = EXCLUDED.pred_indicator_class,
                raw_text = EXCLUDED.raw_text,
                confidence = EXCLUDED.confidence
            """,
            prepared_rows,
        )

    return len(prepared_rows)


# =============================================================================
# Polymarket Market Repository
# =============================================================================
def upsert_polymarket_markets(
    connection: Connection,
    *,
    run_id: int,
    rows: Sequence[Any],
) -> int:
    """Insert or update normalized Polymarket market rows."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        prepared_rows.append(
            (
                run_id,
                record.get("source"),
                record.get("market_id"),
                record.get("event_id"),
                record.get("question"),
                record.get("slug"),
                record.get("category"),
                record.get("subcategory"),
                Jsonb(record.get("tags") or []),
                record.get("description"),
                record.get("start_date"),
                record.get("end_date"),
                record.get("active"),
                record.get("closed"),
                record.get("archived"),
                Jsonb(record.get("outcomes") or []),
                Jsonb(record.get("outcome_prices") or []),
                record.get("liquidity"),
                record.get("volume"),
                record.get("open_interest"),
                record.get("market_type"),
                Jsonb(record.get("raw_record") or {}),
                record.get("confidence"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO polymarket_markets (
                run_id,
                source_name,
                market_id,
                event_id,
                question,
                slug,
                category,
                subcategory,
                tags_json,
                description,
                start_date,
                end_date,
                active,
                closed,
                archived,
                outcomes_json,
                outcome_prices_json,
                liquidity,
                volume,
                open_interest,
                market_type,
                raw_record_json,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, market_id)
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                event_id = EXCLUDED.event_id,
                question = EXCLUDED.question,
                slug = EXCLUDED.slug,
                category = EXCLUDED.category,
                subcategory = EXCLUDED.subcategory,
                tags_json = EXCLUDED.tags_json,
                description = EXCLUDED.description,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                active = EXCLUDED.active,
                closed = EXCLUDED.closed,
                archived = EXCLUDED.archived,
                outcomes_json = EXCLUDED.outcomes_json,
                outcome_prices_json = EXCLUDED.outcome_prices_json,
                liquidity = EXCLUDED.liquidity,
                volume = EXCLUDED.volume,
                open_interest = EXCLUDED.open_interest,
                market_type = EXCLUDED.market_type,
                raw_record_json = EXCLUDED.raw_record_json,
                confidence = EXCLUDED.confidence
            """,
            prepared_rows,
        )

    return len(prepared_rows)
