#!/usr/bin/env python3
"""local_llm_benchmark.py — measure local models (gemma3:4b / gemma3:12b / qwen3:8b) so promotion
decisions are evidence-based, not assumed. Benchmarks ONLY outside the 06:00-12:00 ET market window by
default (so it never adds GPU load while the scalp lane + dashboard need it). gemma4-31b/27b are never
benchmarked during market hours. Default DRY-RUN. Read-only / advisory. No broker writes.

    python3 scripts/local_llm_benchmark.py --json                 # dry-run plan
    python3 scripts/local_llm_benchmark.py --apply --json         # run (off-hours only)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config" / "local_llm_runtime_policy.yaml"
PROMPT = "In one sentence, summarize why a low-float high-RVOL gapper is a momentum-scalp candidate."


def _in_market_window() -> bool:
    try:
        from zoneinfo import ZoneInfo
        et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        et = datetime.now()
    return et.weekday() < 5 and "06:00" <= et.strftime("%H:%M") < "12:00"


def _bench_one(model: str, timeout: int = 60) -> dict:
    import requests
    t0 = time.monotonic()
    try:
        r = requests.post("http://localhost:11434/api/generate",
                          json={"model": model, "prompt": PROMPT, "stream": False}, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        total = time.monotonic() - t0
        out_tokens = j.get("eval_count") or 0
        return {"model": model, "ok": True, "total_latency_ms": round(total * 1000),
                "ttft_ms": round((j.get("prompt_eval_duration", 0) or 0) / 1e6),
                "tokens_per_sec": round(out_tokens / total, 1) if total > 0 else None,
                "out_tokens": out_tokens}
    except Exception as e:
        return {"model": model, "ok": False, "error": str(e).splitlines()[0][:80]}


def build(apply: bool = False) -> dict:
    pol = yaml.safe_load(POLICY.read_text())
    market = _in_market_window()
    candidates = ["gemma3:4b", "gemma3:12b", "qwen3:8b"]    # never 27b/31b here
    results = []
    ran = False
    if apply and market:
        return {"ok": True, "status": "REFUSED_MARKET_HOURS", "market_window": True,
                "note": "Benchmarks refused during 06:00-12:00 ET (would steal GPU from the scalp lane / "
                        "dashboard). Re-run off-hours. No broker writes."}
    if apply and not market:
        ran = True
        for m in candidates:
            results.append(_bench_one(m))
    return {
        "ok": True, "status": "RAN" if ran else "DRY_RUN", "market_window": market,
        "candidates": candidates, "results": results,
        "promotion_rule": "qwen3:8b stays benchmark/fallback-only until it BEATS gemma3:12b locally "
                          "without dashboard or embed regressions; gemma3:12b is the production ceiling. "
                          "SYCL/oneAPI is not promoted over Vulkan without measured wins.",
        "never_benchmarked_in_market": ["gemma3:27b", "gemma4-31b"],
        "note": "Off-hours only; dry-run default. Read-only / advisory. No broker writes.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually benchmark (off-hours only)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = build(apply=args.apply)
    print(json.dumps(r, indent=2, default=str) if args.json else
          f"benchmark: {r['status']} market={r['market_window']} results={len(r.get('results', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
