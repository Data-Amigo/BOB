from dataclasses import dataclass


# =============================================================================
# Mozzart Football Odds Model
# =============================================================================
# This model stores the stable football fields we currently understand from the
# Mozzart prematch football page. It captures fixture identity, kickoff text,
# the extra market count, and the visible 1/X/2 odds.
@dataclass(slots=True)
class MozzartFootballOdds:
    """Structured prematch football odds row extracted from Mozzart."""

    source: str
    sport: str
    league: str
    event_datetime_text: str
    game_id: str
    home_team: str
    away_team: str
    match_status: str | None
    score_text: str | None
    extra_market_count: int | None
    home_odds: float | None
    draw_odds: float | None
    away_odds: float | None
    raw_text: str
    confidence: float


# =============================================================================
# Mozzart Basketball Odds Model
# =============================================================================
# This model stores the stable basketball fields we currently understand from
# the Mozzart prematch basketball page. It captures fixture identity, kickoff
# text, the extra market count, and the visible winner-style odds.
@dataclass(slots=True)
class MozzartBasketballOdds:
    """Structured prematch basketball odds row extracted from Mozzart."""

    source: str
    sport: str
    league: str
    event_datetime_text: str
    game_id: str
    home_team: str
    away_team: str
    match_status: str | None
    score_text: str | None
    extra_market_count: int | None
    home_odds: float | None
    draw_odds: float | None
    away_odds: float | None
    raw_text: str
    confidence: float
