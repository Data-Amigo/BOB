"""This is the sources.py file.

Author: Data-Amigo
Date: 2026-04-16
Description:
This is the source registry. It tells the app which websites/data sources exist,
their target pages, default URLs, display names, descriptions, and default
browser settings.
"""

from dataclasses import dataclass


# =============================================================================
# Source Target Model
# =============================================================================
@dataclass(frozen=True, slots=True)
class SourceTarget:
    """Configuration details for one target page under a source.

    Attributes:
        name: Internal target key, such as "football_today".
        display_name: Human-readable target name shown in the UI.
        url: Exact URL to fetch for this target.
        sport: Sport or category represented by this target.
        description: Short explanation of what this target contains.
    """

    name: str
    display_name: str
    url: str
    sport: str
    description: str


# =============================================================================
# Source Configuration Model
# =============================================================================
@dataclass(frozen=True, slots=True)
class SourceConfig:
    """Configuration details for one supported scraping source."""

    name: str
    display_name: str
    default_target: str
    targets: dict[str, SourceTarget]
    description: str
    default_wait_until: str = "domcontentloaded"
    default_settle_ms: int = 3_000
    default_headless: bool = True

    @property
    def default_url(self) -> str:
        """Return the URL for the source's default target."""

        return self.targets[self.default_target].url


# =============================================================================
# Supported Source Registry
# =============================================================================
SOURCES: dict[str, SourceConfig] = {
    "forebet": SourceConfig(
        name="forebet",
        display_name="Forebet",
        default_target="basketball_today",
        description="Sports prediction source for football and basketball workflows.",
        default_wait_until="domcontentloaded",
        default_settle_ms=15_000,
        default_headless=False,
        targets={
            "football_today": SourceTarget(
                name="football_today",
                display_name="Football Predictions Today",
                url="https://www.forebet.com/en/football-tips-and-predictions-for-today",
                sport="football",
                description="Forebet football predictions for today's matches.",
            ),
            "football_yesterday": SourceTarget(
                name="football_yesterday",
                display_name="Football Results Yesterday",
                url="https://www.forebet.com/en/football-predictions-from-yesterday",
                sport="football",
                description="Forebet football results page for yesterday's finished matches.",
            ),
            "basketball_today": SourceTarget(
                name="basketball_today",
                display_name="Basketball Predictions Today",
                url="https://www.forebet.com/en/basketball/predictions-today",
                sport="basketball",
                description="Forebet basketball predictions for today's games.",
            ),
            "basketball_yesterday": SourceTarget(
                name="basketball_yesterday",
                display_name="Basketball Results Yesterday",
                url="https://www.forebet.com/en/basketball/predictions-yesterday",
                sport="basketball",
                description="Forebet basketball results page for yesterday's finished games.",
            ),
        },
    ),
    "polymarket": SourceConfig(
        name="polymarket",
        display_name="Polymarket",
        default_target="markets",
        description="Strategic prediction-market source for broader market intelligence.",
        default_wait_until="domcontentloaded",
        default_settle_ms=5_000,
        default_headless=True,
        targets={
            "markets": SourceTarget(
                name="markets",
                display_name="All Markets",
                url="https://polymarket.com/markets",
                sport="market_intelligence",
                description="Polymarket markets index for broad prediction-market discovery.",
            ),
        },
    ),
    "sportpesa": SourceConfig(
        name="sportpesa",
        display_name="SportPesa",
        default_target="football_today",
        description="Bookmaker odds source for football and basketball fixtures with visible market prices.",
        default_wait_until="domcontentloaded",
        default_settle_ms=10_000,
        default_headless=False,
        targets={
            "football_today": SourceTarget(
                name="football_today",
                display_name="Football Odds Today",
                url="https://www.sportpesa.co.ke/sports/football",
                sport="football",
                description="SportPesa football fixtures with 3-way, double chance, totals, and BTTS odds.",
            ),
            "basketball_today": SourceTarget(
                name="basketball_today",
                display_name="Basketball Odds Today",
                url="https://www.ke.sportpesa.com/en/sports-betting/basketball-2/today-games/",
                sport="basketball",
                description="SportPesa basketball fixtures with 2-way odds including overtime.",
            ),
        },
    ),
    "betika": SourceConfig(
        name="betika",
        display_name="Betika",
        default_target="football_today",
        description="Bookmaker odds source for football and basketball fixtures from Betika.",
        default_wait_until="domcontentloaded",
        default_settle_ms=10_000,
        default_headless=False,
        targets={
            "football_today": SourceTarget(
                name="football_today",
                display_name="Football Odds Today",
                url="https://ke.betika.com/en-ke/sports/soccer-14",
                sport="football",
                description="Betika football odds page for current fixtures and markets.",
            ),
            "basketball_today": SourceTarget(
                name="basketball_today",
                display_name="Basketball Odds Today",
                url="https://ke.betika.com/en-ke/sports/basketball-30",
                sport="basketball",
                description="Betika basketball odds page for current fixtures and markets.",
            ),
        },
    ),
    "mozzart": SourceConfig(
        name="mozzart",
        display_name="Mozzart",
        default_target="football_today",
        description="Bookmaker odds source for Mozzart Kenya prematch football and basketball fixtures.",
        default_wait_until="domcontentloaded",
        default_settle_ms=15_000,
        default_headless=False,
        targets={
            "football_today": SourceTarget(
                name="football_today",
                display_name="Football Odds Today",
                url="https://m.mozzartbet.co.ke/betting?sport_id=1",
                sport="football",
                description="Mozzart prematch football fixtures with game ids, kickoff times, and 1/X/2 odds.",
            ),
            "basketball_today": SourceTarget(
                name="basketball_today",
                display_name="Basketball Odds Today",
                url="https://m.mozzartbet.co.ke/betting?sport_id=2",
                sport="basketball",
                description="Mozzart prematch basketball fixtures with game ids, kickoff times, and winner-style odds.",
            ),
        },
    ),
    "flashscore": SourceConfig(
        name="flashscore",
        display_name="Flashscore",
        default_target="basketball_today",
        description="Live score and results source for broad football and basketball coverage.",
        default_wait_until="domcontentloaded",
        default_settle_ms=12_000,
        default_headless=False,
        targets={
            "football_today": SourceTarget(
                name="football_today",
                display_name="Football Scores Today",
                url="https://www.flashscore.co.ke/football/",
                sport="football",
                description="Flashscore football live scores, fixtures, and finished-match coverage.",
            ),
            "football_yesterday_results": SourceTarget(
                name="football_yesterday_results",
                display_name="Football Results Yesterday",
                url="https://www.flashscore.co.ke/football/",
                sport="football",
                description="Flashscore football results board shifted to the previous day and filtered to finished matches.",
            ),
            "basketball_today": SourceTarget(
                name="basketball_today",
                display_name="Basketball Scores Today",
                url="https://www.flashscore.co.ke/basketball/",
                sport="basketball",
                description="Flashscore basketball live scores, fixtures, and finished-game coverage.",
            ),
            "basketball_yesterday_results": SourceTarget(
                name="basketball_yesterday_results",
                display_name="Basketball Results Yesterday",
                url="https://www.flashscore.co.ke/basketball/",
                sport="basketball",
                description="Flashscore basketball results board shifted to the previous day and filtered to finished games.",
            ),
        },
    ),
}


# =============================================================================
# Source Lookup Helper
# =============================================================================
def get_source_config(source_name: str) -> SourceConfig:
    """Return the configuration object for a supported source."""

    try:
        return SOURCES[source_name]
    except KeyError as exc:
        supported = ", ".join(sorted(SOURCES))
        raise ValueError(f"Unsupported source '{source_name}'. Supported sources: {supported}") from exc


# =============================================================================
# Target Lookup Helper
# =============================================================================
def get_source_target(source: SourceConfig, target_name: str | None = None) -> SourceTarget:
    """Return a target page config from a source."""

    selected_target = target_name or source.default_target

    try:
        return source.targets[selected_target]
    except KeyError as exc:
        supported = ", ".join(sorted(source.targets))
        raise ValueError(
            f"Unsupported target '{selected_target}' for source '{source.name}'. "
            f"Supported targets: {supported}"
        ) from exc
