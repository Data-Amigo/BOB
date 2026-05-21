from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "Old Mutual"
INSURER_SLUG = "old_mutual"

# =============================================================================
# URL-to-category mapping
# =============================================================================
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("health-insurance",              "health"),
    ("afyaimara",                     "health"),
    ("severe-illness",                "health"),
    ("whole-life",                    "life"),
    ("term-cover",                    "life"),
    ("last-expense",                  "life"),
    ("diaspora-last-expense",         "life"),
    ("Trust-In-Mutual",               "life"),
    ("lady-anchor",                   "life"),
    ("accidental-death",              "life"),
    ("accidental-disability-cover",   "life"),
    ("physical-impairment",           "life"),
    ("home-insurance",                "property"),
    ("golfers-insurance",             "property"),
    ("motor-private",                 "motor"),
    ("student-maxpac-personal-accident", "personal_accident"),
    ("personal-accident",             "personal_accident"),
    ("travel-insurance",              "travel"),
    ("education-plan",                "education"),
    ("personal-pension-plan",         "pension"),
    ("savings-plan",                  "savings"),
    ("hakika",                        "savings"),
    ("digital-savings",               "savings"),
    ("private-wealth",                "investment"),
    ("unit-trust",                    "investment"),
    ("unit-trusts",                   "investment"),
    ("bond-fund",                     "investment"),
]

# Category-level pages that list products but are not products themselves.
_CATEGORY_SUFFIXES = {
    "health-insurance",
    "unit-trusts",
    "unit-trust",
    "investment-solutions",
    "insure",
    "save-and-invest",
    "pension-fund-management",
    "alternative-Investments",
    "private-wealth",
    "investment-portal",
    "projections",
    "get-quote",
    "forms-and-downloads",
    "get-help",
    "about-us",
    "buy-now",
    "get-a-quote",
    "thrive",
    "sustainability",
    "fund-prices",
    "asisa-unclaimed-benefits",
}


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


def _extract_kes_amount(text: str) -> float | None:
    match = re.search(r"(?:KES|Ksh|Kes)\.?\s*([\d,]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


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
# Old Mutual's nav renders all product links on every page. We use the same
# parent-path elimination strategy as Britam: collect all internal links,
# identify category pages (parents of other links), and keep only leaf product URLs.
#
# Section prefix filtering (from listing_url) prevents nav links from unrelated
# sections polluting the results.
def parse_product_listing(html: str, base_url: str, listing_url: str = "") -> list[str]:
    """Extract individual product page URLs from an Old Mutual section page.

    Args:
        html: Rendered HTML from the section overview page.
        base_url: Insurer base URL (https://www.oldmutual.co.ke).
        listing_url: Full URL of the listing page. When provided, only product
            URLs that start with its path are returned.

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
        if "oldmutual.co.ke" not in href:
            continue
        raw.add(href.split("?")[0].split("#")[0].rstrip("/"))

    # Remove known category/utility pages before parent-path computation so they
    # don't cause real product pages to be misclassified as parents.
    raw = {
        href for href in raw
        if urlparse(href).path.rstrip("/").split("/")[-1] not in _CATEGORY_SUFFIXES
    }

    # Parent-path elimination
    parents: set[str] = set()
    raw_list = list(raw)
    for url in raw_list:
        for other in raw_list:
            if url != other and other.startswith(url.rstrip("/") + "/"):
                parents.add(url)
                break

    # Derive section prefix from listing URL
    section_prefix: str | None = None
    if listing_url:
        listing_path = urlparse(listing_url).path.rstrip("/")
        if listing_path:
            section_prefix = listing_path + "/"

    product_roots = ("/personal/insure/", "/personal/save-and-invest/", "/investment/unit-trust/")

    urls: list[str] = []
    seen: set[str] = set()
    for href in sorted(raw):
        path = urlparse(href).path.rstrip("/")

        if section_prefix:
            if not path.startswith(section_prefix.rstrip("/")):
                continue
        else:
            if not any(path.startswith(r.rstrip("/")) for r in product_roots):
                continue

        segments = [s for s in path.split("/") if s]
        if section_prefix:
            listing_depth = len([s for s in urlparse(listing_url).path.split("/") if s])
            if len(segments) <= listing_depth:
                continue
        else:
            if len(segments) < 3:
                continue

        if href in parents:
            continue
        if path.split("/")[-1] in _CATEGORY_SUFFIXES:
            continue

        if href not in seen:
            seen.add(href)
            urls.append(href)

    return urls


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# Old Mutual uses Stencil web components (<om-*>) which Playwright renders
# into standard HTML inside the <main> tag.
#
# Page structure (inside <main>):
#   Hero:       om-page-intro → .page-intro-heading h1  (product name)
#               om-page-intro → .page-intro-text        (description / tagline)
#   Benefits:   om-two-column-image-left → span[slot='text-content'] ul li
#   How to apply: om-two-column-image-right → .page-intro-text or om-section-header
#   Downloads:  Links to .pdf brochures, quotation tools
#   FAQ:        om-faq-cards → om-faq-card elements
#               Each faq-card: button.accordion-button (question) + rest of text (answer)
#
# Product name: Strip "What is " prefix and trailing "?" — used on ~60% of pages.
def parse_product_page(
    html: str,
    product_url: str,
    category: str,
) -> InsuranceProduct | None:
    """Extract a complete InsuranceProduct from one Old Mutual product detail page.

    Args:
        html: Rendered HTML from the product detail page.
        product_url: URL that was fetched — stored in the model for traceability.
        category: Insurance category used as fallback; inferred from URL when possible.

    Returns:
        A populated InsuranceProduct, or None if the page is unrecognisable.
    """
    soup = BeautifulSoup(html, "html.parser")

    # All useful content is inside <main>; the rest of the 1.5MB is nav/framework.
    main = soup.find("main")
    if not main:
        return None

    raw_text = _clean(main.get_text(" ", strip=True))
    if not raw_text or len(raw_text) < 50:
        return None

    product_category = _infer_category(product_url, fallback=category)

    # -------------------------------------------------------------------------
    # Product name — inside om-page-intro → .page-intro-heading h1
    # Many pages phrase the name as "What is Term Cover?" — strip the prefix.
    # -------------------------------------------------------------------------
    h1_el = (
        main.select_one(".page-intro-heading h1")
        or main.find("h1")
    )
    product_name = _clean(h1_el.get_text()) if h1_el else ""
    product_name = re.sub(r"^What\s+is\s+", "", product_name, flags=re.IGNORECASE).rstrip("?").strip()
    product_name = re.sub(r"^(?:Invest\s+in\s+(?:an?\s+)?|(?:an?\s+))", "", product_name, flags=re.IGNORECASE).strip()

    if not product_name:
        title_el = soup.select_one("title")
        if title_el:
            product_name = _clean(title_el.get_text().split("|")[0])
    if not product_name:
        return None

    # -------------------------------------------------------------------------
    # Description — .page-intro-text caption block
    # -------------------------------------------------------------------------
    desc_el = main.select_one(".page-intro-text")
    description = _clean(desc_el.get_text()) if desc_el else raw_text[:600]

    # -------------------------------------------------------------------------
    # Key benefits — span[slot='text-content'] ul li (the benefits/features panel)
    # Scoped to <main> so nav pollution is impossible.
    # -------------------------------------------------------------------------
    benefits: list[str] = []
    seen_b: set[str] = set()
    # Some pages wrap benefits in ul>li; others place li directly inside span.
    for container in main.select("span[slot='text-content']"):
        for li in container.find_all("li"):
            text = _clean(li.get_text())
            if text and len(text) > 5 and text not in seen_b:
                seen_b.add(text)
                benefits.append(text)

    # -------------------------------------------------------------------------
    # FAQs — om-faq-card elements, each containing a button (question) and
    # remaining text (answer). Extracts exclusions and waiting period too.
    # -------------------------------------------------------------------------
    faqs: list[dict[str, str]] = []
    exclusions: list[str] = []
    waiting_period: str | None = None

    for card in main.select("om-faq-card"):
        q_el = card.select_one(".accordion-button")
        if not q_el:
            continue
        q = _clean(q_el.get_text())
        full_card_text = _clean(card.get_text())
        a = full_card_text[len(q):].strip() if full_card_text.startswith(q) else full_card_text
        if q and a:
            faqs.append({"q": q, "a": a})

            # Extract exclusions from the "excluded" FAQ
            if re.search(r"excluded|exclusion", q, re.IGNORECASE):
                # Split on common list separators in the answer text
                exc_items = [_clean(li.get_text()) for li in card.select("ul li") if _clean(li.get_text())]
                if exc_items:
                    exclusions = exc_items
                elif a:
                    exclusions = [a[:300]]

            # Extract waiting period from the "waiting period" FAQ
            if re.search(r"waiting period", q, re.IGNORECASE) and not waiting_period:
                wait_match = re.search(r"(\d+)\s+days?\s+waiting period[^\.\n]{0,80}", a, re.IGNORECASE)
                if wait_match:
                    waiting_period = _clean(wait_match.group(0))

    # Fallback waiting period from raw text
    if not waiting_period:
        wait_match = re.search(r"(\d+)\s+days?\s+waiting period[^\.\n]{0,60}", raw_text, re.IGNORECASE)
        if wait_match:
            waiting_period = _clean(wait_match.group(0))

    # -------------------------------------------------------------------------
    # Target audience — "suitable for" pattern in description or raw text
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
    # Downloadable brochures / documents
    # -------------------------------------------------------------------------
    brochures: list[dict[str, str]] = []
    for a in main.find_all("a", href=True):
        href = str(a["href"])
        if href.endswith(".pdf") or "/om-docs/" in href:
            label = _clean(a.get_text()) or href.split("/")[-1]
            full_url = href if href.startswith("http") else "https://www.oldmutual.co.ke" + href
            brochures.append({"label": label, "url": full_url})

    # -------------------------------------------------------------------------
    # How to apply — from "How do I apply?" om-section-header block
    # -------------------------------------------------------------------------
    how_to_apply: str | None = None
    for header in main.select("om-section-header"):
        header_text = _clean(header.get_text())
        if re.search(r"how do i apply|apply|get started", header_text, re.IGNORECASE):
            # Grab the parent content block
            parent = header.find_parent(["om-2-col-layout-content", "om-two-column-image-right", "om-section"])
            if parent:
                how_to_apply = _clean(parent.get_text())[:400]
            break
    if not how_to_apply and re.search(r"how do i apply", raw_text, re.IGNORECASE):
        m = re.search(r"How do I apply\?(.{20,300}?)(?:TALK TO US|Schedule a Call|$)", raw_text, re.IGNORECASE)
        if m:
            how_to_apply = _clean(m.group(1))

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
            r"(?:from|starting)\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s*(?:/\s*month|per\s*month)",
            raw_text,
            re.IGNORECASE,
        )
        if from_match:
            premium_min = float(from_match.group(1).replace(",", ""))
            premium_frequency = "monthly"

    # -------------------------------------------------------------------------
    # Coverage limits — "from KES X to KES Y" / "minimum cover of KES X"
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
            r"minimum cover of\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s*(million|billion)?",
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

    # "from birth to 65" / "from birth to sixty-five (65)" / "age 0 months to 65 years"
    birth_match = re.search(
        r"from\s+(?:birth|age\s+(?:of\s+)?zero\s*(?:\(\d+\))?\s*months?)\s+to\s+(?:[a-z\-]+\s+)?\(?(\d+)\)?",
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

    if max_age is None:
        until_match = re.search(r"(?:until|turns?|up to age)\s+(\d+)\s*years?", raw_text, re.IGNORECASE)
        if until_match:
            max_age = int(until_match.group(1))

    # Written-out number: "sixty-five (65)"
    if max_age is None:
        written_match = re.search(r"\((\d+)\)\s*years?", raw_text)
        if written_match:
            max_age = int(written_match.group(1))

    # -------------------------------------------------------------------------
    # Contact details
    # -------------------------------------------------------------------------
    contact_phone = _extract_phone(raw_text)
    contact_email = _extract_email(raw_text)

    # -------------------------------------------------------------------------
    # Build extra_data
    # -------------------------------------------------------------------------
    extra_data: dict = {}
    if faqs:
        extra_data["faqs"] = faqs
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
        premium_notes="Quote-based — request a callback or use the online quotation tool.",
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
        how_to_apply=how_to_apply,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extra_data=extra_data,
        raw_text=raw_text,
        confidence=confidence,
    )
