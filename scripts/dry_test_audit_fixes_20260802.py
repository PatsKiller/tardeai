#!/usr/bin/env python3
"""Dry-test audit fixes (2026-08-02) — no paper execution, no live LLM spend.

Run from project root:
  PYTHONPATH=scripts .venv/bin/python scripts/dry_test_audit_fixes_20260802.py

Exit 0 only if all checks pass.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = 0
FAIL = 0
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        results.append((name, True, detail))
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        results.append((name, False, detail))
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=== Audit fixes dry-test 2026-08-02 ===\n")

    # ── 1. Registry JSON ─────────────────────────────────────────────
    print("[1] llm_process_registry.json")
    reg_path = ROOT / "config" / "llm_process_registry.json"
    reg = json.loads(reg_path.read_text())
    check("registry version >= 3", int(reg.get("version") or 0) >= 3, str(reg.get("version")))
    by_id = {p["id"]: p for p in reg.get("processes") or []}
    maria = by_id.get("watchlist_maria_priority") or {}
    cio = by_id.get("watchlist_cio_synthesis") or {}
    cloud = by_id.get("cloud_review") or {}
    unreg = by_id.get("unregistered") or {}
    check("maria has deepseek-flash allowed", "deepseek-flash" in (maria.get("allowed_lanes") or []),
          str(maria.get("allowed_lanes")))
    check("cio has deepseek-v4 allowed", "deepseek-v4" in (cio.get("allowed_lanes") or []),
          str(cio.get("allowed_lanes")))
    check("cloud_review automated", cloud.get("default_mode") == "automated")
    check("unregistered manual (no free-for-all)", unreg.get("default_mode") == "manual")

    # ── 2. llm_consumption lane resolution (no DB) ───────────────────
    print("\n[2] llm_consumption lane helpers")
    import lib.llm_consumption as lc
    lc.reload_registry()
    lanes_m = lc._lanes_for_process(maria, reg)
    lanes_c = lc._lanes_for_process(cio, reg)
    check("lanes_for maria includes deepseek-flash", "deepseek-flash" in lanes_m, str(lanes_m))
    check("lanes_for cio includes deepseek-v4", "deepseek-v4" in lanes_c, str(lanes_c))
    # should_call with mocked config path: seed if DB available
    try:
        lc.ensure_schema()
        cfg = lc.get_process_config("watchlist_maria_priority")
        check("DB config maria allows deepseek-flash",
              "deepseek-flash" in (cfg.get("allowed_lanes") or []),
              str(cfg.get("allowed_lanes")))
        check("DB config maria mode automated", cfg.get("mode") == "automated", str(cfg.get("mode")))
        cfg_cio = lc.get_process_config("watchlist_cio_synthesis")
        check("DB config cio allows deepseek-v4",
              "deepseek-v4" in (cfg_cio.get("allowed_lanes") or []),
              str(cfg_cio.get("allowed_lanes")))
        # should_call deepseek-flash on maria automated without manual
        d = lc.should_call("watchlist_maria_priority", "deepseek-flash", manual_trigger=False)
        check("should_call maria deepseek-flash automated allow", d.get("allow") is True, str(d))
        # unregistered still manual
        d2 = lc.should_call("unregistered", "deepseek-flash", manual_trigger=False)
        check("should_call unregistered blocks without manual", d2.get("allow") is False and d2.get("reason") == "manual_mode", str(d2))
        d3 = lc.should_call("unregistered", "deepseek-flash", manual_trigger=True)
        check("should_call unregistered allows manual_trigger", d3.get("allow") is True, str(d3))
    except Exception as e:
        check("DB seed/config (optional)", False, f"skipped/failed: {e}")

    # ── 3. Watch quality intake ──────────────────────────────────────
    print("\n[3] watch quality intake")
    wqg = json.loads((ROOT / "config" / "watch_quality_gate.json").read_text())
    check("enforce_intake true", wqg.get("enforce_intake") is True)
    from lib.watch_quality_intake import admit_source, should_insert_ai_discovered, load_cfg
    cfg = load_cfg()
    check("load_cfg enforce", cfg.get("enforce_intake") is True)
    op = admit_source("operator")
    check("operator always admitted", op.get("admit") is True, op.get("reason"))
    # Live α check for ai_discovered
    try:
        ai = should_insert_ai_discovered()
        # With current data median α ~ -2.43 and n>30, expect block when enforce on
        if ai.get("low_efficacy"):
            check("ai_discovered low_efficacy blocked", ai.get("admit") is False, str(ai))
        else:
            check("ai_discovered admit (not currently low_efficacy)", ai.get("admit") is True, str(ai))
    except Exception as e:
        check("should_insert_ai_discovered", False, str(e))

    # ── 4. API alias routes present in source ────────────────────────
    print("\n[4] api_v2 alias routes (source)")
    api_src = (ROOT / "scripts" / "api_v2.py").read_text()
    for path in [
        "/api/v2/health/snapshot",
        "/api/v2/consumption/summary",
        "/api/v2/system/llm",
        "/api/v2/agents/maturity",
        "/api/v2/watch/scoreboard",
        "/api/v2/research-intelligence/desk",
        "/api/v2/agent-runtime/status",
    ]:
        check(f"ROUTES has {path}", f'"{path}"' in api_src)

    check("agents summary honesty fields", "is_hold_factory" in api_src and "hold_rate" in api_src)

    # ── 5. Frontend source checks ────────────────────────────────────
    print("\n[5] frontend source")
    ms = (ROOT / "apps/command-center-v3/src/components/MetricStrip.tsx").read_text()
    hl = (ROOT / "apps/command-center-v3/src/lib/homeLabels.ts").read_text()
    ag = (ROOT / "apps/command-center-v3/src/pages/AgentsHub.tsx").read_text()
    check("MetricStrip has RUN SCAN", "RUN SCAN" in ms)
    check("MetricStrip uses isJournalStale", "isJournalStale" in ms)
    check("homeLabels isJournalStale exported", "export function isJournalStale" in hl)
    check("homeLabels lastSessionDay", "export function lastSessionDay" in hl)
    check("AgentsHub honesty banner", "HOLD-factory" in ag or "HOLD factory" in ag)
    check("AgentsHub hold_rate column", "Hold %" in ag)

    # ── 6. homeLabels pure logic (via node if available, else skip) ──
    print("\n[6] isScanStale weekend logic (inline python reimpl check)")
    # Reimplement minimal: Friday date vs Sunday now should NOT be stale
    def last_session_day(now: datetime) -> datetime:
        d = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if d.weekday() == 6:  # Sunday
            d -= timedelta(days=2)
        elif d.weekday() == 5:  # Saturday
            d -= timedelta(days=1)
        return d

    friday = datetime(2026, 7, 31)
    sunday = datetime(2026, 8, 2)
    session = last_session_day(sunday)
    check("Sunday session day is Friday", session.date() == friday.date(), str(session.date()))
    # scan on Friday, now Sunday → not stale
    check("Friday scan not stale on Sunday", friday.date() >= session.date())

    # ── 7. finviz gate hook present ──────────────────────────────────
    print("\n[7] finviz screener intake hook")
    fv = (ROOT / "scripts" / "finviz_screener_runner.py").read_text()
    check("finviz imports quality gate", "should_insert_ai_discovered" in fv)
    check("finviz quality_gate_blocked flag", "quality_gate_blocked" in fv)

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    out = ROOT / "docs/audits/platform-autonomy-2026-08-02/evidence/dry_test_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "pass": PASS, "fail": FAIL,
        "results": [{"name": n, "ok": ok, "detail": d} for n, ok, d in results],
    }, indent=2))
    print(f"Wrote {out}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
