from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ganji_mtaani_agent.insurance.models.product import InsuranceProduct


INSURER_NAME = "CIC Insurance"
INSURER_SLUG = "cic"

# =============================================================================
# Category inference from sub-category page path
# =============================================================================
_PATH_CATEGORY_MAP: list[tuple[str, str]] = [
    ("saving-solution",     "savings"),
    ("investment-solution", "investment"),
    ("retirement",          "pension"),
    ("health",              "health"),
    ("accident",            "personal_accident"),
    ("domestic",            "property"),
    ("professional",        "property"),
    ("indemnity",           "property"),
    ("motor",               "motor"),
    ("fire",                "property"),
    ("burglary",            "property"),
    ("life-protection",     "life"),
    ("credit-life",         "life"),
]

_NAME_CATEGORY_MAP: list[tuple[str, str]] = [
    ("travel",              "travel"),
    ("annuity",             "pension"),
    ("pension",             "pension"),
    ("jipange",             "pension"),
    ("drawdown",            "pension"),
    ("draw down",           "pension"),
    ("education",           "education"),
    ("academia",            "education"),
    ("health",              "health"),
    ("mediplan",            "health"),
    ("accident",            "personal_accident"),
    ("motor",               "motor"),
    ("fire",                "property"),
    ("domestic",            "property"),
]


def _infer_category(product_name: str, page_url: str) -> str:
    name_lower = product_name.lower()
    for fragment, cat in _NAME_CATEGORY_MAP:
        if fragment in name_lower:
            return cat
    url_lower = page_url.lower()
    for fragment, cat in _PATH_CATEGORY_MAP:
        if fragment in url_lower:
            return cat
    return "life"


# =============================================================================
# Small helpers
# =============================================================================
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
# CIC Kenya organises products in a two-level hierarchy:
#   /individual-solutions/  →  /individual-solutions/saving-solutions/
#                              /individual-solutions/accident/
#                              …
#
# Each sub-category page contains MULTIPLE products presented as tabs, each
# introduced by an h3 heading "Why [Product Name]".
#
# parse_product_listing extracts the BASE sub-category page URLs (query
# parameters stripped). The pipeline then fetches each sub-category page and
# passes it to parse_product_page, which returns ALL products found on it.
def parse_product_listing(html: str, base_url: str, listing_url: str = "") -> list[str]:
    """Extract sub-category page URLs from a CIC solutions listing page.

    Args:
        html: Rendered HTML from /individual-solutions/ or /business-solutions/.
        base_url: https://ke.cicinsurancegroup.com
        listing_url: Full URL of the listing page (used to derive the section prefix).

    Returns:
        Sorted, deduplicated list of sub-category page URLs (no tab params).
    """
    soup = BeautifulSoup(html, "html.parser")

    section_prefix: str | None = None
    if listing_url:
        listing_path = urlparse(listing_url).path.rstrip("/")
        if listing_path:
            section_prefix = listing_path + "/"

    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith("#") or href.startswith("mailto"):
            continue
        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        if "ke.cicinsurancegroup.com" not in href:
            continue

        # Strip query and fragment; normalise trailing slash
        parsed = urlparse(href)
        clean_href = (parsed.scheme + "://" + parsed.netloc + parsed.path).rstrip("/") + "/"

        path = parsed.path.rstrip("/")

        if section_prefix and not path.startswith(section_prefix.rstrip("/")):
            continue

        # Must be exactly one level deeper than the section
        if section_prefix:
            relative = path[len(section_prefix.rstrip("/")):]
            segments = [s for s in relative.split("/") if s]
            if len(segments) != 1:
                continue

        if clean_href not in seen:
            seen.add(clean_href)
            urls.append(clean_href)

    return sorted(urls)


# =============================================================================
# Product Page Parser (returns multiple products)
# =============================================================================
# CIC sub-category pages display several products on a single page, each
# introduced by an h3 heading:
#   <h3>Why Smart Saver</h3>
#   <div>description paragraph one</div>
#   <div>description paragraph two</div>
#   <h3>Why Invest Plan</h3>
#   …
#
# This parser collects all "Why …" sections and produces one InsuranceProduct
# per section.  The pipeline must handle a list return value.
def parse_product_page(
    html: str,
    product_url: str,
    category: str,
) -> list[InsuranceProduct] | None:
    """Extract all InsuranceProducts from one CIC sub-category page.

    Args:
        html: Rendered HTML from the sub-category page.
        product_url: URL that was fetched — stored in each product for traceability.
        category: Fallback category from the source target configuration.

    Returns:
        List of populated InsuranceProduct objects (one per "Why…" section),
        or None if no products could be extracted.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Locate all "Why [ProductName]" h3 headings
    why_h3s: list[Tag] = [
        h3 for h3 in soup.find_all("h3")
        if h3.get_text(strip=True).lower().startswith("why ")
    ]
    if not why_h3s:
        return None

    # Page-level raw text for contact / age extraction
    page_raw = _clean(soup.get_text(" ", strip=True))
    contact_phone = _extract_phone(page_raw)
    contact_email = _extract_email(page_raw)

    products: list[InsuranceProduct] = []

    for idx, h3 in enumerate(why_h3s):
        # Product name: strip "Why " prefix
        raw_name = _clean(h3.get_text())
        product_name = re.sub(r"^Why\s+", "", raw_name, flags=re.IGNORECASE).strip()
        if not product_name:
            continue

        # Collect sibling elements until the next "Why" h3
        next_why = why_h3s[idx + 1] if idx + 1 < len(why_h3s) else None

        section_texts: list[str] = []
        benefit_items: list[str] = []

        for sib in h3.find_next_siblings():
            if sib is next_why:
                break
            if isinstance(sib, Tag) and sib.name == "h3" and sib.get_text(strip=True).lower().startswith("why"):
                break

            sib_text = _clean(sib.get_text(" ", strip=True))
            if len(sib_text) < 20:
                continue

            # Collect list items as benefits
            for li in sib.find_all("li"):
                li_text = _clean(li.get_text())
                if len(li_text) > 15:
                    benefit_items.append(li_text)

            # Use div/p text as description candidates
            if sib.name in ("div", "p") and len(sib_text) > 40:
                section_texts.append(sib_text)

        description = section_texts[0] if section_texts else ""
        additional = section_texts[1:3] if len(section_texts) > 1 else []
        benefits = benefit_items or additional

        product_category = _infer_category(product_name, product_url)

        # Age / eligibility from section text
        section_raw = " ".join(section_texts)
        min_age: int | None = None
        max_age: int | None = None

        age_range = re.search(r"(\d+)\s*(?:to|-|–)\s*(\d+)\s*years?", section_raw, re.IGNORECASE)
        if age_range:
            min_age = int(age_range.group(1))
            max_age = int(age_range.group(2))

        # Premium from section text
        premium_min: float | None = None
        premium_frequency: str | None = None
        prem_match = re.search(
            r"(?:from|starting)\s+(?:KES|Ksh|Kes)\.?\s*([\d,]+)\s*(?:/\s*month|per\s*month)",
            section_raw,
            re.IGNORECASE,
        )
        if prem_match:
            premium_min = float(prem_match.group(1).replace(",", ""))
            premium_frequency = "monthly"

        confidence = _score_confidence(product_name, description, benefits)

        products.append(InsuranceProduct(
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
            premium_notes="Contact CIC Insurance for a personalised quote.",
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
            raw_text=_clean(h3.get_text() + " " + " ".join(section_texts)),
            confidence=confidence,
        ))

    return products if products else None
