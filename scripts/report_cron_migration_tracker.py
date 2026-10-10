#!/usr/bin/env python3
"""Living per-lane tracker of the cron -> n8n migration (2026-10-09).

Operator, 2026-10-09 ~21:05 ET: "how many of the 480 crons have moved and validated, how long for
rest to move, do we have this as a running documentation somewhere". This report answers it from
evidence only. It joins:

  * config/lane_registry.json   scheduler kind/state, recommendation / rationalization target
                                pipeline, dispatch block (mode, wave)
  * the live crontab            ``crontab -l`` (optional; --crontab FILE, or --no-crontab)
  * the n8n coordination ledger ``runs`` (dry_run / live RUN_DONE per lane, last success)
  * cutover receipts            data/runtime/n8n_cutover/*-cutover.json (CutoverReceipt@v1)

and classifies every scheduled lane (and every live crontab line) into ONE stage:

  RETIRED            registry state RETIRED
  KEEP_ON_CRON       stays on cron/systemd (broker/order/secret/daemon); watched, not moving
  ON_CRON_UNPLANNED  on cron with no recommendation (or a crontab line no registry row declares)
  R0_PENDING         recommended for elimination, still scheduled
  MERGE_PENDING      to be merged into a target (MERGE_INTO:<target>)
  PIPELINE_PENDING   to become a stage of a pipeline (PIPELINE:Pxx)
  STANDALONE_PENDING to move as its own dispatcher lane (MIGRATE_N8N / EVENT_DRIVEN_CANDIDATE)
  DISPATCH_DRY_RUN   dispatch block mode dry_run, or dry_run runs in the ledger
  LIVE_WITH_CRON     dispatch block mode live / live ledger runs while the cron line still exists
  CUT_OVER           scheduler.kind is n8n/dispatcher and no live cron line remains
  VALIDATED          CUT_OVER + >= validated_min_live_fires natural live RUN_DONE after the cutover

ETA is a conservative, explicit model (config/cron_migration_tracker.json): waves run one after
another; each wave = build days + dry-run (>= 1 natural fire of its slowest lane) + live-with-cron
(>= 1 market day, >= 3 for scalp-class lanes) + cutover + validation (N natural live fires).

Read-only. Never edits the crontab, the registry or the ledger (sqlite opened ``mode=ro``).
  python3 scripts/report_cron_migration_tracker.py                 # print summary
  python3 scripts/report_cron_migration_tracker.py --write         # + markdown + JSON receipt
  python3 scripts/report_cron_migration_tracker.py --check         # exit 1 when the committed doc
                                                                   # was rendered from another registry
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "scripts"))

from lib import lane_registry as _lr  # noqa: E402
from lib.cio_market_session import nyse_holidays  # noqa: E402

SCHEMA = "CronMigrationTracker@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
NO_CONSUMER_REASON = ("read-only report; its consumer is the operator (docs/implementation/n8n-maturity/"
                      "MIGRATION_TRACKER.md). It will be scheduled by the n8n digest scheduler, never cron.")

ET = ZoneInfo("America/New_York")
CONFIG_PATH = PROJ / "config" / "cron_migration_tracker.json"
DOC_REL = Path("docs/implementation/n8n-maturity/MIGRATION_TRACKER.md")
RECEIPT_REL = Path("data/runtime/cron_migration_tracker/cron_migration_tracker_last.json")
CUTOVER_REL = Path("data/runtime/n8n_cutover")
LEDGER_REL = Path("data/governance/n8n_coordination_ledger.sqlite")

STAGES = ("ON_CRON_UNPLANNED", "KEEP_ON_CRON", "R0_PENDING", "RETIRED", "MERGE_PENDING",
          "PIPELINE_PENDING", "STANDALONE_PENDING", "DISPATCH_DRY_RUN", "LIVE_WITH_CRON",
          "CUT_OVER", "VALIDATED")
#: Stages that still need migration work, in ladder order (index = how far along).
LADDER = {"ON_CRON_UNPLANNED": 0, "R0_PENDING": 0, "MERGE_PENDING": 0, "PIPELINE_PENDING": 0,
          "STANDALONE_PENDING": 0, "DISPATCH_DRY_RUN": 1, "LIVE_WITH_CRON": 2, "CUT_OVER": 3}
DONE_STAGES = ("VALIDATED", "RETIRED", "KEEP_ON_CRON")
_PIPE_RE = re.compile(r"^(?:PIPELINE|MERGE_INTO):(P\d{2})$")
_DOC_SHA_RE = re.compile(r"registry sha256 `([0-9a-f]{64})`")


# ---------------------------------------------------------------- inputs
def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("validated_min_live_fires", "dry_run_min_natural_fires", "live_with_cron_market_days",
                "scalp_class_live_with_cron_market_days", "cutover_days", "fire_wait_cap_days", "waves",
                "dispatcher_kinds", "scheduled_kinds", "in_scope_states"):
        if key not in cfg:
            raise KeyError(f"{path}: {key} missing")
    return cfg


def read_crontab(path: Optional[str], disabled: bool) -> Optional[str]:
    if disabled:
        return None
    if path:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        cp = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


def ledger_runs(path: Path, cfg: dict[str, Any]) -> Optional[dict[str, dict[str, Any]]]:
    """Per lane: natural dry_run/live RUN_DONE timestamps. None when the ledger is unreadable."""
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    prefix = str(cfg.get("natural_requested_by_prefix") or "")
    excl = set(cfg.get("natural_requested_by_exclude") or [])
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = con.execute("SELECT lane_id, mode, state, requested_by, finished_at FROM runs "
                           "WHERE finished_at IS NOT NULL").fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    for lane, mode, state, req, fin in rows:
        d = out.setdefault(str(lane), {"dry_run": [], "live": [], "failed": 0, "other": 0})
        natural = str(req or "").startswith(prefix) and str(req or "") not in excl
        if state == "RUN_DONE" and natural and mode in ("dry_run", "live"):
            d[mode].append(str(fin))
        elif state in ("RUN_FAILED", "RUN_TIMEOUT"):
            d["failed"] += 1
        else:
            d["other"] += 1
    for d in out.values():
        d["dry_run"].sort()
        d["live"].sort()
    return out


def cutover_receipts(folder: Path) -> dict[str, dict[str, Any]]:
    """Latest applied cutover/rollback per lane, from CutoverReceipt@v1 files and pre-cutover backups."""
    out: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return out
    # *_last.json mirrors the newest action; it is read last so it wins a same-second tie
    # (cutover -> rollback -> re-cut inside one second, 2026-10-09 n8n-pilot-dispatch).
    for p in sorted(folder.glob("*.json"), key=lambda x: (x.name.endswith("_last.json"), x.name)):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(d, dict) or d.get("schema") != "CutoverReceipt@v1" or not d.get("applied"):
            continue
        lane, at = str(d.get("lane_id") or ""), str(d.get("at") or "")
        if lane and at and (lane not in out or at >= out[lane]["at"]):
            out[lane] = {"at": at, "action": str(d.get("action") or ""), "source": p.name, "kind": "receipt"}
    # A cutover whose receipt was not written still leaves its pre-cutover crontab backup.
    bre = re.compile(r"^crontab-(\d{8}T\d{6}Z)-pre-cutover-lane-(.+)\.txt$")
    for p in sorted(folder.glob("crontab-*-pre-cutover-lane-*.txt")):
        m = bre.match(p.name)
        if not m or m.group(2) in out:
            continue
        at = _dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc).isoformat()
        out[m.group(2)] = {"at": at, "action": "cutover", "source": p.name, "kind": "backup_only"}
    return out


# ---------------------------------------------------------------- classification
def _ts(v: Any) -> Optional[_dt.datetime]:
    try:
        t = _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def recommendation(row: dict[str, Any]) -> str:
    return str(row.get("recommendation") or (row.get("rationalization") or {}).get("recommendation") or "")


def target_of(rec: str) -> str:
    return rec.split(":", 1)[1] if ":" in rec else ""


def lane_markers(row: dict[str, Any]) -> list[str]:
    s = row.get("scheduler") or {}
    out = []
    if s.get("match"):
        out.append(str(s["match"]))
    expr = str(s.get("expression") or "")
    if s.get("kind") == "cron" and expr and not _lr._BARE_CRON_SCHEDULE.match(expr):
        out.append(expr)
    return [m for m in out if m.strip()]


def is_scalp_class(row: dict[str, Any], cfg: dict[str, Any]) -> bool:
    ident = " ".join([str(row.get("lane_id") or "")] + lane_markers(row)).lower()
    return any(str(t).lower() in ident for t in cfg.get("scalp_class_tokens") or [])


def classify(row: dict[str, Any], *, cfg: dict[str, Any], live_lines: Optional[list[str]],
             runs: Optional[dict[str, dict[str, Any]]], cuts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lid = str(row.get("lane_id") or "")
    sched = row.get("scheduler") or {}
    kind, state = str(sched.get("kind") or ""), str(row.get("state") or "")
    rec = recommendation(row)
    disp = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else None
    lr = (runs or {}).get(lid) or {"dry_run": [], "live": [], "failed": 0, "other": 0}
    cut = cuts.get(lid)
    markers = lane_markers(row)
    on_cron: Optional[bool] = None
    if live_lines is not None:
        on_cron = bool(markers) and any(m in ln for ln in live_lines for m in markers)
    flags: list[str] = []
    stage = ""
    cut_at = _ts(cut["at"]) if cut and cut.get("action") == "cutover" else None
    live_after = [t for t in lr["live"] if cut_at is None or (_ts(t) or cut_at) >= cut_at]

    if state == "RETIRED":
        stage = "RETIRED"
    elif kind in cfg["dispatcher_kinds"]:
        if on_cron:
            stage = "LIVE_WITH_CRON"
            flags.append("double_scheduled:cron_line_still_active")
        elif len(live_after) >= int(cfg["validated_min_live_fires"]):
            stage = "VALIDATED"
        else:
            stage = "CUT_OVER"
        if cut is None:
            flags.append("no_cutover_receipt")
        elif cut.get("kind") == "backup_only":
            flags.append("cutover_receipt_missing(backup_only)")
        elif cut.get("action") != "cutover":
            flags.append(f"last_receipt_{cut.get('action')}")
    elif disp and str(disp.get("mode") or "") == "live":
        stage = "LIVE_WITH_CRON"
    elif disp and str(disp.get("mode") or "") == "dry_run":
        stage = "DISPATCH_DRY_RUN"
    elif lr["live"]:
        stage = "LIVE_WITH_CRON"
        flags.append("ledger_live_runs_without_dispatch_block")
    elif lr["dry_run"]:
        stage = "DISPATCH_DRY_RUN"
        flags.append("ledger_dry_runs_without_dispatch_block")
    elif rec == "KEEP_ON_CRON":
        stage = "KEEP_ON_CRON"
    elif rec == "R0_ELIMINATE":
        stage = "R0_PENDING"
    elif rec.startswith("MERGE_INTO:"):
        stage = "MERGE_PENDING"
    elif rec.startswith("PIPELINE:"):
        stage = "PIPELINE_PENDING"
    elif rec in ("MIGRATE_N8N", "EVENT_DRIVEN_CANDIDATE"):
        stage = "STANDALONE_PENDING"
    else:
        stage = "ON_CRON_UNPLANNED"
    if state == "PAUSED":
        flags.append("paused")
    if stage in ("KEEP_ON_CRON",) and ((row.get("output_signal") or {}).get("kind") or "none") == "none":
        flags.append("not_watched:no_output_signal")
    if kind == "cron" and state == "ACTIVE" and on_cron is False and stage not in ("CUT_OVER", "VALIDATED"):
        flags.append("cron_line_not_found")
    last_live = lr["live"][-1] if lr["live"] else None
    return {
        "lane_id": lid, "kind": kind, "state": state, "stage": stage, "recommendation": rec or None,
        "target": target_of(rec) or None, "dispatch_mode": (disp or {}).get("mode"),
        "dispatch_wave": (disp or {}).get("wave"), "dry_run_fires": len(lr["dry_run"]),
        "live_fires": len(lr["live"]), "live_fires_after_cutover": len(live_after) if cut_at else None,
        "failed_runs": lr["failed"], "last_live_success": last_live,
        "cutover_at": cut["at"] if cut else None, "cutover_evidence": (cut or {}).get("source"),
        "cadence_hours": float(row.get("expected_cadence_hours") or 0) or None,
        "scalp_class": is_scalp_class(row, cfg), "on_cron": on_cron, "flags": flags,
    }


def assign_wave(row: dict[str, Any], lane: dict[str, Any], waves: list[dict[str, Any]]) -> str:
    if lane.get("dispatch_wave"):
        return str(lane["dispatch_wave"])
    rec = lane.get("recommendation") or ""
    m = _PIPE_RE.match(rec)
    pipe = m.group(1) if m else None
    for w in waves:
        sel = w.get("select") or {}
        if lane["lane_id"] in (sel.get("lane_ids") or []) or lane["stage"] in (sel.get("stages") or []):
            return w["id"]
    for w in waves:
        sel = w.get("select") or {}
        if rec and rec in (sel.get("recommendations") or []):
            return w["id"]
        if pipe and pipe in (sel.get("pipelines") or []):
            return w["id"]
        if sel.get("merge_other") and rec.startswith("MERGE_INTO:") and not pipe:
            return w["id"]
    for w in waves:
        if (w.get("select") or {}).get("fallback"):
            return w["id"]
    return "UNPLANNED"


# ---------------------------------------------------------------- ETA
def add_market_days(d: _dt.date, n: int) -> _dt.date:
    """The date on which the n-th market day after ``d`` has completed (d itself not counted)."""
    got = 0
    cur = d
    while got < n:
        cur += _dt.timedelta(days=1)
        if cur.weekday() < 5 and cur not in nyse_holidays(cur.year):
            got += 1
    return cur


def _fire_wait_days(cadence_h: Optional[float], fires: int, cap_days: float) -> int:
    hours = (cadence_h or 24.0) * max(fires, 1)
    return max(1, math.ceil(min(hours / 24.0, cap_days * max(fires, 1))))


def wave_eta(wave: dict[str, Any], lanes: list[dict[str, Any]], start: _dt.date,
             cfg: dict[str, Any]) -> dict[str, Any]:
    """Conservative finish date for a wave: its slowest remaining lane through the whole ladder."""
    ladder = wave.get("ladder") or "dispatch"
    todo = [ln for ln in lanes if ln["stage"] not in DONE_STAGES]
    cap = float(cfg["fire_wait_cap_days"])
    if ladder in ("keep", "unplanned", "done"):
        note = {"keep": "stays on cron/systemd (watched)", "done": "nothing to move",
                "unplanned": "not scheduled: needs a rationalization decision before it has an ETA"}[ladder]
        return {"start": None, "end": None, "remaining": len(todo), "steps": [], "note": note}
    if not todo:
        return {"start": start.isoformat(), "cutover": start.isoformat(), "end": start.isoformat(),
                "remaining": 0, "steps": [], "note": "complete"}
    steps: list[str] = []
    d = start + _dt.timedelta(days=int(wave.get("build_days") or 0))
    steps.append(f"build {int(wave.get('build_days') or 0)}d")
    if ladder == "retire":
        d += _dt.timedelta(days=int(cfg["cutover_days"]))
        steps.append(f"retire under one cron grant {cfg['cutover_days']}d")
        return {"start": start.isoformat(), "cutover": d.isoformat(), "end": d.isoformat(),
                "remaining": len(todo), "steps": steps, "note": ""}
    least = min(LADDER.get(ln["stage"], 0) for ln in todo)
    slow = max((ln.get("cadence_hours") or 24.0) for ln in todo)
    scalp = any(ln.get("scalp_class") for ln in todo)
    if least <= 0:
        n = _fire_wait_days(slow, int(cfg["dry_run_min_natural_fires"]), cap)
        d += _dt.timedelta(days=n)
        steps.append(f"dry_run >= {cfg['dry_run_min_natural_fires']} natural fire {n}d")
    if least <= 1:
        md = int(cfg["scalp_class_live_with_cron_market_days"] if scalp else cfg["live_with_cron_market_days"])
        d2 = add_market_days(d, md)
        d2 = max(d2, d + _dt.timedelta(days=_fire_wait_days(slow, 1, cap)))
        steps.append(f"live-with-cron >= {md} market day(s) {(d2 - d).days}d")
        d = d2
    if least <= 2:
        d += _dt.timedelta(days=int(cfg["cutover_days"]))
        steps.append(f"cutover {cfg['cutover_days']}d")
    cut_end = d
    n = _fire_wait_days(slow, int(cfg["validated_min_live_fires"]), cap)
    d += _dt.timedelta(days=n)
    steps.append(f"validate {cfg['validated_min_live_fires']} natural live fires {n}d")
    return {"start": start.isoformat(), "cutover": cut_end.isoformat(), "end": d.isoformat(),
            "remaining": len(todo), "steps": steps,
            "note": f"slowest cadence {slow:g}h" + ("; scalp-class lane present" if scalp else "")}


# ---------------------------------------------------------------- build
def build(*, registry: dict[str, Any], cfg: dict[str, Any], crontab_text: Optional[str],
          runs: Optional[dict[str, dict[str, Any]]], cuts: dict[str, dict[str, Any]],
          now: _dt.datetime, registry_sha: str, sources: dict[str, Any]) -> dict[str, Any]:
    live_lines: Optional[list[str]] = None
    moved_lines: list[dict[str, str]] = []
    if crontab_text is not None:
        live_lines = [c["expression"] for c in _lr.discover_cron(crontab_text)]
        for c in _lr.discover_commented_cron(crontab_text):
            if c.get("retired_lane_id"):
                moved_lines.append({"lane_id": c["retired_lane_id"], "date": c.get("retired_on", "")})
    rows = registry.get("lanes") or []
    scoped, excluded = [], {"kind_none": 0, "never_scheduled": 0}
    for r in rows:
        kind = (r.get("scheduler") or {}).get("kind")
        if kind not in cfg["scheduled_kinds"]:
            excluded["kind_none"] += 1
            continue
        if r.get("state") not in cfg["in_scope_states"]:
            excluded["never_scheduled"] += 1
            continue
        scoped.append(r)
    waves = cfg["waves"]
    lanes = []
    for r in scoped:
        ln = classify(r, cfg=cfg, live_lines=live_lines, runs=runs, cuts=cuts)
        ln["wave"] = assign_wave(r, ln, waves)
        lanes.append(ln)

    # crontab lines -> lane stage (longest marker wins); undeclared lines are ON_CRON_UNPLANNED.
    line_stage: dict[str, int] = {s: 0 for s in STAGES}
    unregistered: list[str] = []
    if live_lines is not None:
        by_id = {ln["lane_id"]: ln for ln in lanes}
        marks = sorted(((m, str(r.get("lane_id"))) for r in scoped
                        if (r.get("scheduler") or {}).get("kind") != "systemd" for m in lane_markers(r)),
                       key=lambda x: -len(x[0]))
        for line in live_lines:
            hit = next((lid for m, lid in marks if m in line), None)
            if hit is None or hit not in by_id:
                line_stage["ON_CRON_UNPLANNED"] += 1
                unregistered.append(line[:160])
            else:
                line_stage[by_id[hit]["stage"]] += 1

    lane_stage = {s: 0 for s in STAGES}
    for ln in lanes:
        lane_stage[ln["stage"]] += 1
    active_sched = [ln for ln in lanes if ln["state"] != "RETIRED"]
    moved = [ln for ln in lanes if ln["stage"] in ("CUT_OVER", "VALIDATED")]
    validated = [ln for ln in lanes if ln["stage"] == "VALIDATED"]
    to_move = [ln for ln in lanes if ln["stage"] not in DONE_STAGES and ln["stage"] not in ("CUT_OVER",)]

    # ETA
    today = now.astimezone(ET).date()
    cursor = today
    wave_rows = []
    for w in waves:
        members = [ln for ln in lanes if ln["wave"] == w["id"]]
        eta = wave_eta(w, members, cursor, cfg)
        if eta.get("cutover") and cfg.get("waves_sequential", True) and eta["remaining"]:
            cursor = _dt.date.fromisoformat(eta["cutover"])
        elif w.get("ladder") == "none" and cfg.get("waves_sequential", True):
            cursor = cursor + _dt.timedelta(days=int(w.get("build_days") or 0))
            eta = {"start": today.isoformat(), "cutover": cursor.isoformat(), "end": cursor.isoformat(),
                   "remaining": 0,
                   "steps": [f"build {w.get('build_days')}d"], "note": "enabler: no lane moves"}
        counts = {s: sum(1 for ln in members if ln["stage"] == s) for s in STAGES}
        wave_rows.append({"id": w["id"], "title": w["title"], "source": w.get("source"),
                          "lanes": len(members), "stages": {k: v for k, v in counts.items() if v},
                          "eta": eta})
    for extra in sorted({ln["wave"] for ln in lanes} - {w["id"] for w in waves}):
        members = [ln for ln in lanes if ln["wave"] == extra]
        wave_rows.append({"id": extra, "title": "(dispatch.wave not in the plan)", "source": "registry",
                          "lanes": len(members), "eta": {"note": "unplanned wave id"},
                          "stages": {s: sum(1 for ln in members if ln["stage"] == s) for s in STAGES
                                     if any(ln["stage"] == s for ln in members)}})
    final = max((w["eta"].get("end") for w in wave_rows if w["eta"].get("end")), default=None)

    summary = {
        "registry_rows": len(rows), "lanes_in_scope": len(lanes), "excluded": excluded,
        "scheduled_lanes_not_retired": len(active_sched),
        "live_cron_lines": None if live_lines is None else len(live_lines),
        "cron_lines_moved_to_n8n": len(moved_lines),
        "moved_lanes": len(moved), "validated_lanes": len(validated),
        "lanes_still_to_move": len(to_move),
        "lanes_by_stage": lane_stage, "cron_lines_by_stage": None if live_lines is None else line_stage,
        "unregistered_cron_lines": None if live_lines is None else len(unregistered),
        "by_kind": {k: sum(1 for ln in lanes if ln["kind"] == k) for k in sorted({ln["kind"] for ln in lanes})},
        "eta_all_waves_done": final,
    }
    return {
        "schema": SCHEMA, "authority": AUTHORITY, "generated_at": now.isoformat(),
        "registry_sha256": registry_sha, "sources": sources,
        "assumptions": assumptions(cfg),
        "summary": summary, "waves": wave_rows,
        "lanes": sorted(lanes, key=lambda x: ([w["id"] for w in waves].index(x["wave"])
                                             if x["wave"] in [w["id"] for w in waves] else 99,
                                             STAGES.index(x["stage"]), x["lane_id"])),
        "moved_cron_lines": moved_lines, "unregistered_cron_lines_sample": unregistered[:25],
    }


def assumptions(cfg: dict[str, Any]) -> list[str]:
    return [
        f"VALIDATED = cut over (registry kind in {cfg['dispatcher_kinds']}, no live cron line) and >= "
        f"{cfg['validated_min_live_fires']} natural live RUN_DONE in the ledger after the cutover time.",
        f"Natural fire = ledger runs.requested_by starts with '{cfg.get('natural_requested_by_prefix')}' "
        f"(manual/smoke requesters {cfg.get('natural_requested_by_exclude')} excluded).",
        "Cutover time = latest applied CutoverReceipt@v1; when only the pre-cutover crontab backup exists "
        "its timestamp is used and the lane is flagged.",
        "Waves run strictly one after another: a wave starts building only after the previous wave's "
        "cutover (validation of the previous wave overlaps the next build). A wave is cut over / validated "
        "only when its slowest remaining lane is; build durations are the roadmap's upper bounds.",
        f"Per-wave ladder: build days + dry_run >= {cfg['dry_run_min_natural_fires']} natural fire of the "
        f"slowest lane + live-with-cron >= {cfg['live_with_cron_market_days']} NYSE market day "
        f"(>= {cfg['scalp_class_live_with_cron_market_days']} for scalp-class lanes) + cutover "
        f"{cfg['cutover_days']}d + {cfg['validated_min_live_fires']} natural live fires; one fire waits "
        f"at most {cfg['fire_wait_cap_days']}d (weekly lanes); a lane slower than weekly is validated by its "
        "own next fire after the wave and is not modelled.",
        "Grants, operator approvals and AGENTS rule changes (R1 for LLM/ingest lanes, R2 for senders) "
        "are assumed same-day; any delay adds directly to the ETA.",
        "KEEP_ON_CRON lanes do not move (they are watched); UNPLANNED lanes have no ETA until they get a "
        "recommendation. Pipeline/merge lanes count as moved only when their own row is cut over or retired.",
    ]


# ---------------------------------------------------------------- render
def _md_cell(v: Any) -> str:
    if v is None or v == "" or v == []:
        return "-"
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_markdown(rep: dict[str, Any]) -> str:
    s = rep["summary"]
    ls = s["lanes_by_stage"]
    cl = s["cron_lines_by_stage"] or {}
    out: list[str] = []
    out.append("<!-- GENERATED by scripts/report_cron_migration_tracker.py; do not hand-edit. "
               "Regenerate: python3 scripts/report_cron_migration_tracker.py --write -->")
    out.append("# Cron to n8n migration tracker")
    out.append("")
    out.append(f"**Generated:** {rep['generated_at']} · registry sha256 `{rep['registry_sha256']}` · "
               f"schema `{rep['schema']}` · authority {rep['authority']}")
    out.append("")
    src = rep["sources"]
    out.append("**Inputs (read-only):** " + "; ".join(f"{k}: {_md_cell(v)}" for k, v in src.items()))
    out.append("")
    out.append("## Headline")
    out.append("")
    lines = s["live_cron_lines"]
    out.append(f"- **Moved to n8n: {s['moved_lanes']} lanes; validated: {s['validated_lanes']}.** "
               f"Crontab lines retired by n8n cutover: {s['cron_lines_moved_to_n8n']}.")
    out.append(f"- Scheduled lanes in the registry (not retired): {s['scheduled_lanes_not_retired']} "
               f"(by kind, incl. retired: {', '.join(f'{k} {v}' for k, v in s['by_kind'].items())}). "
               f"Live crontab lines now: {'-' if lines is None else lines}"
               + ("" if s["unregistered_cron_lines"] is None
                  else f" ({s['unregistered_cron_lines']} not declared by any registry row)") + ".")
    out.append(f"- Still to move: **{s['lanes_still_to_move']} lanes**; staying on cron/systemd (watched): "
               f"{ls['KEEP_ON_CRON']}; retired: {ls['RETIRED']}; no plan yet: {ls['ON_CRON_UNPLANNED']}.")
    out.append(f"- Conservative ETA for every planned wave: **{s['eta_all_waves_done'] or 'n/a'}** "
               "(see ETA; sequential waves, upper-bound durations).")
    out.append("")
    out.append("## Summary by stage")
    out.append("")
    out.append("| Stage | Lanes | Live cron lines | Meaning |")
    out.append("|---|---:|---:|---|")
    meaning = {
        "ON_CRON_UNPLANNED": "scheduled, no recommendation (or line not in the registry)",
        "KEEP_ON_CRON": "stays on cron/systemd; n8n heartbeat watches it",
        "R0_PENDING": "to be eliminated; still scheduled",
        "RETIRED": "registry state RETIRED",
        "MERGE_PENDING": "to merge into a target pipeline/lane",
        "PIPELINE_PENDING": "to become a pipeline stage (Pxx)",
        "STANDALONE_PENDING": "to move as its own dispatcher lane (MIGRATE_N8N / event)",
        "DISPATCH_DRY_RUN": "dispatcher runs it dry_run beside cron",
        "LIVE_WITH_CRON": "dispatcher runs it live; cron line still present",
        "CUT_OVER": "cron line retired; n8n schedules it",
        "VALIDATED": "cut over + enough natural live fires with receipts",
    }
    for st in STAGES:
        out.append(f"| {st} | {ls[st]} | {_md_cell(cl.get(st)) if cl else '-'} | {meaning[st]} |")
    out.append(f"| **total** | **{s['lanes_in_scope']}** | **{_md_cell(lines)}** | excluded: "
               f"{s['excluded']['kind_none']} kind none, {s['excluded']['never_scheduled']} never scheduled |")
    out.append("")
    out.append("## Waves")
    out.append("")
    out.append("| Wave | Scope | Lanes | Stages | Remaining | Start | Cut over by | Validated by | Ladder |")
    out.append("|---|---|---:|---|---:|---|---|---|---|")
    for w in rep["waves"]:
        e = w["eta"]
        st = ", ".join(f"{k} {v}" for k, v in w["stages"].items())
        ladder = "; ".join(e.get("steps") or []) + ((" — " + e["note"]) if e.get("note") else "")
        out.append(f"| {w['id']} | {_md_cell(w['title'])} | {w['lanes']} | {_md_cell(st)} | "
                   f"{_md_cell(e.get('remaining'))} | {_md_cell(e.get('start'))} | {_md_cell(e.get('cutover'))} | "
                   f"{_md_cell(e.get('end'))} | "
                   f"{_md_cell(ladder)} |")
    out.append("")
    out.append("## ETA")
    out.append("")
    out.append(f"All planned waves validated by **{s['eta_all_waves_done'] or 'n/a'}** under these assumptions:")
    out.append("")
    for a in rep["assumptions"]:
        out.append(f"- {a}")
    out.append("")
    out.append("## Lanes")
    out.append("")
    out.append("| Lane | Kind | State | Stage | Wave | Target | Dispatch | Dry/live fires | Last live success "
               "| Cutover | Flags |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for ln in rep["lanes"]:
        fires = f"{ln['dry_run_fires']}/{ln['live_fires']}"
        out.append(f"| `{ln['lane_id']}` | {ln['kind']} | {ln['state']} | {ln['stage']} | {ln['wave']} | "
                   f"{_md_cell(ln['target'])} | {_md_cell(ln['dispatch_mode'])} | {fires} | "
                   f"{_md_cell(ln['last_live_success'])} | {_md_cell(ln['cutover_at'])} | {_md_cell(ln['flags'])} |")
    if rep.get("unregistered_cron_lines_sample"):
        out.append("")
        out.append("## Crontab lines no registry row declares (sample)")
        out.append("")
        for line in rep["unregistered_cron_lines_sample"]:
            out.append(f"- `{line.replace('`', '')}`")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- main
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_doc(doc: Path, registry_path: Path) -> tuple[bool, str]:
    if not doc.is_file():
        return False, f"{doc} missing"
    m = _DOC_SHA_RE.search(doc.read_text(encoding="utf-8"))
    if not m:
        return False, f"{doc}: no registry sha header"
    cur = _sha(registry_path)
    if m.group(1) != cur:
        return False, f"{doc} rendered from registry {m.group(1)[:12]}, current {cur[:12]}: regenerate"
    return True, "tracker current with the registry"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--registry", default=str(PROJ / "config" / "lane_registry.json"))
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT")
                    or str(Path.home() / "trade-ai-releases" / "persistent-state"))
    ap.add_argument("--crontab", help="read crontab text from FILE instead of `crontab -l`")
    ap.add_argument("--no-crontab", action="store_true", help="do not read the crontab (CI)")
    ap.add_argument("--write", action="store_true", help="write the markdown doc(s) and the JSON receipt")
    ap.add_argument("--doc", action="append", help=f"markdown output path (default {DOC_REL}); repeatable")
    ap.add_argument("--receipt", help=f"JSON receipt path (default <state-root>/{RECEIPT_REL})")
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed doc is stale vs the registry")
    ap.add_argument("--json", action="store_true", help="print the full JSON report")
    ap.add_argument("--now", help="ISO timestamp (tests)")
    a = ap.parse_args(list(argv) if argv is not None else None)

    reg_path = Path(a.registry)
    if a.check:
        ok, msg = check_doc(PROJ / DOC_REL, reg_path)
        print(msg)
        return 0 if ok else 1
    cfg = load_config(Path(a.config))
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    root = Path(a.state_root)
    now = _ts(a.now) if a.now else _dt.datetime.now(_dt.timezone.utc)
    assert now is not None
    ctext = read_crontab(a.crontab, a.no_crontab)
    ledger = root / LEDGER_REL
    runs = ledger_runs(ledger, cfg)
    cuts = cutover_receipts(root / CUTOVER_REL)
    sources = {
        "registry": str(reg_path.relative_to(PROJ)) if reg_path.is_relative_to(PROJ) else str(reg_path),
        "crontab": ("file " + a.crontab) if a.crontab else ("not read" if ctext is None else "crontab -l"),
        "ledger": "unreadable" if runs is None else f"{LEDGER_REL} ({len(runs)} lanes with runs)",
        "cutover_evidence": f"{CUTOVER_REL} ({len(cuts)} lanes)",
        "config": "config/cron_migration_tracker.json",
    }
    rep = build(registry=registry, cfg=cfg, crontab_text=ctext, runs=runs, cuts=cuts, now=now,
                registry_sha=_sha(reg_path), sources=sources)
    if a.write:
        md = render_markdown(rep)
        for d in a.doc or [str(PROJ / DOC_REL)]:
            _atomic_write(Path(d), md)
        _atomic_write(Path(a.receipt) if a.receipt else root / RECEIPT_REL,
                      json.dumps(rep, indent=1, sort_keys=False) + "\n")
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        s = rep["summary"]
        print(json.dumps({k: s[k] for k in ("lanes_in_scope", "scheduled_lanes_not_retired", "live_cron_lines",
                                            "moved_lanes", "validated_lanes", "cron_lines_moved_to_n8n",
                                            "lanes_still_to_move", "lanes_by_stage", "cron_lines_by_stage",
                                            "eta_all_waves_done")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
