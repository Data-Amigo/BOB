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
        default_target="health",
        description="Britam Kenya — insurance and asset management products across health, life, and general lines.",
        targets={
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://ke.britam.com/insurance/health-insurance",
                category="health",
                description="Britam individual and group health insurance products.",
            ),
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life Insurance",
                url="https://ke.britam.com/insurance/life-insurance",
                category="life",
                description="Britam life and savings insurance products.",
            ),
        },
    ),

    "cic": InsuranceSourceConfig(
        name="cic",
        display_name="CIC Insurance",
        base_url="https://www.cicinsurancegroup.com",
        default_target="health",
        description="CIC Insurance Group — cooperative-based insurer offering health, life, and general products.",
        targets={
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://www.cicinsurancegroup.com/products/health-insurance",
                category="health",
                description="CIC individual and group medical insurance plans.",
            ),
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life Insurance",
                url="https://www.cicinsurancegroup.com/products/life-insurance",
                category="life",
                description="CIC life insurance and investment-linked products.",
            ),
        },
    ),

    "old_mutual": InsuranceSourceConfig(
        name="old_mutual",
        display_name="Old Mutual",
        base_url="https://www.oldmutual.co.ke",
        default_target="life",
        description="Old Mutual Kenya — long-term insurance, savings, and investment products.",
        targets={
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life Insurance",
                url="https://www.oldmutual.co.ke/personal/life-cover",
                category="life",
                description="Old Mutual life cover and savings products.",
            ),
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://www.oldmutual.co.ke/personal/health",
                category="health",
                description="Old Mutual health insurance products.",
            ),
        },
    ),

    "sanlam": InsuranceSourceConfig(
        name="sanlam",
        display_name="Sanlam Kenya",
        base_url="https://www.sanlam.co.ke",
        default_target="life",
        description="Sanlam Kenya — life, savings, and investment products.",
        targets={
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life Insurance",
                url="https://www.sanlam.co.ke/products/life-insurance",
                category="life",
                description="Sanlam Kenya life insurance and investment products.",
            ),
        },
    ),

    "icea_lion": InsuranceSourceConfig(
        name="icea_lion",
        display_name="ICEA Lion",
        base_url="https://www.icealion.co.ke",
        default_target="health",
        description="ICEA Lion Group — insurance and asset management across health, life, and general lines.",
        targets={
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://www.icealion.co.ke/insurance/health-insurance",
                category="health",
                description="ICEA Lion medical insurance plans.",
            ),
            "life": InsuranceSourceTarget(
                name="life",
                display_name="Life Insurance",
                url="https://www.icealion.co.ke/insurance/life-insurance",
                category="life",
                description="ICEA Lion life and savings products.",
            ),
        },
    ),

    "aar": InsuranceSourceConfig(
        name="aar",
        display_name="AAR Insurance",
        base_url="https://www.aar-insurance.com",
        default_target="health",
        description="AAR Insurance Kenya — specialist health and medical insurance provider.",
        targets={
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://www.aar-insurance.com/kenya/products/health-insurance",
                category="health",
                description="AAR individual and family medical insurance plans.",
            ),
        },
    ),

    "apa": InsuranceSourceConfig(
        name="apa",
        display_name="APA Insurance",
        base_url="https://www.apainsurance.org",
        default_target="health",
        description="APA Insurance — general and life insurance products for Kenyan individuals and businesses.",
        targets={
            "health": InsuranceSourceTarget(
                name="health",
                display_name="Health Insurance",
                url="https://www.apainsurance.org/products/health-insurance",
                category="health",
                description="APA medical and health insurance plans.",
            ),
            "motor": InsuranceSourceTarget(
                name="motor",
                display_name="Motor Insurance",
                url="https://www.apainsurance.org/products/motor-insurance",
                category="motor",
                description="APA motor insurance — comprehensive and third-party.",
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
