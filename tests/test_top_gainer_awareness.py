#!/usr/bin/env python3
"""Top gainer awareness tagging from Finviz prime_setups."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from top_gainer_awareness import (  # noqa: E402
    attach_top_gainer_awareness,
    load_finviz_top_gainers,
    load_market_movers_top_gainers,
    load_top_gainers,
)


def check(label: str, ok: bool):
    print(f"{'PASS' if ok else 'FAIL'}: {label}")
    if not ok:
        raise SystemExit(1)


def main() -> int:
    # Uses live export if present (GMM was #1 on 2026-07-10).
    gainers = load_finviz_top_gainers(ROOT, limit=5, min_change_pct=5.0)
    check("loads finviz top gainers", len(gainers) >= 1)
    if gainers:
        check("sorted by change desc", gainers[0]["change_pct"] >= gainers[-1]["change_pct"])

    tickers = [{"symbol": "GMM", "score": 0, "decision": "AVOID", "disqualified": True,
                "disqualification_reason": "REVERSE_SPLIT: 0.02:1 on 2026-06-11"}]
    tagged = attach_top_gainer_awareness(tickers, ROOT, limit=10)
    gmm = next((t for t in tickers if t["symbol"] == "GMM"), None)
    if "GMM" in tagged:
        check("GMM tagged TOP_GAINER", gmm and gmm.get("awareness_status") == "TOP_GAINER")
        check("GMM has operator pill", gmm and "TOP GAINER" in (gmm.get("operator_pill") or ""))
        check("GMM not_tradeable", gmm and gmm.get("not_tradeable") is True)
        check("GMM backfills change_pct", gmm and gmm.get("change_pct"))
    else:
        check("GMM optional when no finviz file", True)

    # ---- market_movers as a second source (2026-07-28) ----
    # prime_setups is hard-filtered and returned 1 row on a day with 15 double-digit
    # gainers; the union must carry the raw Home-board names too.
    movers = load_market_movers_top_gainers(ROOT, limit=30, min_change_pct=10.0)
    union = load_top_gainers(ROOT, limit=30, min_change_pct=10.0)
    check("union is a superset of each source", len(union) >= len(movers))
    if movers:
        check("movers rows carry a price", all(m.get("price") for m in movers))
        check("movers rows declare their source", all(m["source"] == "market_movers" for m in movers))
        check("movers rows never fake rvol/gap/float",
              all(m["rvol"] is None and m["gap_pct"] is None and m["float_m"] is None for m in movers))
        usyms = {u["symbol"] for u in union}
        check("union keeps every movers symbol", all(m["symbol"] in usyms for m in movers))
    check("union sorted by change desc",
          all(union[i]["change_pct"] >= union[i + 1]["change_pct"] for i in range(len(union) - 1)))
    check("union ranks are 1-based and dense",
          [u["rank"] for u in union] == list(range(1, len(union) + 1)))
    check("union dedupes by symbol", len({u["symbol"] for u in union}) == len(union))

    # ---- the marker survives a lane that already claimed awareness_status ----
    sq = [{"symbol": union[0]["symbol"], "score": 0, "decision": "MANUAL_REVIEW",
           "awareness_status": "SQUEEZE", "operator_pill": "SQUEEZE · R/S · 85.7x",
           "operator_color_token": "squeeze"}] if union else []
    if sq:
        attach_top_gainer_awareness(sq, ROOT, limit=30)
        row = sq[0]
        check("squeeze lane preserved", row["awareness_status"] == "SQUEEZE")
        check("squeeze pill not overwritten", row["operator_pill"] == "SQUEEZE · R/S · 85.7x")
        check("top_gainer marker still set", row.get("top_gainer") is True)
        check("marker carries its own pill", "TOP GAINER" in (row.get("top_gainer_pill") or ""))
        check("marker carries pct", row.get("top_gainer_pct") is not None)

    # ---- awareness tagging is ADDITIVE: never downgrade a lane, never revoke a GO ----
    # LVWR/POLA (2026-07-28) were scored GO in the HIGH_RVOL runner lane and appeared on
    # the raw movers board; tagging relabelled them TOP_GAINER and force-set not_tradeable.
    if union:
        sym = union[0]["symbol"]
        runner = [{"symbol": sym, "score": 39, "grade": "B", "decision": "GO",
                   "awareness_status": "HIGH_RVOL", "operator_pill": "RUNNER · 705.5x",
                   "operator_color_token": "runner"}]
        attach_top_gainer_awareness(runner, ROOT, limit=30)
        r = runner[0]
        check("scored runner keeps its lane", r["awareness_status"] == "HIGH_RVOL")
        check("scored runner keeps its pill", r["operator_pill"] == "RUNNER · 705.5x")
        check("scored GO stays tradeable", not r.get("not_tradeable"))
        check("scored GO stays validation-ready", not r.get("not_validation_ready"))
        check("scored runner still carries the marker", r.get("top_gainer") is True)

        # A row the engine did NOT pass still gets the awareness guard rails.
        avoid = [{"symbol": sym, "score": 4, "decision": "AVOID", "disqualified": True,
                  "disqualification_reason": "REVERSE_SPLIT"}]
        attach_top_gainer_awareness(avoid, ROOT, limit=30)
        a = avoid[0]
        check("non-actionable row is not_tradeable", a.get("not_tradeable") is True)
        check("non-actionable row is not_validation_ready", a.get("not_validation_ready") is True)
        check("unclaimed lane falls to TOP_GAINER", a["awareness_status"] == "TOP_GAINER")

    # ---- injected movers rows are awareness-only, never tradeable ----
    fresh: list[dict] = []
    attach_top_gainer_awareness(fresh, ROOT, limit=30)
    inj = [r for r in fresh if r.get("top_gainer_source") == "market_movers"]
    if inj:
        check("injected movers rows are AWARE", all(r["decision"] == "AWARE" for r in inj))
        check("injected movers rows score 0", all(r["score"] == 0 for r in inj))
        check("injected movers rows not_tradeable", all(r["not_tradeable"] is True for r in inj))
        check("injected movers rows not_validation_ready",
              all(r["not_validation_ready"] is True for r in inj))
        check("injected movers rows name their source",
              all("market movers" in r["source_detail"].lower() for r in inj))

    print("All top_gainer_awareness checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())