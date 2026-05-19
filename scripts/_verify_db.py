import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.db.postgres import get_postgres_connection

SQL = """
    SELECT product_name, product_type, confidence,
           jsonb_array_length(key_benefits)       AS benefits,
           COALESCE(jsonb_array_length(extra_data->'faqs'), 0) AS faqs,
           premium_min_kes, premium_frequency,
           min_age, max_age,
           LEFT(target_audience, 55) AS audience
    FROM insurance_products
    ORDER BY product_type, product_name
"""

with get_postgres_connection() as conn:
    rows = conn.execute(SQL).fetchall()

header = f"{'Name':<43} {'Type':<12} {'C':>3} {'Ben':>3} {'FAQ':>3} {'PremMin':>8} {'Freq':>8} {'Ages':>8}  Audience"
print(header)
print("-" * 130)
for r in rows:
    name, ptype, conf, bens, faqs, pmin, pfreq, minage, maxage, audience = r
    ages = f"{minage}-{maxage}" if minage and maxage else "-"
    prem = str(int(pmin)) if pmin else "-"
    freq = pfreq or "-"
    aud  = (audience or "-")
    print(f"{name[:42]:<43} {ptype:<12} {conf:>3} {bens:>3} {faqs:>3} {prem:>8} {freq:>8} {ages:>8}  {aud}")

print(f"\nTotal: {len(rows)} products")
