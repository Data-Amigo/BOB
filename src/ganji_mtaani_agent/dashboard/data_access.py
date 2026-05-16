from __future__ import annotations

from typing import Any, Iterable

import streamlit as st
from psycopg.rows import dict_row

from ganji_mtaani_agent.db.postgres import get_postgres_connection


def _fetch_all(query: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    with get_postgres_connection(autocommit=True) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, tuple(params or ()))
            return [dict(row) for row in cursor.fetchall()]


def clear_all_caches() -> None:
    st.cache_data.clear()


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
               event_datetime_text, prob_1, prob_x, prob_2, pred_outcome,
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
