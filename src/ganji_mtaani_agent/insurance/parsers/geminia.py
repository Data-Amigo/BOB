from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "Geminia Insurance"
INSURER_SLUG = "geminia"

# =============================================================================
# Complete product URL list
# =============================================================================
# Geminia's URL structure is inconsistent — most products are under
# /protect-yourself/ or /protect-your-business/, but a few live at the
# root level (sme_insurance, dogandpetinsurance).  We maintain a verified
# list to avoid any nav-parsing edge cases.
_ALL_PRODUCT_URLS: list[str] = [
    # --- Personal protection ---
    "https://www.geminia.co.ke/protect-yourself/golf-insurance/",
    "https://www.geminia.co.ke/protect-yourself/home_pack_insurance/",
    "https://www.geminia.co.ke/protect-yourself/motor_insurance/",
    "https://www.geminia.co.ke/protect-yourself/personal_accident/",
    "https://www.geminia.co.ke/protect-yourself/travel_insurance/",
    "https://www.geminia.co.ke/protect-yourself/burglary-insurance/",
    # --- Business protection ---
    "https://www.geminia.co.ke/protect-your-business/aviation-insurance/",
    "https://www.geminia.co.ke/protect-your-business/bankers_blanket_insurance/",
    "https://www.geminia.co.ke/protect-your-business/bonds/",
    "https://www.geminia.co.ke/protect-your-business/business_combined_insurance/",
    "https://www.geminia.co.ke/protect-your-business/directors-and-officers-liability/",
    "https://www.geminia.co.ke/protect-your-business/contractor_all_risk_insurance/",
    "https://www.geminia.co.ke/protect-your-business/employers-liability-insurance-2/",
    "https://www.geminia.co.ke/protect-your-business/fidelity-insurance/",
    "https://www.geminia.co.ke/protect-your-business/machinery-breakdown-insurance/",
    "https://www.geminia.co.ke/protect-your-business/money_insurance/",
    "https://www.geminia.co.ke/protect-your-business/motor-commercial-insurance/",
    "https://www.geminia.co.ke/protect-your-business/political-violence-terrorism-sabotage-insurance/",
    "https://www.geminia.co.ke/protect-your-business/professional-indemnity/",
    "https://www.geminia.co.ke/protect-your-business/public-liability-insurance-2/",
    "https://www.geminia.co.ke/protect-your-business/wiba/",
    "https://www.geminia.co.ke/sme_insurance/",
    # --- Agribusiness ---
    "https://www.geminia.co.ke/dogandpetinsurance/",
    "https://www.geminia.co.ke/protect-your-business/crop_insurance/",
    "https://www.geminia.co.ke/protect-your-business/farm_protector_insurance/",
    "https://www.geminia.co.ke/protect-your-business/greenhouse-insurance/",
    "https://www.geminia.co.ke/protect-your-business/livestock-insurance/",
    # --- Property protection ---
    "https://www.geminia.co.ke/protect-your-business/marine_cargo/",
    "https://www.geminia.co.ke/protect-your-business/marine_hull/",
    "https://www.geminia.co.ke/protect-your-business/plate-glass-insurance/",
    "https://www.geminia.co.ke/protect-your-business/stock-floater-insurance/",
    "https://www.geminia.co.ke/protect-your-business/drone-insurance/",
]

# =============================================================================
# URL-to-category mapping
# =============================================================================
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("motor",               "motor"),
    ("travel",              "travel"),
    ("personal_accident",   "personal_accident"),
    ("personal-accident",   "personal_accident"),
    ("golf",                "personal_accident"),
    ("wiba",                "personal_accident"),
    ("home_pack",           "property"),
    ("burglary",            "property"),
    ("business_combined",   "property"),
    ("bankers",             "property"),
    ("bonds",               "property"),
    ("fidelity",            "property"),
    ("machinery",           "property"),
    ("money_insurance",     "property"),
    ("money",               "property"),
    ("plate-glass",         "property"),
    ("stock-floater",       "property"),
    ("drone",               "property"),
    ("marine",              "marine"),
    ("aviation",            "aviation"),
    ("directors",           "liability"),
    ("professional-indem",  "liability"),
    ("public-liability",    "liability"),
    ("employers-liability", "liability"),
    ("contractor",          "property"),
    ("political-violence",  "property"),
    ("sme",                 "property"),
    ("crop",                "agriculture"),
    ("farm",                "agriculture"),
    ("greenhouse",          "agriculture"),
    ("livestock",           "agriculture"),
    ("dog",                 "property"),
    ("pet",                 "property"),
]


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
def parse_product_listing(_html: str, _base_url: str, _listing_url: str = "") -> list[str]:
    """Return the hardcoded verified product URL list for Geminia Insurance Kenya.

    Geminia's URLs span three path patterns (/protect-yourself/, /protect-your-
    business/, and root-level) making homepage-based extraction error-prone.
    """
    return list(_ALL_PRODUCT_URLS)


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# Geminia product pages use a tabbed layout (WordPress / Elementor):
#   h2: product name (first h2 in #ajax-content-wrap or main content div)
#   p: description paragraph
#   ul: bullet list of covers (inside the "What is Covered" tab)
#
# The tab panels are rendered in the DOM even before clicking, so BeautifulSoup
# can read them from the static HTML collected by Playwright.
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
    # Product name — first h2 that doesn't look like a section heading,
    # then h1, then <title>
    # -------------------------------------------------------------------------
    product_name = ""
    _heading_noise = re.compile(
        r"^(previous post|next post|related|get started|contact us|request a quote)",
        re.IGNORECASE,
    )
    for h2 in soup.find_all("h2"):
        t = _clean(h2.get_text())
        if t and not _heading_noise.match(t) and len(t) > 3:
            product_name = t
            break
    if not product_name:
        h1 = soup.find("h1")
        if h1:
            product_name = _clean(h1.get_text())
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
        if len(t) > 60 and not re.search(r"geminia\.co\.ke|paybill|mpe?sa", t, re.IGNORECASE):
            descriptions.append(t)
    description = descriptions[0] if descriptions else ""

    # -------------------------------------------------------------------------
    # Benefits — all <ul> lists, pick the one with the most meaningful items
    # -------------------------------------------------------------------------
    best_items: list[str] = []
    for ul in soup.find_all("ul"):
        items = [_clean(li.get_text()) for li in ul.find_all("li") if len(_clean(li.get_text())) > 10]
        if len(items) > len(best_items):
            best_items = items
    benefits = best_items

    # -------------------------------------------------------------------------
    # Premium — look for "Ksh X,XXX" or "KES X,XXX" patterns
    # -------------------------------------------------------------------------
    premium_min: float | None = None
    premium_frequency: str | None = None
    prem_match = re.search(
        r"(?:Ksh|KES)\.?\s*([\d,]+)\s*(?:/\s*(?:month|year)|per\s*(?:month|year))?",
        raw_text,
        re.IGNORECASE,
    )
    if prem_match:
        val_str = prem_match.group(1).replace(",", "")
        try:
            premium_min = float(val_str)
            if "year" in (prem_match.group(0) or "").lower():
                premium_frequency = "annual"
            else:
                premium_frequency = "annual"
        except ValueError:
            pass

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
        premium_min_kes=premium_min,
        premium_max_kes=None,
        premium_frequency=premium_frequency,
        premium_notes="Contact Geminia Insurance for a quote.",
        coverage_min_kes=None,
        coverage_max_kes=None,
        coverage_notes=None,
        min_age=None,
        max_age=None,
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
