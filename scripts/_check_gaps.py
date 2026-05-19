import json
from pathlib import Path

SKIP = {
    "tagline", "waiting_period", "claims_process", "how_to_apply",
    "contact_phone", "contact_email", "extra_data", "raw_text",
    "snapshot_path", "screenshot_path",
}

for fname in ["jubilee_health.json", "jubilee_life.json", "jubilee_asset_management.json"]:
    path = Path("data") / fname
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"=== {fname} ===")
    for p in data:
        missing = [k for k, v in p.items() if v in (None, "", [], {}) and k not in SKIP]
        name = p["product_name"][:45].ljust(45)
        conf = p["confidence"]
        benefits = len(p.get("key_benefits") or [])
        print(f"  {name}  conf={conf}  benefits={benefits}  missing={missing}")
    print()
