"""
settle_slips.py
---------------
CLI entry point to manually settle pending bot slips.

Settlement is also triggered automatically at the end of run_daily_ingestion().
To run manually:
    .venv\Scripts\python.exe scripts\settle_slips.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from ganji_mtaani_agent.settlement import settle_slips

if __name__ == "__main__":
    summary = settle_slips()
    print("\n--- Settlement Summary ---")
    print(f"  Legs settled:   {summary['legs_settled']}")
    print(f"  Legs not found: {summary['legs_unresolved']}")
    print(f"  Slips WON:      {summary['slips_won']}")
    print(f"  Slips LOST:     {summary['slips_lost']}")
    print(f"  Still pending:  {summary['slips_still_pending']}")
