from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "GA Insurance"
INSURER_SLUG = "ga_insurance"

# =============================================================================
# Complete product URL list
# =============================================================================
# GA Insurance Kenya uses a multi-level category structure:
#   homepage → /ke/commercial/<category>/ → /ke/insurance/<slug>/
# A single-pass listing parser cannot traverse that hierarchy, so we maintain
# a verified list of all known leaf product URLs here.
_ALL_PRODUCT_URLS: list[str] = [
    # --- Personal ---
    "https://www.gainsuranceltd.com/ke/insurance/motor-car-insurance-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/travel/",
    "https://www.gainsuranceltd.com/ke/insurance/domestic-package-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/personal-accident-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/covid-19-benefit-policy/",
    "https://www.gainsuranceltd.com/ke/insurance/golfers-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/pet-insurance/",
    "https://www.gainsuranceltd.com/ke/ga-drive-flex/",
    # --- Commercial motor ---
    "https://www.gainsuranceltd.com/ke/insurance/motor-commercial-vehicles-insurance-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/motor-trade-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/motorcycle-insurance-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/electric-vehicle-ev/",
    # --- Commercial fire ---
    "https://www.gainsuranceltd.com/ke/insurance/fire-insurance-cover-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/business-interruption-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/industrial-all-risks-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/stock-floater-insurance/",
    # --- Commercial engineering ---
    "https://www.gainsuranceltd.com/ke/insurance/boiler-pressure-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/contractors-all-risks-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/contractors-plant-and-machinery-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/deterioration-of-stock-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/electronic-equipment-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/erections-all-risks-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/machinery-breakdown-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/machinery-breakdown-consequential-loss-insurance/",
    # --- Commercial accident ---
    "https://www.gainsuranceltd.com/ke/insurance/burglary-insurance-policy-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/goods-in-transit-insurance-policy-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/money-insurance-policy/",
    "https://www.gainsuranceltd.com/ke/insurance/wiba-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/wiba-enhanced-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/plate-glass-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/all-risks-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/group-personal-accident-insurance-policy/",
    # --- Commercial liabilities ---
    "https://www.gainsuranceltd.com/ke/insurance/carriers-legal-liability-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/directors-and-officers-liability-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/employers-liability-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/legal-contractual-liability-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/professional-indemnity-insurance-cover-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/public-liability-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/product-liability-insurance/",
    # --- Commercial marine ---
    "https://www.gainsuranceltd.com/ke/insurance/marine-cargo-insurance-policy-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/marine-hull-insurance/",
    # --- Commercial aviation ---
    "https://www.gainsuranceltd.com/ke/insurance/aviation-insurance-policy-in-kenya/",
    # --- Commercial bonds ---
    "https://www.gainsuranceltd.com/ke/insurance/fidelity-guarantee-insurance-cover/",
    "https://www.gainsuranceltd.com/ke/insurance/miscellaneous-bonds-insurance/",
    "https://www.gainsuranceltd.com/ke/insurance/customs-bonds-insurance/",
    # --- Specialty ---
    "https://www.gainsuranceltd.com/ke/insurance/k9/",
    "https://www.gainsuranceltd.com/ke/insurance/bloodstock/",
    "https://www.gainsuranceltd.com/ke/insurance/samaki-bima/",
    # --- Health ---
    "https://www.gainsuranceltd.com/ke/insurance/ga-family-medical-insurance-cover-plan-in-kenya/",
    "https://www.gainsuranceltd.com/ke/insurance/seniors-health-insurance-in-kenya-plan/",
    # SME Economy/Premier and TraumaCare were at WordPress ?post_type&p=NNN permalinks
    # that no longer resolve — removed until stable slug URLs are available.
]

# =============================================================================
# URL-to-category mapping
# =============================================================================
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("motor-car",           "motor"),
    ("motor-commercial",    "motor"),
    ("motor-trade",         "motor"),
    ("motorcycle",          "motor"),
    ("electric-vehicle",    "motor"),
    ("drive-flex",          "motor"),
    ("travel",              "travel"),
    ("domestic-package",    "property"),
    ("personal-accident",   "personal_accident"),
    ("group-personal-acc",  "personal_accident"),
    ("wiba",                "personal_accident"),
    ("golfers",             "personal_accident"),
    ("fire-insurance",      "property"),
    ("industrial-all-risk", "property"),
    ("stock-floater",       "property"),
    ("business-interruption","property"),
    ("burglary",            "property"),
    ("all-risks",           "property"),
    ("goods-in-transit",    "property"),
    ("money-insurance",     "property"),
    ("plate-glass",         "property"),
    ("boiler",              "property"),
    ("contractors",         "property"),
    ("machinery",           "property"),
    ("electronic-equipment","property"),
    ("erections",           "property"),
    ("deterioration",       "property"),
    ("marine",              "marine"),
    ("aviation",            "aviation"),
    ("fidelity",            "property"),
    ("bonds",               "property"),
    ("carriers-legal",      "liability"),
    ("directors-and-officer","liability"),
    ("employers-liability", "liability"),
    ("legal-contractual",   "liability"),
    ("professional-indemni","liability"),
    ("public-liability",    "liability"),
    ("product-liability",   "liability"),
    ("k9",                  "property"),
    ("bloodstock",          "property"),
    ("samaki-bima",         "property"),
    ("pet-insurance",       "property"),
    ("medical",             "health"),
    ("seniors-health",      "health"),
    ("covid",               "health"),
    ("p=973",               "health"),
    ("p=975",               "health"),
    ("p=3617",              "health"),
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
    """Return the hardcoded verified product URL list for GA Insurance Kenya.

    The GA Insurance website uses a multi-level category structure that cannot
    be traversed in a single listing-page fetch.  The URL list is verified
    from the live site and maintained here.
    """
    return list(_ALL_PRODUCT_URLS)


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# GA Insurance uses standard WordPress structure:
#   .entry-title or h1/h2: product name
#   .entry-content p: description
#   .entry-content ul: benefits/cover items
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
    # Product name — .entry-title, then h1, then h2, then <title>
    # -------------------------------------------------------------------------
    product_name = ""
    for sel in (".entry-title", "h1", "h2"):
        el = soup.select_one(sel)
        if el:
            t = _clean(el.get_text())
            if t and len(t) > 3:
                product_name = t
                break
    if not product_name:
        title_el = soup.find("title")
        if title_el:
            product_name = _clean(title_el.get_text().split("|")[0]).strip()
    if not product_name or len(product_name) < 4:
        return None

    # Reject pages that returned a company/site placeholder instead of a product name.
    _bad_names = re.compile(
        r"^(ga insurance|page not found|error 404|not found|home)$",
        re.IGNORECASE,
    )
    if _bad_names.match(product_name.strip()):
        return None

    # -------------------------------------------------------------------------
    # Description — prefer .entry-content p, fallback to any substantial p
    # -------------------------------------------------------------------------
    descriptions: list[str] = []
    content = soup.select_one(".entry-content") or soup.find("main") or soup
    for p in content.find_all("p"):
        t = _clean(p.get_text())
        if len(t) > 60:
            descriptions.append(t)

    description = descriptions[0] if descriptions else ""

    # -------------------------------------------------------------------------
    # Benefits — first meaningful <ul> in content area
    # -------------------------------------------------------------------------
    benefits: list[str] = []
    for ul in content.find_all("ul"):
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

    # -------------------------------------------------------------------------
    # Brochures / downloads
    # -------------------------------------------------------------------------
    brochures: list[dict[str, str]] = []
    for a in content.find_all("a", href=True):
        href = str(a["href"])
        if href.endswith(".pdf"):
            label = _clean(a.get_text()) or href.split("/")[-1]
            full_url = href if href.startswith("http") else "https://www.gainsuranceltd.com" + href
            brochures.append({"label": label, "url": full_url})

    extra_data: dict = {}
    if brochures:
        extra_data["brochures"] = brochures

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
        premium_notes="Contact GA Insurance for a quote.",
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
