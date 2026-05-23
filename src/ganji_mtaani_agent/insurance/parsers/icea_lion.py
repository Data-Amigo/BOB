from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "ICEA Lion"
INSURER_SLUG = "icea_lion"

# =============================================================================
# URL-to-category mapping
# =============================================================================
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("personal-accident",           "personal_accident"),
    ("group-personal-accident",     "personal_accident"),
    ("medical-second-opinion",      "health"),
    ("motor-insurance",             "motor"),
    ("travel-insurance",            "travel"),
    ("dog-insurance",               "motor"),
    ("golfers-insurance",           "motor"),
    ("domestic-insurance",          "property"),
    ("fire-perils",                 "property"),
    ("all-risks-insurance",         "property"),
    ("electronic-equipment",        "property"),
    ("machinery-breakdown",         "property"),
    ("marine-cargo",                "property"),
    ("loss-of-profits",             "property"),
    ("fidelity-guarantee",          "property"),
    ("public-liability",            "property"),
    ("work-injury-benefits",        "property"),
    ("bizbora",                     "property"),
    ("level-term-assurance",        "life"),
    ("whole-of-life",               "life"),
    ("value-added-term",            "life"),
    ("endowment-assurance",         "life"),
    ("mortgage-protection",         "life"),
    ("group-life-assurance",        "life"),
    ("group-credit",                "life"),
    ("education-insurance",         "education"),
    ("money-market-fund",           "investment"),
    ("balanced-fund",               "investment"),
    ("fixed-income-fund",           "investment"),
    ("equity-plan",                 "investment"),
    ("income-drawdown-fund",        "investment"),
    ("guaranteed-umbrella-fund",    "investment"),
    ("investsure",                  "investment"),
    ("annuity",                     "pension"),
    ("personal-retirement-scheme",  "pension"),
    ("umbrella-trust-retirement",   "pension"),
    ("contracting-out-of-nssf",     "pension"),
    ("pensions-management",         "pension"),
    ("deposit-administration",      "pension"),
    ("milele-trust",                "investment"),
    ("charitable-trust",            "investment"),
    ("education-trust",             "investment"),
    ("family-welfare-trust",        "investment"),
    ("medical-trust",               "investment"),
    ("estate-planning",             "investment"),
    ("private-wealth-management",   "investment"),
]

# Slugs that appear in the homepage nav but are NOT product pages.
# ICEA Lion uses a flat URL scheme — all products live at /<slug>.
# These corporate/blog/utility slugs must be excluded from the listing.
_NON_PRODUCT_SLUGS = {
    "blogs",
    "contact-us",
    "home",
    "events",
    "faq-s",
    "find-a-branch",
    "icea-lion-academy",
    "icea-lion-asset-management",
    "icea-lion-general-insurance",
    "icea-lion-life-assurance",
    "icea-lion-trust",
    "integrated-reports",
    "open-roles",
    "our-achievements",
    "our-agency-force",
    "our-heritage",
    "press-release",
    "privacy-policy",
    "sustainability",
    "webinars",
    "whistle-blowing",
    # Blog articles
    "beyond-savings-introducing-kenya-s-first-retirement-preparedness-index-irpi",
    "ilam-at-40-celebrating-four-decades-of-trust-and-wealth-management-in-kenya",
    "we-walked-we-connected-the-first-icea-lion-walk-of-life",
    "why-african-insurers-should-adopt-esg-for-sustainable-growth",
}

# Maximum slug length for product pages.  Blog/article slugs are typically
# much longer than product slugs (e.g., level-term-assurance = 20 chars).
_MAX_PRODUCT_SLUG_LEN = 45


# =============================================================================
# Small helpers
# =============================================================================
def _clean(text: str) -> str:
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


def _comes_before(a: Tag, b: Tag) -> bool:
    """Return True if tag a precedes tag b in document order."""
    for elem in a.find_all_next():
        if elem is b:
            return True
    return False


# =============================================================================
# Product Listing Parser
# =============================================================================
# ICEA Lion uses a completely flat URL scheme: every product lives at
#   https://www.icealion.co.ke/<product-slug>
# There are no section-level listing pages, so we use the homepage as the
# listing source and apply two filters:
#   1. Single-segment path only (no sub-paths like /motor-insurance/buy).
#   2. Exclude known non-product slugs (corporate, blogs, utilities).
#   3. Exclude slugs longer than _MAX_PRODUCT_SLUG_LEN (blog article titles).
def parse_product_listing(html: str, base_url: str, listing_url: str = "") -> list[str]:
    """Extract individual product page URLs from the ICEA Lion homepage.

    Args:
        html: Rendered HTML of https://www.icealion.co.ke (the homepage).
        base_url: https://www.icealion.co.ke
        listing_url: Unused for ICEA Lion (single-listing strategy).

    Returns:
        Sorted, deduplicated list of absolute product detail URLs.
    """
    soup = BeautifulSoup(html, "html.parser")

    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith("#") or href.startswith("mailto") or href.endswith(".pdf"):
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        if "icealion.co.ke" not in href:
            continue
        href = href.split("?")[0].split("#")[0].rstrip("/")

        parsed = urlparse(href)
        # Must be exactly one path segment: /slug
        path_segments = [s for s in parsed.path.split("/") if s]
        if len(path_segments) != 1:
            continue

        slug = path_segments[0]

        if slug in _NON_PRODUCT_SLUGS:
            continue
        if len(slug) > _MAX_PRODUCT_SLUG_LEN:
            continue

        if href not in seen:
            seen.add(href)
            urls.append(href)

    return sorted(urls)


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# ICEA Lion is a Liferay portal. Page sections are <section class="portlet">.
#
# Product name  : first <h1> on the page
# Description   : <p class="about-card-para ..."> — the introductory paragraph
# Benefits      : bare <p> tags (no class) with text > 50 chars, appearing
#                 before the "Related Products" h2 heading
# FAQs          : no consistent FAQ element found — rely on raw-text extraction
def parse_product_page(
    html: str,
    product_url: str,
    category: str,
) -> InsuranceProduct | None:
    """Extract a complete InsuranceProduct from one ICEA Lion product page.

    Args:
        html: Rendered HTML from the product detail page.
        product_url: URL that was fetched — stored in the model for traceability.
        category: Insurance category used as fallback; inferred from URL when possible.

    Returns:
        A populated InsuranceProduct, or None if the page is unrecognisable.
    """
    soup = BeautifulSoup(html, "html.parser")

    raw_text = _clean(soup.get_text(" ", strip=True))
    if not raw_text or len(raw_text) < 50:
        return None

    product_category = _infer_category(product_url, fallback=category)

    # -------------------------------------------------------------------------
    # Product name — <title> tag (format "Name | ICEA LION Group - Kenya") is
    # the most reliable source. Some pages use the h1 for a marketing tagline
    # (e.g. "Make your plan today, so your wishes live on") while the title
    # always contains the clean product name.
    # -------------------------------------------------------------------------
    product_name = ""
    title_el = soup.find("title")
    if title_el:
        # Title format: "Product Name – Marketing tagline | ICEA LION Group - Kenya"
        # Strip the brand suffix first, then strip the " – tagline" portion.
        raw_title = title_el.get_text()
        product_name = _clean(raw_title.split("|")[0])
        # Strip em-dash / en-dash separated tagline that Sanlam/ICEA append to titles
        product_name = re.split(r"\s*[–—]\s*", product_name)[0].strip()
    if not product_name:
        h1_el = soup.find("h1")
        if h1_el:
            product_name = _clean(h1_el.get_text())
    if not product_name:
        return None

    # -------------------------------------------------------------------------
    # Description — <p class="about-card-para ...">
    # Liferay renders the introductory paragraph with this class alongside other
    # decorative classes (regular, text-primary-background-color).
    # -------------------------------------------------------------------------
    desc_el = soup.select_one("p.about-card-para")
    description = _clean(desc_el.get_text()) if desc_el else ""
    if not description:
        # Fallback: first long paragraph
        for p in soup.find_all("p"):
            t = _clean(p.get_text())
            if len(t) > 80:
                description = t[:600]
                break

    # -------------------------------------------------------------------------
    # Benefits — bare <p> tags (no class attribute) with substantial text,
    # appearing before the "Related Products" h2 heading.
    # -------------------------------------------------------------------------
    related_h2: Tag | None = None
    for h2 in soup.find_all("h2"):
        if "related" in h2.get_text().lower():
            related_h2 = h2
            break

    benefits: list[str] = []
    seen_b: set[str] = set()

    for p in soup.find_all("p"):
        if p.get("class"):
            continue
        text = _clean(p.get_text())
        if len(text) < 50:
            continue
        # Stop collecting once we reach (or pass) the Related Products section
        if related_h2 and not _comes_before(related_h2, p):
            # p is before related_h2 — safe to include
            pass
        elif related_h2:
            # p is after related_h2 — skip
            continue
        if text not in seen_b:
            seen_b.add(text)
            benefits.append(text)

    # -------------------------------------------------------------------------
    # Premium — "minimum (monthly) premium of KES X,XXX" or "from KES X/month"
    # -------------------------------------------------------------------------
    premium_min: float | None = None
    premium_frequency: str | None = None

    monthly_match = re.search(
        r"minimum\s+(?:monthly\s+)?premium\s+of\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)",
        raw_text,
        re.IGNORECASE,
    )
    if monthly_match:
        premium_min = float(monthly_match.group(1).replace(",", ""))
        premium_frequency = "monthly"
    else:
        from_match = re.search(
            r"(?:from|starting at|as low as)\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s*(?:/\s*month|per\s*month)",
            raw_text,
            re.IGNORECASE,
        )
        if from_match:
            premium_min = float(from_match.group(1).replace(",", ""))
            premium_frequency = "monthly"

    # -------------------------------------------------------------------------
    # Coverage limits
    # -------------------------------------------------------------------------
    coverage_min: float | None = None
    coverage_max: float | None = None
    coverage_notes: str | None = None

    cov_range_match = re.search(
        r"(?:from|limits? from)\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s+to\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)",
        raw_text,
        re.IGNORECASE,
    )
    if cov_range_match:
        coverage_min = float(cov_range_match.group(1).replace(",", ""))
        coverage_max = float(cov_range_match.group(2).replace(",", ""))
        coverage_notes = f"Cover from KES {int(coverage_min):,} to KES {int(coverage_max):,}"
    else:
        min_cov_match = re.search(
            r"minimum (?:sum assured|cover|benefit)\s+of\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s*(million|billion)?",
            raw_text,
            re.IGNORECASE,
        )
        if min_cov_match:
            amount = float(min_cov_match.group(1).replace(",", ""))
            suffix = (min_cov_match.group(2) or "").lower()
            if "million" in suffix:
                amount *= 1_000_000
            elif "billion" in suffix:
                amount *= 1_000_000_000
            coverage_min = amount
            coverage_notes = f"Minimum cover KES {int(coverage_min):,}"

    # -------------------------------------------------------------------------
    # Age eligibility
    # -------------------------------------------------------------------------
    min_age: int | None = None
    max_age: int | None = None

    birth_match = re.search(
        r"from\s+(?:birth|age\s+(?:of\s+)?zero)\s+to\s+(?:[a-z\-]+\s+)?\(?(\d+)\)?",
        raw_text,
        re.IGNORECASE,
    )
    if birth_match:
        min_age = 0
        max_age = int(birth_match.group(1))

    if max_age is None:
        age_range = re.search(r"aged?\s+(\d+)\s*(?:to|-|–)\s*(\d+)\s*years?", raw_text, re.IGNORECASE)
        if age_range:
            min_age = int(age_range.group(1))
            max_age = int(age_range.group(2))

    if min_age is None:
        entry_match = re.search(
            r"(?:minimum age of entry|entry age|age of entry)\s*(?:of|is|:)?\s*(\d+)",
            raw_text,
            re.IGNORECASE,
        )
        if entry_match:
            min_age = int(entry_match.group(1))

    if max_age is None:
        max_entry = re.search(
            r"(?:maximum age of entry|max(?:imum)?\s*age)\s*(?:of|is|:)?\s*(\d+)",
            raw_text,
            re.IGNORECASE,
        )
        if max_entry:
            max_age = int(max_entry.group(1))

    # -------------------------------------------------------------------------
    # Target audience
    # -------------------------------------------------------------------------
    target_audience: str | None = None
    suitable_match = re.search(
        r"suitable for\s+([^\.]{10,120})",
        description or raw_text,
        re.IGNORECASE,
    )
    if suitable_match:
        target_audience = _clean(suitable_match.group(1))

    # -------------------------------------------------------------------------
    # Exclusions — "what is NOT covered" / "exclusions" sections
    # -------------------------------------------------------------------------
    exclusions: list[str] = []
    excl_match = re.search(
        r"(?:not covered|exclusions?|does not cover)[:\s]+(.{30,500}?)(?:\n\n|$)",
        raw_text,
        re.IGNORECASE,
    )
    if excl_match:
        excl_text = excl_match.group(1)
        items = [_clean(x) for x in re.split(r"[•\-\n]", excl_text) if len(x.strip()) > 10]
        if items:
            exclusions = items[:8]

    # -------------------------------------------------------------------------
    # Waiting period
    # -------------------------------------------------------------------------
    waiting_period: str | None = None
    wait_match = re.search(r"(\d+)\s+days?\s+waiting period[^\.\n]{0,60}", raw_text, re.IGNORECASE)
    if wait_match:
        waiting_period = _clean(wait_match.group(0))

    # -------------------------------------------------------------------------
    # Brochures / downloadable documents
    # -------------------------------------------------------------------------
    brochures: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if href.endswith(".pdf"):
            label = _clean(a.get_text()) or href.split("/")[-1]
            full_url = href if href.startswith("http") else "https://www.icealion.co.ke" + href
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
        target_audience=target_audience,
        premium_min_kes=premium_min,
        premium_max_kes=None,
        premium_frequency=premium_frequency,
        premium_notes="Contact ICEA Lion for a personalised quote.",
        coverage_min_kes=coverage_min,
        coverage_max_kes=coverage_max,
        coverage_notes=coverage_notes,
        min_age=min_age,
        max_age=max_age,
        eligibility_notes=None,
        key_benefits=benefits,
        exclusions=exclusions,
        waiting_period=waiting_period,
        claims_process=None,
        how_to_apply=None,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extra_data=extra_data,
        raw_text=raw_text,
        confidence=confidence,
    )
