"""This is the mozzart.py parser file.

Author: Data-Amigo
Date: 2026-05-02
Description:
This parser module extracts the first stable football and basketball odds
fields from the rendered Mozzart prematch page HTML. The page is mobile-
oriented, so the V1 parser intentionally works from the rendered body text
sequence rather than fragile selectors.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ganji_mtaani_agent.models.mozzart import MozzartBasketballOdds, MozzartFootballOdds


# =============================================================================
# Small Conversion Helpers
# =============================================================================
def _to_float(value: str) -> float | None:
    """Convert a token to float when possible."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_from_plus(value: str) -> int | None:
    """Convert a token like '+224' into the integer 224 when possible."""

    match = re.fullmatch(r"\+(\d+)", value.strip())
    if not match:
        return None
    return int(match.group(1))


def _clean_line(value: str) -> str:
    """Normalize whitespace inside a text line."""

    return re.sub(r"\s+", " ", value).strip()


def _extract_text_lines(html: str) -> list[str]:
    """Extract non-empty rendered text lines from HTML."""

    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text("\n", strip=True)
    return [_clean_line(line) for line in raw_text.splitlines() if _clean_line(line)]


def _looks_like_league_label(value: str) -> bool:
    """Return True when a line looks like a Mozzart league label."""

    return bool(re.fullmatch(r"[A-Za-z&.'\- ]+(?:\.\.\.)?(?:\s+\d+)?(?:\s+[A-Za-z]+(?:\s+[A-Za-z]+)*)?", value))


def _looks_like_datetime(value: str) -> bool:
    """Return True when a line looks like a Mozzart prematch datetime token."""

    return bool(re.fullmatch(r"\d{2}\.\d{2}\. [A-Za-z]{3} \d{2}:\d{2}", value))


# =============================================================================
# Prematch Row Parsing
# =============================================================================
def _parse_prematch_rows(html: str, sport: str) -> list[dict[str, object]]:
    """Parse repeated Mozzart prematch rows for a given sport page."""

    lines = _extract_text_lines(html)
    if not lines:
        return []

    try:
        start_index = next(i for i, line in enumerate(lines) if line.startswith("Highlights -")) + 1
    except StopIteration:
        return []

    index = start_index
    parsed_rows: list[dict[str, object]] = []

    while index < len(lines):
        line = lines[index]

        if line.startswith("Go To Mobile Plus") or line.startswith("Mobile Plus") or line.startswith("T SPORTS"):
            break

        if index + 11 >= len(lines):
            break

        if not _looks_like_league_label(line):
            index += 1
            continue

        game_id = lines[index + 1]
        event_datetime_text = lines[index + 2]
        home_team = lines[index + 3]
        away_team = lines[index + 4]
        extra_market_count = _to_int_from_plus(lines[index + 5])

        if not game_id.isdigit() or not _looks_like_datetime(event_datetime_text):
            index += 1
            continue

        if lines[index + 6] != "1" or lines[index + 8] != "X" or lines[index + 10] != "2":
            index += 1
            continue

        home_odds = _to_float(lines[index + 7])
        draw_odds = _to_float(lines[index + 9])
        away_odds = _to_float(lines[index + 11])

        if home_odds is None or draw_odds is None or away_odds is None:
            index += 1
            continue

        raw_tokens = lines[index : index + 12]
        parsed_rows.append(
            {
                "source": "mozzart",
                "sport": sport,
                "league": line,
                "event_datetime_text": event_datetime_text,
                "game_id": game_id,
                "home_team": home_team,
                "away_team": away_team,
                "match_status": None,
                "score_text": None,
                "extra_market_count": extra_market_count,
                "home_odds": home_odds,
                "draw_odds": draw_odds,
                "away_odds": away_odds,
                "raw_text": " | ".join(raw_tokens),
                "confidence": 0.95,
            }
        )
        index += 12

    return parsed_rows


# =============================================================================
# Main Mozzart Parsers
# =============================================================================
def parse_mozzart_football(html: str) -> list[MozzartFootballOdds]:
    """Parse Mozzart prematch football odds from rendered page HTML."""

    parsed_dicts = _parse_prematch_rows(html=html, sport="football")
    return [MozzartFootballOdds(**row) for row in parsed_dicts]


def parse_mozzart_basketball(html: str) -> list[MozzartBasketballOdds]:
    """Parse Mozzart prematch basketball odds from rendered page HTML."""

    parsed_dicts = _parse_prematch_rows(html=html, sport="basketball")
    return [MozzartBasketballOdds(**row) for row in parsed_dicts]
