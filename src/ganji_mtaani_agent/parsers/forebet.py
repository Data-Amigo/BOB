"""This is the forebet.py parser file.

Author: Data-Amigo
Date: 2026-04-29
Description:
This parser module extracts the first stable basketball and football prediction
fields from saved Forebet HTML snapshots. It intentionally focuses on the stable
core fields first and stores the rest of the row in remaining_tokens for later
refinement.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.models.forebet import (
    ForebetHistoricalAnalysis,
    ForebetHistoricalMatchRow,
    ForebetBasketballResult,
    ForebetBasketballPrediction,
    ForebetFootballResult,
    ForebetFootballPrediction,
)


# =============================================================================
# Basketball Row Parsing Constants
# =============================================================================
# These positions represent the stable part of the Forebet basketball row that
# we have already inspected manually from the saved snapshot.
BASKETBALL_LEAGUE_INDEX = 0
BASKETBALL_HOME_TEAM_INDEX = 1
BASKETBALL_AWAY_TEAM_INDEX = 2
BASKETBALL_EVENT_DATETIME_INDEX = 3
BASKETBALL_PROB_1_INDEX = 4
BASKETBALL_PROB_2_INDEX = 5
BASKETBALL_PRED_OUTCOME_INDEX = 6
BASKETBALL_PREDICTED_HOME_SCORE_INDEX = 7
BASKETBALL_DASH_SEPARATOR_INDEX = 8
BASKETBALL_PREDICTED_AWAY_SCORE_INDEX = 9
BASKETBALL_AVG_POINTS_INDEX = 12
BASKETBALL_COEF_1_INDEX = 13
BASKETBALL_COEF_2_INDEX = 14
BASKETBALL_COEF_3_INDEX = 15
BASKETBALL_MINIMUM_EXPECTED_TOKENS = 16


# =============================================================================
# Football Row Parsing Constants
# =============================================================================
# These positions represent the stable part of the Forebet football row that we
# inspected manually from the saved football snapshot.
FOOTBALL_LEAGUE_INDEX = 0
FOOTBALL_HOME_TEAM_INDEX = 1
FOOTBALL_AWAY_TEAM_INDEX = 2
FOOTBALL_EVENT_DATETIME_INDEX = 3
FOOTBALL_PROB_1_INDEX = 4
FOOTBALL_PROB_X_INDEX = 5
FOOTBALL_PROB_2_INDEX = 6
FOOTBALL_PRED_OUTCOME_INDEX = 7
FOOTBALL_PREDICTED_HOME_SCORE_INDEX = 8
FOOTBALL_DASH_SEPARATOR_INDEX = 9
FOOTBALL_PREDICTED_AWAY_SCORE_INDEX = 10
FOOTBALL_CORRECT_SCORE_TEXT_INDEX = 11
FOOTBALL_AVG_GOALS_INDEX = 12
FOOTBALL_WEATHER_INDEX = 13
FOOTBALL_COEF_1_INDEX = 14
FOOTBALL_COEF_X_INDEX = 15
FOOTBALL_COEF_2_INDEX = 16
FOOTBALL_COEF_EXTRA_INDEX = 17
FOOTBALL_MINIMUM_EXPECTED_TOKENS = 18


# =============================================================================
# Yesterday Result Row Parsing Constants
# =============================================================================
FOOTBALL_RESULT_STATUS_INDEX = 21
FOOTBALL_RESULT_ACTUAL_SCORE_INDEX = 22
FOOTBALL_RESULT_MINIMUM_EXPECTED_TOKENS = 23

BASKETBALL_RESULT_STATUS_INDEX = 24
BASKETBALL_RESULT_ACTUAL_HOME_SCORE_INDEX = 25
BASKETBALL_RESULT_ACTUAL_AWAY_SCORE_INDEX = 26
BASKETBALL_RESULT_MINIMUM_EXPECTED_TOKENS = 27


# =============================================================================
# Small Conversion Helpers
# =============================================================================
# These helpers keep the row parser readable and protect it from bad values.
def _to_int(value: str) -> int | None:
    """Convert a token to int when possible."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: str) -> float | None:
    """Convert a token to float when possible."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dash_score_text(score_text: str | None) -> tuple[int | None, int | None]:
    """Parse a dash-delimited score string such as '1 - 0'."""

    if not score_text:
        return None, None

    normalized = score_text.replace("(", "").replace(")", "").strip()
    if "-" not in normalized:
        return None, None

    left, right = [part.strip() for part in normalized.split("-", maxsplit=1)]
    return _to_int(left), _to_int(right)


def _derive_pred_indicator_class(row) -> str | None:
    """Extract Forebet's hit/miss CSS class from a row when present."""

    for element in row.select("[class]"):
        for class_name in element.get("class", []):
            if class_name in {"predict_y", "predict_no"}:
                return class_name
    return None


def _derive_hit_from_indicator(indicator_class: str | None) -> bool | None:
    """Map Forebet CSS indicator class to a boolean hit flag."""

    if indicator_class == "predict_y":
        return True
    if indicator_class == "predict_no":
        return False
    return None


def _derive_outcome_from_scores(home_score: int | None, away_score: int | None, *, allow_draw: bool) -> str | None:
    """Derive an outcome label from home and away scores."""

    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "1"
    if away_score > home_score:
        return "2"
    return "X" if allow_draw else None


def _clean_text(value: str | None) -> str:
    """Normalize whitespace in a free-text fragment."""

    return " ".join((value or "").split())


def _extract_competition_from_meta(soup: BeautifulSoup) -> str | None:
    """Extract the competition name from Forebet meta description text."""

    meta = soup.select_one("meta[name='description']")
    content = meta.get("content", "") if meta else ""
    content = _clean_text(content)
    if not content:
        return None

    patterns = (
        r"match of\s+(.+?)\s+on\s",
        r"on\s+\d{1,2}/\d{1,2}/\d{4}\s+of\s+(.+?)(?:\.|$)",
        r"of\s+(.+?)(?:\.|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)
        if match:
            return _clean_text(match.group(1))
    return None


def _extract_form_sequences(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract top-level recent form sequences for both teams."""

    sequences: list[str] = []

    for block in soup.select("div.prformcont")[:2]:
        letters = [
            _clean_text(node.get_text(" ", strip=True))
            for node in block.find_all(["span", "b"], recursive=False)
            if _clean_text(node.get_text(" ", strip=True))
        ]
        if not letters:
            letters = [
                _clean_text(node.get_text(" ", strip=True))
                for node in block.select("span, b")
                if _clean_text(node.get_text(" ", strip=True))
            ]
        sequences.append(" ".join(letters) if letters else "")

    while len(sequences) < 2:
        sequences.append("")

    return sequences[0] or None, sequences[1] or None


def _score_text_from_spans(node) -> str | None:
    """Build a score string from child spans when they exist."""

    if node is None:
        return None
    parts = [_clean_text(span.get_text(" ", strip=True)) for span in node.select("span")]
    parts = [part for part in parts if part]
    if len(parts) >= 2:
        return f"{parts[0]} - {parts[1]}"
    if parts:
        return " ".join(parts)
    text = _clean_text(node.get_text(" ", strip=True))
    return text or None


def _resolve_detail_url(href: str | None) -> str | None:
    """Convert a Forebet relative URL into an absolute URL when possible."""

    if not href:
        return None
    href = href.strip().replace("\n", "")
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"https://www.forebet.com{href}"
    return f"https://www.forebet.com/{href.lstrip('/')}"


def _extract_match_url_from_row(row) -> str | None:
    """Extract the Forebet match-detail URL from one result or prediction row."""

    link = row.select_one("a.tnmscn[href]")
    if link is None:
        return None
    return _resolve_detail_url(link.get("href"))


def _map_result_class_to_outcome(result_class: str | None) -> str | None:
    """Map Forebet row result CSS classes to W/D/L values."""

    if result_class == "winres" or result_class == "st_winres":
        return "W"
    if result_class == "loseres" or result_class == "st_lostres":
        return "L"
    if result_class == "drawres":
        return "D"
    return None


# =============================================================================
# Row Tokenizers
# =============================================================================
# Each Forebet row is flattened into pipe-separated text before structured parsing.
def tokenize_basketball_row_text(row_text: str) -> list[str]:
    """Split one Forebet basketball row into cleaned text tokens."""

    return [token.strip() for token in row_text.split("|") if token.strip()]


def tokenize_football_row_text(row_text: str) -> list[str]:
    """Split one Forebet football row into cleaned text tokens."""

    return [token.strip() for token in row_text.split("|") if token.strip()]


# =============================================================================
# Single Basketball Row Parser
# =============================================================================
# This function parses only the stable basketball row core that we understand today.
# It ignores the dash token and stores everything after the stable core in
# remaining_tokens for later work.
def parse_basketball_row(row_text: str, *, match_url: str | None = None) -> ForebetBasketballPrediction | None:
    """Parse one flattened Forebet basketball row into a model object."""

    tokens = tokenize_basketball_row_text(row_text)
    if len(tokens) < BASKETBALL_MINIMUM_EXPECTED_TOKENS:
        return None

    if tokens[BASKETBALL_DASH_SEPARATOR_INDEX] != "-":
        confidence = 0.75
    else:
        confidence = 1.0

    return ForebetBasketballPrediction(
        source="forebet",
        sport="basketball",
        league=tokens[BASKETBALL_LEAGUE_INDEX],
        home_team=tokens[BASKETBALL_HOME_TEAM_INDEX],
        away_team=tokens[BASKETBALL_AWAY_TEAM_INDEX],
        match_url=match_url,
        event_datetime=tokens[BASKETBALL_EVENT_DATETIME_INDEX],
        prob_1=_to_int(tokens[BASKETBALL_PROB_1_INDEX]),
        prob_2=_to_int(tokens[BASKETBALL_PROB_2_INDEX]),
        pred_outcome=tokens[BASKETBALL_PRED_OUTCOME_INDEX],
        predicted_home_score=_to_int(tokens[BASKETBALL_PREDICTED_HOME_SCORE_INDEX]),
        predicted_away_score=_to_int(tokens[BASKETBALL_PREDICTED_AWAY_SCORE_INDEX]),
        avg_points=_to_float(tokens[BASKETBALL_AVG_POINTS_INDEX]),
        coef_1=_to_float(tokens[BASKETBALL_COEF_1_INDEX]),
        coef_2=_to_float(tokens[BASKETBALL_COEF_2_INDEX]),
        coef_3=_to_float(tokens[BASKETBALL_COEF_3_INDEX]),
        remaining_tokens=tokens[16:],
        raw_text=row_text,
        confidence=confidence,
    )


# =============================================================================
# Single Football Row Parser
# =============================================================================
# This function parses only the stable football row core that we understand today.
# It keeps the uncertain live-state and extra values in remaining_tokens.
def parse_football_row(row_text: str, *, match_url: str | None = None) -> ForebetFootballPrediction | None:
    """Parse one flattened Forebet football row into a model object."""

    tokens = tokenize_football_row_text(row_text)
    if len(tokens) < FOOTBALL_MINIMUM_EXPECTED_TOKENS:
        return None

    if tokens[FOOTBALL_DASH_SEPARATOR_INDEX] != "-":
        confidence = 0.75
    else:
        confidence = 1.0

    return ForebetFootballPrediction(
        source="forebet",
        sport="football",
        league=tokens[FOOTBALL_LEAGUE_INDEX],
        home_team=tokens[FOOTBALL_HOME_TEAM_INDEX],
        away_team=tokens[FOOTBALL_AWAY_TEAM_INDEX],
        match_url=match_url,
        event_datetime=tokens[FOOTBALL_EVENT_DATETIME_INDEX],
        prob_1=_to_int(tokens[FOOTBALL_PROB_1_INDEX]),
        prob_x=_to_int(tokens[FOOTBALL_PROB_X_INDEX]),
        prob_2=_to_int(tokens[FOOTBALL_PROB_2_INDEX]),
        pred_outcome=tokens[FOOTBALL_PRED_OUTCOME_INDEX],
        predicted_home_score=_to_int(tokens[FOOTBALL_PREDICTED_HOME_SCORE_INDEX]),
        predicted_away_score=_to_int(tokens[FOOTBALL_PREDICTED_AWAY_SCORE_INDEX]),
        correct_score_text=tokens[FOOTBALL_CORRECT_SCORE_TEXT_INDEX],
        avg_goals=_to_float(tokens[FOOTBALL_AVG_GOALS_INDEX]),
        weather=tokens[FOOTBALL_WEATHER_INDEX],
        coef_1=_to_float(tokens[FOOTBALL_COEF_1_INDEX]),
        coef_x=_to_float(tokens[FOOTBALL_COEF_X_INDEX]),
        coef_2=_to_float(tokens[FOOTBALL_COEF_2_INDEX]),
        coef_extra=_to_float(tokens[FOOTBALL_COEF_EXTRA_INDEX]),
        remaining_tokens=tokens[18:],
        raw_text=row_text,
        confidence=confidence,
    )


def parse_football_result_row(row) -> ForebetFootballResult | None:
    """Parse one Forebet football yesterday row into a result model object."""

    row_text = row.get_text(" | ", strip=True)
    match_url = _extract_match_url_from_row(row)
    tokens = tokenize_football_row_text(row_text)
    if len(tokens) < FOOTBALL_RESULT_MINIMUM_EXPECTED_TOKENS:
        return None

    indicator_class = _derive_pred_indicator_class(row)
    actual_home_score, actual_away_score = _parse_dash_score_text(tokens[FOOTBALL_RESULT_ACTUAL_SCORE_INDEX])
    actual_outcome = _derive_outcome_from_scores(actual_home_score, actual_away_score, allow_draw=True)
    derived_pred_hit = None
    if tokens[FOOTBALL_PRED_OUTCOME_INDEX] and actual_outcome:
        derived_pred_hit = tokens[FOOTBALL_PRED_OUTCOME_INDEX] == actual_outcome

    indicator_pred_hit = _derive_hit_from_indicator(indicator_class)
    pred_hit = derived_pred_hit if derived_pred_hit is not None else indicator_pred_hit
    confidence = 1.0 if pred_hit == indicator_pred_hit or indicator_pred_hit is None else 0.9

    return ForebetFootballResult(
        source="forebet",
        sport="football",
        league=tokens[FOOTBALL_LEAGUE_INDEX],
        home_team=tokens[FOOTBALL_HOME_TEAM_INDEX],
        away_team=tokens[FOOTBALL_AWAY_TEAM_INDEX],
        match_url=match_url,
        event_datetime=tokens[FOOTBALL_EVENT_DATETIME_INDEX],
        prob_1=_to_int(tokens[FOOTBALL_PROB_1_INDEX]),
        prob_x=_to_int(tokens[FOOTBALL_PROB_X_INDEX]),
        prob_2=_to_int(tokens[FOOTBALL_PROB_2_INDEX]),
        pred_outcome=tokens[FOOTBALL_PRED_OUTCOME_INDEX],
        predicted_home_score=_to_int(tokens[FOOTBALL_PREDICTED_HOME_SCORE_INDEX]),
        predicted_away_score=_to_int(tokens[FOOTBALL_PREDICTED_AWAY_SCORE_INDEX]),
        predicted_score_text=tokens[FOOTBALL_CORRECT_SCORE_TEXT_INDEX],
        actual_home_score=actual_home_score,
        actual_away_score=actual_away_score,
        actual_score_text=tokens[FOOTBALL_RESULT_ACTUAL_SCORE_INDEX],
        actual_outcome=actual_outcome,
        status=tokens[FOOTBALL_RESULT_STATUS_INDEX],
        pred_hit=pred_hit,
        pred_indicator_class=indicator_class,
        raw_text=row_text,
        confidence=confidence,
    )


def parse_basketball_result_row(row) -> ForebetBasketballResult | None:
    """Parse one Forebet basketball yesterday row into a result model object."""

    row_text = row.get_text(" | ", strip=True)
    match_url = _extract_match_url_from_row(row)
    tokens = tokenize_basketball_row_text(row_text)
    if len(tokens) < BASKETBALL_RESULT_MINIMUM_EXPECTED_TOKENS:
        return None

    indicator_class = _derive_pred_indicator_class(row)
    actual_home_score = _to_int(tokens[BASKETBALL_RESULT_ACTUAL_HOME_SCORE_INDEX])
    actual_away_score = _to_int(tokens[BASKETBALL_RESULT_ACTUAL_AWAY_SCORE_INDEX])
    actual_outcome = _derive_outcome_from_scores(actual_home_score, actual_away_score, allow_draw=False)
    derived_pred_hit = None
    if tokens[BASKETBALL_PRED_OUTCOME_INDEX] and actual_outcome:
        derived_pred_hit = tokens[BASKETBALL_PRED_OUTCOME_INDEX] == actual_outcome

    indicator_pred_hit = _derive_hit_from_indicator(indicator_class)
    pred_hit = derived_pred_hit if derived_pred_hit is not None else indicator_pred_hit
    confidence = 1.0 if pred_hit == indicator_pred_hit or indicator_pred_hit is None else 0.9

    return ForebetBasketballResult(
        source="forebet",
        sport="basketball",
        league=tokens[BASKETBALL_LEAGUE_INDEX],
        home_team=tokens[BASKETBALL_HOME_TEAM_INDEX],
        away_team=tokens[BASKETBALL_AWAY_TEAM_INDEX],
        match_url=match_url,
        event_datetime=tokens[BASKETBALL_EVENT_DATETIME_INDEX],
        prob_1=_to_int(tokens[BASKETBALL_PROB_1_INDEX]),
        prob_2=_to_int(tokens[BASKETBALL_PROB_2_INDEX]),
        pred_outcome=tokens[BASKETBALL_PRED_OUTCOME_INDEX],
        predicted_home_score=_to_int(tokens[BASKETBALL_PREDICTED_HOME_SCORE_INDEX]),
        predicted_away_score=_to_int(tokens[BASKETBALL_PREDICTED_AWAY_SCORE_INDEX]),
        predicted_score_text=f"{tokens[10]} - {tokens[11]}" if len(tokens) > 11 else None,
        actual_home_score=actual_home_score,
        actual_away_score=actual_away_score,
        actual_score_text=f"{tokens[BASKETBALL_RESULT_ACTUAL_HOME_SCORE_INDEX]} - {tokens[BASKETBALL_RESULT_ACTUAL_AWAY_SCORE_INDEX]}",
        actual_outcome=actual_outcome,
        status=tokens[BASKETBALL_RESULT_STATUS_INDEX],
        pred_hit=pred_hit,
        pred_indicator_class=indicator_class,
        raw_text=row_text,
        confidence=confidence,
    )


# =============================================================================
# Basketball Snapshot Parser
# =============================================================================
def parse_forebet_basketball(html: str) -> list[ForebetBasketballPrediction]:
    """Parse Forebet basketball predictions from a saved HTML snapshot."""

    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.schema.tbuo.tbbsk")
    if container is None:
        return []

    predictions: list[ForebetBasketballPrediction] = []

    for row in container.select("div.rcnt"):
        row_text = row.get_text(" | ", strip=True)
        parsed = parse_basketball_row(row_text, match_url=_extract_match_url_from_row(row))
        if parsed is not None:
            predictions.append(parsed)

    return predictions


# =============================================================================
# Football Snapshot Parser
# =============================================================================
def parse_forebet_football(html: str) -> list[ForebetFootballPrediction]:
    """Parse Forebet football predictions from a saved HTML snapshot."""

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.rcnt")
    if not rows:
        return []

    predictions: list[ForebetFootballPrediction] = []

    for row in rows:
        row_text = row.get_text(" | ", strip=True)
        parsed = parse_football_row(row_text, match_url=_extract_match_url_from_row(row))
        if parsed is not None:
            predictions.append(parsed)

    return predictions


def parse_forebet_football_yesterday(html: str) -> list[ForebetFootballResult]:
    """Parse Forebet football results from the yesterday page HTML."""

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.rcnt")
    if not rows:
        return []

    results: list[ForebetFootballResult] = []

    for row in rows:
        parsed = parse_football_result_row(row)
        if parsed is not None:
            results.append(parsed)

    return results


def parse_forebet_basketball_yesterday(html: str) -> list[ForebetBasketballResult]:
    """Parse Forebet basketball results from the yesterday page HTML."""

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.rcnt")
    if not rows:
        return []

    results: list[ForebetBasketballResult] = []

    for row in rows:
        parsed = parse_basketball_result_row(row)
        if parsed is not None:
            results.append(parsed)

    return results


def _parse_forebet_football_summary(soup: BeautifulSoup, *, match_url: str) -> ForebetHistoricalAnalysis | None:
    """Parse the summary block from a Forebet football detail page."""

    row = soup.select_one("div.hdrtb.prblh.tb1x2 ~ div.rcnt")
    if row is None:
        row = soup.select_one("div.rcnt")
    if row is None:
        return None

    home_team = _clean_text(row.select_one(".homeTeam").get_text(" ", strip=True)) if row.select_one(".homeTeam") else None
    away_team = _clean_text(row.select_one(".awayTeam").get_text(" ", strip=True)) if row.select_one(".awayTeam") else None
    if not home_team or not away_team:
        return None

    pred_outcome = _clean_text(row.select_one(".predict .forepr span").get_text(" ", strip=True)) if row.select_one(".predict .forepr span") else None
    predicted_score_text = _clean_text(row.select_one(".ex_sc.tabonly").get_text(" ", strip=True)) if row.select_one(".ex_sc.tabonly") else None
    event_datetime = _clean_text(row.select_one(".date_bah").get_text(" ", strip=True)) if row.select_one(".date_bah") else None
    league_code = _clean_text(row.select_one(".shortTag").get_text(" ", strip=True)) if row.select_one(".shortTag") else None

    status_node = row.select_one(".lscr_td .mprv")
    actual_status = _clean_text(status_node.get_text(" ", strip=True)) if status_node else None
    score_node = row.select_one(".lscr_td .l_scr")
    actual_score_text = _clean_text(score_node.get_text(" ", strip=True)) if score_node else None
    if not actual_score_text:
        actual_score_text = _score_text_from_spans(row.select_one(".lscr_td .fj_column"))

    home_form_sequence, away_form_sequence = _extract_form_sequences(soup)

    return ForebetHistoricalAnalysis(
        source="forebet",
        sport="football",
        match_url=match_url,
        competition=_extract_competition_from_meta(soup),
        league_code=league_code or None,
        event_datetime=event_datetime,
        home_team=home_team,
        away_team=away_team,
        pred_outcome=pred_outcome or None,
        predicted_score_text=predicted_score_text or None,
        actual_score_text=actual_score_text or None,
        actual_status=actual_status or None,
        home_form_sequence=home_form_sequence,
        away_form_sequence=away_form_sequence,
        confidence=0.95,
    )


def _parse_forebet_basketball_summary(soup: BeautifulSoup, *, match_url: str) -> ForebetHistoricalAnalysis | None:
    """Parse the summary block from a Forebet basketball detail page."""

    row = soup.select_one("div.rcnt")
    if row is None:
        return None

    home_team = _clean_text(row.select_one(".homeTeam").get_text(" ", strip=True)) if row.select_one(".homeTeam") else None
    away_team = _clean_text(row.select_one(".awayTeam").get_text(" ", strip=True)) if row.select_one(".awayTeam") else None
    if not home_team or not away_team:
        return None

    pred_wrapper = row.select_one(".predict_y, .predict_no, .predict")
    pred_outcome = _clean_text(pred_wrapper.select_one(".forepr span").get_text(" ", strip=True)) if pred_wrapper and pred_wrapper.select_one(".forepr span") else None
    predicted_score_text = _score_text_from_spans(row.select_one(".ex_sc.tabonly"))
    actual_score_text = _score_text_from_spans(row.select_one(".lscr_td .fj_column"))
    actual_status = _clean_text(row.select_one(".lmin_td .scoreLnk").get_text(" ", strip=True)) if row.select_one(".lmin_td .scoreLnk") else None
    event_datetime = _clean_text(row.select_one(".date_bah").get_text(" ", strip=True)) if row.select_one(".date_bah") else None
    league_code = _clean_text(row.select_one(".shortTag").get_text(" ", strip=True)) if row.select_one(".shortTag") else None
    home_form_sequence, away_form_sequence = _extract_form_sequences(soup)

    return ForebetHistoricalAnalysis(
        source="forebet",
        sport="basketball",
        match_url=match_url,
        competition=_extract_competition_from_meta(soup),
        league_code=league_code or None,
        event_datetime=event_datetime,
        home_team=home_team,
        away_team=away_team,
        pred_outcome=pred_outcome or None,
        predicted_score_text=predicted_score_text or None,
        actual_score_text=actual_score_text or None,
        actual_status=actual_status or None,
        home_form_sequence=home_form_sequence,
        away_form_sequence=away_form_sequence,
        confidence=0.95,
    )


def _parse_football_section_title(header) -> str:
    """Return the visible football section title from a module header."""

    direct_children = header.find_all("div", recursive=False)
    if direct_children:
        return _clean_text(direct_children[-1].get_text(" ", strip=True))
    return _clean_text(header.get_text(" ", strip=True))


def _parse_forebet_football_history_rows(
    soup: BeautifulSoup,
    *,
    match_url: str,
    home_team: str,
    away_team: str,
) -> list[ForebetHistoricalMatchRow]:
    """Parse football history sections into normalized rows."""

    rows: list[ForebetHistoricalMatchRow] = []
    last_six_index = 0

    for module in soup.select("div.moduletable"):
        header = module.select_one("div.mptlt")
        if header is None:
            continue

        title = _parse_football_section_title(header).casefold()
        section_name: str | None = None
        section_team: str | None = None
        if title == "last 6 matches":
            last_six_index += 1
            section_name = "last_6_matches"
            section_team = home_team if last_six_index == 1 else away_team
        elif title == "home matches":
            section_name = "home_matches"
            section_team = home_team
        elif title == "away matches":
            section_name = "away_matches"
            section_team = away_team
        else:
            continue

        for sequence_no, row in enumerate(module.select("div.st_row"), start=1):
            date_parts = [_clean_text(part.get_text(" ", strip=True)) for part in row.select(".st_date > div")]
            date_parts = [part for part in date_parts if part]
            event_date_text = "/".join(date_parts) if len(date_parts) == 2 else " ".join(date_parts) or None

            home_node = row.select_one(".st_hteam")
            away_node = row.select_one(".st_ateam")
            score_node = row.select_one(".st_res")
            half_node = row.select_one(".st_htscr")
            result_node = row.select_one(".st_rescnt")
            league_node = row.select_one(".st_ltag")
            detail_link = row.select_one("a.stat_link[href]")

            home_name = _clean_text(home_node.get_text(" ", strip=True)) if home_node else ""
            away_name = _clean_text(away_node.get_text(" ", strip=True)) if away_node else ""
            if not home_name or not away_name:
                continue

            result_class = None
            if result_node:
                for class_name in result_node.get("class", []):
                    if class_name in {"winres", "loseres", "drawres"}:
                        result_class = class_name
                        break

            active_side = None
            if home_node and "active-team" in home_node.get("class", []):
                active_side = "home"
            elif away_node and "active-team" in away_node.get("class", []):
                active_side = "away"

            rows.append(
                ForebetHistoricalMatchRow(
                    source="forebet",
                    sport="football",
                    match_url=match_url,
                    section_name=section_name,
                    section_team=section_team,
                    sequence_no=sequence_no,
                    event_date_text=event_date_text,
                    competition_tag=_clean_text(league_node.get_text(" ", strip=True)) if league_node else None,
                    home_team=home_name,
                    away_team=away_name,
                    score_text=_clean_text(score_node.get_text(" ", strip=True)) if score_node else None,
                    extra_score_text=_clean_text(half_node.get_text(" ", strip=True)) if half_node else None,
                    result_outcome=_map_result_class_to_outcome(result_class),
                    result_class=result_class,
                    active_side=active_side,
                    detail_url=_resolve_detail_url(detail_link.get("href")) if detail_link else None,
                    raw_text=_clean_text(row.get_text(" ", strip=True)),
                )
            )

    return rows


def _extract_basketball_section_name_and_team(title: str) -> tuple[str | None, str | None]:
    """Split a basketball historical section title into section kind and team."""

    normalized = _clean_text(title)
    for suffix, section_name in (
        ("Last 6 matches", "last_6_matches"),
        ("home matches", "home_matches"),
        ("away matches", "away_matches"),
    ):
        if normalized.endswith(suffix):
            section_team = _clean_text(normalized[: -len(suffix)])
            return section_name, section_team
    return None, None


def _parse_basketball_quarter_text(row) -> str | None:
    """Convert basketball quarter spans into a compact summary string."""

    quarter_rows = row.select(".ov_gp .fj_between")
    if not quarter_rows:
        return None

    chunks: list[str] = []
    for index, quarter_row in enumerate(quarter_rows, start=1):
        values = [_clean_text(span.get_text(" ", strip=True)) for span in quarter_row.select("span")]
        values = [value for value in values if value]
        if len(values) >= 2:
            chunks.append(f"Q{index}: {'-'.join(values[:2])}")
    return " | ".join(chunks) if chunks else None


def _parse_forebet_basketball_history_rows(
    soup: BeautifulSoup,
    *,
    match_url: str,
) -> list[ForebetHistoricalMatchRow]:
    """Parse basketball history sections into normalized rows."""

    rows: list[ForebetHistoricalMatchRow] = []

    for wrapper in soup.select("div.mmatches_mc div.mx-width_hc"):
        title_node = wrapper.select_one(".st_minih span")
        if title_node is None:
            continue

        section_name, section_team = _extract_basketball_section_name_and_team(title_node.get_text(" ", strip=True))
        if not section_name or not section_team:
            continue

        for sequence_no, row in enumerate(wrapper.select("div.ov_row"), start=1):
            date_parts = [_clean_text(part.get_text(" ", strip=True)) for part in row.select(".st_dt")]
            date_parts = [part for part in date_parts if part]
            event_date_text = "/".join(date_parts) if len(date_parts) == 2 else " ".join(date_parts) or None

            team_spans = row.select(".st_tnames > span")
            if len(team_spans) < 2:
                continue

            home_name = _clean_text(team_spans[0].get_text(" ", strip=True))
            away_name = _clean_text(team_spans[1].get_text(" ", strip=True))
            active_side = "home" if "st_bold" in team_spans[0].get("class", []) else "away" if "st_bold" in team_spans[1].get("class", []) else None

            score_spans = row.select(".sm_btn > span")
            score_values = [_clean_text(span.get_text(" ", strip=True)) for span in score_spans if _clean_text(span.get_text(" ", strip=True))]
            score_text = f"{score_values[0]} - {score_values[1]}" if len(score_values) >= 2 else None

            result_button = row.select_one(".sm_btn")
            result_class = None
            if result_button:
                for class_name in result_button.get("class", []):
                    if class_name in {"st_winres", "st_lostres"}:
                        result_class = class_name
                        break

            rows.append(
                ForebetHistoricalMatchRow(
                    source="forebet",
                    sport="basketball",
                    match_url=match_url,
                    section_name=section_name,
                    section_team=section_team,
                    sequence_no=sequence_no,
                    event_date_text=event_date_text,
                    competition_tag=None,
                    home_team=home_name,
                    away_team=away_name,
                    score_text=score_text,
                    extra_score_text=_parse_basketball_quarter_text(row),
                    result_outcome=_map_result_class_to_outcome(result_class),
                    result_class=result_class,
                    active_side=active_side,
                    detail_url=None,
                    raw_text=_clean_text(row.get_text(" ", strip=True)),
                )
            )

    return rows


def parse_forebet_football_historical_page(
    html: str,
    *,
    match_url: str,
) -> tuple[ForebetHistoricalAnalysis | None, list[ForebetHistoricalMatchRow]]:
    """Parse one Forebet football match-detail page into summary + history rows."""

    soup = BeautifulSoup(html, "html.parser")
    analysis = _parse_forebet_football_summary(soup, match_url=match_url)
    if analysis is None:
        return None, []
    rows = _parse_forebet_football_history_rows(
        soup,
        match_url=match_url,
        home_team=analysis.home_team,
        away_team=analysis.away_team,
    )
    return analysis, rows


def parse_forebet_basketball_historical_page(
    html: str,
    *,
    match_url: str,
) -> tuple[ForebetHistoricalAnalysis | None, list[ForebetHistoricalMatchRow]]:
    """Parse one Forebet basketball match-detail page into summary + history rows."""

    soup = BeautifulSoup(html, "html.parser")
    analysis = _parse_forebet_basketball_summary(soup, match_url=match_url)
    if analysis is None:
        return None, []
    rows = _parse_forebet_basketball_history_rows(soup, match_url=match_url)
    return analysis, rows
