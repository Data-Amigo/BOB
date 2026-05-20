from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "Britam"
INSURER_SLUG = "britam"

# =============================================================================
# URL-to-category mapping
# =============================================================================
# Britam uses a single overview listing page per section, so all product types
# are scraped together. Category is inferred from the product URL path.
_URL_CATEGORY_MAP: list[tuple[str, str]] = [
    ("health-insurance-covers", "health"),
    ("malkia",                  "health"),
    ("hospicash",               "health"),
    ("afya-tele",               "health"),
    ("bima-ya-mwananchi",       "health"),
    ("kinga-ya-mkulima",        "health"),
    ("family-protection-plans", "life"),
    ("funeral-covers",          "life"),
    ("whole-life",              "life"),
    ("tegemeo",                 "life"),
    ("fariji",                  "life"),
    ("travel-insurance",        "travel"),
    ("personal-accident",       "personal_accident"),
    ("motor-insurance",         "motor"),
    ("motiflex",                "motor"),
    ("electric-motor",          "motor"),
    ("home-insurance",          "property"),
    ("fire-and-burglary",       "property"),
    ("combined-solutions",      "property"),
    ("education-plans",         "education"),
    ("insurance-savings-plans", "savings"),
    ("investment-linked",       "investment"),
    ("unit-trust-funds",        "investment"),
    ("pension",                 "pension"),
]

# Sub-category pages that are NOT individual products — excluded from scraping.
# These are category-level pages that list products but don't describe one product.
_CATEGORY_SUFFIXES = {
    "health-insurance-covers",
    "family-protection-plans",
    "funeral-covers",
    "personal-accident-covers",
    "protect-who-you-love",
    "protect-what-you-love",
    "education-plans",
    "insurance-savings-plans",
    "investment-linked",
    "unit-trust-funds",
    "plan-for-retirement",
    "enjoy-your-retirement",
    "individual-pension-plans",
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
    match = re.search(r"(?:KES|Ksh)\.?\s*([\d,]+)", text, re.IGNORECASE)
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
# Britam's sub-category listing pages (e.g. /health-insurance-covers) return
# ERR_CONNECTION_TIMED_OUT. The parent overview pages (e.g. protect-who-you-love)
# load fine and contain ALL product links in the navigation mega-menu.
#
# Strategy:
#   1. Collect all internal ke.britam.com links from the page.
#   2. Build a set of "parent paths" — any URL that is a path-prefix of another
#      URL on the same page (i.e. it is a category, not a leaf product).
#   3. Keep only leaf URLs with enough path depth (>= 5 segments) that are
#      under a product section (/home/, /save-and-invest/, /pension/).
def parse_product_listing(html: str, base_url: str, listing_url: str = "") -> list[str]:
    """Extract individual product page URLs from a Britam overview page.

    Args:
        html: Rendered HTML of the section overview page (e.g. protect-who-you-love).
        base_url: Insurer base URL (https://ke.britam.com).
        listing_url: Full URL of the listing page being parsed. When provided,
            only product URLs that start with its path are returned. This prevents
            the nav-menu links to unrelated sections from polluting the results.

    Returns:
        Sorted, deduplicated list of absolute product detail URLs.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Collect every internal Britam link
    raw: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith("#") or href.startswith("mailto"):
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        if "ke.britam.com" not in href:
            continue
        raw.add(href.split("?")[0].split("#")[0])  # strip query / fragment

    # Build set of parent paths (URL is a parent if another URL starts with it + "/")
    parents: set[str] = set()
    raw_list = list(raw)
    for url in raw_list:
        for other in raw_list:
            if url != other and other.startswith(url.rstrip("/") + "/"):
                parents.add(url)
                break

    # Derive section prefix filter from the listing URL (e.g. /home/personal/protect-who-you-love)
    # so that nav links to unrelated sections are excluded.
    section_prefix: str | None = None
    if listing_url:
        listing_path = urlparse(listing_url).path.rstrip("/")
        if listing_path:
            section_prefix = listing_path + "/"

    # All valid product section roots (fallback when no section_prefix)
    product_roots = ("/home/personal/", "/home/business/", "/save-and-invest/", "/pension/")

    urls: list[str] = []
    seen: set[str] = set()
    for href in sorted(raw):
        path = urlparse(href).path

        # Must be under the same section as the listing page (or any product root)
        if section_prefix:
            if not path.startswith(section_prefix):
                continue
        else:
            if not any(path.startswith(r) for r in product_roots):
                continue

        segments = [s for s in path.split("/") if s]
        # Needs to be deeper than the listing page itself
        if section_prefix:
            listing_depth = len([s for s in urlparse(listing_url).path.split("/") if s])
            if len(segments) <= listing_depth:
                continue
        else:
            if len(segments) < 5:
                continue

        # Must not be a parent of other product URLs (i.e. must be a leaf)
        if href in parents:
            continue
        # Exclude known category-level suffixes even if they appear as leaves
        if path.rstrip("/").split("/")[-1] in _CATEGORY_SUFFIXES:
            continue

        if href not in seen:
            seen.add(href)
            urls.append(href)

    return urls


# =============================================================================
# Product Detail Page Parser
# =============================================================================
# Confirmed against snapshot: data/raw/insurance/britam/health/20260519_173213.html
# (Milele Health – Quality Healthcare for Every Stage of Life)
#
# Page structure summary:
#   - Hero:       .content-banner-holder h1  (product name, repeated in carousel)
#   - Heading:    section.full-year .heading h2  (tagline / subtitle)
#   - Description:section.full-year .heading p   (intro paragraphs)
#   - Benefits:   section.full-year .heading ul li  (key benefit bullet list)
#   - Coverage:   table rows with td.milele-plans-features-col +
#                 td.milele-plans-plan-col (plan comparison table, Britam-specific)
#   - FAQ:        .accordion-item with Bootstrap data-bs-toggle="collapse"
#   - Contact:    a[href*="whatsapp"] → phone number embedded in href
#   - Apply:      button#productscallback or .milele-plans-get-started modal
def parse_product_page(
    html: str,
    product_url: str,
    category: str,
) -> InsuranceProduct | None:
    """Extract a complete InsuranceProduct from one Britam product detail page.

    Args:
        html: Rendered HTML from the product detail page.
        product_url: URL that was fetched — stored in the model for traceability.
        category: Insurance category from the source target (used as fallback;
            the real category is inferred from the product URL when possible).

    Returns:
        A populated InsuranceProduct, or None if the page is unrecognisable.
    """
    soup = BeautifulSoup(html, "html.parser")
    raw_text = _clean(soup.get_text(" ", strip=True))

    if not raw_text or len(raw_text) < 100:
        return None

    # Infer the real product category from the URL
    product_category = _infer_category(product_url, fallback=category)

    # -------------------------------------------------------------------------
    # Product name — two layouts exist on Britam product pages:
    #
    # Layout A (Milele Health): banner carousel h1 IS the specific product name
    #   e.g. <h1>Milele Health</h1> in .content-banner-holder
    #
    # Layout B (CarePlus, Student Accident, etc.): the banner h1 is the generic
    #   CATEGORY name ("Pure Protection Plans", "Personal Accident Covers").
    #   The specific product name lives in:
    #   section.full-year .content-section .heading h2
    #
    # Strategy: prefer the content-section h2 (always specific); fall back to
    # the banner h1 only when no content-section h2 is found.
    # -------------------------------------------------------------------------
    content_h2_el = soup.select_one("section.full-year .content-section .heading h2")
    banner_h1_el = (
        soup.select_one(".content-banner-holder h1")
        or soup.select_one(".banner-background h1")
        or soup.select_one("h1")
    )

    content_h2_text = _clean(content_h2_el.get_text()) if content_h2_el else ""
    banner_h1_text  = _clean(banner_h1_el.get_text()) if banner_h1_el else ""

    # If the content-section h2 contains " – " or " | " it is a tagline compound
    # ("Milele Health – Quality Healthcare for Every Stage of Life"), not the name.
    # In that case split on the separator: left part = name, full h2 = tagline.
    # Otherwise the content-section h2 IS the specific product name (Layout B).
    if content_h2_text and (" – " in content_h2_text or " | " in content_h2_text):
        sep = " – " if " – " in content_h2_text else " | "
        product_name = content_h2_text.split(sep)[0].strip()
        tagline = content_h2_text
    elif content_h2_text:
        product_name = content_h2_text
        tagline = None
    else:
        product_name = banner_h1_text

    if not product_name:
        title_el = soup.select_one("title")
        if title_el:
            product_name = _clean(title_el.get_text().split("|")[0])

    if not product_name:
        return None

    # Fallback tagline: section.full-year h2 when name came from banner h1
    if not tagline and not content_h2_text:
        h2_el = soup.select_one("section.full-year .heading h2")
        if h2_el:
            t = _clean(h2_el.get_text())
            tagline = t if t.lower() != product_name.lower() else None

    # -------------------------------------------------------------------------
    # Description — prefer the content-section .heading block (Layout B);
    # fall back to the general .full-year .heading block (Layout A).
    # -------------------------------------------------------------------------
    desc_container = (
        soup.select_one("section.full-year .content-section .heading")
        or soup.select_one("section.full-year .heading")
        or soup.select_one(".product-description")
    )
    if desc_container:
        # Collect text from p and span children; skip the product name heading
        paragraphs: list[str] = []
        for el in desc_container.find_all(["p", "span"], recursive=True):
            # Skip nested spans already collected inside a p
            if el.parent and el.parent.name in ("p", "span") and el.parent in desc_container.descendants:
                continue
            text = _clean(el.get_text())
            if text and len(text) > 30 and text not in paragraphs:
                paragraphs.append(text)
        description = " ".join(paragraphs) if paragraphs else _clean(desc_container.get_text())
    else:
        description = raw_text[:800]

    # -------------------------------------------------------------------------
    # Key benefits — three sources merged and deduplicated:
    #   1. .tab-content .tab-pane ul li  (tabbed benefit/coverage panels)
    #   2. section.full-year .heading ul li  (inline bullet list, Layout A)
    #   3. .benefit-card / .icon-benefit cards
    # -------------------------------------------------------------------------
    benefits: list[str] = []
    seen_b: set[str] = set()

    # Scope tab-pane benefit lists to section.full-year to avoid picking up
    # the nav mega-menu tabs which use the same .tab-content/.tab-pane structure
    # across the whole page.
    full_year = soup.select_one("section.full-year")
    benefit_scope = full_year if full_year else soup
    for li in benefit_scope.select(".tab-content .tab-pane ul li, .tab-content .tab-pane ol li"):
        text = _clean(li.get_text())
        if text and len(text) > 5 and text not in seen_b:
            seen_b.add(text)
            benefits.append(text)

    if desc_container:
        for li in desc_container.select("ul li"):
            text = _clean(li.get_text())
            if text and len(text) > 5 and text not in seen_b:
                seen_b.add(text)
                benefits.append(text)

    for card in soup.select(".benefit-card, .icon-benefit, .feature-item"):
        text = _clean(card.get_text())
        if text and len(text) > 5 and text not in seen_b:
            seen_b.add(text)
            benefits.append(text)

    # -------------------------------------------------------------------------
    # Target audience — look for "Who is it for?" / "Ideal for" headings,
    # or infer from the first description paragraph
    # -------------------------------------------------------------------------
    target_audience: str | None = None

    who_el = soup.find(string=re.compile(r"who (is it |should |can )?for|ideal for|designed for", re.IGNORECASE))
    if who_el:
        block = who_el.find_parent(["p", "div", "section", "li"])
        if block:
            ul = block.find_next_sibling("ul") or block.find("ul")
            if ul:
                items = [_clean(li.get_text()) for li in ul.select("li") if _clean(li.get_text())]
                target_audience = " | ".join(items) if items else None

    if not target_audience:
        suitable_el = soup.find(string=re.compile(r"suitable for|meant for", re.IGNORECASE))
        if suitable_el:
            block = suitable_el.find_parent(["p", "div"])
            ul = block.find_next_sibling("ul") if block else None
            if ul:
                items = [_clean(li.get_text()) for li in ul.select("li") if _clean(li.get_text())]
                target_audience = " | ".join(items) if items else None

    # -------------------------------------------------------------------------
    # Coverage table — Britam plan comparison tables (e.g. Milele Health tiers)
    # Each row: feature name | values per plan tier
    # Stored as coverage_notes summary + full table in extra_data
    # -------------------------------------------------------------------------
    coverage_notes: str | None = None
    coverage_table: list[dict] = []

    for row in soup.select("tr.milele-plans-row, tr.plans-row, tr[class*='plan']"):
        feature_el = row.select_one("td[class*='features-col'], td:first-child")
        value_els = row.select("td[class*='plan-col'], td[data-plan-col]")
        if feature_el and value_els:
            feature = _clean(feature_el.get_text())
            values = [_clean(v.get_text()) for v in value_els]
            if feature and any(values):
                coverage_table.append({"feature": feature, "values": values})

    if coverage_table:
        # Build a brief human-readable summary from the inpatient limit row
        for row_data in coverage_table:
            if "inpatient" in row_data["feature"].lower() and "limit" in row_data["feature"].lower():
                coverage_notes = f"Inpatient limits: {' / '.join(v for v in row_data['values'] if v)}"
                break
        if not coverage_notes:
            coverage_notes = f"{len(coverage_table)} plan features in comparison table"

    # -------------------------------------------------------------------------
    # Premium — no public price table on most Britam pages; scan for KES amounts
    # prefixed with "from", "starting", "as low as"
    # -------------------------------------------------------------------------
    premium_min: float | None = None
    premium_frequency: str | None = None

    monthly_match = re.search(
        r"(?:from|start|as low as)\s+(?:KES|Ksh)\.?\s*([\d,]+)\s*(?:/\s*month|per\s*month)",
        raw_text,
        re.IGNORECASE,
    )
    if monthly_match:
        premium_min = float(monthly_match.group(1).replace(",", ""))
        premium_frequency = "monthly"

    # -------------------------------------------------------------------------
    # Age eligibility — "join up to age X" / "aged X to Y" / "entry age"
    # -------------------------------------------------------------------------
    min_age: int | None = None
    max_age: int | None = None

    entry_match = re.search(r"(?:minimum age of entry|entry age|age of entry)\s*(?:of|is|:)?\s*(\d+)", raw_text, re.IGNORECASE)
    if entry_match:
        min_age = int(entry_match.group(1))

    max_entry_match = re.search(r"(?:maximum age of entry|max(?:imum)?\s*age)\s*(?:of|is|:)?\s*(\d+)", raw_text, re.IGNORECASE)
    if max_entry_match:
        max_age = int(max_entry_match.group(1))

    join_match = re.search(r"join (?:up to )?age\s+(\d+)", raw_text, re.IGNORECASE)
    if join_match:
        max_age = max_age or int(join_match.group(1))

    aged_match = re.search(r"aged\s+(\d+)\s*[-–to]+\s*(\d+)", raw_text, re.IGNORECASE)
    if aged_match:
        min_age = min_age or int(aged_match.group(1))
        max_age = max_age or int(aged_match.group(2))

    # -------------------------------------------------------------------------
    # Waiting period
    # -------------------------------------------------------------------------
    waiting_period: str | None = None
    wait_match = re.search(r"waiting period\s*[:\-]?\s*([^\.\n]{5,60})", raw_text, re.IGNORECASE)
    if wait_match:
        waiting_period = _clean(wait_match.group(1))

    # -------------------------------------------------------------------------
    # FAQs — Bootstrap accordion (.accordion-item), same pattern as Jubilee
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
    # Downloadable brochures — stored in extra_data for future reference
    # -------------------------------------------------------------------------
    brochures: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if href.endswith(".pdf") or "/FormsAndDownloads/" in href:
            label = _clean(a.get_text()) or href.split("/")[-1]
            full_url = href if href.startswith("http") else "https://ke.britam.com" + href
            brochures.append({"label": label, "url": full_url})

    # -------------------------------------------------------------------------
    # Contact — WhatsApp number embedded in the chat link href
    # -------------------------------------------------------------------------
    contact_phone: str | None = None
    wa_link = soup.find("a", href=re.compile(r"whatsapp\.com/send/?\?phone=(\d+)"))
    if wa_link:
        wa_match = re.search(r"phone=(\d+)", str(wa_link["href"]))
        if wa_match:
            contact_phone = "+" + wa_match.group(1)

    if not contact_phone:
        contact_phone = _extract_phone(raw_text)

    contact_email = _extract_email(raw_text)

    # -------------------------------------------------------------------------
    # How to apply — callback modal or "Get Started" button present on all pages
    # -------------------------------------------------------------------------
    how_to_apply: str | None = None
    if soup.select_one("button#productscallback, .milele-plans-get-started, button[data-bs-target*='Callback']"):
        how_to_apply = "Request a callback online via the product page. Britam also available on WhatsApp: +254705100100."

    # -------------------------------------------------------------------------
    # Build extra_data
    # -------------------------------------------------------------------------
    extra_data: dict = {}
    if faqs:
        extra_data["faqs"] = faqs
    if coverage_table:
        extra_data["coverage_table"] = coverage_table
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
        tagline=tagline,
        target_audience=target_audience,
        premium_min_kes=premium_min,
        premium_max_kes=None,
        premium_frequency=premium_frequency,
        premium_notes="Quote-based — no public price table. Request a callback or download the product brochure.",
        coverage_min_kes=None,
        coverage_max_kes=None,
        coverage_notes=coverage_notes,
        min_age=min_age,
        max_age=max_age,
        eligibility_notes=None,
        key_benefits=benefits,
        exclusions=[],
        waiting_period=waiting_period,
        claims_process=None,
        how_to_apply=how_to_apply,
        contact_phone=contact_phone,
        contact_email=contact_email,
        extra_data=extra_data,
        raw_text=raw_text,
        confidence=confidence,
    )
