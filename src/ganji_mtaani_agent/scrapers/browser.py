"""This is the browser.py file.

Author: Data-Amigo
Date: 2026-04-16
Description:
This is the reusable browser scraping layer. It launches Playwright/Chromium,
opens a URL, waits for the page to load, collects rendered HTML, handles
failures, and optionally saves raw page snapshots for debugging.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


# =============================================================================
# Browser Fetch Result Model
# =============================================================================
# BrowserFetchResult is the standard response object for the browser layer.
#
# Why this exists:
# - Returning only HTML is not enough for a production scraper.
# - The UI needs status, timing, warnings, and errors.
# - The Scraper Agent will later need structured evidence when a scrape fails.
# - Tests become easier because every browser run returns the same shape.
@dataclass(slots=True)
class BrowserFetchResult:
    """Structured result returned after trying to load a page.

    Attributes:
        url: The URL that Playwright attempted to open.
        status: Current outcome of the fetch, usually "success" or "failed".
        started_at: UTC timestamp when the browser fetch started.
        finished_at: UTC timestamp when the browser fetch finished.
        duration_ms: Total runtime in milliseconds.
        title: Browser page title after loading.
        html: Rendered HTML collected from the browser.
        html_length: Character length of the rendered HTML.
        snapshot_path: Optional file path where raw HTML was saved.
        screenshot_path: Optional file path where a page screenshot was saved.
        warnings: Non-fatal issues discovered during the fetch.
        error: Fatal error message if the fetch failed.
    """

    url: str
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    title: str = ""
    html: str = ""
    html_length: int = 0
    snapshot_path: str | None = None
    screenshot_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Return True when the fetch completed successfully.

        This makes caller code easier to read. Instead of writing
        `result.status == "success"` everywhere, callers can use `result.ok`.
        """

        return self.status == "success"


# =============================================================================
# Security Challenge Detection Rules
# =============================================================================
# These phrases help us detect when the browser loaded a security verification
# page instead of the real target content.
#
# Important:
# - This does not bypass anything.
# - It only warns us that the HTML may not contain useful source data.
# - Later, the Streamlit UI can show this warning clearly to the user.
#
# We split title phrases from HTML phrases because the page title is much more
# reliable. Some real pages may still contain challenge-related JavaScript text
# in the HTML after verification has passed.
SECURITY_CHALLENGE_TITLE_PHRASES = (
    "just a moment",
    "checking your browser",
    "security verification",
)

SECURITY_CHALLENGE_HTML_PHRASES = (
    "performing security verification",
    "verify you are not a bot",
    "security service to protect against malicious bots",
    "cf-challenge",
    "cf-turnstile",
    "challenge-platform",
)


# =============================================================================
# Main Browser Fetch Function
# =============================================================================
# fetch_page is the reusable browser function for all source scrapers.
#
# Important design choice:
# This function does not parse betting data. It only fetches rendered page
# content. Source-specific parsing will live in parser modules later.
def fetch_page(
    url: str,
    *,
    timeout_ms: int = 60_000,
    wait_until: str = "domcontentloaded",
    settle_ms: int = 3_000,
    headless: bool = True,
    ignore_https_errors: bool = False,
    click_selector_before_capture: str | None = None,
    click_selector_max_times: int = 0,
    click_text_before_capture: str | None = None,
    click_text_max_times: int = 0,
    click_wait_ms: int = 1_500,
    snapshot_path: str | Path | None = None,
    screenshot_path: str | Path | None = None,
) -> BrowserFetchResult:
    """Open a URL with Chromium and return a structured fetch result.

    Args:
        url: Page URL to open.
        timeout_ms: Maximum time to wait for the initial page load.
        wait_until: Playwright load state. For script-heavy pages, start with
            "domcontentloaded". "networkidle" can timeout if ads, trackers, or
            background requests keep running.
        settle_ms: Extra milliseconds to wait after the initial load state.
            This gives JavaScript-heavy pages time to render useful content.
        headless: Whether to run the browser without a visible window.
        click_selector_before_capture: Optional CSS selector to click
            repeatedly before collecting HTML. This is preferred when the page
            has multiple identical text labels and we need the precise control.
        click_selector_max_times: Maximum number of repeated clicks to attempt
            for click_selector_before_capture.
        click_text_before_capture: Optional visible button/link text to click
            repeatedly before collecting HTML. Useful for pages that lazy-load
            more rows behind a simple "More" control.
        click_text_max_times: Maximum number of repeated clicks to attempt for
            click_text_before_capture.
        click_wait_ms: Wait time after each successful click so the page can
            render the newly loaded content before the next click attempt.
        snapshot_path: Optional path for saving the raw rendered HTML.
        screenshot_path: Optional path for saving a screenshot of the page.

    Returns:
        BrowserFetchResult containing HTML, timing, status, and error details.

    Example:
        result = fetch_page("https://polymarket.com/markets")
        if result.ok:
            print(result.title, result.html_length)
    """

    # -------------------------------------------------------------------------
    # Timing Setup
    # -------------------------------------------------------------------------
    # We track both human-readable UTC timestamps and precise runtime duration.
    # This will be useful in the Streamlit status panel and scraper run history.
    started_at = datetime.now(UTC)
    start = perf_counter()
    warnings: list[str] = []

    try:
        # ---------------------------------------------------------------------
        # Browser Lifecycle
        # ---------------------------------------------------------------------
        # sync_playwright starts the Playwright controller.
        # chromium.launch starts a Chromium browser.
        # page.goto opens the target URL and waits for the selected load state.
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(ignore_https_errors=ignore_https_errors)
            page = context.new_page()
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            # Some sites fire continuous network requests. Instead of waiting for
            # complete network silence, we wait briefly after DOM load so scripts
            # have time to render useful content.
            if settle_ms > 0:
                page.wait_for_timeout(settle_ms)

            if click_selector_before_capture and click_selector_max_times > 0:
                _click_selector_repeatedly(
                    page,
                    selector=click_selector_before_capture,
                    max_times=click_selector_max_times,
                    wait_ms=click_wait_ms,
                )

            if click_text_before_capture and click_text_max_times > 0:
                _click_visible_text_repeatedly(
                    page,
                    text=click_text_before_capture,
                    max_times=click_text_max_times,
                    wait_ms=click_wait_ms,
                )

            # After the page settles, collect basic browser evidence.
            title = page.title()
            html = page.content()

            # Screenshot capture is useful when HTML alone is not enough to
            # understand what the browser saw, especially with verification pages.
            saved_screenshot_path = _save_screenshot(screenshot_path, page)
            browser.close()

        # ---------------------------------------------------------------------
        # Result Assembly
        # ---------------------------------------------------------------------
        # If the caller requested a snapshot, save the rendered HTML for later
        # debugging or Scraper Agent review.
        saved_snapshot_path = _save_snapshot(snapshot_path, html)
        finished_at = datetime.now(UTC)
        duration_ms = int((perf_counter() - start) * 1000)

        # Empty HTML is not a fatal exception, but it is suspicious enough to
        # show as a warning in the UI.
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

    # -------------------------------------------------------------------------
    # Error Handling
    # -------------------------------------------------------------------------
    # We return failed BrowserFetchResult objects instead of raising errors.
    # This lets Streamlit show a clean error panel instead of crashing the app.
    except PlaywrightTimeoutError as exc:
        return _failed_result(url, started_at, start, f"Timed out loading page: {exc}")
    except Exception as exc:
        return _failed_result(url, started_at, start, str(exc))


# =============================================================================
# Security Challenge Detection Helper
# =============================================================================
# This helper checks whether the returned page looks like a security verification
# page. The browser may technically succeed, but the content may still be unusable
# for scraping if the site shows an anti-bot challenge instead of real data.
def _detect_security_challenge(title: str, html: str) -> list[str]:
    """Return warnings if the page looks like a bot/security challenge.

    Args:
        title: Browser page title after loading.
        html: Rendered HTML collected from the browser.

    Returns:
        A list of warning messages. Empty list means no challenge was detected.
    """

    normalized_title = title.lower().strip()
    normalized_html = html.lower()

    # Title-based detection is the strongest signal. If the visible browser title
    # says "Just a moment", we almost certainly loaded a verification page.
    if any(phrase in normalized_title for phrase in SECURITY_CHALLENGE_TITLE_PHRASES):
        return [
            "Possible anti-bot/security verification page detected from page title. "
            "The browser loaded HTML, but it may not be the real source content."
        ]

    # HTML-based detection is weaker. We only use phrases that strongly indicate
    # a verification page, and we avoid broad words like "cloudflare" because
    # real pages can include those in scripts after verification passes.
    if any(phrase in normalized_html for phrase in SECURITY_CHALLENGE_HTML_PHRASES):
        return [
            "Possible anti-bot/security verification page detected from page HTML. "
            "Inspect the saved snapshot or screenshot before parsing this page."
        ]

    return []


# =============================================================================
# Snapshot Helper
# =============================================================================
# Snapshots are raw rendered HTML files saved for debugging. They are useful when
# selectors break or when we want to compare current page structure to an older
# successful scrape.
def _save_snapshot(snapshot_path: str | Path | None, html: str) -> str | None:
    """Save raw HTML to disk when a snapshot path is provided.

    Args:
        snapshot_path: File path where HTML should be written, or None.
        html: Rendered HTML collected from the browser.

    Returns:
        The saved file path as a string, or None if snapshots are disabled.
    """

    if snapshot_path is None:
        return None

    path = Path(snapshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)


# =============================================================================
# Screenshot Helper
# =============================================================================
# Screenshots are visual debugging evidence. They help us see whether the browser
# reached the real page, a blank page, a consent modal, or a security challenge.
def _save_screenshot(screenshot_path: str | Path | None, page) -> str | None:
    """Save a full-page screenshot when a screenshot path is provided.

    Args:
        screenshot_path: File path where the screenshot should be written, or None.
        page: Active Playwright page object.

    Returns:
        The saved screenshot path as a string, or None if screenshots are disabled.
    """

    if screenshot_path is None:
        return None

    path = Path(screenshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def _click_visible_text_repeatedly(page, *, text: str, max_times: int, wait_ms: int) -> None:
    """Click a visible element with matching text until it disappears or maxes out."""

    for _ in range(max_times):
        locator = page.get_by_text(text, exact=True)
        if locator.count() == 0:
            break

        target = locator.first
        try:
            if not target.is_visible():
                break
            target.scroll_into_view_if_needed(timeout=5_000)
            target.click(timeout=5_000)
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)
        except Exception:
            break


def _click_selector_repeatedly(page, *, selector: str, max_times: int, wait_ms: int) -> None:
    """Click a CSS-selected element until it disappears or maxes out."""

    for _ in range(max_times):
        locator = page.locator(selector)
        if locator.count() == 0:
            break

        target = locator.first
        try:
            if not target.is_visible():
                break
            target.scroll_into_view_if_needed(timeout=5_000)
            target.click(timeout=5_000)
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)
        except Exception:
            break


# =============================================================================
# Failed Result Helper
# =============================================================================
# This helper keeps every failure response consistent. The UI can rely on the
# same fields whether a page loaded successfully or failed.
def _failed_result(url: str, started_at: datetime, start: float, error: str) -> BrowserFetchResult:
    """Create a BrowserFetchResult for a failed browser run.

    Args:
        url: URL that failed to load.
        started_at: UTC timestamp captured before the browser work began.
        start: perf_counter value captured before the browser work began.
        error: Human-readable error message.

    Returns:
        BrowserFetchResult with status="failed" and error details populated.
    """

    finished_at = datetime.now(UTC)
    duration_ms = int((perf_counter() - start) * 1000)

    return BrowserFetchResult(
        url=url,
        status="failed",
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        error=error,
    )

