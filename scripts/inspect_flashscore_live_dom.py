"""This is the inspect_flashscore_live_dom.py file.

Author: Data-Amigo
Date: 2026-05-19
Description:
This script opens a Flashscore target page in Playwright, waits for the live
page to render, prints DOM clues from likely score/event containers, and logs
network responses that may carry fixture or score data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


def _clean_text(value: str) -> str:
    """Normalize whitespace inside a text fragment."""

    return re.sub(r"\s+", " ", value).strip()


def main() -> None:
    """Inspect a live Flashscore DOM and network activity."""

    parser = argparse.ArgumentParser(description="Inspect a live Flashscore DOM and network activity.")
    parser.add_argument("--target", default="basketball_today", help="Flashscore target key to inspect.")
    parser.add_argument("--url", help="Optional URL override for the selected Flashscore page.")
    parser.add_argument("--settle-ms", type=int, default=12000, help="Extra time to wait after initial load.")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Maximum page load timeout.")
    parser.add_argument("--response-limit", type=int, default=25, help="Maximum matching response URLs to print.")
    args = parser.parse_args()

    source = get_source_config("flashscore")
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
                    "feed",
                    "event",
                    "events",
                    "fixtures",
                    "score",
                    "scores",
                    "match",
                    "matches",
                    "basketball",
                    "football",
                    "api",
                ]
            )
            if interesting and response_url not in matching_responses:
                matching_responses.append(response_url)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(args.settle_ms)

        title = page.title()
        html = page.content()

        candidate_selectors = [
            ".event__match",
            ".event__row",
            ".event__title",
            ".sportName",
            ".sportName__event",
            ".sportName__league",
            ".duelParticipant",
            "[data-testid*='event']",
            "[data-testid*='match']",
            "[class*='event__']",
        ]

        selector_texts: dict[str, list[str]] = {}

        for selector in candidate_selectors:
            locator = page.locator(selector)
            count = min(locator.count(), 10)
            selector_texts[selector] = []

            for index in range(count):
                try:
                    text = _clean_text(locator.nth(index).inner_text())
                except Exception:
                    text = ""

                if text:
                    selector_texts[selector].append(text)

        json_ld_scripts = page.locator('script[type="application/ld+json"]')
        json_ld_count = min(json_ld_scripts.count(), 10)
        json_ld_samples: list[dict[str, str | None]] = []

        for index in range(json_ld_count):
            try:
                raw_text = json_ld_scripts.nth(index).inner_text()
                payload = json.loads(raw_text)
            except Exception:
                continue

            if isinstance(payload, dict):
                json_ld_samples.append(
                    {
                        "type": str(payload.get("@type") or ""),
                        "name": str(payload.get("name") or "") or None,
                        "url": str(payload.get("url") or "") or None,
                    }
                )
                if len(json_ld_samples) >= 5:
                    break

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

    print("json_ld_samples:")
    for index, sample in enumerate(json_ld_samples, start=1):
        print("---")
        print(f"sample_{index}:")
        print(f"  type: {sample.get('type')}")
        print(f"  name: {sample.get('name')}")
        print(f"  url: {sample.get('url')}")

    print("selector_text_samples:")
    for selector, texts in selector_texts.items():
        print("---")
        print(f"selector: {selector}")
        print(f"texts_found: {len(texts)}")
        for index, text in enumerate(texts[:5], start=1):
            print(f"  text_{index}: {text}")

    print("body_text_sample:")
    print(body_text[:2500])


if __name__ == "__main__":
    main()
