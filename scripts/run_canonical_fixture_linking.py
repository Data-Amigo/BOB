from __future__ import annotations

import argparse
from datetime import date

from ganji_mtaani_agent.etl.canonical_fixtures import CanonicalBuildConfig, SOURCE_TABLES, build_canonical_fixtures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build canonical fixtures and source links from raw BoB tables.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Reference batch date in YYYY-MM-DD format.")
    parser.add_argument("--limit-per-source", type=int, default=500, help="Maximum unlinked rows to inspect per source table.")
    parser.add_argument(
        "--include-linked-rows",
        action="store_true",
        help="Refresh already-linked source rows too, useful for backfilling normalized date/time fields.",
    )
    parser.add_argument(
        "--source-table",
        action="append",
        dest="source_tables",
        choices=SOURCE_TABLES,
        help="Restrict the run to one or more source tables. Repeat the flag to include several tables.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = CanonicalBuildConfig(
        batch_date=date.fromisoformat(args.date),
        source_tables=tuple(args.source_tables) if args.source_tables else SOURCE_TABLES,
        limit_per_source=args.limit_per_source,
        include_linked_rows=args.include_linked_rows,
    )
    summary = build_canonical_fixtures(config)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
