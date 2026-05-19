from dataclasses import dataclass


# =============================================================================
# Flashscore Score Model
# =============================================================================
# Flashscore is being considered as a live/results fallback source. The V1 model
# stays intentionally small and focuses on fixture identity, visible page-date
# context, status, and score.
@dataclass(slots=True)
class FlashscoreScoreRow:
    """Structured score row extracted from Flashscore."""

    source: str
    sport: str
    page_date_text: str | None
    country_or_region: str | None
    league: str
    match_status: str
    event_time_text: str | None
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    raw_text: str
    confidence: float
