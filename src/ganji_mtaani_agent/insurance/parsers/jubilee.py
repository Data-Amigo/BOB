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

    The keyword may contain regex alternation (|), so it is wrapped in a
    non-capturing group to ensure the (\d+) capturing group is always part
    of every alternative and group(1) is never None on a successful match.
    """
    pattern = rf"(?:{keyword})\s*:?\s*(\d+)"
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
# PURPOSE: Takes the HTML from a Jubilee category listing page (e.g. /ke/health/)
# and returns the URLs of individual product detail pages. We fetch each URL
# separately and call parse_product_page() on each one.
#
# SELECTOR STATUS: Confirmed against snapshot 20260517_051757.html.
# Page structure: div.card > div.content.p-4 > h3 (name) + p (teaser) + a.read-more (link).
# Cards sit inside div.row.olddata (the full static set). The JS-rendered
# div#datafetch duplicates the same links when a filter is active — de-duplication
# by building a set is handled by the `if href not in urls` guard.
def parse_product_listing(html: str, base_url: str, listing_url: str = "") -> list[str]:
    """Extract individual product URLs from a Jubilee category listing page.

    Args:
        html: Rendered HTML from the category listing page.
        base_url: Insurer base URL used to resolve relative links.

    Returns:
        List of absolute product detail page URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    # Scoped to .cards-holder to avoid picking up a.read-more links in the
    # footer, navigation, or related-products sections.
    for link in soup.select(".cards-holder a.read-more"):
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
# PURPOSE: Takes the HTML from one Jubilee product page and builds a complete
# InsuranceProduct record.
#
# SELECTOR STATUS: Confirmed against snapshot 20260518_032005.html (J-Care).
# Page structure summary:
#   - Hero:        section.main-banner > div.banner-content > h1 / h5
#   - Description: article > .col-lg-8 > .col-12.mb-3 > <p> tags (rich text)
#   - Benefits:    ◆ bullets in the "Top Benefits:" paragraph (core insurance)
#                  + div.benefit-item p items in the owl-carousel (wellness add-ons)
#   - FAQ:         div.accordion > .accordion-item (Q&A pairs → extra_data)
#   - How to buy:  form#contactform (callback form) — present on all product pages
#   - Pricing:     no public price table; quote-based (budget field in the form)
#   - Exclusions:  not published on the web page; in the policy document only
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
    # Product name — most product pages use h1, but some (Diaspora, J-Junior,
    # Critical Illness) use h2 inside the same .banner-content container.
    # -------------------------------------------------------------------------
    name_el = (
        soup.select_one(".banner-content h1")
        or soup.select_one(".banner-content h2")
        or soup.select_one("h1")
    )
    product_name = _clean(name_el.get_text()) if name_el else ""

    if not product_name:
        return None

    # -------------------------------------------------------------------------
    # Tagline — h5 directly below h1 in the hero
    # -------------------------------------------------------------------------
    tagline_el = soup.select_one(".banner-content h5")
    tagline = _clean(tagline_el.get_text()) if tagline_el else None

    # -------------------------------------------------------------------------
    # Description — primary selector targets health-style pages; falls back to
    # .maisha-container for life pages that use a different layout.
    # -------------------------------------------------------------------------
    desc_container = (
        soup.select_one("article .col-lg-8 .col-12.mb-3")
        or soup.select_one("article .col-lg-8 .maisha-container")
    )
    if desc_container:
        paragraphs = [
            _clean(p.get_text())
            for p in desc_container.select("p")
            if _clean(p.get_text()) and len(_clean(p.get_text())) > 30
        ]
        description = " ".join(paragraphs)
    else:
        description = raw_text[:800]

    # -------------------------------------------------------------------------
    # Target audience — two layouts:
    #   Health pages: "Who's It For?" inline heading
    #   Life pages:   <p><strong>Plan is suitable for:</strong></p> + <ul>
    # -------------------------------------------------------------------------
    target_audience: str | None = None

    who_match = re.search(r"Who'?s?\s+It\s+For\?\s*(.+?)(?:\s{2,}|$)", raw_text, re.IGNORECASE)
    if who_match:
        target_audience = _clean(who_match.group(1))

    if not target_audience:
        suitable_el = soup.find(string=re.compile(r"Plan is suitable for", re.IGNORECASE))
        if suitable_el:
            # The text lives inside <strong> → <p>. Walk up to the nearest block
            # element (<p> or <div>) so find_next_sibling("ul") sees the list.
            block = suitable_el.find_parent(["p", "div", "li"])
            ul_el = block.find_next_sibling("ul") if block else None
            if ul_el:
                items = [_clean(li.get_text()) for li in ul_el.select("li") if _clean(li.get_text())]
                if items:
                    target_audience = " | ".join(items)

    # -------------------------------------------------------------------------
    # Key benefits — three sources, merged and deduplicated:
    #   1. ◆ bullet points (health pages — "Top Benefits:" paragraph)
    #   2. div.benefit-item p (health owl-carousel wellness add-ons)
    #   3. .benefits-carousel .benefit-card (life Maisha-style pages)
    #      Each card has a <p><strong>title</strong></p> + <ul><li> sub-items.
    # -------------------------------------------------------------------------
    benefits: list[str] = []
    seen: set[str] = set()

    for match in re.finditer(r"◆\s*([^\n◆]+)", raw_text):
        text = _clean(match.group(1))
        if text and len(text) > 5 and text not in seen:
            seen.add(text)
            benefits.append(text)

    for p in soup.select("div.benefit-item p"):
        text = _clean(p.get_text())
        if text and len(text) > 5 and text not in seen:
            seen.add(text)
            benefits.append(text)

    for card in soup.select(".benefits-carousel .benefit-card"):
        title_el = card.select_one("p > strong")
        sub_items = [_clean(li.get_text()) for li in card.select("ul > li") if _clean(li.get_text())]
        if title_el:
            title = _clean(title_el.get_text())
            combined = f"{title}: {'; '.join(sub_items)}" if sub_items else title
            if combined not in seen:
                seen.add(combined)
                benefits.append(combined)

    # -------------------------------------------------------------------------
    # Exclusions — not published on the web page; referenced in policy docs only
    # -------------------------------------------------------------------------
    exclusions: list[str] = []

    # -------------------------------------------------------------------------
    # Waiting period — regex over raw text
    # -------------------------------------------------------------------------
    waiting_period: str | None = None
    waiting_match = re.search(
        r"waiting period\s*[:\-]?\s*([^\.\n]{5,60})",
        raw_text,
        re.IGNORECASE,
    )
    if waiting_match:
        waiting_period = _clean(waiting_match.group(1))

    # -------------------------------------------------------------------------
    # Claims process — no dedicated section on product pages
    # -------------------------------------------------------------------------
    claims_el = soup.select_one(".claims-process, .how-to-claim, #claims")
    claims_process = _clean(claims_el.get_text()) if claims_el else None

    # -------------------------------------------------------------------------
    # How to apply — every product page has an embedded callback request form
    # -------------------------------------------------------------------------
    how_to_apply = (
        "Request a callback online via the product page, or visit a Jubilee branch."
        if soup.select_one("form#contactform")
        else None
    )

    # -------------------------------------------------------------------------
    # FAQs — accordion at the bottom of the page; stored in extra_data so an
    # LLM can use the Q&A pairs as supplementary context for this product
    # -------------------------------------------------------------------------
    faqs: list[dict[str, str]] = []
    for item in soup.select(".accordion-item"):
        q_el = item.select_one(".accordion-button")
        a_el = item.select_one(".accordion-body")
        if q_el and a_el:
            faqs.append({
                "q": _clean(q_el.get_text()),
                "a": _clean(a_el.get_text()),
            })

    # -------------------------------------------------------------------------
    # Pricing — look for "start/from KES X/month" first (life pages publish
    # a minimum premium in their benefit cards); fall back to the first KES
    # figure in the raw text for any other mention.
    # -------------------------------------------------------------------------
    premium_min: float | None = None
    premium_frequency: str | None = None

    monthly_match = re.search(
        r"(?:start|from|as low as)\s+(?:KES|Ksh)\.?\s*([\d,]+)\s*(?:/\s*month|per\s*month)",
        raw_text,
        re.IGNORECASE,
    )
    if monthly_match:
        premium_min = float(monthly_match.group(1).replace(",", ""))
        premium_frequency = "monthly"
    else:
        premium_min = _extract_kes_amount(raw_text)

    # -------------------------------------------------------------------------
    # Eligibility — two patterns:
    #   "minimum age: 18" / "entry age: 18"      (health/life structured tables)
    #   "aged 18 – 65 years"                      (life narrative text)
    # -------------------------------------------------------------------------
    min_age = _extract_age(raw_text, r"minimum age|min(?:imum)?\s*age|entry age")
    max_age = _extract_age(raw_text, r"maximum age|max(?:imum)?\s*age")

    if min_age is None or max_age is None:
        aged_match = re.search(r"aged\s+(\d+)\s*[-–]\s*(\d+)", raw_text, re.IGNORECASE)
        if aged_match:
            min_age = min_age or int(aged_match.group(1))
            max_age = max_age or int(aged_match.group(2))

    # -------------------------------------------------------------------------
    # Contact details — regex over raw text
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
        target_audience=target_audience,
        premium_min_kes=premium_min,
        premium_max_kes=None,
        premium_frequency=premium_frequency,
        premium_notes="Quote-based — no public price table. Request a callback for pricing.",
        coverage_min_kes=None,
        coverage_max_kes=None,
        coverage_notes=None,
        min_age=min_age,
        max_age=max_age,
        eligibility_notes=None,
        key_benefits=benefits,
        exclusions=exclusions,
        waiting_period=waiting_period,
        claims_process=claims_process,
        how_to_apply=how_to_apply,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extra_data={"faqs": faqs} if faqs else {},
        raw_text=raw_text,
        confidence=confidence,
    )
