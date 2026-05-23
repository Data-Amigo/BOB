from __future__ import annotations

from dataclasses import dataclass


# =============================================================================
# Insurance Source Target
# =============================================================================
# Mirrors scrapers/sources.py SourceTarget but uses `category` instead of
# `sport` — insurance products belong to categories like health, life, motor.
@dataclass(frozen=True, slots=True)
class InsuranceSourceTarget:
    """Configuration for one target page under an insurance source.

    Attributes:
        name: Internal key. e.g. "health".
        display_name: Human-readable label shown in the UI.
        url: Exact URL to fetch for this target.
        category: Insurance category this target covers.
        description: Short explanation of what this page contains.
    """

    name: str
    display_name: str
    url: str
    category: str
    description: str


# =============================================================================
# Insurance Source Configuration
# =============================================================================
@dataclass(frozen=True, slots=True)
class InsuranceSourceConfig:
    """Configuration for one supported insurance source (insurer).

    Attributes:
        name: Internal slug. e.g. "jubilee".
        display_name: Human-readable insurer name.
        base_url: Root domain of the insurer's website.
        default_target: Key of the target to use when none is specified.
        targets: All known product pages for this insurer, keyed by target name.
        description: Short description of the insurer for display purposes.
        default_wait_until: Playwright load state. Insurance sites are usually
            less JavaScript-heavy than betting sites, so domcontentloaded works.
        default_settle_ms: Extra milliseconds after load before reading HTML.
        default_headless: Whether to run the browser without a visible window.
    """

    name: str
    display_name: str
    base_url: str
    default_target: str
    targets: dict[str, InsuranceSourceTarget]
    description: str
    default_wait_until: str = "domcontentloaded"
    default_settle_ms: int = 4_000
    default_headless: bool = True
    ignore_https_errors: bool = False
    skip_listing_fetch: bool = False

    @property
    def default_url(self) -> str:
        """Return the URL for the default target."""
        return self.targets[self.default_target].url


# =============================================================================
# Insurance Source Registry
# =============================================================================
INSURANCE_SOURCES: dict[str, InsuranceSourceConfig] = {

    "jubilee": InsuranceSourceConfig(
        name="jubilee",
        display_name="Jubilee Insurance",
        base_url="https://jubileeinsurance.com",
        default_target="health",
        description="One of Kenya's largest insurers. Products span health, life, asset management, and wellness lines.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        default_headless=True,
        targets={
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://jubileeinsurance.com/ke/health/",
                category="health",
                description="Jubilee individual and family health insurance plans.",
            ),
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life & Pension",
                url="https://jubileeinsurance.com/ke/life-pension/",
                category="life",
                description="Jubilee life insurance, pension, and savings-linked products.",
            ),
            "asset_management": InsuranceSourceTarget(
                name="asset_management",
                display_name="Asset Management",
                url="https://jubileeinsurance.com/ke/asset-management/",
                category="investment",
                description="Jubilee asset management and investment products.",
            ),
            "maisha_fiti": InsuranceSourceTarget(
                name="maisha_fiti",
                display_name="Maisha Fiti",
                url="https://jubileeinsurance.com/ke/maisha-fiti/",
                category="wellness",
                description="Jubilee Maisha Fiti wellness and lifestyle product.",
            ),
        },
    ),

    "britam": InsuranceSourceConfig(
        name="britam",
        display_name="Britam",
        base_url="https://ke.britam.com",
        default_target="personal_protection",
        description="Britam Kenya — insurance, savings, education, and pension products for individuals and businesses.",
        default_wait_until="load",
        default_settle_ms=6_000,
        targets={
            # --- Personal protection products --------------------------------
            # The sub-category listing pages (e.g. /health-insurance-covers)
            # time out; the parent overview page loads and contains all product
            # links in its navigation, so it is used as the listing source.
            "personal_protection": InsuranceSourceTarget(
                name="personal_protection",
                display_name="Personal Protection",
                url="https://ke.britam.com/home/personal/protect-who-you-love",
                category="health",
                description="All personal protection products: health, life, funeral, travel, personal accident.",
            ),
            # --- Personal property / motor products --------------------------
            "personal_property": InsuranceSourceTarget(
                name="personal_property",
                display_name="Personal Property & Motor",
                url="https://ke.britam.com/home/personal/protect-what-you-love",
                category="motor",
                description="Motor, home, fire & burglary, and other personal property products.",
            ),
            # --- Savings & investment products --------------------------------
            "education": InsuranceSourceTarget(
                name="education",
                display_name="Education Plans",
                url="https://ke.britam.com/save-and-invest/personal/education-plans",
                category="education",
                description="Britam education savings plans for school and university fees.",
            ),
            "savings": InsuranceSourceTarget(
                name="savings",
                display_name="Insurance Savings Plans",
                url="https://ke.britam.com/save-and-invest/personal/insurance-savings-plans",
                category="savings",
                description="Britam insurance-linked savings plans (Akiba, Dhamana).",
            ),
            "investment": InsuranceSourceTarget(
                name="investment",
                display_name="Investment-Linked Plans",
                url="https://ke.britam.com/save-and-invest/personal/invest/investment-linked",
                category="investment",
                description="Britam investment-linked insurance plans (Imarika Plus, Nawiri).",
            ),
            "unit_trust": InsuranceSourceTarget(
                name="unit_trust",
                display_name="Unit Trust Funds",
                url="https://ke.britam.com/save-and-invest/personal/invest/unit-trust-funds",
                category="investment",
                description="Britam unit trust funds: money market, bond, equity, balanced.",
            ),
            # --- Pension & retirement products --------------------------------
            "pension": InsuranceSourceTarget(
                name="pension",
                display_name="Pension & Retirement",
                url="https://ke.britam.com/pension/personal",
                category="pension",
                description="Britam personal pension and retirement products (individual plans, annuities, drawdown).",
            ),
        },
    ),

    "cic": InsuranceSourceConfig(
        name="cic",
        display_name="CIC Insurance",
        base_url="https://ke.cicinsurancegroup.com",
        default_target="individual",
        description="CIC Insurance Group (Kenya) — cooperative-based insurer with individual, business, and cooperatives products.",
        default_wait_until="networkidle",
        default_settle_ms=4_000,
        targets={
            # Individual solutions: savings, health, accident, retirement, investment,
            # domestic, professional indemnity.  Each sub-category page holds multiple
            # products introduced by h3 "Why [Product Name]" headings.
            "individual": InsuranceSourceTarget(
                name="individual",
                display_name="Individual Solutions",
                url="https://ke.cicinsurancegroup.com/individual-solutions/",
                category="life",
                description="CIC individual solutions: savings, health, accident, retirement, investment, domestic.",
            ),
            # Business solutions: motor, fire, burglary, accident, investment.
            "business": InsuranceSourceTarget(
                name="business",
                display_name="Business Solutions",
                url="https://ke.cicinsurancegroup.com/business-solutions/",
                category="general",
                description="CIC business insurance: motor, fire, burglary, group accident, investment.",
            ),
        },
    ),

    "old_mutual": InsuranceSourceConfig(
        name="old_mutual",
        display_name="Old Mutual",
        base_url="https://www.oldmutual.co.ke",
        default_target="personal_insure",
        description="Old Mutual Kenya — insurance, savings, education, pension, and investment products.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        targets={
            # All personal insurance products: life, health, accident, travel, motor, home
            "personal_insure": InsuranceSourceTarget(
                name="personal_insure",
                display_name="Personal Insurance",
                url="https://www.oldmutual.co.ke/personal/insure/",
                category="life",
                description="All Old Mutual personal insurance: life, health, accident, travel, motor, home.",
            ),
            # Savings, education, and pension products
            "save_invest": InsuranceSourceTarget(
                name="save_invest",
                display_name="Save & Invest",
                url="https://www.oldmutual.co.ke/personal/save-and-invest/",
                category="savings",
                description="Old Mutual savings, education, and pension products.",
            ),
            # Unit trust funds
            "unit_trust": InsuranceSourceTarget(
                name="unit_trust",
                display_name="Unit Trust Funds",
                url="https://www.oldmutual.co.ke/investment/unit-trust/",
                category="investment",
                description="Old Mutual unit trust funds: money market, equity, balanced, bond.",
            ),
        },
    ),

    "sanlam": InsuranceSourceConfig(
        name="sanlam",
        display_name="Sanlam Kenya",
        base_url="https://www.sanlam.co.ke",
        default_target="all_products",
        description="Sanlam Kenya General Insurance — motor, home, travel, personal accident, and commercial products.",
        default_wait_until="networkidle",
        default_settle_ms=3_000,
        targets={
            # The /general-insurance/individual and /general-insurance/corporate
            # sub-pages return empty HTML; the parent /general-insurance overview
            # page contains all product links (individual + corporate).
            "all_products": InsuranceSourceTarget(
                name="all_products",
                display_name="All Products",
                url="https://www.sanlam.co.ke/general-insurance",
                category="general",
                description="All Sanlam Kenya products: personal and commercial general insurance.",
            ),
        },
    ),

    "icea_lion": InsuranceSourceConfig(
        name="icea_lion",
        display_name="ICEA Lion",
        base_url="https://www.icealion.co.ke",
        default_target="all_products",
        description="ICEA Lion Group — insurance and asset management across health, life, general, pension, and investment lines.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        targets={
            # ICEA Lion uses a flat URL scheme: every product lives at /<slug>.
            # There are no section listing pages, so the homepage is used as the
            # listing source.  The parser filters to single-segment product slugs.
            "all_products": InsuranceSourceTarget(
                name="all_products",
                display_name="All Products",
                url="https://www.icealion.co.ke",
                category="life",
                description="All ICEA Lion products: life, health, motor, general, pension, and investment.",
            ),
        },
    ),

    "aar": InsuranceSourceConfig(
        name="aar",
        display_name="AAR Insurance",
        base_url="https://aar-insurance.com",
        default_target="all_products",
        description="AAR Insurance Kenya — health, personal accident, property, and travel insurance.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        ignore_https_errors=True,
        skip_listing_fetch=True,
        targets={
            "all_products": InsuranceSourceTarget(
                name="all_products",
                display_name="All Products",
                url="https://aar-insurance.com",
                category="health",
                description="All AAR products: medical, accident, homeowners, landlord, WIBA, travel, marine.",
            ),
        },
    ),

    "apa": InsuranceSourceConfig(
        name="apa",
        display_name="APA Insurance",
        base_url="https://www.apainsurance.org",
        default_target="all_products",
        description="APA Insurance — general and life insurance products for Kenyan individuals and businesses. Pages protected by AWS WAF; headed browser required.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        default_headless=False,
        skip_listing_fetch=True,
        targets={
            "all_products": InsuranceSourceTarget(
                name="all_products",
                display_name="All Products",
                url="https://www.apainsurance.org/products",
                category="general",
                description="All APA Insurance products: health, motor, travel, agriculture, micro.",
            ),
        },
    ),

    "ga_insurance": InsuranceSourceConfig(
        name="ga_insurance",
        display_name="GA Insurance",
        base_url="https://www.gainsuranceltd.com",
        default_target="all_products",
        description="GA Insurance Kenya — general, health, and specialty insurance for individuals and businesses.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        skip_listing_fetch=True,
        targets={
            # GA uses a multi-level category structure (homepage → category pages →
            # product pages).  The parser uses a hardcoded product URL list derived
            # from that structure; any listing URL is accepted.
            "all_products": InsuranceSourceTarget(
                name="all_products",
                display_name="All Products",
                url="https://www.gainsuranceltd.com/ke/",
                category="general",
                description="All GA Insurance personal, commercial, and health products.",
            ),
        },
    ),

    "geminia": InsuranceSourceConfig(
        name="geminia",
        display_name="Geminia Insurance",
        base_url="https://www.geminia.co.ke",
        default_target="all_products",
        description="Geminia Insurance — general insurance for personal, business, agribusiness, and property in Kenya.",
        default_wait_until="domcontentloaded",
        default_settle_ms=4_000,
        skip_listing_fetch=True,
        targets={
            # parse_product_listing returns a hardcoded URL list and ignores the
            # HTML, so any stable product page can serve as the listing URL.
            "all_products": InsuranceSourceTarget(
                name="all_products",
                display_name="All Products",
                url="https://www.geminia.co.ke/protect-yourself/motor_insurance/",
                category="general",
                description="All Geminia products: personal, business, agribusiness, and property protection.",
            ),
        },
    ),

    "absa_life": InsuranceSourceConfig(
        name="absa_life",
        display_name="ABSA Life Insurance",
        base_url="https://www.absa.co.ke",
        default_target="life",
        description="ABSA Life Insurance Kenya — life and credit life products.",
        targets={
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life Insurance",
                url="https://www.absa.co.ke/personal/insurance/life-insurance",
                category="life",
                description="ABSA life insurance and credit life products.",
            ),
        },
    ),
}


# =============================================================================
# Lookup Helpers
# =============================================================================
def get_insurance_source(name: str) -> InsuranceSourceConfig:
    """Return an insurer config by slug. Raises ValueError for unknown names."""

    try:
        return INSURANCE_SOURCES[name]
    except KeyError as exc:
        supported = ", ".join(sorted(INSURANCE_SOURCES))
        raise ValueError(
            f"Unknown insurance source '{name}'. Supported: {supported}"
        ) from exc


def get_insurance_target(source: InsuranceSourceConfig, target_name: str | None = None) -> InsuranceSourceTarget:
    """Return a target page config from an insurer source."""

    key = target_name or source.default_target
    try:
        return source.targets[key]
    except KeyError as exc:
        supported = ", ".join(sorted(source.targets))
        raise ValueError(
            f"Unknown target '{key}' for '{source.name}'. Supported: {supported}"
        ) from exc
