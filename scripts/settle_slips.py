"""
settle_slips.py
---------------
Settle pending bot slips by matching each leg against actual match results
from three sources: forebet_results, flashscore_results, sports_results.

Run this every day after your morning scrape:
    .venv\Scripts\python.exe scripts\settle_slips.py
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from psycopg.rows import dict_row
from ganji_mtaani_agent.db import get_postgres_connection

# ---------------------------------------------------------------------------
# Team name normalisation (simple — strips punctuation and common suffixes)
# ---------------------------------------------------------------------------
_STRIP_RE = re.compile(r"[^a-z0-9 ]")
_SUFFIXES = {"fc", "sc", "cf", "afc", "fk", "sk", "bk", "ac", "united",
             "city", "town", "athletic", "club", "sports"}

def _norm(name: str | None) -> str:
    if not name:
        return ""
    lower = _STRIP_RE.sub("", name.lower())
    tokens = [t for t in lower.split() if t not in _SUFFIXES]
    return " ".join(tokens).strip()

def _teams_match(a: str | None, b: str | None) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # One name is a subset of the other (handles abbreviations)
    return na in nb or nb in na


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
# (best: same team names as predictions, has pred_hit boolean)
# ---------------------------------------------------------------------------
def _lookup_forebet(cur, leg: dict) -> tuple[str | None, bool | None]:
    """Return (actual_outcome, won) or (None, None) if not found."""
    sport_vals = ["football", "soccer"] if leg.get("sport") == "football" else [leg.get("sport", "")]
    cur.execute(
        """
        SELECT actual_outcome, pred_hit, home_team, away_team
        FROM forebet_results
        WHERE LOWER(sport) = ANY(%s)
          AND actual_outcome IS NOT NULL
          AND event_datetime_text ~ E'^\\d{2}/\\d{2}/\\d{4}'
          AND TO_DATE(SUBSTRING(event_datetime_text, 1, 10), 'DD/MM/YYYY') = %s
        """,
        (sport_vals, leg["event_date"]),
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
        from datetime import datetime as _dt
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y"):
            try:
                if _dt.strptime(pd, fmt).date() == event_date:
                    matched_date = True
                    break
            except ValueError:
                pass
        if not matched_date:
            # Handle "DD/MM DayAbbr" format e.g. "04/06 Th" — infer year
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
# Main settlement logic
# ---------------------------------------------------------------------------
def settle_slips(lookback_days: int = 14) -> None:
    cutoff = date.today() - timedelta(days=lookback_days)

    with get_postgres_connection(autocommit=True) as conn, \
         conn.cursor(row_factory=dict_row) as cur:

        # Fetch pending slip legs for past matches
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
        print("No pending legs to settle.")
        return

    print(f"Settling {len(legs)} pending legs across {len({l['slip_id'] for l in legs})} slips…\n")

    settled_legs   = 0
    unresolved_legs = 0

    with get_postgres_connection(autocommit=True) as conn, \
         conn.cursor(row_factory=dict_row) as cur:

        for leg in legs:
            actual, won = None, None

            # Try each source in order of reliability
            for lookup_fn in (_lookup_forebet, _lookup_flashscore, _lookup_sports_db):
                actual, won = lookup_fn(cur, leg)
                if actual is not None:
                    break

            if actual is None:
                unresolved_legs += 1
                continue

            # Update the leg
            cur.execute(
                """
                UPDATE bot_slip_legs
                SET result_outcome = %s, won = %s
                WHERE id = %s
                """,
                (actual, won, leg["leg_id"]),
            )
            settled_legs += 1
            status = "✅" if won else "❌"
            print(
                f"  {status} {leg['home_team']} vs {leg['away_team']} "
                f"({leg['event_date']}) — pred {leg['pred_outcome']} | actual {actual}"
            )

        # Now settle full slips where all legs have results
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
                """
                SELECT won FROM bot_slip_legs WHERE slip_id = %s
                """,
                (slip_id,),
            )
            leg_results = [r["won"] for r in cur.fetchall()]

            if any(w is None for w in leg_results):
                slips_still_pending += 1
                continue  # Not all legs resolved yet

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
            print(f"\n  Slip {slip_id} → {new_status.upper()}")

    print("\n--- Summary ---")
    print(f"  Legs settled:   {settled_legs}")
    print(f"  Legs not found: {unresolved_legs}")
    print(f"  Slips WON:      {slips_won}")
    print(f"  Slips LOST:     {slips_lost}")
    print(f"  Still pending:  {slips_still_pending}")


if __name__ == "__main__":
    settle_slips()
