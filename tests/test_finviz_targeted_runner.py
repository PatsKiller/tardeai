#!/usr/bin/env python3
"""P2: the targeted Finviz runner resolves ONLY the requested registry screeners, dedupes across them,
tags every row with full source lineage, and never invokes the broad all-screeners runner."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import run_finviz_targeted_screeners as tr  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # resolve by screener_id AND preset_id
    r = tr.resolve(["momentum_scalp_primary_gappers", "s144880160", "does_not_exist"])
    check("resolves by screener_id + preset_id, drops unknown", len(r) == 2)
    check("resolved are the two scalp screens",
          {p["screener_id"] for p in r} == {"momentum_scalp_primary_gappers", "momentum_scalp_low_price_active_gappers"})

    # dry-run run() — resolves, no broad runner
    out = tr.run(["momentum_scalp_primary_gappers", "momentum_scalp_low_price_active_gappers"], dry_run=True)
    check("dry-run resolves both screens", out["resolved_screeners"] ==
          ["momentum_scalp_primary_gappers", "momentum_scalp_low_price_active_gappers"])
    check("never uses the broad runner", out["uses_broad_runner"] is False)
    check("note: discovery only, no broker writes", "discovery only" in out["note"].lower() and "no broker writes" in out["note"].lower())

    # tagging + dedupe (simulate fetched tickers via monkeypatching the fetch)
    import finviz_screener_runner as fr
    orig = getattr(fr, "_fetch_screener_tickers", None)
    fr._fetch_screener_tickers = lambda url, cookie: ["AAA", "BBB", "aaa"]  # dup across case
    fr._get_finviz_cookie = lambda: "x"
    try:
        out2 = tr.run(["momentum_scalp_primary_gappers", "momentum_scalp_low_price_active_gappers"], dry_run=False)
    finally:
        if orig:
            fr._fetch_screener_tickers = orig
    check("dedupes across screens (AAA,BBB once each)", out2["unique_symbols"] == 2)
    row = out2["rows_sample"][0]
    for tag in ("screener_id", "preset_id", "source_screen_name", "source_url_hash",
                "source_seen_at", "discovery_trace_id", "strategy_family", "time_sensitivity"):
        check(f"row tagged with {tag}", tag in row and row[tag] is not None)
    check("strategy_family is momentum_scalp", row["strategy_family"] == "momentum_scalp")
    check("discovery_trace_id has fvtgt prefix", row["discovery_trace_id"].startswith("fvtgt-"))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
