"""Quick audit of canonical_fixtures data to verify what the bot can query."""
from datetime import date, timedelta
from ganji_mtaani_agent.db import get_postgres_connection
from psycopg.rows import dict_row

today = date.today()
tomorrow = today + timedelta(days=1)

with get_postgres_connection() as conn, conn.cursor(row_factory=dict_row) as cur:

    # 1. How many canonical fixtures exist per date (next 7 days)?
    cur.execute("""
        SELECT canonical_event_date, sport, COUNT(*) AS fixtures,
               SUM(CASE WHEN canonical_status = 'finished' THEN 1 ELSE 0 END) AS finished,
               SUM(CASE WHEN canonical_status IS NULL OR canonical_status != 'finished' THEN 1 ELSE 0 END) AS upcoming
        FROM canonical_fixtures
        WHERE canonical_event_date BETWEEN %s AND %s
        GROUP BY canonical_event_date, sport
        ORDER BY canonical_event_date, sport
    """, (today, today + timedelta(days=6)))
    print("=== Canonical fixtures next 7 days ===")
    for r in cur.fetchall():
        print(f"  {r['canonical_event_date']}  {r['sport']:12}  total={r['fixtures']}  finished={r['finished']}  upcoming={r['upcoming']}")

    # 2. How many are linked to forebet_predictions?
    cur.execute("""
        SELECT cf.canonical_event_date, cf.sport, COUNT(DISTINCT cf.id) AS canonical_linked
        FROM canonical_fixtures cf
        JOIN fixture_source_links fsl ON fsl.fixture_id = cf.id AND fsl.source_table = 'forebet_predictions'
        WHERE cf.canonical_event_date BETWEEN %s AND %s
        GROUP BY cf.canonical_event_date, cf.sport
        ORDER BY cf.canonical_event_date, cf.sport
    """, (today, today + timedelta(days=6)))
    print("\n=== Canonical fixtures WITH forebet link ===")
    for r in cur.fetchall():
        print(f"  {r['canonical_event_date']}  {r['sport']:12}  linked={r['canonical_linked']}")

    # 3. How many are linked to bookmaker_odds?
    cur.execute("""
        SELECT cf.canonical_event_date, cf.sport, COUNT(DISTINCT cf.id) AS with_odds
        FROM canonical_fixtures cf
        JOIN fixture_source_links fsl ON fsl.fixture_id = cf.id AND fsl.source_table = 'bookmaker_odds'
        WHERE cf.canonical_event_date BETWEEN %s AND %s
        GROUP BY cf.canonical_event_date, cf.sport
        ORDER BY cf.canonical_event_date, cf.sport
    """, (today, today + timedelta(days=6)))
    print("\n=== Canonical fixtures WITH bookmaker_odds link ===")
    for r in cur.fetchall():
        print(f"  {r['canonical_event_date']}  {r['sport']:12}  with_odds={r['with_odds']}")

    # 4. Sample the full joined query for today/tomorrow
    cur.execute("""
        SELECT
            cf.sport,
            cf.canonical_league,
            cf.canonical_home_team,
            cf.canonical_away_team,
            cf.canonical_event_date,
            cf.canonical_event_datetime_utc,
            cf.canonical_status,
            fp.pred_outcome,
            CASE
                WHEN fp.pred_outcome = '1' THEN fp.prob_1
                WHEN fp.pred_outcome = '2' THEN fp.prob_2
                WHEN fp.pred_outcome = 'X' THEN fp.prob_x
                ELSE NULL
            END AS pred_probability,
            bo.home_odds, bo.draw_odds, bo.away_odds,
            bo.source_name AS bookmaker_source
        FROM canonical_fixtures cf
        JOIN fixture_source_links fsl_fp ON fsl_fp.fixture_id = cf.id AND fsl_fp.source_table = 'forebet_predictions'
        JOIN forebet_predictions fp ON fp.id = fsl_fp.source_row_id
        LEFT JOIN fixture_source_links fsl_bo ON fsl_bo.fixture_id = cf.id AND fsl_bo.source_table = 'bookmaker_odds'
        LEFT JOIN bookmaker_odds bo ON bo.id = fsl_bo.source_row_id
        WHERE cf.canonical_event_date IN (%s, %s)
          AND (cf.canonical_status IS NULL OR cf.canonical_status != 'finished')
          AND fp.pred_outcome IS NOT NULL
        ORDER BY cf.canonical_event_date, pred_probability DESC NULLS LAST
        LIMIT 20
    """, (today, tomorrow))
    rows = cur.fetchall()
    print(f"\n=== Sample joined rows (today + tomorrow, limit 20) — {len(rows)} rows ===")
    for r in rows:
        odds_str = f"H={r['home_odds']} D={r['draw_odds']} A={r['away_odds']}" if r['home_odds'] else "no odds"
        time_str = r['canonical_event_datetime_utc'].strftime("%H:%M UTC") if r['canonical_event_datetime_utc'] else "time TBD"
        print(f"  {r['canonical_event_date']} {time_str}  {r['sport']:10}  "
              f"{r['canonical_home_team']} vs {r['canonical_away_team']}  "
              f"pick={r['pred_outcome']} prob={r['pred_probability']}%  {odds_str}")

print("\nDone.")
