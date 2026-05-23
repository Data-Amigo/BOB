from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "Sanlam Kenya"
INSURER_SLUG = "sanlam"

# =============================================================================
# URL-to-category mapping
# =============================================================================
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("motor",                   "motor"),
    ("home-insurance",          "property"),
    ("personal-accident",       "personal_accident"),
    ("travel-insurance",        "travel"),
    ("sme-insurance",           "property"),
    ("fire-and-perils",         "property"),
    ("marine-cargo",            "property"),
    ("marine-hull",             "property"),
    ("burglary",                "property"),
    ("electronic-equipment",    "property"),
    ("machinery-breakdown",     "property"),
    ("goods-in-transit",        "property"),
    ("plate-glass",             "property"),
    ("asset-all-risk",          "property"),
    ("plant-all-risk",          "property"),
    ("contractors-all-risk",    "property"),
    ("erection-all-risk",       "property"),
    ("contractors-plant",       "property"),
    ("boiler",                  "property"),
    ("carriers-liability",      "property"),
    ("business-combined",       "property"),
    ("public-liability",        "property"),
    ("professional-indemnity",  "property"),
    ("directors-officers",      "property"),
    ("bankers-blanket",         "property"),
    ("bonds",                   "property"),
    ("work-injury",             "property"),
    ("group-personal-accident", "personal_accident"),
    ("machine-breakdown",       "property"),
]

# Category/utility slugs that appear in nav but are not product pages.
_NON_PRODUCT_SLUGS = {
    "about-us",
    "board-of-directors",
    "leadership-team",
    "who-we-are",
    "contact",
    "downloads",
    "make-a-claim",
    "customer-center",
    "emergency-assist",
    "request-a-quote",
    "news",
    "self-service",
    "corporate",
    "individual",
}


# =============================================================================
# Small helpers
# =============================================================================
def _clean(text: str) -> str:
    # Strip zero-width and invisible Unicode chars Sanlam injects into h2 text
    text = re.sub("[​‌‍\u200E\u200F﻿­]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _infer_category(url: str, fallback: str) -> str:
    for fragment, category in _URL_CATEGORY_MAP:
        if fragment in url:
            return category
    return fallback


def _extract_phone(text: str) -> str | None:
    match = re.search(r"(\+?254[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}|\b0\d{9}\b)", text)
    return match.group(0).strip() if match else None


def _extract_email(text: str) -> str | None:
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


def _score_confidence(name: str, description: str, benefits: list[str]) -> float:
    score = 0.0
    if name:
        score += 0.4
    if description and len(description) > 60:
        score += 0.3
    if benefits:
        score += 0.3
    return round(score, 2)


# =============================================================================
# Product Listing Parser
# =============================================================================
# Sanlam Kenya provides general insurance only. Products are organised under:
#   /general-insurance/individual/<product-slug>
#   /general-insurance/corporate/<product-slug>
#
# The section overview page (e.g. /general-insurance/individual) renders
# links to all products in its navigation — we use parent-path elimination
# plus section-prefix filtering to keep only leaf product URLs.
def parse_product_listing(html: str, base_url: str, listing_url: str = "") -> list[str]:
    """Extract individual product page URLs from a Sanlam section overview page.

    Args:
        html: Rendered HTML from /general-insurance/individual or /general-insurance/corporate.
        base_url: https://www.sanlam.co.ke
        listing_url: Full URL of the section page used to derive the section prefix.

    Returns:
        Sorted, deduplicated list of absolute product detail URLs.
    """
    soup = BeautifulSoup(html, "html.parser")

    raw: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith("#") or href.startswith("mailto") or href.endswith(".pdf"):
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        if "sanlam.co.ke" not in href:
            continue
        raw.add(href.split("?")[0].split("#")[0].rstrip("/"))

    # Derive section prefix from listing URL (e.g. /general-insurance/individual)
    section_prefix: str | None = None
    if listing_url:
        listing_path = urlparse(listing_url).path.rstrip("/")
        if listing_path:
            section_prefix = listing_path

    urls: list[str] = []
    seen: set[str] = set()

    for href in sorted(raw):
        parsed = urlparse(href)
        path = parsed.path.rstrip("/")
        slug = path.split("/")[-1] if path else ""

        if slug in _NON_PRODUCT_SLUGS:
            continue

        # Sanlam products live at /general-insurance/{individual|corporate}/<slug>
        # which is 3 path segments deep.  The listing URL is /general-insurance
        # (the parent overview page that contains all nav links).
        if "/general-insurance/" not in path:
            continue

        segments = [s for s in path.split("/") if s]
        if len(segments) != 3:
            continue

        # Must be under individual/ or corporate/
        if segments[1] not in ("individual", "corporate"):
            continue

        if href not in seen:
            seen.add(href)
            urls.append(href)

    return urls


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# Sanlam product pages follow a simple structure inside <main>:
#   h2: product name (first h2, e.g. "Personal Accident")
#   h2: "What is [Product Name]?" (description heading — merged text node)
#   p (bare, no class): description paragraph(s)
#   ul (no class): bullet-list of key benefits / cover features
#   h2: "Request a quote"
#   h2: "Buy your ... cover online"
#   h2: "Visit any of our branches"
def parse_product_page(
    html: str,
    product_url: str,
    category: str,
) -> InsuranceProduct | None:
    """Extract a complete InsuranceProduct from one Sanlam product detail page.

    Args:
        html: Rendered HTML from the product detail page.
        product_url: URL that was fetched — stored in the model for traceability.
        category: Insurance category used as fallback; inferred from URL when possible.

    Returns:
        A populated InsuranceProduct, or None if the page is unrecognisable.
    """
    soup = BeautifulSoup(html, "html.parser")

    main = soup.find("main")
    if not main:
        return None

    raw_text = _clean(main.get_text(" ", strip=True))
    if not raw_text or len(raw_text) < 40:
        return None

    product_category = _infer_category(product_url, fallback=category)

    # -------------------------------------------------------------------------
    # Product name — first h2 in <main>
    # Sanlam pages open with a simple h2 like "Personal Accident" before the
    # "What is..." decorative heading.
    # -------------------------------------------------------------------------
    product_name = ""
    for h2 in main.find_all("h2"):
        # Use separator=" " so concatenated text nodes get a space between them
        t = _clean(h2.get_text(" "))
        if t and not re.match(r"^(what\s+is|request\s+a\s+quote|buy\s+your|visit\s+any)", t, re.IGNORECASE):
            product_name = t
            break

    if not product_name:
        title_el = soup.find("title")
        if title_el:
            product_name = _clean(title_el.get_text().split("|")[0])
    if not product_name:
        return None

    # -------------------------------------------------------------------------
    # Description — bare <p> tags in <main>
    # -------------------------------------------------------------------------
    descriptions: list[str] = []
    for p in main.find_all("p"):
        if p.get("class"):
            continue
        t = _clean(p.get_text())
        if len(t) > 40:
            descriptions.append(t)

    description = descriptions[0] if descriptions else ""

    # -------------------------------------------------------------------------
    # Benefits — first <ul> with no class in <main>, or first meaningful list
    # -------------------------------------------------------------------------
    benefits: list[str] = []
    for ul in main.find_all("ul"):
        if ul.get("class"):
            continue
        items = [_clean(li.get_text()) for li in ul.find_all("li") if len(_clean(li.get_text())) > 15]
        if len(items) >= 2:
            benefits = items
            break

    # -------------------------------------------------------------------------
    # Age eligibility
    # -------------------------------------------------------------------------
    min_age: int | None = None
    max_age: int | None = None

    age_match = re.search(r"(\d+)\s*(?:to|-|–)\s*(\d+)\s*years?", raw_text, re.IGNORECASE)
    if age_match:
        min_age = int(age_match.group(1))
        max_age = int(age_match.group(2))

    infancy_match = re.search(
        r"(?:from\s+)?infan(?:cy|ts?)\s+to\s+(\d+)\s*years?",
        raw_text,
        re.IGNORECASE,
    )
    if infancy_match:
        min_age = 0
        max_age = int(infancy_match.group(1))

    # -------------------------------------------------------------------------
    # Premium
    # -------------------------------------------------------------------------
    premium_min: float | None = None
    premium_frequency: str | None = None

    prem_match = re.search(
        r"(?:from|starting)\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s*(?:/\s*month|per\s*month)",
        raw_text,
        re.IGNORECASE,
    )
    if prem_match:
        premium_min = float(prem_match.group(1).replace(",", ""))
        premium_frequency = "monthly"

    # -------------------------------------------------------------------------
    # Brochures
    # -------------------------------------------------------------------------
    brochures: list[dict[str, str]] = []
    for a in main.find_all("a", href=True):
        href = str(a["href"])
        if href.endswith(".pdf"):
            label = _clean(a.get_text()) or href.split("/")[-1]
            full_url = href if href.startswith("http") else "https://www.sanlam.co.ke" + href
            brochures.append({"label": label, "url": full_url})

    contact_phone = _extract_phone(raw_text)
    contact_email = _extract_email(raw_text)

    extra_data: dict = {}
    if brochures:
        extra_data["brochures"] = brochures

    confidence = _score_confidence(product_name, description, benefits)

    return InsuranceProduct(
        insurer_name=INSURER_NAME,
        insurer_slug=INSURER_SLUG,
        product_name=product_name,
        product_type=product_category,
        product_url=product_url,
        description=description,
        tagline=None,
        target_audience=None,
        premium_min_kes=premium_min,
        premium_max_kes=None,
        premium_frequency=premium_frequency,
        premium_notes="Contact Sanlam Kenya for a quote via request-a-quote or a branch visit.",
        coverage_min_kes=None,
        coverage_max_kes=None,
        coverage_notes=None,
        min_age=min_age,
        max_age=max_age,
        eligibility_notes=None,
        key_benefits=benefits,
        exclusions=[],
        waiting_period=None,
        claims_process=None,
        how_to_apply=None,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extra_data=extra_data,
        raw_text=raw_text,
        confidence=confidence,
    )
