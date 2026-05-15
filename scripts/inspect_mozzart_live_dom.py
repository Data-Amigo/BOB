"""This is the inspect_mozzart_live_dom.py file.

Author: Data-Amigo
Date: 2026-05-02
Description:
This script opens a Mozzart target page in Playwright, waits for the page to
render, prints DOM text clues from likely event containers, and logs network
responses that may contain markets, odds, or event data.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


# =============================================================================
# Text Helpers
# =============================================================================
def _clean_text(value: str) -> str:
    """Normalize whitespace inside a text fragment."""

    return re.sub(r"\s+", " ", value).strip()


# =============================================================================
# Main Live Inspection Function
# =============================================================================
def main() -> None:
    """Inspect a Mozzart page after browser rendering."""

    parser = argparse.ArgumentParser(description="Inspect a Mozzart DOM and network activity.")
    parser.add_argument("--target", default="football_today", help="Mozzart target key to inspect.")
    parser.add_argument("--url", help="Optional URL override for the selected Mozzart page.")
    parser.add_argument("--settle-ms", type=int, default=12000, help="Extra time to wait after initial load.")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Maximum page load timeout.")
    parser.add_argument("--response-limit", type=int, default=20, help="Maximum matching response URLs to print.")
    args = parser.parse_args()

    source = get_source_config("mozzart")
    target = get_source_target(source, args.target)
    url = args.url or target.url

    matching_responses: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()

        def on_response(response) -> None:
            response_url = response.url
            lowered = response_url.casefold()
            interesting = any(
                token in lowered
                for token in [
                    "live",
                    "sport",
                    "event",
                    "market",
                    "odd",
                    "football",
                    "basketball",
                    "api",
                    "betting",
                ]
            )
            if interesting and response_url not in matching_responses:
                matching_responses.append(response_url)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(args.settle_ms)

        title = page.title()
        html = page.content()
        body_text = _clean_text(page.locator("body").inner_text())
        browser.close()

    print(f"source: {source.display_name}")
    print(f"target: {target.display_name}")
    print(f"sport: {target.sport}")
    print(f"url: {url}")
    print(f"title: {title}")
    print(f"html_length: {len(html)}")

    print("network_response_urls:")
    for response_url in matching_responses[: args.response_limit]:
        print(f"- {response_url}")

    print("body_text_sample:")
    print(body_text[:3000])


if __name__ == "__main__":
    main()
