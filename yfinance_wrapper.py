#!/usr/bin/env python
"""
YFinance-based Financials Scraper & Q&A
--------------------------------------

Purpose
- Pulls annual Income Statement & Balance Sheet from Yahoo Finance via `yfinance` for a set of tickers & years.
- Normalizes the assignment-required fields (Revenue, Gross Profit, Operating Income, Net Income, EPS; Assets, Liabilities, Equity, Cash & Cash Equivalents).
- Saves datasets to disk (JSONL, per-record JSON, CSV) and writes answers for five sample questions to text + JSON files.

Usage
-----
pip install yfinance pandas numpy

python yfinance_financials_pipeline.py \
  --tickers TSLA AAPL MSFT GOOGL AMZN \
  --years 2021 2022 2023 2024 \
  --out ./data

Notes
- `yfinance` is an unofficial scraper for Yahoo Finance. Field labels can vary; we use alias lists to improve robustness.
- Column headers returned by yfinance financials are fiscal period end dates; we map them to FY by year.
- All outputs are written under the `--out` directory.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# --------------------------- Aliases / Config ---------------------------
ALIASES = {
    "revenue": ["Total Revenue", "Revenue", "Sales", "Sales/Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Operating Income or Loss"],
    "net_income": [
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income Applicable To Common Shares",
        "Net Income From Continuing Operation Net Minority Interest",
    ],
    "eps_diluted": ["Diluted EPS", "EPS Diluted", "Diluted EPS from Continuing Operations"],
    "assets": ["Total Assets"],
    "liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "equity": ["Total Equity Gross Minority Interest", "Stockholders' Equity", "Total Stockholder Equity"],
    "cash_eq": [
        "Cash And Cash Equivalents",
        "Cash And Cash Equivalents, at Carrying Value",
        "Cash & Cash Equivalents",
    ],
}

REQUIRED_FIELDS = [
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "assets",
    "liabilities",
    "equity",
    "cash_and_cash_equivalents",
]

# --------------------------- Core Helpers ---------------------------

def get_annual_frames(ticker: str) -> Dict[str, pd.DataFrame]:
    """Return annual Income Statement and Balance Sheet DataFrames from yfinance.
    Rows are line items; columns are fiscal period end dates (Timestamps).
    """
    t = yf.Ticker(ticker)
    is_df = t.financials if hasattr(t, "financials") else pd.DataFrame()
    bs_df = t.balance_sheet if hasattr(t, "balance_sheet") else pd.DataFrame()

    # Normalize indices
    for df in (is_df, bs_df):
        if isinstance(df, pd.DataFrame) and not df.empty:
            df.index = df.index.astype(str)
    return {"is": is_df, "bs": bs_df}


def pick_year_col(df: pd.DataFrame, fiscal_year: int) -> Optional[pd.Timestamp]:
    """Pick the column in DF corresponding to the requested fiscal year.
    If exact year not found, return nearest year column.
    """
    if df is None or df.empty:
        return None
    cols = list(df.columns)
    candidates = [c for c in cols if pd.Timestamp(c).year == fiscal_year]
    if candidates:
        return sorted(candidates)[-1]
    # fallback: nearest by absolute year distance
    return (
        sorted(cols, key=lambda c: abs(pd.Timestamp(c).year - fiscal_year))[0]
        if cols else None
    )


def get_value(df: pd.DataFrame, aliases: List[str], col) -> Optional[float]:
    """Lookup a row by aliases for a given column; return float or None."""
    if df is None or df.empty or col is None:
        return None
    norm_index = {i.strip().lower(): i for i in df.index}
    for a in aliases:
        key = a.strip().lower()
        if key in norm_index:
            try:
                val = df.loc[norm_index[key], col]
                return float(val) if pd.notna(val) else None
            except Exception:
                continue
    return None


def fmt_money(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    return f"${x:,.0f}"


# --------------------------- Normalization ---------------------------

def normalize_company_year(ticker: str, year: int) -> Tuple[Optional[dict], dict]:
    """Build a normalized record for (ticker, fiscal_year) with required fields.
    Returns (record_or_None, debug_info)
    """
    frames = get_annual_frames(ticker)
    is_df, bs_df = frames["is"], frames["bs"]

    col_is = pick_year_col(is_df, year)
    col_bs = pick_year_col(bs_df, year)

    rec = {
        "ticker": ticker,
        "fiscal_year": year,
        "currency": "USD",
        "income_statement": {
            "revenue": get_value(is_df, ALIASES["revenue"], col_is),
            "gross_profit": get_value(is_df, ALIASES["gross_profit"], col_is),
            "operating_income": get_value(is_df, ALIASES["operating_income"], col_is),
            "net_income": get_value(is_df, ALIASES["net_income"], col_is),
            "eps_diluted": get_value(is_df, ALIASES["eps_diluted"], col_is),
        },
        "balance_sheet": {
            "assets": get_value(bs_df, ALIASES["assets"], col_bs),
            "liabilities": get_value(bs_df, ALIASES["liabilities"], col_bs),
            "equity": get_value(bs_df, ALIASES["equity"], col_bs),
            "cash_and_cash_equivalents": get_value(bs_df, ALIASES["cash_eq"], col_bs),
        },
        "source": {"provider": "yfinance", "urls": []},
    }

    # Acceptance checks
    missing = []
    for path in [
        ("income_statement", "revenue"),
        ("income_statement", "gross_profit"),
        ("income_statement", "operating_income"),
        ("income_statement", "net_income"),
        ("income_statement", "eps_diluted"),
        ("balance_sheet", "assets"),
        ("balance_sheet", "liabilities"),
        ("balance_sheet", "equity"),
        ("balance_sheet", "cash_and_cash_equivalents"),
    ]:
        section, key = path
        if rec[section][key] is None:
            missing.append(f"{section}.{key}")

    debug = {"missing_fields": missing, "col_is": str(col_is), "col_bs": str(col_bs)}

    if missing:
        return None, debug
    return rec, debug


# --------------------------- Q&A Routines ---------------------------

def q1_tesla_net_income_2022_vs_2021() -> dict:
    frames = get_annual_frames("TSLA")
    is_df = frames["is"]
    c2022 = pick_year_col(is_df, 2022)
    c2021 = pick_year_col(is_df, 2021)
    ni_2022 = get_value(is_df, ALIASES["net_income"], c2022)
    ni_2021 = get_value(is_df, ALIASES["net_income"], c2021)
    return {
        "question": "Tesla net income in 2022 vs 2021",
        "tsla_2022": ni_2022,
        "tsla_2021": ni_2021,
        "delta": None if (ni_2022 is None or ni_2021 is None) else ni_2022 - ni_2021,
    }


def q2_apple_cash_fy2023() -> dict:
    bs_df = get_annual_frames("AAPL")["bs"]
    c2023 = pick_year_col(bs_df, 2023)
    cash = get_value(bs_df, ALIASES["cash_eq"], c2023)
    return {"question": "Apple cash & cash equivalents in FY2023", "aapl_2023_cash": cash}


def q3_eps_2022_msft_vs_googl() -> dict:
    msft = get_annual_frames("MSFT")["is"]
    googl = get_annual_frames("GOOGL")["is"]
    c2022_msft = pick_year_col(msft, 2022)
    c2022_googl = pick_year_col(googl, 2022)
    eps_msft = get_value(msft, ALIASES["eps_diluted"], c2022_msft)
    eps_googl = get_value(googl, ALIASES["eps_diluted"], c2022_googl)
    higher = (
        "MSFT" if (eps_msft is not None and eps_googl is not None and eps_msft > eps_googl)
        else "GOOGL" if (eps_msft is not None and eps_googl is not None and eps_googl > eps_msft)
        else "Tie/N-A"
    )
    return {
        "question": "Which had higher EPS in 2022, MSFT or GOOGL?",
        "msft_eps_2022": eps_msft,
        "googl_eps_2022": eps_googl,
        "higher": higher,
    }


def q4_amazon_liab_asset_pct_2021() -> dict:
    bs_df = get_annual_frames("AMZN")["bs"]
    c2021 = pick_year_col(bs_df, 2021)
    liab = get_value(bs_df, ALIASES["liabilities"], c2021)
    assets = get_value(bs_df, ALIASES["assets"], c2021)
    pct = None
    if assets and assets != 0 and liab is not None:
        pct = 100.0 * (liab / assets)
    return {
        "question": "Amazon % assets financed by liabilities (2021)",
        "amzn_liabilities_2021": liab,
        "amzn_assets_2021": assets,
        "pct": pct,
    }


def q5_tesla_operating_income_last_3_years() -> dict:
    is_df = get_annual_frames("TSLA")["is"]
    if is_df is None or is_df.empty:
        return {"question": "Tesla operating income last 3 years", "values": []}
    cols_sorted = sorted(is_df.columns, reverse=True)
    seen_years = set()
    vals: List[Tuple[int, Optional[float]]] = []
    for c in cols_sorted:
        y = pd.Timestamp(c).year
        if y in seen_years:
            continue
        oi = get_value(is_df, ALIASES["operating_income"], c)
        vals.append((y, oi))
        seen_years.add(y)
        if len(vals) == 3:
            break
    vals = sorted(vals)  # ascending by year
    return {"question": "Tesla operating income last 3 FY", "values": vals}


# --------------------------- IO Helpers ---------------------------

def ensure_dirs(out: Path):
    (out / "normalized").mkdir(parents=True, exist_ok=True)
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "derived").mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, records: List[dict]):
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_csv(path: Path, records: List[dict]):
    df = pd.DataFrame(records)
    header = not path.exists()
    df.to_csv(path, mode="a", index=False, header=header)


# --------------------------- Main Runner ---------------------------

def run_pipeline(tickers: List[str], years: List[int], out_dir: str):
    out = Path(out_dir)
    ensure_dirs(out)

    normalized_records: List[dict] = []
    log_rows: List[dict] = []

    for ticker in tickers:
        for yr in years:
            rec, dbg = normalize_company_year(ticker, yr)
            dbg_row = {"ticker": ticker, "year": yr, **dbg}
            log_rows.append(dbg_row)

            if rec is None:
                continue

            # write individual JSON
            single_json = out / "normalized" / f"{ticker}_{yr}.json"
            single_json.write_text(json.dumps(rec, indent=2))
            normalized_records.append(rec)

    # bulk outputs
    if normalized_records:
        write_jsonl(out / "normalized" / "financials.jsonl", normalized_records)
        append_csv(out / "normalized" / "financials_by_year.csv", normalized_records)

    # log
    pd.DataFrame(log_rows).to_csv(out / "SCRAPER_LOG.csv", index=False)

    # Data dictionary
    dd = {
        "ticker": "Stock ticker",
        "fiscal_year": "Fiscal year (int)",
        "currency": "USD",
        "income_statement": {
            "revenue": "Total revenue",
            "gross_profit": "Gross profit",
            "operating_income": "Operating income (EBIT)",
            "net_income": "Net income",
            "eps_diluted": "Diluted EPS",
        },
        "balance_sheet": {
            "assets": "Total assets",
            "liabilities": "Total liabilities",
            "equity": "Shareholders' equity",
            "cash_and_cash_equivalents": "Cash & cash equivalents",
        },
        "source": {"provider": "yfinance", "urls": []},
    }
    (out / "DATA_DICTIONARY.json").write_text(json.dumps(dd, indent=2))

    # ---------- Answer the five questions ----------
    answers = [
        q1_tesla_net_income_2022_vs_2021(),
        q2_apple_cash_fy2023(),
        q3_eps_2022_msft_vs_googl(),
        q4_amazon_liab_asset_pct_2021(),
        q5_tesla_operating_income_last_3_years(),
    ]
    # Write text
    lines = []
    for a in answers:
        q = a.get("question", "Question")
        lines.append(q)
        for k, v in a.items():
            if k == "question":
                continue
            if isinstance(v, (int, float)):
                lines.append(f"  - {k}: {v:,.2f}")
            else:
                lines.append(f"  - {k}: {v}")
        lines.append("")
    (out / "answers.txt").write_text("\n".join(lines))
    # Write JSON
    (out / "answers.json").write_text(json.dumps(answers, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="YFinance Financials Scraper & QnA")
    p.add_argument("--tickers", nargs="+", required=True, help="Tickers to process")
    p.add_argument("--years", nargs="+", type=int, required=True, help="Fiscal years e.g., 2021 2022 2023")
    p.add_argument("--out", required=True, help="Output directory")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args.tickers, args.years, args.out)
