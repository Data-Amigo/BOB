"""FastAPI backend for the BOB Telegram Mini App."""
from __future__ import annotations

import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
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

STATIC_DIR   = Path(__file__).parent / "static"
UPLOADS_DIR  = Path(__file__).resolve().parents[3] / "uploads" / "betslips"

app = FastAPI(title="BOB Mini App", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _log_db_config() -> None:
    url = os.getenv("DATABASE_URL", "")
    all_keys = sorted(os.environ.keys())
    db_keys = [k for k in all_keys if any(x in k for x in ("DATA", "PG", "POSTGRES", "RAILWAY", "DB"))]
    print(f"[startup] all env keys: {all_keys}", flush=True)
    print(f"[startup] DB-related keys: {db_keys}", flush=True)
    if url:
        print(f"[startup] DATABASE_URL found: {url[:45]}...", flush=True)
    else:
        print("[startup] WARNING: DATABASE_URL is NOT set — will fall back to localhost!", flush=True)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Pages
# =============================================================================
@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "ok"}


@app.get("/api/debug/env", include_in_schema=False)
def debug_env():
    url = os.getenv("DATABASE_URL", "")
    return {
        "database_url_set": bool(url),
        "database_url_prefix": url[:40] if url else None,
        "postgres_host": os.getenv("POSTGRES_HOST", "not set"),
        "all_env_var_names": sorted(os.environ.keys()),
    }


@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# =============================================================================
# API — Today's Slips
# =============================================================================
def _record_slip_for_user(user_id: int, sport: str, tier_name: str, tier_range: str,
                          combined_odds: float, rows: list[dict], today: date) -> None:
    """Save a viewed slip to bot_slips/bot_slip_legs if not already saved today."""
    import json as _json
    with get_postgres_connection(autocommit=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id FROM bot_slips
            WHERE user_id = %s AND sport = %s AND event_date = %s
              AND bucket_labels_json::text ILIKE %s
            LIMIT 1
            """,
            (user_id, sport, today, f'%{tier_name}%'),
        )
        if cur.fetchone():
            return   # already recorded today

        cur.execute(
            """
            INSERT INTO bot_slips
              (user_id, channel, sport, slip_size, bucket_labels_json,
               status, event_date, total_combined_odds, source_logic, created_at, updated_at)
            VALUES (%s, 'miniapp', %s, %s, %s::jsonb, 'pending', %s, %s, 'miniapp_view', NOW(), NOW())
            RETURNING id
            """,
            (user_id, sport, len(rows),
             _json.dumps([f"{tier_name} ({tier_range})"]),
             today, combined_odds),
        )
        slip_row = cur.fetchone()
        if not slip_row:
            return
        slip_id = slip_row["id"]

        for i, r in enumerate(rows, start=1):
            cur.execute(
                """
                INSERT INTO bot_slip_legs
                  (slip_id, leg_no, sport, event_date, home_team, away_team,
                   pred_outcome, pred_probability, probability_bucket,
                   selected_odds, bookmaker_source, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (slip_id, leg_no) DO NOTHING
                """,
                (slip_id, i, sport,
                 r.get("event_date"),
                 r.get("home_team"), r.get("away_team"),
                 r.get("pred_outcome"),
                 r.get("pred_probability"),
                 r.get("probability_bucket"),
                 r.get("selected_odds"),
                 r.get("bookmaker_source")),
            )


@app.get("/api/today-slips")
def get_today_slips(telegram_user_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Return Gold/Silver/Bronze tiered slips for football and basketball.
    If telegram_user_id is provided, auto-saves the slips for that user."""
    today = date.today()
    result: dict[str, list[dict[str, Any]]] = {}

    # Resolve internal user_id once so we can record slips per tier
    db_user_id: int | None = None
    if telegram_user_id:
        try:
            with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT id FROM bot_users WHERE channel='telegram' AND channel_user_id=%s",
                    (telegram_user_id,),
                )
                row = cur.fetchone()
                db_user_id = row["id"] if row else None
        except Exception:
            pass

    SLIP_SIZE = 4

    # Football uses 70%+; basketball 80%+ only (Bronze excluded for basketball)
    sport_config: dict[str, tuple[float, list]] = {
        "football":   (70.0, [
            ("Gold",   "90-100%", 90.0, 101.0),
            ("Silver", "80-90%",  80.0,  90.0),
            ("Bronze", "70-80%",  70.0,  80.0),
        ]),
        "basketball": (80.0, [
            ("Gold",   "90-100%", 90.0, 101.0),
            ("Silver", "80-90%",  80.0,  90.0),
        ]),
    }

    for sport, (min_prob, tier_defs) in sport_config.items():
        all_candidates = _fetch_upcoming_forebet_candidates(sport=sport, min_probability=min_prob)
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

            # Cross-tier fill: when < SLIP_SIZE games in this tier, pull best
            # remaining games from lower tiers (still ≥ sport's min_prob)
            mixed = False
            if len(pool) < SLIP_SIZE:
                used = {(r.get("home_team"), r.get("away_team"), str(r.get("event_date"))) for r in pool}
                fillers = sorted(
                    [r for r in all_candidates
                     if (r.get("pred_probability") or 0) >= min_prob
                     and (r.get("pred_probability") or 0) < min_p
                     and (r.get("home_team"), r.get("away_team"), str(r.get("event_date"))) not in used],
                    key=lambda r: -(r.get("pred_probability") or 0),
                )
                today_fill  = [r for r in fillers if r.get("event_date") == today]
                other_fill  = [r for r in fillers if r.get("event_date") != today]
                fill_picked = (today_fill + other_fill)[: SLIP_SIZE - len(pool)]
                if fill_picked:
                    pool  = pool + fill_picked
                    mixed = True

            rows = _attach_best_odds(pool[:SLIP_SIZE], sport=sport)

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
                "range": f"{tier_range}+" if mixed else tier_range,
                "emoji": _TIER_EMOJIS.get(tier_name, ""),
                "games": len(rows),
                "combined_odds": round(combined, 2),
                "legs": legs,
                "mixed": mixed,
            })

            # Auto-record this slip for the user so analytics builds daily
            if db_user_id and rows:
                try:
                    _record_slip_for_user(db_user_id, sport, tier_name, tier_range,
                                          round(combined, 2), rows, today)
                except Exception:
                    pass

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
def get_successful_teams(days: int = 7, sport: str = "all") -> list[dict[str, Any]]:
    """Teams appearing most in winning slips over the last N days."""
    cutoff = date.today() - timedelta(days=days)
    sport_clause = "" if sport == "all" else "AND bsl.sport = %(sport)s"

    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            WITH team_appearances AS (
                SELECT bsl.home_team AS team,
                       COUNT(*) AS appearances,
                       COUNT(CASE WHEN bs.status = 'won' THEN 1 END) AS wins
                FROM bot_slip_legs bsl
                JOIN bot_slips bs ON bs.id = bsl.slip_id
                WHERE bs.created_at >= %(cutoff)s
                  AND bsl.home_team IS NOT NULL
                  {sport_clause}
                GROUP BY bsl.home_team

                UNION ALL

                SELECT bsl.away_team AS team,
                       COUNT(*) AS appearances,
                       COUNT(CASE WHEN bs.status = 'won' THEN 1 END) AS wins
                FROM bot_slip_legs bsl
                JOIN bot_slips bs ON bs.id = bsl.slip_id
                WHERE bs.created_at >= %(cutoff)s
                  AND bsl.away_team IS NOT NULL
                  {sport_clause}
                GROUP BY bsl.away_team
            )
            SELECT team,
                   SUM(appearances) AS appearances,
                   SUM(wins) AS wins
            FROM team_appearances
            GROUP BY team
            HAVING SUM(wins) >= 1
            ORDER BY SUM(wins) DESC, SUM(appearances) DESC
            LIMIT 10
            """,
            {"cutoff": cutoff, "sport": sport},
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
def get_user_stats(telegram_user_id: str, days: int = 7, sport: str = "all") -> dict[str, Any]:
    """Personal slip stats and net P&L, optionally filtered by sport."""
    cutoff = date.today() - timedelta(days=days)
    sport_filter = "" if sport == "all" else "AND bs.sport = %(sport)s"

    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM bot_users WHERE channel = 'telegram' AND channel_user_id = %s",
            (telegram_user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return {"total": 0, "won": 0, "lost": 0, "pending": 0, "win_rate": 0, "net_pnl_kes": 0}
        user_id = user_row["id"]

        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(CASE WHEN bs.status = 'won'  THEN 1 END) AS won,
                COUNT(CASE WHEN bs.status = 'lost' THEN 1 END) AS lost,
                COUNT(CASE WHEN bs.status = 'pending' THEN 1 END) AS pending,
                COALESCE(SUM(
                    CASE WHEN bs.status = 'won' AND bs.total_combined_odds IS NOT NULL
                    THEN COALESCE(bs.stake_kes, bup.stake_kes, 500) * bs.total_combined_odds
                    ELSE 0 END
                ), 0) AS gross_won_kes,
                COALESCE(SUM(
                    CASE WHEN bs.status IN ('won', 'lost')
                    THEN COALESCE(bs.stake_kes, bup.stake_kes, 500)
                    ELSE 0 END
                ), 0) AS total_staked_kes,
                COALESCE(MAX(bup.stake_kes), 500) AS daily_stake
            FROM bot_slips bs
            LEFT JOIN bot_user_preferences bup ON bup.user_id = bs.user_id
            WHERE bs.user_id = %(user_id)s AND bs.created_at >= %(cutoff)s
            {sport_filter}
            """,
            {"user_id": user_id, "cutoff": cutoff, "sport": sport},
        )
        stats = dict(cur.fetchone() or {})

    total = int(stats.get("total") or 0)
    won = int(stats.get("won") or 0)
    lost = int(stats.get("lost") or 0)
    resolved = won + lost
    win_rate = round(100 * won / resolved) if resolved > 0 else 0
    gross_won = float(stats.get("gross_won_kes") or 0)
    total_staked = float(stats.get("total_staked_kes") or 0)
    net_pnl = round(gross_won - total_staked, 0)
    daily_stake = float(stats.get("daily_stake") or 500)

    return {
        "total": total,
        "won": won,
        "lost": lost,
        "pending": int(stats.get("pending") or 0),
        "win_rate": win_rate,
        "daily_stake_kes": daily_stake,
        "net_pnl_kes": net_pnl,
        "days": days,
    }


def _parse_tier(bucket_labels_json) -> str:
    labels = bucket_labels_json or []
    label = str(labels[0]) if isinstance(labels, list) and labels else str(labels or "")
    if "Gold" in label or "90" in label:
        return "Gold"
    if "Silver" in label or "80" in label:
        return "Silver"
    if "Bronze" in label or "70" in label:
        return "Bronze"
    return ""


@app.get("/api/user/{telegram_user_id}/slips")
def get_user_slips(telegram_user_id: str, limit: int = 50, days: int = 90) -> list[dict[str, Any]]:
    """Slip history for a user with legs, filtered by number of past days."""
    cutoff = date.today() - timedelta(days=days)

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
                   bs.total_combined_odds, bs.created_at, bs.bucket_labels_json,
                   COALESCE(bs.stake_kes, bup.stake_kes, 500) AS stake_kes
            FROM bot_slips bs
            LEFT JOIN bot_user_preferences bup ON bup.user_id = bs.user_id
            WHERE bs.user_id = %s AND bs.created_at >= %s
            ORDER BY bs.created_at DESC
            LIMIT %s
            """,
            (user_id, cutoff, limit),
        )
        slips = [dict(r) for r in cur.fetchall()]

        for slip in slips:
            cur.execute(
                """
                SELECT leg_no, home_team, away_team, pred_outcome, pred_probability,
                       selected_odds, probability_bucket, competition,
                       result_outcome, won
                FROM bot_slip_legs
                WHERE slip_id = %s
                ORDER BY leg_no
                """,
                (slip["id"],),
            )
            slip["legs"] = [dict(r) for r in cur.fetchall()]
            slip["tier"] = _parse_tier(slip.pop("bucket_labels_json", None))
            slip["event_date"] = slip["event_date"].isoformat() if slip.get("event_date") else None
            slip["created_at"] = slip["created_at"].isoformat() if slip.get("created_at") else None
            stake = float(slip.get("stake_kes") or 500)
            odds = float(slip.get("total_combined_odds") or 1.0)
            slip["payout_kes"] = round(stake * odds) if slip.get("status") == "won" else None
            slip["stake_kes"] = stake

    return slips


@app.get("/api/user/{telegram_user_id}/analytics")
def get_user_analytics(telegram_user_id: str, days: int = 30, sport: str = "all") -> dict[str, Any]:
    """Per-tier performance breakdown for a user, optionally filtered by sport."""
    cutoff = date.today() - timedelta(days=days)

    with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM bot_users WHERE channel = 'telegram' AND channel_user_id = %s",
            (telegram_user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return {"tiers": []}
        user_id = user_row["id"]

        sport_filter = "" if sport == "all" else "AND bs.sport = %(sport)s"
        cur.execute(
            f"""
            SELECT bs.bucket_labels_json, bs.status, bs.total_combined_odds,
                   bs.sport,
                   COALESCE(bs.stake_kes, bup.stake_kes, 500) AS stake_kes
            FROM bot_slips bs
            LEFT JOIN bot_user_preferences bup ON bup.user_id = bs.user_id
            WHERE bs.user_id = %(user_id)s AND bs.created_at >= %(cutoff)s
              AND bs.status IN ('won', 'lost')
              {sport_filter}
            """,
            {"user_id": user_id, "cutoff": cutoff, "sport": sport},
        )
        slips = cur.fetchall()

    buckets: dict[str, dict] = {
        "Gold":   {"total": 0, "won": 0, "earned": 0.0},
        "Silver": {"total": 0, "won": 0, "earned": 0.0},
        "Bronze": {"total": 0, "won": 0, "earned": 0.0},
    }
    for slip in slips:
        tier = _parse_tier(slip["bucket_labels_json"])
        if tier not in buckets:
            continue
        buckets[tier]["total"] += 1
        if slip["status"] == "won":
            buckets[tier]["won"] += 1
            buckets[tier]["earned"] += float(slip.get("total_combined_odds") or 1.0) * float(slip.get("stake_kes") or 500)

    emojis = {"Gold": "🥇", "Silver": "🥈", "Bronze": "🥉"}
    tiers = []
    for name in ("Gold", "Silver", "Bronze"):
        b = buckets[name]
        resolved = b["total"]
        win_rate = round(100 * b["won"] / resolved) if resolved > 0 else 0
        tiers.append({
            "tier": name,
            "emoji": emojis[name],
            "total": b["total"],
            "won": b["won"],
            "lost": b["total"] - b["won"],
            "win_rate": win_rate,
            "earned_kes": round(b["earned"]),
        })

    return {"tiers": tiers}


# =============================================================================
# API — Betslip image upload
# =============================================================================
@app.post("/api/slips/upload-image")
async def upload_betslip_image(
    telegram_user_id: str = Form(...),
    note: str = Form(""),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Save an uploaded betslip image for the user."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "slip.jpg").suffix or ".jpg"
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{telegram_user_id}_{timestamp}{ext}"
    dest = UPLOADS_DIR / filename
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return {"status": "ok", "filename": filename}


# =============================================================================
# Static files (must be last so API routes are matched first)
# =============================================================================
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
