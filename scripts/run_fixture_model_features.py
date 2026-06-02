from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ganji_mtaani_agent.etl.fixture_model_features import (  # noqa: E402
    FixtureModelFeatureBuildConfig,
    build_fixture_model_features,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build fixture-level model feature rows from historical form data.")
    parser.add_argument("--sport", help="Optional sport filter, e.g. football or basketball.")
    parser.add_argument("--limit", type=int, help="Optional row limit for faster smoke runs.")
    parser.add_argument("--window-size", type=int, default=5, help="Historical window size. Defaults to 5.")
    args = parser.parse_args()

    summary = build_fixture_model_features(
        FixtureModelFeatureBuildConfig(
            sport=args.sport,
            limit=args.limit,
            window_size=args.window_size,
        )
    )
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
