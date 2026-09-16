"""Run the pipeline: Dune API -> clean CSV tables for Power BI.

Usage:
    python main.py            # fetch from the API (falls back to cache)
    python main.py --offline  # use cached raw results only
"""
import argparse
import sys

from extract import extract_all
from transform import save_tables, transform_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Dune API pipeline")
    parser.add_argument("--offline", action="store_true", help="use cached results in data/raw")
    args = parser.parse_args()

    raw = extract_all(offline=args.offline)
    tables, checks = transform_all(raw)
    save_tables(tables, checks)

    print("\nQuality checks:")
    for row in checks.itertuples():
        print(f"  [{row.status:7}] {row.check} — {row.detail}")

    failed = (checks["status"] == "fail").sum()
    print(f"\n{len(tables)} tables written to data/clean/. Failed checks: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
