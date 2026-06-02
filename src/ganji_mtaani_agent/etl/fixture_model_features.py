from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row

from ganji_mtaani_agent.db.postgres import get_postgres_connection
from ganji_mtaani_agent.db.repositories import upsert_fixture_model_features
from ganji_mtaani_agent.etl.canonical_fixtures import normalize_team_name
from ganji_mtaani_agent.etl.fixture_evaluations import _normalize_sport_name


POINTS_BY_OUTCOME = {
    "W": 1.0,
    "D": 0.5,
    "L": 0.0,
}


@dataclass(frozen=True, slots=True)
class FixtureModelFeatureBuildConfig:
    sport: str | None = None
    limit: int | None = None
    window_size: int = 5


def _fetch_all(connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def _clamp_probability(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, value))


def _fetch_fixture_evaluation_rows(connection, *, sport: str | None, limit: int | None) -> list[dict[str, Any]]:
    clauses = [
        "prediction_source = 'forebet'",
        "prediction_match_url IS NOT NULL",
        "pred_outcome IS NOT NULL",
        "pred_probability IS NOT NULL",
    ]
    params: list[Any] = []
    if sport:
        clauses.append("LOWER(sport) = %s")
        params.append(_normalize_sport_name(sport))

    where_sql = f"WHERE {' AND '.join(clauses)}"
    sql = f"""
        SELECT
            id AS evaluation_id,
            canonical_fixture_id,
            sport,
            event_date,
            normalized_home_team,
            normalized_away_team,
            display_home_team,
            display_away_team,
            display_league,
            prediction_source,
            prediction_match_url,
            pred_outcome,
            pred_probability,
            actual_outcome,
            pred_hit
        FROM fixture_evaluations
        {where_sql}
        ORDER BY event_date DESC, id DESC
    """
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return _fetch_all(connection, sql, tuple(params))


def _fetch_history_rows(connection, *, match_urls: list[str]) -> list[dict[str, Any]]:
    if not match_urls:
        return []
    return _fetch_all(
        connection,
        """
        SELECT
            sport,
            match_url,
            section_name,
            section_team,
            sequence_no,
            result_outcome,
            active_side,
            home_team,
            away_team
        FROM forebet_match_history_rows
        WHERE match_url = ANY(%s)
        ORDER BY match_url, section_name, section_team, sequence_no ASC
        """,
        (match_urls,),
    )


def _points_for_row(row: dict[str, Any]) -> float:
    return POINTS_BY_OUTCOME.get(str(row.get("result_outcome") or "").upper(), 0.0)


def _compute_form_metrics(
    rows: list[dict[str, Any]],
    *,
    section_name: str,
    section_team: str,
    window_size: int,
) -> tuple[int, float, float]:
    normalized_section_team = normalize_team_name(section_team)
    section_rows = [
        row
        for row in rows
        if str(row.get("section_name") or "") == section_name
        and normalize_team_name(row.get("section_team")) == normalized_section_team
    ]
    selected_rows = section_rows[:window_size]
    matches_used = len(selected_rows)
    points = sum(_points_for_row(row) for row in selected_rows)
    normalized_form = points / float(window_size) if window_size else 0.0
    return matches_used, points, normalized_form


def _compute_outcome_breakdown(
    rows: list[dict[str, Any]],
    *,
    section_name: str,
    section_team: str,
    window_size: int,
) -> dict[str, float]:
    normalized_section_team = normalize_team_name(section_team)
    section_rows = [
        row
        for row in rows
        if str(row.get("section_name") or "") == section_name
        and normalize_team_name(row.get("section_team")) == normalized_section_team
    ]
    selected_rows = section_rows[:window_size]
    total_matches = len(selected_rows)
    wins = sum(1 for row in selected_rows if str(row.get("result_outcome") or "").upper() == "W")
    draws = sum(1 for row in selected_rows if str(row.get("result_outcome") or "").upper() == "D")
    losses = sum(1 for row in selected_rows if str(row.get("result_outcome") or "").upper() == "L")
    return {
        "matches": total_matches,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_pct": (wins / total_matches * 100.0) if total_matches else 0.0,
        "draw_pct": (draws / total_matches * 100.0) if total_matches else 0.0,
        "loss_pct": (losses / total_matches * 100.0) if total_matches else 0.0,
    }


def _predicted_side_metrics(
    *,
    pred_outcome: str | None,
    home_signal: float,
    away_signal: float,
    base_probability: float,
) -> tuple[float | None, float | None, float | None]:
    pred_value = str(pred_outcome or "")
    if pred_value == "1":
        predicted_side_form = home_signal
        opponent_side_form = away_signal
        return (
            predicted_side_form,
            opponent_side_form,
            _clamp_probability(base_probability + ((predicted_side_form - opponent_side_form) * 0.20)),
        )
    if pred_value == "2":
        predicted_side_form = away_signal
        opponent_side_form = home_signal
        return (
            predicted_side_form,
            opponent_side_form,
            _clamp_probability(base_probability + ((predicted_side_form - opponent_side_form) * 0.20)),
        )
    if pred_value == "X":
        balance_signal = max(0.0, 1.0 - abs(home_signal - away_signal))
        return (
            balance_signal,
            abs(home_signal - away_signal),
            _clamp_probability(base_probability + ((balance_signal - 0.5) * 0.20)),
        )
    return None, None, None


def build_fixture_model_features(config: FixtureModelFeatureBuildConfig) -> dict[str, Any]:
    with get_postgres_connection(autocommit=True) as connection:
        evaluation_rows = _fetch_fixture_evaluation_rows(
            connection,
            sport=config.sport,
            limit=config.limit,
        )
        if not evaluation_rows:
            return {
                "rows_considered": 0,
                "rows_upserted": 0,
                "rows_with_history": 0,
                "average_history_coverage_pct": 0.0,
                "window_size": config.window_size,
            }

        match_urls = sorted(
            {
                str(row.get("prediction_match_url"))
                for row in evaluation_rows
                if row.get("prediction_match_url")
            }
        )
        history_rows = _fetch_history_rows(connection, match_urls=match_urls)
        history_by_match_url: dict[str, list[dict[str, Any]]] = {}
        for row in history_rows:
            history_by_match_url.setdefault(str(row["match_url"]), []).append(row)

        prepared_rows: list[dict[str, Any]] = []
        rows_with_history = 0
        coverage_values: list[float] = []

        for evaluation_row in evaluation_rows:
            match_url = str(evaluation_row.get("prediction_match_url") or "")
            fixture_history_rows = history_by_match_url.get(match_url, [])

            home_team = str(evaluation_row.get("display_home_team") or evaluation_row.get("normalized_home_team") or "")
            away_team = str(evaluation_row.get("display_away_team") or evaluation_row.get("normalized_away_team") or "")

            home_overall_matches_used, home_overall_points, home_overall_form = _compute_form_metrics(
                fixture_history_rows,
                section_name="last_6_matches",
                section_team=home_team,
                window_size=config.window_size,
            )
            away_overall_matches_used, away_overall_points, away_overall_form = _compute_form_metrics(
                fixture_history_rows,
                section_name="last_6_matches",
                section_team=away_team,
                window_size=config.window_size,
            )
            home_home_matches_used, home_home_points, home_home_form = _compute_form_metrics(
                fixture_history_rows,
                section_name="home_matches",
                section_team=home_team,
                window_size=config.window_size,
            )
            away_away_matches_used, away_away_points, away_away_form = _compute_form_metrics(
                fixture_history_rows,
                section_name="away_matches",
                section_team=away_team,
                window_size=config.window_size,
            )
            home_prev_breakdown = _compute_outcome_breakdown(
                fixture_history_rows,
                section_name="last_6_matches",
                section_team=home_team,
                window_size=config.window_size,
            )
            away_prev_breakdown = _compute_outcome_breakdown(
                fixture_history_rows,
                section_name="last_6_matches",
                section_team=away_team,
                window_size=config.window_size,
            )

            history_coverage_pct = (
                (
                    home_overall_matches_used
                    + away_overall_matches_used
                    + home_home_matches_used
                    + away_away_matches_used
                )
                / float(config.window_size * 4)
                * 100.0
            ) if config.window_size else 0.0

            if history_coverage_pct > 0:
                rows_with_history += 1
                coverage_values.append(history_coverage_pct)

            home_signal = (home_overall_form + home_home_form) / 2.0
            away_signal = (away_overall_form + away_away_form) / 2.0
            predicted_side_form, opponent_side_form, model_confidence_v1 = _predicted_side_metrics(
                pred_outcome=evaluation_row.get("pred_outcome"),
                home_signal=home_signal,
                away_signal=away_signal,
                base_probability=float(evaluation_row.get("pred_probability") or 0.0) / 100.0,
            )

            prepared_rows.append(
                {
                    "evaluation_id": evaluation_row["evaluation_id"],
                    "canonical_fixture_id": evaluation_row.get("canonical_fixture_id"),
                    "sport": _normalize_sport_name(evaluation_row.get("sport")),
                    "event_date": evaluation_row["event_date"],
                    "normalized_home_team": evaluation_row["normalized_home_team"],
                    "normalized_away_team": evaluation_row["normalized_away_team"],
                    "display_home_team": evaluation_row.get("display_home_team"),
                    "display_away_team": evaluation_row.get("display_away_team"),
                    "display_league": evaluation_row.get("display_league"),
                    "prediction_source": evaluation_row.get("prediction_source"),
                    "prediction_match_url": evaluation_row.get("prediction_match_url"),
                    "pred_outcome": evaluation_row.get("pred_outcome"),
                    "pred_probability": evaluation_row.get("pred_probability"),
                    "actual_outcome": evaluation_row.get("actual_outcome"),
                    "pred_hit": evaluation_row.get("pred_hit"),
                    "home_overall_matches_used": home_overall_matches_used,
                    "away_overall_matches_used": away_overall_matches_used,
                    "home_home_matches_used": home_home_matches_used,
                    "away_away_matches_used": away_away_matches_used,
                    "home_overall_points_5": home_overall_points,
                    "away_overall_points_5": away_overall_points,
                    "home_home_points_5": home_home_points,
                    "away_away_points_5": away_away_points,
                    "home_overall_form_5": home_overall_form,
                    "away_overall_form_5": away_overall_form,
                    "home_home_form_5": home_home_form,
                    "away_away_form_5": away_away_form,
                    "overall_form_edge_5": home_overall_form - away_overall_form,
                    "venue_form_edge_5": home_home_form - away_away_form,
                    "home_prev_matches": home_prev_breakdown["matches"],
                    "home_prev_wins": home_prev_breakdown["wins"],
                    "home_prev_draws": home_prev_breakdown["draws"],
                    "home_prev_losses": home_prev_breakdown["losses"],
                    "home_prev_win_pct": home_prev_breakdown["win_pct"],
                    "home_prev_draw_pct": home_prev_breakdown["draw_pct"],
                    "home_prev_loss_pct": home_prev_breakdown["loss_pct"],
                    "away_prev_matches": away_prev_breakdown["matches"],
                    "away_prev_wins": away_prev_breakdown["wins"],
                    "away_prev_draws": away_prev_breakdown["draws"],
                    "away_prev_losses": away_prev_breakdown["losses"],
                    "away_prev_win_pct": away_prev_breakdown["win_pct"],
                    "away_prev_draw_pct": away_prev_breakdown["draw_pct"],
                    "away_prev_loss_pct": away_prev_breakdown["loss_pct"],
                    "predicted_side_form_5": predicted_side_form,
                    "opponent_side_form_5": opponent_side_form,
                    "model_confidence_v1": model_confidence_v1,
                    "history_coverage_pct": history_coverage_pct,
                }
            )

        rows_upserted = upsert_fixture_model_features(connection, rows=prepared_rows)
        return {
            "rows_considered": len(evaluation_rows),
            "rows_upserted": rows_upserted,
            "rows_with_history": rows_with_history,
            "average_history_coverage_pct": round(sum(coverage_values) / len(coverage_values), 2) if coverage_values else 0.0,
            "window_size": config.window_size,
        }
