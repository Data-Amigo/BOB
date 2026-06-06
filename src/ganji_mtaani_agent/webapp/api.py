"""FastAPI backend for the BOB Telegram Mini App."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel

from ganji_mtaani_agent.db import get_postgres_connection
from ganji_mtaani_agent.services.telegram_bot import (
    _attach_best_odds,
    _fetch_upcoming_forebet_candidates,
    _OUTCOME_LABELS,
    _tier_label_from_bucket,
    _TIER_EMOJIS,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="BOB Mini App", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Pages
# =============================================================================
@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# =============================================================================
# API — Today's Slips
# =============================================================================
@app.get("/api/today-slips")
def get_today_slips() -> dict[str, list[dict[str, Any]]]:
    """Return Gold/Silver/Bronze tiered slips for football and basketball."""
    today = date.today()
    result: dict[str, list[dict[str, Any]]] = {}

    tier_defs = [
        ("Gold",   "90-100%", 90.0, 101.0),
        ("Silver", "80-90%",  80.0,  90.0),
        ("Bronze", "70-80%",  70.0,  80.0),
    ]

    for sport in ("football", "basketball"):
        all_candidates = _fetch_upcoming_forebet_candidates(sport=sport, min_probability=70.0)
        tiers: list[dict[str, Any]] = []

        for tier_name, tier_range, min_p, max_p in tier_defs:
            tier_games = [
                r for r in all_candidates
                if min_p <= (r.get("pred_probability") or 0.0) < max_p
            ]
            if not tier_games:
                continue

            today_pool = [r for r in tier_games if r.get("event_date") == today]
            pool = today_pool if today_pool else tier_games
            rows = _attach_best_odds(pool[:3], sport=sport)

            combined = 1.0
            for r in rows:
                combined *= float(r.get("selected_odds") or 1.5)

            legs = []
            for r in rows:
                outcome = str(r.get("pred_outcome") or "")
                legs.append({
                    "home_team": r.get("home_team"),
                    "away_team": r.get("away_team"),
                    "league": r.get("league") or "",
                    "outcome": outcome,
                    "outcome_label": _OUTCOME_LABELS.get(outcome, outcome),
                    "probability": round(float(r.get("pred_probability") or 0.0), 1),
                    "odds": r.get("selected_odds"),
                    "bookmaker": r.get("bookmaker_source") or "",
                    "time": r.get("event_time") or "",
                    "event_date": r.get("event_date").isoformat() if r.get("event_date") else "",
                })

            tiers.append({
                "tier": tier_name,
                "range": tier_range,
                "emoji": _TIER_EMOJIS.get(tier_name, ""),
                "games": len(rows),
                "combined_odds": round(combined, 2),
                "legs": legs,
            })

        result[sport] = tiers

    return result


# =============================================================================
# API — Stats
# =============================================================================
@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    """Overall slip counts and 7-day performance."""
    today = date.today()
    cutoff = today - timedelta(days=7)

    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM bot_slips WHERE DATE(created_at) = %s",
            (today,),
        )
        today_count = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(CASE WHEN status = 'won'  THEN 1 END) AS won,
                COUNT(CASE WHEN status = 'lost' THEN 1 END) AS lost,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) AS pending
            FROM bot_slips
            WHERE created_at >= %s
            """,
            (cutoff,),
        )
        perf = dict(cur.fetchone() or {})

    total = int(perf.get("total") or 0)
    won = int(perf.get("won") or 0)
    lost = int(perf.get("lost") or 0)
    resolved = won + lost
    win_rate = round(100 * won / resolved) if resolved > 0 else 0

    return {
        "today_slips": today_count,
        "total_7d": total,
        "won_7d": won,
        "lost_7d": lost,
        "pending_7d": int(perf.get("pending") or 0),
        "win_rate_7d": win_rate,
    }


# =============================================================================
# API — Successful Teams
# =============================================================================
@app.get("/api/successful-teams")
def get_successful_teams(days: int = 7) -> list[dict[str, Any]]:
    """Teams appearing most in winning slips over the last N days."""
    cutoff = date.today() - timedelta(days=days)

    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH team_appearances AS (
                SELECT bsl.home_team AS team,
                       COUNT(*) AS appearances,
                       COUNT(CASE WHEN bs.status = 'won' THEN 1 END) AS wins
                FROM bot_slip_legs bsl
                JOIN bot_slips bs ON bs.id = bsl.slip_id
                WHERE bs.created_at >= %s
                  AND bsl.home_team IS NOT NULL
                GROUP BY bsl.home_team

                UNION ALL

                SELECT bsl.away_team AS team,
                       COUNT(*) AS appearances,
                       COUNT(CASE WHEN bs.status = 'won' THEN 1 END) AS wins
                FROM bot_slip_legs bsl
                JOIN bot_slips bs ON bs.id = bsl.slip_id
                WHERE bs.created_at >= %s
                  AND bsl.away_team IS NOT NULL
                GROUP BY bsl.away_team
            )
            SELECT team,
                   SUM(appearances) AS appearances,
                   SUM(wins) AS wins
            FROM team_appearances
            GROUP BY team
            HAVING SUM(appearances) >= 2
            ORDER BY SUM(wins) DESC, SUM(appearances) DESC
            LIMIT 10
            """,
            (cutoff, cutoff),
        )
        rows = [dict(r) for r in cur.fetchall()]

    return [
        {
            "team": r["team"],
            "appearances": int(r["appearances"]),
            "wins": int(r["wins"]),
            "win_rate": round(100 * int(r["wins"]) / int(r["appearances"])) if int(r["appearances"]) > 0 else 0,
        }
        for r in rows
    ]


# =============================================================================
# Static files (must be last so API routes are matched first)
# =============================================================================
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
