#!/usr/bin/env python3
"""Fetch beta values from Yahoo Finance via yfinance OLS regression and populate manual_beta_overrides.json."""

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yfinance as yf

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "manual_beta_overrides.json"


def compute_beta_regression(ticker: str, market_ticker: str = "^GSPC", years: int = 3, freq: str = "1wk"):
    """Compute beta via OLS regression of weekly returns against the market.

    Returns (beta, r_squared, n_observations) or (None, None, None) on failure.
    """
    end = date.today()
    start = end - timedelta(days=years * 365)

    try:
        fund = yf.download(ticker, start=str(start), end=str(end), interval=freq, progress=False, auto_adjust=True)
        market = yf.download(market_ticker, start=str(start), end=str(end), interval=freq, progress=False, auto_adjust=True)
    except Exception:
        return None, None, None, "ERROR: download failed"

    if fund.empty or market.empty or len(fund) < 20 or len(market) < 20:
        return None, None, None, "INSUFFICIENT_DATA"

    # Align by date
    fund_close = fund["Close"].squeeze()
    market_close = market["Close"].squeeze()
    combined = fund_close.to_frame("fund").join(market_close.to_frame("market"), how="inner").dropna()

    if len(combined) < 20:
        return None, None, None, "INSUFFICIENT_DATA"

    # Compute percentage returns
    fund_ret = combined["fund"].pct_change().dropna()
    mkt_ret = combined["market"].pct_change().dropna()

    # Align after pct_change
    idx = fund_ret.index.intersection(mkt_ret.index)
    fund_ret = fund_ret.loc[idx].values
    mkt_ret = mkt_ret.loc[idx].values

    n = len(fund_ret)
    if n < 15:
        return None, None, None, "INSUFFICIENT_DATA"

    # OLS: fund_ret = alpha + beta * mkt_ret
    x_mean = np.mean(mkt_ret)
    y_mean = np.mean(fund_ret)
    ss_xy = np.sum((mkt_ret - x_mean) * (fund_ret - y_mean))
    ss_xx = np.sum((mkt_ret - x_mean) ** 2)

    if ss_xx == 0:
        return None, None, None, "ERROR: zero variance in market returns"

    beta = ss_xy / ss_xx
    alpha = y_mean - beta * x_mean

    # R²
    y_pred = alpha + beta * mkt_ret
    ss_res = np.sum((fund_ret - y_pred) ** 2)
    ss_tot = np.sum((fund_ret - y_mean) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Reasonableness flags
    status = "OK"
    if abs(beta) > 3.0:
        status = "SUSPICIOUS: |beta| > 3.0"
    elif beta < -0.5:
        status = "SUSPICIOUS: negative beta for equity"
    elif r_squared < 0.30:
        status = "LOW_CONFIDENCE_R2"

    return float(beta), float(r_squared), n, status


def fetch_betas(dry_run: bool = True, compute_all: bool = False):
    with open(CONFIG_PATH) as f:
        data = json.load(f)

    results = []  # (local_ticker, real_ticker, beta, r_sq, n_obs, status)
    updated = 0

    for local_ticker, entry in data.items():
        if local_ticker.startswith("_"):
            continue
        if not isinstance(entry, dict):
            continue
        if not compute_all and entry.get("beta") is not None:
            continue

        real_ticker = entry.get("real_ticker", local_ticker)
        print(f"  Fetching {local_ticker} ({real_ticker})...", flush=True)

        beta, r_sq, n_obs, status = compute_beta_regression(real_ticker)
        results.append((local_ticker, real_ticker, beta, r_sq, n_obs, status))

        if beta is not None and status == "OK":
            updated += 1
            if not dry_run:
                entry["beta"] = round(beta, 3)
                entry["r_squared"] = round(r_sq, 2)
                entry["source"] = "yfinance_regression_3y_weekly"
                entry["date_added"] = date.today().isoformat()
                entry["n_observations"] = n_obs

        time.sleep(2)

    # Print summary table
    print(f"\n{'Local Ticker':<16} {'Real Ticker':<12} {'Beta':<10} {'R²':<8} {'N_obs':<8} {'Status'}")
    print("-" * 72)
    for local, real, beta, r_sq, n_obs, status in results:
        beta_str = f"{beta:.3f}" if beta is not None else "NONE"
        r_sq_str = f"{r_sq:.2f}" if r_sq is not None else "NONE"
        n_str = str(n_obs) if n_obs is not None else "NONE"
        print(f"{local:<16} {real:<12} {beta_str:<10} {r_sq_str:<8} {n_str:<8} {status}")

    # Low-confidence report
    low_conf = [(l, r, b, rr) for l, r, b, rr, _, s in results if s == "LOW_CONFIDENCE_R2"]
    suspicious_list = [(l, r, b, rr) for l, r, b, rr, _, s in results if s.startswith("SUSPICIOUS")]
    if low_conf or suspicious_list:
        report_path = Path("/tmp/low_confidence_betas.txt")
        with open(report_path, "w") as f:
            f.write("Tickers requiring manual beta lookup (R² < 0.30 or suspicious)\n")
            f.write(f"Generated: {date.today().isoformat()}\n\n")
            f.write(f"{'Ticker':<16} {'Real':<12} {'Beta':<10} {'R²':<8} Morningstar URL\n")
            f.write("-" * 90 + "\n")
            for local, real, beta, r_sq in low_conf + suspicious_list:
                url = f"https://www.morningstar.com/search?query={real}"
                beta_str = f"{beta:.3f}" if beta is not None else "NONE"
                r_sq_str = f"{r_sq:.2f}" if r_sq is not None else "NONE"
                f.write(f"{local:<16} {real:<12} {beta_str:<10} {r_sq_str:<8} {url}\n")
        print(f"\nLow-confidence report written to {report_path}")

    print(f"\n--- Summary ---")
    ok = sum(1 for *_, s in results if s == "OK")
    low_conf_n = sum(1 for *_, s in results if s == "LOW_CONFIDENCE_R2")
    suspicious = sum(1 for *_, s in results if s.startswith("SUSPICIOUS"))
    insufficient = sum(1 for *_, s in results if s == "INSUFFICIENT_DATA")
    errors = sum(1 for *_, s in results if s.startswith("ERROR"))
    print(f"Total:           {len(results)}")
    print(f"OK (will write): {ok}")
    print(f"LOW_CONFIDENCE:  {low_conf_n}")
    print(f"SUSPICIOUS:      {suspicious}")
    print(f"INSUFFICIENT:    {insufficient}")
    print(f"ERROR:           {errors}")

    if dry_run:
        print(f"\n[DRY RUN] No changes written. Would update {updated} entries.")
    else:
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print(f"\nWrote {updated} beta values to {CONFIG_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch betas from Yahoo Finance via OLS regression")
    ap.add_argument("--dry-run", action="store_true", help="Print results without modifying JSON")
    ap.add_argument("--compute-all", action="store_true", help="Recompute all entries, even those with existing beta")
    args = ap.parse_args()
    fetch_betas(dry_run=args.dry_run, compute_all=args.compute_all)
