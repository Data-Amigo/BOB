"""This is the fetch_and_parse_forebet.py file.

Author: Data-Amigo
Date: 2026-04-29
Description:
This is a unified developer workflow script for Forebet. It fetches the selected
Forebet target page, optionally saves debug artifacts, routes the HTML to the
correct parser, and prints a structured preview for either basketball or football.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# =============================================================================
# Local Import Setup
# =============================================================================
# This lets the script run directly from the repo before the package is fully
# installed in the environment.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.parsers.forebet import (
    parse_forebet_basketball,
    parse_forebet_football,
)
from ganji_mtaani_agent.scrapers.browser import fetch_page
from ganji_mtaani_agent.scrapers.forebet import build_forebet_collection_urls
from ganji_mtaani_agent.scrapers.sources import get_source_config, get_source_target


# =============================================================================
# Artifact Path Helper
# =============================================================================
# We keep raw HTML and screenshots under data/raw/ so we can inspect what the
# browser actually saw during a parser test run.
def build_artifact_paths(source_name: str, target_name: str) -> tuple[Path, Path]:
    """Build snapshot and screenshot paths for one fetch run."""

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    folder = Path("data") / "raw" / source_name / target_name
    return folder / f"{timestamp}.html", folder / f"{timestamp}.png"


# =============================================================================
# Parser Router
# =============================================================================
# This helper keeps the source-target-to-parser mapping in one place.
def parse_forebet_target(target_name: str, html: str):
    """Route Forebet HTML to the correct parser for the selected target."""

    if target_name == "basketball_today":
        return parse_forebet_basketball(html)
    if target_name == "football_today":
        return parse_forebet_football(html)

    raise ValueError(f"No parser is configured for Forebet target '{target_name}'.")


def _normalized_text(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def dedupe_predictions(predictions: list) -> list:
    """Deduplicate parsed Forebet predictions by fixture identity."""

    deduped: dict[tuple[str, str, str, str, str], object] = {}

    for prediction in predictions:
        key = (
            _normalized_text(getattr(prediction, "sport", None)),
            _normalized_text(getattr(prediction, "league", None)),
            _normalized_text(getattr(prediction, "home_team", None)),
            _normalized_text(getattr(prediction, "away_team", None)),
            _normalized_text(getattr(prediction, "event_datetime", None)),
        )
        deduped.setdefault(key, prediction)

    return list(deduped.values())


# =============================================================================
# Row Preview Printer
# =============================================================================
# Basketball and football have slightly different stable fields, so we print
# previews based on the target being parsed.
def print_prediction_preview(target_name: str, predictions: list, limit: int) -> None:
    """Print a small parsed-row preview for the selected Forebet target."""

    print(f"parsed_rows: {len(predictions)}")
    print()

    if target_name == "basketball_today":
        for index, prediction in enumerate(predictions[:limit], start=1):
            print(f"row_{index}:")
            print(f"  league: {prediction.league}")
            print(f"  home_team: {prediction.home_team}")
            print(f"  away_team: {prediction.away_team}")
            print(f"  event_datetime: {prediction.event_datetime}")
            print(f"  prob_1: {prediction.prob_1}")
            print(f"  prob_2: {prediction.prob_2}")
            print(f"  pred_outcome: {prediction.pred_outcome}")
            print(f"  predicted_home_score: {prediction.predicted_home_score}")
            print(f"  predicted_away_score: {prediction.predicted_away_score}")
            print(f"  avg_points: {prediction.avg_points}")
            print(f"  coef_1: {prediction.coef_1}")
            print(f"  coef_2: {prediction.coef_2}")
            print(f"  coef_3: {prediction.coef_3}")
            print(f"  remaining_tokens: {prediction.remaining_tokens}")
            print(f"  confidence: {prediction.confidence}")
            print("---")
        return

    if target_name == "football_today":
        for index, prediction in enumerate(predictions[:limit], start=1):
            print(f"row_{index}:")
            print(f"  league: {prediction.league}")
            print(f"  home_team: {prediction.home_team}")
            print(f"  away_team: {prediction.away_team}")
            print(f"  event_datetime: {prediction.event_datetime}")
            print(f"  prob_1: {prediction.prob_1}")
            print(f"  prob_x: {prediction.prob_x}")
            print(f"  prob_2: {prediction.prob_2}")
            print(f"  pred_outcome: {prediction.pred_outcome}")
            print(f"  predicted_home_score: {prediction.predicted_home_score}")
            print(f"  predicted_away_score: {prediction.predicted_away_score}")
            print(f"  correct_score_text: {prediction.correct_score_text}")
            print(f"  avg_goals: {prediction.avg_goals}")
            print(f"  weather: {prediction.weather}")
            print(f"  coef_1: {prediction.coef_1}")
            print(f"  coef_x: {prediction.coef_x}")
            print(f"  coef_2: {prediction.coef_2}")
            print(f"  coef_extra: {prediction.coef_extra}")
            print(f"  remaining_tokens: {prediction.remaining_tokens}")
            print(f"  confidence: {prediction.confidence}")
            print("---")
        return


# =============================================================================
# Command-Line Entry Point
# =============================================================================
def main() -> None:
    """Fetch a Forebet target, parse it, and print a small preview."""

    parser = argparse.ArgumentParser(description="Fetch and parse Forebet data.")
    parser.add_argument(
        "--target",
        choices=["basketball_today", "football_today"],
        default="basketball_today",
        help="Forebet target page to fetch and parse.",
    )
    parser.add_argument("--limit", type=int, default=5, help="How many parsed rows to print.")
    parser.add_argument("--save-snapshot", action="store_true", help="Save the raw HTML snapshot.")
    parser.add_argument("--screenshot", action="store_true", help="Save a screenshot of the page.")
    parser.add_argument("--headless", action="store_true", help="Force headless mode for comparison.")
    args = parser.parse_args()

    source = get_source_config("forebet")
    target = get_source_target(source, args.target)

    snapshot_path = None
    screenshot_path = None
    if args.save_snapshot or args.screenshot:
        built_snapshot_path, built_screenshot_path = build_artifact_paths(source.name, target.name)
        if args.save_snapshot:
            snapshot_path = built_snapshot_path
        if args.screenshot:
            screenshot_path = built_screenshot_path

    collection_urls = build_forebet_collection_urls(target.name, target.url)
    predictions: list = []
    page_summaries: list[dict[str, object]] = []

    for index, url in enumerate(collection_urls, start=1):
        result = fetch_page(
            url,
            wait_until=source.default_wait_until,
            settle_ms=source.default_settle_ms,
            headless=args.headless if args.headless else source.default_headless,
            snapshot_path=snapshot_path if index == 1 else None,
            screenshot_path=screenshot_path if index == 1 else None,
        )

        page_summaries.append(
            {
                "url": url,
                "status": result.status,
                "title": result.title,
                "html_length": result.html_length,
                "warnings": result.warnings,
                "error": result.error,
            }
        )

        if result.error:
            continue

        predictions.extend(parse_forebet_target(target.name, result.html))

    predictions = dedupe_predictions(predictions)

    print(f"source: {source.display_name}")
    print(f"target: {target.display_name}")
    print(f"sport: {target.sport}")
    print(f"collection_urls: {len(collection_urls)}")
    print(f"snapshot_path: {snapshot_path}")
    print(f"screenshot_path: {screenshot_path}")
    print("page_summaries:")
    for summary in page_summaries:
        print(f"- url: {summary['url']}")
        print(f"  status: {summary['status']}")
        print(f"  title: {summary['title']}")
        print(f"  html_length: {summary['html_length']}")
        if summary["warnings"]:
            print(f"  warnings: {summary['warnings']}")
        if summary["error"]:
            print(f"  error: {summary['error']}")

    print_prediction_preview(target.name, predictions, args.limit)


# =============================================================================
# Script Runner Guard
# =============================================================================
if __name__ == "__main__":
    main()
