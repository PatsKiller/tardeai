#!/usr/bin/env python3
"""validate_missed_opportunities_dedup.py — verify /api/v2/backtesting/missed-opportunities dedup+verdict.
Read-only (HTTP GET). No trading/proposal/strategy mutation.
  python3 scripts/validate_missed_opportunities_dedup.py
"""
import sys, json, urllib.request

URL = "http://127.0.0.1:7777/api/v2/backtesting/missed-opportunities"


def main():
    raw = urllib.request.urlopen(URL, timeout=40).read().decode()
    doc = json.loads(raw)  # strict JSON (raises on NaN/invalid)
    d = doc["data"]; s = d["summary"]; rows = d["rows"]
    checks = []
    def chk(n, ok, detail=""):
        checks.append((n, bool(ok), str(detail)))

    chk("strict valid JSON", True)
    chk("summary present", isinstance(s, dict) and "deduped_rows" in s)
    chk("missed_opportunity_key on every row", all(r.get("missed_opportunity_key") for r in rows))
    keys = [r["missed_opportunity_key"] for r in rows]
    chk("no duplicate missed_opportunity_key", len(keys) == len(set(keys)), f"{len(keys)} rows / {len(set(keys))} unique")
    chk("raw_rows >= deduped_rows", s["raw_rows"] >= s["deduped_rows"], f"{s['raw_rows']} >= {s['deduped_rows']}")
    chk("duplicates_removed > 0", s["duplicates_removed"] > 0, s["duplicates_removed"])
    tot = s["would_win"] + s["would_lose"] + s["breakeven"] + s["mixed"] + s["no_data"]
    chk("verdict counts sum to deduped_rows", tot == s["deduped_rows"], f"{tot} == {s['deduped_rows']}")
    chk("verdict on every row", all(r.get("sim_outcome_verdict") in ("WIN", "LOSS", "BREAKEVEN", "MIXED", "NO_DATA") for r in rows))
    chk("verdict_source on every row", all(r.get("sim_verdict_source") for r in rows))
    chk("duplicate_count present", all("duplicate_count" in r for r in rows))
    chk("dedupe_confidence present", all(r.get("dedupe_confidence") for r in rows))
    # symbols that previously duplicated must collapse (each proposal_id appears once)
    for sym in ("ARM", "SNOW", "MRVL", "BLBD"):
        srows = [r for r in rows if r["symbol"] == sym]
        pids = [r["proposal_id"] for r in srows]
        chk(f"{sym}: one row per proposal_id (no fan-out dup)", len(pids) == len(set(pids)), f"{len(pids)} rows, {len(set(pids))} distinct proposals")
    # mixed visibility
    mixed = [r for r in rows if r["sim_outcome_verdict"] == "MIXED"]
    chk("MIXED rows expose win/loss counts", all("win_count" in r and "loss_count" in r for r in mixed), f"{len(mixed)} mixed")

    ok = all(c[1] for c in checks)
    print(json.dumps({"summary": s, "rows": len(rows)}, indent=2))
    for n, p, dt in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {n}" + (f" — {dt}" if dt else ""))
    print(f"\n{sum(1 for c in checks if c[1])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
