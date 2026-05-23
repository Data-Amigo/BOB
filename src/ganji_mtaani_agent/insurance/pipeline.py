from __future__ import annotations

import time
from types import ModuleType

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct
from ganji_mtaani_agent.insurance.parsers import britam as _britam
from ganji_mtaani_agent.insurance.parsers import cic as _cic
from ganji_mtaani_agent.insurance.parsers import icea_lion as _icea_lion
from ganji_mtaani_agent.insurance.parsers import jubilee as _jubilee
from ganji_mtaani_agent.insurance.parsers import old_mutual as _old_mutual
from ganji_mtaani_agent.insurance.parsers import sanlam as _sanlam
from ganji_mtaani_agent.insurance.sources import get_insurance_source, get_insurance_target
from ganji_mtaani_agent.scrapers.browser import fetch_page


# =============================================================================
# Parser Registry
# =============================================================================
# Maps source slug → parser module. Each module must expose:
#   parse_product_listing(html, base_url, listing_url) -> list[str]
#   parse_product_page(html, product_url, category)
#       -> InsuranceProduct | list[InsuranceProduct] | None
#
# Parsers that return a list from parse_product_page (e.g. CIC, which puts
# multiple products on one sub-category page) are handled transparently by
# the pipeline.
_PARSERS: dict[str, ModuleType] = {
    "britam":     _britam,
    "cic":        _cic,
    "icea_lion":  _icea_lion,
    "jubilee":    _jubilee,
    "old_mutual": _old_mutual,
    "sanlam":     _sanlam,
}


def get_registered_sources() -> list[str]:
    """Return source slugs that have a working parser registered."""
    return sorted(_PARSERS)


# =============================================================================
# Scrape Pipeline
# =============================================================================
def scrape_source_target(
    source_name: str,
    target_name: str | None = None,
    *,
    delay_s: float = 2.0,
    headless: bool = True,
    verbose: bool = True,
    listing_timeout_ms: int = 90_000,
    listing_retries: int = 2,
) -> list[InsuranceProduct]:
    """Run the full scrape pipeline for one insurance source + target.

    Steps:
        1. Fetch the category listing page (e.g. /ke/health/).
        2. Extract individual product page URLs via the source parser.
        3. For each URL: fetch the detail page, then parse it into a product.
        4. Return all successfully parsed InsuranceProduct objects.

    Args:
        source_name: Source slug registered in _PARSERS. e.g. "jubilee".
        target_name: Target key under the source. e.g. "health", "life".
            Defaults to the source's configured default_target.
        delay_s: Seconds to sleep between consecutive detail-page requests.
            Keeps the scraper polite and avoids rate-limiting.
        headless: Run the browser without a visible window.
        verbose: Print progress to stdout.

    Returns:
        List of InsuranceProduct objects, one per successfully parsed page.

    Raises:
        ValueError: If the source has no registered parser.
        RuntimeError: If the listing page fetch fails entirely.
    """
    if source_name not in _PARSERS:
        raise ValueError(
            f"No parser registered for '{source_name}'. "
            f"Registered: {get_registered_sources()}"
        )

    parser  = _PARSERS[source_name]
    source  = get_insurance_source(source_name)
    target  = get_insurance_target(source, target_name)

    _log(verbose, f"source={source.display_name}  target={target.display_name}")
    _log(verbose, f"fetching listing: {target.url}")

    # -------------------------------------------------------------------------
    # Step 1 - fetch the category listing page (with retries for slow sites)
    # -------------------------------------------------------------------------
    listing = None
    for attempt in range(1, listing_retries + 2):
        timeout = listing_timeout_ms + (attempt - 1) * 30_000
        listing = fetch_page(
            target.url,
            timeout_ms=timeout,
            wait_until=source.default_wait_until,
            settle_ms=source.default_settle_ms,
            headless=headless,
        )
        if listing.ok:
            break
        if attempt <= listing_retries:
            _log(verbose, f"listing fetch failed (attempt {attempt}), retrying in 5s...")
            time.sleep(5)

    if not listing.ok:
        raise RuntimeError(f"Listing page fetch failed: {listing.error}")

    for w in listing.warnings:
        print(f"[warn] {w}")

    # -------------------------------------------------------------------------
    # Step 2 — extract product detail URLs from the listing HTML
    # -------------------------------------------------------------------------
    product_urls = parser.parse_product_listing(listing.html, source.base_url, target.url)
    _log(verbose, f"found {len(product_urls)} product URLs")

    # -------------------------------------------------------------------------
    # Step 3 — fetch and parse each detail page
    # -------------------------------------------------------------------------
    products: list[InsuranceProduct] = []
    total = len(product_urls)

    for i, url in enumerate(product_urls, start=1):
        _log(verbose, f"[{i}/{total}] {url}")

        if i > 1:
            time.sleep(delay_s)

        detail = fetch_page(
            url,
            wait_until=source.default_wait_until,
            settle_ms=source.default_settle_ms,
            headless=headless,
        )

        if not detail.ok:
            print(f"[skip] fetch failed — {detail.error}")
            continue

        for w in detail.warnings:
            print(f"[warn] {w}")

        result = parser.parse_product_page(detail.html, url, target.category)

        if result is None:
            print(f"[skip] parser returned None for {url}")
            continue

        # Support multi-product parsers (e.g. CIC sub-category pages)
        if isinstance(result, list):
            for prod in result:
                if prod:
                    products.append(prod)
                    _log(verbose, f"[ok] {prod.product_name}  confidence={prod.confidence}")
        else:
            products.append(result)
            _log(verbose, f"[ok] {result.product_name}  confidence={result.confidence}")

    _log(verbose, f"done - {len(products)}/{total} products parsed")
    return products


# =============================================================================
# Internal Helpers
# =============================================================================
def _log(verbose: bool, msg: str) -> None:
    if verbose:
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"[pipeline] {safe}")
