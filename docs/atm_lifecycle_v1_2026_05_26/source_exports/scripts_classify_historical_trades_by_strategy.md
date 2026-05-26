# Source Export: scripts/classify_historical_trades_by_strategy.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/classify_historical_trades_by_strategy.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `b47d16b5727f326ffc100167789fa7f0d64a40bcb637bcf63579d2bb53afcdaf` |
| **File Size** | 7399 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""SCHWAB-BT-2 — Classify historical closed trades by strategy.

Uses hold duration, price/volume characteristics, account type, and
symbol properties to assign strategy_id. All classifications are
human_review_only=true. Does not change strategy activation.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def classify_trade(trade: dict) -> dict:
    """Classify a single historical trade by strategy. Pure function."""
    sym = trade.get("symbol", "")
    acct = (trade.get("account_label") or "").lower()
    hold = trade.get("hold_days") or 0
    entry = float(trade.get("entry_price") or 0)
    exit_p = float(trade.get("exit_price") or 0)
    qty = float(trade.get("quantity") or 0)
    pnl = float(trade.get("realized_pnl") or 0)

    # Skip zero-cost/transfer rows
    if entry == 0 or qty == 0:
        return {
            "strategy_id": None, "strategy_family": "unclassifiable",
            "confidence_score": 0, "classification_reason": "zero entry price or quantity — likely transfer/corporate action",
            "human_review_only": True, "review_required_reason": "non-trade event",
        }

    reasons = []
    confidence = 50  # base

    # Account-type hints (not hardcoded strategy, just context)
    is_ira = "ira" in acct or "roth" in acct or "401k" in acct
    is_taxable = "taxable" in acct

    # Hold duration classification
    if hold == 0:
        # Same-day
        if qty >= 500 and entry < 10:
            strategy = "momentum_scalp"
            family = "momentum"
            reasons.append(f"same-day, high qty ({qty}), low price (${entry:.2f})")
            confidence = 70
        elif qty >= 100:
            strategy = "gap_and_go"
            family = "momentum"
            reasons.append(f"same-day, qty={qty}")
            confidence = 60
        else:
            strategy = "momentum_scalp"
            family = "momentum"
            reasons.append(f"same-day trade")
            confidence = 55
    elif hold <= 5:
        strategy = "swing_trade"
        family = "swing"
        reasons.append(f"short hold ({hold}d)")
        confidence = 65
    elif hold <= 21:
        strategy = "swing_breakout"
        family = "swing"
        reasons.append(f"swing hold ({hold}d)")
        confidence = 60
    elif hold <= 90:
        if is_ira:
            strategy = "dividend_growth_compounder"
            family = "income"
            reasons.append(f"medium hold ({hold}d) in IRA")
            confidence = 55
        else:
            strategy = "recovery_watch"
            family = "income"
            reasons.append(f"medium hold ({hold}d)")
            confidence = 50
    else:
        # Long hold (>90 days)
        if is_ira:
            strategy = "core_growth_compounder"
            family = "position"
            reasons.append(f"long hold ({hold}d) in IRA")
            confidence = 60
        else:
            strategy = "dividend_growth_compounder"
            family = "income"
            reasons.append(f"long hold ({hold}d)")
            confidence = 55

    # Well-known symbol overrides
    KNOWN_INCOME = {"PFE", "VZ", "T", "KO", "PG", "JNJ", "ABBV", "MO", "XOM", "CVX"}
    KNOWN_GROWTH = {"TSLA", "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "V", "MA"}
    KNOWN_DEFENSE = {"LMT", "RTX", "NOC", "GD", "BA", "HII", "LHX", "LDOS"}

    if sym in KNOWN_INCOME and hold > 30:
        strategy = "dividend_growth_compounder"
        family = "income"
        reasons.append(f"known income stock {sym}")
        confidence = min(confidence + 15, 85)
    elif sym in KNOWN_GROWTH and hold > 60:
        strategy = "core_growth_compounder"
        family = "position"
        reasons.append(f"known growth stock {sym}")
        confidence = min(confidence + 10, 80)
    elif sym in KNOWN_DEFENSE:
        strategy = "defense_thesis"
        family = "position"
        reasons.append(f"defense/aerospace stock {sym}")
        confidence = min(confidence + 15, 85)

    return {
        "strategy_id": strategy,
        "strategy_family": family,
        "confidence_score": confidence,
        "classification_reason": "; ".join(reasons),
        "human_review_only": True,
        "review_required_reason": "historical trade — needs manual verification" if confidence < 70 else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", type=str)
    ap.add_argument("--account-label", type=str)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--output-json", type=str)
    ap.add_argument("--output-md", type=str)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    from canonical_closed_trade_adapter import extract_canonical
    trades = extract_canonical(args.account_label, args.broker, verbose=False)

    results = []
    by_strategy = {}
    high = medium = low = unclass = 0

    for t in trades:
        c = classify_trade(t)
        c["symbol"] = t.get("symbol")
        c["account_label"] = t.get("account_label")
        c["broker"] = t.get("broker")
        c["source_trade_id"] = t.get("source_trade_id")
        c["hold_days"] = t.get("hold_days")
        c["realized_pnl"] = t.get("realized_pnl")

        sid = c.get("strategy_id") or "unclassified"
        by_strategy.setdefault(sid, []).append(c)

        conf = c.get("confidence_score", 0)
        if conf >= 70: high += 1
        elif conf >= 50: medium += 1
        elif conf > 0: low += 1
        else: unclass += 1

        results.append(c)
        if args.verbose and c.get("strategy_id"):
            print(f"  {c['symbol']:6s} {c['account_label']:22s} → {sid:30s} conf={conf} ({c['classification_reason'][:50]})")

    summary = {
        "total": len(results),
        "high_confidence": high,
        "medium_confidence": medium,
        "low_confidence": low,
        "unclassified": unclass,
        "by_strategy": {k: len(v) for k, v in sorted(by_strategy.items(), key=lambda x: -len(x[1]))},
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump({"summary": summary, "classifications": results}, f, indent=2, default=str)

    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_md, "w") as f:
            f.write(f"# Historical Trade Strategy Classification\n\n")
            f.write(f"Total: {len(results)} | High: {high} | Medium: {medium} | Low: {low} | Unclass: {unclass}\n\n")
            f.write(f"## By Strategy\n\n| Strategy | Count | Avg Confidence |\n|---|---|---|\n")
            for sid, trades in sorted(by_strategy.items(), key=lambda x: -len(x[1])):
                avg_c = sum(t.get("confidence_score", 0) for t in trades) / len(trades)
                f.write(f"| {sid} | {len(trades)} | {avg_c:.0f} |\n")
            f.write(f"\n*All classifications are human_review_only=true*\n")

    print(f"\nClassified: {len(results)} | High: {high} | Medium: {medium} | Low: {low} | Unclass: {unclass}")
    print(f"Strategies: {json.dumps(summary['by_strategy'])}")


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
```
