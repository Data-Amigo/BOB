from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from psycopg.rows import dict_row

from ganji_mtaani_agent.db import get_postgres_connection, upsert_fixture_evaluations
from ganji_mtaani_agent.etl.canonical_fixtures import (
    _candidate_from_row,
    _parse_flashscore_date,
    _parse_forebet_datetime,
    normalize_team_name,
)


RESULT_SOURCE_PRIORITY = {
    "forebet_results": 0,
    "flashscore_results": 1,
    "sports_results": 2,
}


@dataclass(frozen=True, slots=True)
class FixtureEvaluationBuildConfig:
    sport: str | None = None
    limit_per_source: int | None = None


def _normalize_sport_name(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    if text == "soccer":
        return "football"
    return text


def _sport_matches_filter(raw_value: str | None, requested_sport: str | None) -> bool:
    if not requested_sport:
        return True
    return _normalize_sport_name(raw_value) == _normalize_sport_name(requested_sport)


def _parse_forebet_event_date(value: str | None) -> date | None:
    parsed_date, _, _ = _parse_forebet_datetime(value)
    return parsed_date


def _parse_flashscore_event_date(page_date_text: str | None, event_time_text: str | None) -> date | None:
    parsed_date, _, _ = _parse_flashscore_date(
        page_date_text,
        event_time_text,
        reference_year=date.today().year,
    )
    return parsed_date


def _actual_outcome(home_score: int | None, away_score: int | None) -> str | None:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "1"
    if away_score > home_score:
        return "2"
    return "X"


def _pred_probability(pred_outcome: str | None, row: dict[str, Any]) -> float | None:
    if pred_outcome == "1":
        return row.get("prob_1")
    if pred_outcome == "X":
        return row.get("prob_x")
    if pred_outcome == "2":
        return row.get("prob_2")
    return None


def _display_value(*values: Any) -> str | None:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def _fetch_all(connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def _fetch_forebet_predictions(connection, *, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, sport, league, home_team, away_team, match_url, event_datetime_text,
               prob_1, prob_x, prob_2, pred_outcome,
               predicted_home_score, predicted_away_score, correct_score_text, created_at
        FROM forebet_predictions
        ORDER BY id DESC
    """
    if limit:
        sql += " LIMIT %s"
        return _fetch_all(connection, sql, (limit,))
    return _fetch_all(connection, sql)


def _fetch_forebet_results(connection, *, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, sport, league, home_team, away_team, match_url, event_datetime_text,
               prob_1, prob_x, prob_2, pred_outcome,
               predicted_home_score, predicted_away_score, predicted_score_text,
               actual_home_score, actual_away_score, actual_score_text, actual_outcome,
               pred_hit, created_at
        FROM forebet_results
        ORDER BY id DESC
    """
    if limit:
        sql += " LIMIT %s"
        return _fetch_all(connection, sql, (limit,))
    return _fetch_all(connection, sql)


def _fetch_flashscore_results(connection, *, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, sport, league, home_team, away_team, page_date_text, event_time_text,
               home_score, away_score, created_at
        FROM flashscore_results
        ORDER BY id DESC
    """
    if limit:
        sql += " LIMIT %s"
        return _fetch_all(connection, sql, (limit,))
    return _fetch_all(connection, sql)


def _fetch_sports_results(connection, *, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, sport, league, home_team, away_team, event_date,
               home_score, away_score, created_at
        FROM sports_results
        ORDER BY id DESC
    """
    if limit:
        sql += " LIMIT %s"
        return _fetch_all(connection, sql, (limit,))
    return _fetch_all(connection, sql)


def _fetch_bookmaker_rows(connection, *, limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            bo.id,
            bo.source_name,
            bo.sport,
            bo.league,
            bo.home_team,
            bo.away_team,
            bo.event_datetime_text,
            bo.created_at,
            sr.started_at AS source_run_started_at
        FROM bookmaker_odds AS bo
        LEFT JOIN source_runs AS sr
            ON sr.id = bo.run_id
        ORDER BY id DESC
    """
    if limit:
        sql += " LIMIT %s"
        return _fetch_all(connection, sql, (limit,))
    return _fetch_all(connection, sql)


def _fetch_canonical_index(connection) -> dict[tuple[str, date, str, str], int]:
    rows = _fetch_all(
        connection,
        """
        SELECT id, sport, canonical_event_date, canonical_home_team, canonical_away_team
        FROM canonical_fixtures
        ORDER BY id DESC
        """,
    )
    index: dict[tuple[str, date, str, str], int] = {}
    for row in rows:
        event_date = row.get("canonical_event_date")
        if not event_date:
            continue
        key = (
            _normalize_sport_name(row.get("sport")),
            event_date,
            str(row.get("canonical_home_team") or ""),
            str(row.get("canonical_away_team") or ""),
        )
        index.setdefault(key, int(row["id"]))
    return index


def _key_for_row(*, sport: str | None, event_date: date | None, home_team: str | None, away_team: str | None) -> tuple[str, date, str, str] | None:
    if not event_date:
        return None

    normalized_sport = _normalize_sport_name(sport)
    normalized_home = normalize_team_name(home_team)
    normalized_away = normalize_team_name(away_team)
    if not normalized_sport or not normalized_home or not normalized_away:
        return None

    return normalized_sport, event_date, normalized_home, normalized_away


def _maybe_attach_canonical_id(
    row: dict[str, Any],
    canonical_index: dict[tuple[str, date, str, str], int],
) -> None:
    key = _key_for_row(
        sport=row.get("sport"),
        event_date=row.get("event_date"),
        home_team=row.get("normalized_home_team"),
        away_team=row.get("normalized_away_team"),
    )
    if key:
        row["canonical_fixture_id"] = canonical_index.get(key)


def _prefer_display(current: str | None, candidate: Any) -> str | None:
    if current not in (None, ""):
        return current
    if candidate in (None, ""):
        return current
    return str(candidate)


def build_fixture_evaluations(config: FixtureEvaluationBuildConfig) -> dict[str, Any]:
    evaluation_index: dict[tuple[str, date, str, str], dict[str, Any]] = {}

    def ensure_row(
        *,
        sport: str,
        event_date: date,
        normalized_home_team: str,
        normalized_away_team: str,
    ) -> dict[str, Any]:
        key = (sport, event_date, normalized_home_team, normalized_away_team)
        row = evaluation_index.get(key)
        if row is None:
            row = {
                "sport": sport,
                "event_date": event_date,
                "normalized_home_team": normalized_home_team,
                "normalized_away_team": normalized_away_team,
                "display_home_team": None,
                "display_away_team": None,
                "display_league": None,
                "prediction_source": None,
                "prediction_row_id": None,
                "prediction_match_url": None,
                "pred_outcome": None,
                "pred_probability": None,
                "predicted_home_score": None,
                "predicted_away_score": None,
                "result_source_used": None,
                "result_row_id": None,
                "actual_home_score": None,
                "actual_away_score": None,
                "actual_outcome": None,
                "pred_hit": None,
                "bookmaker_row_count": 0,
                "bookmaker_sources_json": [],
                "available_sources_json": [],
                "canonical_fixture_id": None,
                "evaluation_status": "pending",
                "evaluation_confidence": 0.5,
            }
            evaluation_index[key] = row
        return row

    with get_postgres_connection(autocommit=True) as connection:
        canonical_index = _fetch_canonical_index(connection)

        for prediction in _fetch_forebet_predictions(connection, limit=config.limit_per_source):
            if not _sport_matches_filter(prediction.get("sport"), config.sport):
                continue
            event_date = _parse_forebet_event_date(prediction.get("event_datetime_text"))
            if not event_date:
                continue
            sport = _normalize_sport_name(prediction.get("sport"))
            normalized_home = normalize_team_name(prediction.get("home_team"))
            normalized_away = normalize_team_name(prediction.get("away_team"))
            row = ensure_row(
                sport=sport,
                event_date=event_date,
                normalized_home_team=normalized_home,
                normalized_away_team=normalized_away,
            )
            if row["prediction_source"] is None:
                row["prediction_source"] = "forebet"
                row["prediction_row_id"] = int(prediction["id"])
                row["prediction_match_url"] = prediction.get("match_url")
                row["pred_outcome"] = prediction.get("pred_outcome")
                row["pred_probability"] = _pred_probability(prediction.get("pred_outcome"), prediction)
                row["predicted_home_score"] = prediction.get("predicted_home_score")
                row["predicted_away_score"] = prediction.get("predicted_away_score")
            row["display_home_team"] = _display_value(row["display_home_team"], prediction.get("home_team"))
            row["display_away_team"] = _display_value(row["display_away_team"], prediction.get("away_team"))
            row["display_league"] = _display_value(row["display_league"], prediction.get("league"))
            if "forebet" not in row["available_sources_json"]:
                row["available_sources_json"].append("forebet")
            row["canonical_fixture_id"] = canonical_index.get((sport, event_date, normalized_home, normalized_away))

        for bookmaker in _fetch_bookmaker_rows(connection, limit=config.limit_per_source):
            if not _sport_matches_filter(bookmaker.get("sport"), config.sport):
                continue
            candidate = _candidate_from_row(
                {
                    "source_name": bookmaker.get("source_name"),
                    "source_row_id": bookmaker.get("id"),
                    "source_run_id": None,
                    "source_run_started_at": bookmaker.get("source_run_started_at"),
                    "sport": bookmaker.get("sport"),
                    "league": bookmaker.get("league"),
                    "home_team": bookmaker.get("home_team"),
                    "away_team": bookmaker.get("away_team"),
                    "event_datetime_text": bookmaker.get("event_datetime_text"),
                },
                source_table="bookmaker_odds",
                reference_date=date.today(),
            )
            if candidate is None or not candidate.source_event_date:
                continue
            sport = _normalize_sport_name(bookmaker.get("sport"))
            normalized_home = normalize_team_name(bookmaker.get("home_team"))
            normalized_away = normalize_team_name(bookmaker.get("away_team"))
            row = ensure_row(
                sport=sport,
                event_date=candidate.source_event_date,
                normalized_home_team=normalized_home,
                normalized_away_team=normalized_away,
            )
            row["display_home_team"] = _display_value(row["display_home_team"], bookmaker.get("home_team"))
            row["display_away_team"] = _display_value(row["display_away_team"], bookmaker.get("away_team"))
            row["display_league"] = _display_value(row["display_league"], bookmaker.get("league"))
            row["bookmaker_row_count"] += 1
            source_name = str(bookmaker.get("source_name") or "")
            if source_name and source_name not in row["bookmaker_sources_json"]:
                row["bookmaker_sources_json"].append(source_name)
            if source_name and source_name not in row["available_sources_json"]:
                row["available_sources_json"].append(source_name)
            row["canonical_fixture_id"] = canonical_index.get((sport, candidate.source_event_date, normalized_home, normalized_away))

        for forebet_result in _fetch_forebet_results(connection, limit=config.limit_per_source):
            if not _sport_matches_filter(forebet_result.get("sport"), config.sport):
                continue
            event_date = _parse_forebet_event_date(forebet_result.get("event_datetime_text"))
            if not event_date:
                continue
            sport = _normalize_sport_name(forebet_result.get("sport"))
            normalized_home = normalize_team_name(forebet_result.get("home_team"))
            normalized_away = normalize_team_name(forebet_result.get("away_team"))
            row = ensure_row(
                sport=sport,
                event_date=event_date,
                normalized_home_team=normalized_home,
                normalized_away_team=normalized_away,
            )
            if row["prediction_source"] is None:
                row["prediction_source"] = "forebet"
                row["prediction_row_id"] = int(forebet_result["id"])
                row["prediction_match_url"] = forebet_result.get("match_url")
                row["pred_outcome"] = forebet_result.get("pred_outcome")
                row["pred_probability"] = _pred_probability(forebet_result.get("pred_outcome"), forebet_result)
                row["predicted_home_score"] = forebet_result.get("predicted_home_score")
                row["predicted_away_score"] = forebet_result.get("predicted_away_score")
            current_priority = RESULT_SOURCE_PRIORITY.get(str(row["result_source_used"] or ""), 99)
            if RESULT_SOURCE_PRIORITY["forebet_results"] <= current_priority:
                row["result_source_used"] = "forebet_results"
                row["result_row_id"] = int(forebet_result["id"])
                row["actual_home_score"] = forebet_result.get("actual_home_score")
                row["actual_away_score"] = forebet_result.get("actual_away_score")
                row["actual_outcome"] = forebet_result.get("actual_outcome") or _actual_outcome(
                    forebet_result.get("actual_home_score"),
                    forebet_result.get("actual_away_score"),
                )
                row["pred_hit"] = forebet_result.get("pred_hit")
            row["display_home_team"] = _display_value(row["display_home_team"], forebet_result.get("home_team"))
            row["display_away_team"] = _display_value(row["display_away_team"], forebet_result.get("away_team"))
            row["display_league"] = _display_value(row["display_league"], forebet_result.get("league"))
            if "forebet" not in row["available_sources_json"]:
                row["available_sources_json"].append("forebet")
            if "forebet_results" not in row["available_sources_json"]:
                row["available_sources_json"].append("forebet_results")
            row["canonical_fixture_id"] = canonical_index.get((sport, event_date, normalized_home, normalized_away))

        for flashscore_result in _fetch_flashscore_results(connection, limit=config.limit_per_source):
            if not _sport_matches_filter(flashscore_result.get("sport"), config.sport):
                continue
            event_date = _parse_flashscore_event_date(
                flashscore_result.get("page_date_text"),
                flashscore_result.get("event_time_text"),
            )
            if not event_date:
                continue
            sport = _normalize_sport_name(flashscore_result.get("sport"))
            normalized_home = normalize_team_name(flashscore_result.get("home_team"))
            normalized_away = normalize_team_name(flashscore_result.get("away_team"))
            row = ensure_row(
                sport=sport,
                event_date=event_date,
                normalized_home_team=normalized_home,
                normalized_away_team=normalized_away,
            )
            current_priority = RESULT_SOURCE_PRIORITY.get(str(row["result_source_used"] or ""), 99)
            if RESULT_SOURCE_PRIORITY["flashscore_results"] < current_priority:
                row["result_source_used"] = "flashscore_results"
                row["result_row_id"] = int(flashscore_result["id"])
                row["actual_home_score"] = flashscore_result.get("home_score")
                row["actual_away_score"] = flashscore_result.get("away_score")
                row["actual_outcome"] = _actual_outcome(
                    flashscore_result.get("home_score"),
                    flashscore_result.get("away_score"),
                )
            row["display_home_team"] = _display_value(row["display_home_team"], flashscore_result.get("home_team"))
            row["display_away_team"] = _display_value(row["display_away_team"], flashscore_result.get("away_team"))
            row["display_league"] = _display_value(row["display_league"], flashscore_result.get("league"))
            if "flashscore" not in row["available_sources_json"]:
                row["available_sources_json"].append("flashscore")
            row["canonical_fixture_id"] = canonical_index.get((sport, event_date, normalized_home, normalized_away))

        for sports_result in _fetch_sports_results(connection, limit=config.limit_per_source):
            if not _sport_matches_filter(sports_result.get("sport"), config.sport):
                continue
            event_date = sports_result.get("event_date")
            if not event_date:
                continue
            sport = _normalize_sport_name(sports_result.get("sport"))
            normalized_home = normalize_team_name(sports_result.get("home_team"))
            normalized_away = normalize_team_name(sports_result.get("away_team"))
            row = ensure_row(
                sport=sport,
                event_date=event_date,
                normalized_home_team=normalized_home,
                normalized_away_team=normalized_away,
            )
            current_priority = RESULT_SOURCE_PRIORITY.get(str(row["result_source_used"] or ""), 99)
            if RESULT_SOURCE_PRIORITY["sports_results"] < current_priority:
                row["result_source_used"] = "sports_results"
                row["result_row_id"] = int(sports_result["id"])
                row["actual_home_score"] = sports_result.get("home_score")
                row["actual_away_score"] = sports_result.get("away_score")
                row["actual_outcome"] = _actual_outcome(
                    sports_result.get("home_score"),
                    sports_result.get("away_score"),
                )
            row["display_home_team"] = _display_value(row["display_home_team"], sports_result.get("home_team"))
            row["display_away_team"] = _display_value(row["display_away_team"], sports_result.get("away_team"))
            row["display_league"] = _display_value(row["display_league"], sports_result.get("league"))
            if "thesportsdb" not in row["available_sources_json"]:
                row["available_sources_json"].append("thesportsdb")
            row["canonical_fixture_id"] = canonical_index.get((sport, event_date, normalized_home, normalized_away))

        prepared_rows: list[dict[str, Any]] = []
        for row in evaluation_index.values():
            row["display_home_team"] = _prefer_display(row.get("display_home_team"), row.get("normalized_home_team"))
            row["display_away_team"] = _prefer_display(row.get("display_away_team"), row.get("normalized_away_team"))

            if row["pred_hit"] is None and row["pred_outcome"] and row["actual_outcome"]:
                row["pred_hit"] = row["pred_outcome"] == row["actual_outcome"]

            if row["prediction_source"] and row["result_source_used"] and row["pred_hit"] is not None:
                row["evaluation_status"] = "evaluated"
                row["evaluation_confidence"] = 1.0 if row["result_source_used"] == "forebet_results" else 0.95
            elif row["prediction_source"] and row["result_source_used"]:
                row["evaluation_status"] = "result_joined"
                row["evaluation_confidence"] = 0.9
            elif row["prediction_source"]:
                row["evaluation_status"] = "predicted_only"
                row["evaluation_confidence"] = 0.75
            elif row["result_source_used"]:
                row["evaluation_status"] = "result_only"
                row["evaluation_confidence"] = 0.8
            elif row["bookmaker_row_count"] > 0:
                row["evaluation_status"] = "odds_only"
                row["evaluation_confidence"] = 0.6
            else:
                row["evaluation_status"] = "pending"
                row["evaluation_confidence"] = 0.5

            row["available_sources_json"] = sorted(set(row["available_sources_json"]))
            row["bookmaker_sources_json"] = sorted(set(row["bookmaker_sources_json"]))
            prepared_rows.append(row)

        upserted_rows = upsert_fixture_evaluations(connection, rows=prepared_rows)

    return {
        "status": "success",
        "rows_upserted": upserted_rows,
        "evaluation_rows": len(evaluation_index),
        "sport_filter": config.sport,
        "limit_per_source": config.limit_per_source,
    }
