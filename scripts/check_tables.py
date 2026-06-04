from ganji_mtaani_agent.db import get_postgres_connection
from psycopg.rows import dict_row

with get_postgres_connection() as conn:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = [row["tablename"] for row in cur.fetchall()]

print(f"Found {len(tables)} tables:")
for t in tables:
    print(f"  {t}")
