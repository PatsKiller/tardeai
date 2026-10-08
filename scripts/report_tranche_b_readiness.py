#!/usr/bin/env python3
"""report_tranche_b_readiness.py — are the tranche B pipeline stages ready to cut over?

Cron tranche B (2026-10-07): eight manifest stages were installed as `--dry-run` cron lines next to
the lines they absorb. Cutover (flip the stage to `--apply`, comment the absorbed lines) is a
per-stage decision. This report answers it from EXISTING evidence only — it probes nothing and
runs nothing:

  (a) is every absorbed cron line still present, verbatim, in the crontab;
  (b) did every step produce in the last 7 days (the declared lane's output_signal when a lane
      covers the line, else the step's own log: mtime, dated lines in 7 d, last rc if logged);
  (c) each step's p95 — the measured value when the design verified it, else the design's PAM
      upper bound (cited as such);
  (d) Σ p95 against the stage window from the manifest;
  (e) the steps the design left NOT VERIFIED.

Verdict per stage: GO (every step fresh, Σ p95 fits), GO_WITH_NOTES (fresh, but the p95 sum
overflows only through unverified upper bounds while Σ median fits), NO_GO (a line is missing,
a step has no receipt in 7 d, or the median sum does not fit) — the step is named.

    python3 scripts/report_tranche_b_readiness.py --dry-run        # table only, writes nothing
    python3 scripts/report_tranche_b_readiness.py --write          # + data/runtime/tranche_b_readiness_last.json

AUTHORITY: READ_ONLY_ADVISORY. No crontab, systemd, DB or send.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.lane_registry import load_registry, observe_signal, state_root  # noqa: E402

SCHEMA = "TrancheBReadiness@v1"
NO_CONSUMER_REASON = (
    "Cron tranche B cutover readiness receipt (2026-10-08). Read by the operator and by the per-stage "
    "scripts/pipelines/cutover/cutover_*.sh dry-runs before a cutover; no scheduled lane consumes it yet — "
    "it is produced on demand until the last stage is cut over, then retired with the dry-run lines."
)
AUTHORITY = "READ_ONLY_ADVISORY"
RECEIPT_REL = "data/runtime/tranche_b_readiness_last.json"
FRESH_DAYS = 7
DATE_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
RC_RE = re.compile(r"\brc=(\d+)\b")
REDIRECT_RE = re.compile(r">>\s*(logs/[\w./-]+\.log)")
# Wrapper scripts that redirect inside themselves (the cron line carries no `>>`): the wrapper's own LOG default.
KNOWN_WRAPPER_LOGS = {
    "run_scheduled_strategy_audits.sh": "logs/strategy_audits.log",          # LOG="${LOG:-$PROJ/logs/strategy_audits.log}"
    "run_scheduled_atp2_research_cycle.sh": "logs/atp2_research_cycle.log",  # LOG="$PROJ/logs/atp2_research_cycle.log"
    "run_scheduled_stale_proposal_sweeper.sh": "logs/stale_proposal_sweeper.log",
}

# pipeline -> (manifest file, runner script, extra runner args)
PIPELINES: dict[str, tuple[str, str, str]] = {
    "after_close": ("config/pipelines/after_close.json", "run_after_close_pipeline.sh", ""),
    "premarket": ("config/pipelines/premarket.json", "run_premarket_data_pipeline.sh", ""),
    "hermes_learning": ("config/pipelines/hermes_learning.json", "run_hermes_pipeline.sh", ""),
    "hermes_overnight": ("config/pipelines/hermes_overnight.json", "run_hermes_pipeline.sh",
                         "--manifest config/pipelines/hermes_overnight.json"),
}


def crontab_text(cmd: Optional[str] = None, file: Optional[Path] = None) -> str:
    if file is not None:
        return file.read_text(encoding="utf-8")
    cmd = cmd or os.environ.get("CRONTAB_CMD", "crontab")
    proc = subprocess.run([cmd, "-l"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd} -l failed: {proc.stderr.strip()[:120]}")
    return proc.stdout


def active_lines(text: str) -> set[str]:
    return {ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")}


def window_seconds(window: str) -> Optional[int]:
    m = re.match(r"^(\d\d):(\d\d)-(\d\d):(\d\d)$", str(window or ""))
    if not m:
        return None
    a = int(m.group(1)) * 60 + int(m.group(2))
    b = int(m.group(3)) * 60 + int(m.group(4))
    if b < a:
        b += 24 * 60
    return (b - a) * 60


def stage_line_present(text: str, runner: str, extra: str, stage: str) -> dict[str, Any]:
    pat = re.compile(r"scripts/pipelines/" + re.escape(runner) + r"\s+" + (re.escape(extra) + r"\s+" if extra else "")
                     + r"--stage\s+" + re.escape(stage) + r"\s+--(dry-run|apply)\b")
    hits = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#") and pat.search(ln)]
    mode = None
    if hits:
        mode = "apply" if "--apply" in hits[0] else "dry-run"
    return {"present": bool(hits), "count": len(hits), "mode": mode}


def lane_for_line(reg: dict[str, Any], line: str) -> Optional[dict[str, Any]]:
    """The declared lane whose scheduler.match sits inside this cron line, ACTIVE first."""
    hits = []
    for row in reg.get("lanes") or []:
        m = str(((row.get("scheduler") or {}).get("match")) or "")
        if m and m in line:
            hits.append(row)
    hits.sort(key=lambda r: 0 if r.get("state") == "ACTIVE" else 1)
    return hits[0] if hits else None


def infer_log(step: dict[str, Any]) -> tuple[str, str]:
    """(log path relative to the tree, how it was found). Manifest `log` first, then the command's own
    `>> logs/x.log`, then a known wrapper default; empty when nothing can be observed."""
    lg = str(step.get("log") or "")
    if lg and lg != "None":
        return lg, "manifest"
    cmd = str(step.get("command") or "")
    m = REDIRECT_RE.search(cmd)
    if m:
        return m.group(1), "command_redirect"
    for wrapper, log in KNOWN_WRAPPER_LOGS.items():
        if wrapper in cmd:
            return log, f"wrapper_default:{wrapper}"
    return "", "none"


def log_evidence(log_rel: str, *, root: Path, now: datetime, how: str = "manifest") -> dict[str, Any]:
    if not log_rel or log_rel == "None":
        return {"kind": "none", "last_output_at": None, "dated_lines_7d": None, "last_rc": None,
                "detail": "UNVERIFIABLE: no log, no lane — instrument first (design §6 step 1)"}
    p = Path(log_rel)
    if not p.is_absolute():
        p = root / log_rel
    if not p.exists():
        return {"kind": "log", "path": str(p), "last_output_at": None, "dated_lines_7d": 0, "last_rc": None, "detail": "absent"}
    ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    dated = 0
    last_rc = None
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 400_000))
            chunk = fh.read().decode("utf-8", "replace")
        cutoff = (now - timedelta(days=FRESH_DAYS)).date().isoformat()
        for ln in chunk.splitlines():
            m = DATE_RE.search(ln)
            if m and m.group(0) >= cutoff:
                dated += 1
            r = RC_RE.search(ln)
            if r:
                last_rc = int(r.group(1))
    except OSError:
        pass
    return {"kind": "log", "path": str(p), "last_output_at": ts, "dated_lines_7d": dated, "last_rc": last_rc,
            "size": p.stat().st_size, "found_by": how, "detail": "tail 400 KB scanned for dates and rc="}


def step_duration(measured: dict[str, Any]) -> dict[str, Any]:
    verified = bool(measured.get("verified"))
    if verified and measured.get("p95_s") is not None:
        return {"verified": True, "median_s": float(measured.get("median_s") or 0.0),
                "p95_s": float(measured.get("p95_s") or 0.0), "source": f"measured:{measured.get('source')}"}
    return {"verified": False, "median_s": float(measured.get("upper_bound_median_s") or 0.0),
            "p95_s": float(measured.get("upper_bound_p95_s") or 0.0),
            "source": f"upper_bound:{measured.get('bound_source') or measured.get('source')}"}


def assess_stage(pipeline: str, stage: str, spec: dict[str, Any], *, text: str, reg: dict[str, Any],
                 state: Path, now: datetime, runner: str, extra: str) -> dict[str, Any]:
    lines = active_lines(text)
    budget = window_seconds(spec.get("window"))
    steps_out: list[dict[str, Any]] = []
    sum_p95 = 0.0
    sum_med = 0.0
    unverified: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    unverifiable: list[str] = []
    absorbed_elsewhere: list[str] = []
    for st in spec.get("steps") or []:
        sid = str(st.get("id"))
        verbatim = str(st.get("cron_line_verbatim") or "").rstrip()
        present = verbatim in lines
        lane = lane_for_line(reg, verbatim)
        dur = step_duration(st.get("measured") or {})
        sum_p95 += dur["p95_s"]
        sum_med += dur["median_s"]
        if not dur["verified"]:
            unverified.append(sid)
        ev: dict[str, Any] = {}
        if lane is not None and lane.get("output_signal"):
            obs = observe_signal(lane["output_signal"], root=state)
            if obs.get("last_output_at") is not None or obs.get("readable", True):
                ev = {"kind": "lane", "lane_id": lane.get("lane_id"), "lane_state": lane.get("state"),
                      "last_output_at": obs.get("last_output_at"), "detail": obs.get("detail")}
        if not ev or (ev.get("last_output_at") is None and "db_query" in str(ev.get("detail") or "")):
            log_rel, how = infer_log(st)
            ev = log_evidence(log_rel, root=state, now=now, how=how)
        last = ev.get("last_output_at")
        fresh = bool(last) and (now - last) <= timedelta(days=FRESH_DAYS)
        if not present:
            missing.append(sid)
            if lane is not None and lane.get("state") == "RETIRED" and lane.get("superseded_by"):
                absorbed_elsewhere.append(f"{sid}->{lane['superseded_by']}")
        if ev.get("kind") == "none":
            unverifiable.append(sid)
        elif not fresh:
            stale.append(sid)
        steps_out.append({"id": sid, "cron_line_present": present, "lane_id": (lane or {}).get("lane_id"),
                          "lane_state": (lane or {}).get("state"), "superseded_by": (lane or {}).get("superseded_by"),
                          "evidence": {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in ev.items()},
                          "fresh_7d": fresh, "duration": dur})
    fits_p95 = budget is not None and sum_p95 <= budget
    fits_med = budget is not None and sum_med <= budget
    if missing or stale or unverifiable or not fits_med:
        verdict = "NO_GO"
    elif fits_p95 and not unverified:
        verdict = "GO"
    else:
        verdict = "GO_WITH_NOTES"
    reasons = []
    if missing:
        reasons.append("cron line missing: " + ", ".join(missing) + (" (absorbed elsewhere: " + ", ".join(absorbed_elsewhere) + ")" if absorbed_elsewhere else ""))
    if stale:
        reasons.append(f"no receipt in {FRESH_DAYS} d: " + ", ".join(stale))
    if unverifiable:
        reasons.append("unverifiable (no log, no lane): " + ", ".join(unverifiable))
    if budget is None:
        reasons.append("no window in manifest")
    elif not fits_med:
        reasons.append(f"sum of medians {sum_med:.0f}s > window {budget}s")
    elif not fits_p95:
        reasons.append(f"sum p95 {sum_p95:.0f}s > window {budget}s (upper bounds on {len(unverified)} unverified steps; medians {sum_med:.0f}s fit)")
    if unverified and verdict != "NO_GO":
        reasons.append("design NOT VERIFIED: " + ", ".join(unverified))
    return {"pipeline": pipeline, "stage": stage, "schedule": spec.get("proposed_schedule"), "window": spec.get("window"),
            "window_s": budget, "stage_line": stage_line_present(text, runner, extra, stage), "steps": steps_out,
            "step_count": len(steps_out), "sum_median_s": round(sum_med, 1), "sum_p95_s": round(sum_p95, 1),
            "fits_median": fits_med, "fits_p95": fits_p95, "unverified": unverified, "missing_lines": missing,
            "absorbed_elsewhere": absorbed_elsewhere, "stale_steps": stale, "unverifiable_steps": unverifiable,
            "verdict": verdict, "reasons": reasons}


def assess_all(*, text: str, reg: dict[str, Any], state: Path, now: datetime, code_root: Path = ROOT) -> list[dict[str, Any]]:
    out = []
    for pipeline, (manifest_rel, runner, extra) in PIPELINES.items():
        manifest = json.loads((code_root / manifest_rel).read_text(encoding="utf-8"))
        for stage, spec in (manifest.get("stages") or {}).items():
            out.append(assess_stage(pipeline, stage, spec, text=text, reg=reg, state=state, now=now, runner=runner, extra=extra))
    return out


def render(rows: list[dict[str, Any]]) -> str:
    lines = [f"{'stage':<36} {'verdict':<13} {'steps':>5} {'Σmed':>7} {'Σp95':>7} {'window':>7}  notes"]
    for r in rows:
        name = f"{r['pipeline']}/{r['stage']}"
        notes = "; ".join(r["reasons"])[:150]
        w = r["window_s"] if r["window_s"] is not None else "-"
        lines.append(f"{name:<36} {r['verdict']:<13} {r['step_count']:>5} {r['sum_median_s']:>7.0f} {r['sum_p95_s']:>7.0f} {str(w):>7}  {notes}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print the table, write nothing (default)")
    g.add_argument("--write", action="store_true", help=f"also write {RECEIPT_REL} under the state root")
    ap.add_argument("--crontab-file", type=Path, default=None, help="read this file instead of `crontab -l` (tests)")
    ap.add_argument("--state-root", type=Path, default=None)
    ap.add_argument("--code-root", type=Path, default=None)
    ap.add_argument("--now", default=None, help="ISO timestamp override (tests)")
    ap.add_argument("--json", action="store_true", help="print the full JSON instead of the table")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now).astimezone(timezone.utc) if args.now else datetime.now(timezone.utc)
    state = args.state_root or state_root()
    code_root = args.code_root or ROOT
    reg = load_registry(code_root / "config" / "lane_registry.json")
    text = crontab_text(file=args.crontab_file)
    rows = assess_all(text=text, reg=reg, state=state, now=now, code_root=code_root)
    doc = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "mode": "write" if args.write else "dry-run",
           "fresh_days": FRESH_DAYS, "state_root": str(state), "stages": rows,
           "summary": {v: sum(1 for r in rows if r["verdict"] == v) for v in ("GO", "GO_WITH_NOTES", "NO_GO")}}
    if args.json:
        print(json.dumps(doc, indent=1, default=str))
    else:
        print(render(rows))
        print("summary:", doc["summary"])
    if args.write:
        p = state / RECEIPT_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
        print("wrote", p, file=sys.stderr if args.json else sys.stdout)
    else:
        print("dry-run: nothing written", file=sys.stderr if args.json else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
