from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from ganji_mtaani_agent.etl import FixtureEvaluationBuildConfig, build_fixture_evaluations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the unified fixture evaluation layer.")
    parser.add_argument(
        "--sport",
        choices=["football", "soccer", "basketball"],
        default=None,
        help="Optional sport filter for a targeted rebuild.",
    )
    parser.add_argument(
        "--limit-per-source",
        type=int,
        default=None,
        help="Optional per-source row limit for testing or targeted rebuilds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_fixture_evaluations(
        FixtureEvaluationBuildConfig(
            sport=args.sport,
            limit_per_source=args.limit_per_source,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
