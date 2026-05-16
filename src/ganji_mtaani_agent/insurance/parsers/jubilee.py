from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "Jubilee Insurance"
INSURER_SLUG = "jubilee"

# =============================================================================
# Small Conversion Helpers
# =============================================================================
def _clean(text: str) -> str:
    """Collapse whitespace and strip a text fragment."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_kes_amount(text: str) -> float | None:
    """Pull the first KES figure out of a text string.

    Handles formats like 'KES 1,500', 'Ksh 2000', 'KES1500/month'.
    """
    match = re.search(r"(?:KES|Ksh)\.?\s*([\d,]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _extract_age(text: str, keyword: str) -> int | None:
    """Extract an age number that appears near a keyword.

    Example: 'Minimum age: 18 years' with keyword 'minimum age' → 18.
    """
    pattern = rf"{keyword}\s*:?\s*(\d+)"
    match = re.search(pattern, text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_phone(text: str) -> str | None:
    """Extract the first phone number found in a text block."""
    match = re.search(r"(\+?254[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}|\b0\d{9}\b)", text)
    return match.group(0).strip() if match else None


def _extract_email(text: str) -> str | None:
    """Extract the first email address found in a text block."""
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


def _score_confidence(product_name: str, description: str, benefits: list[str]) -> float:
    """Score extraction quality from 0.0 to 1.0.

    Weights: product name (40%), description depth (30%), benefits found (30%).
    A low score signals the page structure may have changed and the selectors
    need to be reviewed.
    """
    score = 0.0
    if product_name:
        score += 0.4
    if description and len(description) > 80:
        score += 0.3
    if benefits:
        score += 0.3
    return round(score, 2)


# =============================================================================
# Product Listing Parser
# =============================================================================
# PURPOSE: This function takes the HTML from a Jubilee products category page
# (e.g. the health insurance listing) and returns URLs of individual product
# detail pages. We then fetch each of those URLs separately and call
# parse_product_page() on each one.
#
# SELECTOR STATUS: Placeholders — update after inspecting the HTML snapshot.
# Run browser.py on the target URL, save the snapshot, open it, and find the
# correct CSS selectors for product card links.
def parse_product_listing(html: str, base_url: str) -> list[str]:
    """Extract individual product URLs from a Jubilee category listing page.

    Args:
        html: Rendered HTML from the category listing page.
        base_url: Insurer base URL used to resolve relative links.

    Returns:
        List of absolute product detail page URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    # TODO: Replace with the real selector after HTML inspection.
    # Look for anchor tags on product card components.
    # Common patterns on insurance sites: <a class="product-card__cta">,
    # <a class="learn-more">, <a href="/products/...">.
    for link in soup.select("a[href*='/product'], a[href*='/cover'], a[href*='/plan']"):
        href = str(link.get("href", "")).strip()
        if not href or href.startswith("#") or href.startswith("mailto"):
            continue
        if not href.startswith("http"):
            href = base_url.rstrip("/") + "/" + href.lstrip("/")
        if href not in urls:
            urls.append(href)

    return urls


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# PURPOSE: This function takes the HTML from one Jubilee product page and
# builds a complete InsuranceProduct record. The extraction attempts structured
# CSS-selector-based extraction first, then falls back to regex over raw text
# for fields like phone numbers, emails, and KES amounts.
#
# SELECTOR STATUS: Placeholders — update after inspecting the HTML snapshot.
# Fields marked TODO need real selectors. Fields using regex over raw_text
# will work on any page without selectors.
def parse_product_page(html: str, product_url: str, category: str) -> InsuranceProduct | None:
    """Extract a complete InsuranceProduct from one Jubilee product detail page.

    Args:
        html: Rendered HTML from the product detail page.
        product_url: The URL that was fetched — stored in the model for traceability.
        category: Insurance category from the source target (e.g. "health").

    Returns:
        A populated InsuranceProduct, or None if the page is unrecognisable.
    """
    soup = BeautifulSoup(html, "html.parser")
    raw_text = _clean(soup.get_text(" ", strip=True))

    if not raw_text or len(raw_text) < 100:
        return None

    # -------------------------------------------------------------------------
    # Product name
    # -------------------------------------------------------------------------
    # TODO: Replace 'h1' with the specific heading selector after HTML inspection.
    # Insurance sites often wrap the product name in a hero section heading.
    name_el = soup.select_one("h1")
    product_name = _clean(name_el.get_text()) if name_el else ""

    if not product_name:
        return None

    # -------------------------------------------------------------------------
    # Description
    # -------------------------------------------------------------------------
    # TODO: Replace with the selector for the product overview paragraph.
    # Look for a <div class="product-overview">, <section class="intro">, etc.
    desc_el = (
        soup.select_one(".product-description")
        or soup.select_one(".product-overview")
        or soup.select_one(".intro-text")
        or soup.select_one("main p")
    )
    description = _clean(desc_el.get_text()) if desc_el else raw_text[:600]

    # -------------------------------------------------------------------------
    # Tagline
    # -------------------------------------------------------------------------
    # TODO: Replace with the selector for the marketing subtitle in the hero.
    tagline_el = soup.select_one(".product-tagline") or soup.select_one(".hero-subtitle")
    tagline = _clean(tagline_el.get_text()) if tagline_el else None

    # -------------------------------------------------------------------------
    # Key benefits
    # -------------------------------------------------------------------------
    # TODO: Replace with the real benefits list selector.
    # Insurance sites usually present benefits as <ul><li> blocks with a
    # heading like "What's covered" or "Benefits".
    benefits: list[str] = []
    for li in soup.select(".benefits-list li, .what-is-covered li, .product-benefits li"):
        text = _clean(li.get_text())
        if text and len(text) > 5:
            benefits.append(text)

    # -------------------------------------------------------------------------
    # Exclusions
    # -------------------------------------------------------------------------
    # TODO: Replace with the real exclusions list selector.
    # Look for sections labelled "What's not covered", "Exclusions", "Limitations".
    exclusions: list[str] = []
    for li in soup.select(".exclusions-list li, .not-covered li, .exclusions li"):
        text = _clean(li.get_text())
        if text and len(text) > 5:
            exclusions.append(text)

    # -------------------------------------------------------------------------
    # Waiting period
    # -------------------------------------------------------------------------
    # TODO: May need a dedicated selector. For now we extract from raw text.
    waiting_period: str | None = None
    waiting_match = re.search(
        r"waiting period\s*[:\-]?\s*([^\.\n]{5,60})",
        raw_text,
        re.IGNORECASE,
    )
    if waiting_match:
        waiting_period = _clean(waiting_match.group(1))

    # -------------------------------------------------------------------------
    # Claims process
    # -------------------------------------------------------------------------
    # TODO: Replace with the real claims section selector.
    claims_el = soup.select_one(".claims-process, .how-to-claim, #claims")
    claims_process = _clean(claims_el.get_text()) if claims_el else None

    # -------------------------------------------------------------------------
    # How to apply
    # -------------------------------------------------------------------------
    # TODO: Replace with the real CTA/apply section selector.
    apply_el = soup.select_one(".how-to-apply, .get-covered, .apply-section")
    how_to_apply = _clean(apply_el.get_text()) if apply_el else None

    # -------------------------------------------------------------------------
    # Pricing — extracted from raw text via regex (works without selectors)
    # -------------------------------------------------------------------------
    premium_min = _extract_kes_amount(raw_text)

    # -------------------------------------------------------------------------
    # Eligibility — extracted from raw text via regex (works without selectors)
    # -------------------------------------------------------------------------
    min_age = _extract_age(raw_text, r"minimum age|min(?:imum)?\s*age|entry age")
    max_age = _extract_age(raw_text, r"maximum age|max(?:imum)?\s*age")

    # -------------------------------------------------------------------------
    # Contact details — regex over raw text (reliable regardless of layout)
    # -------------------------------------------------------------------------
    contact_phone = _extract_phone(raw_text)
    contact_email = _extract_email(raw_text)

    confidence = _score_confidence(product_name, description, benefits)

    return InsuranceProduct(
        insurer_name=INSURER_NAME,
        insurer_slug=INSURER_SLUG,
        product_name=product_name,
        product_type=category,
        product_url=product_url,
        description=description,
        tagline=tagline,
        target_audience=None,       # TODO: extract from eligibility section
        premium_min_kes=premium_min,
        premium_max_kes=None,        # TODO: extract upper bound from pricing table
        premium_frequency=None,      # TODO: detect "monthly" / "annual" from page
        premium_notes=None,          # TODO: extract pricing footnotes
        coverage_min_kes=None,       # TODO: extract sum assured lower bound
        coverage_max_kes=None,       # TODO: extract sum assured upper bound
        coverage_notes=None,         # TODO: extract coverage scope summary
        min_age=min_age,
        max_age=max_age,
        eligibility_notes=None,      # TODO: extract full eligibility paragraph
        key_benefits=benefits,
        exclusions=exclusions,
        waiting_period=waiting_period,
        claims_process=claims_process,
        how_to_apply=how_to_apply,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extra_data={},
        raw_text=raw_text,
        confidence=confidence,
    )
