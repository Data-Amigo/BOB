"""Forebet collection helpers for broader daily coverage.

This module does not fetch pages itself. It only defines which Forebet URLs are
worth collecting for a target so the ETL layer can widen coverage without
hardcoding link lists in multiple places.
"""

from __future__ import annotations

FOREBET_BASE_URL = "https://www.forebet.com"


# The main "today" page exposes region-level prediction-list links whose counts
# add up to far more fixtures than the single landing page currently renders.
# We prefer those list pages over alternative market tabs because they are much
# more likely to add breadth instead of repeating the exact same fixtures with a
# different market view.
FOREBET_FOOTBALL_TODAY_PATHS: tuple[str, ...] = (
    "/en/football-tips-and-predictions-for-today",
    "/en/football-tips-and-predictions-for-today/by-league",
    "/en/prediction-lists/united-kingdom",
    "/en/prediction-lists/all-europe",
    "/en/prediction-lists/america",
    "/en/prediction-lists/africa",
    "/en/prediction-lists/asia",
    "/en/prediction-lists/australia",
    "/en/prediction-lists/international",
    "/en/prediction-lists/national-cups",
)

FOREBET_BASKETBALL_TODAY_PATHS: tuple[str, ...] = (
    "/en/basketball/predictions-today",
)

# The yesterday football results page also has a by-league variant that widens
# coverage without switching into unrelated market tabs. We keep this set
# conservative until we validate more yesterday-specific subpages.
FOREBET_FOOTBALL_YESTERDAY_PATHS: tuple[str, ...] = (
    "/en/football-predictions-from-yesterday",
    "/en/football-predictions-from-yesterday/by-league",
)

FOREBET_BASKETBALL_YESTERDAY_PATHS: tuple[str, ...] = (
    "/en/basketball/predictions-yesterday",
)


def _to_absolute_forebet_url(path_or_url: str) -> str:
    """Return an absolute Forebet URL from either a path or a full URL."""

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return f"{FOREBET_BASE_URL}{path_or_url}"


def _dedupe_urls(urls: list[str]) -> list[str]:
    """Deduplicate URLs while preserving order."""

    deduped: list[str] = []
    seen: set[str] = set()

    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)

    return deduped


def build_forebet_collection_urls(target_name: str, primary_url: str | None = None) -> list[str]:
    """Return the ordered list of Forebet URLs to collect for a target."""

    urls: list[str] = []
    if primary_url:
        urls.append(_to_absolute_forebet_url(primary_url))

    if target_name == "football_today":
        urls.extend(_to_absolute_forebet_url(path) for path in FOREBET_FOOTBALL_TODAY_PATHS)
        return _dedupe_urls(urls)

    if target_name == "basketball_today":
        urls.extend(_to_absolute_forebet_url(path) for path in FOREBET_BASKETBALL_TODAY_PATHS)
        return _dedupe_urls(urls)

    if target_name == "football_yesterday":
        urls.extend(_to_absolute_forebet_url(path) for path in FOREBET_FOOTBALL_YESTERDAY_PATHS)
        return _dedupe_urls(urls)

    if target_name == "basketball_yesterday":
        urls.extend(_to_absolute_forebet_url(path) for path in FOREBET_BASKETBALL_YESTERDAY_PATHS)
        return _dedupe_urls(urls)

    raise ValueError(f"No Forebet collection URL set is configured for target {target_name!r}.")
