from __future__ import annotations

import re
from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "AAR Insurance"
INSURER_SLUG = "aar"

# =============================================================================
# Complete product URL list
# =============================================================================
# AAR Insurance Kenya offers health, personal, business, and travel products.
# All product pages use a flat slug at aar-insurance.com/<slug>/.
# ShwAARi Medical Cover uses an unstable WP ?page_id= permalink and is omitted
# until a stable slug is available.
_ALL_PRODUCT_URLS: list[str] = [
    # --- Personal & family ---
    "https://aar-insurance.com/family-and-individual-plan/",
    "https://aar-insurance.com/seniors-caare-medical-cover/",
    "https://aar-insurance.com/personal-accident-cover/",
    "https://aar-insurance.com/aar-insurance-protect/",
    "https://aar-insurance.com/homeowners-insurance/",
    # --- Business ---
    "https://aar-insurance.com/business-enterprise-medical-plan/",
    "https://aar-insurance.com/school-insurance-cover/",
    "https://aar-insurance.com/landlord-insurance/",
    "https://aar-insurance.com/work-injury-benefit-act-wiba/",
    "https://aar-insurance.com/professional-indemnity-cover/",
    # --- Travel ---
    "https://aar-insurance.com/marine-insurance/",
    "https://aar-insurance.com/travel-insurance/",
]

# URL-to-category mapping
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("family",          "health"),
    ("seniors",         "health"),
    ("medical",         "health"),
    ("accident",        "personal_accident"),
    ("protect",         "life"),
    ("homeowners",      "property"),
    ("landlord",        "property"),
    ("business-enter",  "health"),
    ("school",          "health"),
    ("wiba",            "personal_accident"),
    ("professional-ind","liability"),
    ("marine",          "marine"),
    ("travel",          "travel"),
]

# Slugs that appear in navigation but are not product pages.
_NON_PRODUCT_SLUGS = {
    "about-us",
    "contact",
    "contacts",
    "find-a-hospital",
    "help",
    "home",
    "make-a-claim",
    "news",
    "our-team",
    "privacy-policy",
    "providers",
    "self-help",
    "submit-a-claim",
}


# =============================================================================
# Small helpers
# =============================================================================
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _infer_category(url: str, fallback: str) -> str:
    for fragment, cat in _URL_CATEGORY_MAP:
        if fragment in url:
            return cat
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
# AAR Insurance Kenya uses a flat slug URL scheme.  We maintain a hardcoded
# verified product URL list — the homepage listing approach is unreliable due
# to navigation links mixing product and utility pages.
def parse_product_listing(_html: str, _base_url: str, _listing_url: str = "") -> list[str]:
    return list(_ALL_PRODUCT_URLS)


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# AAR product pages use a standard WordPress/custom CMS layout:
#   h1 or h2: product name
#   p: description paragraph(s)
#   ul: benefits/cover list
def parse_product_page(
    html: str,
    product_url: str,
    category: str,
) -> InsuranceProduct | None:
    soup = BeautifulSoup(html, "html.parser")

    raw_text = _clean(soup.get_text(" ", strip=True))
    if not raw_text or len(raw_text) < 40:
        return None

    product_category = _infer_category(product_url, fallback=category)

    # -------------------------------------------------------------------------
    # Product name — prefer h1, fallback to <title>
    # -------------------------------------------------------------------------
    product_name = ""
    h1 = soup.find("h1")
    if h1:
        product_name = _clean(h1.get_text())
    if not product_name:
        title_el = soup.find("title")
        if title_el:
            product_name = _clean(title_el.get_text().split("|")[0].split("–")[0].split("-")[0]).strip()
    if not product_name or len(product_name) < 4:
        return None

    # -------------------------------------------------------------------------
    # Description — first substantial <p> after the heading
    # -------------------------------------------------------------------------
    descriptions: list[str] = []
    for p in soup.find_all("p"):
        t = _clean(p.get_text())
        if len(t) > 60:
            descriptions.append(t)

    description = descriptions[0] if descriptions else ""

    # -------------------------------------------------------------------------
    # Benefits — first meaningful <ul>
    # -------------------------------------------------------------------------
    benefits: list[str] = []
    for ul in soup.find_all("ul"):
        items = [_clean(li.get_text()) for li in ul.find_all("li") if len(_clean(li.get_text())) > 10]
        if len(items) >= 2:
            benefits = items
            break

    # -------------------------------------------------------------------------
    # Age range
    # -------------------------------------------------------------------------
    min_age: int | None = None
    max_age: int | None = None
    age_match = re.search(r"(\d+)\s*(?:to|-|–)\s*(\d+)\s*years?", raw_text, re.IGNORECASE)
    if age_match:
        min_age = int(age_match.group(1))
        max_age = int(age_match.group(2))

    contact_phone = _extract_phone(raw_text)
    contact_email = _extract_email(raw_text)

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
        premium_min_kes=None,
        premium_max_kes=None,
        premium_frequency=None,
        premium_notes="Contact AAR Insurance for a quote.",
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
        extra_data={},
        raw_text=raw_text,
        confidence=confidence,
    )
