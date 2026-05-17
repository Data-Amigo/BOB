from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.insurance.sources import INSURANCE_SOURCES, get_insurance_source, get_insurance_target


def main() -> None:
    """Fetch a raw HTML snapshot from an insurance source and save it to disk.

    Run from the project root:

        python scripts\\fetch_insurance_snapshot.py --source jubilee --target health --save-snapshot --screenshot

    The snapshot is saved under data/raw/insurance/<source>/<target>/.
    Open the .html file to inspect the page structure before writing selectors.
    """

    parser = argparse.ArgumentParser(description="Fetch and snapshot an insurance source page.")
    parser.add_argument("--source", choices=sorted(INSURANCE_SOURCES), default="jubilee")
    parser.add_argument("--target", help="Target key under the selected source (e.g. 'health', 'life').")
    parser.add_argument("--url", help="Optional URL override — skips the source registry URL.")
    parser.add_argument("--save-snapshot", action="store_true", help="Save rendered HTML to data/raw/insurance/.")
    parser.add_argument("--screenshot", action="store_true", help="Save a PNG screenshot alongside the snapshot.")

    browser_mode = parser.add_mutually_exclusive_group()
    browser_mode.add_argument("--headed",   action="store_true", help="Force a visible browser window.")
    browser_mode.add_argument("--headless", action="store_true", help="Force a hidden browser window.")

    parser.add_argument("--wait-until", choices=["commit", "domcontentloaded", "load", "networkidle"])
    parser.add_argument("--settle-ms",  type=int, help="Extra milliseconds to wait after page load.")
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    args = parser.parse_args()

    source = get_insurance_source(args.source)
    target = get_insurance_target(source, args.target)
    url    = args.url or target.url

    wait_until = args.wait_until or source.default_wait_until
    settle_ms  = args.settle_ms  if args.settle_ms is not None else source.default_settle_ms
    headless   = source.default_headless
    if args.headed:
        headless = False
    elif args.headless:
        headless = True

    snapshot_path   = None
    screenshot_path = None
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    artifact_folder = Path("data") / "raw" / "insurance" / args.source / target.name

    if args.save_snapshot:
        snapshot_path = artifact_folder / f"{timestamp}.html"
    if args.screenshot:
        screenshot_path = artifact_folder / f"{timestamp}.png"

    result = fetch_page(
        url,
        timeout_ms=args.timeout_ms,
        wait_until=wait_until,
        settle_ms=settle_ms,
        headless=headless,
        snapshot_path=snapshot_path,
        screenshot_path=screenshot_path,
    )

    print(f"source:          {source.display_name}")
    print(f"target:          {target.display_name}")
    print(f"category:        {target.category}")
    print(f"url:             {result.url}")
    print(f"status:          {result.status}")
    print(f"title:           {result.title}")
    print(f"html_length:     {result.html_length}")
    print(f"duration_ms:     {result.duration_ms}")
    print(f"snapshot_path:   {result.snapshot_path}")
    print(f"screenshot_path: {result.screenshot_path}")

    if result.warnings:
        print("warnings:")
        for w in result.warnings:
            print(f"  - {w}")

    if result.error:
        print(f"error: {result.error}")


if __name__ == "__main__":
    main()
