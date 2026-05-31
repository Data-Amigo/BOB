from __future__ import annotations

import importlib
import math
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ganji_mtaani_agent.dashboard.data_access import (
    clear_all_caches,
    fetch_bookmaker_league_options,
    fetch_bookmaker_odds,
    fetch_bookmaker_source_options,
    fetch_canonical_fixture_rows,
    fetch_canonical_probability_breakdown,
    fetch_canonical_source_options,
    fetch_canonical_sport_options,
    fetch_canonical_summary,
    fetch_fixture_simulation_inputs,
    fetch_flashscore_results,
    fetch_flashscore_results_sport_options,
    fetch_flashscore_results_status_options,
    fetch_flashscore_results_summary,
    fetch_forebet_match_analyses,
    fetch_forebet_match_history_rows,
    fetch_forebet_results,
    fetch_forebet_results_sport_options,
    fetch_forebet_results_status_options,
    fetch_forebet_results_summary,
    fetch_bookmaker_summary,
    fetch_forebet_league_options,
    fetch_forebet_predictions,
    fetch_forebet_sport_options,
    fetch_forebet_summary,
    fetch_insurance_insurer_options,
    fetch_insurance_product_detail,
    fetch_insurance_products,
    fetch_insurance_summary,
    fetch_insurance_type_options,
    fetch_latest_ingestion_batches,
    fetch_latest_source_runs,
    fetch_polymarket_category_options,
    fetch_polymarket_markets,
    fetch_polymarket_summary,
    fetch_results_sport_options,
    fetch_results_status_options,
    fetch_source_run_summary,
    fetch_sports_results,
    fetch_sports_results_summary,
    fetch_table_inventory,
    table_exists,
)


# =============================================================================
# Constants
# =============================================================================
PAGE_TITLE = "BoB | Decision Intelligence"
PAGE_SIMULATION = "Simulation"

PAGE_OVERVIEW   = "📊  Overview"
PAGE_BOOKMAKER  = "🎰  Bookmaker Odds"
PAGE_FOREBET    = "📈  Forebet Predictions"
PAGE_POLYMARKET = "🌐  Polymarket Markets"
PAGE_RESULTS    = "⚽  Sports Results"
PAGE_CANONICAL  = "🧩  Canonical Fixtures"
PAGE_HISTORY    = "📚  Historical Analysis"
PAGE_INSURANCE  = "🏥  Insurance"

SOURCE_FAMILY_CATALOG = [
    {"source_name": "betika",      "display_name": "Betika",      "role": "Bookmaker odds",       "table_name": "bookmaker_odds"},
    {"source_name": "sportpesa",   "display_name": "SportPesa",   "role": "Bookmaker odds",       "table_name": "bookmaker_odds"},
    {"source_name": "mozzart",     "display_name": "Mozzart",     "role": "Bookmaker odds",       "table_name": "bookmaker_odds"},
    {"source_name": "forebet",     "display_name": "Forebet",     "role": "Predictions",          "table_name": "forebet_predictions"},
    {"source_name": "forebet_results", "display_name": "Forebet Results", "role": "Finished results", "table_name": "forebet_results"},
    {"source_name": "forebet_history", "display_name": "Forebet History", "role": "Historical analysis", "table_name": "forebet_match_analyses"},
    {"source_name": "flashscore",  "display_name": "Flashscore Results", "role": "Finished results", "table_name": "flashscore_results"},
    {"source_name": "polymarket",  "display_name": "Polymarket",  "role": "Prediction markets",   "table_name": "polymarket_markets"},
    {"source_name": "thesportsdb", "display_name": "TheSportsDB", "role": "Results & enrichment", "table_name": "sports_results"},
    {"source_name": "jubilee",     "display_name": "Jubilee Insurance", "role": "Insurance products", "table_name": "insurance_products"},
]


# =============================================================================
# Page Configuration
# =============================================================================
def configure_page() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )


# =============================================================================
# Global CSS  — runs once per page load, styles everything Streamlit can't
# =============================================================================
def inject_global_css() -> None:
    st.markdown(
        """
        <style>
        /* ── Metric cards ───────────────────────────────────────────────────── */
        [data-testid="metric-container"] {
            background: linear-gradient(135deg, rgba(240,180,41,0.09) 0%, rgba(17,34,64,0.55) 100%);
            border: 1px solid rgba(240,180,41,0.28);
            border-radius: 0.8rem;
            padding: 1rem 1.1rem 0.9rem 1.1rem;
        }
        [data-testid="stMetricValue"] {
            color: #F0B429 !important;
            font-size: 1.9rem !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricLabel"] p {
            color: #94a3b8 !important;
            font-size: 0.7rem !important;
            text-transform: uppercase;
            letter-spacing: 0.09em;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.75rem !important;
        }

        /* ── Sidebar ─────────────────────────────────────────────────────────── */
        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(240,180,41,0.18);
        }
        [data-testid="stSidebar"] h3 {
            color: #F0B429 !important;
            font-weight: 800;
            letter-spacing: 0.07em;
            font-size: 1.4rem;
        }
        [data-testid="stSidebar"] .stRadio > label {
            color: #94a3b8 !important;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
            padding: 0.4rem 0.6rem;
            border-radius: 0.5rem;
            font-size: 0.95rem !important;
            text-transform: none !important;
            letter-spacing: normal !important;
            color: #cbd5e0 !important;
            transition: background 0.15s ease;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
            background: rgba(240,180,41,0.1);
        }

        /* ── Refresh button ──────────────────────────────────────────────────── */
        [data-testid="stSidebar"] .stButton > button {
            background: linear-gradient(135deg, rgba(240,180,41,0.14), rgba(240,180,41,0.05));
            border: 1px solid rgba(240,180,41,0.45);
            color: #F0B429;
            font-weight: 600;
            letter-spacing: 0.04em;
            border-radius: 0.5rem;
            transition: all 0.2s ease;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: linear-gradient(135deg, rgba(240,180,41,0.26), rgba(240,180,41,0.12));
            border-color: rgba(240,180,41,0.75);
            box-shadow: 0 0 14px rgba(240,180,41,0.22);
        }

        /* ── Dataframe containers ────────────────────────────────────────────── */
        [data-testid="stDataFrame"] {
            border: 1px solid rgba(240,180,41,0.14);
            border-radius: 0.65rem;
            overflow: hidden;
        }

        /* ── Section headings ────────────────────────────────────────────────── */
        h3 {
            color: #e2e8f0 !important;
            font-weight: 700;
            letter-spacing: 0.02em;
            padding-bottom: 0.3rem;
            border-bottom: 1px solid rgba(240,180,41,0.15);
            margin-bottom: 0.8rem !important;
        }

        /* ── Selectbox / text input ──────────────────────────────────────────── */
        [data-testid="stSelectbox"] > div > div,
        [data-testid="stTextInput"] > div > div {
            border-radius: 0.45rem;
            border-color: rgba(240,180,41,0.25) !important;
        }

        /* ── Alert / info boxes ──────────────────────────────────────────────── */
        [data-testid="stAlert"] {
            border-radius: 0.6rem;
            border-left: 3px solid rgba(240,180,41,0.55);
        }

        /* ── Divider ─────────────────────────────────────────────────────────── */
        hr {
            border-color: rgba(240,180,41,0.18) !important;
        }

        /* ── Pending card (used in placeholders) ─────────────────────────────── */
        .pending-card {
            padding: 1.1rem 1.3rem;
            border: 1px dashed rgba(240,180,41,0.35);
            border-radius: 0.85rem;
            background: rgba(240,180,41,0.04);
            color: #cbd5e0;
            line-height: 1.7;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Brand Header  — gold shimmer BOB + tagline + three pillar badges
# =============================================================================
def render_brand_header() -> None:
    st.markdown(
        """
        <style>
        /* ── Shimmer + glow animation for BoB ───────────────────────────────── */
        @keyframes bobShimmer {
            0%   { background-position: -400% center;
                   filter: drop-shadow(0 0 6px rgba(240,180,41,0.3)); }
            50%  { background-position:  400% center;
                   filter: drop-shadow(0 0 24px rgba(240,180,41,1))
                           drop-shadow(0 0 55px rgba(240,180,41,0.45)); }
            100% { background-position: -400% center;
                   filter: drop-shadow(0 0 6px rgba(240,180,41,0.3)); }
        }

        .bob-shell {
            padding: 1.1rem 0 1.5rem 0;
            border-bottom: 1px solid rgba(240,180,41,0.22);
            margin-bottom: 1.3rem;
        }
        .bob-wordmark {
            font-size: 4rem;
            font-weight: 900;
            line-height: 1;
            letter-spacing: 0.2em;
            font-family: Georgia, "Times New Roman", serif;

            /* Gold gradient that slides across the text */
            background: linear-gradient(
                90deg,
                #5c3d00  0%,
                #b87c0a 18%,
                #F0B429 35%,
                #FFE066 50%,
                #F0B429 65%,
                #b87c0a 82%,
                #5c3d00 100%
            );
            background-size: 400% auto;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: bobShimmer 4s ease-in-out infinite;
        }
        .bob-tagline {
            margin-top: 0.45rem;
            font-size: 1rem;
            color: #94a3b8;
            font-weight: 400;
            letter-spacing: 0.04em;
        }

        /* ── Pillar badges ──────────────────────────────────────────────────── */
        .bob-pillars {
            display: flex;
            gap: 0.55rem;
            margin-top: 0.9rem;
            flex-wrap: wrap;
        }
        .pillar {
            display: inline-block;
            padding: 0.24rem 0.85rem;
            border-radius: 2rem;
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.03em;
        }
        .p-risk    { background: rgba(248,113,113,0.1); color: #fca5a5; border: 1px solid rgba(248,113,113,0.3); }
        .p-invest  { background: rgba(52,211,153,0.1);  color: #6ee7b7; border: 1px solid rgba(52,211,153,0.3); }
        .p-protect { background: rgba(147,197,253,0.1); color: #93c5fd; border: 1px solid rgba(147,197,253,0.3); }
        </style>

        <div class="bob-shell">
            <div class="bob-wordmark">BOB</div>
            <div class="bob-tagline">Bonga na BOB &mdash; Save smart. Invest smart. Risk smart.</div>
            <div class="bob-pillars">
                <span class="pillar p-risk">🎯 Risk &nbsp;·&nbsp; Betting &amp; Forex</span>
                <span class="pillar p-invest">💰 Investment &nbsp;·&nbsp; Insurance</span>
                <span class="pillar p-protect">🛡️ Protection &nbsp;·&nbsp; Coming soon</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Sidebar
# =============================================================================
def render_sidebar() -> str:
    st.sidebar.markdown("### BOB")
    st.sidebar.caption("Bonga na BOB")

    page = st.sidebar.radio(
        "Navigate",
        options=[PAGE_OVERVIEW, PAGE_BOOKMAKER, PAGE_FOREBET, PAGE_POLYMARKET, PAGE_RESULTS, PAGE_CANONICAL, PAGE_SIMULATION, PAGE_HISTORY, PAGE_INSURANCE],
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")

    if st.sidebar.button("🔄  Refresh Data", use_container_width=True):
        clear_all_caches()
        st.session_state["last_refreshed"] = datetime.now(UTC)
        st.rerun()

    last = st.session_state.get("last_refreshed")
    if last:
        st.sidebar.caption(f"Refreshed at {last.strftime('%H:%M:%S')} UTC")
    else:
        st.sidebar.caption("Data cached for 2 min · click to refresh")

    return page


# =============================================================================
# Shared helpers
# =============================================================================
def safe_table_exists(table_name: str) -> bool:
    try:
        return table_exists(table_name)
    except Exception:
        return False


def safe_rows(loader, *args, **kwargs) -> list[Any]:
    try:
        return loader(*args, **kwargs)
    except Exception as exc:
        st.error(f"Database read failed: {exc}")
        return []


SIMULATION_TIER_BUCKETS = {
    "Gold": ["80-90%", "90-100%"],
    "Silver": ["60-70%", "70-80%"],
    "Bronze": ["<40%", "40-50%", "50-60%"],
}


def _probability_bucket(probability: float | int | None) -> str | None:
    if probability is None:
        return None
    value = float(probability)
    if value < 40:
        return "<40%"
    if value < 50:
        return "40-50%"
    if value < 60:
        return "50-60%"
    if value < 70:
        return "60-70%"
    if value < 80:
        return "70-80%"
    if value < 90:
        return "80-90%"
    return "90-100%"


def _tier_for_bucket(bucket: str | None) -> str:
    if not bucket:
        return "Unclassified"
    for tier_name, tier_buckets in SIMULATION_TIER_BUCKETS.items():
        if bucket in tier_buckets:
            return tier_name
    return "Unclassified"


def _prepare_simulation_rows(
    raw_rows: list[dict[str, Any]],
    bookmaker_mode: str,
    *,
    fallback_odds: float = 1.5,
) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}

    for raw_row in raw_rows:
        evaluation_id = int(raw_row["evaluation_id"])
        row = grouped.get(evaluation_id)
        if row is None:
            bucket = _probability_bucket(raw_row.get("pred_probability"))
            row = {
                "evaluation_id": evaluation_id,
                "canonical_fixture_id": raw_row.get("canonical_fixture_id"),
                "sport": raw_row.get("sport"),
                "event_date": raw_row.get("event_date"),
                "display_league": raw_row.get("display_league"),
                "display_home_team": raw_row.get("display_home_team"),
                "display_away_team": raw_row.get("display_away_team"),
                "pred_outcome": raw_row.get("pred_outcome"),
                "pred_probability": float(raw_row.get("pred_probability") or 0.0),
                "pred_hit": bool(raw_row.get("pred_hit")),
                "result_source_used": raw_row.get("result_source_used"),
                "probability_bucket": bucket,
                "tier": _tier_for_bucket(bucket),
                "odds_by_source": {},
            }
            grouped[evaluation_id] = row

        bookmaker_source = raw_row.get("bookmaker_source")
        odds_value = raw_row.get("predicted_outcome_odds")
        if bookmaker_source and odds_value not in (None, "", 0):
            odds_float = float(odds_value)
            current_value = row["odds_by_source"].get(bookmaker_source)
            if current_value is None or odds_float > current_value:
                row["odds_by_source"][bookmaker_source] = odds_float

    prepared_rows: list[dict[str, Any]] = []
    for row in grouped.values():
        odds_by_source = row.pop("odds_by_source")
        selected_odds = None
        selected_bookmaker = None

        if bookmaker_mode == "Best Available":
            if odds_by_source:
                selected_bookmaker, selected_odds = max(odds_by_source.items(), key=lambda item: item[1])
        else:
            selected_odds = odds_by_source.get(bookmaker_mode.lower())
            selected_bookmaker = bookmaker_mode.lower() if selected_odds is not None else None

        if selected_odds is None or selected_odds <= 1:
            selected_odds = float(fallback_odds)
            selected_bookmaker = "fallback_1.50"
            row["used_fallback_odds"] = True
        else:
            row["used_fallback_odds"] = False

        row["selected_odds"] = float(selected_odds)
        row["selected_bookmaker"] = selected_bookmaker
        row["has_linked_bookmaker_odds"] = not bool(row["used_fallback_odds"])
        row["linked_bookmaker_count"] = len(odds_by_source)
        prepared_rows.append(row)

    prepared_rows.sort(
        key=lambda row: (
            str(row.get("probability_bucket") or ""),
            str(row.get("event_date") or ""),
            int(row.get("evaluation_id") or 0),
        )
    )
    return prepared_rows


def _simulate_bucket_slips(rows: list[dict[str, Any]], *, slip_size: int, stake_per_slip: float) -> dict[str, Any] | None:
    if len(rows) < slip_size:
        return None

    full_slip_game_count = (len(rows) // slip_size) * slip_size
    if full_slip_game_count <= 0:
        return None

    usable_rows = rows[:full_slip_game_count]
    slips = [usable_rows[index : index + slip_size] for index in range(0, full_slip_game_count, slip_size)]
    if not slips:
        return None

    expected_wins = 0.0
    expected_payout = 0.0
    actual_wins = 0
    actual_payout = 0.0

    for slip in slips:
        combined_odds = math.prod(float(game["selected_odds"]) for game in slip)
        win_probability = math.prod(float(game["pred_probability"]) / 100.0 for game in slip)
        expected_wins += win_probability
        expected_payout += stake_per_slip * combined_odds * win_probability

        if all(bool(game["pred_hit"]) for game in slip):
            actual_wins += 1
            actual_payout += stake_per_slip * combined_odds

    slips_formed = len(slips)
    total_staked = slips_formed * stake_per_slip
    expected_net = expected_payout - total_staked
    actual_net = actual_payout - total_staked

    return {
        "games_available": len(rows),
        "slip_size": slip_size,
        "slips_formed": slips_formed,
        "stake_per_slip": stake_per_slip,
        "total_staked": total_staked,
        "expected_wins": expected_wins,
        "expected_payout": expected_payout,
        "expected_net_pnl": expected_net,
        "expected_roi_pct": (expected_net / total_staked * 100.0) if total_staked else 0.0,
        "actual_wins": actual_wins,
        "actual_payout": actual_payout,
        "actual_net_pnl": actual_net,
        "actual_hit_rate_pct": (actual_wins / slips_formed * 100.0) if slips_formed else 0.0,
        "actual_roi_pct": (actual_net / total_staked * 100.0) if total_staked else 0.0,
    }


def _build_simulation_outputs(
    raw_rows: list[dict[str, Any]],
    *,
    bookmaker_mode: str,
    slip_sizes: list[int],
    stake_per_slip: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prepared_rows = _prepare_simulation_rows(raw_rows, bookmaker_mode)
    if not prepared_rows:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    bucket_rows: list[dict[str, Any]] = []
    rows_by_bucket: dict[str, list[dict[str, Any]]] = {}
    for row in prepared_rows:
        rows_by_bucket.setdefault(str(row["probability_bucket"]), []).append(row)

    bucket_order = ["<40%", "40-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
    for bucket in bucket_order:
        bucket_games = rows_by_bucket.get(bucket, [])
        if not bucket_games:
            continue
        for slip_size in slip_sizes:
            result = _simulate_bucket_slips(bucket_games, slip_size=slip_size, stake_per_slip=stake_per_slip)
            if result is None:
                continue
            result["probability_bucket"] = bucket
            result["tier"] = _tier_for_bucket(bucket)
            bucket_rows.append(result)

    bucket_frame = pd.DataFrame(bucket_rows)
    if bucket_frame.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    games_per_tier = (
        pd.DataFrame(prepared_rows)[["evaluation_id", "tier"]]
        .drop_duplicates()
        .groupby("tier", as_index=False)
        .agg(games_available=("evaluation_id", "count"))
    )

    tier_rollup = (
        bucket_frame.groupby(["tier", "slip_size"], as_index=False)
        .agg(
            slips_formed=("slips_formed", "sum"),
            total_staked=("total_staked", "sum"),
            expected_wins=("expected_wins", "sum"),
            expected_payout=("expected_payout", "sum"),
            expected_net_pnl=("expected_net_pnl", "sum"),
            actual_wins=("actual_wins", "sum"),
            actual_payout=("actual_payout", "sum"),
            actual_net_pnl=("actual_net_pnl", "sum"),
        )
    )
    tier_rollup["expected_roi_pct"] = (
        tier_rollup["expected_net_pnl"] / tier_rollup["total_staked"].replace(0, pd.NA) * 100.0
    ).fillna(0.0)
    tier_rollup["actual_roi_pct"] = (
        tier_rollup["actual_net_pnl"] / tier_rollup["total_staked"].replace(0, pd.NA) * 100.0
    ).fillna(0.0)
    tier_rollup["actual_hit_rate_pct"] = (
        tier_rollup["actual_wins"] / tier_rollup["slips_formed"].replace(0, pd.NA) * 100.0
    ).fillna(0.0)

    recommended_rows: list[dict[str, Any]] = []
    for tier_name, tier_buckets in SIMULATION_TIER_BUCKETS.items():
        tier_subset = tier_rollup[tier_rollup["tier"] == tier_name]
        if tier_subset.empty:
            continue
        best_row = tier_subset.sort_values(["actual_roi_pct", "actual_net_pnl"], ascending=[False, False]).iloc[0]
        games_row = games_per_tier[games_per_tier["tier"] == tier_name]
        games_available = int(games_row["games_available"].iloc[0]) if not games_row.empty else 0
        recommended_rows.append(
            {
                "tier": tier_name,
                "buckets": ", ".join(tier_buckets),
                "games_available": games_available,
                "recommended_slip_size": int(best_row["slip_size"]),
                "actual_roi_pct": float(best_row["actual_roi_pct"]),
                "expected_roi_pct": float(best_row["expected_roi_pct"]),
                "actual_hit_rate_pct": float(best_row["actual_hit_rate_pct"]),
            }
        )

    tier_frame = pd.DataFrame(recommended_rows)
    return pd.DataFrame(prepared_rows), bucket_frame, tier_frame


def _resolve_selected_buckets(selected_tier: str, custom_buckets: list[str]) -> list[str]:
    if selected_tier == "All":
        return ["<40%", "40-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
    if selected_tier == "Custom":
        return custom_buckets
    return SIMULATION_TIER_BUCKETS.get(selected_tier, [])


def _filter_prepared_simulation_rows(
    rows: list[dict[str, Any]],
    *,
    selected_buckets: list[str],
    date_from: date | None,
    date_to: date | None,
) -> list[dict[str, Any]]:
    filtered_rows: list[dict[str, Any]] = []
    selected_bucket_set = set(selected_buckets)

    for row in rows:
        event_date = row.get("event_date")
        if selected_bucket_set and row.get("probability_bucket") not in selected_bucket_set:
            continue
        if date_from and event_date and event_date < date_from:
            continue
        if date_to and event_date and event_date > date_to:
            continue
        filtered_rows.append(row)

    filtered_rows.sort(
        key=lambda row: (
            row.get("event_date") or date.min,
            str(row.get("probability_bucket") or ""),
            int(row.get("evaluation_id") or 0),
        )
    )
    return filtered_rows


def _build_simulation_slip_ledger(
    rows: list[dict[str, Any]],
    *,
    slip_size: int,
    stake_per_slip: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    if not rows:
        return pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame()

    rows_by_date: dict[date, list[dict[str, Any]]] = {}
    for row in rows:
        event_date = row.get("event_date")
        if isinstance(event_date, date):
            rows_by_date.setdefault(event_date, []).append(row)

    ledger_rows: list[dict[str, Any]] = []
    leftover_rows: list[dict[str, Any]] = []
    bucket_summary_rows: list[dict[str, Any]] = []
    slip_counter = 1

    total_winning_payout = 0.0
    total_losing_stake = 0.0
    total_staked = 0.0
    won_slips = 0
    lost_slips = 0
    total_game_wins = sum(1 for row in rows if bool(row.get("pred_hit")))
    total_game_losses = sum(1 for row in rows if not bool(row.get("pred_hit")))
    bookmaker_odds_games = sum(1 for row in rows if bool(row.get("has_linked_bookmaker_odds")))
    fallback_odds_games = sum(1 for row in rows if bool(row.get("used_fallback_odds")))
    games_used_in_slips = 0
    combined_odds_values: list[float] = []

    for event_date in sorted(rows_by_date):
        date_rows = rows_by_date[event_date]

        bucket_counts: dict[str, dict[str, int]] = {}
        for game in date_rows:
            bucket = str(game.get("probability_bucket") or "Unknown")
            bucket_counts.setdefault(bucket, {"games": 0, "won": 0, "lost": 0})
            bucket_counts[bucket]["games"] += 1
            if bool(game.get("has_linked_bookmaker_odds")):
                bucket_counts[bucket]["bookmaker_odds_games"] = bucket_counts[bucket].get("bookmaker_odds_games", 0) + 1
            if bool(game.get("used_fallback_odds")):
                bucket_counts[bucket]["fallback_odds_games"] = bucket_counts[bucket].get("fallback_odds_games", 0) + 1
            if bool(game.get("pred_hit")):
                bucket_counts[bucket]["won"] += 1
            else:
                bucket_counts[bucket]["lost"] += 1

        for bucket_name, counts in bucket_counts.items():
            bucket_summary_rows.append(
                {
                    "event_date": event_date,
                    "probability_bucket": bucket_name,
                    "games": counts["games"],
                    "won": counts["won"],
                    "lost": counts["lost"],
                    "bookmaker_odds_games": counts.get("bookmaker_odds_games", 0),
                    "fallback_odds_games": counts.get("fallback_odds_games", 0),
                    "win_pct": (counts["won"] / counts["games"] * 100.0) if counts["games"] else 0.0,
                }
            )

        actual_leg_count = min(len(date_rows), slip_size)
        slip_rows = date_rows[:actual_leg_count]
        leftover_games = date_rows[actual_leg_count:]
        games_used_in_slips += len(slip_rows)

        for leftover in leftover_games:
            leftover_rows.append(
                {
                    "event_date": event_date,
                    "probability_bucket": leftover.get("probability_bucket"),
                    "home_team": leftover.get("display_home_team"),
                    "away_team": leftover.get("display_away_team"),
                    "pred_probability": leftover.get("pred_probability"),
                    "selected_odds": leftover.get("selected_odds"),
                    "selected_bookmaker": leftover.get("selected_bookmaker"),
                    "used_fallback_odds": leftover.get("used_fallback_odds"),
                }
            )

        if not slip_rows:
            continue

        combined_odds = math.prod(float(game["selected_odds"]) for game in slip_rows)
        combined_odds_values.append(combined_odds)
        win_probability = math.prod(float(game["pred_probability"]) / 100.0 for game in slip_rows)
        total_staked += stake_per_slip
        won = all(bool(game["pred_hit"]) for game in slip_rows)
        payout = stake_per_slip * combined_odds if won else 0.0
        net_pnl = payout - stake_per_slip

        if won:
            won_slips += 1
            total_winning_payout += payout
        else:
            lost_slips += 1
            total_losing_stake += stake_per_slip

        failed_legs = [
            f'{game["display_home_team"]} vs {game["display_away_team"]}'
            for game in slip_rows
            if not bool(game["pred_hit"])
        ]
        leg_summary = " | ".join(
            f'{game["display_home_team"]} vs {game["display_away_team"]} ({game["selected_odds"]:.2f})'
            for game in slip_rows
        )
        bucket_mix = ", ".join(str(game.get("probability_bucket") or "") for game in slip_rows)
        odds_sources = " | ".join(
            f'{game["display_home_team"]} vs {game["display_away_team"]}: {game["selected_bookmaker"]}'
            for game in slip_rows
        )

        ledger_rows.append(
            {
                "slip_id": f"{event_date.isoformat()}-1",
                "event_date": event_date,
                "slip_sequence": slip_counter,
                "slip_size": len(slip_rows),
                "target_slip_size": slip_size,
                "bucket_mix": bucket_mix,
                "legs": leg_summary,
                "odds_sources": odds_sources,
                "combined_odds": combined_odds,
                "stake": stake_per_slip,
                "expected_win_probability_pct": win_probability * 100.0,
                "result": "Won" if won else "Lost",
                "payout": payout,
                "net_pnl": net_pnl,
                "failed_legs": ", ".join(failed_legs) if failed_legs else "",
            }
        )
        slip_counter += 1

    ledger_frame = pd.DataFrame(ledger_rows)
    leftover_frame = pd.DataFrame(leftover_rows)
    bucket_summary_frame = pd.DataFrame(bucket_summary_rows)

    summary = {
        "games_selected": len(rows),
        "game_wins": total_game_wins,
        "game_losses": total_game_losses,
        "game_win_rate_pct": (total_game_wins / len(rows) * 100.0) if rows else 0.0,
        "bookmaker_odds_games": bookmaker_odds_games,
        "fallback_odds_games": fallback_odds_games,
        "games_used_in_slips": games_used_in_slips,
        "slips_formed": len(ledger_rows),
        "leftover_games": len(leftover_rows),
        "amount_earned": total_winning_payout,
        "amount_lost": total_losing_stake,
        "net_pnl": total_winning_payout - total_staked,
        "roi_pct": ((total_winning_payout - total_staked) / total_staked * 100.0) if total_staked else 0.0,
        "won_slips": won_slips,
        "lost_slips": lost_slips,
        "slip_win_rate_pct": (won_slips / len(ledger_rows) * 100.0) if ledger_rows else 0.0,
        "total_staked": total_staked,
        "average_combined_odds": (sum(combined_odds_values) / len(combined_odds_values)) if combined_odds_values else 0.0,
        "break_even_slip_hit_rate_pct": ((1 / (sum(combined_odds_values) / len(combined_odds_values))) * 100.0)
        if combined_odds_values and (sum(combined_odds_values) / len(combined_odds_values)) > 0
        else 0.0,
    }
    return ledger_frame, leftover_frame, summary, bucket_summary_frame


def render_daily_ingestion_controls() -> None:
    st.markdown("### Daily Ingestion")
    st.caption("Run the current BoB daily ETL batch manually from the dashboard.")

    with st.expander("Open ingestion controls", expanded=False):
        try:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
            etl_module = importlib.import_module("ganji_mtaani_agent.etl.daily_ingestion")
            etl_module = importlib.reload(etl_module)
            DailyIngestionConfig = etl_module.DailyIngestionConfig
            run_daily_ingestion = etl_module.run_daily_ingestion
            get_daily_task_catalog = etl_module.get_daily_task_catalog
            task_catalog = get_daily_task_catalog()
        except Exception as exc:
            st.error(f"Could not load the ingestion runner: {exc}")
            return

        task_name_to_label = {row["task_name"]: row["display_name"] for row in task_catalog}
        all_task_names = list(task_name_to_label)
        default_task_names = st.session_state.get("daily_selected_tasks", all_task_names)

        c1, c2 = st.columns([1, 1.2])
        batch_date = c1.date_input("Batch date", value=date.today(), key="daily_batch_date")
        triggered_by = c2.text_input(
            "Triggered by",
            value="streamlit_manual",
            key="daily_triggered_by",
        )
        selected_task_names = st.multiselect(
            "Tasks to run",
            options=all_task_names,
            default=default_task_names,
            format_func=lambda task_name: task_name_to_label.get(task_name, task_name),
            key="daily_selected_tasks",
            help="Leave all selected for a full run, or pick only the tasks you want to rerun.",
        )
        if st.button("Run Daily Ingestion", key="run_daily_ingestion", use_container_width=True):
            if not selected_task_names:
                st.warning("Select at least one ingestion task before running the batch.")
                return
            with st.spinner("Running selected BoB ingestion tasks..."):
                summary = run_daily_ingestion(
                    DailyIngestionConfig(
                        batch_date=batch_date,
                        triggered_by=triggered_by or "streamlit_manual",
                        selected_tasks=tuple(selected_task_names),
                    )
                )
            clear_all_caches()
            st.session_state["last_daily_ingestion_summary"] = summary
            st.success(
                "Daily ingestion finished with status "
                f"{summary['status']} for batch {summary['batch_id']}."
            )

    last_summary = st.session_state.get("last_daily_ingestion_summary")
    if last_summary:
        st.caption("Latest manual ingestion summary")
        st.dataframe(
            last_summary["outcomes"],
            use_container_width=True,
            hide_index=True,
        )

    if safe_table_exists("ingestion_batches"):
        recent_batches = safe_rows(fetch_latest_ingestion_batches, limit=10)
        if recent_batches:
            st.caption("Recent ingestion batches")
            st.dataframe(recent_batches, use_container_width=True, hide_index=True)


# =============================================================================
# Overview Page
# =============================================================================
def render_overview_page() -> None:
    st.subheader("Overview")
    st.caption("Pipeline health, storage readiness, and source coverage at a glance.")
    render_daily_ingestion_controls()

    source_runs_ok     = safe_table_exists("source_runs")
    bookmaker_ok       = safe_table_exists("bookmaker_odds")
    results_ok         = safe_table_exists("sports_results")
    forebet_results_ok = safe_table_exists("forebet_results")
    flashscore_results_ok = safe_table_exists("flashscore_results")
    forebet_ok         = safe_table_exists("forebet_predictions")
    polymarket_ok      = safe_table_exists("polymarket_markets")

    run_summary       = safe_rows(fetch_source_run_summary)      if source_runs_ok else []
    latest_runs       = safe_rows(fetch_latest_source_runs, limit=12) if source_runs_ok else []
    bookmaker_summary      = safe_rows(fetch_bookmaker_summary)       if bookmaker_ok       else []
    results_summary        = safe_rows(fetch_sports_results_summary)  if results_ok         else []
    forebet_results_summary = safe_rows(fetch_forebet_results_summary) if forebet_results_ok else []
    flashscore_results_summary = safe_rows(fetch_flashscore_results_summary) if flashscore_results_ok else []
    forebet_summary        = safe_rows(fetch_forebet_summary)         if forebet_ok         else []
    polymarket_summary     = safe_rows(fetch_polymarket_summary)      if polymarket_ok      else []
    table_inventory        = safe_rows(fetch_table_inventory)

    total_runs      = sum(int(r.get("total_runs",     0)) for r in run_summary)
    successful_runs = sum(int(r.get("successful_runs",0)) for r in run_summary)
    failed_runs     = sum(int(r.get("failed_runs",    0)) for r in run_summary)
    bookmaker_rows      = sum(int(r.get("row_count", 0)) for r in bookmaker_summary)
    forebet_result_rows = sum(int(r.get("row_count", 0)) for r in forebet_results_summary)
    flashscore_result_rows = sum(int(r.get("row_count", 0)) for r in flashscore_results_summary)
    forebet_rows        = sum(int(r.get("row_count", 0)) for r in forebet_summary)
    polymarket_rows     = sum(int(r.get("row_count", 0)) for r in polymarket_summary)

    # ── Metric row ──────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
    m1.metric("Total Runs",      total_runs)
    m2.metric("Successful",      successful_runs)
    m3.metric("Failed",          failed_runs,
              delta=f"-{failed_runs}" if failed_runs else None,
              delta_color="inverse")
    m4.metric("Bookmaker Rows",  bookmaker_rows)
    m5.metric("Forebet Rows",    forebet_rows)
    m6.metric("Polymarket Rows", polymarket_rows)
    m7.metric("Forebet Results", forebet_result_rows)
    m8.metric("Flashscore Results", flashscore_result_rows)

    # ── Source coverage table ────────────────────────────────────────────────
    st.markdown("### Source Coverage")
    run_by_source = {r["source_name"]: r for r in run_summary}
    coverage: list[dict[str, Any]] = []
    for item in SOURCE_FAMILY_CATALOG:
        sr = run_by_source.get(item["source_name"], {})
        coverage.append({
            "source":     item["display_name"],
            "role":       item["role"],
            "table":      item["table_name"],
            "db_ready":   "✅ yes" if safe_table_exists(item["table_name"]) else "⏳ pending",
            "runs":       int(sr.get("total_runs",             0)),
            "ok":         int(sr.get("successful_runs",        0)),
            "failed":     int(sr.get("failed_runs",            0)),
            "last_run":   sr.get("latest_started_at"),
            "records":    int(sr.get("cumulative_records_found", 0)),
        })
    st.dataframe(
        coverage,
        use_container_width=True,
        hide_index=True,
        column_config={
            "source":   "Source",
            "role":     "Role",
            "table":    "Table",
            "db_ready": st.column_config.TextColumn("DB Ready", width="small"),
            "runs":     st.column_config.NumberColumn("Runs",    width="small"),
            "ok":       st.column_config.NumberColumn("✓ OK",    width="small"),
            "failed":   st.column_config.NumberColumn("✗ Fail",  width="small"),
            "last_run": st.column_config.DatetimeColumn("Last Run"),
            "records":  st.column_config.NumberColumn("Records"),
        },
    )

    # ── Charts ───────────────────────────────────────────────────────────────
    if run_summary or bookmaker_summary:
        cl, cr = st.columns(2)

        with cl:
            if run_summary:
                st.markdown("### Run Activity")
                df = (
                    pd.DataFrame(run_summary)[["source_name", "successful_runs", "failed_runs"]]
                    .set_index("source_name")
                    .astype(int)
                    .rename(columns={"successful_runs": "✓ Successful", "failed_runs": "✗ Failed"})
                )
                st.bar_chart(df, color=["#10b981", "#ef4444"])

        with cr:
            if bookmaker_summary:
                st.markdown("### Records by Source")
                bdf = pd.DataFrame(bookmaker_summary)
                bdf["label"] = bdf["source_name"].str.title() + " / " + bdf["sport"].str.title()
                bdf = bdf.set_index("label")[["row_count"]].rename(columns={"row_count": "Rows"})
                st.bar_chart(bdf, color=["#F0B429"])

    # ── Detail tables ────────────────────────────────────────────────────────
    left, right = st.columns([1.3, 1])

    with left:
        st.markdown("### Latest Runs")
        if latest_runs:
            st.dataframe(
                latest_runs,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id":             st.column_config.NumberColumn("ID",      width="small"),
                    "source_name":    "Source",
                    "target_name":    "Target",
                    "source_type":    "Type",
                    "status":         "Status",
                    "started_at":     st.column_config.DatetimeColumn("Started"),
                    "finished_at":    st.column_config.DatetimeColumn("Finished"),
                    "duration_ms":    st.column_config.NumberColumn("ms"),
                    "records_found":  st.column_config.NumberColumn("Records"),
                    "warnings_count": st.column_config.NumberColumn("Warns", width="small"),
                    "error_message":  "Error",
                },
            )
        else:
            st.info("No source run records yet.")

    with right:
        st.markdown("### DB Tables")
        if table_inventory:
            st.dataframe(table_inventory, use_container_width=True, hide_index=True)
        else:
            st.info("No public tables found.")

        for caption, summary, cfg in [
            ("Bookmaker rows · source / sport", bookmaker_summary, {
                "source_name": "Source", "sport": "Sport",
                "row_count": st.column_config.NumberColumn("Rows"),
                "latest_created_at": st.column_config.DatetimeColumn("Last Scraped"),
            }),
            ("Forebet rows · sport", forebet_summary, {}),
            ("Forebet results · sport / status", forebet_results_summary, {}),
            ("Flashscore results · sport / status", flashscore_results_summary, {}),
            ("Polymarket rows · category", polymarket_summary, {}),
            ("Results rows · sport / status", results_summary, {
                "sport": "Sport", "status": "Status",
                "row_count": st.column_config.NumberColumn("Rows"),
                "latest_event_date": st.column_config.DateColumn("Latest"),
            }),
        ]:
            if summary:
                st.caption(caption)
                st.dataframe(summary, use_container_width=True, hide_index=True, column_config=cfg)


# =============================================================================
# Bookmaker Odds Page
# =============================================================================
def render_bookmaker_page() -> None:
    st.subheader("Bookmaker Odds")
    st.caption("Unified odds view across Betika, SportPesa, and Mozzart.")

    if not safe_table_exists("bookmaker_odds"):
        st.warning("The `bookmaker_odds` table does not exist yet.")
        return

    source_options = ["All"] + safe_rows(fetch_bookmaker_source_options)
    sport_options  = ["All", "football", "basketball"]

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1.2, 1.6, 0.8])
    sel_source = c1.selectbox("Source", options=source_options)
    sel_sport  = c2.selectbox("Sport",  options=sport_options)
    league_options = ["All"] + safe_rows(
        fetch_bookmaker_league_options,
        None if sel_source == "All" else sel_source,
        None if sel_sport  == "All" else sel_sport,
    )
    sel_league  = c3.selectbox("League",           options=league_options)
    search_text = c4.text_input("Search team or league", value="")
    row_limit   = c5.number_input("Rows", min_value=10, max_value=1000, value=200, step=10)

    rows = safe_rows(
        fetch_bookmaker_odds,
        source_name=None if sel_source == "All" else sel_source,
        sport=None       if sel_sport  == "All" else sel_sport,
        league=None      if sel_league == "All" else sel_league,
        search_text=search_text or None,
        limit=int(row_limit),
    )

    st.metric("Matching Rows", len(rows))

    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id":                  st.column_config.NumberColumn("ID",      width="small"),
                "run_id":              None,
                "source_name":         "Source",
                "sport":               "Sport",
                "league":              "League",
                "event_datetime_text": "Match Time",
                "home_team":           "Home",
                "away_team":           "Away",
                "game_id":             None,
                "match_status":        "Status",
                "score_text":          "Score",
                "market_type":         "Market",
                "home_odds":           st.column_config.NumberColumn("1",       format="%.2f"),
                "draw_odds":           st.column_config.NumberColumn("X",       format="%.2f"),
                "away_odds":           st.column_config.NumberColumn("2",       format="%.2f"),
                "home_or_draw_odds":   st.column_config.NumberColumn("1X",      format="%.2f"),
                "draw_or_away_odds":   st.column_config.NumberColumn("X2",      format="%.2f"),
                "home_or_away_odds":   st.column_config.NumberColumn("12",      format="%.2f"),
                "over_2_5_odds":       st.column_config.NumberColumn("Ov2.5",   format="%.2f"),
                "under_2_5_odds":      st.column_config.NumberColumn("Un2.5",   format="%.2f"),
                "btts_yes_odds":       st.column_config.NumberColumn("BTTS Y",  format="%.2f"),
                "btts_no_odds":        st.column_config.NumberColumn("BTTS N",  format="%.2f"),
                "extra_market_count":  None,
                "confidence":          st.column_config.NumberColumn("Conf",    format="%.2f"),
                "created_at":          st.column_config.DatetimeColumn("Scraped At"),
            },
        )
    else:
        st.info("No bookmaker rows matched the current filters.")


# =============================================================================
# Forebet Predictions Page
# =============================================================================
def render_forebet_page() -> None:
    st.subheader("Forebet Predictions")
    st.caption("Structured football and basketball prediction rows captured from Forebet.")

    if not safe_table_exists("forebet_predictions"):
        st.warning("The `forebet_predictions` table does not exist yet.")
        return

    sport_options = ["All"] + safe_rows(fetch_forebet_sport_options)

    c1, c2, c3, c4 = st.columns([1, 1.4, 1.8, 0.8])
    sel_sport    = c1.selectbox("Sport",  options=sport_options)
    league_opts  = ["All"] + safe_rows(
        fetch_forebet_league_options,
        None if sel_sport == "All" else sel_sport,
    )
    sel_league   = c2.selectbox("League",                options=league_opts)
    search_text  = c3.text_input("Search team or league", value="")
    row_limit    = c4.number_input("Rows", min_value=10, max_value=1000, value=200, step=10, key="fb_limit")

    rows = safe_rows(
        fetch_forebet_predictions,
        sport=None  if sel_sport  == "All" else sel_sport,
        league=None if sel_league == "All" else sel_league,
        search_text=search_text or None,
        limit=int(row_limit),
    )

    st.metric("Matching Rows", len(rows))

    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id":                    None,
                "run_id":                None,
                "source":                "Source",
                "sport":                 "Sport",
                "league":                "League",
                "home_team":             "Home",
                "away_team":             "Away",
                "match_url":             st.column_config.LinkColumn("Match URL"),
                "event_datetime":        "Match Time",
                "prob_1":                st.column_config.NumberColumn("P(1) %",  format="%d"),
                "prob_x":                st.column_config.NumberColumn("P(X) %",  format="%d"),
                "prob_2":                st.column_config.NumberColumn("P(2) %",  format="%d"),
                "pred_outcome":          "Pred",
                "predicted_home_score":  st.column_config.NumberColumn("H Score", format="%d"),
                "predicted_away_score":  st.column_config.NumberColumn("A Score", format="%d"),
                "correct_score_text":    "Score",
                "avg_goals":             st.column_config.NumberColumn("Avg Goals", format="%.1f"),
                "weather":               "Weather",
                "coef_1":                st.column_config.NumberColumn("Coef 1",  format="%.2f"),
                "coef_x":                st.column_config.NumberColumn("Coef X",  format="%.2f"),
                "coef_2":                st.column_config.NumberColumn("Coef 2",  format="%.2f"),
                "avg_points":            st.column_config.NumberColumn("Avg Pts", format="%.1f"),
                "confidence":            st.column_config.NumberColumn("Conf",    format="%.2f"),
                "remaining_tokens":      None,
                "raw_text":              None,
                "created_at":            st.column_config.DatetimeColumn("Scraped At"),
            },
        )
    else:
        st.info("No Forebet rows matched the current filters.")


# =============================================================================
# Polymarket Markets Page
# =============================================================================
def render_polymarket_page() -> None:
    st.subheader("Polymarket Markets")
    st.caption("Normalized Gamma API markets with category, outcomes, and volume / liquidity.")

    if not safe_table_exists("polymarket_markets"):
        st.warning("The `polymarket_markets` table does not exist yet.")
        return

    category_options = ["All"] + safe_rows(fetch_polymarket_category_options)
    status_options   = ["All", "active", "closed", "archived"]

    c1, c2, c3, c4 = st.columns([1.2, 1, 1.8, 0.8])
    sel_category = c1.selectbox("Category", options=category_options)
    sel_status   = c2.selectbox("Status",   options=status_options)
    search_text  = c3.text_input("Search question, slug, or category", value="")
    row_limit    = c4.number_input("Rows", min_value=10, max_value=1000, value=200, step=10, key="pm_limit")

    rows = safe_rows(
        fetch_polymarket_markets,
        category=None if sel_category == "All" else sel_category,
        status=None   if sel_status   == "All" else sel_status,
        search_text=search_text or None,
        limit=int(row_limit),
    )

    st.metric("Matching Markets", len(rows))

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No Polymarket rows matched the current filters.")


# =============================================================================
# Sports Results Page
# =============================================================================
def render_results_page() -> None:
    st.subheader("Sports Results")
    st.caption("Ground-truth event schedule, status, and score view from TheSportsDB, Forebet, and Flashscore results.")

    sports_results_ok = safe_table_exists("sports_results")
    forebet_results_ok = safe_table_exists("forebet_results")
    flashscore_results_ok = safe_table_exists("flashscore_results")

    if not sports_results_ok and not forebet_results_ok and not flashscore_results_ok:
        st.warning("None of `sports_results`, `forebet_results`, or `flashscore_results` exists yet.")
        return

    result_source_options = ["TheSportsDB"] if sports_results_ok else []
    if forebet_results_ok:
        result_source_options.append("Forebet Results")
    if flashscore_results_ok:
        result_source_options.append("Flashscore Results")

    if flashscore_results_ok:
        default_source = "Flashscore Results"
    elif forebet_results_ok:
        default_source = "Forebet Results"
    else:
        default_source = result_source_options[0]

    c0, c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1.2, 1.8, 0.8])
    sel_source = c0.selectbox("Result Source", options=result_source_options, index=result_source_options.index(default_source))

    using_forebet_results = sel_source == "Forebet Results"
    using_flashscore_results = sel_source == "Flashscore Results"

    sport_options = ["All"] + safe_rows(
        fetch_forebet_results_sport_options if using_forebet_results
        else fetch_flashscore_results_sport_options if using_flashscore_results
        else fetch_results_sport_options
    )
    status_options = ["All"] + safe_rows(
        fetch_forebet_results_status_options if using_forebet_results
        else fetch_flashscore_results_status_options if using_flashscore_results
        else fetch_results_status_options
    )

    sel_sport   = c1.selectbox("Sport",  options=sport_options)
    sel_status  = c2.selectbox("Status", options=status_options)
    sel_date    = c3.date_input("Event date", value=None, help="Leave empty for all dates")
    search_text = c4.text_input("Search team, league, or event", value="")
    row_limit   = c5.number_input("Rows", min_value=10, max_value=1000, value=200, step=10, key="res_limit")

    if using_forebet_results:
        rows = safe_rows(
            fetch_forebet_results,
            sport=None      if sel_sport  == "All" else sel_sport,
            status=None     if sel_status == "All" else sel_status,
            event_date_text=sel_date.strftime("%d/%m/%Y") if sel_date else None,
            search_text=search_text or None,
            limit=int(row_limit),
        )
    elif using_flashscore_results:
        rows = safe_rows(
            fetch_flashscore_results,
            sport=None if sel_sport == "All" else sel_sport,
            status=None if sel_status == "All" else sel_status,
            page_date_text=sel_date.strftime("%d/%m") if sel_date else None,
            search_text=search_text or None,
            limit=int(row_limit),
        )
    else:
        rows = safe_rows(
            fetch_sports_results,
            sport=None      if sel_sport  == "All" else sel_sport,
            status=None     if sel_status == "All" else sel_status,
            event_date=sel_date.isoformat() if sel_date else None,
            search_text=search_text or None,
            limit=int(row_limit),
        )

    st.metric("Matching Results", len(rows))

    if rows:
        if using_forebet_results:
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id":                   None,
                    "run_id":               None,
                    "source_name":          "Source",
                    "sport":                "Sport",
                    "league":               "League",
                    "home_team":            "Home",
                    "away_team":            "Away",
                    "match_url":            st.column_config.LinkColumn("Match URL"),
                    "event_datetime_text":  "Match Time",
                    "pred_outcome":         "Pred",
                    "predicted_score_text": "Correct Score",
                    "actual_score_text":    "Score",
                    "actual_outcome":       "Actual",
                    "status":               "Status",
                    "pred_hit":             "Pred Hit",
                    "pred_indicator_class": "Forebet Signal",
                    "prob_1":               st.column_config.NumberColumn("P(1) %", format="%d"),
                    "prob_x":               st.column_config.NumberColumn("P(X) %", format="%d"),
                    "prob_2":               st.column_config.NumberColumn("P(2) %", format="%d"),
                    "confidence":           st.column_config.NumberColumn("Conf", format="%.2f"),
                    "created_at":           None,
                },
            )
        elif using_flashscore_results:
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id":                None,
                    "run_id":            None,
                    "source_name":       "Source",
                    "sport":             "Sport",
                    "page_date_text":    "Page Date",
                    "country_or_region": "Country / Region",
                    "league":            "League",
                    "match_status":      "Status",
                    "event_time_text":   "Time",
                    "home_team":         "Home",
                    "away_team":         "Away",
                    "home_score":        st.column_config.NumberColumn("H", width="small"),
                    "away_score":        st.column_config.NumberColumn("A", width="small"),
                    "confidence":        st.column_config.NumberColumn("Conf", format="%.2f"),
                    "created_at":        None,
                },
            )
        else:
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id":          None,
                    "run_id":      None,
                    "source_name": "Source",
                    "sport":       "Sport",
                    "event_id":    "Event ID",
                    "league_id":   None,
                    "league":      "League",
                    "season":      "Season",
                    "event_name":  "Match",
                    "event_date":  st.column_config.DateColumn("Date"),
                    "event_time":  "Time",
                    "home_team":   "Home",
                    "away_team":   "Away",
                    "home_score":  st.column_config.NumberColumn("H", width="small"),
                    "away_score":  st.column_config.NumberColumn("A", width="small"),
                    "status":      "Status",
                    "progress":    "Progress",
                    "venue":       "Venue",
                    "winner":      "Winner",
                    "confidence":  st.column_config.NumberColumn("Conf", format="%.2f"),
                    "created_at":  None,
                },
            )
    else:
        st.info("No results matched the current filters.")


# =============================================================================
# Canonical Fixtures Page
# =============================================================================
def render_canonical_page() -> None:
    st.subheader("Canonical Fixtures")
    st.caption("Standardized fixture layer across bookmakers, Forebet, Flashscore, and results sources for monitoring and modelling.")

    if not safe_table_exists("canonical_fixtures") or not safe_table_exists("fixture_source_links"):
        st.warning("Canonical fixture tables are not available yet. Apply the canonical schema and run fixture linking first.")
        return

    sport_options = ["All", "Football", "Basketball"]
    source_options = ["All"] + safe_rows(fetch_canonical_source_options)

    c1, c2, c3 = st.columns([1, 1, 2])
    selected_sport = c1.selectbox("Sport", options=sport_options, key="canonical_sport")
    selected_source = c2.selectbox("Source", options=source_options, key="canonical_source")
    search_text = c3.text_input("Search team or league", value="", key="canonical_search")

    sport_filter = None if selected_sport == "All" else selected_sport
    source_filter = None if selected_source == "All" else selected_source
    search_filter = search_text or None

    summary = fetch_canonical_summary(
        sport=sport_filter,
        source_name=source_filter,
        search_text=search_filter,
    )

    total_games = int(summary.get("total_games") or 0)
    total_predicted = int(summary.get("total_games_predicted") or 0)
    total_results = int(summary.get("total_results") or 0)
    total_won = int(summary.get("total_won") or 0)
    total_lost = int(summary.get("total_lost") or 0)
    pct_won = float(summary.get("pct_won") or 0.0)
    pct_lost = float(summary.get("pct_lost") or 0.0)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total Games", total_games)
    m2.metric("Games Predicted", total_predicted)
    m3.metric("Results Rows", total_results)
    m4.metric("Won", total_won)
    m5.metric("Lost", total_lost)
    m6.metric("Win Rate", f"{pct_won:.2f}%", delta=f"Loss {pct_lost:.2f}%")

    probability_rows = safe_rows(
        fetch_canonical_probability_breakdown,
        sport=sport_filter,
        source_name=source_filter,
        search_text=search_filter,
    )
    if probability_rows:
        st.markdown("### Forebet Probability Buckets")
        probability_frame = pd.DataFrame(probability_rows)
        probability_frame["win_pct"] = (
            probability_frame["won_count"] / probability_frame["total_decided"].replace(0, pd.NA) * 100.0
        ).fillna(0.0)
        probability_frame["loss_pct"] = 100.0 - probability_frame["win_pct"]
        chart_frame = probability_frame.melt(
            id_vars=["probability_bucket"],
            value_vars=["won_count", "lost_count"],
            var_name="outcome_type",
            value_name="match_count",
        )
        chart_frame["outcome_type"] = chart_frame["outcome_type"].map(
            {"won_count": "Won", "lost_count": "Lost"}
        )
        bar_chart = (
            alt.Chart(chart_frame)
            .mark_bar()
            .encode(
                x=alt.X("probability_bucket:N", title="Probability Bucket", sort=None),
                y=alt.Y("match_count:Q", title="Match Count"),
                color=alt.Color(
                    "outcome_type:N",
                    title="Outcome",
                    scale=alt.Scale(domain=["Won", "Lost"], range=["#2563eb", "#dc2626"]),
                ),
                tooltip=["probability_bucket", "outcome_type", "match_count"],
            )
        )
        line_base = alt.Chart(probability_frame).encode(
            x=alt.X("probability_bucket:N", sort=None),
            y=alt.Y(
                "win_pct:Q",
                title="Win Rate (%)",
                axis=alt.Axis(orient="right", format=".0f"),
                scale=alt.Scale(domain=[0, 100]),
            ),
            tooltip=[
                alt.Tooltip("probability_bucket:N", title="Probability Bucket"),
                alt.Tooltip("won_count:Q", title="Won"),
                alt.Tooltip("lost_count:Q", title="Lost"),
                alt.Tooltip("total_decided:Q", title="Decided"),
                alt.Tooltip("win_pct:Q", title="Win %", format=".1f"),
                alt.Tooltip("loss_pct:Q", title="Loss %", format=".1f"),
            ],
        )
        win_rate_line = line_base.mark_line(color="#f59e0b", point=True, strokeWidth=3)
        win_rate_labels = line_base.mark_text(
            color="#f8fafc",
            dy=-12,
            fontSize=12,
        ).encode(text=alt.Text("win_pct:Q", format=".0f"))
        probability_chart = alt.layer(bar_chart, win_rate_line, win_rate_labels).resolve_scale(y="independent")
        st.altair_chart(probability_chart, use_container_width=True)
        st.dataframe(
            probability_frame,
            use_container_width=True,
            hide_index=True,
            column_config={
                "probability_bucket": "Probability Bucket",
                "won_count": st.column_config.NumberColumn("Won"),
                "lost_count": st.column_config.NumberColumn("Lost"),
                "total_decided": st.column_config.NumberColumn("Decided"),
                "win_pct": st.column_config.NumberColumn("Win %", format="%.1f"),
                "loss_pct": st.column_config.NumberColumn("Loss %", format="%.1f"),
            },
        )
    else:
        st.info("No Forebet prediction/result overlap is available yet for the current canonical filters.")

    st.markdown("### Canonical Fixture Table")
    canonical_rows = safe_rows(
        fetch_canonical_fixture_rows,
        sport=sport_filter,
        source_name=source_filter,
        search_text=search_filter,
        limit=500,
    )

    if canonical_rows:
        st.dataframe(
            canonical_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.NumberColumn("Fixture ID", width="small"),
                "sport": "Sport",
                "canonical_event_date": "Event Date",
                "canonical_event_time_text": "Event Time",
                "canonical_league": "League",
                "canonical_home_team": "Home",
                "canonical_away_team": "Away",
                "linked_rows": st.column_config.NumberColumn("Link Rows", width="small"),
                "source_count": st.column_config.NumberColumn("Sources", width="small"),
                "linked_sources": "Linked Sources",
                "pred_outcome": "Forebet Pred",
                "pred_probability": st.column_config.NumberColumn("Pred %", format="%.2f"),
                "correct_score_text": "Correct Score",
                "result_home_score": st.column_config.NumberColumn("H", width="small"),
                "result_away_score": st.column_config.NumberColumn("A", width="small"),
                "primary_result_source": "Result Source",
                "actual_outcome": "Actual",
                "pred_hit": "Pred Hit",
                "confidence": st.column_config.NumberColumn("Conf", format="%.2f"),
                "updated_at": st.column_config.DatetimeColumn("Updated"),
            },
        )
    else:
        st.info("No canonical fixtures matched the current filters.")


def render_simulation_page() -> None:
    st.subheader("Canonical Fixture Simulation")
    st.caption(
        "Date-driven baseline simulation across evaluated Forebet fixtures using bookmaker odds tied to the canonical key. "
        "Assumptions: one slip per day, flat daily stake, up-to-N legs per day, and predicted-outcome odds only."
    )

    if not safe_table_exists("fixture_evaluations"):
        st.warning("The unified evaluation table is not available yet. Run ingestion so the evaluation rebuild can complete first.")
        return

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    selected_sport = c1.selectbox("Sport", options=["All", "Football", "Basketball"], key="simulation_sport")
    selected_bookmaker = c2.selectbox(
        "Odds Source",
        options=["Best Available", "betika", "sportpesa", "mozzart"],
        key="simulation_bookmaker",
    )
    stake_per_slip = float(
        c3.number_input(
            "Stake (KES)",
            min_value=100,
            max_value=1000,
            value=1000,
            step=50,
            key="simulation_stake",
        )
    )
    search_text = c4.text_input("Search team or league", value="", key="simulation_search")

    f1, f2 = st.columns([1, 3])
    fallback_odds = float(
        f1.selectbox(
            "Fallback Odds",
            options=[1.2, 1.3, 1.4, 1.5],
            index=3,
            key="simulation_fallback_odds",
            help="Used only when a game has no linked bookmaker odds for the predicted outcome.",
        )
    )

    raw_rows = safe_rows(
        fetch_fixture_simulation_inputs,
        sport=None if selected_sport == "All" else selected_sport,
        search_text=search_text or None,
    )
    prepared_rows = _prepare_simulation_rows(raw_rows, selected_bookmaker, fallback_odds=fallback_odds)
    if not prepared_rows:
        st.info("No evaluated fixtures matched the current simulation filters.")
        return

    available_dates = sorted(
        {
            row["event_date"]
            for row in prepared_rows
            if isinstance(row.get("event_date"), date)
        }
    )
    if not available_dates:
        st.info("The filtered simulation rows do not have usable event dates yet.")
        return

    d1, d2, d3, d4 = st.columns([1, 1, 1, 1])
    selected_tier = d1.selectbox("Tier", options=["All", "Gold", "Silver", "Bronze", "Custom"], key="simulation_tier")
    available_buckets = ["<40%", "40-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
    default_custom_buckets = SIMULATION_TIER_BUCKETS["Gold"]
    if selected_tier == "Custom":
        selected_custom_buckets = d2.multiselect(
            "Custom Buckets",
            options=available_buckets,
            default=default_custom_buckets,
            key="simulation_custom_buckets",
        )
    else:
        d2.caption(f"Buckets: {', '.join(SIMULATION_TIER_BUCKETS.get(selected_tier, available_buckets))}")
        selected_custom_buckets = default_custom_buckets
    default_start = available_dates[0]
    default_end = available_dates[-1]
    selected_date_from = d3.date_input("Date From", value=default_start, key="simulation_date_from")
    selected_date_to = d4.date_input("Date To", value=default_end, key="simulation_date_to")

    s1, s2 = st.columns([1, 3])
    slip_size = int(s1.selectbox("Slip Size", options=[1, 2, 3, 4], index=3, key="simulation_single_slip_size"))
    selected_buckets = _resolve_selected_buckets(selected_tier, selected_custom_buckets)

    filtered_rows = _filter_prepared_simulation_rows(
        prepared_rows,
        selected_buckets=selected_buckets,
        date_from=selected_date_from,
        date_to=selected_date_to,
    )
    if not filtered_rows:
        st.info("No evaluated games matched the selected tier and date filters.")
        return

    ledger_frame, leftover_frame, summary, bucket_summary_frame = _build_simulation_slip_ledger(
        filtered_rows,
        slip_size=slip_size,
        stake_per_slip=stake_per_slip,
    )

    games_selected = int(summary.get("games_selected") or 0)
    bookmaker_odds_games = int(summary.get("bookmaker_odds_games") or 0)
    fallback_odds_games = int(summary.get("fallback_odds_games") or 0)
    games_used_in_slips = int(summary.get("games_used_in_slips") or 0)
    slips_formed = int(summary.get("slips_formed") or 0)
    leftover_games = int(summary.get("leftover_games") or 0)
    total_staked = float(summary.get("total_staked") or 0.0)
    amount_earned = float(summary.get("amount_earned") or 0.0)
    amount_lost = float(summary.get("amount_lost") or 0.0)
    net_pnl = float(summary.get("net_pnl") or 0.0)
    roi_pct = float(summary.get("roi_pct") or 0.0)
    game_win_rate_pct = float(summary.get("game_win_rate_pct") or 0.0)
    slip_win_rate_pct = float(summary.get("slip_win_rate_pct") or 0.0)
    average_combined_odds = float(summary.get("average_combined_odds") or 0.0)
    break_even_slip_hit_rate_pct = float(summary.get("break_even_slip_hit_rate_pct") or 0.0)

    st.caption(
        f"Evaluated games in scope: {games_selected}. "
        f"Linked bookmaker odds found: {bookmaker_odds_games}. "
        f"Fallback odds used: {fallback_odds_games} at {fallback_odds:.2f}. "
        f"Games used in daily slips: {games_used_in_slips}. "
        f"Leftover games: {leftover_games}."
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Games", games_selected)
    m2.metric("Bookmaker Odds Found", bookmaker_odds_games)
    m3.metric("Fallback Odds Used", fallback_odds_games, delta=f"At {fallback_odds:.2f}")
    m4.metric("Total Bet Amount", f"KES {total_staked:,.0f}")

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Slips Formed", slips_formed)
    m6.metric("Amount Earned", f"KES {amount_earned:,.0f}")
    m7.metric("Amount Lost", f"KES {amount_lost:,.0f}")
    m8.metric("Net P&L", f"KES {net_pnl:,.0f}", delta=f"ROI {roi_pct:.1f}%")

    m9, m10, m11, m12 = st.columns(4)
    m9.metric("Game Win Rate", f"{game_win_rate_pct:.1f}%")
    m10.metric("Slip Win Rate", f"{slip_win_rate_pct:.1f}%")
    m11.metric("Avg Combined Odds", f"{average_combined_odds:.2f}")
    m12.metric("Break-even Slip Rate", f"{break_even_slip_hit_rate_pct:.1f}%")

    st.markdown("### Bucket Summary For Selected Games")
    if not bucket_summary_frame.empty:
        st.dataframe(
            bucket_summary_frame.sort_values(["event_date", "probability_bucket"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "event_date": st.column_config.DateColumn("Game Date"),
                "probability_bucket": "Probability Bucket",
                "games": st.column_config.NumberColumn("Games"),
                "won": st.column_config.NumberColumn("Won"),
                "lost": st.column_config.NumberColumn("Lost"),
                "bookmaker_odds_games": st.column_config.NumberColumn("Bookmaker Odds"),
                "fallback_odds_games": st.column_config.NumberColumn("Fallback Odds"),
                "win_pct": st.column_config.NumberColumn("Win %", format="%.1f"),
            },
        )

        daily_earnings = (
            ledger_frame.groupby("event_date", as_index=False)
            .agg(
                net_pnl=("net_pnl", "sum"),
                payout=("payout", "sum"),
                total_stake=("stake", "sum"),
                slips=("slip_id", "count"),
                legs_used=("slip_size", "sum"),
            )
            .sort_values("event_date")
        ) if not ledger_frame.empty else pd.DataFrame()

        if not daily_earnings.empty:
            daily_earnings["cumulative_net_pnl"] = daily_earnings["net_pnl"].cumsum()
            st.markdown("### Daily Earnings")
            daily_base = alt.Chart(daily_earnings).encode(
                x=alt.X("event_date:T", title="Game Date"),
                tooltip=[
                    alt.Tooltip("event_date:T", title="Game Date"),
                    alt.Tooltip("slips:Q", title="Daily Slips"),
                    alt.Tooltip("total_stake:Q", title="Total Stake", format=",.0f"),
                    alt.Tooltip("net_pnl:Q", title="Daily Net P&L", format=",.0f"),
                    alt.Tooltip("payout:Q", title="Payout", format=",.0f"),
                    alt.Tooltip("legs_used:Q", title="Legs Used"),
                    alt.Tooltip("cumulative_net_pnl:Q", title="Cumulative Net P&L", format=",.0f"),
                ],
            )
            daily_bars = (
                daily_base
                .mark_bar(color="#60A5FA", opacity=0.35)
                .encode(
                    y=alt.Y("net_pnl:Q", title="Net P&L (KES)"),
                )
            )
            daily_labels = (
                daily_base
                .mark_text(
                    dy=-12,
                    color="#E2E8F0",
                    fontSize=11,
                    fontWeight="bold",
                )
                .encode(
                    y=alt.Y("net_pnl:Q"),
                    text=alt.Text("net_pnl:Q", format=",.0f"),
                )
            )
            cumulative_line = (
                alt.Chart(daily_earnings)
                .mark_line(point=True, strokeWidth=3, color="#F0B429")
                .encode(
                    x=alt.X("event_date:T", title="Game Date"),
                    y=alt.Y("cumulative_net_pnl:Q", title="Net P&L (KES)"),
                    tooltip=[
                        alt.Tooltip("event_date:T", title="Game Date"),
                        alt.Tooltip("cumulative_net_pnl:Q", title="Cumulative Net P&L", format=",.0f"),
                    ],
                )
            )
            cumulative_labels = (
                alt.Chart(daily_earnings)
                .mark_text(
                    dy=14,
                    color="#F0B429",
                    fontSize=11,
                    fontWeight="bold",
                )
                .encode(
                    x=alt.X("event_date:T"),
                    y=alt.Y("cumulative_net_pnl:Q"),
                    text=alt.Text("cumulative_net_pnl:Q", format=",.0f"),
                )
            )
            earnings_chart = (daily_bars + daily_labels + cumulative_line + cumulative_labels).properties(height=320)
            st.altair_chart(earnings_chart, use_container_width=True)

    if not ledger_frame.empty:
        st.markdown("### Slip Ledger")
        st.dataframe(
            ledger_frame,
            use_container_width=True,
            hide_index=True,
            column_config={
                "slip_id": "Slip ID",
                "event_date": st.column_config.DateColumn("Game Date"),
                "slip_sequence": st.column_config.NumberColumn("Seq"),
                "slip_size": st.column_config.NumberColumn("Slip Size"),
                "bucket_mix": "Bucket Mix",
                "legs": "Legs",
                "odds_sources": "Odds Sources",
                "combined_odds": st.column_config.NumberColumn("Combined Odds", format="%.2f"),
                "stake": st.column_config.NumberColumn("Stake", format="%.0f"),
                "expected_win_probability_pct": st.column_config.NumberColumn("Expected Win %", format="%.1f"),
                "result": "Result",
                "payout": st.column_config.NumberColumn("Payout", format="%.0f"),
                "net_pnl": st.column_config.NumberColumn("Net P&L", format="%.0f"),
                "failed_legs": "Failed Legs",
            },
        )

    if not leftover_frame.empty:
        st.markdown("### Leftover Games")
        st.dataframe(
            leftover_frame.sort_values(["event_date", "probability_bucket"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "event_date": st.column_config.DateColumn("Game Date"),
                "probability_bucket": "Probability Bucket",
                "home_team": "Home",
                "away_team": "Away",
                "pred_probability": st.column_config.NumberColumn("Pred %", format="%.1f"),
                "selected_odds": st.column_config.NumberColumn("Odds", format="%.2f"),
                "selected_bookmaker": "Bookmaker",
                "used_fallback_odds": st.column_config.CheckboxColumn("Fallback"),
            },
        )


# =============================================================================
# Historical Analysis Page
# =============================================================================
def render_historical_page() -> None:
    st.subheader("Historical Analysis")
    st.caption("Analyze a Forebet match detail page and store recent-form and opponent history for modelling.")

    analyses_table_ok = safe_table_exists("forebet_match_analyses")
    history_table_ok = safe_table_exists("forebet_match_history_rows")

    if not analyses_table_ok or not history_table_ok:
        st.warning("Historical analysis tables are not available yet. Apply the Phase 6 schema first.")
        return

    default_url = st.session_state.get("historical_match_url", "")
    c1, c2 = st.columns([2.4, 0.8])
    match_url = c1.text_input(
        "Forebet match URL",
        value=default_url,
        placeholder="https://www.forebet.com/en/football/matches/...",
        key="historical_match_url_input",
    )
    selected_sport = c2.selectbox("Sport", options=["auto", "football", "basketball"], key="historical_sport")

    if st.button("Analyze Forebet Match", use_container_width=True, key="analyze_forebet_match"):
        if not match_url.strip():
            st.warning("Paste a Forebet football or basketball match URL first.")
        elif "forebet.com" not in match_url:
            st.warning("Use a Forebet match-detail URL so we can pull the right history sections.")
        else:
            inferred_sport = "basketball" if "/basketball/" in match_url else "football"
            sport = inferred_sport if selected_sport == "auto" else selected_sport
            try:
                os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
                from ganji_mtaani_agent.db import get_postgres_connection, upsert_forebet_match_analysis, upsert_forebet_match_history_rows
                from ganji_mtaani_agent.parsers.forebet import (
                    parse_forebet_basketball_historical_page,
                    parse_forebet_football_historical_page,
                )
                from ganji_mtaani_agent.scrapers.browser import fetch_page
                from ganji_mtaani_agent.scrapers.sources import get_source_config

                source = get_source_config("forebet")
                with st.spinner("Fetching Forebet match detail page and parsing history..."):
                    result = fetch_page(
                        match_url.strip(),
                        timeout_ms=60_000,
                        wait_until=source.default_wait_until,
                        settle_ms=source.default_settle_ms,
                        headless=source.default_headless,
                    )

                    if result.error:
                        raise RuntimeError(result.error)

                    parser_fn = (
                        parse_forebet_basketball_historical_page
                        if sport == "basketball"
                        else parse_forebet_football_historical_page
                    )
                    analysis, history_rows = parser_fn(result.html, match_url=match_url.strip())
                    if analysis is None:
                        raise RuntimeError("The Forebet detail page loaded, but the historical parser could not extract a match summary.")

                    with get_postgres_connection(autocommit=True) as connection:
                        upsert_forebet_match_analysis(connection, analysis=analysis)
                        upsert_forebet_match_history_rows(connection, rows=history_rows)

                clear_all_caches()
                st.session_state["historical_match_url"] = match_url.strip()
                st.session_state["historical_latest_analysis"] = {
                    "match_url": analysis.match_url,
                    "sport": analysis.sport,
                }
                st.success(
                    f"Stored historical analysis for {analysis.home_team} vs {analysis.away_team} "
                    f"with {len(history_rows)} historical rows."
                )
            except Exception as exc:
                st.error(f"Historical analysis failed: {exc}")

    st.markdown("### Saved Analyses")
    c3, c4 = st.columns([1, 1.8])
    selected_saved_sport = c3.selectbox("Saved sport", options=["All", "football", "basketball"], key="saved_historical_sport")
    saved_analyses = safe_rows(
        fetch_forebet_match_analyses,
        sport=None if selected_saved_sport == "All" else selected_saved_sport,
        limit=50,
    )

    if saved_analyses:
        option_map = {
            f"{row['sport'].title()} · {row['home_team']} vs {row['away_team']} · {row.get('event_datetime_text') or 'n/a'}": row
            for row in saved_analyses
        }
        default_label = next(iter(option_map))
        selected_label = c4.selectbox("Choose a saved match", options=list(option_map), index=0, key="saved_historical_match")
        selected_analysis = option_map[selected_label]

        st.markdown("### Match Summary")
        summary_cols = st.columns(4)
        summary_cols[0].metric("Fixture", f"{selected_analysis['home_team']} vs {selected_analysis['away_team']}")
        summary_cols[1].metric("Pred", selected_analysis.get("pred_outcome") or "-")
        summary_cols[2].metric("Correct Score", selected_analysis.get("predicted_score_text") or "-")
        summary_cols[3].metric("Actual Score", selected_analysis.get("actual_score_text") or selected_analysis.get("actual_status") or "-")

        st.caption(
            f"{selected_analysis.get('competition') or 'Competition n/a'} · "
            f"{selected_analysis.get('event_datetime_text') or 'Date n/a'}"
        )
        form_left, form_right = st.columns(2)
        form_left.info(f"Home form: {selected_analysis.get('home_form_sequence') or 'n/a'}")
        form_right.info(f"Away form: {selected_analysis.get('away_form_sequence') or 'n/a'}")

        history_rows = safe_rows(fetch_forebet_match_history_rows, match_url=selected_analysis["match_url"])
        if history_rows:
            st.markdown("### Historical Rows")
            st.dataframe(
                history_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "source_name": None,
                    "sport": "Sport",
                    "match_url": None,
                    "section_name": "Section",
                    "section_team": "Section Team",
                    "sequence_no": st.column_config.NumberColumn("#", width="small"),
                    "event_date_text": "Date",
                    "competition_tag": "Tag",
                    "home_team": "Home",
                    "away_team": "Away",
                    "score_text": "Score",
                    "extra_score_text": "Extra Score Detail",
                    "result_outcome": "Result",
                    "result_class": None,
                    "active_side": "Active Side",
                    "detail_url": st.column_config.LinkColumn("Detail URL"),
                    "raw_text": None,
                    "scraped_at": None,
                },
            )
        else:
            st.info("No saved historical rows were found for this match yet.")

        st.markdown("### Recent Saved Matches")
        st.dataframe(
            saved_analyses,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": None,
                "source_name": None,
                "sport": "Sport",
                "match_url": st.column_config.LinkColumn("Match URL"),
                "competition": "Competition",
                "league_code": "Code",
                "event_datetime_text": "Event Time",
                "home_team": "Home",
                "away_team": "Away",
                "pred_outcome": "Pred",
                "predicted_score_text": "Correct Score",
                "actual_score_text": "Actual Score",
                "actual_status": "Status",
                "home_form_sequence": "Home Form",
                "away_form_sequence": "Away Form",
                "confidence": st.column_config.NumberColumn("Conf", format="%.2f"),
                "scraped_at": st.column_config.DatetimeColumn("Scraped"),
            },
        )
    else:
        st.info("No saved Forebet historical analyses yet. Analyze one match URL to populate this workspace.")


# =============================================================================
# Insurance Products Page
# =============================================================================
def render_insurance_page() -> None:
    st.subheader("Insurance Products")
    st.caption("Kenyan insurance products scraped and structured for comparison.")

    if not safe_table_exists("insurance_products"):
        st.markdown(
            """
            <div class="pending-card">
            The <code>insurance_products</code> table does not exist yet.<br><br>
            Run the setup and scrape commands to populate it:<br>
            <code>python scripts/create_insurance_schema.py</code><br>
            <code>python scripts/scrape_insurance.py --source jubilee --target health --save-db</code>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    summary   = safe_rows(fetch_insurance_summary)
    insurer_opts = ["All"] + safe_rows(fetch_insurance_insurer_options)
    type_opts    = ["All"] + safe_rows(fetch_insurance_type_options)

    total_products = sum(int(r.get("product_count", 0)) for r in summary)
    total_insurers = len({r["insurer_name"] for r in summary if r.get("insurer_name")})
    total_types    = len({r["product_type"]  for r in summary if r.get("product_type")})

    # ── Metrics ──────────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Products", total_products)
    m2.metric("Insurers",       total_insurers)
    m3.metric("Product Types",  total_types)

    # ── Filters ───────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1, 1, 2])
    sel_insurer = c1.selectbox("Insurer",   options=insurer_opts, key="ins_insurer")
    sel_type    = c2.selectbox("Category",  options=type_opts,    key="ins_type")
    search_text = c3.text_input("Search product name or description", value="", key="ins_search")

    insurer_slug_map = {r["insurer_name"]: r.get("insurer_slug", r["insurer_name"].lower())
                        for r in summary if r.get("insurer_name")}

    rows = safe_rows(
        fetch_insurance_products,
        insurer_slug=insurer_slug_map.get(sel_insurer) if sel_insurer != "All" else None,
        product_type=None if sel_type == "All" else sel_type,
        search_text=search_text or None,
    )

    st.metric("Matching Products", len(rows))

    if not rows:
        st.info("No products matched the current filters.")
        return

    # ── Product table ─────────────────────────────────────────────────────────
    st.markdown("### Product Catalogue")
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id":               st.column_config.NumberColumn("ID",        width="small"),
            "insurer_name":     "Insurer",
            "insurer_slug":     None,
            "product_name":     st.column_config.TextColumn("Product",     width="large"),
            "product_type":     "Category",
            "tagline":          "Tagline",
            "target_audience":  "Audience",
            "premium_notes":    "Pricing",
            "benefit_count":    st.column_config.NumberColumn("Benefits",  width="small"),
            "waiting_period":   "Waiting Period",
            "how_to_apply":     "How to Apply",
            "contact_phone":    "Phone",
            "contact_email":    "Email",
            "confidence":       st.column_config.NumberColumn("Conf",      format="%.2f", width="small"),
            "scraped_at":       st.column_config.DatetimeColumn("Scraped"),
            "product_url":      st.column_config.LinkColumn("URL"),
        },
    )

    # ── Product detail expander ───────────────────────────────────────────────
    st.markdown("### Product Detail")
    product_options = {f"{r['insurer_name']} — {r['product_name']}": r["id"] for r in rows}
    selected_label  = st.selectbox("Select a product to view full details", options=list(product_options))

    if selected_label:
        detail = safe_rows(fetch_insurance_product_detail, product_options[selected_label])
        if detail:
            d = detail[0] if isinstance(detail, list) else detail
            with st.expander(f"{d['product_name']}", expanded=True):
                col_l, col_r = st.columns([1.6, 1])

                with col_l:
                    if d.get("tagline"):
                        st.markdown(f"*{d['tagline']}*")
                    if d.get("description"):
                        st.markdown(d["description"])

                    if d.get("key_benefits"):
                        st.markdown("**Key Benefits**")
                        for b in d["key_benefits"]:
                            st.markdown(f"- {b}")

                    if d.get("exclusions"):
                        st.markdown("**Exclusions**")
                        for e in d["exclusions"]:
                            st.markdown(f"- {e}")

                with col_r:
                    info_rows = [
                        ("Category",       d.get("product_type")),
                        ("Target",         d.get("target_audience")),
                        ("Pricing",        d.get("premium_notes")),
                        ("Waiting Period", d.get("waiting_period")),
                        ("How to Apply",   d.get("how_to_apply")),
                        ("Phone",          d.get("contact_phone")),
                        ("Email",          d.get("contact_email")),
                        ("Min Age",        d.get("min_age")),
                        ("Max Age",        d.get("max_age")),
                        ("Confidence",     d.get("confidence")),
                    ]
                    for label, value in info_rows:
                        if value is not None:
                            st.markdown(f"**{label}:** {value}")

                    if d.get("extra_data", {}).get("faqs"):
                        faqs = d["extra_data"]["faqs"]
                        st.markdown(f"**FAQs** ({len(faqs)} Q&A pairs)")
                        for faq in faqs[:5]:
                            with st.expander(faq.get("q", ""), expanded=False):
                                st.write(faq.get("a", ""))
                        if len(faqs) > 5:
                            st.caption(f"… and {len(faqs) - 5} more FAQs in the database.")

    # ── Summary breakdown ─────────────────────────────────────────────────────
    if summary:
        st.markdown("### Coverage Breakdown")
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "insurer_name":   "Insurer",
                "product_type":   "Category",
                "product_count":  st.column_config.NumberColumn("Products"),
                "avg_confidence": st.column_config.NumberColumn("Avg Conf", format="%.2f"),
                "last_scraped":   st.column_config.DatetimeColumn("Last Scraped"),
            },
        )


# =============================================================================
# Entry Point
# =============================================================================
def main() -> None:
    configure_page()
    inject_global_css()
    render_brand_header()

    if "last_refreshed" not in st.session_state:
        st.session_state["last_refreshed"] = None

    page = render_sidebar()

    if   page == PAGE_OVERVIEW:   render_overview_page()
    elif page == PAGE_BOOKMAKER:  render_bookmaker_page()
    elif page == PAGE_FOREBET:    render_forebet_page()
    elif page == PAGE_POLYMARKET: render_polymarket_page()
    elif page == PAGE_RESULTS:    render_results_page()
    elif page == PAGE_CANONICAL:  render_canonical_page()
    elif page == PAGE_SIMULATION: render_simulation_page()
    elif page == PAGE_HISTORY:    render_historical_page()
    elif page == PAGE_INSURANCE:  render_insurance_page()
    else:
        st.error(f"Unknown page: {page}")


if __name__ == "__main__":
    main()
