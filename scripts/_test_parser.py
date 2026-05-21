"""Quick local test: run parsers against saved snapshots."""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.insurance.parsers import britam, jubilee, old_mutual


def _print_product(p, label):
    if p is None:
        print(f"  [FAIL] {label} -> None")
        return
    print(f"\n  Product:     {p.product_name}")
    print(f"  Type:        {p.product_type}")
    print(f"  Confidence:  {p.confidence}")
    print(f"  Description: {p.description[:100]}...")
    print(f"  Tagline:     {p.tagline}")
    print(f"  Audience:    {p.target_audience}")
    print(f"  Benefits ({len(p.key_benefits)}):")
    for b in p.key_benefits[:4]:
        print(f"    - {b[:85]}")
    print(f"  Premium:     {p.premium_min_kes} {p.premium_frequency or ''}")
    print(f"  Ages:        {p.min_age}-{p.max_age}")
    print(f"  Coverage:    {p.coverage_notes}")
    print(f"  Phone:       {p.contact_phone}")
    faqs = p.extra_data.get("faqs", [])
    brochures = p.extra_data.get("brochures", [])
    cov_table = p.extra_data.get("coverage_table", [])
    print(f"  FAQs:        {len(faqs)}")
    print(f"  Brochures:   {len(brochures)}")
    print(f"  Cov table:   {len(cov_table)} rows")


# ── Jubilee ──────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("JUBILEE")
print("="*70)
jubilee_snapshots = [
    ("data/raw/insurance/jubilee/life/20260519_073049.html",
     "https://jubileeinsurance.com/ke/life-individual/faida-maisha-plan/", "life"),
]
for path, url, cat in jubilee_snapshots:
    html = Path(path).read_text(encoding="utf-8")
    p = jubilee.parse_product_page(html, url, cat)
    _print_product(p, path)

# ── Britam listing ────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("BRITAM — listing page (protect-who-you-love)")
print("="*70)
listing_html = Path("data/raw/insurance/britam/health/20260519_172943.html").read_text(encoding="utf-8")
urls = britam.parse_product_listing(listing_html, "https://ke.britam.com", "https://ke.britam.com/home/personal/protect-who-you-love")
print(f"  found {len(urls)} product URLs:")
for u in urls:
    print(f"    {u}")

# ── Britam detail pages ───────────────────────────────────────────────────────
britam_detail_cases = [
    ("data/raw/insurance/britam/health/20260519_173213.html",
     "https://ke.britam.com/home/personal/protect-who-you-love/health-insurance-covers/milele-health-quality-healthcare", "health"),
    ("data/raw/insurance/britam/personal_protection/20260519_181941.html",
     "https://ke.britam.com/home/personal/protect-who-you-love/family-protection-plans/careplus-protection-plan", "life"),
    ("data/raw/insurance/britam/personal_protection/20260519_181945.html",
     "https://ke.britam.com/home/personal/protect-who-you-love/personal-accident-covers/student-personal-accident", "personal_accident"),
]
for snap, url, cat in britam_detail_cases:
    print(f"\n--- {url.split('/')[-1]} ---")
    html = Path(snap).read_text(encoding="utf-8")
    p = britam.parse_product_page(html, url, cat)
    _print_product(p, snap)

# ── Old Mutual detail pages ───────────────────────────────────────────────────
print("\n" + "="*70)
print("OLD MUTUAL — product pages")
print("="*70)
old_mutual_cases = [
    ("data/raw/insurance/old_mutual/term_cover.html",
     "https://www.oldmutual.co.ke/personal/insure/term-cover", "life"),
    ("data/raw/insurance/old_mutual/afya_imara.html",
     "https://www.oldmutual.co.ke/personal/insure/health-insurance/afyaimara-family-cover/", "health"),
    ("data/raw/insurance/old_mutual/lengo_edu.html",
     "https://www.oldmutual.co.ke/personal/save-and-invest/lengo-education-plan", "education"),
]
for snap, url, cat in old_mutual_cases:
    print(f"\n--- {url.split('/')[-1].rstrip('/')} ---")
    html = Path(snap).read_text(encoding="utf-8", errors="replace")
    p = old_mutual.parse_product_page(html, url, cat)
    _print_product(p, snap)
