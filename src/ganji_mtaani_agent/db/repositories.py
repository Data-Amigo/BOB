from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Sequence

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct
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
                record.get("match_url"),
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
                match_url,
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
                %s, %s, %s, %s, %s, %s
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
                record.get("match_url"),
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
                match_url,
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
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, sport, event_datetime_text, home_team, away_team)
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                league = EXCLUDED.league,
                match_url = EXCLUDED.match_url,
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
# Flashscore Results Repository
# =============================================================================
def upsert_flashscore_results(
    connection: Connection,
    *,
    run_id: int,
    rows: Sequence[Any],
) -> int:
    """Insert or update finished Flashscore result rows."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        prepared_rows.append(
            (
                run_id,
                record.get("source"),
                record.get("sport"),
                record.get("page_date_text"),
                record.get("country_or_region"),
                record.get("league"),
                record.get("match_status"),
                record.get("event_time_text"),
                record.get("home_team"),
                record.get("away_team"),
                record.get("home_score"),
                record.get("away_score"),
                record.get("raw_text"),
                record.get("confidence"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO flashscore_results (
                run_id,
                source_name,
                sport,
                page_date_text,
                country_or_region,
                league,
                match_status,
                event_time_text,
                home_team,
                away_team,
                home_score,
                away_score,
                raw_text,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, sport, page_date_text, league, home_team, away_team, event_time_text)
            DO UPDATE SET
                run_id = EXCLUDED.run_id,
                country_or_region = EXCLUDED.country_or_region,
                match_status = EXCLUDED.match_status,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                raw_text = EXCLUDED.raw_text,
                confidence = EXCLUDED.confidence
            """,
            prepared_rows,
        )

    return len(prepared_rows)


# =============================================================================
# Forebet Historical Analysis Repository
# =============================================================================
def upsert_forebet_match_analysis(
    connection: Connection,
    *,
    analysis: Any,
) -> int:
    """Insert or update one Forebet match-analysis summary row."""

    record = _as_record_dict(analysis)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO forebet_match_analyses (
                source_name,
                sport,
                match_url,
                competition,
                league_code,
                event_datetime_text,
                home_team,
                away_team,
                pred_outcome,
                predicted_score_text,
                actual_score_text,
                actual_status,
                home_form_sequence,
                away_form_sequence,
                confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, sport, match_url)
            DO UPDATE SET
                competition = EXCLUDED.competition,
                league_code = EXCLUDED.league_code,
                event_datetime_text = EXCLUDED.event_datetime_text,
                home_team = EXCLUDED.home_team,
                away_team = EXCLUDED.away_team,
                pred_outcome = EXCLUDED.pred_outcome,
                predicted_score_text = EXCLUDED.predicted_score_text,
                actual_score_text = EXCLUDED.actual_score_text,
                actual_status = EXCLUDED.actual_status,
                home_form_sequence = EXCLUDED.home_form_sequence,
                away_form_sequence = EXCLUDED.away_form_sequence,
                confidence = EXCLUDED.confidence,
                scraped_at = NOW()
            RETURNING id
            """,
            (
                record.get("source"),
                record.get("sport"),
                record.get("match_url"),
                record.get("competition"),
                record.get("league_code"),
                record.get("event_datetime"),
                record.get("home_team"),
                record.get("away_team"),
                record.get("pred_outcome"),
                record.get("predicted_score_text"),
                record.get("actual_score_text"),
                record.get("actual_status"),
                record.get("home_form_sequence"),
                record.get("away_form_sequence"),
                record.get("confidence"),
            ),
        )
        return int(cursor.fetchone()[0])


def upsert_forebet_match_history_rows(
    connection: Connection,
    *,
    rows: Sequence[Any],
) -> int:
    """Insert or update structured historical rows from Forebet detail pages."""

    prepared_rows: list[tuple[Any, ...]] = []

    for row in rows:
        record = _as_record_dict(row)
        prepared_rows.append(
            (
                record.get("source"),
                record.get("sport"),
                record.get("match_url"),
                record.get("section_name"),
                record.get("section_team"),
                record.get("sequence_no"),
                record.get("event_date_text"),
                record.get("competition_tag"),
                record.get("home_team"),
                record.get("away_team"),
                record.get("score_text"),
                record.get("extra_score_text"),
                record.get("result_outcome"),
                record.get("result_class"),
                record.get("active_side"),
                record.get("detail_url"),
                record.get("raw_text"),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO forebet_match_history_rows (
                source_name,
                sport,
                match_url,
                section_name,
                section_team,
                sequence_no,
                event_date_text,
                competition_tag,
                home_team,
                away_team,
                score_text,
                extra_score_text,
                result_outcome,
                result_class,
                active_side,
                detail_url,
                raw_text
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_name, sport, match_url, section_name, section_team, sequence_no)
            DO UPDATE SET
                event_date_text = EXCLUDED.event_date_text,
                competition_tag = EXCLUDED.competition_tag,
                home_team = EXCLUDED.home_team,
                away_team = EXCLUDED.away_team,
                score_text = EXCLUDED.score_text,
                extra_score_text = EXCLUDED.extra_score_text,
                result_outcome = EXCLUDED.result_outcome,
                result_class = EXCLUDED.result_class,
                active_side = EXCLUDED.active_side,
                detail_url = EXCLUDED.detail_url,
                raw_text = EXCLUDED.raw_text,
                scraped_at = NOW()
            """,
            prepared_rows,
        )

    return len(prepared_rows)


def fetch_forebet_history_candidates(
    connection: Connection,
    *,
    sport: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return Forebet match URLs that still need automatic historical enrichment."""

    sql = """
        WITH candidate_rows AS (
            SELECT
                sport,
                match_url,
                event_datetime_text,
                home_team,
                away_team,
                created_at
            FROM forebet_predictions
            WHERE sport = %s
              AND match_url IS NOT NULL

            UNION ALL

            SELECT
                sport,
                match_url,
                event_datetime_text,
                home_team,
                away_team,
                created_at
            FROM forebet_results
            WHERE sport = %s
              AND match_url IS NOT NULL
        )
        SELECT
            candidates.sport,
            candidates.match_url,
            MAX(candidates.event_datetime_text) AS event_datetime_text,
            MAX(candidates.home_team) AS home_team,
            MAX(candidates.away_team) AS away_team,
            MAX(candidates.created_at) AS latest_seen_at
        FROM candidate_rows AS candidates
        LEFT JOIN forebet_match_analyses AS analyses
            ON analyses.source_name = 'forebet'
           AND analyses.sport = candidates.sport
           AND analyses.match_url = candidates.match_url
        WHERE analyses.id IS NULL
        GROUP BY candidates.sport, candidates.match_url
        ORDER BY MAX(candidates.created_at) DESC, MAX(candidates.event_datetime_text) DESC NULLS LAST
    """

    params: list[Any] = [sport, sport]
    if limit is not None and limit > 0:
        sql += "\nLIMIT %s"
        params.append(limit)

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def upsert_canonical_fixture(
    connection: Connection,
    *,
    sport: str,
    canonical_league: str | None,
    canonical_home_team: str,
    canonical_away_team: str,
    canonical_event_date: date,
    canonical_event_datetime_utc: datetime | None = None,
    canonical_event_datetime_text: str | None = None,
    canonical_event_time_text: str | None = None,
    canonical_status: str | None = None,
    result_home_score: int | None = None,
    result_away_score: int | None = None,
    primary_result_source: str | None = None,
    confidence: float = 1.0,
) -> int:
    """Insert or update one canonical fixture row and return its id."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO canonical_fixtures (
                sport,
                canonical_league,
                canonical_home_team,
                canonical_away_team,
                canonical_event_date,
                canonical_event_datetime_utc,
                canonical_event_datetime_text,
                canonical_event_time_text,
                canonical_status,
                result_home_score,
                result_away_score,
                primary_result_source,
                confidence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sport, canonical_event_date, canonical_home_team, canonical_away_team)
            DO UPDATE SET
                canonical_league = COALESCE(EXCLUDED.canonical_league, canonical_fixtures.canonical_league),
                canonical_event_datetime_utc = COALESCE(EXCLUDED.canonical_event_datetime_utc, canonical_fixtures.canonical_event_datetime_utc),
                canonical_event_datetime_text = COALESCE(EXCLUDED.canonical_event_datetime_text, canonical_fixtures.canonical_event_datetime_text),
                canonical_event_time_text = COALESCE(EXCLUDED.canonical_event_time_text, canonical_fixtures.canonical_event_time_text),
                canonical_status = COALESCE(EXCLUDED.canonical_status, canonical_fixtures.canonical_status),
                result_home_score = COALESCE(EXCLUDED.result_home_score, canonical_fixtures.result_home_score),
                result_away_score = COALESCE(EXCLUDED.result_away_score, canonical_fixtures.result_away_score),
                primary_result_source = COALESCE(EXCLUDED.primary_result_source, canonical_fixtures.primary_result_source),
                confidence = GREATEST(EXCLUDED.confidence, canonical_fixtures.confidence),
                updated_at = NOW()
            RETURNING id
            """,
            (
                sport,
                canonical_league,
                canonical_home_team,
                canonical_away_team,
                canonical_event_date,
                canonical_event_datetime_utc,
                canonical_event_datetime_text,
                canonical_event_time_text,
                canonical_status,
                result_home_score,
                result_away_score,
                primary_result_source,
                confidence,
            ),
        )
        return int(cursor.fetchone()[0])


def upsert_fixture_source_links(
    connection: Connection,
    *,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Insert or update raw-source-to-canonical-fixture links."""

    prepared_rows: list[tuple[Any, ...]] = []
    for row in rows:
        prepared_rows.append(
            (
                row["fixture_id"],
                row["source_name"],
                row["source_table"],
                row["source_row_id"],
                row.get("source_run_id"),
                row.get("source_match_url"),
                row["source_sport"],
                row.get("source_league"),
                row["source_home_team"],
                row["source_away_team"],
                row.get("source_event_date"),
                row.get("source_event_datetime_text"),
                row.get("source_event_time_text"),
                row["link_method"],
                row.get("link_confidence", 1.0),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO fixture_source_links (
                fixture_id,
                source_name,
                source_table,
                source_row_id,
                source_run_id,
                source_match_url,
                source_sport,
                source_league,
                source_home_team,
                source_away_team,
                source_event_date,
                source_event_datetime_text,
                source_event_time_text,
                link_method,
                link_confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (source_table, source_row_id)
            DO UPDATE SET
                fixture_id = EXCLUDED.fixture_id,
                source_name = EXCLUDED.source_name,
                source_run_id = EXCLUDED.source_run_id,
                source_match_url = EXCLUDED.source_match_url,
                source_sport = EXCLUDED.source_sport,
                source_league = EXCLUDED.source_league,
                source_home_team = EXCLUDED.source_home_team,
                source_away_team = EXCLUDED.source_away_team,
                source_event_date = EXCLUDED.source_event_date,
                source_event_datetime_text = EXCLUDED.source_event_datetime_text,
                source_event_time_text = EXCLUDED.source_event_time_text,
                link_method = EXCLUDED.link_method,
                link_confidence = EXCLUDED.link_confidence
            """,
            prepared_rows,
        )

    return len(prepared_rows)


def upsert_fixture_evaluations(
    connection: Connection,
    *,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Insert or update unified fixture evaluation rows."""

    prepared_rows: list[tuple[Any, ...]] = []
    for row in rows:
        prepared_rows.append(
            (
                row.get("canonical_fixture_id"),
                row["sport"],
                row["event_date"],
                row["normalized_home_team"],
                row["normalized_away_team"],
                row.get("display_home_team"),
                row.get("display_away_team"),
                row.get("display_league"),
                row.get("prediction_source"),
                row.get("prediction_row_id"),
                row.get("prediction_match_url"),
                row.get("pred_outcome"),
                row.get("pred_probability"),
                row.get("predicted_home_score"),
                row.get("predicted_away_score"),
                row.get("result_source_used"),
                row.get("result_row_id"),
                row.get("actual_home_score"),
                row.get("actual_away_score"),
                row.get("actual_outcome"),
                row.get("pred_hit"),
                row.get("bookmaker_row_count", 0),
                Jsonb(row.get("bookmaker_sources_json") or []),
                Jsonb(row.get("available_sources_json") or []),
                row["evaluation_status"],
                row.get("evaluation_confidence", 1.0),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO fixture_evaluations (
                canonical_fixture_id,
                sport,
                event_date,
                normalized_home_team,
                normalized_away_team,
                display_home_team,
                display_away_team,
                display_league,
                prediction_source,
                prediction_row_id,
                prediction_match_url,
                pred_outcome,
                pred_probability,
                predicted_home_score,
                predicted_away_score,
                result_source_used,
                result_row_id,
                actual_home_score,
                actual_away_score,
                actual_outcome,
                pred_hit,
                bookmaker_row_count,
                bookmaker_sources_json,
                available_sources_json,
                evaluation_status,
                evaluation_confidence
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (sport, event_date, normalized_home_team, normalized_away_team)
            DO UPDATE SET
                canonical_fixture_id = COALESCE(EXCLUDED.canonical_fixture_id, fixture_evaluations.canonical_fixture_id),
                display_home_team = COALESCE(EXCLUDED.display_home_team, fixture_evaluations.display_home_team),
                display_away_team = COALESCE(EXCLUDED.display_away_team, fixture_evaluations.display_away_team),
                display_league = COALESCE(EXCLUDED.display_league, fixture_evaluations.display_league),
                prediction_source = COALESCE(EXCLUDED.prediction_source, fixture_evaluations.prediction_source),
                prediction_row_id = COALESCE(EXCLUDED.prediction_row_id, fixture_evaluations.prediction_row_id),
                prediction_match_url = COALESCE(EXCLUDED.prediction_match_url, fixture_evaluations.prediction_match_url),
                pred_outcome = COALESCE(EXCLUDED.pred_outcome, fixture_evaluations.pred_outcome),
                pred_probability = COALESCE(EXCLUDED.pred_probability, fixture_evaluations.pred_probability),
                predicted_home_score = COALESCE(EXCLUDED.predicted_home_score, fixture_evaluations.predicted_home_score),
                predicted_away_score = COALESCE(EXCLUDED.predicted_away_score, fixture_evaluations.predicted_away_score),
                result_source_used = COALESCE(EXCLUDED.result_source_used, fixture_evaluations.result_source_used),
                result_row_id = COALESCE(EXCLUDED.result_row_id, fixture_evaluations.result_row_id),
                actual_home_score = COALESCE(EXCLUDED.actual_home_score, fixture_evaluations.actual_home_score),
                actual_away_score = COALESCE(EXCLUDED.actual_away_score, fixture_evaluations.actual_away_score),
                actual_outcome = COALESCE(EXCLUDED.actual_outcome, fixture_evaluations.actual_outcome),
                pred_hit = COALESCE(EXCLUDED.pred_hit, fixture_evaluations.pred_hit),
                bookmaker_row_count = EXCLUDED.bookmaker_row_count,
                bookmaker_sources_json = EXCLUDED.bookmaker_sources_json,
                available_sources_json = EXCLUDED.available_sources_json,
                evaluation_status = EXCLUDED.evaluation_status,
                evaluation_confidence = EXCLUDED.evaluation_confidence,
                updated_at = NOW()
            """,
            prepared_rows,
        )

    return len(prepared_rows)


def upsert_fixture_model_features(
    connection: Connection,
    *,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Insert or update transparent model feature rows built from history."""

    prepared_rows: list[tuple[Any, ...]] = []
    for row in rows:
        prepared_rows.append(
            (
                row["evaluation_id"],
                row.get("canonical_fixture_id"),
                row["sport"],
                row["event_date"],
                row["normalized_home_team"],
                row["normalized_away_team"],
                row.get("display_home_team"),
                row.get("display_away_team"),
                row.get("display_league"),
                row.get("prediction_source"),
                row.get("prediction_match_url"),
                row.get("pred_outcome"),
                row.get("pred_probability"),
                row.get("actual_outcome"),
                row.get("pred_hit"),
                row.get("home_overall_matches_used", 0),
                row.get("away_overall_matches_used", 0),
                row.get("home_home_matches_used", 0),
                row.get("away_away_matches_used", 0),
                row.get("home_overall_points_5", 0.0),
                row.get("away_overall_points_5", 0.0),
                row.get("home_home_points_5", 0.0),
                row.get("away_away_points_5", 0.0),
                row.get("home_overall_form_5", 0.0),
                row.get("away_overall_form_5", 0.0),
                row.get("home_home_form_5", 0.0),
                row.get("away_away_form_5", 0.0),
                row.get("overall_form_edge_5", 0.0),
                row.get("venue_form_edge_5", 0.0),
                row.get("home_prev_matches", 0),
                row.get("home_prev_wins", 0),
                row.get("home_prev_draws", 0),
                row.get("home_prev_losses", 0),
                row.get("home_prev_win_pct", 0.0),
                row.get("home_prev_draw_pct", 0.0),
                row.get("home_prev_loss_pct", 0.0),
                row.get("away_prev_matches", 0),
                row.get("away_prev_wins", 0),
                row.get("away_prev_draws", 0),
                row.get("away_prev_losses", 0),
                row.get("away_prev_win_pct", 0.0),
                row.get("away_prev_draw_pct", 0.0),
                row.get("away_prev_loss_pct", 0.0),
                row.get("predicted_side_form_5"),
                row.get("opponent_side_form_5"),
                row.get("model_confidence_v1"),
                row.get("history_coverage_pct", 0.0),
            )
        )

    if not prepared_rows:
        return 0

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO fixture_model_features (
                evaluation_id,
                canonical_fixture_id,
                sport,
                event_date,
                normalized_home_team,
                normalized_away_team,
                display_home_team,
                display_away_team,
                display_league,
                prediction_source,
                prediction_match_url,
                pred_outcome,
                pred_probability,
                actual_outcome,
                pred_hit,
                home_overall_matches_used,
                away_overall_matches_used,
                home_home_matches_used,
                away_away_matches_used,
                home_overall_points_5,
                away_overall_points_5,
                home_home_points_5,
                away_away_points_5,
                home_overall_form_5,
                away_overall_form_5,
                home_home_form_5,
                away_away_form_5,
                overall_form_edge_5,
                venue_form_edge_5,
                home_prev_matches,
                home_prev_wins,
                home_prev_draws,
                home_prev_losses,
                home_prev_win_pct,
                home_prev_draw_pct,
                home_prev_loss_pct,
                away_prev_matches,
                away_prev_wins,
                away_prev_draws,
                away_prev_losses,
                away_prev_win_pct,
                away_prev_draw_pct,
                away_prev_loss_pct,
                predicted_side_form_5,
                opponent_side_form_5,
                model_confidence_v1,
                history_coverage_pct
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (evaluation_id)
            DO UPDATE SET
                canonical_fixture_id = COALESCE(EXCLUDED.canonical_fixture_id, fixture_model_features.canonical_fixture_id),
                sport = EXCLUDED.sport,
                event_date = EXCLUDED.event_date,
                normalized_home_team = EXCLUDED.normalized_home_team,
                normalized_away_team = EXCLUDED.normalized_away_team,
                display_home_team = COALESCE(EXCLUDED.display_home_team, fixture_model_features.display_home_team),
                display_away_team = COALESCE(EXCLUDED.display_away_team, fixture_model_features.display_away_team),
                display_league = COALESCE(EXCLUDED.display_league, fixture_model_features.display_league),
                prediction_source = COALESCE(EXCLUDED.prediction_source, fixture_model_features.prediction_source),
                prediction_match_url = COALESCE(EXCLUDED.prediction_match_url, fixture_model_features.prediction_match_url),
                pred_outcome = COALESCE(EXCLUDED.pred_outcome, fixture_model_features.pred_outcome),
                pred_probability = COALESCE(EXCLUDED.pred_probability, fixture_model_features.pred_probability),
                actual_outcome = COALESCE(EXCLUDED.actual_outcome, fixture_model_features.actual_outcome),
                pred_hit = COALESCE(EXCLUDED.pred_hit, fixture_model_features.pred_hit),
                home_overall_matches_used = EXCLUDED.home_overall_matches_used,
                away_overall_matches_used = EXCLUDED.away_overall_matches_used,
                home_home_matches_used = EXCLUDED.home_home_matches_used,
                away_away_matches_used = EXCLUDED.away_away_matches_used,
                home_overall_points_5 = EXCLUDED.home_overall_points_5,
                away_overall_points_5 = EXCLUDED.away_overall_points_5,
                home_home_points_5 = EXCLUDED.home_home_points_5,
                away_away_points_5 = EXCLUDED.away_away_points_5,
                home_overall_form_5 = EXCLUDED.home_overall_form_5,
                away_overall_form_5 = EXCLUDED.away_overall_form_5,
                home_home_form_5 = EXCLUDED.home_home_form_5,
                away_away_form_5 = EXCLUDED.away_away_form_5,
                overall_form_edge_5 = EXCLUDED.overall_form_edge_5,
                venue_form_edge_5 = EXCLUDED.venue_form_edge_5,
                home_prev_matches = EXCLUDED.home_prev_matches,
                home_prev_wins = EXCLUDED.home_prev_wins,
                home_prev_draws = EXCLUDED.home_prev_draws,
                home_prev_losses = EXCLUDED.home_prev_losses,
                home_prev_win_pct = EXCLUDED.home_prev_win_pct,
                home_prev_draw_pct = EXCLUDED.home_prev_draw_pct,
                home_prev_loss_pct = EXCLUDED.home_prev_loss_pct,
                away_prev_matches = EXCLUDED.away_prev_matches,
                away_prev_wins = EXCLUDED.away_prev_wins,
                away_prev_draws = EXCLUDED.away_prev_draws,
                away_prev_losses = EXCLUDED.away_prev_losses,
                away_prev_win_pct = EXCLUDED.away_prev_win_pct,
                away_prev_draw_pct = EXCLUDED.away_prev_draw_pct,
                away_prev_loss_pct = EXCLUDED.away_prev_loss_pct,
                predicted_side_form_5 = EXCLUDED.predicted_side_form_5,
                opponent_side_form_5 = EXCLUDED.opponent_side_form_5,
                model_confidence_v1 = EXCLUDED.model_confidence_v1,
                history_coverage_pct = EXCLUDED.history_coverage_pct,
                updated_at = NOW()
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


# =============================================================================
# Insurance Products Repository
# =============================================================================
def upsert_insurance_products(
    connection: Connection,
    products: Sequence[InsuranceProduct],
) -> int:
    """Insert or update insurance products scraped from an insurer's website.

    Uses (insurer_slug, product_url) as the conflict key so re-running the
    scraper refreshes existing products rather than inserting duplicates.

    Returns the number of rows processed.
    """
    from datetime import UTC, datetime

    if not products:
        return 0

    scraped_at = datetime.now(UTC)
    prepared_rows: list[tuple[Any, ...]] = []

    for p in products:
        prepared_rows.append((
            p.insurer_name,
            p.insurer_slug,
            p.product_name,
            p.product_type,
            p.product_url,
            p.description,
            p.tagline,
            p.target_audience,
            p.premium_min_kes,
            p.premium_max_kes,
            p.premium_frequency,
            p.premium_notes,
            p.coverage_min_kes,
            p.coverage_max_kes,
            p.coverage_notes,
            p.min_age,
            p.max_age,
            p.eligibility_notes,
            Jsonb(p.key_benefits),
            Jsonb(p.exclusions),
            p.waiting_period,
            p.claims_process,
            p.how_to_apply,
            p.contact_phone,
            p.contact_email,
            Jsonb(p.extra_data),
            p.raw_text,
            p.confidence,
            scraped_at,
        ))

    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO insurance_products (
                insurer_name, insurer_slug, product_name, product_type, product_url,
                description, tagline, target_audience,
                premium_min_kes, premium_max_kes, premium_frequency, premium_notes,
                coverage_min_kes, coverage_max_kes, coverage_notes,
                min_age, max_age, eligibility_notes,
                key_benefits, exclusions, waiting_period,
                claims_process, how_to_apply,
                contact_phone, contact_email,
                extra_data, raw_text, confidence, scraped_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (insurer_slug, product_url)
            DO UPDATE SET
                product_name       = EXCLUDED.product_name,
                description        = EXCLUDED.description,
                tagline            = EXCLUDED.tagline,
                target_audience    = EXCLUDED.target_audience,
                premium_min_kes    = EXCLUDED.premium_min_kes,
                premium_max_kes    = EXCLUDED.premium_max_kes,
                premium_frequency  = EXCLUDED.premium_frequency,
                premium_notes      = EXCLUDED.premium_notes,
                coverage_min_kes   = EXCLUDED.coverage_min_kes,
                coverage_max_kes   = EXCLUDED.coverage_max_kes,
                coverage_notes     = EXCLUDED.coverage_notes,
                min_age            = EXCLUDED.min_age,
                max_age            = EXCLUDED.max_age,
                eligibility_notes  = EXCLUDED.eligibility_notes,
                key_benefits       = EXCLUDED.key_benefits,
                exclusions         = EXCLUDED.exclusions,
                waiting_period     = EXCLUDED.waiting_period,
                claims_process     = EXCLUDED.claims_process,
                how_to_apply       = EXCLUDED.how_to_apply,
                contact_phone      = EXCLUDED.contact_phone,
                contact_email      = EXCLUDED.contact_email,
                extra_data         = EXCLUDED.extra_data,
                raw_text           = EXCLUDED.raw_text,
                confidence         = EXCLUDED.confidence,
                scraped_at         = EXCLUDED.scraped_at
            """,
            prepared_rows,
        )

    return len(prepared_rows)
