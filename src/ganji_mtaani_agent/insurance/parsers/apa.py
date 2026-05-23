from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "APA Insurance"
INSURER_SLUG = "apa"

# =============================================================================
# Complete product URL list
# =============================================================================
# APA Insurance Kenya's website is protected by AWS WAF which blocks headless
# browsers.  The pipeline must run with headless=False (visible browser) so
# Playwright's real Chromium fingerprint bypasses the WAF challenge.
# This URL list was extracted from the /products page (2026-05-23).
_ALL_PRODUCT_URLS: list[str] = [
    # --- Personal ---
    "https://www.apainsurance.org/product_detail_motor",
    "https://www.apainsurance.org/product_detail_motor_commercial",
    "https://www.apainsurance.org/product_detail_travel",
    "https://www.apainsurance.org/product_detail_domestic",
    "https://www.apainsurance.org/product_detail_personal_accident",
    "https://www.apainsurance.org/product_detail_golfers",
    "https://www.apainsurance.org/product_detail_pet",
    "https://www.apainsurance.org/product_detail_crop",
    "https://www.apainsurance.org/product_detail_livestock",
    "https://www.apainsurance.org/product_detail_bima_bamba",
    "https://www.apainsurance.org/product_detail_flexpax",
    # --- Health ---
    "https://www.apainsurance.org/product_detail_afyanafuu",
    "https://www.apainsurance.org/product_detail_hollard",
    "https://www.apainsurance.org/product_detail_jamii",
    "https://www.apainsurance.org/product_detail_femina",
    "https://www.apainsurance.org/product_detail_femina_plus",
    # --- Life ---
    "https://www.apainsurance.org/product_detail_life_Imarika",
    "https://www.apainsurance.org/product_detail_life_akiba_halisi",
    "https://www.apainsurance.org/product_detail_life_elimu",
    "https://www.apainsurance.org/product_detail_life_hosicare",
    "https://www.apainsurance.org/product_detail_life_pumzisha",
    "https://www.apainsurance.org/product_detail_life_term_assuarance",
    "https://www.apainsurance.org/product_detail_life_individual_pension_plan",
    "https://www.apainsurance.org/product_detail_life_morgage_protection",
    # --- Investment ---
    "https://www.apainsurance.org/product_investment_wb",
    "https://www.apainsurance.org/product_investment_ammf",
    "https://www.apainsurance.org/product_investment_abf",
    # --- Commercial ---
    "https://www.apainsurance.org/product_commercial_fire",
    "https://www.apainsurance.org/product_commercial_engineer",
    "https://www.apainsurance.org/product_commercial_marine",
    "https://www.apainsurance.org/product_commercial_aviation",
    "https://www.apainsurance.org/product_commercial_liability",
    "https://www.apainsurance.org/product_commercial_bonds",
    "https://www.apainsurance.org/product_commercial_wiba",
    "https://www.apainsurance.org/product_commercial_theft",
    "https://www.apainsurance.org/product_commercial_goods_in_transit",
    "https://www.apainsurance.org/product_commercial_credit",
    "https://www.apainsurance.org/product_commercial_health",
    "https://www.apainsurance.org/product_commercial_life",
    "https://www.apainsurance.org/product_commercial_micro",
    "https://www.apainsurance.org/product_commercial_group_deposit",
    "https://www.apainsurance.org/product_commercial_special_package",
    "https://www.apainsurance.org/product_commercial_apa_cyber_insurance",
]

# =============================================================================
# URL-to-category mapping
# =============================================================================
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("motor",       "motor"),
    ("travel",      "travel"),
    ("health",      "health"),
    ("medical",     "health"),
    ("afya",        "health"),
    ("hollard",     "health"),
    ("micro",       "micro"),
    ("agri",        "agriculture"),
    ("livestock",   "agriculture"),
    ("crop",        "agriculture"),
    ("fire",        "property"),
    ("property",    "property"),
    ("accident",    "personal_accident"),
    ("life",        "life"),
]


# =============================================================================
# Small helpers
# =============================================================================
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _infer_category(url: str, fallback: str) -> str:
    lower = url.lower()
    for fragment, cat in _URL_CATEGORY_MAP:
        if fragment in lower:
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
# APA Insurance products live at:
#   /product_detail_<slug>   — individual product pages
#   /product_commercial_<slug> — commercial product pages
#
# The /products listing page links to all of them.  APA's server returns 405
# to non-browser requests but Playwright (a real browser) loads it correctly.
def parse_product_listing(_html: str, _base_url: str, _listing_url: str = "") -> list[str]:
    return list(_ALL_PRODUCT_URLS)


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# APA product pages follow a consistent structure:
#   h1 or prominent heading: product name
#   p: description paragraph(s)
#   ul: key benefits/cover list
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
    # Product name — h1, then h2, then <title>
    # -------------------------------------------------------------------------
    product_name = ""
    for tag in ("h1", "h2"):
        el = soup.find(tag)
        if el:
            t = _clean(el.get_text())
            if t and len(t) > 3:
                product_name = t
                break
    if not product_name:
        title_el = soup.find("title")
        if title_el:
            product_name = _clean(title_el.get_text().split("|")[0].split("-")[0]).strip()
    if not product_name or len(product_name) < 4:
        return None

    # -------------------------------------------------------------------------
    # Description — first substantial <p>
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
        premium_notes="Contact APA Insurance for a quote.",
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
