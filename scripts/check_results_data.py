"""Diagnose what result data exists vs what legs need settling."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
from psycopg.rows import dict_row
from ganji_mtaani_agent.db import get_postgres_connection

with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:

    # What dates/teams are in pending legs?
    cur.execute("""
        SELECT bsl.event_date, bsl.sport, bsl.home_team, bsl.away_team, bsl.pred_outcome
        FROM bot_slip_legs bsl
        JOIN bot_slips bs ON bs.id = bsl.slip_id
        WHERE bs.status = 'pending' AND bsl.event_date < CURRENT_DATE AND bsl.won IS NULL
        ORDER BY bsl.event_date
        LIMIT 10
    """)
    print("=== Pending legs sample ===")
    for r in cur.fetchall():
        print(f"  {r['event_date']}  {r['sport']:12}  {r['home_team']} vs {r['away_team']}  pick={r['pred_outcome']}")

    # What's in forebet_results?
    cur.execute("""
        SELECT DISTINCT TO_DATE(SUBSTRING(event_datetime_text,1,10),'DD/MM/YYYY') AS d, sport, COUNT(*) AS n
        FROM forebet_results
        WHERE actual_outcome IS NOT NULL
          AND event_datetime_text ~ E'^\\d{2}/\\d{2}/\\d{4}'
        GROUP BY d, sport ORDER BY d DESC LIMIT 10
    """)
    print("\n=== forebet_results (with actual_outcome) ===")
    for r in cur.fetchall():
        print(f"  {r['d']}  {r['sport']:12}  {r['n']} results")

    # What's in flashscore_results?
    cur.execute("""
        SELECT page_date_text, sport, COUNT(*) AS n
        FROM flashscore_results
        WHERE home_score IS NOT NULL
        GROUP BY page_date_text, sport ORDER BY page_date_text DESC LIMIT 10
    """)
    print("\n=== flashscore_results (with scores) ===")
    for r in cur.fetchall():
        print(f"  '{r['page_date_text']}'  {r['sport']:12}  {r['n']} results")

    # What's in sports_results?
    cur.execute("""
        SELECT event_date, sport, COUNT(*) AS n
        FROM sports_results
        WHERE home_score IS NOT NULL OR winner IS NOT NULL
        GROUP BY event_date, sport ORDER BY event_date DESC LIMIT 10
    """)
    print("\n=== sports_results (with scores/winner) ===")
    for r in cur.fetchall():
        print(f"  {r['event_date']}  {r['sport']:12}  {r['n']} results")

print("\nDone.")
