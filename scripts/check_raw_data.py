"""Audit raw forebet_predictions and bookmaker_odds for upcoming games."""
from datetime import date
from ganji_mtaani_agent.db import get_postgres_connection
from psycopg.rows import dict_row

with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:

    # 1. Most recent forebet_predictions rows
    cur.execute("""
        SELECT id, source_name, sport, league, home_team, away_team,
               event_datetime_text, pred_outcome,
               CASE WHEN pred_outcome='1' THEN prob_1
                    WHEN pred_outcome='2' THEN prob_2
                    WHEN pred_outcome='X' THEN prob_x
               END AS pred_probability,
               created_at
        FROM forebet_predictions
        WHERE pred_outcome IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 15
    """)
    rows = cur.fetchall()
    print(f"=== Latest forebet_predictions ({len(rows)} rows) ===")
    for r in rows:
        print(f"  [{r['id']}] {r['event_datetime_text']:20}  {r['sport']:10}  "
              f"{r['home_team']} vs {r['away_team']}  "
              f"pick={r['pred_outcome']} prob={r['pred_probability']}%  "
              f"scraped={r['created_at'].date()}")

    # 2. Distinct event dates in forebet_predictions
    cur.execute("""
        SELECT DISTINCT event_datetime_text,
               SUBSTRING(event_datetime_text FROM 1 FOR 10) AS date_part,
               COUNT(*) AS cnt
        FROM forebet_predictions
        WHERE event_datetime_text IS NOT NULL
        GROUP BY event_datetime_text
        ORDER BY event_datetime_text DESC
        LIMIT 20
    """)
    print("\n=== Distinct event_datetime_text values (latest 20) ===")
    for r in cur.fetchall():
        print(f"  '{r['event_datetime_text']}'  count={r['cnt']}")

    # 3. Latest bookmaker_odds
    cur.execute("""
        SELECT id, source_name, sport, home_team, away_team,
               event_datetime_text, home_odds, draw_odds, away_odds,
               created_at
        FROM bookmaker_odds
        ORDER BY created_at DESC, id DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    print(f"\n=== Latest bookmaker_odds ({len(rows)} rows) ===")
    for r in rows:
        print(f"  [{r['id']}] {r['event_datetime_text']:20}  {r['sport']:10}  "
              f"{r['home_team']} vs {r['away_team']}  "
              f"H={r['home_odds']} D={r['draw_odds']} A={r['away_odds']}  "
              f"scraped={r['created_at'].date()}")

    # 4. Total row counts
    for tbl in ("forebet_predictions", "bookmaker_odds", "canonical_fixtures", "fixture_source_links"):
        cur.execute(f"SELECT COUNT(*) AS n FROM {tbl}")
        print(f"\n  {tbl}: {cur.fetchone()['n']} rows total")

print("\nDone.")
