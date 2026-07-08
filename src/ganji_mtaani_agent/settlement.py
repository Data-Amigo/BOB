"""
settlement.py
-------------
Settle pending bot slips by matching each leg against actual match results
from three sources: forebet_results, flashscore_results, sports_results.

Called automatically at the end of run_daily_ingestion(), but can also be
run manually:
    .venv\Scripts\python.exe scripts\settle_slips.py
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from psycopg.rows import dict_row

from ganji_mtaani_agent.db import get_postgres_connection

# ---------------------------------------------------------------------------
# Team name normalisation
# ---------------------------------------------------------------------------
_STRIP_RE   = re.compile(r"[^a-z0-9 ]")
_HYPHEN_AGE = re.compile(r"\bu-(\d{2})\b")   # u-20 → u20, u-23 → u23
_SUFFIXES = {"fc", "sc", "cf", "afc", "fk", "sk", "bk", "ac", "united",
             "city", "town", "athletic", "club", "sports", "de", "da", "do"}


def _norm(name: str | None) -> str:
    if not name:
        return ""
    lower = name.lower()
    lower = _HYPHEN_AGE.sub(r"u\1", lower)          # u-20 → u20 before stripping hyphens
    lower = _STRIP_RE.sub("", lower)
    tokens = [t for t in lower.split() if t not in _SUFFIXES]
    return " ".join(tokens).strip()


def _teams_match(a: str | None, b: str | None) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    # Token-overlap fallback: useful for "Vasco U20" vs "Vasco da Gama U20"
    ta, tb = set(na.split()), set(nb.split())
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not shorter:
        return False
    # Single-word short name: the word must appear in the longer name
    if len(shorter) == 1:
        return bool(shorter & longer)
    # Multi-word: at least ceil(len(shorter)/2) tokens must overlap,
    # and the first token (usually most distinctive) must be shared
    first = list(shorter)[0]
    overlap = shorter & longer
    return first in longer and len(overlap) >= max(1, (len(shorter) + 1) // 2)


# ---------------------------------------------------------------------------
# Derive outcome string (1 / 2 / X) from scores
# ---------------------------------------------------------------------------
def _outcome_from_scores(home: int | None, away: int | None) -> str | None:
    if home is None or away is None:
        return None
    if home > away:
        return "1"
    if away > home:
        return "2"
    return "X"


# ---------------------------------------------------------------------------
# Source 1 — forebet_results
# ---------------------------------------------------------------------------
def _lookup_forebet_by_url_id(cur, leg: dict) -> tuple[str | None, bool | None]:
    """Match by the numeric match ID at the end of the Forebet URL — most reliable."""
    url = leg.get("match_url") or ""
    m = re.search(r"(\d{5,})$", url)
    if not m:
        return None, None
    match_id = m.group(1)
    cur.execute(
        """
        SELECT actual_outcome, pred_hit, pred_outcome
        FROM forebet_results
        WHERE match_url LIKE %s AND actual_outcome IS NOT NULL
        LIMIT 1
        """,
        (f"%{match_id}",),
    )
    row = cur.fetchone()
    if not row:
        return None, None
    actual = str(row["actual_outcome"] or "").strip().upper()
    pred   = str(leg.get("pred_outcome") or "").strip().upper()
    won    = actual == pred if actual and pred else row.get("pred_hit")
    return actual or None, won


def _lookup_forebet(cur, leg: dict) -> tuple[str | None, bool | None]:
    sport_vals = ["football", "soccer"] if leg.get("sport") == "football" else [leg.get("sport", "")]
    event_date: date = leg["event_date"]
    # ±1 day window handles timezone shifts between forebet server and local time
    date_lo = event_date - timedelta(days=1)
    date_hi = event_date + timedelta(days=1)
    cur.execute(
        """
        SELECT actual_outcome, pred_hit, home_team, away_team
        FROM forebet_results
        WHERE LOWER(sport) = ANY(%s)
          AND actual_outcome IS NOT NULL
          AND event_datetime_text ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}'
          AND TO_DATE(SUBSTRING(event_datetime_text, 1, 10), 'DD/MM/YYYY') BETWEEN %s AND %s
        """,
        (sport_vals, date_lo, date_hi),
    )
    for row in cur.fetchall():
        if _teams_match(row["home_team"], leg["home_team"]) and \
           _teams_match(row["away_team"], leg["away_team"]):
            actual = str(row["actual_outcome"] or "").strip().upper()
            pred   = str(leg.get("pred_outcome") or "").strip().upper()
            won    = actual == pred if actual and pred else row.get("pred_hit")
            return actual or None, won
    return None, None


# ---------------------------------------------------------------------------
# Source 2 — flashscore_results
# ---------------------------------------------------------------------------
def _lookup_flashscore(cur, leg: dict) -> tuple[str | None, bool | None]:
    from datetime import datetime as _dt
    sport_vals = ["football", "soccer"] if leg.get("sport") == "football" else [leg.get("sport", "")]
    cur.execute(
        """
        SELECT home_team, away_team, home_score, away_score, page_date_text
        FROM flashscore_results
        WHERE LOWER(sport) = ANY(%s)
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND page_date_text IS NOT NULL
        ORDER BY created_at DESC
        """,
        (sport_vals,),
    )
    event_date: date = leg["event_date"]
    for row in cur.fetchall():
        pd = str(row["page_date_text"] or "")
        matched_date = False
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y"):
            try:
                if _dt.strptime(pd, fmt).date() == event_date:
                    matched_date = True
                    break
            except ValueError:
                pass
        if not matched_date:
            m = re.match(r"(\d{2})/(\d{2})", pd)
            if m:
                day, month = int(m.group(1)), int(m.group(2))
                for yr in (event_date.year, event_date.year - 1):
                    try:
                        if date(yr, month, day) == event_date:
                            matched_date = True
                            break
                    except ValueError:
                        pass
        if not matched_date:
            continue
        if _teams_match(row["home_team"], leg["home_team"]) and \
           _teams_match(row["away_team"], leg["away_team"]):
            actual = _outcome_from_scores(row["home_score"], row["away_score"])
            pred   = str(leg.get("pred_outcome") or "").strip().upper()
            won    = actual == pred if actual and pred else None
            return actual, won
    return None, None


# ---------------------------------------------------------------------------
# Source 3 — sports_results
# ---------------------------------------------------------------------------
def _lookup_sports_db(cur, leg: dict) -> tuple[str | None, bool | None]:
    sport_vals = ["soccer", "football"] if leg.get("sport") == "football" else [leg.get("sport", "")]
    cur.execute(
        """
        SELECT home_team, away_team, home_score, away_score, winner
        FROM sports_results
        WHERE LOWER(sport) = ANY(%s)
          AND event_date = %s
          AND (home_score IS NOT NULL OR winner IS NOT NULL)
        """,
        (sport_vals, leg["event_date"]),
    )
    for row in cur.fetchall():
        if not (_teams_match(row["home_team"], leg["home_team"]) and
                _teams_match(row["away_team"], leg["away_team"])):
            continue
        actual = _outcome_from_scores(row["home_score"], row["away_score"])
        if actual is None and row.get("winner"):
            w = str(row["winner"]).lower()
            if "home" in w:
                actual = "1"
            elif "away" in w:
                actual = "2"
            elif "draw" in w:
                actual = "X"
        pred = str(leg.get("pred_outcome") or "").strip().upper()
        won  = actual == pred if actual and pred else None
        return actual, won
    return None, None


# ---------------------------------------------------------------------------
# Main settlement function
# ---------------------------------------------------------------------------
def settle_slips(lookback_days: int = 14) -> dict:
    """
    Settle all pending slip legs whose event_date is in the past.
    Returns a summary dict with counts.
    """
    cutoff = date.today() - timedelta(days=lookback_days)

    with get_postgres_connection(autocommit=True) as conn, \
         conn.cursor(row_factory=dict_row) as cur:

        cur.execute(
            """
            SELECT bsl.id AS leg_id, bsl.slip_id, bsl.leg_no,
                   bsl.sport, bsl.event_date, bsl.home_team, bsl.away_team,
                   bsl.pred_outcome, bsl.won
            FROM bot_slip_legs bsl
            JOIN bot_slips bs ON bs.id = bsl.slip_id
            WHERE bs.status = 'pending'
              AND bsl.event_date IS NOT NULL
              AND bsl.event_date < CURRENT_DATE
              AND bsl.event_date >= %s
              AND bsl.won IS NULL
            ORDER BY bsl.event_date, bsl.slip_id, bsl.leg_no
            """,
            (cutoff,),
        )
        legs = [dict(r) for r in cur.fetchall()]

    if not legs:
        return {"legs_settled": 0, "legs_unresolved": 0, "slips_won": 0, "slips_lost": 0, "slips_still_pending": 0}

    settled_legs = 0
    unresolved_legs = 0

    with get_postgres_connection(autocommit=True) as conn, \
         conn.cursor(row_factory=dict_row) as cur:

        for leg in legs:
            actual, won = None, None

            for lookup_fn in (_lookup_forebet_by_url_id, _lookup_forebet, _lookup_flashscore, _lookup_sports_db):
                actual, won = lookup_fn(cur, leg)
                if actual is not None:
                    break

            if actual is None:
                unresolved_legs += 1
                continue

            cur.execute(
                """
                UPDATE bot_slip_legs
                SET result_outcome = %s, won = %s
                WHERE id = %s
                """,
                (actual, won, leg["leg_id"]),
            )
            settled_legs += 1

        # Settle full slips where all legs are resolved
        cur.execute(
            """
            SELECT DISTINCT bsl.slip_id
            FROM bot_slip_legs bsl
            JOIN bot_slips bs ON bs.id = bsl.slip_id
            WHERE bs.status = 'pending'
              AND bsl.event_date < CURRENT_DATE
            """
        )
        slip_ids = [r["slip_id"] for r in cur.fetchall()]

        slips_won = slips_lost = slips_still_pending = 0

        for slip_id in slip_ids:
            cur.execute(
                "SELECT won FROM bot_slip_legs WHERE slip_id = %s",
                (slip_id,),
            )
            leg_results = [r["won"] for r in cur.fetchall()]

            if any(w is None for w in leg_results):
                slips_still_pending += 1
                continue

            if all(w is True for w in leg_results):
                new_status = "won"
                slips_won += 1
            else:
                new_status = "lost"
                slips_lost += 1

            cur.execute(
                "UPDATE bot_slips SET status = %s, updated_at = NOW() WHERE id = %s",
                (new_status, slip_id),
            )

    return {
        "legs_settled": settled_legs,
        "legs_unresolved": unresolved_legs,
        "slips_won": slips_won,
        "slips_lost": slips_lost,
        "slips_still_pending": slips_still_pending,
    }
