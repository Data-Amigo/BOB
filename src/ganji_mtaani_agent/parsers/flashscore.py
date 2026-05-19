"""Flashscore score parser.

This parser reads Flashscore event rows from the rendered DOM structure instead
of flattened page text. The page groups league headers and match rows as sibling
elements inside `div.sportName` containers, which gives us a stable V1 path.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.models.flashscore import FlashscoreScoreRow


DATE_HEADER_RE = re.compile(r"^\d{2}/\d{2}(?:/\d{4})?\s+[A-Z]{2}$")
LEAGUE_HEADER_RE = re.compile(r"^(?P<league>.+?)\s+(?P<country>[A-Z][A-Z .&'-]+)\s*:\s*(?:.+)?$")


def _clean_text(value: str) -> str:
    """Normalize whitespace inside a text fragment."""

    return re.sub(r"\s+", " ", value).strip()


def _class_contains(tag, fragment: str) -> bool:
    """Return True when any class name on a tag contains the given fragment."""

    classes = tag.get("class", [])
    return any(fragment in class_name for class_name in classes)


def _to_int(value: str | None) -> int | None:
    """Convert a score-like string to int when possible."""

    if value in (None, "", "-"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_page_date(soup: BeautifulSoup) -> str | None:
    """Return the first visible date header on the page when present."""

    day_picker = soup.select_one("[data-testid='wcl-dayPickerButton']")
    if day_picker:
        value = _clean_text(day_picker.get_text(" ", strip=True))
        if value:
            return value

    body_text = soup.get_text("\n", strip=True)
    for raw_line in body_text.splitlines():
        line = _clean_text(raw_line)
        if DATE_HEADER_RE.fullmatch(line):
            return line
    return None


def _parse_league_header(header_text: str) -> tuple[str, str | None]:
    """Split a Flashscore league header into league and country/region."""

    normalized = _clean_text(header_text)
    match = LEAGUE_HEADER_RE.fullmatch(normalized)
    if not match:
        return normalized, None
    return match.group("league").strip(), match.group("country").strip()


def _extract_status(row) -> str:
    """Extract a readable match status from one event row."""

    stage = row.select_one(".event__stage")
    if stage:
        return _clean_text(stage.get_text(" ", strip=True))

    preview = row.select_one(".icon--preview")
    if preview:
        return "Preview"

    time_cell = row.select_one(".event__time")
    if time_cell:
        return "Scheduled"

    return "Unknown"


def _extract_time_text(row) -> str | None:
    """Extract visible kickoff/status time text when present."""

    time_cell = row.select_one(".event__time")
    if time_cell:
        value = _clean_text(time_cell.get_text(" ", strip=True))
        return value or None
    return None


def _extract_team_name(row, selectors: tuple[str, ...]) -> str | None:
    """Extract a team name from one of several possible participant selectors."""

    for selector in selectors:
        node = row.select_one(selector)
        if not node:
            continue
        value = _clean_text(node.get_text(" ", strip=True))
        if value:
            return value
    return None


def _extract_score(row, selector: str) -> int | None:
    """Extract a score value from a Flashscore score element."""

    node = row.select_one(selector)
    if not node:
        return None
    return _to_int(_clean_text(node.get_text(" ", strip=True)))


def _parse_sport_container(container, *, sport: str, page_date_text: str | None) -> list[FlashscoreScoreRow]:
    """Parse one Flashscore sport container into structured rows."""

    parsed_rows: list[FlashscoreScoreRow] = []
    current_league: str | None = None
    current_country: str | None = None

    for child in container.find_all(recursive=False):
        if _class_contains(child, "headerLeague__wrapper"):
            current_league, current_country = _parse_league_header(child.get_text(" ", strip=True))
            continue

        if not _class_contains(child, "event__match"):
            continue

        if current_league is None:
            continue

        home_team = _extract_team_name(child, (".event__homeParticipant", ".event__participant--home"))
        away_team = _extract_team_name(child, (".event__awayParticipant", ".event__participant--away"))
        if not home_team or not away_team:
            continue

        status = _extract_status(child)
        event_time_text = _extract_time_text(child)
        home_score = _extract_score(child, ".event__score--home")
        away_score = _extract_score(child, ".event__score--away")

        confidence = 0.95
        if home_score is None and away_score is None and status not in {"Scheduled", "Preview"}:
            confidence = 0.8

        parsed_rows.append(
            FlashscoreScoreRow(
                source="flashscore",
                sport=sport,
                page_date_text=page_date_text,
                country_or_region=current_country,
                league=current_league,
                match_status=status,
                event_time_text=event_time_text,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                raw_text=_clean_text(child.get_text(" ", strip=True)),
                confidence=confidence,
            )
        )

    return parsed_rows


def _parse_flashscore_rows(html: str, sport: str) -> list[FlashscoreScoreRow]:
    """Parse Flashscore rendered HTML into structured score rows."""

    soup = BeautifulSoup(html, "html.parser")
    page_date_text = _find_page_date(soup)
    containers = soup.select("div.sportName")
    if not containers:
        return []

    parsed_rows: list[FlashscoreScoreRow] = []

    for container in containers:
        parsed_rows.extend(_parse_sport_container(container, sport=sport, page_date_text=page_date_text))

    return parsed_rows


def parse_flashscore_football(html: str) -> list[FlashscoreScoreRow]:
    """Parse Flashscore football score rows from rendered HTML."""

    return _parse_flashscore_rows(html, sport="football")


def parse_flashscore_basketball(html: str) -> list[FlashscoreScoreRow]:
    """Parse Flashscore basketball score rows from rendered HTML."""

    return _parse_flashscore_rows(html, sport="basketball")
