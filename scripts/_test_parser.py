"""Quick local test: run the jubilee parser against saved snapshots."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.insurance.parsers import jubilee

snapshots = [
    ("data/raw/insurance/jubilee/life/20260519_073049.html", "https://jubileeinsurance.com/ke/life-individual/faida-maisha-plan/", "life"),
    ("data/raw/insurance/jubilee/asset_management/20260519_073106.html", "https://jubileeinsurance.com/ke/asset-management-products/umbrella-retirement-solution/", "investment"),
]

for path, url, category in snapshots:
    html = Path(path).read_text(encoding="utf-8")
    p = jubilee.parse_product_page(html, url, category)
    if p is None:
        print(f"[FAIL] {path} -> None")
        continue
    print(f"\n{'='*60}")
    print(f"  {p.product_name}")
    print(f"  confidence:      {p.confidence}")
    print(f"  description:     {p.description[:120]}...")
    print(f"  target_audience: {p.target_audience}")
    print(f"  benefits ({len(p.key_benefits)}):")
    for b in p.key_benefits[:5]:
        print(f"    - {b[:90]}")
    if len(p.key_benefits) > 5:
        print(f"    ... and {len(p.key_benefits) - 5} more")
    print(f"  premium_min_kes: {p.premium_min_kes}")
    print(f"  premium_freq:    {p.premium_frequency}")
    print(f"  min_age:         {p.min_age}")
    print(f"  max_age:         {p.max_age}")
    faqs = p.extra_data.get("faqs", [])
    print(f"  faqs:            {len(faqs)}")
    for faq in faqs[:3]:
        print(f"    Q: {faq['q'][:70]}")
        print(f"    A: {faq['a'][:70]}")
