#!/usr/bin/env python3
"""Q1 — measure whether today's DeepSeek rows are research or filler.

READ_ONLY_ADVISORY. No LLM calls. No thesis writes.
Sample 40 nonempty deepseek rows (20 T1, 10 T0-HOLD, 10 reentry) from CURRENT_DATE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.thesis_substantiveness import score_text  # noqa: E402

TICKER_STRIP = re.compile(r"\b[A-Z]{1,5}\b")


def _db():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from db_adapter import _get_conn
    return _get_conn()


def _sample_key(sym: str) -> str:
    return hashlib.sha256(f"q1-2026-08-22|{sym}".encode()).hexdigest()


def _shingles(text: str, n: int = 5) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


def _score_row(sym: str, rec: str, ctx: str) -> dict:
    return score_text(sym, rec or "", ctx or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/cio/research_quality_sample_2026-08-22.json"))
    args = ap.parse_args()

    import os, sys
    sys.path.insert(0, str(ROOT / "scripts"))
    os.chdir(str(ROOT))
    CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
    from research_scheduler import load_universe, load_reentry_ready_near_symbols

    uni = load_universe(root=CURRENT)
    reentry = set(load_reentry_ready_near_symbols(root=CURRENT) or [])
    by_tier = {}
    for s, v in uni.items():
        by_tier.setdefault(v["tier"], set()).add(s)

    c = _db().cursor()
    c.execute(
        """SELECT upper(symbol), recommendation, coalesce(redacted_context::text,''), id
           FROM hermes_external_research
           WHERE lane='deepseek' AND created_at::date = CURRENT_DATE
             AND coalesce(recommendation,'')<>'' AND recommendation NOT LIKE '[%%'
           ORDER BY id"""
    )
    rows = {}
    for sym, rec, ctx, rid in c.fetchall():
        rows[sym] = {"recommendation": rec or "", "context": ctx or "", "id": rid}

    def pick(pool: list[str], n: int) -> list[str]:
        have = [s for s in pool if s in rows]
        have.sort(key=_sample_key)
        return have[:n]

    t0 = pick(sorted(by_tier.get("T0-HOLD") or []), 10)
    t1_pool = [s for s in sorted(by_tier.get("T1-WATCH") or []) if s not in reentry]
    t1 = pick(t1_pool, 20)
    re_s = pick(sorted(reentry), 10)
    sample = [("T0-HOLD", s) for s in t0] + [("T1-WATCH", s) for s in t1] + [("reentry", s) for s in re_s]

    scored = []
    for bucket, s in sample:
        r = rows[s]
        sc = _score_row(s, r["recommendation"], r["context"])
        sc["bucket"] = bucket
        sc["id"] = r["id"]
        scored.append(sc)

    sh = {s["symbol"]: _shingles(TICKER_STRIP.sub("TICKER", rows[s["symbol"]]["recommendation"])) for s in scored}
    dup_pairs = []
    for i, a in enumerate(scored):
        for b in scored[i + 1 :]:
            if a["symbol"] == b["symbol"]:
                continue
            j = _jaccard(sh[a["symbol"]], sh[b["symbol"]])
            if j >= 0.45:
                dup_pairs.append({"a": a["symbol"], "b": b["symbol"], "jaccard": round(j, 3)})
    dup_syms = set()
    for p in dup_pairs:
        dup_syms.add(p["a"])
        dup_syms.add(p["b"])

    n = len(scored) or 1
    lens = sorted(s["n_chars"] for s in scored)
    mid = lens[len(lens) // 2] if lens else 0
    pct = lambda k: round(100.0 * sum(1 for s in scored if s[k]) / n, 1)

    report = {
        "schema": "ResearchQualitySample@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "n": len(scored),
        "buckets": dict(Counter(s["bucket"] for s in scored)),
        "median_chars": mid,
        "pct_under_300": pct("under_300"),
        "pct_specific_fact": pct("specific_fact"),
        "pct_generic_prose": pct("generic_prose"),
        "pct_numeric_fidelity_fail": pct("numeric_fidelity_fail"),
        "pct_near_duplicate": round(100.0 * len(dup_syms) / n, 1),
        "near_duplicate_pairs": dup_pairs[:20],
        "pct_thesis_survivable": pct("thesis_survivable"),
        "generic_prose_threshold_40": pct("generic_prose") > 40,
        "verdict": (
            "LANE_RUNNING_NOT_RESEARCHING"
            if pct("generic_prose") > 40
            else "CONTENT_MEASURED"
        ),
        "rows": scored,
        "note": "Deterministic sample via sha256(q1-2026-08-22|SYM). Specific-fact is keyword heuristic, not a human grade.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
