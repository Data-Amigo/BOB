from __future__ import annotations

import sys
from datetime import UTC, datetime
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
    fetch_bookmaker_summary,
    fetch_latest_source_runs,
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

PAGE_OVERVIEW = "📊 Overview"
PAGE_BOOKMAKER = "🎰 Bookmaker Odds"
PAGE_FOREBET = "📈 Forebet Predictions"
PAGE_POLYMARKET = "🌐 Polymarket Markets"
PAGE_RESULTS = "⚽ Sports Results"

SOURCE_FAMILY_CATALOG = [
    {"source_name": "betika",      "display_name": "Betika",      "role": "Bookmaker odds",          "table_name": "bookmaker_odds"},
    {"source_name": "sportpesa",   "display_name": "SportPesa",   "role": "Bookmaker odds",          "table_name": "bookmaker_odds"},
    {"source_name": "mozzart",     "display_name": "Mozzart",     "role": "Bookmaker odds",          "table_name": "bookmaker_odds"},
    {"source_name": "forebet",     "display_name": "Forebet",     "role": "Predictions",             "table_name": "forebet_predictions"},
    {"source_name": "polymarket",  "display_name": "Polymarket",  "role": "Prediction markets",      "table_name": "polymarket_markets"},
    {"source_name": "thesportsdb", "display_name": "TheSportsDB", "role": "Results & enrichment",    "table_name": "sports_results"},
]


# =============================================================================
# Page Setup
# =============================================================================
def configure_page() -> None:
    """Set base Streamlit page config."""

    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def inject_global_css() -> None:
    """Inject global dark-navy/gold CSS that applies across every page."""

    st.markdown(
        """
        <style>
            /* ---- Metric cards ---- */
            [data-testid="metric-container"] {
                background: rgba(240, 180, 41, 0.06);
                border: 1px solid rgba(240, 180, 41, 0.2);
                border-radius: 0.65rem;
                padding: 0.75rem 1rem;
            }
            [data-testid="metric-container"] label {
                color: #94a3b8 !important;
                font-size: 0.78rem;
                letter-spacing: 0.04em;
                text-transform: uppercase;
            }
            [data-testid="metric-container"] [data-testid="stMetricValue"] {
                color: #F0B429 !important;
                font-weight: 700;
            }

            /* ---- Sidebar nav radio ---- */
            [data-testid="stSidebar"] .stRadio label {
                font-size: 0.95rem;
                padding: 0.35rem 0.5rem;
                border-radius: 0.4rem;
                transition: background 0.15s;
            }
            [data-testid="stSidebar"] .stRadio label:hover {
                background: rgba(240, 180, 41, 0.1);
            }

            /* ---- Sidebar title ---- */
            [data-testid="stSidebar"] h3 {
                color: #F0B429;
                letter-spacing: 0.06em;
                font-weight: 800;
            }

            /* ---- Section headings ---- */
            h3 {
                color: #cbd5e0;
                font-weight: 700;
                letter-spacing: 0.02em;
            }

            /* ---- Dataframe ---- */
            [data-testid="stDataFrame"] {
                border: 1px solid rgba(240, 180, 41, 0.12);
                border-radius: 0.6rem;
                overflow: hidden;
            }

            /* ---- Primary button (Refresh) ---- */
            [data-testid="stSidebar"] .stButton > button {
                background: rgba(240, 180, 41, 0.12);
                color: #F0B429;
                border: 1px solid rgba(240, 180, 41, 0.4);
                border-radius: 0.5rem;
                font-weight: 600;
                letter-spacing: 0.03em;
                transition: background 0.2s, border-color 0.2s;
            }
            [data-testid="stSidebar"] .stButton > button:hover {
                background: rgba(240, 180, 41, 0.22);
                border-color: rgba(240, 180, 41, 0.7);
            }

            /* ---- Info / warning boxes ---- */
            [data-testid="stAlert"] {
                border-radius: 0.6rem;
            }

            /* ---- Selectbox & text input ---- */
            [data-testid="stSelectbox"] > div,
            [data-testid="stTextInput"] > div > div {
                border-radius: 0.45rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Brand Header
# =============================================================================
def render_brand_header() -> None:
    """Render the BoB brand header with gold shimmer animation and pillar badges."""

    st.markdown(
        """
        <style>
            /* ---- BOB header shell ---- */
            .bob-shell {
                padding: 1.1rem 0 1.4rem 0;
                border-bottom: 1px solid rgba(240, 180, 41, 0.25);
                margin-bottom: 1.2rem;
            }

            /* ---- BOB wordmark: gold shimmer + glow ---- */
            @keyframes bobGoldShimmer {
                0%   {
                    background-position: -300% center;
                    filter: drop-shadow(0 0 6px rgba(240, 180, 41, 0.35));
                }
                50%  {
                    background-position: 300% center;
                    filter: drop-shadow(0 0 22px rgba(240, 180, 41, 0.9))
                            drop-shadow(0 0 50px rgba(240, 180, 41, 0.4));
                }
                100% {
                    background-position: -300% center;
                    filter: drop-shadow(0 0 6px rgba(240, 180, 41, 0.35));
                }
            }
            .bob-wordmark {
                font-size: 3.8rem;
                font-weight: 900;
                line-height: 1;
                letter-spacing: 0.18em;
                background: linear-gradient(
                    90deg,
                    #7a5200 0%,
                    #c8860a 20%,
                    #F0B429 40%,
                    #FFD700 50%,
                    #F0B429 60%,
                    #c8860a 80%,
                    #7a5200 100%
                );
                background-size: 300% auto;
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                animation: bobGoldShimmer 3.5s ease-in-out infinite;
                font-family: Georgia, "Times New Roman", serif;
            }

            /* ---- Tagline ---- */
            .bob-tagline {
                margin-top: 0.4rem;
                font-size: 1rem;
                color: #94a3b8;
                font-weight: 400;
                letter-spacing: 0.03em;
            }

            /* ---- Pillar badges ---- */
            .bob-pillars {
                display: flex;
                gap: 0.5rem;
                margin-top: 0.85rem;
                flex-wrap: wrap;
            }
            .pillar {
                display: inline-block;
                padding: 0.22rem 0.8rem;
                border-radius: 2rem;
                font-size: 0.78rem;
                font-weight: 600;
                letter-spacing: 0.03em;
            }
            .pillar-risk {
                background: rgba(248, 113, 113, 0.1);
                color: #fca5a5;
                border: 1px solid rgba(248, 113, 113, 0.3);
            }
            .pillar-invest {
                background: rgba(52, 211, 153, 0.1);
                color: #6ee7b7;
                border: 1px solid rgba(52, 211, 153, 0.3);
            }
            .pillar-protect {
                background: rgba(147, 197, 253, 0.1);
                color: #93c5fd;
                border: 1px solid rgba(147, 197, 253, 0.3);
            }

            /* ---- Placeholder pending card (dark mode) ---- */
            .pending-card {
                padding: 1rem 1.1rem;
                border: 1px dashed rgba(240, 180, 41, 0.3);
                border-radius: 0.85rem;
                background: rgba(240, 180, 41, 0.04);
                color: #cbd5e0;
            }
        </style>
        <div class="bob-shell">
            <div class="bob-wordmark">BoB</div>
            <div class="bob-tagline">Risk smarter. &nbsp;Invest better. &nbsp;Protect more.</div>
            <div class="bob-pillars">
                <span class="pillar pillar-risk">🎯 Risk &nbsp;·&nbsp; Betting &amp; Forex</span>
                <span class="pillar pillar-invest">💰 Investment &nbsp;·&nbsp; Insurance</span>
                <span class="pillar pillar-protect">🛡️ Protection &nbsp;·&nbsp; Coming soon</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Sidebar
# =============================================================================
def render_sidebar() -> str:
    """Render sidebar navigation and return the selected page label."""

    st.sidebar.markdown("### BoB")
    st.sidebar.caption("Decision intelligence platform")

    page = st.sidebar.radio(
        "Navigate",
        options=[PAGE_OVERVIEW, PAGE_BOOKMAKER, PAGE_FOREBET, PAGE_POLYMARKET, PAGE_RESULTS],
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")

    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        clear_all_caches()
        st.session_state["last_refreshed"] = datetime.now(UTC)
        st.rerun()

    last_refreshed: datetime | None = st.session_state.get("last_refreshed")
    if last_refreshed:
        st.sidebar.caption(f"Refreshed at {last_refreshed.strftime('%H:%M:%S')} UTC")
    else:
        st.sidebar.caption("Data cached for 2 min · click to refresh")

    return page


# =============================================================================
# Shared Helpers
# =============================================================================
def safe_table_exists(table_name: str) -> bool:
    """Return a table-existence flag without crashing the dashboard."""

    try:
        return table_exists(table_name)
    except Exception:
        return False


def safe_rows(loader, *args, **kwargs) -> list[dict[str, Any]]:
    """Run a data loader and return an empty list on any error."""

    try:
        return loader(*args, **kwargs)
    except Exception as exc:
        st.error(f"Database read failed: {exc}")
        return []


# =============================================================================
# Overview Page
# =============================================================================
def render_overview_page() -> None:
    """Render the BoB overview page."""

    st.subheader("Overview")
    st.caption("Pipeline health, storage readiness, and source coverage at a glance.")

    source_runs_available = safe_table_exists("source_runs")
    bookmaker_available = safe_table_exists("bookmaker_odds")
    results_available = safe_table_exists("sports_results")

    latest_runs     = safe_rows(fetch_latest_source_runs, limit=12) if source_runs_available else []
    run_summary     = safe_rows(fetch_source_run_summary) if source_runs_available else []
    bookmaker_summary = safe_rows(fetch_bookmaker_summary) if bookmaker_available else []
    results_summary = safe_rows(fetch_sports_results_summary) if results_available else []
    table_inventory = safe_rows(fetch_table_inventory)

    total_runs        = sum(int(r.get("total_runs", 0)) for r in run_summary)
    successful_runs   = sum(int(r.get("successful_runs", 0)) for r in run_summary)
    failed_runs       = sum(int(r.get("failed_runs", 0)) for r in run_summary)
    bookmaker_rows    = sum(int(r.get("row_count", 0)) for r in bookmaker_summary)
    sports_result_rows = sum(int(r.get("row_count", 0)) for r in results_summary)

    # --- Top metrics ---
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Runs", total_runs)
    m2.metric("Successful", successful_runs)
    m3.metric("Failed", failed_runs, delta=f"-{failed_runs}" if failed_runs else None, delta_color="inverse")
    m4.metric("Bookmaker Rows", bookmaker_rows)
    m5.metric("Sports Results", sports_result_rows)

    # --- Source coverage ---
    st.markdown("### Source Coverage")
    run_summary_by_source = {r["source_name"]: r for r in run_summary}
    coverage_rows: list[dict[str, Any]] = []

    for item in SOURCE_FAMILY_CATALOG:
        table_ready = safe_table_exists(item["table_name"])
        source_row = run_summary_by_source.get(item["source_name"], {})
        coverage_rows.append(
            {
                "source":                    item["display_name"],
                "role":                      item["role"],
                "table":                     item["table_name"],
                "table_ready":               "✅ yes" if table_ready else "⏳ pending",
                "total_runs":                int(source_row.get("total_runs", 0)),
                "successful_runs":           int(source_row.get("successful_runs", 0)),
                "failed_runs":               int(source_row.get("failed_runs", 0)),
                "latest_started_at":         source_row.get("latest_started_at"),
                "cumulative_records_found":  int(source_row.get("cumulative_records_found", 0)),
            }
        )

    st.dataframe(
        coverage_rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "source":                   st.column_config.TextColumn("Source"),
            "role":                     st.column_config.TextColumn("Role"),
            "table":                    st.column_config.TextColumn("Table"),
            "table_ready":              st.column_config.TextColumn("DB Ready", width="small"),
            "total_runs":               st.column_config.NumberColumn("Runs", width="small"),
            "successful_runs":          st.column_config.NumberColumn("✓ OK", width="small"),
            "failed_runs":              st.column_config.NumberColumn("✗ Fail", width="small"),
            "latest_started_at":        st.column_config.DatetimeColumn("Last Run"),
            "cumulative_records_found": st.column_config.NumberColumn("Total Records"),
        },
    )

    # --- Charts ---
    if run_summary or bookmaker_summary:
        chart_left, chart_right = st.columns(2)

        with chart_left:
            if run_summary:
                st.markdown("**Run Activity by Source**")
                chart_df = (
                    pd.DataFrame(run_summary)[["source_name", "successful_runs", "failed_runs"]]
                    .set_index("source_name")
                    .astype(int)
                    .rename(columns={"successful_runs": "Successful", "failed_runs": "Failed"})
                )
                st.bar_chart(chart_df, color=["#10b981", "#ef4444"])

        with chart_right:
            if bookmaker_summary:
                st.markdown("**Records Collected by Source**")
                bm_df = pd.DataFrame(bookmaker_summary)
                bm_df["label"] = bm_df["source_name"].str.title() + " / " + bm_df["sport"].str.title()
                bm_df = bm_df.set_index("label")[["row_count"]].rename(columns={"row_count": "Records"})
                st.bar_chart(bm_df)

    # --- Detail tables ---
    left, right = st.columns([1.3, 1])

    with left:
        st.markdown("### Latest Source Runs")
        if latest_runs:
            st.dataframe(
                latest_runs,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id":             st.column_config.NumberColumn("ID", width="small"),
                    "source_name":    st.column_config.TextColumn("Source"),
                    "target_name":    st.column_config.TextColumn("Target"),
                    "source_type":    st.column_config.TextColumn("Type"),
                    "status":         st.column_config.TextColumn("Status"),
                    "started_at":     st.column_config.DatetimeColumn("Started"),
                    "finished_at":    st.column_config.DatetimeColumn("Finished"),
                    "duration_ms":    st.column_config.NumberColumn("ms"),
                    "records_found":  st.column_config.NumberColumn("Records"),
                    "warnings_count": st.column_config.NumberColumn("Warns", width="small"),
                    "error_message":  st.column_config.TextColumn("Error"),
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

        if bookmaker_summary:
            st.caption("Bookmaker rows by source / sport")
            st.dataframe(
                bookmaker_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "source_name":      "Source",
                    "sport":            "Sport",
                    "row_count":        st.column_config.NumberColumn("Rows"),
                    "latest_created_at": st.column_config.DatetimeColumn("Last Scraped"),
                },
            )

        if results_summary:
            st.caption("Sports results by sport / status")
            st.dataframe(
                results_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "sport":             "Sport",
                    "status":            "Status",
                    "row_count":         st.column_config.NumberColumn("Rows"),
                    "latest_event_date": st.column_config.DateColumn("Latest Date"),
                },
            )


# =============================================================================
# Bookmaker Odds Page
# =============================================================================
def render_bookmaker_page() -> None:
    """Render the bookmaker odds page."""

    st.subheader("Bookmaker Odds")
    st.caption("Unified odds view across Betika, SportPesa, and Mozzart.")

    if not safe_table_exists("bookmaker_odds"):
        st.warning("The `bookmaker_odds` table does not exist yet.")
        return

    source_options = ["All"] + safe_rows(fetch_bookmaker_source_options)
    sport_options  = ["All", "football", "basketball"]

    f1, f2, f3, f4, f5 = st.columns([1, 1, 1.2, 1.6, 0.8])
    selected_source = f1.selectbox("Source", options=source_options)
    selected_sport  = f2.selectbox("Sport",  options=sport_options)

    league_options  = ["All"] + safe_rows(
        fetch_bookmaker_league_options,
        None if selected_source == "All" else selected_source,
        None if selected_sport  == "All" else selected_sport,
    )
    selected_league = f3.selectbox("League", options=league_options)
    search_text     = f4.text_input("Search team or league", value="")
    row_limit       = f5.number_input("Rows", min_value=10, max_value=1000, value=200, step=10)

    rows = safe_rows(
        fetch_bookmaker_odds,
        source_name=None if selected_source == "All" else selected_source,
        sport=None       if selected_sport  == "All" else selected_sport,
        league=None      if selected_league == "All" else selected_league,
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
                "id":                 st.column_config.NumberColumn("ID", width="small"),
                "run_id":             None,
                "source_name":        st.column_config.TextColumn("Source"),
                "sport":              st.column_config.TextColumn("Sport"),
                "league":             st.column_config.TextColumn("League"),
                "event_datetime_text":st.column_config.TextColumn("Match Time"),
                "home_team":          st.column_config.TextColumn("Home"),
                "away_team":          st.column_config.TextColumn("Away"),
                "game_id":            None,
                "match_status":       st.column_config.TextColumn("Status"),
                "score_text":         st.column_config.TextColumn("Score"),
                "market_type":        st.column_config.TextColumn("Market"),
                "home_odds":          st.column_config.NumberColumn("1",      format="%.2f"),
                "draw_odds":          st.column_config.NumberColumn("X",      format="%.2f"),
                "away_odds":          st.column_config.NumberColumn("2",      format="%.2f"),
                "home_or_draw_odds":  st.column_config.NumberColumn("1X",     format="%.2f"),
                "draw_or_away_odds":  st.column_config.NumberColumn("X2",     format="%.2f"),
                "home_or_away_odds":  st.column_config.NumberColumn("12",     format="%.2f"),
                "over_2_5_odds":      st.column_config.NumberColumn("Ov2.5",  format="%.2f"),
                "under_2_5_odds":     st.column_config.NumberColumn("Un2.5",  format="%.2f"),
                "btts_yes_odds":      st.column_config.NumberColumn("BTTS Y", format="%.2f"),
                "btts_no_odds":       st.column_config.NumberColumn("BTTS N", format="%.2f"),
                "extra_market_count": None,
                "confidence":         st.column_config.NumberColumn("Conf",   format="%.2f"),
                "created_at":         st.column_config.DatetimeColumn("Scraped At"),
            },
        )
    else:
        st.info("No bookmaker rows matched the current filters.")


# =============================================================================
# Sports Results Page
# =============================================================================
def render_results_page() -> None:
    """Render the sports results page."""

    st.subheader("Sports Results")
    st.caption("Ground-truth event schedule, status, and score view from TheSportsDB.")

    if not safe_table_exists("sports_results"):
        st.warning("The `sports_results` table does not exist yet.")
        return

    sport_options  = ["All"] + safe_rows(fetch_results_sport_options)
    status_options = ["All"] + safe_rows(fetch_results_status_options)

    f1, f2, f3, f4, f5 = st.columns([1, 1, 1.2, 1.8, 0.8])
    selected_sport  = f1.selectbox("Sport",  options=sport_options)
    selected_status = f2.selectbox("Status", options=status_options)
    selected_date   = f3.date_input("Event date", value=None, help="Leave empty to show all dates")
    search_text     = f4.text_input("Search team, league, or event", value="")
    row_limit       = f5.number_input("Rows", min_value=10, max_value=1000, value=200, step=10)

    event_date_str = selected_date.isoformat() if selected_date else None

    rows = safe_rows(
        fetch_sports_results,
        sport=None   if selected_sport  == "All" else selected_sport,
        status=None  if selected_status == "All" else selected_status,
        event_date=event_date_str,
        search_text=search_text or None,
        limit=int(row_limit),
    )

    st.metric("Matching Results", len(rows))

    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id":          None,
                "run_id":      None,
                "source_name": st.column_config.TextColumn("Source"),
                "sport":       st.column_config.TextColumn("Sport"),
                "event_id":    st.column_config.TextColumn("Event ID"),
                "league_id":   None,
                "league":      st.column_config.TextColumn("League"),
                "season":      st.column_config.TextColumn("Season"),
                "event_name":  st.column_config.TextColumn("Match"),
                "event_date":  st.column_config.DateColumn("Date"),
                "event_time":  st.column_config.TextColumn("Time"),
                "home_team":   st.column_config.TextColumn("Home"),
                "away_team":   st.column_config.TextColumn("Away"),
                "home_score":  st.column_config.NumberColumn("H", width="small"),
                "away_score":  st.column_config.NumberColumn("A", width="small"),
                "status":      st.column_config.TextColumn("Status"),
                "progress":    st.column_config.TextColumn("Progress"),
                "venue":       st.column_config.TextColumn("Venue"),
                "winner":      st.column_config.TextColumn("Winner"),
                "confidence":  st.column_config.NumberColumn("Conf", format="%.2f"),
                "created_at":  None,
            },
        )
    else:
        st.info("No results matched the current filters.")


# =============================================================================
# Placeholder Page
# =============================================================================
def render_placeholder_page(title: str, table_name: str, body: str, next_step: str) -> None:
    """Render a placeholder for a source whose DB table is not ready yet."""

    st.subheader(title)
    if safe_table_exists(table_name):
        st.success(f"The `{table_name}` table exists — this page can be expanded next.")
    st.markdown(
        f"""
        <div class="pending-card">
            <strong>{body}</strong><br/><br/>
            Next step: {next_step}
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# Main Entry Point
# =============================================================================
def main() -> None:
    """Run the BoB Streamlit dashboard."""

    configure_page()
    inject_global_css()
    render_brand_header()

    if "last_refreshed" not in st.session_state:
        st.session_state["last_refreshed"] = None

    selected_page = render_sidebar()

    if selected_page == PAGE_OVERVIEW:
        render_overview_page()

    elif selected_page == PAGE_BOOKMAKER:
        render_bookmaker_page()

    elif selected_page == PAGE_FOREBET:
        render_placeholder_page(
            title=PAGE_FOREBET,
            table_name="forebet_predictions",
            body="Forebet extraction is working, but the dedicated PostgreSQL table for predictions has not been created and loaded yet.",
            next_step="create `forebet_predictions`, insert football and basketball rows, then wire this page to filters and a structured table.",
        )

    elif selected_page == PAGE_POLYMARKET:
        render_placeholder_page(
            title=PAGE_POLYMARKET,
            table_name="polymarket_markets",
            body="Polymarket Gamma ingestion is working, but market records are not yet persisted into a dedicated PostgreSQL table.",
            next_step="create `polymarket_markets`, insert normalized market rows, then expose category, volume, liquidity, and outcome-price views here.",
        )

    elif selected_page == PAGE_RESULTS:
        render_results_page()

    else:
        st.error(f"Unknown page: {selected_page}")


if __name__ == "__main__":
    main()
