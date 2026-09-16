# Dune API Pipeline — Jupiter v6 Trading Data for Power BI

A small ETL pipeline: stored query results are fetched from the Dune API,
cleaned and checked in Python, and modelled as a star schema for Power BI.

**Data source:** [solana-jupiter-trading-analysis](https://github.com/Amirhoushang/solana-jupiter-trading-analysis)
— SQL analysis of Jupiter v6 swaps on Solana, H1 2026.

```
Dune (SQL on 465M rows) → Dune API → Python (extract, clean, check, model) → CSV → Power BI
```

Heavy computation stays in SQL on Dune. Python handles what SQL results do not:
cleaning, validation across queries, and a model built for a BI tool.

---

## What the pipeline does

**Extract** (`extract.py`)
- Reads the latest stored result of 11 queries. Queries are never re-executed.
- Paginates, retries on rate limits and server errors, validates row counts.
- Caches every result in `data/raw/`, so the pipeline also runs without the API.

**Clean** (`transform.py`)
- Removes null bytes from token symbols (e.g. `ZEC\x00\x00…`).
- Corrects wrong or missing metadata by mint address (`test` → PENGU, `SPLT` → BIRB, missing → bSOL).
- Parses Dune timestamps and enforces numeric types.

**Check** — 16 automated checks, written to `data/clean/quality_checks.csv`
- Cross-query totals: event and transaction totals in Q5, Q6, Q7, C2 and Q9 must equal Q1.
- Shares sum to 100%; each week in Q9 sums to 100%.
- Every top-100 token is mapped; no unknown categories.
- `approx_distinct` estimates above exact event counts are flagged as warnings.

**Model** — star schema in `data/clean/`

| Table | Grain |
|---|---|
| `dim_token` | one row per mapped token (105) |
| `dim_category` | one row per category |
| `dim_dex` | one row per DEX program (89) |
| `dim_week` | one row per week, with partial-week flag |
| `fact_token_activity` | token |
| `fact_category_distribution` | category × mapping method × method |
| `fact_dex_usage` | DEX program |
| `fact_routing` | category × method |
| `fact_fees` | category × method, with fee-event coverage |
| `fact_weekly_category` | week × category × method |
| `kpi_baseline` | single row of headline figures |

The `method` column is `all_events` for now. A planned second part of the source
project assigns categories by final output token; its results will be added as
`final_output` rows to the same tables, without changing the model.

---

## Setup

Requires Python 3.10+. Tested on Linux.

**With Miniconda (recommended)**

```bash
conda env create -f environment.yml
conda activate dune-api
```

**With venv (alternative)**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**API key**

```bash
cp .env.example .env    # then add your Dune API key to .env
```

## Run

```bash
python main.py            # fetch from the API, fall back to cache on failure
python main.py --offline  # use cached results only, no API key needed
```

The exit code is 1 if any check fails, so the pipeline can be used in automation.

`data/raw/` holds a snapshot of the query results and is part of the repository,
so the pipeline can be reproduced with `--offline` without a Dune account.

## Power BI

Load all CSVs from `data/clean/`. Relationships:

- `dim_token[token_mint]` → `fact_token_activity[token_mint]`
- `dim_category[category]` → `fact_category_distribution`, `fact_routing`, `fact_fees`, `fact_weekly_category`
- `dim_dex[dex_program]` → `fact_dex_usage[dex_program]`
- `dim_week[week_start]` → `fact_weekly_category[week_start]`

Add a slicer on `method`.

---

## Limitations

- The pipeline reads results; it does not change them. All analytical limitations
  of the source project apply (intermediate hops, price coverage, fee-event coverage).
- Columns ending in `_est` are `approx_distinct` estimates (~2% error).
- `fact_token_activity` combines the top 100 by events and the top 50 by priced
  volume; five tokens only have volume figures.

## Security

The API key is read from `.env`, which is excluded by `.gitignore`. Never commit it.
