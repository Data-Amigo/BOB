"""Smoke-test the new bot data queries."""
import sys
sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8")

from ganji_mtaani_agent.services.telegram_bot import (
    _fetch_upcoming_forebet_candidates,
    _attach_best_odds,
    _generate_slips,
)

print("=== Football candidates (60%+) ===")
football = _fetch_upcoming_forebet_candidates(sport="football", min_probability=60.0)
by_date: dict = {}
for row in football:
    d = str(row.get("event_date"))
    by_date.setdefault(d, []).append(row)
for d, rows in sorted(by_date.items()):
    print(f"  {d}: {len(rows)} games  (top prob: {max(r.get('pred_probability',0) for r in rows):.0f}%)")
    for r in rows[:3]:
        print(f"    {r.get('event_time','?'):5}  {r.get('home_team')} vs {r.get('away_team')}  "
              f"pick={r.get('pred_outcome')} {r.get('pred_probability'):.0f}%  [{r.get('probability_bucket')}]")
print(f"Total: {len(football)}")

print("\n=== Basketball candidates (60%+) ===")
bball = _fetch_upcoming_forebet_candidates(sport="basketball", min_probability=60.0)
print(f"Total: {len(bball)}")
for r in bball[:4]:
    print(f"  {r.get('event_date')} {r.get('event_time','?'):5}  "
          f"{r.get('home_team')} vs {r.get('away_team')}  {r.get('pred_probability'):.0f}%")

print("\n=== Odds on first 3 football games ===")
if football:
    enriched = _attach_best_odds(football[:3], sport="football")
    for r in enriched:
        print(f"  {r.get('home_team')} vs {r.get('away_team')}  "
              f"odds={r.get('selected_odds')}  via={r.get('bookmaker_source')}")

print("\n=== Generate 2x 3-leg football slips ===")
slips = _generate_slips(sport="football", slip_size=3, slip_count=2, min_probability=60.0)
print(f"Got {len(slips)} slips")
for i, slip in enumerate(slips, 1):
    print(f"  Slip {i}:")
    for row in slip:
        print(f"    {row.get('home_team')} vs {row.get('away_team')}  "
              f"{row.get('pred_probability'):.0f}%  odds={row.get('selected_odds')}")

print("\nDone.")
