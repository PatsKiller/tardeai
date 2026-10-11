#!/usr/bin/env python3
"""monitor_fold_parity.py — the W1-9 monitor-fold parallel run: one read-only parity compare per day.

Operator rulings 2026-10-11 ("R1 yes, R11 yes"): the health plane's STALE_OUTPUT (registry freshness_contracts) and
NO_OUTPUT replace job-coverage-monitor (cron L389) after a parallel run of at least one trading week with matching
results; pipeline-freshness-monitor and pipeline-liveness-report fold after the same run. This script is that
compare. It reads, never writes a store:

- the detector ledger ``data/runtime/supervisor_breaches.jsonl`` (rows detected in the last ``--window-hours``);
- the monitors' own logs (the last N runs of each, N set by the run cadence so that N runs span about 24 h):
  ``logs/job_coverage_monitor.log`` (2 runs, 08:30 + 20:30), ``logs/pipeline_freshness.log`` (6 runs, every 4 h),
  ``logs/pipeline_liveness.log`` (48 runs, every 30 min);
- ``config/lane_registry.json`` from ``--root`` (which contracts exist, which lane runs each job) and
  ``scripts/job_coverage_monitor.py`` REGISTRY (its jobs, imported from this checkout; no I/O at import).

Per monitor the verdict is MATCH or MISMATCH:

- job-coverage-monitor: its STALE DB jobs == the plane's ``jcm.*`` STALE_OUTPUT contracts (both directions); every
  STALE log job has a NO_OUTPUT row on its producer lane (one direction: the plane must see what the monitor sees;
  the lane is the ACTIVE registry lane whose scheduler / exec_start names the job's ``schedule_match``, as in
  tests/test_monitor_fold_coverage_20261011.py). NOT_SCHEDULED is not compared here: the plane covers it with NO_OUTPUT after 3x cadence and
  ``check_lane_registry --state-drift`` (listed under ``not_compared``).
- pipeline-freshness-monitor: its STALE / MISSING targets == the plane's ``pfm.*`` STALE_OUTPUT contracts (both
  directions). ``hermes_canonical`` and ``rotation_summary`` have no ``pfm.*`` contract (a lane output_signal names
  them already) and are listed under ``not_compared``.
- pipeline-liveness-report: its (lane, STARVED / NO-INPUT / UNKNOWN) set == the plane's INPUT_STARVATION
  (lane, status) set (both directions).

A MISMATCH is not automatically a defect: ``trading_days`` may report up to about half a Monday later than the
monitors, never earlier, and the log windows are run-counted, not clock-aligned. Each MISMATCH is explained in the
day's parity note before the run can conclude. Exit 0 = all MATCH, 3 = a MISMATCH (a finding), 2 = an input could
not be read. With ``--out DIR`` the document is also written to ``DIR/parity-<UTC date>.json`` (DIR must not be
under ``--root``: this script never writes into the release).

    python3 scripts/monitor_fold_parity.py --root ~/trade-ai-releases/portfolio-server/CURRENT \
        --out ~/n8n-maturity-verification/packets/fold-job-coverage-monitor/parity

COVERS = ["scripts/monitor_fold_parity.py"]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "MonitorFoldParity@v1"
NO_CONSUMER_REASON = (
    "W1-9 parallel-run evidence (rulings R1/R11, 2026-10-11): run by hand or by an agent once per trading day through "
    "~/n8n-maturity-verification/packets/fold-job-coverage-monitor/run_parity.sh, which writes the documents to the "
    "packet's parity/ dir; the packet's parity_gate.py reads them before the L389 / health-tick fold. No repo caller and "
    "no schedule on purpose (cron freeze, operator 2026-10-09); it retires with the fold."
)
PROJ = Path(__file__).resolve().parents[1]

JCM_LOG = "logs/job_coverage_monitor.log"
PFM_LOG = "logs/pipeline_freshness.log"
PLR_LOG = "logs/pipeline_liveness.log"
LEDGER = "data/runtime/supervisor_breaches.jsonl"
REGISTRY = "config/lane_registry.json"

#: runs per ~24 h at each monitor's cadence (cron L389 08:30+20:30; health_tick 240 min; health_tick 30 min).
DEFAULT_RUNS = {"job-coverage-monitor": 2, "pipeline-freshness-monitor": 6, "pipeline-liveness-report": 48}
#: pipeline-freshness targets that have no pfm.* contract (a registry output_signal already names them).
PFM_NOT_CONTRACTED = ("hermes_canonical", "rotation_summary")
#: pipeline_liveness_report._MARK -> PipelineLiveness@v1 status (the detector's evidence.status).
PLR_MARKS = {"STARVED": "STARVED", "NO-INPUT": "NO_ELIGIBLE_INPUT", "UNKNOWN": "UNKNOWN", "ok": "LIVE", "quiet": "QUIET"}
PLR_FINDINGS = ("STARVED", "NO_ELIGIBLE_INPUT", "UNKNOWN")

_JCM_ROW = re.compile(r"^\s*\S+\s+\[(?P<status>[A-Z_]+)\s*\]\s+(?P<job>\S+)\s")
_PFM_ROW = re.compile(r"^\s*(?:⚠ STALE|\? MISSING|ok)\s+(?P<name>\S+)")
_PLR_ROW = re.compile(r"^(?P<mark>STARVED|NO-INPUT|UNKNOWN|ok|quiet)\s+(?P<lane>\S+)\s")


# ── log parsers (pure) ────────────────────────────────────────────────────────────────────────────────────────────
def parse_job_coverage(text: str, runs: int) -> dict[str, Any]:
    """{job: status} flagged (STALE / NOT_SCHEDULED) in any of the last ``runs`` blocks, plus the run count."""
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("Job coverage / heartbeat:"):
            blocks.append([])
        elif blocks:
            blocks[-1].append(line)
    flagged: dict[str, str] = {}
    for block in blocks[-runs:] if runs > 0 else []:
        for line in block:
            m = _JCM_ROW.match(line)
            if m and m["status"] in ("STALE", "NOT_SCHEDULED"):
                flagged.setdefault(m["job"], m["status"])
    return {"runs": min(len(blocks), max(runs, 0)), "flagged": flagged}


def parse_pipeline_freshness(text: str, runs: int) -> dict[str, Any]:
    """{target: STALE|MISSING} in any of the last ``runs`` blocks (a block starts at its ``N fresh`` summary line)."""
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("[pipeline-freshness]") and " fresh " in line:
            blocks.append([])
        elif blocks:
            blocks[-1].append(line)
    flagged: dict[str, str] = {}
    for block in blocks[-runs:] if runs > 0 else []:
        for line in block:
            s = line.strip()
            if s.startswith("⚠ STALE") or s.startswith("? MISSING"):
                m = _PFM_ROW.match(line)
                if m:
                    flagged.setdefault(m["name"], "STALE" if "STALE" in s.split()[1] else "MISSING")
    return {"runs": min(len(blocks), max(runs, 0)), "flagged": flagged}


def parse_pipeline_liveness(text: str, runs: int) -> dict[str, Any]:
    """{(lane, status)} flagged in the last ``runs`` runs. The log has no run header: each run prints one status
    line per lane, so the last ``runs`` x (number of distinct lanes) status lines are the window."""
    rows = [(m["mark"], m["lane"]) for m in (_PLR_ROW.match(ln) for ln in text.splitlines()) if m]
    lanes = {lane for _mark, lane in rows}
    window = rows[-(runs * len(lanes)):] if runs > 0 and lanes else []
    flagged = sorted({(lane, PLR_MARKS[mark]) for mark, lane in window if PLR_MARKS[mark] in PLR_FINDINGS})
    return {"runs": (len(window) // len(lanes)) if lanes else 0, "lanes": sorted(lanes), "flagged": flagged}


# ── ledger (pure over rows) ──────────────────────────────────────────────────────────────────────────────────────
def ledger_window(rows: list[dict], now: datetime, window_hours: float) -> list[dict]:
    lo = now - timedelta(hours=window_hours)
    out = []
    for r in rows:
        try:
            at = datetime.fromisoformat(str(r.get("detected_at")))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if lo <= at <= now:
            out.append(r)
    return out


def _stale_contracts(rows: list[dict], prefix: str) -> set[str]:
    return {str((r.get("evidence") or {}).get("contract"))[len(prefix):] for r in rows
            if r.get("kind") == "STALE_OUTPUT" and str((r.get("evidence") or {}).get("contract") or "").startswith(prefix)}


def job_log_lanes(jobs: list[dict], lanes: list[dict]) -> dict[str, set[str]]:
    """job -> ACTIVE lane_ids running it, for job_coverage_monitor's ("log", file) jobs. Pure."""
    out: dict[str, set[str]] = {}
    for j in jobs:
        if (j.get("signal") or ("",))[0] != "log":
            continue
        out[j["name"]] = {str(ln.get("lane_id")) for ln in lanes if ln.get("state") == "ACTIVE" and j.get("schedule_match")
                          and j["schedule_match"] in json.dumps(ln.get("scheduler")) + json.dumps(ln.get("exec_start") or "")}
    return out


# ── compares (pure) ──────────────────────────────────────────────────────────────────────────────────────────────
def compare_job_coverage(parsed: dict, rows: list[dict], *, contract_keys: set[str], log_lanes: dict[str, set[str]]) -> dict:
    flagged = parsed["flagged"]
    db_jobs = {k[len("jcm."):] for k in contract_keys if k.startswith("jcm.")}
    stale = {j for j, s in flagged.items() if s == "STALE"}
    monitor_db = stale & db_jobs
    plane_db = _stale_contracts(rows, "jcm.") & db_jobs
    no_output = {str(r.get("lane_id")) for r in rows if r.get("kind") == "NO_OUTPUT"}
    log_stale = {j for j in stale if j in log_lanes}
    log_unmatched = sorted(j for j in log_stale if not (log_lanes[j] & no_output))
    # A STALE job that is neither a jcm.* contract nor a log job: a DB check the registry has no contract for (e.g. a
    # release from before W1-9) or a job added to the monitor since. Either way the plane does not cover it.
    uncovered = sorted(stale - db_jobs - log_stale)
    doc = {"runs": parsed["runs"], "monitor_stale_db": sorted(monitor_db), "plane_stale_output": sorted(plane_db),
           "monitor_only": sorted(monitor_db - plane_db), "plane_only": sorted(plane_db - monitor_db),
           "monitor_stale_log": sorted(log_stale), "log_without_no_output": log_unmatched, "uncovered": uncovered,
           "not_compared": sorted(f"{j}:{s}" for j, s in flagged.items() if s == "NOT_SCHEDULED")}
    doc["verdict"] = ("MATCH" if parsed["runs"] and not (doc["monitor_only"] or doc["plane_only"] or log_unmatched
                                                        or uncovered) else "MISMATCH")
    if not parsed["runs"]:
        doc["note"] = "no monitor run in the log window"
    return doc


def compare_pipeline_freshness(parsed: dict, rows: list[dict], *, contract_keys: set[str]) -> dict:
    targets = {k[len("pfm."):] for k in contract_keys if k.startswith("pfm.")}
    monitor = {t for t in parsed["flagged"] if t in targets}
    plane = _stale_contracts(rows, "pfm.") & targets
    doc = {"runs": parsed["runs"], "monitor_flagged": sorted(monitor), "plane_stale_output": sorted(plane),
           "monitor_only": sorted(monitor - plane), "plane_only": sorted(plane - monitor),
           "not_compared": sorted(f"{t}:{s}" for t, s in parsed["flagged"].items() if t not in targets)}
    doc["verdict"] = "MATCH" if parsed["runs"] and not (doc["monitor_only"] or doc["plane_only"]) else "MISMATCH"
    if not parsed["runs"]:
        doc["note"] = "no monitor run in the log window"
    return doc


def compare_pipeline_liveness(parsed: dict, rows: list[dict]) -> dict:
    monitor = {f"{lane}:{st}" for lane, st in parsed["flagged"]}
    plane = {f"{str(r.get('lane_id'))[len('liveness:'):]}:{(r.get('evidence') or {}).get('status')}" for r in rows
             if r.get("kind") == "INPUT_STARVATION" and str(r.get("lane_id") or "").startswith("liveness:")}
    doc = {"runs": parsed["runs"], "monitor_flagged": sorted(monitor), "plane_input_starvation": sorted(plane),
           "monitor_only": sorted(monitor - plane), "plane_only": sorted(plane - monitor)}
    doc["verdict"] = "MATCH" if parsed["runs"] and not (doc["monitor_only"] or doc["plane_only"]) else "MISMATCH"
    if not parsed["runs"]:
        doc["note"] = "no monitor run in the log window"
    return doc


# ── I/O (read-only) ──────────────────────────────────────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _jcm_jobs() -> list[dict]:
    """job_coverage_monitor.REGISTRY (imports the module; it does no I/O at import)."""
    if str(PROJ / "scripts") not in sys.path:
        sys.path.insert(0, str(PROJ / "scripts"))
    import job_coverage_monitor as jcm  # type: ignore  # noqa: PLC0415

    return list(jcm.REGISTRY)


def run(root: Path, now: datetime, *, window_hours: float, runs: dict[str, int], jobs: list[dict]) -> dict:
    errors: list[str] = []

    def _text(rel: str) -> str:
        try:
            return (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{rel}: {type(exc).__name__}")
            return ""

    try:
        rows = ledger_window(_read_jsonl(root / LEDGER), now, window_hours)
    except OSError as exc:
        errors.append(f"{LEDGER}: {type(exc).__name__}")
        rows = []
    try:
        reg = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
        keys = {c.get("key") for c in reg.get("freshness_contracts") or [] if c.get("key")}
        log_lanes = job_log_lanes(jobs, reg.get("lanes") or [])
    except (OSError, ValueError) as exc:
        errors.append(f"{REGISTRY}: {type(exc).__name__}")
        keys, log_lanes = set(), {}
    monitors = {
        "job-coverage-monitor": compare_job_coverage(parse_job_coverage(_text(JCM_LOG), runs["job-coverage-monitor"]),
                                                     rows, contract_keys=keys, log_lanes=log_lanes),
        "pipeline-freshness-monitor": compare_pipeline_freshness(
            parse_pipeline_freshness(_text(PFM_LOG), runs["pipeline-freshness-monitor"]), rows, contract_keys=keys),
        "pipeline-liveness-report": compare_pipeline_liveness(
            parse_pipeline_liveness(_text(PLR_LOG), runs["pipeline-liveness-report"]), rows),
    }
    status = "UNREADABLE" if errors else ("MATCH" if all(m["verdict"] == "MATCH" for m in monitors.values()) else "MISMATCH")
    return {"schema": SCHEMA, "as_of": now.isoformat(), "root": str(root), "window_hours": window_hours,
            "ledger_rows_in_window": len(rows), "status": status, "errors": errors, "monitors": monitors,
            "authority": "READ_ONLY_ADVISORY"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", required=True, help="release root holding logs/, data/runtime/, config/ (read-only)")
    ap.add_argument("--window-hours", type=float, default=24.0)
    ap.add_argument("--now", help="ISO time (default: now, UTC)")
    ap.add_argument("--out", help="directory for parity-<UTC date>.json (never under --root)")
    for name, n in DEFAULT_RUNS.items():
        ap.add_argument(f"--runs-{name}", type=int, default=n, dest=f"runs_{name.replace('-', '_')}")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser().resolve()
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    runs = {name: getattr(a, f"runs_{name.replace('-', '_')}") for name in DEFAULT_RUNS}
    doc = run(root, now, window_hours=a.window_hours, runs=runs, jobs=_jcm_jobs())
    text = json.dumps(doc, indent=2, sort_keys=True)
    print(text)
    if a.out:
        out = Path(a.out).expanduser().resolve()
        if out == root or root in out.parents:
            print("REFUSED: --out is under --root (this script never writes into the release)", file=sys.stderr)
            return 2
        out.mkdir(parents=True, exist_ok=True)
        (out / f"parity-{now.astimezone(timezone.utc):%Y-%m-%d}.json").write_text(text + "\n", encoding="utf-8")
    return {"MATCH": 0, "MISMATCH": 3}.get(doc["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
