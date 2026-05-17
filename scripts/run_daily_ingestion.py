from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ganji_mtaani_agent.etl import DailyIngestionConfig, run_daily_ingestion


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full daily BoB ingestion batch.")
    parser.add_argument("--date", type=str, default=date.today().isoformat(), help="Batch date in YYYY-MM-DD format.")
    parser.add_argument("--triggered-by", type=str, default="manual_cli", help="Who or what triggered the batch.")
    parser.add_argument("--bookmaker-limit", type=int, default=0, help="0 means no artificial row cap.")
    parser.add_argument("--forebet-limit", type=int, default=0, help="0 means no artificial row cap.")
    parser.add_argument("--polymarket-limit", type=int, default=200)
    parser.add_argument("--polymarket-scan-limit", type=int, default=500)
    parser.add_argument("--results-limit", type=int, default=0, help="0 means no artificial row cap.")
    parser.add_argument("--results-days-back", type=int, default=7)
    parser.add_argument("--results-days-forward", type=int, default=3)
    parser.add_argument("--notes", type=str, default=None)
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    config = DailyIngestionConfig(
        batch_date=datetime.strptime(args.date, "%Y-%m-%d").date(),
        triggered_by=args.triggered_by,
        bookmaker_limit=(None if args.bookmaker_limit <= 0 else args.bookmaker_limit),
        forebet_limit=(None if args.forebet_limit <= 0 else args.forebet_limit),
        polymarket_limit=args.polymarket_limit,
        polymarket_scan_limit=args.polymarket_scan_limit,
        results_limit=(None if args.results_limit <= 0 else args.results_limit),
        results_days_back=args.results_days_back,
        results_days_forward=args.results_days_forward,
        notes=args.notes,
    )
    summary = run_daily_ingestion(config)
    print(f"batch_id: {summary['batch_id']}")
    print(f"batch_date: {summary['batch_date']}")
    print(f"status: {summary['status']}")
    print(f"successful_sources: {summary['successful_sources']}")
    print(f"failed_sources: {summary['failed_sources']}")
    for outcome in summary["outcomes"]:
        print("---")
        print(f"task_name: {outcome.get('task_name')}")
        print(f"status: {outcome.get('status')}")
        print(f"records_found: {outcome.get('records_found')}")
        if outcome.get("error"):
            print(f"error: {outcome['error']}")


if __name__ == "__main__":
    main()
