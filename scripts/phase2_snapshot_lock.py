#!/usr/bin/env python3
# phase2_snapshot_lock.py
# Recalculates portfolio_totals from account_summaries on every read.
# This prevents stale or drifted totals from being served to the dashboard
# or Steph. Called from read_holdings() in portfolio_server.py.

from __future__ import annotations
from pathlib import Path


def lock_portfolio_totals(data: dict, project_root: Path = None) -> dict:
    """
    Recalculates portfolio_totals.total_value and day_change
    from the sum of account_summaries. Safe — only updates if
    account_summaries exist and are non-zero.

    Args:
        data: loaded holdings.json dict
        project_root: unused, kept for future extension

    Returns:
        data with portfolio_totals recalculated in-place
    """
    acct = data.get("account_summaries", {}) or {}
    pt   = data.get("portfolio_totals", {}) or {}

    if not acct:
        return data  # nothing to recalculate

    total = round(
        sum(float((v or {}).get("total_value") or 0) for v in acct.values()), 2)
    day   = round(
        sum(float((v or {}).get("day_change") or 0) for v in acct.values()), 2)

    # Only overwrite if the recalculated total is non-zero
    # (protects against edge case where account_summaries are empty dicts)
    if total > 0:
        prev = total - day
        pt["total_value"]    = total
        pt["day_change"]     = day
        pt["day_change_pct"] = round((day / prev * 100) if prev else 0, 4)
        data["portfolio_totals"] = pt

    return data


if __name__ == "__main__":
    print("phase2_snapshot_lock: import-only module")
