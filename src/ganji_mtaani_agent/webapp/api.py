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
# API — User registration / profile
# =============================================================================
class UserRegisterBody(BaseModel):
    telegram_user_id: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    preferred_name: str | None = None
    phone_number: str | None = None


class UserUpdateBody(BaseModel):
    preferred_name: str | None = None
    phone_number: str | None = None
    daily_stake_kes: float | None = None


@app.post("/api/user/register")
def register_user(body: UserRegisterBody) -> dict[str, Any]:
    """Register or retrieve a user by Telegram ID. Called on every Mini App open."""
    with get_postgres_connection(autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        # Upsert into bot_users
        cur.execute(
            """
            INSERT INTO bot_users (channel, channel_user_id, first_name, last_name, username, status, last_seen_at)
            VALUES ('telegram', %s, %s, %s, %s, 'active', NOW())
            ON CONFLICT (channel, channel_user_id) DO UPDATE
              SET first_name   = COALESCE(EXCLUDED.first_name,  bot_users.first_name),
                  last_name    = COALESCE(EXCLUDED.last_name,   bot_users.last_name),
                  username     = COALESCE(EXCLUDED.username,    bot_users.username),
                  last_seen_at = NOW()
            RETURNING id
            """,
            (body.telegram_user_id, body.first_name, body.last_name, body.username),
        )
        row = cur.fetchone()
        user_id = row["id"]

        # Upsert preferences if provided
        cur.execute(
            """
            INSERT INTO bot_user_preferences (user_id)
            VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )
        if body.preferred_name:
            cur.execute(
                "UPDATE bot_user_preferences SET preferred_name = %s WHERE user_id = %s",
                (body.preferred_name, user_id),
            )
        if body.phone_number:
            cur.execute(
                "UPDATE bot_users SET phone_number = %s WHERE id = %s",
                (body.phone_number, user_id),
            )

        # Fetch full profile
        cur.execute(
            """
            SELECT bu.id, bu.first_name, bu.last_name, bu.username, bu.phone_number,
                   bup.preferred_name, bup.preferred_slip_size, bup.risk_profile,
                   COALESCE(bup.stake_kes, 500) AS daily_stake_kes
            FROM bot_users bu
            LEFT JOIN bot_user_preferences bup ON bup.user_id = bu.id
            WHERE bu.id = %s
            """,
            (user_id,),
        )
        profile = dict(cur.fetchone() or {})

    display_name = (
        profile.get("preferred_name")
        or profile.get("first_name")
        or profile.get("username")
        or "Bettor"
    )
    return {
        "user_id": profile.get("id"),
        "display_name": display_name,
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "username": profile.get("username"),
        "phone_number": profile.get("phone_number"),
        "preferred_name": profile.get("preferred_name"),
        "daily_stake_kes": float(profile.get("daily_stake_kes") or 500),
        "risk_profile": profile.get("risk_profile"),
        "is_new": not bool(profile.get("preferred_name")),
    }


@app.patch("/api/user/{telegram_user_id}")
def update_user(telegram_user_id: str, body: UserUpdateBody) -> dict[str, Any]:
    """Update preferred name, phone number, or daily stake."""
    with get_postgres_connection(autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM bot_users WHERE channel = 'telegram' AND channel_user_id = %s",
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        user_id = row["id"]

        if body.preferred_name is not None:
            cur.execute(
                "UPDATE bot_user_preferences SET preferred_name = %s WHERE user_id = %s",
                (body.preferred_name, user_id),
            )
            cur.execute(
                "UPDATE bot_users SET pseudo_name = %s WHERE id = %s",
                (body.preferred_name, user_id),
            )
        if body.phone_number is not None:
            cur.execute(
                "UPDATE bot_users SET phone_number = %s WHERE id = %s",
                (body.phone_number, user_id),
            )
        if body.daily_stake_kes is not None:
            cur.execute(
                """
                INSERT INTO bot_user_preferences (user_id, stake_kes)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET stake_kes = EXCLUDED.stake_kes
                """,
                (user_id, body.daily_stake_kes),
            )

    return {"ok": True}


# =============================================================================
# API — Per-user slip history and earnings
# =============================================================================
@app.get("/api/user/{telegram_user_id}/stats")
def get_user_stats(telegram_user_id: str, days: int = 7) -> dict[str, Any]:
    """Personal slip stats and estimated earnings for a specific user."""
    cutoff = date.today() - timedelta(days=days)

    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM bot_users WHERE channel = 'telegram' AND channel_user_id = %s",
            (telegram_user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return {"total": 0, "won": 0, "lost": 0, "pending": 0, "win_rate": 0, "earned_kes": 0}
        user_id = user_row["id"]

        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(CASE WHEN status = 'won'  THEN 1 END) AS won,
                COUNT(CASE WHEN status = 'lost' THEN 1 END) AS lost,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) AS pending,
                COALESCE(SUM(CASE WHEN status = 'won' AND total_combined_odds IS NOT NULL
                    THEN total_combined_odds ELSE 0 END), 0) AS total_odds_won
            FROM bot_slips
            WHERE user_id = %s AND created_at >= %s
            """,
            (user_id, cutoff),
        )
        stats = dict(cur.fetchone() or {})

        cur.execute(
            "SELECT COALESCE(stake_kes, 500) AS daily_stake FROM bot_user_preferences WHERE user_id = %s",
            (user_id,),
        )
        pref = cur.fetchone()
        daily_stake = float((pref or {}).get("daily_stake") or 500)

    total = int(stats.get("total") or 0)
    won = int(stats.get("won") or 0)
    lost = int(stats.get("lost") or 0)
    resolved = won + lost
    win_rate = round(100 * won / resolved) if resolved > 0 else 0
    earned_kes = round(float(stats.get("total_odds_won") or 0) * daily_stake, 0)

    return {
        "total": total,
        "won": won,
        "lost": lost,
        "pending": int(stats.get("pending") or 0),
        "win_rate": win_rate,
        "daily_stake_kes": daily_stake,
        "earned_kes": earned_kes,
    }


@app.get("/api/user/{telegram_user_id}/slips")
def get_user_slips(telegram_user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Recent slip history for a user with legs."""
    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM bot_users WHERE channel = 'telegram' AND channel_user_id = %s",
            (telegram_user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return []
        user_id = user_row["id"]

        cur.execute(
            """
            SELECT bs.id, bs.sport, bs.slip_size, bs.status, bs.event_date,
                   bs.total_combined_odds, bs.created_at,
                   COALESCE(bup.stake_kes, 500) AS stake_kes
            FROM bot_slips bs
            LEFT JOIN bot_user_preferences bup ON bup.user_id = bs.user_id
            WHERE bs.user_id = %s
            ORDER BY bs.created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        slips = [dict(r) for r in cur.fetchall()]

        # Attach legs to each slip
        for slip in slips:
            cur.execute(
                """
                SELECT leg_no, home_team, away_team, pred_outcome, pred_probability,
                       selected_odds, probability_bucket, competition
                FROM bot_slip_legs
                WHERE slip_id = %s
                ORDER BY leg_no
                """,
                (slip["id"],),
            )
            slip["legs"] = [dict(r) for r in cur.fetchall()]
            slip["event_date"] = slip["event_date"].isoformat() if slip.get("event_date") else None
            slip["created_at"] = slip["created_at"].isoformat() if slip.get("created_at") else None
            stake = float(slip.get("stake_kes") or 500)
            odds = float(slip.get("total_combined_odds") or 1.0)
            slip["payout_kes"] = round(stake * odds) if slip.get("status") == "won" else None
            slip["stake_kes"] = stake

    return slips


# =============================================================================
# Static files (must be last so API routes are matched first)
# =============================================================================
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
