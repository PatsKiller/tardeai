#!/usr/bin/env python3
"""finviz_screen_compiler.py — Phase 1: canonical registry -> runtime executor.

Architecture (per the 2026-07-20 review):

    config/finviz_screen_registry.yaml   version-controlled canonical source
        -> compile      deterministic URL + filter manifest + definition hash
        -> VALIDATE     every token proven APPLIED against live Finviz
        -> upsert       idempotent write into finviz_screeners (the executor)
        -> runtime      finviz_screener_runner.py reads the DB table

The YAML alone does nothing: the executor reads the DB. Equally, hand-editing
the DB loses review history. The compiler is the only sanctioned bridge.

HARD GATE: a definition containing a token Finviz silently ignores is REFUSED,
never upserted. That check exists because 16 of 54 tokens already in production
were found doing nothing (fa_dividendyield_* is not a real filter family;
decimals like ta_beta_u1.2 are dropped). Without the gate, a screen ships
looking healthy — right schema, thousands of rows — while selecting nothing.

  finviz_screen_compiler.py                 # compile + report (writes nothing)
  finviz_screen_compiler.py --validate      # + live token validation
  finviz_screen_compiler.py --apply         # + idempotent upsert (implies --validate)
  finviz_screen_compiler.py --screen ID     # limit to one definition
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REGISTRY = ROOT / "config" / "finviz_screen_registry.yaml"
EXPORT_BASE = "https://elite.finviz.com/export"
PRESET_BASE = "https://elite.finviz.com/screener.ashx"


def load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text()) or {}


VALID_MODES = ("SHADOW", "VALIDATION_READY", "OPERATIONAL")


def _gov(spec: dict, defaults: dict, key: str, fallback):
    """Per-screen governance value, falling back to registry defaults."""
    if key in spec:
        return spec[key]
    if key in defaults:
        return defaults[key]
    return fallback


def _check_governance(sid: str, m: dict) -> None:
    """Refuse to compile a definition that claims authority it must not have."""
    if m["research_mode"] not in VALID_MODES:
        raise ValueError(f"{sid}: research_mode {m['research_mode']!r} not in {VALID_MODES}")
    if m["research_mode"] == "SHADOW" and (m["proposal_eligible"] or m["execution_eligible"]):
        raise ValueError(f"{sid}: a SHADOW screen cannot be proposal- or execution-eligible")
    if m["execution_eligible"]:
        raise ValueError(f"{sid}: execution_eligible must be false — no Finviz list has "
                         f"execution authority in this phase")


def compile_screen(sid: str, spec: dict, defaults: dict) -> dict:
    """Definition -> deterministic URLs + manifest + hash. Pure; no network."""
    tokens = [f["token"] if isinstance(f, dict) else str(f)
              for f in (spec.get("hard_filters") or [])]
    if not tokens:
        raise ValueError(f"{sid}: no hard_filters — refusing to compile an unfiltered screen")

    # Deterministic ordering so the same semantics always yield the same URL/hash.
    canon = sorted(set(tokens))
    view = spec.get("view") or defaults.get("view", 152)
    cols = spec.get("column_pack") or defaults.get("column_pack", "")
    f_param = ",".join(canon)

    machine_url = f"{EXPORT_BASE}?v={view}&f={f_param}&ft=3&c={cols}"
    human_url = f"{PRESET_BASE}?v={view}&f={f_param}&ft=3"

    manifest = {
        "screen_id": sid,
        "screen_version": spec.get("screen_version", 1),
        "filters_canonical": canon,
        "view": view,
        "column_pack": cols,
        "schedule": spec.get("schedule", ""),
        "play_families": spec.get("play_families", []),
        "run_enabled": _gov(spec, defaults, "run_enabled", True),
        "research_mode": _gov(spec, defaults, "research_mode", "SHADOW"),
        "proposal_eligible": _gov(spec, defaults, "proposal_eligible", False),
        "execution_eligible": _gov(spec, defaults, "execution_eligible", False),
    }
    _check_governance(sid, manifest)
    definition_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]

    return {"screen_id": sid, "manifest": manifest, "machine_url": machine_url,
            "human_url": human_url, "definition_hash": definition_hash,
            "tokens": canon, "spec": spec}


def validate_tokens(compiled: list) -> dict:
    """Prove every token is actually applied by Finviz. Network-bound."""
    from finviz_filter_validator import validate, IGNORED, ERROR
    all_tokens = sorted({t for c in compiled for t in c["tokens"]})
    rep = validate(all_tokens)
    if not rep.get("ok"):
        return {"ok": False, "error": rep.get("error")}
    bad = {t: r for t, r in rep["results"].items() if r["state"] in (IGNORED, ERROR)}
    return {"ok": True, "baseline": rep["baseline_universe"],
            "results": rep["results"], "bad_tokens": bad}


def upsert(compiled: dict, cur) -> str:
    """Idempotent write into the executor table. Returns 'inserted'|'updated'|'unchanged'."""
    sid = compiled["screen_id"]
    spec = compiled["spec"]
    desc = (f"{spec.get('purpose','').strip()} "
            f"[canonical registry v{spec.get('screen_version',1)}, "
            f"def#{compiled['definition_hash']}]").strip()

    cur.execute("""SELECT finviz_url, description, schedule, strategy_type, active,
                          research_mode, proposal_eligible, execution_eligible
                   FROM finviz_screeners WHERE screener_id=%s""", (sid,))
    row = cur.fetchone()
    # `active` means ONLY "the executor runs this screen". A SHADOW screen RUNS
    # (that is how shadow evidence accumulates) but carries proposal_eligible
    # false. Conflating the two is what produced 0 membership rows in Phase 1.
    m = compiled["manifest"]
    active = bool(m["run_enabled"])
    payload = (compiled["machine_url"], desc, spec.get("schedule", ""),
               spec.get("strategy_type", ""), active,
               m["research_mode"], bool(m["proposal_eligible"]),
               bool(m["execution_eligible"]))

    if row is None:
        cur.execute("""INSERT INTO finviz_screeners
                       (screener_id, display_name, strategy_type, finviz_url,
                        description, schedule, active, research_mode,
                        proposal_eligible, execution_eligible, human_review_only,
                        added_by, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,
                               'finviz_screen_compiler',NOW(),NOW())""",
                    (sid, spec.get("display_name", sid), spec.get("strategy_type", ""),
                     compiled["machine_url"], desc, spec.get("schedule", ""), active,
                     m["research_mode"], bool(m["proposal_eligible"]),
                     bool(m["execution_eligible"])))
        return "inserted"

    if tuple(row[:8]) == payload:
        return "unchanged"

    cur.execute("""UPDATE finviz_screeners
                   SET finviz_url=%s, description=%s, schedule=%s,
                       strategy_type=%s, active=%s, research_mode=%s,
                       proposal_eligible=%s, execution_eligible=%s, updated_at=NOW()
                   WHERE screener_id=%s""", (*payload, sid))
    return "updated"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile canonical Finviz screens into the executor")
    ap.add_argument("--apply", action="store_true", help="upsert into finviz_screeners")
    ap.add_argument("--validate", action="store_true", help="live-validate filter tokens")
    ap.add_argument("--screen", default="", help="limit to one screen id")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    reg = load_registry()
    defaults = reg.get("defaults") or {}
    screens = reg.get("screens") or {}
    if args.screen:
        screens = {k: v for k, v in screens.items() if k == args.screen}
        if not screens:
            print(f"no such screen: {args.screen}")
            return 2

    compiled = []
    for sid, spec in screens.items():
        try:
            compiled.append(compile_screen(sid, spec, defaults))
        except ValueError as e:
            print(f"REFUSED {sid}: {e}")
            return 1

    result = {"compiled": len(compiled), "screens": [], "applied": False}
    for c in compiled:
        result["screens"].append({
            "screen_id": c["screen_id"], "definition_hash": c["definition_hash"],
            "tokens": c["tokens"],
            "research_mode": c["manifest"]["research_mode"],
            "run_enabled": c["manifest"]["run_enabled"],
            "proposal_eligible": c["manifest"]["proposal_eligible"],
            "schedule": c["manifest"]["schedule"], "machine_url": c["machine_url"],
            "human_url": c["human_url"]})

    # Validation is mandatory before any write.
    if args.validate or args.apply:
        v = validate_tokens(compiled)
        if not v.get("ok"):
            print(f"REFUSED — validation unavailable: {v.get('error')}")
            return 1
        result["validation"] = {"baseline": v["baseline"],
                                "bad_tokens": list(v["bad_tokens"])}
        if v["bad_tokens"]:
            print("REFUSED — these tokens are NOT APPLIED by Finviz "
                  "(a screen using them would select nothing while looking healthy):")
            for t, r in sorted(v["bad_tokens"].items()):
                print(f"  {t}: {r['state']} {r.get('error','')}")
            for c in compiled:
                hit = [t for t in c["tokens"] if t in v["bad_tokens"]]
                if hit:
                    print(f"  -> {c['screen_id']} depends on: {', '.join(hit)}")
            return 1
        print(f"validation OK — all {sum(len(c['tokens']) for c in compiled)} "
              f"token references applied (baseline {v['baseline']} rows)",
              file=sys.stderr if args.json else sys.stdout)

    if args.apply:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        actions = {}
        for c in compiled:
            actions[c["screen_id"]] = upsert(c, cur)
        conn.commit()
        result["applied"] = True
        result["actions"] = actions

    if args.json:
        print(json.dumps(result, indent=1))
        return 0

    print(f"\ncompiled {result['compiled']} canonical screen(s)")
    for s in result["screens"]:
        print(f"\n  {s['screen_id']}  [{s['research_mode']}] "
              f"run={s['run_enabled']} propose={s['proposal_eligible']}  "
              f"def#{s['definition_hash']}")
        print(f"    schedule : {s['schedule']}")
        print(f"    filters  : {','.join(s['tokens'])}")
        print(f"    machine  : {s['machine_url'][:120]}")
    if result.get("actions"):
        print(f"\nupsert into finviz_screeners: {result['actions']}")
        print("NOTE: SHADOW screens RUN (active=true) so evidence accumulates, but "
              "carry proposal_eligible=false — membership can never become a proposal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
