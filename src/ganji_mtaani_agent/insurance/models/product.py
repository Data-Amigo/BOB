from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Insurance Product Model
# =============================================================================
# This model represents one insurance product scraped from a Kenyan insurer's
# website. Every field is designed with one goal: give an LLM enough structured
# context to explain, compare, and recommend products accurately.
#
# Design decisions:
# - One unified model for all product types (health, life, motor, etc.).
#   Type-specific fields go into extra_data as a dict rather than creating
#   separate subclasses. This keeps the DB schema simple and makes LLM
#   queries across product types straightforward.
# - Required fields come first (no defaults). Optional fields follow.
# - list[str] fields use field(default_factory=list) — never a mutable default.
@dataclass(slots=True)
class InsuranceProduct:
    """One insurance product scraped from a Kenyan insurer's website.

    Attributes:
        insurer_name: Full legal name of the insurer. e.g. "Jubilee Insurance".
        insurer_slug: Short lowercase key used for routing. e.g. "jubilee".
        product_name: Exact product name as shown on the insurer's site.
        product_type: Category of insurance. One of: "health", "life", "motor",
            "education", "personal_accident", "pension", "travel", "general".
        product_url: The exact page URL this product was scraped from.
        description: Full product description text. Should be comprehensive
            enough for an LLM to summarise and explain the product without
            needing to re-visit the source page.

        tagline: Short marketing headline for the product, if present.
        target_audience: Who the product is intended for. e.g. "Individuals
            aged 18–65", "Families", "SMEs", "First-time buyers".

        premium_min_kes: Lowest stated monthly or annual premium in KES.
        premium_max_kes: Highest stated monthly or annual premium in KES.
        premium_frequency: How often the premium is paid. One of: "monthly",
            "annual", "one-off". None when the insurer does not state it.
        premium_notes: Free-text premium context when no exact number is
            available. e.g. "Premium varies by age and coverage selected".

        coverage_min_kes: Minimum sum assured or benefit limit in KES.
        coverage_max_kes: Maximum sum assured or benefit limit in KES.
        coverage_notes: Free-text coverage context. e.g. "Inpatient only" or
            "Includes maternity up to KES 150,000".

        min_age: Minimum entry age for the product.
        max_age: Maximum entry age for the product.
        eligibility_notes: Other eligibility conditions not captured by age.
            e.g. "Must be a Kenyan resident", "No pre-existing conditions".

        key_benefits: Structured list of what the product covers. This is the
            primary field an LLM uses to explain what a product offers.
        exclusions: Structured list of what is NOT covered. Critical for honest
            comparison — young users need to know what they cannot claim for.
        waiting_period: How long before cover begins. e.g. "3 months",
            "6 months for pre-existing conditions", "Immediate for accidents".

        claims_process: How to file a claim. Important for usability — knowing
            a product is cheap means nothing if claiming is difficult.

        how_to_apply: How to buy or sign up. e.g. "Online", "Via agent",
            "Branch visit required".
        contact_phone: Insurer's contact phone number for this product.
        contact_email: Insurer's contact email for this product.

        extra_data: Type-specific fields that do not fit the shared schema.
            Examples: {"network_hospitals": [...]} for health products,
            {"vehicle_types": ["saloon", "SUV"]} for motor products.

        raw_text: Full page text as scraped. Used as LLM fallback context when
            structured fields are incomplete or parsing confidence is low.
        confidence: Extraction quality score from 0.0 to 1.0. Computed by the
            parser based on how many key fields were successfully extracted.
    """

    # -- Required fields (parser must provide these) --------------------------
    insurer_name: str
    insurer_slug: str
    product_name: str
    product_type: str
    product_url: str
    description: str

    # -- What the product is --------------------------------------------------
    tagline: str | None = None
    target_audience: str | None = None

    # -- Pricing --------------------------------------------------------------
    premium_min_kes: float | None = None
    premium_max_kes: float | None = None
    premium_frequency: str | None = None
    premium_notes: str | None = None

    # -- Coverage -------------------------------------------------------------
    coverage_min_kes: float | None = None
    coverage_max_kes: float | None = None
    coverage_notes: str | None = None

    # -- Eligibility ----------------------------------------------------------
    min_age: int | None = None
    max_age: int | None = None
    eligibility_notes: str | None = None

    # -- The honest comparison fields -----------------------------------------
    key_benefits: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    waiting_period: str | None = None

    # -- Claims ---------------------------------------------------------------
    claims_process: str | None = None

    # -- Contact / apply ------------------------------------------------------
    how_to_apply: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None

    # -- Type-specific overflow -----------------------------------------------
    extra_data: dict[str, Any] = field(default_factory=dict)

    # -- Raw context and metadata ---------------------------------------------
    raw_text: str = ""
    confidence: float = 0.0
