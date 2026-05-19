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
               event_datetime_text, prob_1, prob_x, prob_2, pred_outcome,
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
               product_type,
               COUNT(*)              AS product_count,
               ROUND(AVG(confidence)::numeric, 2) AS avg_confidence,
               MAX(scraped_at)       AS last_scraped
        FROM insurance_products
        GROUP BY insurer_name, product_type
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
