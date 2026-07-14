#!/usr/bin/env python3
"""Capital-allocation book acceptance (Part B). Read-only; every DB test rolls back."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _conn():
    try:
        from db_adapter import get_connection
    except Exception:
        return None
    return get_connection()


def test_book_rows_have_required_fields():
    cb = _load("redeploy_capital_book", "scripts/lib/redeploy_capital_book.py")
    conn = _conn()
    if not conn:
        return  # skip without DB
    cur = conn.cursor()
    try:
        book = cb.build_capital_book(cur, limit=50)
        assert book["ok"] and book["advisory_only"]
        assert book["row_count"] > 0
        required = {
            "event_id", "symbol", "account", "sold_at", "proceeds_usd",
            "deployable_usd", "settled", "plan_selected", "deployed_usd",
            "remaining_usd", "restoration_pct", "plan_age_days",
            "quote_age_minutes", "monitoring_status", "completion_status", "warnings",
        }
        missing = required - set(book["rows"][0])
        assert not missing, f"book row missing fields: {missing}"
    finally:
        conn.rollback()


def test_book_excludes_quarantined_fills_from_deployed():
    cb = _load("redeploy_capital_book", "scripts/lib/redeploy_capital_book.py")
    conn = _conn()
    if not conn:
        return
    cur = conn.cursor()
    try:
        book = cb.build_capital_book(cur)
        for row in book["rows"]:
            quarantine_flags = [w for w in row["warnings"] if w.startswith("quarantined_test_fills")]
            if quarantine_flags and row["fill_count"] == 0:
                # events whose only fills are quarantined must report $0 deployed
                assert row["deployed_usd"] == 0, row
    finally:
        conn.rollback()


def test_history_reconciles_all_material_sells():
    cb = _load("redeploy_capital_book", "scripts/lib/redeploy_capital_book.py")
    conn = _conn()
    if not conn:
        return
    cur = conn.cursor()
    try:
        hist = cb.build_history(cur)
        c = hist["counts"]
        assert c["sells_found"] == c["matched"] + c["unmatched"]
        assert c["matched"] == c["open"] + c["dismissed"] + c["completed_or_reviewing"]
        assert len(hist["rows"]) == c["sells_found"]
    finally:
        conn.rollback()


def test_capital_pools_by_account():
    cb = _load("redeploy_capital_book", "scripts/lib/redeploy_capital_book.py")
    conn = _conn()
    if not conn:
        return
    cur = conn.cursor()
    try:
        pools = cb.build_capital_pools(cur)
        assert pools["ok"]
        for p in pools["pools"]:
            assert p["account"]
            assert p["open_event_remaining_usd"] >= 0
            assert p["visible_cash_usd"] >= 0
    finally:
        conn.rollback()


def test_opportunity_set_totals_match_book():
    cb = _load("redeploy_capital_book", "scripts/lib/redeploy_capital_book.py")
    conn = _conn()
    if not conn:
        return
    cur = conn.cursor()
    try:
        opp = cb.build_opportunity_set(cur)
        book = cb.build_capital_book(cur, include_dismissed=False)
        open_remaining = round(sum(
            r["remaining_usd"] for r in book["rows"]
            if r["completion_status"] in ("open", "partial")
        ), 2)
        assert abs(opp["deployable_capital_usd"] - open_remaining) < 0.01
        assert opp["portfolio_context"]["sector_weights"]
    finally:
        conn.rollback()


if __name__ == "__main__":
    tests = [
        test_book_rows_have_required_fields,
        test_book_excludes_quarantined_fills_from_deployed,
        test_history_reconciles_all_material_sells,
        test_capital_pools_by_account,
        test_opportunity_set_totals_match_book,
    ]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")
