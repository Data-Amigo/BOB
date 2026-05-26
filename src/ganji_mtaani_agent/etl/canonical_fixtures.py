from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Iterable

from psycopg.rows import dict_row

from ganji_mtaani_agent.db import (
    get_postgres_connection,
    upsert_canonical_fixture,
    upsert_fixture_source_links,
)


SOURCE_TABLES: tuple[str, ...] = (
    "bookmaker_odds",
    "forebet_predictions",
    "forebet_results",
    "flashscore_results",
    "sports_results",
    "forebet_match_analyses",
)

TEAM_NAME_REPLACEMENTS = {
    "MAN UTD": "MANCHESTER UNITED",
    "MAN UNITED": "MANCHESTER UNITED",
    "MAN CITY": "MANCHESTER CITY",
    "PSG": "PARIS SAINT GERMAIN",
    "D R CONGO": "DR CONGO",
    "B MUNICH": "BAYERN",
    "BAYERN MUNICH": "BAYERN",
    "L RYTAS": "RYTAS",
    "NEW YORK LIBERTY": "NEW YORK LIBERTY W",
    "NY LIBERTY": "NEW YORK LIBERTY W",
    "LOS ANGELES SPARKS": "LOS ANGELES SPARKS W",
    "LA SPARKS": "LOS ANGELES SPARKS W",
    "TORONTO TEMPO": "TORONTO TEMPO W",
    "GOLDEN STATE VALKYRIES": "GOLDEN STATE VALKYRIES W",
    "CEZ NYMBURK": "NYMBURK",
    "PITESTI": "ARGES PITESTI",
    "ATLASSIB SIBIU": "CSU SIBIU",
    "TIMISOARA": "SCM TIMISOARA",
    "SCM UNIV CRAIOVA": "SCM CRAIOVA",
    "U BANCA TRANSILVANIA": "CLUJ NAPOCA",
    "CS VALCEA 1924 RM VALCEA": "VALCEA",
    "VALCEA 1924 RM VALCEA": "VALCEA",
}

TEAM_NAME_NOISE_TOKENS = {
    "FC",
    "FK",
    "NK",
    "BC",
    "BK",
    "KK",
    "KD",
    "CS",
    "CSO",
    "CF",
    "CD",
    "CB",
}

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True, slots=True)
class CanonicalBuildConfig:
    batch_date: date
    source_tables: tuple[str, ...] = SOURCE_TABLES
    limit_per_source: int = 500
    include_linked_rows: bool = False


@dataclass(slots=True)
class CanonicalCandidate:
    source_name: str
    source_table: str
    source_row_id: int
    source_run_id: int | None
    sport: str
    league: str | None
    home_team: str
    away_team: str
    source_event_date: date | None
    source_event_datetime_utc: datetime | None
    source_event_datetime_text: str | None
    source_event_time_text: str | None
    source_match_url: str | None
    source_status: str | None
    result_home_score: int | None
    result_away_score: int | None


def _normalize_whitespace(value: str | None) -> str:
    return " ".join((value or "").split())


def _strip_accents(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def normalize_team_name(value: str | None) -> str:
    """Normalize team text into a stable canonical key."""

    text = _normalize_whitespace(value).upper()
    text = _strip_accents(text)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = text.split()

    while len(parts) > 1 and parts[0] in TEAM_NAME_NOISE_TOKENS:
        parts = parts[1:]
    while len(parts) > 1 and parts[-1] in TEAM_NAME_NOISE_TOKENS:
        parts = parts[:-1]

    text = " ".join(parts)
    text = TEAM_NAME_REPLACEMENTS.get(text, text)
    return text


def _parse_time_fragment(value: str | None) -> time | None:
    if not value:
        return None
    text = _normalize_whitespace(value)
    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _parse_time_text(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2}:\d{2}(?:\s?[AP]M)?)", _normalize_whitespace(value), flags=re.IGNORECASE)
    return _normalize_whitespace(match.group(1)) if match else None


def _coerce_year(year_text: str | None, *, reference_year: int) -> int:
    if not year_text:
        return reference_year
    parsed_year = int(year_text)
    return 2000 + parsed_year if len(year_text) == 2 else parsed_year


def _parse_slash_date(
    value: str | None,
    *,
    default_order: str,
    reference_year: int,
) -> date | None:
    if not value:
        return None

    match = re.search(
        r"(?P<first>\d{1,2})/(?P<second>\d{1,2})(?:/(?P<year>\d{2,4}))?",
        _normalize_whitespace(value),
    )
    if not match:
        return None

    first = int(match.group("first"))
    second = int(match.group("second"))
    year = _coerce_year(match.group("year"), reference_year=reference_year)

    if default_order == "mdy":
        month, day = first, second
    else:
        day, month = first, second

    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_dot_date(value: str | None, *, reference_year: int) -> date | None:
    if not value:
        return None
    match = re.search(
        r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2,4}))?",
        _normalize_whitespace(value),
    )
    if not match:
        return None
    year = _coerce_year(match.group("year"), reference_year=reference_year)
    try:
        return date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _parse_forebet_datetime(value: str | None) -> tuple[date | None, datetime | None, str | None]:
    if not value:
        return None, None, None
    text = _normalize_whitespace(value)
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H.%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date(), parsed.replace(tzinfo=UTC), parsed.strftime("%H:%M")
        except ValueError:
            continue
    parsed_date = _parse_slash_date(text, default_order="dmy", reference_year=date.today().year)
    return parsed_date, None, _parse_time_text(text)


def _parse_flashscore_date(
    page_date_text: str | None,
    event_time_text: str | None,
    *,
    reference_year: int,
) -> tuple[date | None, datetime | None, str | None]:
    parsed_date = _parse_slash_date(page_date_text, default_order="dmy", reference_year=reference_year)
    parsed_time = _parse_time_fragment(event_time_text)
    if parsed_date and parsed_time:
        return parsed_date, datetime.combine(parsed_date, parsed_time, tzinfo=UTC), parsed_time.strftime("%H:%M")
    return parsed_date, None, _parse_time_text(event_time_text)


def _next_weekday(base_date: date, weekday: int) -> date:
    delta = (weekday - base_date.weekday()) % 7
    return base_date + timedelta(days=delta)


def _parse_relative_bookmaker_datetime(
    value: str | None,
    *,
    reference_date: date,
) -> tuple[date | None, datetime | None, str | None]:
    if not value:
        return None, None, None

    text = _normalize_whitespace(value)
    lower = text.casefold()
    explicit_date = _parse_slash_date(text, default_order="mdy", reference_year=reference_date.year)
    if explicit_date:
        time_text = _parse_time_text(text)
        parsed_time = _parse_time_fragment(time_text)
        if parsed_time:
            return explicit_date, datetime.combine(explicit_date, parsed_time, tzinfo=UTC), parsed_time.strftime("%H:%M")
        return explicit_date, None, time_text

    resolved_date: date | None = None
    if "today" in lower:
        resolved_date = reference_date
    elif "tomorrow" in lower:
        resolved_date = reference_date + timedelta(days=1)
    elif "yesterday" in lower:
        resolved_date = reference_date - timedelta(days=1)
    else:
        for weekday_name, weekday_index in WEEKDAY_MAP.items():
            if weekday_name in lower:
                resolved_date = _next_weekday(reference_date, weekday_index)
                break

    time_text = _parse_time_text(text)
    parsed_time = _parse_time_fragment(time_text)
    if resolved_date and parsed_time:
        return resolved_date, datetime.combine(resolved_date, parsed_time, tzinfo=UTC), parsed_time.strftime("%H:%M")
    return resolved_date, None, time_text


def _parse_sportpesa_datetime(value: str | None, *, reference_year: int) -> tuple[date | None, datetime | None, str | None]:
    parsed_date = _parse_slash_date(value, default_order="dmy", reference_year=reference_year)
    time_text = _parse_time_text(value)
    parsed_time = _parse_time_fragment(time_text)
    if parsed_date and parsed_time:
        return parsed_date, datetime.combine(parsed_date, parsed_time, tzinfo=UTC), parsed_time.strftime("%H:%M")
    return parsed_date, None, time_text


def _parse_mozzart_datetime(value: str | None, *, reference_year: int) -> tuple[date | None, datetime | None, str | None]:
    parsed_date = _parse_dot_date(value, reference_year=reference_year)
    time_text = _parse_time_text(value)
    parsed_time = _parse_time_fragment(time_text)
    if parsed_date and parsed_time:
        return parsed_date, datetime.combine(parsed_date, parsed_time, tzinfo=UTC), parsed_time.strftime("%H:%M")
    return parsed_date, None, time_text


def _candidate_from_row(row: dict[str, Any], *, source_table: str, reference_date: date) -> CanonicalCandidate | None:
    sport = str(row["sport"]) if row.get("sport") else ""
    home_team = str(row["home_team"]) if row.get("home_team") else ""
    away_team = str(row["away_team"]) if row.get("away_team") else ""
    if not sport or not home_team or not away_team:
        return None

    source_event_date: date | None = None
    source_event_datetime_utc: datetime | None = None
    source_event_datetime_text: str | None = None
    source_event_time_text: str | None = None
    source_status: str | None = None
    result_home_score: int | None = None
    result_away_score: int | None = None
    source_match_url: str | None = None

    if source_table == "bookmaker_odds":
        source_event_datetime_text = row.get("event_datetime_text")
        source_reference_date = reference_date
        source_run_started_at = row.get("source_run_started_at")
        if isinstance(source_run_started_at, datetime):
            source_reference_date = source_run_started_at.date()
        elif source_run_started_at:
            source_reference_date = datetime.fromisoformat(str(source_run_started_at)).date()

        source_name = str(row.get("source_name", "")).casefold()
        if source_name == "betika":
            source_event_date, source_event_datetime_utc, source_event_time_text = _parse_relative_bookmaker_datetime(
                source_event_datetime_text,
                reference_date=source_reference_date,
            )
        elif source_name == "sportpesa":
            source_event_date, source_event_datetime_utc, source_event_time_text = _parse_sportpesa_datetime(
                source_event_datetime_text,
                reference_year=source_reference_date.year,
            )
        elif source_name == "mozzart":
            source_event_date, source_event_datetime_utc, source_event_time_text = _parse_mozzart_datetime(
                source_event_datetime_text,
                reference_year=source_reference_date.year,
            )
        else:
            source_event_date, source_event_datetime_utc, source_event_time_text = _parse_relative_bookmaker_datetime(
                source_event_datetime_text,
                reference_date=source_reference_date,
            )
        source_status = row.get("match_status")
    elif source_table == "forebet_predictions":
        source_event_datetime_text = row.get("event_datetime_text")
        source_event_date, source_event_datetime_utc, source_event_time_text = _parse_forebet_datetime(source_event_datetime_text)
        source_match_url = row.get("match_url")
    elif source_table == "forebet_results":
        source_event_datetime_text = row.get("event_datetime_text")
        source_event_date, source_event_datetime_utc, source_event_time_text = _parse_forebet_datetime(source_event_datetime_text)
        source_match_url = row.get("match_url")
        source_status = row.get("status")
        result_home_score = row.get("actual_home_score")
        result_away_score = row.get("actual_away_score")
    elif source_table == "flashscore_results":
        source_event_datetime_text = row.get("page_date_text")
        source_event_date, source_event_datetime_utc, source_event_time_text = _parse_flashscore_date(
            row.get("page_date_text"),
            row.get("event_time_text"),
            reference_year=reference_date.year,
        )
        source_status = row.get("match_status")
        result_home_score = row.get("home_score")
        result_away_score = row.get("away_score")
    elif source_table == "sports_results":
        event_date_value = row.get("event_date")
        if isinstance(event_date_value, date):
            source_event_date = event_date_value
        elif event_date_value:
            source_event_date = date.fromisoformat(str(event_date_value))
        source_event_datetime_text = row.get("event_time")
        source_event_time_text = row.get("event_time")
        if source_event_date and row.get("event_time"):
            parsed_time = _parse_time_fragment(str(row["event_time"]))
            if parsed_time:
                source_event_datetime_utc = datetime.combine(source_event_date, parsed_time, tzinfo=UTC)
        source_status = row.get("status")
        result_home_score = row.get("home_score")
        result_away_score = row.get("away_score")
    elif source_table == "forebet_match_analyses":
        source_event_datetime_text = row.get("event_datetime_text")
        source_event_date, source_event_datetime_utc, source_event_time_text = _parse_forebet_datetime(source_event_datetime_text)
        source_match_url = row.get("match_url")
        source_status = row.get("actual_status")

    return CanonicalCandidate(
        source_name=str(row["source_name"]),
        source_table=source_table,
        source_row_id=int(row["source_row_id"]),
        source_run_id=int(row["source_run_id"]) if row.get("source_run_id") is not None else None,
        sport=sport,
        league=row.get("league"),
        home_team=home_team,
        away_team=away_team,
        source_event_date=source_event_date,
        source_event_datetime_utc=source_event_datetime_utc,
        source_event_datetime_text=source_event_datetime_text,
        source_event_time_text=source_event_time_text,
        source_match_url=source_match_url,
        source_status=source_status,
        result_home_score=result_home_score,
        result_away_score=result_away_score,
    )


def _candidate_identity(candidate: CanonicalCandidate) -> tuple[str, date, str, str] | None:
    if candidate.source_event_date is None:
        return None
    return (
        candidate.sport.casefold(),
        candidate.source_event_date,
        normalize_team_name(candidate.home_team),
        normalize_team_name(candidate.away_team),
    )


def _fetch_rows(connection, query: str, params: Iterable[Any]) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]


def fetch_source_rows(
    connection,
    *,
    source_table: str,
    limit: int,
    include_linked_rows: bool,
) -> list[dict[str, Any]]:
    """Fetch source rows for canonical linking, optionally including already-linked rows."""

    queries: dict[str, str] = {
        "bookmaker_odds": """
            SELECT
                bo.id AS source_row_id,
                bo.run_id AS source_run_id,
                sr.started_at AS source_run_started_at,
                bo.source_name,
                bo.sport,
                bo.league,
                bo.home_team,
                bo.away_team,
                bo.event_datetime_text
            FROM bookmaker_odds AS bo
            LEFT JOIN source_runs AS sr
                ON sr.id = bo.run_id
            LEFT JOIN fixture_source_links AS links
                ON links.source_table = 'bookmaker_odds'
               AND links.source_row_id = bo.id
            WHERE links.id IS NULL
            ORDER BY bo.id DESC
            LIMIT %s
        """,
        "forebet_predictions": """
            SELECT
                fp.id AS source_row_id,
                fp.run_id AS source_run_id,
                fp.source_name,
                fp.sport,
                fp.league,
                fp.home_team,
                fp.away_team,
                fp.event_datetime_text,
                fp.match_url
            FROM forebet_predictions AS fp
            LEFT JOIN fixture_source_links AS links
                ON links.source_table = 'forebet_predictions'
               AND links.source_row_id = fp.id
            WHERE links.id IS NULL
            ORDER BY fp.id DESC
            LIMIT %s
        """,
        "forebet_results": """
            SELECT
                fr.id AS source_row_id,
                fr.run_id AS source_run_id,
                fr.source_name,
                fr.sport,
                fr.league,
                fr.home_team,
                fr.away_team,
                fr.event_datetime_text,
                fr.match_url,
                fr.status,
                fr.actual_home_score,
                fr.actual_away_score
            FROM forebet_results AS fr
            LEFT JOIN fixture_source_links AS links
                ON links.source_table = 'forebet_results'
               AND links.source_row_id = fr.id
            WHERE links.id IS NULL
            ORDER BY fr.id DESC
            LIMIT %s
        """,
        "flashscore_results": """
            SELECT
                fs.id AS source_row_id,
                fs.run_id AS source_run_id,
                fs.source_name,
                fs.sport,
                fs.league,
                fs.home_team,
                fs.away_team,
                fs.page_date_text,
                fs.event_time_text,
                fs.match_status,
                fs.home_score,
                fs.away_score
            FROM flashscore_results AS fs
            LEFT JOIN fixture_source_links AS links
                ON links.source_table = 'flashscore_results'
               AND links.source_row_id = fs.id
            WHERE links.id IS NULL
            ORDER BY fs.id DESC
            LIMIT %s
        """,
        "sports_results": """
            SELECT
                sr.id AS source_row_id,
                sr.run_id AS source_run_id,
                sr.source_name,
                sr.sport,
                sr.league,
                sr.home_team,
                sr.away_team,
                sr.event_date,
                sr.event_time,
                sr.status,
                sr.home_score,
                sr.away_score
            FROM sports_results AS sr
            LEFT JOIN fixture_source_links AS links
                ON links.source_table = 'sports_results'
               AND links.source_row_id = sr.id
            WHERE links.id IS NULL
            ORDER BY sr.id DESC
            LIMIT %s
        """,
        "forebet_match_analyses": """
            SELECT
                fa.id AS source_row_id,
                NULL::BIGINT AS source_run_id,
                fa.source_name,
                fa.sport,
                fa.competition AS league,
                fa.home_team,
                fa.away_team,
                fa.event_datetime_text,
                fa.match_url,
                fa.actual_status AS status
            FROM forebet_match_analyses AS fa
            LEFT JOIN fixture_source_links AS links
                ON links.source_table = 'forebet_match_analyses'
               AND links.source_row_id = fa.id
            WHERE links.id IS NULL
            ORDER BY fa.id DESC
            LIMIT %s
        """,
    }

    if source_table not in queries:
        raise ValueError(f"Unsupported source table: {source_table}")

    query = queries[source_table]
    if include_linked_rows:
        query = re.sub(r"^\s*WHERE links\.id IS NULL\s*$", "", query, flags=re.MULTILINE)

    rows = _fetch_rows(connection, query, (limit,))
    if source_table == "flashscore_results":
        for row in rows:
            row["event_datetime_text"] = row.get("event_time_text")
    return rows


def build_canonical_fixtures(config: CanonicalBuildConfig) -> dict[str, Any]:
    """Create canonical fixtures and source links from current raw-source tables."""

    created_links = 0
    created_fixtures: set[int] = set()
    skipped_rows = 0

    with get_postgres_connection(autocommit=True) as connection:
        for source_table in config.source_tables:
            raw_rows = fetch_source_rows(
                connection,
                source_table=source_table,
                limit=config.limit_per_source,
                include_linked_rows=config.include_linked_rows,
            )
            for row in raw_rows:
                candidate = _candidate_from_row(row, source_table=source_table, reference_date=config.batch_date)
                if candidate is None:
                    skipped_rows += 1
                    continue

                identity = _candidate_identity(candidate)
                if identity is None:
                    skipped_rows += 1
                    continue

                result_source = candidate.source_name if candidate.result_home_score is not None and candidate.result_away_score is not None else None
                fixture_id = upsert_canonical_fixture(
                    connection,
                    sport=candidate.sport,
                    canonical_league=candidate.league,
                    canonical_home_team=normalize_team_name(candidate.home_team),
                    canonical_away_team=normalize_team_name(candidate.away_team),
                    canonical_event_date=candidate.source_event_date,
                    canonical_event_datetime_utc=candidate.source_event_datetime_utc,
                    canonical_event_datetime_text=candidate.source_event_datetime_text,
                    canonical_event_time_text=candidate.source_event_time_text,
                    canonical_status=candidate.source_status,
                    result_home_score=candidate.result_home_score,
                    result_away_score=candidate.result_away_score,
                    primary_result_source=result_source,
                    confidence=0.95,
                )
                created_fixtures.add(fixture_id)
                created_links += upsert_fixture_source_links(
                    connection,
                    rows=[
                        {
                            "fixture_id": fixture_id,
                            "source_name": candidate.source_name,
                            "source_table": candidate.source_table,
                            "source_row_id": candidate.source_row_id,
                            "source_run_id": candidate.source_run_id,
                            "source_match_url": candidate.source_match_url,
                            "source_sport": candidate.sport,
                            "source_league": candidate.league,
                            "source_home_team": candidate.home_team,
                            "source_away_team": candidate.away_team,
                            "source_event_date": candidate.source_event_date,
                            "source_event_datetime_text": candidate.source_event_datetime_text,
                            "source_event_time_text": candidate.source_event_time_text,
                            "link_method": "exact_date_team_match",
                            "link_confidence": 0.95,
                        }
                    ],
                )

    return {
        "status": "success",
        "fixtures_touched": len(created_fixtures),
        "links_written": created_links,
        "skipped_rows": skipped_rows,
        "source_tables": list(config.source_tables),
        "limit_per_source": config.limit_per_source,
        "include_linked_rows": config.include_linked_rows,
        "batch_date": config.batch_date.isoformat(),
    }
