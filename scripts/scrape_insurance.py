from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ganji_mtaani_agent.insurance.pipeline import get_registered_sources, scrape_source_target
from ganji_mtaani_agent.insurance.sources import INSURANCE_SOURCES


def main() -> None:
    """Fetch and parse all insurance products for one source + target combination.

    Run from the project root:

        python scripts\\scrape_insurance.py --source jubilee --target health
        python scripts\\scrape_insurance.py --source jubilee --target health --output-json data/jubilee_health.json
        python scripts\\scrape_insurance.py --source jubilee --target life --delay 3

    Registered sources (parser implemented):
        jubilee

    All sources in sources.py (parser pending):
        britam, cic, old_mutual, sanlam, icea_lion, aar, apa, absa_life
    """

    parser = argparse.ArgumentParser(
        description="Run the insurance scrape pipeline for one source + target.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=sorted(INSURANCE_SOURCES),
        default="jubilee",
        help="Insurance source slug (default: jubilee).",
    )
    parser.add_argument(
        "--target",
        help="Target key under the source, e.g. 'health', 'life'. Defaults to source default.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="Wait between consecutive detail-page requests (default: 2.0s).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Force a visible browser window.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        metavar="FILE",
        help="Save parsed products to a JSON file instead of printing.",
    )
    args = parser.parse_args()

    registered = get_registered_sources()
    if args.source not in registered:
        print(
            f"[error] no parser implemented for '{args.source}' yet.\n"
            f"        Registered: {registered}\n"
            f"        To add one, implement parsers/{args.source}.py and register it in pipeline.py."
        )
        sys.exit(1)

    products = scrape_source_target(
        args.source,
        args.target,
        delay_s=args.delay,
        headless=not args.headed,
    )

    if not products:
        print("[done] no products were parsed.")
        return

    if args.output_json:
        rows = [dataclasses.asdict(p) for p in products]
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[output] {len(products)} products → {args.output_json}")
    else:
        for product in products:
            print(f"\n{'-' * 60}")
            print(f"  {product.product_name}")
            if product.tagline:
                print(f"  {product.tagline}")
            print(f"  url:        {product.product_url}")
            print(f"  confidence: {product.confidence}")
            print(f"  benefits:   {len(product.key_benefits)}")
            for benefit in product.key_benefits[:4]:
                print(f"    • {benefit}")
            if len(product.key_benefits) > 4:
                print(f"    … and {len(product.key_benefits) - 4} more")
            if product.target_audience:
                print(f"  audience:   {product.target_audience}")
            if product.extra_data.get("faqs"):
                print(f"  FAQs:       {len(product.extra_data['faqs'])} Q&A pairs")
        print(f"\n[done] {len(products)} products parsed.")


if __name__ == "__main__":
    main()
