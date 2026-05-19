from dataclasses import dataclass


# =============================================================================
# Forebet Basketball Prediction Model
# =============================================================================
# This model stores the stable fields we currently understand from a Forebet
# basketball row. Anything beyond the stable core is kept in remaining_tokens
# until we fully understand the live/finished game structure.
@dataclass(slots=True)
class ForebetBasketballPrediction:
    """Structured basketball prediction row extracted from Forebet.

    Attributes:
        source: Source name. For this parser it will be "forebet".
        sport: Sport name. For this parser it will be "basketball".
        league: League code or competition label, for example "NBA".
        home_team: Home team name.
        away_team: Away team name.
        event_datetime: Date and time string as seen in the snapshot.
        prob_1: First probability column, likely home-win probability.
        prob_2: Second probability column, likely away-win probability.
        pred_outcome: Predicted outcome marker, usually "1" or "2".
        predicted_home_score: Predicted home team score.
        predicted_away_score: Predicted away team score.
        avg_points: Average total points value.
        coef_1: First coefficient-style value.
        coef_2: Second coefficient-style value.
        coef_3: Third coefficient-style value.
        remaining_tokens: Tokens after the stable core. We keep these for later
            live-score and quarter parsing.
        raw_text: Original row text before structured parsing.
        confidence: Extraction confidence score for the row.
    """

    source: str
    sport: str
    league: str
    home_team: str
    away_team: str
    event_datetime: str
    prob_1: int | None
    prob_2: int | None
    pred_outcome: str | None
    predicted_home_score: int | None
    predicted_away_score: int | None
    avg_points: float | None
    coef_1: float | None
    coef_2: float | None
    coef_3: float | None
    remaining_tokens: list[str]
    raw_text: str
    confidence: float


# =============================================================================
# Forebet Football Prediction Model
# =============================================================================
# This model stores the stable fields we currently understand from a Forebet
# football row. Anything after the stable core remains in remaining_tokens until
# we decide to parse live state and extra coefficient details later.
@dataclass(slots=True)
class ForebetFootballPrediction:
    """Structured football prediction row extracted from Forebet.

    Attributes:
        source: Source name. For this parser it will be "forebet".
        sport: Sport name. For this parser it will be "football".
        league: League code or competition label, for example "It1".
        home_team: Home team name.
        away_team: Away team name.
        event_datetime: Date and time string as seen in the snapshot.
        prob_1: Probability for home win.
        prob_x: Probability for draw.
        prob_2: Probability for away win.
        pred_outcome: Predicted outcome marker, usually "1", "X", or "2".
        predicted_home_score: Predicted home team score.
        predicted_away_score: Predicted away team score.
        correct_score_text: Combined correct-score text such as "1 - 2".
        avg_goals: Average goals value.
        weather: Weather string as shown by Forebet.
        coef_1: Coefficient for home win.
        coef_x: Coefficient for draw.
        coef_2: Coefficient for away win.
        coef_extra: Additional coefficient-style value shown after 1/X/2.
        remaining_tokens: Tokens after the stable core.
        raw_text: Original row text before structured parsing.
        confidence: Extraction confidence score for the row.
    """

    source: str
    sport: str
    league: str
    home_team: str
    away_team: str
    event_datetime: str
    prob_1: int | None
    prob_x: int | None
    prob_2: int | None
    pred_outcome: str | None
    predicted_home_score: int | None
    predicted_away_score: int | None
    correct_score_text: str | None
    avg_goals: float | None
    weather: str | None
    coef_1: float | None
    coef_x: float | None
    coef_2: float | None
    coef_extra: float | None
    remaining_tokens: list[str]
    raw_text: str
    confidence: float


# =============================================================================
# Forebet Basketball Result Model
# =============================================================================
@dataclass(slots=True)
class ForebetBasketballResult:
    """Structured finished basketball result row from Forebet yesterday pages."""

    source: str
    sport: str
    league: str
    home_team: str
    away_team: str
    event_datetime: str
    prob_1: int | None
    prob_2: int | None
    pred_outcome: str | None
    predicted_home_score: int | None
    predicted_away_score: int | None
    predicted_score_text: str | None
    actual_home_score: int | None
    actual_away_score: int | None
    actual_score_text: str | None
    actual_outcome: str | None
    status: str | None
    pred_hit: bool | None
    pred_indicator_class: str | None
    raw_text: str
    confidence: float


# =============================================================================
# Forebet Football Result Model
# =============================================================================
@dataclass(slots=True)
class ForebetFootballResult:
    """Structured finished football result row from Forebet yesterday pages."""

    source: str
    sport: str
    league: str
    home_team: str
    away_team: str
    event_datetime: str
    prob_1: int | None
    prob_x: int | None
    prob_2: int | None
    pred_outcome: str | None
    predicted_home_score: int | None
    predicted_away_score: int | None
    predicted_score_text: str | None
    actual_home_score: int | None
    actual_away_score: int | None
    actual_score_text: str | None
    actual_outcome: str | None
    status: str | None
    pred_hit: bool | None
    pred_indicator_class: str | None
    raw_text: str
    confidence: float


# =============================================================================
# Forebet Historical Analysis Models
# =============================================================================
@dataclass(slots=True)
class ForebetHistoricalAnalysis:
    """Structured summary extracted from one Forebet match detail page."""

    source: str
    sport: str
    match_url: str
    competition: str | None
    league_code: str | None
    event_datetime: str | None
    home_team: str
    away_team: str
    pred_outcome: str | None
    predicted_score_text: str | None
    actual_score_text: str | None
    actual_status: str | None
    home_form_sequence: str | None
    away_form_sequence: str | None
    confidence: float


@dataclass(slots=True)
class ForebetHistoricalMatchRow:
    """One historical match row extracted from a Forebet detail section."""

    source: str
    sport: str
    match_url: str
    section_name: str
    section_team: str
    sequence_no: int
    event_date_text: str | None
    competition_tag: str | None
    home_team: str
    away_team: str
    score_text: str | None
    extra_score_text: str | None
    result_outcome: str | None
    result_class: str | None
    active_side: str | None
    detail_url: str | None
    raw_text: str
