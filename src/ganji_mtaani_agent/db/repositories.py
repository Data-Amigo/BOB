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
    metadata_json: dict[str, Any] | None = None,
) -> int:
    """Insert a new source run row and return its generated id."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO source_runs (
                source_name,
                target_name,
                source_type,
                status,
                started_at,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                source_name,
                target_name,
                source_type,
                status,
                started_at,
                Jsonb(metadata_json or {}),
            ),
        )
        return int(cursor.fetchone()[0])


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
