"""Check what probability ranges and dates actually exist for upcoming games."""
from datetime import date
from ganji_mtaani_agent.db import get_postgres_connection
from psycopg.rows import dict_row

today = date.today()
today_str = today.strftime("%d/%m/%Y")

with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:

    # Upcoming games by sport and probability bucket
    cur.execute("""
        SELECT
            sport,
            SUBSTRING(event_datetime_text FROM 1 FOR 10) AS event_date_text,
            COUNT(*) AS total,
            SUM(CASE WHEN
                CASE WHEN pred_outcome='1' THEN prob_1
                     WHEN pred_outcome='2' THEN prob_2
                     WHEN pred_outcome='X' THEN prob_x
                END >= 70 THEN 1 ELSE 0 END) AS prob_70_plus,
            SUM(CASE WHEN
                CASE WHEN pred_outcome='1' THEN prob_1
                     WHEN pred_outcome='2' THEN prob_2
                     WHEN pred_outcome='X' THEN prob_x
                END >= 60 THEN 1 ELSE 0 END) AS prob_60_plus,
            SUM(CASE WHEN
                CASE WHEN pred_outcome='1' THEN prob_1
                     WHEN pred_outcome='2' THEN prob_2
                     WHEN pred_outcome='X' THEN prob_x
                END >= 50 THEN 1 ELSE 0 END) AS prob_50_plus,
            MAX(CASE WHEN pred_outcome='1' THEN prob_1
                     WHEN pred_outcome='2' THEN prob_2
                     WHEN pred_outcome='X' THEN prob_x
                END) AS max_prob
        FROM forebet_predictions
        WHERE event_datetime_text >= %s
          AND pred_outcome IS NOT NULL
        GROUP BY sport, event_date_text
        ORDER BY event_date_text, sport
        LIMIT 30
    """, (today_str,))
    rows = cur.fetchall()
    print(f"=== Upcoming forebet data (event_datetime_text >= today: {today_str}) ===")
    if not rows:
        print("  No rows found with event_datetime_text >= today_str (text comparison)")

    for r in rows:
        print(f"  {r['event_date_text']}  {r['sport']:12}  total={r['total']:3}  "
              f"70%+={r['prob_70_plus']:3}  60%+={r['prob_60_plus']:3}  "
              f"50%+={r['prob_50_plus']:3}  max={r['max_prob']}%")

    # Try numeric date comparison via text parsing
    cur.execute("""
        SELECT sport,
               event_datetime_text,
               pred_outcome,
               CASE WHEN pred_outcome='1' THEN prob_1
                    WHEN pred_outcome='2' THEN prob_2
                    WHEN pred_outcome='X' THEN prob_x
               END AS pred_prob
        FROM forebet_predictions
        WHERE event_datetime_text LIKE %s
          AND pred_outcome IS NOT NULL
        ORDER BY CASE WHEN pred_outcome='1' THEN prob_1
                      WHEN pred_outcome='2' THEN prob_2
                      WHEN pred_outcome='X' THEN prob_x END DESC NULLS LAST
        LIMIT 20
    """, (today.strftime("%d/%m/%Y") + "%",))
    rows = cur.fetchall()
    print(f"\n=== Games with event_datetime_text matching today ({today.strftime('%d/%m/%Y')}) — top 20 by prob ===")
    for r in rows:
        print(f"  {r['sport']:12}  {r['event_datetime_text']:22}  pick={r['pred_outcome']}  prob={r['pred_prob']}%")

    # Football only - what's the highest probability upcoming?
    cur.execute("""
        SELECT home_team, away_team, event_datetime_text, league, pred_outcome,
               CASE WHEN pred_outcome='1' THEN prob_1
                    WHEN pred_outcome='2' THEN prob_2
                    WHEN pred_outcome='X' THEN prob_x
               END AS pred_prob
        FROM forebet_predictions
        WHERE LOWER(sport) IN ('football', 'soccer')
          AND pred_outcome IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 20
    """)
    rows = cur.fetchall()
    print(f"\n=== Most recent football/soccer rows (by scrape time) ===")
    for r in rows:
        print(f"  {r['event_datetime_text']:22}  {r['home_team']} vs {r['away_team']}  "
              f"pick={r['pred_outcome']}  prob={r['pred_prob']}%")

print("\nDone.")
