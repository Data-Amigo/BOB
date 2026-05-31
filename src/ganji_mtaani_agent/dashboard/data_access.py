from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

import streamlit as st
from psycopg.rows import dict_row

from ganji_mtaani_agent.db.postgres import get_postgres_connection
from ganji_mtaani_agent.etl.canonical_fixtures import _candidate_from_row, normalize_team_name


def _fetch_all(query: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    with get_postgres_connection(autocommit=True) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, tuple(params or ()))
            return [dict(row) for row in cursor.fetchall()]


def clear_all_caches() -> None:
    st.cache_data.clear()


def _canonical_sport_aliases(sport: str | None) -> list[str] | None:
    if not sport or sport == "All":
        return None

    normalized = str(sport).strip().casefold()
    if normalized in {"football", "soccer"}:
        return ["football", "soccer"]
    if normalized == "basketball":
        return ["basketball"]
    return [normalized]


def _normalize_simulation_sport(value: str | None) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"football", "soccer"}:
        return "football"
    return normalized


def _names_compatible(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True

    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) >= min(2, len(left_tokens), len(right_tokens))


@st.cache_data(ttl=30)
def table_exists(table_name: str) -> bool:
    rows = _fetch_all("SELECT to_regclass(%s) AS relation_name", (f"public.{table_name}",))
    return bool(rows and rows[0]["relation_name"])


@st.cache_data(ttl=60)
def fetch_table_inventory() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
        """
    )


@st.cache_data(ttl=120)
def fetch_latest_ingestion_batches(limit: int = 20) -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT id, batch_name, batch_date, status, started_at, finished_at,
               triggered_by, total_sources, successful_sources, failed_sources, notes
        FROM ingestion_batches
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )


@st.cache_data(ttl=120)
def fetch_latest_source_runs(limit: int = 50) -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT id, source_name, target_name, source_type, status, started_at,
               finished_at, duration_ms, records_found, warnings_count, error_message
        FROM source_runs
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )


@st.cache_data(ttl=120)
def fetch_source_run_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT source_name,
               COUNT(*) AS total_runs,
               COUNT(*) FILTER (WHERE status = 'success') AS successful_runs,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed_runs,
               MAX(started_at) AS latest_started_at,
               SUM(COALESCE(records_found, 0)) AS cumulative_records_found
        FROM source_runs
        GROUP BY source_name
        ORDER BY source_name
        """
    )


@st.cache_data(ttl=300)
def fetch_bookmaker_source_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT source_name FROM bookmaker_odds ORDER BY source_name")
    return [str(row["source_name"]) for row in rows if row.get("source_name")]


@st.cache_data(ttl=300)
def fetch_bookmaker_league_options(source_name: str | None = None, sport: str | None = None) -> list[str]:
    clauses = []
    params: list[Any] = []
    if source_name:
        clauses.append("source_name = %s")
        params.append(source_name)
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = _fetch_all(f"SELECT DISTINCT league FROM bookmaker_odds {where_sql} ORDER BY league", params)
    return [str(row["league"]) for row in rows if row.get("league")]


@st.cache_data(ttl=120)
def fetch_bookmaker_odds(*, source_name: str | None = None, sport: str | None = None, league: str | None = None, search_text: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if source_name:
        clauses.append("source_name = %s")
        params.append(source_name)
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    if league:
        clauses.append("league = %s")
        params.append(league)
    if search_text:
        clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s)")
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, run_id, source_name, sport, league, event_datetime_text,
               home_team, away_team, game_id, match_status, score_text, market_type,
               home_odds, draw_odds, away_odds, home_or_draw_odds, draw_or_away_odds,
               home_or_away_odds, over_2_5_odds, under_2_5_odds, btts_yes_odds,
               btts_no_odds, extra_market_count, confidence, created_at
        FROM bookmaker_odds
        {where_sql}
        ORDER BY id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_bookmaker_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT source_name, sport, COUNT(*) AS row_count, MAX(created_at) AS latest_created_at
        FROM bookmaker_odds
        GROUP BY source_name, sport
        ORDER BY source_name, sport
        """
    )


@st.cache_data(ttl=300)
def fetch_results_sport_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT sport FROM sports_results ORDER BY sport")
    return [str(row["sport"]) for row in rows if row.get("sport")]


@st.cache_data(ttl=300)
def fetch_results_status_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT status FROM sports_results WHERE status IS NOT NULL ORDER BY status")
    return [str(row["status"]) for row in rows if row.get("status")]


@st.cache_data(ttl=120)
def fetch_sports_results(*, sport: str | None = None, status: str | None = None, event_date: str | None = None, search_text: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if event_date:
        clauses.append("event_date = %s")
        params.append(event_date)
    if search_text:
        clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s OR event_name ILIKE %s)")
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, run_id, source_name, sport, event_id, league_id, league, season,
               event_name, event_date, event_time, home_team, away_team, home_score,
               away_score, status, progress, venue, winner, confidence, created_at
        FROM sports_results
        {where_sql}
        ORDER BY event_date DESC NULLS LAST, id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_sports_results_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT sport, status, COUNT(*) AS row_count, MAX(event_date) AS latest_event_date
        FROM sports_results
        GROUP BY sport, status
        ORDER BY sport, status
        """
    )


@st.cache_data(ttl=300)
def fetch_forebet_results_sport_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT sport FROM forebet_results ORDER BY sport")
    return [str(row["sport"]) for row in rows if row.get("sport")]


@st.cache_data(ttl=300)
def fetch_forebet_results_status_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT status FROM forebet_results WHERE status IS NOT NULL ORDER BY status")
    return [str(row["status"]) for row in rows if row.get("status")]


@st.cache_data(ttl=120)
def fetch_forebet_results(*, sport: str | None = None, status: str | None = None, event_date_text: str | None = None, search_text: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if event_date_text:
        clauses.append("event_datetime_text LIKE %s")
        params.append(f"{event_date_text}%")
    if search_text:
        clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s)")
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, run_id, source_name, sport, league, home_team, away_team,
               match_url, event_datetime_text, prob_1, prob_x, prob_2, pred_outcome,
               predicted_home_score, predicted_away_score, predicted_score_text,
               actual_home_score, actual_away_score, actual_score_text, actual_outcome,
               status, pred_hit, pred_indicator_class, confidence, created_at
        FROM forebet_results
        {where_sql}
        ORDER BY id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_forebet_results_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT sport, status, COUNT(*) AS row_count, MAX(created_at) AS latest_created_at
        FROM forebet_results
        GROUP BY sport, status
        ORDER BY sport, status
        """
    )


@st.cache_data(ttl=300)
def fetch_flashscore_results_sport_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT sport FROM flashscore_results ORDER BY sport")
    return [str(row["sport"]) for row in rows if row.get("sport")]


@st.cache_data(ttl=300)
def fetch_flashscore_results_status_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT match_status FROM flashscore_results WHERE match_status IS NOT NULL ORDER BY match_status")
    return [str(row["match_status"]) for row in rows if row.get("match_status")]


@st.cache_data(ttl=120)
def fetch_flashscore_results(*, sport: str | None = None, status: str | None = None, page_date_text: str | None = None, search_text: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    if status:
        clauses.append("match_status = %s")
        params.append(status)
    if page_date_text:
        clauses.append("page_date_text LIKE %s")
        params.append(f"{page_date_text}%")
    if search_text:
        clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s OR country_or_region ILIKE %s)")
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, run_id, source_name, sport, page_date_text, country_or_region, league,
               match_status, event_time_text, home_team, away_team, home_score, away_score,
               confidence, created_at
        FROM flashscore_results
        {where_sql}
        ORDER BY id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_flashscore_results_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT sport, match_status, COUNT(*) AS row_count, MAX(created_at) AS latest_created_at
        FROM flashscore_results
        GROUP BY sport, match_status
        ORDER BY sport, match_status
        """
    )


@st.cache_data(ttl=300)
def fetch_forebet_sport_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT sport FROM forebet_predictions ORDER BY sport")
    return [str(row["sport"]) for row in rows if row.get("sport")]


@st.cache_data(ttl=300)
def fetch_forebet_league_options(sport: str | None = None) -> list[str]:
    clauses = []
    params: list[Any] = []
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = _fetch_all(f"SELECT DISTINCT league FROM forebet_predictions {where_sql} ORDER BY league", params)
    return [str(row["league"]) for row in rows if row.get("league")]


@st.cache_data(ttl=120)
def fetch_forebet_predictions(*, sport: str | None = None, league: str | None = None, search_text: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    if league:
        clauses.append("league = %s")
        params.append(league)
    if search_text:
        clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s)")
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, run_id, source_name, sport, league, home_team, away_team,
               match_url, event_datetime_text, prob_1, prob_x, prob_2, pred_outcome,
               predicted_home_score, predicted_away_score, correct_score_text,
               avg_goals, avg_points, weather, coef_1, coef_x, coef_2,
               coef_3, coef_extra, remaining_tokens_json, confidence, created_at
        FROM forebet_predictions
        {where_sql}
        ORDER BY id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_forebet_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT sport, COUNT(*) AS row_count, MAX(created_at) AS latest_created_at
        FROM forebet_predictions
        GROUP BY sport
        ORDER BY sport
        """
    )


@st.cache_data(ttl=300)
def fetch_polymarket_category_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT category FROM polymarket_markets WHERE category IS NOT NULL ORDER BY category")
    return [str(row["category"]) for row in rows if row.get("category")]


@st.cache_data(ttl=120)
def fetch_polymarket_markets(*, category: str | None = None, status: str | None = None, search_text: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if category:
        clauses.append("category = %s")
        params.append(category)
    if status == "active":
        clauses.append("active = TRUE")
    elif status == "closed":
        clauses.append("closed = TRUE")
    elif status == "archived":
        clauses.append("archived = TRUE")
    if search_text:
        clauses.append("(question ILIKE %s OR slug ILIKE %s OR category ILIKE %s)")
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, run_id, source_name, market_id, event_id, question, slug,
               category, subcategory, tags_json, description, start_date, end_date,
               active, closed, archived, outcomes_json, outcome_prices_json,
               liquidity, volume, open_interest, market_type, confidence, created_at
        FROM polymarket_markets
        {where_sql}
        ORDER BY id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_polymarket_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT category,
               COUNT(*) AS row_count,
               COUNT(*) FILTER (WHERE active) AS active_rows,
               MAX(created_at) AS latest_created_at
        FROM polymarket_markets
        GROUP BY category
        ORDER BY category
        """
    )


@st.cache_data(ttl=120)
def fetch_forebet_match_analyses(*, sport: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if sport:
        clauses.append("sport = %s")
        params.append(sport)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, source_name, sport, match_url, competition, league_code,
               event_datetime_text, home_team, away_team, pred_outcome,
               predicted_score_text, actual_score_text, actual_status,
               home_form_sequence, away_form_sequence, confidence, scraped_at
        FROM forebet_match_analyses
        {where_sql}
        ORDER BY scraped_at DESC, id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_forebet_match_history_rows(*, match_url: str, section_name: str | None = None) -> list[dict[str, Any]]:
    clauses = ["match_url = %s"]
    params: list[Any] = [match_url]
    if section_name:
        clauses.append("section_name = %s")
        params.append(section_name)
    where_sql = f"WHERE {' AND '.join(clauses)}"
    return _fetch_all(
        f"""
        SELECT id, source_name, sport, match_url, section_name, section_team, sequence_no,
               event_date_text, competition_tag, home_team, away_team, score_text,
               extra_score_text, result_outcome, result_class, active_side, detail_url,
               raw_text, scraped_at
        FROM forebet_match_history_rows
        {where_sql}
        ORDER BY section_name, section_team, sequence_no
        """,
        params,
    )


# =============================================================================
# Canonical Fixtures Data Access
# =============================================================================
def _canonical_filters(
    *,
    sport: str | None = None,
    source_name: str | None = None,
    search_text: str | None = None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    sport_aliases = _canonical_sport_aliases(sport)
    if sport_aliases:
        clauses.append("LOWER(cf.sport) = ANY(%s)")
        params.append(sport_aliases)
    if source_name:
        clauses.append(
            """
            EXISTS (
                SELECT 1
                FROM fixture_source_links AS source_filter
                WHERE source_filter.fixture_id = cf.id
                  AND source_filter.source_name = %s
            )
            """
        )
        params.append(source_name)
    if search_text:
        search_value = f"%{search_text}%"
        clauses.append(
            """
            (
                cf.canonical_home_team ILIKE %s
                OR cf.canonical_away_team ILIKE %s
                OR COALESCE(cf.canonical_league, '') ILIKE %s
            )
            """
        )
        params.extend([search_value, search_value, search_value])

    return clauses, params


def _fixture_evaluation_filters(
    *,
    sport: str | None = None,
    source_name: str | None = None,
    search_text: str | None = None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    sport_aliases = _canonical_sport_aliases(sport)
    if sport_aliases:
        clauses.append("LOWER(fe.sport) = ANY(%s)")
        params.append(sport_aliases)
    if source_name:
        clauses.append("fe.available_sources_json ? %s")
        params.append(source_name)
    if search_text:
        search_value = f"%{search_text}%"
        clauses.append(
            """
            (
                COALESCE(fe.display_home_team, '') ILIKE %s
                OR COALESCE(fe.display_away_team, '') ILIKE %s
                OR COALESCE(fe.display_league, '') ILIKE %s
            )
            """
        )
        params.extend([search_value, search_value, search_value])

    return clauses, params


@st.cache_data(ttl=300)
def fetch_canonical_sport_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT LOWER(sport) AS sport FROM canonical_fixtures ORDER BY 1")
    sports = {str(row["sport"]) for row in rows if row.get("sport")}
    options: list[str] = []
    if sports.intersection({"football", "soccer"}):
        options.append("Football")
    if "basketball" in sports:
        options.append("Basketball")
    return options


@st.cache_data(ttl=300)
def fetch_canonical_source_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT source_name FROM fixture_source_links ORDER BY source_name")
    return [str(row["source_name"]) for row in rows if row.get("source_name")]


@st.cache_data(ttl=120)
def fetch_canonical_summary(
    *,
    sport: str | None = None,
    source_name: str | None = None,
    search_text: str | None = None,
) -> dict[str, Any]:
    if table_exists("fixture_evaluations"):
        clauses, params = _fixture_evaluation_filters(
            sport=sport,
            source_name=source_name,
            search_text=search_text,
        )
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = _fetch_all(
            f"""
            SELECT
                COUNT(*) AS total_games,
                COUNT(*) FILTER (WHERE fe.prediction_source IS NOT NULL) AS total_games_predicted,
                COUNT(*) FILTER (
                    WHERE fe.prediction_source IS NOT NULL
                      AND fe.result_source_used IS NOT NULL
                      AND fe.pred_hit IS NOT NULL
                ) AS total_results,
                COUNT(*) FILTER (WHERE fe.pred_hit IS TRUE) AS total_won,
                COUNT(*) FILTER (WHERE fe.pred_hit IS FALSE) AS total_lost
            FROM fixture_evaluations AS fe
            {where_sql}
            """,
            params,
        )
        summary = rows[0] if rows else {}
        total_results = int(summary.get("total_results") or 0)
        total_won = int(summary.get("total_won") or 0)
        total_lost = int(summary.get("total_lost") or 0)
        summary["pct_won"] = round((100.0 * total_won / total_results), 2) if total_results else 0
        summary["pct_lost"] = round((100.0 * total_lost / total_results), 2) if total_results else 0
        return summary

    clauses, params = _canonical_filters(sport=sport, source_name=source_name, search_text=search_text)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    canonical_rows = _fetch_all(
        f"""
        WITH filtered_fixtures AS (
            SELECT cf.*
            FROM canonical_fixtures AS cf
            {where_sql}
        )
        SELECT
            COUNT(*) AS total_games,
            COUNT(*) FILTER (
                WHERE EXISTS (
                    SELECT 1
                    FROM fixture_source_links AS pred_links
                    WHERE pred_links.fixture_id = filtered_fixtures.id
                      AND pred_links.source_table IN ('forebet_predictions', 'forebet_results')
                )
            ) AS total_games_predicted,
            COUNT(*) FILTER (
                WHERE EXISTS (
                    SELECT 1
                    FROM fixture_source_links AS result_links
                    WHERE result_links.fixture_id = filtered_fixtures.id
                      AND result_links.source_table IN ('forebet_results', 'flashscore_results', 'sports_results')
                )
            ) AS total_results
        FROM filtered_fixtures
        """,
        params,
    )
    summary = canonical_rows[0] if canonical_rows else {}

    if source_name and source_name not in {"forebet", "forebet_results", "All"}:
        summary["total_won"] = 0
        summary["total_lost"] = 0
        summary["pct_won"] = 0
        summary["pct_lost"] = 0
        return summary

    forebet_clauses: list[str] = []
    forebet_params: list[Any] = []
    sport_aliases = _canonical_sport_aliases(sport)
    if sport_aliases:
        forebet_clauses.append("LOWER(sport) = ANY(%s)")
        forebet_params.append(sport_aliases)
    if search_text:
        search_value = f"%{search_text}%"
        forebet_clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s)")
        forebet_params.extend([search_value, search_value, search_value])
    forebet_where_sql = f"WHERE {' AND '.join(forebet_clauses)}" if forebet_clauses else ""

    forebet_rows = _fetch_all(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE pred_hit IS TRUE) AS total_won,
            COUNT(*) FILTER (WHERE pred_hit IS FALSE) AS total_lost,
            COUNT(*) FILTER (WHERE pred_hit IS NOT NULL) AS evaluated_rows
        FROM forebet_results
        {forebet_where_sql}
        """,
        forebet_params,
    )
    forebet_summary = forebet_rows[0] if forebet_rows else {}
    total_won = int(forebet_summary.get("total_won") or 0)
    total_lost = int(forebet_summary.get("total_lost") or 0)
    evaluated_rows = int(forebet_summary.get("evaluated_rows") or 0)

    summary["total_won"] = total_won
    summary["total_lost"] = total_lost
    summary["pct_won"] = round((100.0 * total_won / evaluated_rows), 2) if evaluated_rows else 0
    summary["pct_lost"] = round((100.0 * total_lost / evaluated_rows), 2) if evaluated_rows else 0
    return summary


@st.cache_data(ttl=120)
def fetch_canonical_probability_breakdown(
    *,
    sport: str | None = None,
    source_name: str | None = None,
    search_text: str | None = None,
) -> list[dict[str, Any]]:
    if table_exists("fixture_evaluations"):
        clauses, params = _fixture_evaluation_filters(
            sport=sport,
            source_name=source_name,
            search_text=search_text,
        )
        clauses.append("fe.pred_probability IS NOT NULL")
        clauses.append("fe.pred_hit IS NOT NULL")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return _fetch_all(
            f"""
            WITH bucketed AS (
                SELECT
                    CASE
                        WHEN fe.pred_probability < 40 THEN '<40%%'
                        WHEN fe.pred_probability < 50 THEN '40-50%%'
                        WHEN fe.pred_probability < 60 THEN '50-60%%'
                        WHEN fe.pred_probability < 70 THEN '60-70%%'
                        WHEN fe.pred_probability < 80 THEN '70-80%%'
                        WHEN fe.pred_probability < 90 THEN '80-90%%'
                        ELSE '90-100%%'
                    END AS probability_bucket,
                    CASE
                        WHEN fe.pred_probability < 40 THEN 0
                        WHEN fe.pred_probability < 50 THEN 1
                        WHEN fe.pred_probability < 60 THEN 2
                        WHEN fe.pred_probability < 70 THEN 3
                        WHEN fe.pred_probability < 80 THEN 4
                        WHEN fe.pred_probability < 90 THEN 5
                        ELSE 6
                    END AS bucket_order,
                    fe.pred_hit
                FROM fixture_evaluations AS fe
                {where_sql}
            )
            SELECT
                probability_bucket,
                COUNT(*) FILTER (WHERE pred_hit IS TRUE) AS won_count,
                COUNT(*) FILTER (WHERE pred_hit IS FALSE) AS lost_count,
                COUNT(*) AS total_decided
            FROM bucketed
            GROUP BY probability_bucket, bucket_order
            ORDER BY bucket_order
            """,
            params,
        )

    if source_name and source_name not in {"forebet", "forebet_results", "All"}:
        return []

    clauses: list[str] = []
    params: list[Any] = []
    sport_aliases = _canonical_sport_aliases(sport)
    if sport_aliases:
        clauses.append("LOWER(sport) = ANY(%s)")
        params.append(sport_aliases)
    if search_text:
        search_value = f"%{search_text}%"
        clauses.append("(home_team ILIKE %s OR away_team ILIKE %s OR league ILIKE %s)")
        params.extend([search_value, search_value, search_value])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    return _fetch_all(
        f"""
        WITH evaluated AS (
            SELECT
                pred_outcome,
                CASE
                    WHEN pred_outcome = '1' THEN prob_1
                    WHEN pred_outcome = 'X' THEN prob_x
                    WHEN pred_outcome = '2' THEN prob_2
                    ELSE NULL
                END AS pred_probability,
                pred_hit
            FROM forebet_results
            {where_sql}
        ),
        bucketed AS (
            SELECT
                CASE
                    WHEN pred_probability < 40 THEN '<40%%'
                    WHEN pred_probability < 50 THEN '40-50%%'
                    WHEN pred_probability < 60 THEN '50-60%%'
                    WHEN pred_probability < 70 THEN '60-70%%'
                    WHEN pred_probability < 80 THEN '70-80%%'
                    WHEN pred_probability < 90 THEN '80-90%%'
                    ELSE '90-100%%'
                END AS probability_bucket,
                CASE
                    WHEN pred_probability < 40 THEN 0
                    WHEN pred_probability < 50 THEN 1
                    WHEN pred_probability < 60 THEN 2
                    WHEN pred_probability < 70 THEN 3
                    WHEN pred_probability < 80 THEN 4
                    WHEN pred_probability < 90 THEN 5
                    ELSE 6
                END AS bucket_order,
                pred_hit
            FROM evaluated
            WHERE pred_probability IS NOT NULL
              AND pred_hit IS NOT NULL
        )
        SELECT
            probability_bucket,
            COUNT(*) FILTER (WHERE pred_hit IS TRUE) AS won_count,
            COUNT(*) FILTER (WHERE pred_hit IS FALSE) AS lost_count,
            COUNT(*) AS total_decided
        FROM bucketed
        GROUP BY probability_bucket, bucket_order
        ORDER BY bucket_order
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_canonical_fixture_rows(
    *,
    sport: str | None = None,
    source_name: str | None = None,
    search_text: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses, params = _canonical_filters(sport=sport, source_name=source_name, search_text=search_text)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    return _fetch_all(
        f"""
        WITH filtered_fixtures AS (
            SELECT cf.*
            FROM canonical_fixtures AS cf
            {where_sql}
        ),
        fixture_sources AS (
            SELECT
                fsl.fixture_id,
                COUNT(*) AS linked_rows,
                COUNT(DISTINCT fsl.source_name) AS source_count,
                STRING_AGG(DISTINCT fsl.source_name, ', ' ORDER BY fsl.source_name) AS linked_sources
            FROM fixture_source_links AS fsl
            WHERE fsl.fixture_id IN (SELECT id FROM filtered_fixtures)
            GROUP BY fsl.fixture_id
        ),
        ranked_forebet_predictions AS (
            SELECT DISTINCT ON (fsl.fixture_id)
                fsl.fixture_id,
                fp.pred_outcome,
                fp.correct_score_text,
                CASE
                    WHEN fp.pred_outcome = '1' THEN fp.prob_1
                    WHEN fp.pred_outcome = 'X' THEN fp.prob_x
                    WHEN fp.pred_outcome = '2' THEN fp.prob_2
                    ELSE NULL
                END AS pred_probability
            FROM fixture_source_links AS fsl
            JOIN forebet_predictions AS fp
                ON fp.id = fsl.source_row_id
            WHERE fsl.source_table = 'forebet_predictions'
              AND fsl.fixture_id IN (SELECT id FROM filtered_fixtures)
            ORDER BY fsl.fixture_id, fp.created_at DESC, fp.id DESC
        ),
        ranked_forebet_results AS (
            SELECT DISTINCT ON (fsl.fixture_id)
                fsl.fixture_id,
                fr.pred_outcome,
                fr.predicted_score_text,
                fr.pred_hit,
                CASE
                    WHEN fr.pred_outcome = '1' THEN fr.prob_1
                    WHEN fr.pred_outcome = 'X' THEN fr.prob_x
                    WHEN fr.pred_outcome = '2' THEN fr.prob_2
                    ELSE NULL
                END AS pred_probability
            FROM fixture_source_links AS fsl
            JOIN forebet_results AS fr
                ON fr.id = fsl.source_row_id
            WHERE fsl.source_table = 'forebet_results'
              AND fsl.fixture_id IN (SELECT id FROM filtered_fixtures)
            ORDER BY fsl.fixture_id, fr.created_at DESC, fr.id DESC
        )
        SELECT
            ff.id,
            ff.sport,
            ff.canonical_event_date,
            ff.canonical_event_time_text,
            ff.canonical_league,
            ff.canonical_home_team,
            ff.canonical_away_team,
            fs.linked_rows,
            fs.source_count,
            fs.linked_sources,
            COALESCE(rfr.pred_outcome, rfp.pred_outcome) AS pred_outcome,
            COALESCE(rfr.pred_probability, rfp.pred_probability) AS pred_probability,
            COALESCE(rfr.predicted_score_text, rfp.correct_score_text) AS correct_score_text,
            ff.result_home_score,
            ff.result_away_score,
            ff.primary_result_source,
            CASE
                WHEN ff.result_home_score IS NULL OR ff.result_away_score IS NULL THEN NULL
                WHEN ff.result_home_score > ff.result_away_score THEN '1'
                WHEN ff.result_home_score < ff.result_away_score THEN '2'
                ELSE 'X'
            END AS actual_outcome,
            COALESCE(
                rfr.pred_hit,
                CASE
                    WHEN rfp.pred_outcome IS NULL THEN NULL
                    WHEN ff.result_home_score IS NULL OR ff.result_away_score IS NULL THEN NULL
                    WHEN (
                        CASE
                            WHEN ff.result_home_score > ff.result_away_score THEN '1'
                            WHEN ff.result_home_score < ff.result_away_score THEN '2'
                            ELSE 'X'
                        END
                    ) = rfp.pred_outcome THEN TRUE
                    ELSE FALSE
                END
            ) AS pred_hit,
            ff.confidence,
            ff.updated_at
        FROM filtered_fixtures AS ff
        LEFT JOIN fixture_sources AS fs
            ON fs.fixture_id = ff.id
        LEFT JOIN ranked_forebet_predictions AS rfp
            ON rfp.fixture_id = ff.id
        LEFT JOIN ranked_forebet_results AS rfr
            ON rfr.fixture_id = ff.id
        ORDER BY ff.canonical_event_date DESC, ff.id DESC
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_fixture_simulation_inputs(
    *,
    sport: str | None = None,
    search_text: str | None = None,
) -> list[dict[str, Any]]:
    if not table_exists("fixture_evaluations"):
        return []

    clauses, params = _fixture_evaluation_filters(
        sport=sport,
        source_name=None,
        search_text=search_text,
    )
    clauses.extend(
        [
            "fe.prediction_source IS NOT NULL",
            "fe.result_source_used IS NOT NULL",
            "fe.pred_hit IS NOT NULL",
            "fe.pred_probability IS NOT NULL",
        ]
    )
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    evaluation_rows = _fetch_all(
        f"""
        SELECT
            fe.id AS evaluation_id,
            fe.canonical_fixture_id,
            fe.sport,
            fe.event_date,
            fe.normalized_home_team,
            fe.normalized_away_team,
            fe.display_league,
            fe.display_home_team,
            fe.display_away_team,
            fe.pred_outcome,
            fe.pred_probability,
            fe.pred_hit,
            fe.result_source_used,
            fe.bookmaker_row_count
        FROM fixture_evaluations AS fe
        {where_sql}
        ORDER BY fe.event_date, fe.id
        """,
        params,
    )
    if not evaluation_rows:
        return []

    bookmaker_params: list[Any] = []
    bookmaker_clauses: list[str] = []
    sport_aliases = _canonical_sport_aliases(sport)
    if sport_aliases:
        bookmaker_clauses.append("LOWER(bo.sport) = ANY(%s)")
        bookmaker_params.append(sport_aliases)
    bookmaker_where_sql = f"WHERE {' AND '.join(bookmaker_clauses)}" if bookmaker_clauses else ""
    bookmaker_rows = _fetch_all(
        f"""
        SELECT
            bo.id,
            bo.source_name,
            bo.sport,
            bo.home_team,
            bo.away_team,
            bo.event_datetime_text,
            bo.home_odds,
            bo.draw_odds,
            bo.away_odds,
            sr.started_at AS source_run_started_at
        FROM bookmaker_odds AS bo
        LEFT JOIN source_runs AS sr
            ON sr.id = bo.run_id
        {bookmaker_where_sql}
        ORDER BY bo.id DESC
        """,
        bookmaker_params,
    )

    bookmaker_index: dict[tuple[str, date, str, str], list[dict[str, Any]]] = {}
    bookmaker_by_sport_date: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for bookmaker_row in bookmaker_rows:
        started_at = bookmaker_row.get("source_run_started_at")
        if isinstance(started_at, datetime):
            reference_date = started_at.date()
        else:
            reference_date = date.today()
        candidate = _candidate_from_row(
            {
                "source_name": bookmaker_row.get("source_name"),
                "source_row_id": bookmaker_row.get("id"),
                "sport": bookmaker_row.get("sport"),
                "home_team": bookmaker_row.get("home_team"),
                "away_team": bookmaker_row.get("away_team"),
                "event_datetime_text": bookmaker_row.get("event_datetime_text"),
            },
            source_table="bookmaker_odds",
            reference_date=reference_date,
        )
        if candidate is None or candidate.source_event_date is None:
            continue
        key = (
            _normalize_simulation_sport(bookmaker_row.get("sport")),
            candidate.source_event_date,
            normalize_team_name(bookmaker_row.get("home_team")),
            normalize_team_name(bookmaker_row.get("away_team")),
        )
        bookmaker_index.setdefault(key, []).append(bookmaker_row)
        bookmaker_by_sport_date.setdefault((key[0], key[1]), []).append(bookmaker_row)

    simulation_rows: list[dict[str, Any]] = []
    for evaluation_row in evaluation_rows:
        key = (
            _normalize_simulation_sport(evaluation_row.get("sport")),
            evaluation_row.get("event_date"),
            str(evaluation_row.get("normalized_home_team") or ""),
            str(evaluation_row.get("normalized_away_team") or ""),
        )
        matched_bookmakers = bookmaker_index.get(key, [])
        if not matched_bookmakers:
            same_day_candidates = bookmaker_by_sport_date.get((key[0], key[1]), [])
            matched_bookmakers = [
                bookmaker_row
                for bookmaker_row in same_day_candidates
                if _names_compatible(key[2], normalize_team_name(bookmaker_row.get("home_team")))
                and _names_compatible(key[3], normalize_team_name(bookmaker_row.get("away_team")))
            ]
        if not matched_bookmakers:
            simulation_rows.append(
                {
                    **evaluation_row,
                    "bookmaker_source": None,
                    "predicted_outcome_odds": None,
                }
            )
            continue

        best_by_source: dict[str, float] = {}
        pred_outcome = str(evaluation_row.get("pred_outcome") or "")
        for bookmaker_row in matched_bookmakers:
            if pred_outcome == "1":
                odds_value = bookmaker_row.get("home_odds")
            elif pred_outcome == "X":
                odds_value = bookmaker_row.get("draw_odds")
            elif pred_outcome == "2":
                odds_value = bookmaker_row.get("away_odds")
            else:
                odds_value = None
            if odds_value in (None, "", 0):
                continue
            source_name = str(bookmaker_row.get("source_name") or "")
            try:
                odds_float = float(odds_value)
            except (TypeError, ValueError):
                continue
            current = best_by_source.get(source_name)
            if current is None or odds_float > current:
                best_by_source[source_name] = odds_float

        if not best_by_source:
            simulation_rows.append(
                {
                    **evaluation_row,
                    "bookmaker_source": None,
                    "predicted_outcome_odds": None,
                }
            )
            continue

        for source_name, odds_float in sorted(best_by_source.items()):
            simulation_rows.append(
                {
                    **evaluation_row,
                    "bookmaker_source": source_name,
                    "predicted_outcome_odds": odds_float,
                }
            )

    return simulation_rows


# =============================================================================
# Insurance Products Data Access
# =============================================================================
@st.cache_data(ttl=300)
def fetch_insurance_insurer_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT insurer_name FROM insurance_products ORDER BY insurer_name")
    return [str(r["insurer_name"]) for r in rows if r.get("insurer_name")]


@st.cache_data(ttl=300)
def fetch_insurance_type_options() -> list[str]:
    rows = _fetch_all("SELECT DISTINCT product_type FROM insurance_products ORDER BY product_type")
    return [str(r["product_type"]) for r in rows if r.get("product_type")]


@st.cache_data(ttl=120)
def fetch_insurance_summary() -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT insurer_name,
               insurer_slug,
               product_type,
               COUNT(*)              AS product_count,
               ROUND(AVG(confidence)::numeric, 2) AS avg_confidence,
               MAX(scraped_at)       AS last_scraped
        FROM insurance_products
        GROUP BY insurer_name, insurer_slug, product_type
        ORDER BY insurer_name, product_type
        """
    )


@st.cache_data(ttl=120)
def fetch_insurance_products(
    *,
    insurer_slug: str | None = None,
    product_type: str | None = None,
    search_text: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if insurer_slug:
        clauses.append("insurer_slug = %s")
        params.append(insurer_slug)
    if product_type:
        clauses.append("product_type = %s")
        params.append(product_type)
    if search_text:
        clauses.append(
            "(product_name ILIKE %s OR tagline ILIKE %s OR description ILIKE %s)"
        )
        sv = f"%{search_text}%"
        params.extend([sv, sv, sv])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return _fetch_all(
        f"""
        SELECT id, insurer_name, insurer_slug, product_name, product_type,
               tagline, target_audience, premium_notes,
               jsonb_array_length(key_benefits) AS benefit_count,
               waiting_period, how_to_apply,
               contact_phone, contact_email,
               confidence, scraped_at, product_url
        FROM insurance_products
        {where_sql}
        ORDER BY insurer_name, product_type, product_name
        LIMIT %s
        """,
        params,
    )


@st.cache_data(ttl=120)
def fetch_insurance_product_detail(product_id: int) -> dict[str, Any] | None:
    rows = _fetch_all(
        """
        SELECT id, insurer_name, product_name, product_type, product_url,
               description, tagline, target_audience,
               premium_min_kes, premium_max_kes, premium_frequency, premium_notes,
               coverage_notes, min_age, max_age, eligibility_notes,
               key_benefits, exclusions, waiting_period,
               claims_process, how_to_apply, contact_phone, contact_email,
               extra_data, confidence, scraped_at
        FROM insurance_products
        WHERE id = %s
        """,
        (product_id,),
    )
    return rows[0] if rows else None
