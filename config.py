"""Configuration: query IDs, paths and period settings."""
from pathlib import Path

# Dune query IDs from the project "solana-jupiter-trading-analysis".
# Chart variants (Q2a/b, Q3a/b, Q5a, Q6c/e) and C3 are not needed:
# Power BI computes sorting, top-N and min/max itself.
# Q6b is not needed: Q6 already contains the DEX names.
QUERIES = {
    "q1_baseline":            8724188,
    "c1_coverage":            8724689,
    "c2_fee_coverage":        8732013,
    "q2_tokens_by_count":     8724549,
    "q3_tokens_by_volume":    8726202,
    "q4_token_categories":    8725347,
    "q5_category_distribution": 8725434,
    "q6_dex_usage":           8725506,
    "q7_routing":             8725850,
    "q8_fee_rate":            8726471,
    "q9_weekly_categories":   8726069,
    # Part 2 — final output token per Jupiter route
    "q10_route_types":              8760232,
    "q11_final_output_categories":  8760274,
    "q13_weekly_final_output":      8760447,
    "q14_intermediate_tokens":      8760737,
}

API_BASE = "https://api.dune.com/api/v1"
PAGE_SIZE = 5000          # rows per API request
REQUEST_TIMEOUT = 60      # seconds
MAX_RETRIES = 3

PERIOD_START = "2026-01-01"
PERIOD_END = "2026-07-01"   # exclusive

# How a category was assigned to an observation.
#   all_events   — every swap event output is counted (Part 1, Q5/Q9)
#   final_output — only the final token of a non-circular route (Part 2, Q11/Q13)
METHOD_ALL_EVENTS = "all_events"
METHOD_FINAL_OUTPUT = "final_output"

BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "data" / "raw"
CLEAN_DIR = BASE_DIR / "data" / "clean"
