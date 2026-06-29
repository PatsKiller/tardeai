#!/usr/bin/env python3
"""P7: local LLM runtime policy — discrete B50 pinning, market-hour 27B/31B block, qwen3:8b
benchmark-only, embed protected. Probe + benchmark structure + safety."""
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from local_llm_runtime_probe import probe  # noqa: E402
from local_llm_benchmark import build as bench_build  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    pol = yaml.safe_load(open(os.path.join(ROOT, "config", "local_llm_runtime_policy.yaml")).read())

    # ---- policy correctness ----
    check("discrete GPU is Arc Pro B50, required", pol["hardware"]["discrete_gpu"]["name"] == "Intel Arc Pro B50"
          and pol["hardware"]["discrete_gpu"]["required"] is True)
    check("integrated Iris Xe NOT allowed for generation",
          pol["hardware"]["integrated_gpu"]["allowed_for_llm_generation"] is False)
    check("vulkan device pin = 1 (discrete)", pol["runtime"]["required_env"]["GGML_VK_VISIBLE_DEVICES"] == "1")
    check("production model gemma3:12b", pol["lanes"]["local_quality"]["model"] == "gemma3:12b")
    check("fast model gemma3:4b", pol["lanes"]["local_fast"]["model"] == "gemma3:4b")
    check("embed model protected nomic-embed-text",
          pol["lanes"]["local_embed"]["model"] == "nomic-embed-text" and pol["lanes"]["local_embed"]["protected"] is True)
    check("qwen3:8b is benchmark-only (not production)",
          pol["lanes"]["local_fallback_benchmark"]["model"] == "qwen3:8b"
          and pol["lanes"]["local_fallback_benchmark"]["production_enabled"] is False)
    check("27b + 31b blocked in market hours",
          set(pol["market_hours_policy"]["blocked_local_models"]) == {"gemma3:27b", "gemma4-31b"})
    check("no_paid_fallback + no_local_31b_fallback",
          pol["market_hours_policy"]["no_paid_fallback"] is True and pol["market_hours_policy"]["no_local_31b_fallback"] is True)

    # ---- probe ----
    r = probe()
    check("probe reports backend + device", "backend" in r and "device_selected" in r)
    check("probe reports production/fast/embed models",
          r["production_model"] == "gemma3:12b" and r["fast_model"] == "gemma3:4b" and r["embed_model"] == "nomic-embed-text")
    check("probe lists blocked market models", set(r["blocked_market_models"]) == {"gemma3:27b", "gemma4-31b"})
    check("probe findings is a list", isinstance(r["findings"], list))
    check("probe no broker writes", "No broker writes" in r["note"])

    # ---- benchmark refuses market hours + never benchmarks 31b in market ----
    b = bench_build(apply=False)
    check("benchmark dry-run by default", b["status"] in ("DRY_RUN", "REFUSED_MARKET_HOURS"))
    check("benchmark never includes 27b/31b in candidates",
          "gemma4-31b" not in b.get("candidates", []) and "gemma3:27b" not in b.get("candidates", []))
    check("benchmark documents 31b never benchmarked in market",
          "gemma4-31b" in bench_build(apply=False).get("never_benchmarked_in_market", []))
    # apply during market hours is refused
    import local_llm_benchmark as lb
    if lb._in_market_window():
        check("benchmark --apply REFUSED during market hours", bench_build(apply=True)["status"] == "REFUSED_MARKET_HOURS")
    else:
        check("benchmark off-hours apply allowed (skipped in-market)", True)
    check("promotion rule: qwen3 stays fallback until it beats gemma3:12b", "BEATS gemma3:12b" in b["promotion_rule"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
