#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
CONFIG = ROOT / "config/asset_classification_rules.json"

INPUT_FILES = [
    "ai_watchlist.json",
    "discovery_candidates.json",
    "asset_intelligence.json",
    "etf_intelligence.json",
    "mutual_fund_intelligence.json",
    "stock_intelligence.json"
]


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def normalize_symbol(raw, rules):
    if not raw:
        return ""
    s = str(raw).strip().upper().replace("$", "")
    s = rules.get("aliases", {}).get(s, s)
    if s in set(rules.get("exclude_symbols", [])):
        return ""
    if not re.match(r"^[A-Z0-9.\-]{1,12}$", s):
        return ""
    return s


def extract_candidates(obj, rules):
    out = {}

    def add(sym, source, context):
        s = normalize_symbol(sym, rules)
        if not s:
            return
        rec = out.setdefault(s, {
            "symbol": s,
            "sources": [],
            "contexts": []
        })
        if source not in rec["sources"]:
            rec["sources"].append(source)
        if context:
            rec["contexts"].append(str(context)[:500])

    def walk(x, source):
        if isinstance(x, dict):
            sym = x.get("symbol") or x.get("ticker")
            if sym:
                add(sym, source, x)
            for k, v in x.items():
                # Treat dict keys as symbols only when they look like real ticker keys.
                # Avoid generic JSON keys such as analyst, candidates, profile, reasons, sources, watchlist.
                bad_keys = {
                    "analyst", "candidates", "items", "profile", "reasons",
                    "sources", "watchlist", "metadata", "generated_at",
                    "summary", "notes", "context", "bucket_counts"
                }
                kk = str(k).strip().lower()
                if kk not in bad_keys and isinstance(v, dict):
                    candidate_key = normalize_symbol(k, rules)
                    if candidate_key and (
                        candidate_key in rules.get("asset_type_overrides", {})
                        or candidate_key in rules.get("bucket_overrides", {})
                        or candidate_key.endswith("X")
                        or len(candidate_key) <= 5
                    ):
                        add(candidate_key, source, v)
                walk(v, source)
        elif isinstance(x, list):
            for item in x:
                walk(item, source)

    for fname in INPUT_FILES:
        data = load_json(STATE / fname, {})
        walk(data, fname)

    return list(out.values())


def classify(rec, rules):
    symbol = rec["symbol"]
    text = " ".join(rec.get("contexts", [])).lower()

    asset_type = rules.get("asset_type_overrides", {}).get(symbol)
    buckets = list(rules.get("bucket_overrides", {}).get(symbol, []))

    if not asset_type:
        if symbol.endswith("X"):
            asset_type = "mutual_fund"
        elif symbol in buckets:
            asset_type = buckets[0]
        else:
            asset_type = "unknown"

    for bucket, keywords in rules.get("keyword_rules", {}).items():
        if any(k.lower() in text for k in keywords):
            if bucket not in buckets:
                buckets.append(bucket)

    if asset_type == "etf" and "etf" not in buckets:
        buckets.insert(0, "etf")
    if asset_type == "mutual_fund" and "mutual_fund" not in buckets:
        buckets.insert(0, "mutual_fund")
    if asset_type == "stock" and "stock" not in buckets:
        buckets.insert(0, "stock")

    needs_review = False
    reasons = []

    if asset_type == "unknown":
        needs_review = True
        reasons.append("unknown_asset_type")

    if not buckets:
        needs_review = True
        reasons.append("no_strategy_bucket")

    # Stock tickers ending in X can be legitimate equities or preferred/foreign variants.
    # Do not auto-review if explicit override says stock.

    if asset_type in {"etf", "mutual_fund"} and not symbol.endswith("X") and asset_type == "mutual_fund":
        needs_review = True
        reasons.append("mutual_fund_symbol_does_not_end_x")

    rec.update({
        "asset_type": asset_type,
        "buckets": buckets,
        "needs_review": needs_review,
        "review_reasons": reasons
    })
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rules = load_json(CONFIG, {})
    candidates = extract_candidates({}, rules)
    classified = [classify(c, rules) for c in candidates]

    classified.sort(key=lambda x: (x["needs_review"], x["asset_type"], x["symbol"]))

    review = [c for c in classified if c["needs_review"]]
    clean = [c for c in classified if not c["needs_review"]]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(classified),
        "clean": len(clean),
        "needs_review": len(review),
        "classified_candidates": classified
    }

    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "classified_candidates.json").write_text(json.dumps(out, indent=2))
    (STATE / "classification_review_queue.json").write_text(json.dumps({
        "generated_at": out["generated_at"],
        "needs_review": review
    }, indent=2))

    if args.json:
        print(json.dumps({
            "ok": True,
            "total": len(classified),
            "clean": len(clean),
            "needs_review": len(review),
            "files": [
                str(STATE / "classified_candidates.json"),
                str(STATE / "classification_review_queue.json")
            ]
        }, indent=2))
    else:
        print(f"classified={len(classified)} clean={len(clean)} needs_review={len(review)}")


if __name__ == "__main__":
    main()
