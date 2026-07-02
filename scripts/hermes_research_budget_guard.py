#!/usr/bin/env python3
"""hermes_research_budget_guard.py — the chokepoint that decides whether a Hermes research request
runs, defers, downgrades to metadata, or is blocked. Same shape as scripts/llm_budget_guard.py.

Decision: ALLOW | DEFER | METADATA_ONLY | BLOCK.

Invariants (config/hermes_research_budget.yaml):
  * Fail closed: unknown trigger_source -> BLOCK.
  * Broad-universe tiers (T3/T4) NEVER call an LLM (LLM lane request -> METADATA_ONLY / BLOCK).
  * Free-OAuth only for cloud synthesis; a paid model is NEVER an allowed lane (no paid fallback).
  * Market-hours local-heavy models (gemma3:27b / gemma4-31b) are blocked — matches LOCAL_LLM_RUNTIME_POLICY.
  * Cloud lane requested but unavailable -> DEFER (never fall back to paid or local-heavy).
  * Duplicate research inside the freshness window -> DEFER.
  * Advisory only — this guard never places a trade, touches the broker, or bypasses a gate.

  from hermes_research_budget_guard import decide
  d = decide(symbol="AAPL", trigger_source="holdings", research_type="thesis",
             lane="cloud_grok", urgency="normal")
  # -> {"decision":"ALLOW","tier":"T0", ...}

CLI:
  python3 scripts/hermes_research_budget_guard.py --json            # policy + self-test summary
  python3 scripts/hermes_research_budget_guard.py --selftest        # exit non-zero on invariant break
"""
import argparse
import datetime as _dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_PATH = os.path.join(ROOT, "config", "hermes_research_budget.yaml")

ALLOW, DEFER, METADATA_ONLY, BLOCK = "ALLOW", "DEFER", "METADATA_ONLY", "BLOCK"

# Lane taxonomy. A "lane" is the requested execution path. model is optional refinement.
_LOCAL_FAST = {"local_fast", "gemma3:4b"}
_LOCAL_QUALITY = {"local_quality", "gemma3:12b"}
_LOCAL_HEAVY = {"local_heavy", "gemma3:27b", "gemma4-31b"}
_CLOUD_FREE = {"cloud", "cloud_grok", "cloud_chatgpt", "grok", "chatgpt"}
_CLOUD_PAID = {"cloud_paid", "claude", "claude-sonnet-4-6", "claude-opus-4-8", "gpt-4o"}
_METADATA = {"metadata", "none", "metadata_only"}


def _load_policy(path=None):
    import yaml
    with open(path or POLICY_PATH) as f:
        return yaml.safe_load(f)


def _is_market_hours(now, pol):
    mh = pol.get("market_hours", {})
    win = mh.get("window", "06:00-12:00")
    start, end = win.split("-")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(mh.get("timezone", "America/New_York"))
        now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    except Exception:
        pass
    hhmm = now.strftime("%H:%M")
    return start <= hhmm <= end


def _lane_kind(lane, model, pol):
    """Classify the requested lane into: metadata | local_fast | local_quality | local_heavy |
    cloud_free | cloud_paid | unknown."""
    key = (lane or "").strip().lower()
    m = (model or "").strip().lower()
    if key in _METADATA:
        return "metadata"
    if key in {x.lower() for x in _LOCAL_HEAVY} or m in {x.lower() for x in _LOCAL_HEAVY}:
        return "local_heavy"
    if key in {x.lower() for x in _LOCAL_QUALITY} or m == "gemma3:12b":
        return "local_quality"
    if key in {x.lower() for x in _LOCAL_FAST} or m == "gemma3:4b":
        return "local_fast"
    if key in {x.lower() for x in _CLOUD_PAID} or m in {x.lower() for x in _CLOUD_PAID}:
        return "cloud_paid"
    if key in {x.lower() for x in _CLOUD_FREE} or m in {x.lower() for x in pol["lanes"].get("free_oauth_models", [])}:
        return "cloud_free"
    return "unknown"


def decide(symbol, trigger_source, research_type="research", lane="metadata", urgency="normal",
           now=None, model=None, cloud_available=True, dedup_fresh=False,
           has_active_trigger=None, calls_today=None, symbols_this_run=None, policy=None):
    """Return a decision dict. Pure / DB-free — all runtime state is injected so it is testable.

    cloud_available: is a free-OAuth lane reachable right now?
    dedup_fresh:     was (symbol, research_type, lane) already researched inside the freshness window?
    has_active_trigger: for T2, is there an actual active directive/theme/wait trigger? (None=assume yes)
    calls_today / symbols_this_run: optional runtime counters to enforce caps.
    """
    pol = policy or _load_policy()
    now = now or _dt.datetime.now()
    res = {"symbol": symbol, "trigger_source": trigger_source, "research_type": research_type,
           "requested_lane": lane, "urgency": urgency, "decision": None, "tier": None,
           "lane_used": None, "reason": None, "expires_at": None,
           "advisory_only": True}

    # --- 1. Resolve tier (fail closed) ---
    tier_map = pol.get("trigger_source_tier", {})
    tier = tier_map.get((trigger_source or "").strip())
    if not tier or tier not in pol.get("tiers", {}):
        res.update(decision=BLOCK, tier=tier or "UNKNOWN",
                   reason=f"unknown/unmapped trigger_source '{trigger_source}' — fail closed")
        return res
    tcfg = pol["tiers"][tier]
    res["tier"] = tier

    # --- 2. T2 requires an active trigger; without one it drops to broad/metadata ---
    if tcfg.get("requires_active_trigger") and has_active_trigger is False:
        tier = "T3"
        tcfg = pol["tiers"]["T3"]
        res["tier"] = "T3"
        res["reason_note"] = "T2 source with no active trigger -> downgraded to T3 metadata-only"

    lk = _lane_kind(lane, model, pol)
    res["lane_kind"] = lk

    # --- 3. Cold universe: no research at all ---
    if tcfg.get("no_research"):
        res.update(decision=BLOCK, lane_used="none", reason=f"{tier}: cold universe — no research")
        return res

    # --- 4. Broad-universe tiers never call an LLM ---
    if not tcfg.get("llm_allowed", False):
        if lk == "metadata":
            res.update(decision=ALLOW, lane_used="metadata",
                       reason=f"{tier}: metadata-only enrichment allowed", expires_at=_expiry(now, tcfg, pol))
        else:
            res.update(decision=METADATA_ONLY, lane_used="metadata",
                       reason=f"{tier}: broad universe — LLM lane '{lane}' downgraded to metadata-only (no LLM)")
        return res

    # --- 5. Paid model is never an allowed lane (no paid fallback) ---
    if lk == "cloud_paid":
        res.update(decision=BLOCK, lane_used="none",
                   reason="paid model is never an allowed research lane (no paid fallback) — use free-OAuth or defer")
        return res

    if lk == "unknown":
        res.update(decision=BLOCK, lane_used="none", reason=f"unknown lane '{lane}' — fail closed")
        return res

    # --- 6. Market-hours local-heavy block (matches LOCAL_LLM_RUNTIME_POLICY) ---
    if lk == "local_heavy" and _is_market_hours(now, pol):
        res.update(decision=BLOCK, lane_used="none",
                   reason="local heavy model (27B/31B) blocked during market hours — defer to overnight or use free-OAuth")
        return res

    # --- 7. Cloud requested but unavailable -> DEFER (never paid / local-heavy fallback) ---
    if lk == "cloud_free" and not cloud_available:
        res.update(decision=DEFER, lane_used="none",
                   reason="free-OAuth cloud lane unavailable — DEFER (never fall back to paid or local-heavy)")
        return res

    # --- 7b. External cloud only for T0/T1 (audit: stop OAuth spray on T2/T3) ---
    if lk == "cloud_free":
        allowed = pol.get("external_cloud_tiers") or ["T0", "T1"]
        if tier not in allowed:
            res.update(decision=DEFER, lane_used="none",
                       reason=f"{tier}: external cloud reserved for {allowed} — DEFER")
            return res
        ext_cap = pol.get("max_external_symbols_per_run")
        if symbols_this_run is not None and ext_cap is not None and symbols_this_run >= ext_cap:
            res.update(decision=DEFER, lane_used="none",
                       reason=f"global external symbol cap {ext_cap}/run reached — DEFER")
            return res

    # --- 8. Duplicate suppression ---
    if dedup_fresh:
        res.update(decision=pol.get("dedup", {}).get("decision_when_fresh", DEFER), lane_used="none",
                   reason=f"duplicate — same (symbol,research_type,lane) researched inside "
                          f"{pol.get('dedup',{}).get('freshness_hours',12)}h window")
        return res

    # --- 9. Caps ---
    cap_calls = tcfg.get("max_llm_calls_per_day")
    if calls_today is not None and cap_calls is not None and calls_today >= cap_calls:
        res.update(decision=DEFER, lane_used="none",
                   reason=f"{tier}: daily LLM call cap {cap_calls} reached ({calls_today}) — DEFER")
        return res
    cap_sym = tcfg.get("max_symbols_per_run")
    if symbols_this_run is not None and cap_sym is not None and symbols_this_run >= cap_sym:
        res.update(decision=DEFER, lane_used="none",
                   reason=f"{tier}: per-run symbol cap {cap_sym} reached ({symbols_this_run}) — DEFER")
        return res

    # --- 10. ALLOW ---
    res.update(decision=ALLOW, lane_used=lk, reason=f"{tier}: within budget", expires_at=_expiry(now, tcfg, pol))
    return res


def _expiry(now, tcfg, pol):
    ttl = tcfg.get("research_ttl_hours", pol.get("default_research_ttl_hours", 24))
    return (now + _dt.timedelta(hours=ttl)).isoformat()


def _selftest(pol=None):
    """Exercise every invariant. Returns (results, ok)."""
    pol = pol or _load_policy()
    mkt = _dt.datetime(2026, 6, 29, 9, 30)      # inside 06:00-12:00 ET window
    night = _dt.datetime(2026, 6, 29, 22, 0)     # outside market hours
    cases = [
        ("unknown source fails closed", dict(symbol="X", trigger_source="who_knows", lane="cloud_grok"), BLOCK),
        ("T0 holdings cloud allowed", dict(symbol="AAPL", trigger_source="holdings", lane="cloud_grok"), ALLOW),
        ("T1 go candidate local allowed", dict(symbol="NVDA", trigger_source="go_candidate", lane="local_fast"), ALLOW),
        ("T2 directive with trigger allowed (local)", dict(symbol="SMCI", trigger_source="active_directive", lane="local_fast", has_active_trigger=True), ALLOW),
        ("T2 directive WITHOUT trigger -> metadata only", dict(symbol="SMCI", trigger_source="active_directive", lane="cloud_grok", has_active_trigger=False), METADATA_ONLY),
        ("T3 broad universe LLM -> metadata only", dict(symbol="FOO", trigger_source="broad_universe", lane="cloud_grok"), METADATA_ONLY),
        ("top20_curation broad LLM -> metadata only", dict(symbol="FOO", trigger_source="top20_curation", lane="cloud_chatgpt"), METADATA_ONLY),
        ("T3 metadata lane allowed", dict(symbol="FOO", trigger_source="broad_universe", lane="metadata"), ALLOW),
        ("T4 cold universe blocked", dict(symbol="ZZZ", trigger_source="cold_universe", lane="metadata"), BLOCK),
        ("paid model never allowed", dict(symbol="AAPL", trigger_source="holdings", lane="cloud_paid"), BLOCK),
        ("market-hours local heavy blocked", dict(symbol="AAPL", trigger_source="holdings", lane="local_heavy", now=mkt), BLOCK),
        ("overnight local heavy allowed", dict(symbol="AAPL", trigger_source="holdings", lane="local_heavy", now=night), ALLOW),
        ("cloud unavailable -> defer", dict(symbol="AAPL", trigger_source="holdings", lane="cloud_grok", cloud_available=False), DEFER),
        ("duplicate -> defer", dict(symbol="AAPL", trigger_source="holdings", lane="cloud_grok", dedup_fresh=True), DEFER),
        ("T1 cap reached -> defer", dict(symbol="NVDA", trigger_source="go_candidate", lane="cloud_grok", calls_today=999), DEFER),
        ("T2 external cloud -> defer", dict(symbol="SMCI", trigger_source="active_directive", lane="cloud_grok", has_active_trigger=True), DEFER),
        ("T3 external cloud -> defer", dict(symbol="FOO", trigger_source="broad_universe", lane="cloud_grok"), METADATA_ONLY),
    ]
    results, ok = [], True
    for name, kw, expect in cases:
        kw.setdefault("now", night if "now" not in kw else kw["now"])
        d = decide(policy=pol, **kw)
        passed = d["decision"] == expect
        ok = ok and passed
        results.append({"case": name, "expected": expect, "got": d["decision"], "pass": passed,
                        "tier": d["tier"], "reason": d["reason"]})
    return results, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    pol = _load_policy()
    results, ok = _selftest(pol)
    summary = {
        "ok": ok,
        "fail_closed": pol.get("fail_closed"),
        "no_paid_fallback": pol.get("no_paid_fallback"),
        "tiers": {k: v["name"] for k, v in pol["tiers"].items()},
        "market_hours_blocked_local": pol["market_hours"]["blocked_local_models"],
        "free_oauth_lanes": pol["lanes"]["free_oauth"],
        "selftest": results,
        "note": "Advisory only. No trades, no broker writes, no gate bypass. Broad universe never calls an LLM.",
    }
    if a.selftest:
        print(json.dumps({"ok": ok, "failed": [r for r in results if not r["pass"]]}, indent=2))
        sys.exit(0 if ok else 1)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
