"""Flashscore browser interaction helpers."""

from __future__ import annotations

from ganji_mtaani_agent.scrapers.browser import (
    BrowserFetchResult,
    _detect_security_challenge,
    _failed_result,
    _save_screenshot,
    _save_snapshot,
)
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


FLASHSCORE_FINISHED_SELECTOR = ".filters__tab[data-analytics-alias='finished']"
FLASHSCORE_PREVIOUS_DAY_SELECTOR = "button[aria-label='Previous day']"


def _click_flashscore_control(page, selector: str) -> None:
    """Click a Flashscore control with a few safe fallbacks."""

    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=15_000)
    locator.scroll_into_view_if_needed(timeout=5_000)

    try:
        locator.click(timeout=10_000)
        return
    except Exception:
        try:
            locator.click(timeout=10_000, force=True)
            return
        except Exception:
            page.evaluate(
                """
                (cssSelector) => {
                    const node = document.querySelector(cssSelector);
                    if (node) {
                        node.click();
                    }
                }
                """,
                selector,
            )


def fetch_flashscore_scoreboard(
    url: str,
    *,
    days_back: int = 0,
    finished_only: bool = False,
    timeout_ms: int = 60_000,
    settle_ms: int = 12_000,
    headless: bool = True,
    snapshot_path: str | Path | None = None,
    screenshot_path: str | Path | None = None,
) -> BrowserFetchResult:
    """Fetch a Flashscore page after applying date and results filters."""

    started_at = datetime.now(UTC)
    start = perf_counter()
    warnings: list[str] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            if settle_ms > 0:
                page.wait_for_timeout(settle_ms)

            for _ in range(max(days_back, 0)):
                _click_flashscore_control(page, FLASHSCORE_PREVIOUS_DAY_SELECTOR)
                page.wait_for_timeout(2_000)

            if finished_only:
                _click_flashscore_control(page, FLASHSCORE_FINISHED_SELECTOR)
                page.wait_for_timeout(2_000)

            title = page.title()
            html = page.content()
            saved_screenshot_path = _save_screenshot(screenshot_path, page)
            browser.close()

        saved_snapshot_path = _save_snapshot(snapshot_path, html)
        finished_at = datetime.now(UTC)
        duration_ms = int((perf_counter() - start) * 1000)

        if not html.strip():
            warnings.append("Page returned empty HTML.")

        warnings.extend(_detect_security_challenge(title=title, html=html))

        return BrowserFetchResult(
            url=url,
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            title=title,
            html=html,
            html_length=len(html),
            snapshot_path=saved_snapshot_path,
            screenshot_path=saved_screenshot_path,
            warnings=warnings,
        )
    except PlaywrightTimeoutError as exc:
        return _failed_result(url, started_at, start, f"Timed out loading page: {exc}")
    except Exception as exc:
        return _failed_result(url, started_at, start, str(exc))
