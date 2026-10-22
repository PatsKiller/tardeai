#!/usr/bin/env python3
"""Calibration shadow harness -- test each PROPOSED threshold beside the current one, forward (operator design
2026-10-22, Gate 4 item 3). READ-ONLY on every journal; PROPOSALS ONLY; the operator ratifies.

``signal_calibration`` (Active Trader learning) already measures the journaled decisions and writes threshold
proposals to ``<AT dir>/learning/calibration_report.json`` ("PROPOSED — operator ratifies"). Nothing tested
whether a proposal holds up on sessions it was not fitted on. This harness does that.

1. Each threshold proposal opens a **trial** keyed by its knob. The trial freezes the proposed value and
   records ``first_seen_session``, the last session the proposal was fitted on. A later proposal for the
   same knob that drifts more than ``drift_tolerance`` from the frozen value supersedes the trial and starts a
   new one. The old trial is kept in ``history`` and never deleted.
2. Over the next ``sessions`` sessions after ``first_seen_session`` (the forward, out-of-sample window), it
   reads the journaled decisions (``<AT dir>/learning/trade_learning.jsonl``, ``type: decision`` with an
   outcome) and evaluates both filters on the same decisions:
   - current: feature passes the current threshold;
   - proposed: feature passes the frozen proposed value.

   For each it computes the decisions admitted, WORKED / STOPPED / NO_TOUCH, the worked rate, the mean
   rule-exit %, the worked decisions the proposal would drop and the stopped ones it would avoid.
3. It writes a comparison report with one recommendation per trial:
   - ``IN_PROGRESS``: fewer than N sessions so far; interim numbers are shown;
   - ``INSUFFICIENT_SAMPLE``;
   - ``RECOMMEND_ADOPT``;
   - ``RECOMMEND_REJECT``;
   - ``NO_CLEAR_EDGE``.

   Every recommendation is a proposal; config changes only by operator ratification. One-click approval in
   Ops is a later step.

The current value comes from ``config/scalp_signal_engine.yaml`` at the knob path when the operator has set
one. Otherwise it comes from ``current_values`` in ``config/calibration_shadow_harness.json`` (labelled
``declared``). Otherwise it is ``None``, rendered "not computed": the engine default lives in the broker
execution file set, which this harness does not read. The baseline is then "no threshold" and the report says so.

Run modes (n8n lane ``calibration-shadow-harness``; the dispatcher row is at stage shadow):
  --dry-run   evaluate and print the summary; write nothing (what a shadow fire runs)
  (default)   also write data/runtime/calibration_shadow_report.json + .md and the lane receipt
              data/runtime/calibration-shadow-harness_last.json

AUTHORITY: READ_ONLY_ADVISORY. No broker, no order, no Telegram, no model call, no config write.
MBI_BEHAVIOR=0: a recommendation is never applied by code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

LANE_ID = "calibration-shadow-harness"
SCHEMA = "CalibrationShadowReport@v1"
CONFIG_PATH = ROOT / "config" / "calibration_shadow_harness.json"
ENGINE_YAML = ROOT / "config" / "scalp_signal_engine.yaml"
REPORT_REL = Path("data") / "runtime" / "calibration_shadow_report.json"
RECEIPT_REL = Path("data") / "runtime" / f"{LANE_ID}_last.json"
STOPPED = frozenset({"STOPPED", "AT_OR_BELOW_STOP"})
OUTCOMES = frozenset({"WORKED", "NO_TOUCH"}) | STOPPED
OPERATOR_LINE = "PROPOSED — operator ratifies; config is unchanged until then."
DEFAULTS = {"sessions": 5, "min_sample": 30, "min_edge": 0.03, "max_exit_regression_pct": 0.10,
            "drift_tolerance": 0.10, "current_values": {}, "current_scale": {}}


# ── inputs ──────────────────────────────────────────────────────────────────────────────────────────────────────

def load_config(path: Optional[Path] = None) -> dict:
    cfg = dict(DEFAULTS)
    try:
        doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    for k in DEFAULTS:
        if k in doc:
            cfg[k] = doc[k]
    return cfg


def at_dir() -> Path:
    """The Active Trader journal root, resolved by the data-broker microstructure projection (read side)."""
    from lib.data_broker.microstructure import store_dir

    return store_dir().parent


def state_root() -> Path:
    from lib.canonical_store_registry import production_state_root

    return Path(production_state_root())


def read_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def read_decisions(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        fh = Path(path).open(encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("type") == "decision" and (r.get("outcome") or {}).get("result") in OUTCOMES:
                out.append(r)
    return out


def current_value(knob: str, cfg: dict, engine_yaml: Path = ENGINE_YAML) -> tuple[Optional[float], str]:
    """(value in the FEATURE's units, provenance). Engine config first, then the declared map, else None.

    ``current_scale`` converts a knob stored in other units than its journal feature (min_stop.pct_of_price is a
    fraction, 0.01; the feature risk_pct is a percent, 1.0)."""
    value, prov = _raw_current(knob, cfg, engine_yaml)
    scale = (cfg.get("current_scale") or {}).get(knob)
    if value is not None and isinstance(scale, (int, float)) and not isinstance(scale, bool) and scale != 1:
        return value * float(scale), f"{prov} ×{scale:g} (feature units)"
    return value, prov


def _raw_current(knob: str, cfg: dict, engine_yaml: Path) -> tuple[Optional[float], str]:
    try:
        import yaml  # type: ignore

        node: Any = yaml.safe_load(Path(engine_yaml).read_text(encoding="utf-8")) or {}
        for part in knob.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, (int, float)) and not isinstance(node, bool):
            return float(node), "config/scalp_signal_engine.yaml"
    except Exception:  # noqa: BLE001 -- unreadable config falls through to the declared value
        pass
    declared = (cfg.get("current_values") or {}).get(knob)
    if isinstance(declared, (int, float)) and not isinstance(declared, bool):
        return float(declared), "declared in config/calibration_shadow_harness.json"
    return None, "not computed: engine default not readable outside the broker execution set"


def direction(knob: str, feature_stats: Optional[dict]) -> str:
    """'max' (pass when value <= threshold) or 'min' (pass when value >= threshold)."""
    leaf = knob.rsplit(".", 1)[-1]
    if leaf.startswith("max_"):
        return "max"
    if leaf.startswith("min_"):
        return "min"
    fs = feature_stats or {}
    w, s = fs.get("worked_median"), fs.get("stopped_median")
    if isinstance(w, (int, float)) and isinstance(s, (int, float)):
        return "min" if w >= s else "max"
    return "min"


# ── evaluation ──────────────────────────────────────────────────────────────────────────────────────────────────

def _passes(x: float, t: Optional[float], d: str) -> bool:
    if t is None:
        return True
    return x <= t if d == "max" else x >= t


def stats(decisions: list[dict], feature: str, threshold: Optional[float], d: str) -> dict:
    admitted = []
    for r in decisions:
        x = (r.get("features") or {}).get(feature)
        if isinstance(x, (int, float)) and not isinstance(x, bool) and _passes(float(x), threshold, d):
            admitted.append(r)
    res = [(r.get("outcome") or {}).get("result") for r in admitted]
    exits = [float((r.get("outcome") or {}).get("rule_exit_pct")) for r in admitted
             if isinstance((r.get("outcome") or {}).get("rule_exit_pct"), (int, float))]
    n = len(admitted)
    worked = sum(1 for x in res if x == "WORKED")
    return {"threshold": threshold, "admitted": n, "worked": worked, "stopped": sum(1 for x in res if x in STOPPED),
            "no_touch": sum(1 for x in res if x == "NO_TOUCH"),
            "worked_rate": round(worked / n, 4) if n else None,
            "avg_rule_exit_pct": round(statistics.fmean(exits), 3) if exits else None,
            "_ids": {r.get("id") for r in admitted}}


def compare(decisions: list[dict], feature: str, current: Optional[float], proposed: float, d: str) -> dict:
    with_feature = [r for r in decisions if isinstance((r.get("features") or {}).get(feature), (int, float))]
    cur, prop = stats(with_feature, feature, current, d), stats(with_feature, feature, proposed, d)
    by_id = {r.get("id"): r for r in with_feature}
    dropped = cur["_ids"] - prop["_ids"]
    added = prop["_ids"] - cur["_ids"]

    def count(ids, results):
        return sum(1 for i in ids if (by_id[i].get("outcome") or {}).get("result") in results)

    out = {"decisions": len(with_feature), "current": cur, "proposed": prop,
           "worked_dropped": count(dropped, {"WORKED"}), "stopped_avoided": count(dropped, STOPPED),
           "worked_added": count(added, {"WORKED"}), "stopped_added": count(added, STOPPED)}
    for side in ("current", "proposed"):
        out[side] = {k: v for k, v in out[side].items() if k != "_ids"}
    return out


def recommend(cmp: dict, *, sessions_done: int, sessions_needed: int, cfg: dict) -> tuple[str, str]:
    cur, prop = cmp["current"], cmp["proposed"]
    if sessions_done < sessions_needed:
        return "IN_PROGRESS", f"{sessions_done}/{sessions_needed} forward sessions observed"
    if prop["admitted"] < int(cfg["min_sample"]) or cur["admitted"] < int(cfg["min_sample"]):
        return "INSUFFICIENT_SAMPLE", (f"admitted current {cur['admitted']} / proposed {prop['admitted']} < "
                                       f"min_sample {cfg['min_sample']}")
    dr = (prop["worked_rate"] or 0.0) - (cur["worked_rate"] or 0.0)
    ce, pe = cur["avg_rule_exit_pct"], prop["avg_rule_exit_pct"]
    de = None if ce is None or pe is None else pe - ce
    tol = float(cfg["max_exit_regression_pct"])
    if dr >= float(cfg["min_edge"]) and (de is None or de >= -tol):
        return "RECOMMEND_ADOPT", f"worked rate {dr:+.3f}, mean rule exit {_pp(de)}"
    if dr <= -float(cfg["min_edge"]) or (de is not None and de < -tol):
        return "RECOMMEND_REJECT", f"worked rate {dr:+.3f}, mean rule exit {_pp(de)}"
    return "NO_CLEAR_EDGE", f"worked rate {dr:+.3f} inside ±{cfg['min_edge']}, mean rule exit {_pp(de)}"


def _pp(v: Optional[float]) -> str:
    return "not computed" if v is None else f"{v:+.3f} pp"


# ── trials ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _trial_id(knob: str, value: float, first: str) -> str:
    return hashlib.sha256(f"{knob}|{value}|{first}".encode()).hexdigest()[:12]


def update_trials(previous: Optional[dict], calibration: dict, cfg: dict) -> tuple[list[dict], list[dict]]:
    """(active trials, history). Pure. A drifted proposal supersedes its knob's trial; nothing is deleted."""
    prev_trials = {t["knob"]: t for t in (previous or {}).get("trials", [])}
    history = list((previous or {}).get("history", []))
    sessions = sorted(calibration.get("sessions") or [])
    fitted_through = sessions[-1] if sessions else None
    active: list[dict] = []
    seen = set()
    for p in calibration.get("proposals") or []:
        if p.get("type") != "threshold" or not str(p.get("status", "")).startswith("PROPOSED"):
            continue
        knob, val = p.get("knob"), p.get("proposed_value")
        if not knob or not isinstance(val, (int, float)) or knob in seen:
            continue
        seen.add(knob)
        old = prev_trials.get(knob)
        if old is not None:
            frozen = float(old["frozen_value"])
            drift = abs(float(val) - frozen) / (abs(frozen) or 1.0)
            if drift <= float(cfg["drift_tolerance"]):
                active.append({**old, "latest_proposed_value": float(val), "latest_why": p.get("why")})
                continue
            history.append({**old, "status": "SUPERSEDED", "superseded_by_value": float(val),
                            "superseded_on": fitted_through})
        if fitted_through is None:
            continue
        active.append({"trial_id": _trial_id(knob, float(val), fitted_through), "knob": knob,
                       "feature": p.get("feature"), "frozen_value": float(val), "latest_proposed_value": float(val),
                       "first_seen_session": fitted_through, "why": p.get("why"), "latest_why": p.get("why")})
    for knob, old in prev_trials.items():
        if knob not in seen:
            history.append({**old, "status": "WITHDRAWN", "withdrawn_on": fitted_through})
    return active, history


# ── report ──────────────────────────────────────────────────────────────────────────────────────────────────────

def build_report(*, calibration: Optional[dict], decisions: list[dict], previous: Optional[dict], cfg: dict,
                 engine_yaml: Path = ENGINE_YAML, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    base = {"schema": SCHEMA, "lane_id": LANE_ID, "generated_at": now.isoformat(), "operator_line": OPERATOR_LINE,
            "authority": {"read_only": True, "config_write": False, "order": False, "broker_write": False},
            "config": {k: cfg[k] for k in DEFAULTS if k not in ("current_values", "current_scale")}}
    if not calibration or calibration.get("status") not in (None, "ok"):
        return {**base, "status": "NO_CALIBRATION_REPORT", "trials": [], "history": (previous or {}).get("history", []),
                "produced_count": 0}
    trials, history = update_trials(previous, calibration, cfg)
    features = calibration.get("features") or {}
    all_sessions = sorted({r.get("session_date") for r in decisions if r.get("session_date")})
    out_trials = []
    n_needed = int(cfg["sessions"])
    for t in trials:
        feature = t.get("feature")
        d = direction(t["knob"], features.get(feature))
        cur, prov = current_value(t["knob"], cfg, engine_yaml)
        window = [s for s in all_sessions if s > t["first_seen_session"]][:n_needed]
        fwd = [r for r in decisions if r.get("session_date") in set(window)]
        cmp = compare(fwd, feature, cur, t["frozen_value"], d)
        rec, why = recommend(cmp, sessions_done=len(window), sessions_needed=n_needed, cfg=cfg)
        fitted = set(calibration.get("sessions") or [])
        ins = compare([r for r in decisions if r.get("session_date") in fitted], feature, cur, t["frozen_value"], d)
        out_trials.append({**t, "direction": d, "current_value": cur, "current_provenance": prov,
                           "baseline": "current threshold" if cur is not None else "no threshold (current not computed)",
                           "forward_sessions": window, "sessions_needed": n_needed, "forward": cmp,
                           "in_sample": {**ins, "label": "IN_SAMPLE — the sessions the proposal was fitted on"},
                           "recommendation": rec, "recommendation_reason": why, "approval": OPERATOR_LINE})
    return {**base, "status": "ok", "calibration_generated_at": calibration.get("generated_at"),
            "calibration_sessions": calibration.get("sessions"), "decisions_read": len(decisions),
            "trials": out_trials, "history": history, "produced_count": len(out_trials)}


def render_md(rep: dict) -> str:
    lines = ["# Calibration shadow harness", "",
             f"Status: {rep.get('status')} · generated {rep.get('generated_at')} · {OPERATOR_LINE}", ""]
    if not rep.get("trials"):
        lines.append("No PROPOSED threshold to test." if rep.get("status") == "ok" else
                     "Calibration report missing or not ok — nothing evaluated.")
        return "\n".join(lines) + "\n"
    lines += ["| knob | current | proposed | forward sessions | admitted cur/prop | worked rate cur/prop | "
              "mean rule exit cur/prop | recommendation |", "|---|---|---|---|---|---|---|---|"]
    for t in rep["trials"]:
        f = t["forward"]
        cur = "not computed" if t["current_value"] is None else f"{t['current_value']:g}"
        lines.append(
            f"| `{t['knob']}` ({t['direction']}) | {cur} | {t['frozen_value']:g} | "
            f"{len(t['forward_sessions'])}/{t['sessions_needed']} | {f['current']['admitted']}/{f['proposed']['admitted']} | "
            f"{f['current']['worked_rate']}/{f['proposed']['worked_rate']} | "
            f"{f['current']['avg_rule_exit_pct']}/{f['proposed']['avg_rule_exit_pct']} | "
            f"**{t['recommendation']}** — {t['recommendation_reason']} |")
    lines += ["", "Current values marked *not computed* compare the proposal against no threshold.",
              "In-sample numbers (the fitted sessions) are in the JSON report under `in_sample`."]
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="evaluate and print; write nothing")
    ap.add_argument("--at-dir", type=Path, default=None, help="Active Trader journal root (default: data broker)")
    ap.add_argument("--state-root", type=Path, default=None, help="where data/runtime outputs go")
    ap.add_argument("--config", type=Path, default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    root_at = a.at_dir or at_dir()
    root_state = a.state_root or state_root()
    calibration = read_json(root_at / "learning" / "calibration_report.json")
    decisions = read_decisions(root_at / "learning" / "trade_learning.jsonl")
    previous = read_json(root_state / REPORT_REL)
    rep = build_report(calibration=calibration, decisions=decisions, previous=previous, cfg=cfg)
    summary = {"lane_id": LANE_ID, "status": rep["status"], "dry_run": bool(a.dry_run),
               "decisions_read": rep.get("decisions_read", 0),
               "trials": [{"knob": t["knob"], "current": t["current_value"], "proposed": t["frozen_value"],
                           "forward_sessions": len(t["forward_sessions"]), "recommendation": t["recommendation"],
                           "in_sample_worked_rate_cur_prop": [t["in_sample"]["current"]["worked_rate"],
                                                              t["in_sample"]["proposed"]["worked_rate"]]}
                          for t in rep["trials"]]}
    from lib import lane_last_receipt as lr
    from lib.lane_output import emit as lane_emit, output_block

    n = int(rep["produced_count"])
    empty = None if n else ("no_calibration_report" if rep["status"] != "ok" else "no_proposals")
    block = output_block(produced=n, attempted=n, empty_reason=("dry_run" if a.dry_run else empty), unit="trial")
    if a.dry_run:
        lr.dry_run_report(LANE_ID, summary, would_write=[str(root_state / REPORT_REL),
                                                        str((root_state / REPORT_REL).with_suffix(".md"))],
                          receipt=root_state / RECEIPT_REL)
        lane_emit(LANE_ID, "dry_run", output_block(produced=0, attempted=n, empty_reason="dry_run", unit="trial"))
        return 0
    print(json.dumps(summary, indent=1, sort_keys=True))
    started = rep["generated_at"]
    _atomic_write(root_state / REPORT_REL, json.dumps(rep, indent=1, sort_keys=True) + "\n")
    _atomic_write((root_state / REPORT_REL).with_suffix(".md"), render_md(rep))
    lr.write_lane_receipt(LANE_ID, ok=rep["status"] == "ok", exit_code=0, started_at=started,
                          script="calibration_shadow_harness.py", path=root_state / RECEIPT_REL,
                          summary={"status": rep["status"], "trials": n, "report": str(REPORT_REL)},
                          produced_count=n, attempted_count=n, empty_reason=empty)
    lane_emit(LANE_ID, "live", block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
