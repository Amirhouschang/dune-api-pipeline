# Dune API Pipeline — Jupiter v6 Trading Data for Power BI

A small ETL pipeline: stored query results are fetched from the Dune API,
cleaned and checked in Python, and modelled as a star schema for Power BI.

**Data source:** [solana-jupiter-trading-analysis](https://github.com/Amirhouschang/solana-jupiter-trading-analysis)
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

## Power BI dashboard

File: `powerbi/jupiter_trading_dashboard.pbix` (Power BI Desktop, Windows)

### Model

All CSVs from `data/clean/` are loaded; `data/raw/` is not used by Power BI.

![Data model](powerbi/screenshots/00_data_model.png)

Relationships (all one-to-many, single direction, from dimension to fact):

- `dim_category[category]` → `fact_category_distribution`, `fact_routing`, `fact_fees`, `fact_weekly_category`, `dim_token`
- `dim_token[token_mint]` → `fact_token_activity[token_mint]`
- `dim_dex[dex_program]` → `fact_dex_usage[dex_program]`
- `dim_week[week_start]` → `fact_weekly_category[week_start]`
- `dim_method[method]` → `method` in all category and token fact tables

`dim_method` is a calculated table built in Power BI from the distinct `method`
values. One slicer on it filters every fact table at once.

`kpi_baseline` and `quality_checks` have no relationships: the first holds
single-row headline figures, the second the pipeline check log.
`dim_dex` / `fact_dex_usage` form a separate star, because the DEX query is
not broken down by category, token or week.

### Measures

Shares and ratios are recomputed as DAX measures instead of summing
pre-computed columns, so they stay correct under any filter:

| Measure | Definition |
|---|---|
| `Share of Events %` | category swap events / all swap events |
| `Weekly Share %` | category swap events / all swap events in the week |
| `Events per Transaction` | dominant-category events / transactions |
| `Fee bps` | recorded fees × 10,000 / priced event-output volume |
| `Fee Event Coverage %` | transactions with a fee event / all transactions |
| `DEX Share %` | program swap events / all swap events |
| `Avg Priced Event USD` | priced volume / priced swap events |
| `Category Color`, `Token Category Color`, `Status Color` | consistent colours across visuals |
| `Checks Passed` / `Warning` / `Failed` | counts from `quality_checks` |

Estimated distinct counts (`_est`) are never summed across categories,
because the same signer or transaction can appear in several groups.

### Pages

**1. Overview** — headline KPIs, weekly swap events, key findings

![Overview](powerbi/screenshots/01_overview.png)

**2. Tokens** — top 10 by estimated transactions vs. top 10 by priced
event-output volume, with a full token table

![Tokens](powerbi/screenshots/02_tokens.png)

**3. Categories** — share of swap events by category, weekly composition,
and the split between manually mapped and suffix-matched tokens

![Categories](powerbi/screenshots/03_categories.png)

**4. Routing & Fees** — dominant-category events per transaction, recorded
fee ratio, and the fee-event coverage the ratio depends on

![Routing & Fees](powerbi/screenshots/04_routing_fees.png)

**5. DEX Programs** — top 10 programs and all 89 programs Jupiter routed through

![DEX Programs](powerbi/screenshots/05_dex_programs.png)

**6. Data Quality** — results of the 16 automated pipeline checks

![Data Quality](powerbi/screenshots/06_data_quality.png)

### Refreshing

After re-running the pipeline, **refresh** the Power BI model. The generated CSV files must keep the same names and paths.

---

## Repository structure

```
dune-api-pipeline/
├── README.md
├── environment.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── config.py            # query IDs, paths, period
├── extract.py           # Dune API client with caching
├── transform.py         # cleaning, checks, star schema
├── main.py              # pipeline entry point
├── data/
│   ├── raw/             # cached API results
│   └── clean/           # tables for Power BI
└── powerbi/
    ├── jupiter_trading_dashboard.pbix
    └── screenshots/
```

---

## Limitations

- The pipeline reads results; it does not change them. All analytical limitations
  of the source project apply (intermediate hops, price coverage, fee-event coverage).
- Columns ending in `_est` are `approx_distinct` estimates (~2% error).
- `fact_token_activity` combines the top 100 by events and the top 50 by priced
  volume; five tokens only have volume figures, and tokens outside the top 50
  have no volume. Blank values in the dashboard reflect this.
- The dashboard describes execution activity. Event outputs include intermediate
  routing hops, and the fee ratio covers only 0.12–7.85% of transactions per category.

## Security

The API key is read from `.env`, which is excluded by `.gitignore`. Never commit it.
