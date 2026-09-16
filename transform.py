"""Transform: clean the raw query results, run quality checks and build
a star schema (dimension + fact tables) for Power BI."""
import pandas as pd

import config

# Token metadata in Dune is partly wrong or missing. Corrections verified
# manually on Solscan in the source project (see Q4 comments).
SYMBOL_OVERRIDES = {
    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv": "PENGU",    # Dune: 'test'
    "G7vQWurMkMMm2dU3iZpXYFTHT9Biio4F4gZCrwFpKNwG": "BIRB",     # Dune: 'SPLT'
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": "bSOL",     # no metadata
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": "INF",      # prices: 'SCNSOL'
    "5Y8NV33Vv7WbnLfq3zBcKSdYPrk7g2KoiQoe7M2tcxp5": "ONyc",     # Dune: 'ONe'
    "Es9vdPD6sXzHhbAskU19WFnAtyRo94HKrGrPSdQ3aSSB": "USDT (impostor)",
}

CATEGORY_ORDER = [
    "Stablecoin", "Native Solana", "Meme Coin", "Cross-Chain Asset",
    "Liquid Staking", "Tokenized RWA", "Other", "Unmapped",
]


# --------------------------------------------------------------------------
# Cleaning helpers
# --------------------------------------------------------------------------
def clean_text(series: pd.Series) -> pd.Series:
    """Remove null bytes and surrounding whitespace; empty strings -> NA."""
    s = series.astype("string").str.replace("\x00", "", regex=False).str.strip()
    return s.mask(s == "", pd.NA)


def to_utc_timestamp(series: pd.Series) -> pd.Series:
    """Parse Dune timestamps like '2026-01-01 00:00:00.000 UTC'."""
    s = series.astype("string").str.replace(" UTC", "", regex=False)
    return pd.to_datetime(s, utc=True).dt.tz_localize(None)


def to_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# --------------------------------------------------------------------------
# Quality checks
# --------------------------------------------------------------------------
class Checks:
    def __init__(self):
        self.rows = []

    def add(self, name: str, passed: bool, detail: str, severity: str = "error"):
        self.rows.append({
            "check": name,
            "status": "pass" if passed else ("fail" if severity == "error" else "warning"),
            "detail": detail,
        })

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def flag_approx_above_exact(df, approx_col, exact_col, label, checks):
    """approx_distinct can exceed the exact event count, which is impossible."""
    mask = df[approx_col] > df[exact_col]
    df[f"{approx_col}_exceeds_events"] = mask
    checks.add(
        f"{label}: {approx_col} <= {exact_col}",
        not mask.any(),
        f"{int(mask.sum())} row{'s' if mask.sum() != 1 else ''} where the estimate exceeds exact events (flagged)",
        severity="warning",
    )
    return df


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------
def build_dim_token(q2, q3, q4):
    tokens = q4[["token_mint", "category", "flag"]].copy()
    tokens["category"] = clean_text(tokens["category"])
    tokens["flag"] = clean_text(tokens["flag"])

    sym_q2 = q2.set_index("token_mint")["symbol"]
    sym_q3 = q3.set_index("token_mint")["symbol"]
    tokens["symbol"] = (
        tokens["token_mint"].map(SYMBOL_OVERRIDES)
        .fillna(tokens["token_mint"].map(sym_q2))
        .fillna(tokens["token_mint"].map(sym_q3))
    )
    tokens["name"] = tokens["token_mint"].map(q2.set_index("token_mint")["name"])
    tokens["in_top100_by_count"] = tokens["token_mint"].isin(q2["token_mint"])
    return tokens[["token_mint", "symbol", "name", "category", "flag", "in_top100_by_count"]]


def build_dim_category():
    return pd.DataFrame({
        "category": CATEGORY_ORDER,
        "sort_order": range(1, len(CATEGORY_ORDER) + 1),
        "is_classified": [c != "Unmapped" for c in CATEGORY_ORDER],
    })


def build_dim_dex(q6):
    dex = q6[["dex_program", "dex_name"]].drop_duplicates("dex_program").copy()
    dex["is_named"] = dex["dex_name"] != "Unmapped"
    dex["dex_label"] = dex["dex_name"].where(dex["is_named"], "Unmapped " + dex["dex_program"].str[:6])
    return dex


def build_dim_week(q9):
    start, end = pd.Timestamp(config.PERIOD_START), pd.Timestamp(config.PERIOD_END)
    weeks = pd.DataFrame({"week_start": sorted(q9["week_start"].unique())})
    weeks["week_end"] = weeks["week_start"] + pd.Timedelta(days=6)
    weeks["is_partial"] = (weeks["week_start"] < start) | (weeks["week_start"] + pd.Timedelta(days=7) > end)
    first_day = weeks["week_start"].clip(lower=start)
    last_day = weeks["week_end"].clip(upper=end - pd.Timedelta(days=1))
    weeks["days_in_period"] = (last_day - first_day).dt.days + 1
    weeks["week_number"] = range(1, len(weeks) + 1)
    return weeks


# --------------------------------------------------------------------------
# Main transform
# --------------------------------------------------------------------------
def transform_all(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    checks = Checks()
    method = config.METHOD

    # --- clean raw frames ------------------------------------------------
    q1 = to_numeric(raw["q1_baseline"].copy(), [
        "total_swap_events", "total_user_swaps", "total_traders", "dex_programs_used",
        "distinct_input_tokens", "distinct_output_tokens"])
    for col in ("first_swap", "last_swap"):
        q1[col] = to_utc_timestamp(q1[col])

    c1 = to_numeric(raw["c1_coverage"].copy(), ["pct_top_100", "pct_top_500"])

    q2 = raw["q2_tokens_by_count"].copy()
    for col in ("token_mint", "symbol", "name"):
        q2[col] = clean_text(q2[col])
    q2 = to_numeric(q2, ["decimals", "user_swaps", "swap_events", "traders"])
    q2 = flag_approx_above_exact(q2, "user_swaps", "swap_events", "Q2", checks)

    q3 = raw["q3_tokens_by_volume"].copy()
    for col in ("token_mint", "symbol"):
        q3[col] = clean_text(q3[col])
    q3 = to_numeric(q3, ["volume_usd", "swap_events", "user_swaps", "avg_size_usd"])
    q3 = flag_approx_above_exact(q3, "user_swaps", "swap_events", "Q3", checks)

    q4 = raw["q4_token_categories"].copy()
    q4["token_mint"] = clean_text(q4["token_mint"])

    q5 = raw["q5_category_distribution"].copy()
    for col in ("category", "mapping_method"):
        q5[col] = clean_text(q5[col])
    q5 = to_numeric(q5, ["swap_events", "user_swaps", "traders", "dex_programs", "pct_of_swap_events"])
    q5 = flag_approx_above_exact(q5, "user_swaps", "swap_events", "Q5", checks)

    q6 = raw["q6_dex_usage"].copy()
    for col in ("dex_name", "dex_program"):
        q6[col] = clean_text(q6[col])
    q6 = to_numeric(q6, ["swap_events", "user_swaps", "distinct_tokens", "traders", "pct_of_swap_events"])
    q6 = flag_approx_above_exact(q6, "user_swaps", "swap_events", "Q6", checks)

    q7 = raw["q7_routing"].copy()
    q7["category"] = clean_text(q7["category"])
    q7 = to_numeric(q7, ["user_swaps", "swap_events", "legs_per_swap"])

    q8 = raw["q8_fee_rate"].copy()
    q8["category"] = clean_text(q8["category"])
    q8 = to_numeric(q8, ["transactions", "total_fees_usd", "volume_usd", "avg_fee_usd", "fee_bps"])

    c2 = raw["c2_fee_coverage"].copy()
    c2["category"] = clean_text(c2["category"])
    c2 = to_numeric(c2, ["all_tx", "tx_with_fee", "pct_with_fee"])

    q9 = raw["q9_weekly_categories"].copy()
    q9["category"] = clean_text(q9["category"])
    q9["week_start"] = to_utc_timestamp(q9["week"]).dt.normalize()
    q9 = to_numeric(q9, ["swap_events", "pct_of_week"])

    # --- consistency checks ----------------------------------------------
    b = q1.iloc[0]
    checks.add("Q4: 105 unique token mints", q4["token_mint"].nunique() == 105 and len(q4) == 105,
               f"{len(q4)} rows, {q4['token_mint'].nunique()} unique")
    missing = set(q2["token_mint"]) - set(q4["token_mint"])
    checks.add("Q2: all top-100 tokens mapped in Q4", not missing, f"{len(missing)} unmapped")
    checks.add("Q5: event total equals Q1", q5["swap_events"].sum() == b["total_swap_events"],
               f"{q5['swap_events'].sum():,} vs {b['total_swap_events']:,}")
    checks.add("Q5: shares sum to 100%", abs(q5["pct_of_swap_events"].sum() - 100) < 0.01,
               f"{q5['pct_of_swap_events'].sum():.4f}")
    checks.add("Q6: event total equals Q1", q6["swap_events"].sum() == b["total_swap_events"],
               f"{q6['swap_events'].sum():,} vs {b['total_swap_events']:,}")
    checks.add("Q6: program count equals Q1", len(q6) == b["dex_programs_used"],
               f"{len(q6)} vs {b['dex_programs_used']}")
    checks.add("Q7: transactions equal Q1", q7["user_swaps"].sum() == b["total_user_swaps"],
               f"{q7['user_swaps'].sum():,} vs {b['total_user_swaps']:,}")
    checks.add("Q7: legs_per_swap >= 1", (q7["legs_per_swap"] >= 1).all(),
               f"min {q7['legs_per_swap'].min():.4f}")
    checks.add("C2: transactions equal Q1", c2["all_tx"].sum() == b["total_user_swaps"],
               f"{c2['all_tx'].sum():,} vs {b['total_user_swaps']:,}")
    weekly = q9.groupby("week_start")["pct_of_week"].sum()
    checks.add("Q9: each week sums to 100%", ((weekly - 100).abs() < 0.01).all(),
               f"max deviation {(weekly - 100).abs().max():.6f}")
    checks.add("Q9: event total equals Q1", q9["swap_events"].sum() == b["total_swap_events"],
               f"{q9['swap_events'].sum():,} vs {b['total_swap_events']:,}")
    unknown = set(q5["category"]) - set(CATEGORY_ORDER)
    checks.add("Categories known", not unknown, f"unknown: {sorted(unknown) or 'none'}")

    # --- dimensions ------------------------------------------------------
    dim_token = build_dim_token(q2, q3, q4)
    dim_category = build_dim_category()
    dim_dex = build_dim_dex(q6)
    dim_week = build_dim_week(q9)

    # --- facts -----------------------------------------------------------
    fact_token_activity = (
        q2[["token_mint", "swap_events", "user_swaps", "traders", "user_swaps_exceeds_events"]]
        .rename(columns={"user_swaps": "transactions_est", "traders": "signers_est",
                         "user_swaps_exceeds_events": "estimate_exceeds_events"})
        .merge(
            q3[["token_mint", "volume_usd", "swap_events", "avg_size_usd"]]
            .rename(columns={"swap_events": "priced_swap_events", "avg_size_usd": "avg_priced_event_usd"}),
            on="token_mint", how="outer",
        )
    )
    fact_token_activity["in_volume_top50"] = fact_token_activity["volume_usd"].notna()
    fact_token_activity["method"] = method

    fact_category_distribution = q5.rename(columns={
        "user_swaps": "transactions_est", "traders": "signers_est",
        "dex_programs": "dex_programs_est", "user_swaps_exceeds_events": "estimate_exceeds_events",
    })
    fact_category_distribution["method"] = method

    fact_dex_usage = q6.drop(columns=["dex_name"]).rename(columns={
        "user_swaps": "transactions_est", "distinct_tokens": "output_tokens_est",
        "traders": "signers_est", "user_swaps_exceeds_events": "estimate_exceeds_events",
    })

    fact_routing = q7.rename(columns={
        "user_swaps": "transactions", "swap_events": "dominant_category_events",
        "legs_per_swap": "events_per_transaction",
    })
    fact_routing["method"] = method

    fact_fees = c2.merge(q8, on="category", how="left").rename(columns={
        "all_tx": "transactions_total", "tx_with_fee": "transactions_with_fee_event",
        "pct_with_fee": "fee_event_coverage_pct", "transactions": "transactions_in_fee_ratio",
        "volume_usd": "priced_event_volume_usd",
    })
    fact_fees["fee_ratio_inclusion_pct"] = (
        fact_fees["transactions_in_fee_ratio"] / fact_fees["transactions_total"] * 100
    )
    fact_fees["method"] = method

    fact_weekly_category = q9[["week_start", "category", "swap_events", "pct_of_week"]].copy()
    fact_weekly_category["method"] = method

    kpi_baseline = q1.assign(
        avg_events_per_transaction=q1["total_swap_events"] / q1["total_user_swaps"],
        pct_events_top_100_tokens=c1["pct_top_100"].iloc[0],
        pct_events_top_500_tokens=c1["pct_top_500"].iloc[0],
    )

    tables = {
        "dim_token": dim_token,
        "dim_category": dim_category,
        "dim_dex": dim_dex,
        "dim_week": dim_week,
        "fact_token_activity": fact_token_activity,
        "fact_category_distribution": fact_category_distribution,
        "fact_dex_usage": fact_dex_usage,
        "fact_routing": fact_routing,
        "fact_fees": fact_fees,
        "fact_weekly_category": fact_weekly_category,
        "kpi_baseline": kpi_baseline,
    }
    return tables, checks.to_frame()


def save_tables(tables: dict[str, pd.DataFrame], checks: pd.DataFrame) -> None:
    config.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(config.CLEAN_DIR / f"{name}.csv", index=False)
    checks.to_csv(config.CLEAN_DIR / "quality_checks.csv", index=False)
