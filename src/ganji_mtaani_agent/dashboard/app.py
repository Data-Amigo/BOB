from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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
    fetch_forebet_results,
    fetch_forebet_results_sport_options,
    fetch_forebet_results_status_options,
    fetch_forebet_results_summary,
    fetch_bookmaker_summary,
    fetch_forebet_league_options,
    fetch_forebet_predictions,
    fetch_forebet_sport_options,
    fetch_forebet_summary,
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

PAGE_OVERVIEW   = "📊  Overview"
PAGE_BOOKMAKER  = "🎰  Bookmaker Odds"
PAGE_FOREBET    = "📈  Forebet Predictions"
PAGE_POLYMARKET = "🌐  Polymarket Markets"
PAGE_RESULTS    = "⚽  Sports Results"

SOURCE_FAMILY_CATALOG = [
    {"source_name": "betika",      "display_name": "Betika",      "role": "Bookmaker odds",       "table_name": "bookmaker_odds"},
    {"source_name": "sportpesa",   "display_name": "SportPesa",   "role": "Bookmaker odds",       "table_name": "bookmaker_odds"},
    {"source_name": "mozzart",     "display_name": "Mozzart",     "role": "Bookmaker odds",       "table_name": "bookmaker_odds"},
    {"source_name": "forebet",     "display_name": "Forebet",     "role": "Predictions",          "table_name": "forebet_predictions"},
    {"source_name": "forebet_results", "display_name": "Forebet Results", "role": "Finished results", "table_name": "forebet_results"},
    {"source_name": "polymarket",  "display_name": "Polymarket",  "role": "Prediction markets",   "table_name": "polymarket_markets"},
    {"source_name": "thesportsdb", "display_name": "TheSportsDB", "role": "Results & enrichment", "table_name": "sports_results"},
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
        options=[PAGE_OVERVIEW, PAGE_BOOKMAKER, PAGE_FOREBET, PAGE_POLYMARKET, PAGE_RESULTS],
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
    forebet_ok         = safe_table_exists("forebet_predictions")
    polymarket_ok      = safe_table_exists("polymarket_markets")

    run_summary       = safe_rows(fetch_source_run_summary)      if source_runs_ok else []
    latest_runs       = safe_rows(fetch_latest_source_runs, limit=12) if source_runs_ok else []
    bookmaker_summary      = safe_rows(fetch_bookmaker_summary)       if bookmaker_ok       else []
    results_summary        = safe_rows(fetch_sports_results_summary)  if results_ok         else []
    forebet_results_summary = safe_rows(fetch_forebet_results_summary) if forebet_results_ok else []
    forebet_summary        = safe_rows(fetch_forebet_summary)         if forebet_ok         else []
    polymarket_summary     = safe_rows(fetch_polymarket_summary)      if polymarket_ok      else []
    table_inventory        = safe_rows(fetch_table_inventory)

    total_runs      = sum(int(r.get("total_runs",     0)) for r in run_summary)
    successful_runs = sum(int(r.get("successful_runs",0)) for r in run_summary)
    failed_runs     = sum(int(r.get("failed_runs",    0)) for r in run_summary)
    bookmaker_rows      = sum(int(r.get("row_count", 0)) for r in bookmaker_summary)
    forebet_result_rows = sum(int(r.get("row_count", 0)) for r in forebet_results_summary)
    forebet_rows        = sum(int(r.get("row_count", 0)) for r in forebet_summary)
    polymarket_rows     = sum(int(r.get("row_count", 0)) for r in polymarket_summary)

    # ── Metric row ──────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Total Runs",      total_runs)
    m2.metric("Successful",      successful_runs)
    m3.metric("Failed",          failed_runs,
              delta=f"-{failed_runs}" if failed_runs else None,
              delta_color="inverse")
    m4.metric("Bookmaker Rows",  bookmaker_rows)
    m5.metric("Forebet Rows",    forebet_rows)
    m6.metric("Polymarket Rows", polymarket_rows)
    m7.metric("Forebet Results", forebet_result_rows)

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
    st.caption("Ground-truth event schedule, status, and score view from TheSportsDB and Forebet results.")

    sports_results_ok = safe_table_exists("sports_results")
    forebet_results_ok = safe_table_exists("forebet_results")

    if not sports_results_ok and not forebet_results_ok:
        st.warning("Neither `sports_results` nor `forebet_results` exists yet.")
        return

    result_source_options = ["TheSportsDB"] if sports_results_ok else []
    if forebet_results_ok:
        result_source_options.append("Forebet Results")

    default_source = "Forebet Results" if forebet_results_ok else result_source_options[0]

    c0, c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1.2, 1.8, 0.8])
    sel_source = c0.selectbox("Result Source", options=result_source_options, index=result_source_options.index(default_source))

    using_forebet_results = sel_source == "Forebet Results"

    sport_options = ["All"] + safe_rows(fetch_forebet_results_sport_options if using_forebet_results else fetch_results_sport_options)
    status_options = ["All"] + safe_rows(fetch_forebet_results_status_options if using_forebet_results else fetch_results_status_options)

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
    else:
        st.error(f"Unknown page: {page}")


if __name__ == "__main__":
    main()
