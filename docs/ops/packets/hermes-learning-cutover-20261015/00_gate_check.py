#!/usr/bin/env python3
"""hermes-learning cutover — READ-ONLY gate check against the SERVED release (default CURRENT) and the ledger.

    python3 00_gate_check.py                     # what is met, what is not; exit 0 only when every gate for --phase is met
    python3 00_gate_check.py --phase claim       # gates before C2 (PIPELINE_EFFECT_CLAIM=1 on the learn line)
    python3 00_gate_check.py --phase live        # gates before C3 (owner -> n8n; the live n8n run with cron present)
    python3 00_gate_check.py --phase promote     # gates before PR-3 (stage cutover)

Never writes: config files are read as text/JSON, the ledger with sqlite ``mode=ro``. Imports the SERVED release's
scripts/lib/n8n_process_keys.py only to evaluate today's learn key (pure function).

Gates
  B   builds served: G3 (gateway p: key validation + executor validated-marker claim), G4 (executor off-peak gate +
      offpeak_gate on the five learn lanes), G5a (hermes_tag_engine bridge route + llm_route), G5b (host intent route
      + --notify queue + consumer merge).
  S   shadow evidence: 5 consecutive daily dry_run PARITY slots (03_parity.py --mode dry_run --days 5), run by hand.
  C   config state for the phase: claim -> cron_claim true; live -> + spec mode live, live_arg = cutover_live_arg,
      registry stage canary, relay live-lanes env lists the five lanes (operator-checked: the env file is not read);
      promote -> + stage cutover and the 5-day LIVE parity (03_parity.py --mode live --days 5).
  O   effect owners: claim -> owner rows exist = cron; live -> cron (C3 moves them); promote -> n8n.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROCESS = "hermes-learning"
LEARN_STEPS = ("outcome_grader", "tag_engine", "outcome_feedback_agent", "outcome_learning", "config_governor")


def _served() -> Path:
    return Path(
        os.environ.get("SERVED") or (Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT")
    ).resolve()


def _state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


def _json(root: Path, rel: str) -> dict:
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="00_gate_check.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--phase", choices=("builds", "claim", "live", "promote"), default="builds")
    a = ap.parse_args(argv)
    root = _served()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))

    # ── B: builds served ──
    gw = _text(root, "scripts/lib/n8n_coordination_gateway.py")
    ex = _text(root, "scripts/n8n_run_executor.py")
    check(
        "B.G3 gateway validates p: keys",
        "run_process_key_invalid" in gw and (root / "scripts/lib/n8n_process_keys.py").exists(),
    )
    check("B.G3 executor claims only gateway-validated p: rows", "effect_process_key_unvalidated" in ex)
    check("B.G4 executor off-peak gate", "def offpeak_verdict" in ex)
    allow = {e.get("lane_id"): e for e in _json(root, "config/n8n_run_allowlist.json").get("lanes", [])}
    spec = (_json(root, "config/n8n_fabric_processes.json").get("processes") or {}).get(PROCESS) or {}
    steps = spec.get("steps") or {}
    lanes = {sid: (steps.get(sid) or {}).get("lane_id") for sid in LEARN_STEPS}
    check(
        "B.G4 five learn lanes declare offpeak_gate bulk",
        all((allow.get(lane) or {}).get("offpeak_gate") == "bulk" for lane in lanes.values()),
    )
    routes = _text(root, "scripts/lib/governed_process_routes.py")
    check(
        "B.G5a hermes_tag_engine bridge route",
        "'hermes_tag_engine': 'hermes_tag_engine'" in routes
        and '"hermes_tag_engine": "hermes_tag_engine"' in _text(root, "scripts/lib/cio_governed_model_bridge.py"),
    )
    check(
        "B.G5a tag-engine lane llm_route",
        (allow.get(lanes["tag_engine"]) or {}).get("llm_route", {}).get("process_id") == "hermes_tag_engine",
    )
    host = _json(root, "config/host_comms_intent_routes.json")
    check("B.G5b host intent route", any(r.get("kind") == "hermes_closed_loop_alert" for r in host.get("routes", [])))
    check(
        "B.G5b --notify queue + consumer merge",
        '"queue"' in _text(root, "scripts/lib/hermes_outcome_bus/alert_notifications.py")
        and "load_host_intent_routes" in _text(root, "scripts/lib/n8n_comms_intent_consumption.py"),
    )

    # today's scheduled learn key, evaluated by the SERVED validator (pure)
    try:
        spec_mod = importlib.util.spec_from_file_location(
            "served_process_keys", root / "scripts/lib/n8n_process_keys.py"
        )
        PK = importlib.util.module_from_spec(spec_mod)
        sys.modules["served_process_keys"] = PK  # dataclasses resolve their module by name
        sys.path.insert(0, str(root))
        spec_mod.loader.exec_module(PK)  # type: ignore[union-attr]
        src = PK.load_sources(root)
        today = datetime.now(ZoneInfo("America/New_York"))
        slot = today.strftime("%Y%m%d") + "T1050"
        at = today.replace(hour=10, minute=55, second=0, microsecond=0)
        for mode in ("dry_run", "live"):
            c = PK.check_process_key(
                f"p:{lanes['outcome_grader']}:{mode}:{slot}", lanes["outcome_grader"], mode, sources=src, now=at
            )
            print(f"  served validator: p:{lanes['outcome_grader']}:{mode}:{slot} at 10:55 ET -> {c.state}")
    except Exception as exc:  # noqa: BLE001 - a report, not a gate decision
        print(f"  served validator not loadable: {type(exc).__name__}: {exc}")

    # ── C: config state ──
    eff = _json(root, "config/n8n_effect_keys.json").get("lanes") or {}
    reg = {r.get("lane_id"): r for r in _json(root, "config/lane_registry.json").get("lanes", [])}
    cron_claim = all((eff.get(lane) or {}).get("cron_claim") is True for lane in lanes.values())
    live_cfg = spec.get("mode") == "live" and all(
        (allow.get(lane) or {}).get("live_arg") == (steps.get(sid) or {}).get("cutover_live_arg")
        for sid, lane in lanes.items()
    )
    stages = {((reg.get(lane) or {}).get("scheduler") or {}).get("stage") for lane in lanes.values()}
    tune_lane = (steps.get("autonomous_self_tune") or {}).get("lane_id")
    tune_stage = ((reg.get(tune_lane) or {}).get("scheduler") or {}).get("stage")
    print(
        f"  config: spec mode={spec.get('mode')} cron_claim(all learn)={cron_claim} learn stages={sorted(map(str, stages))}"
        f" tune stage={tune_stage}"
    )

    # ── O: owners ──
    owners: dict[str, str | None] = {}
    ledger = _state_root() / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    try:
        conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        for lane in lanes.values():
            try:
                r = conn.execute("SELECT owner, epoch FROM effect_owners WHERE process = ?", (lane,)).fetchone()
            except sqlite3.OperationalError:
                r = None
            owners[lane] = None if r is None else f"{r['owner']}@{r['epoch']}"
        conn.close()
    except sqlite3.Error as exc:
        print(f"  ledger unreadable: {type(exc).__name__}")
    print(f"  owners: {owners}")

    if a.phase in ("claim", "live", "promote"):
        check("C cron_claim true (PR-1 served)", cron_claim)
        check("O owner rows exist (C1)", all(owners.get(lane) for lane in lanes.values()))
    if a.phase == "claim":
        check("O owners are cron", all(str(owners.get(lane) or "").startswith("cron@") for lane in lanes.values()))
    if a.phase in ("live", "promote"):
        check("C spec mode live + live_arg = cutover_live_arg (PR-2 served)", live_cfg)
        check("C learn lanes at canary/cutover", stages <= {"canary", "cutover"} and bool(stages))
        check("C tune lane still shadow (manifest split not done)", tune_stage == "shadow")
    if a.phase == "live":
        check(
            "O owners are cron (C3 moves them)",
            all(str(owners.get(lane) or "").startswith("cron@") for lane in lanes.values()),
        )
    if a.phase == "promote":
        check("O owners are n8n", all(str(owners.get(lane) or "").startswith("n8n@") for lane in lanes.values()))

    print(f"SERVED: {root}")
    for name, ok, detail in checks:
        print(f"  [{'met' if ok else 'NOT MET'}] {name}{(' - ' + detail) if detail else ''}")
    print(
        "  [operator] S: 03_parity.py --mode dry_run --days 5 PASS; live phase: relay env lists the five learn lanes;"
        " promote: 03_parity.py --mode live --days 5 PASS"
    )
    ok = all(c[1] for c in checks)
    print(f"GATE {a.phase}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
