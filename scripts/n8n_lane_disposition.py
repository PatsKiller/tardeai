#!/usr/bin/env python3
"""n8n_lane_disposition.py — one authoritative per-line / per-lane disposition table (2026-10-15).

Operator, 2026-10-15: "go into the 200+ lanes, no excuses, execute now". The architecture review of 2026-10-14
(``MIGRATION_TARGET.md``) recast 524 jobs into four destinations. This tool joins, read-only:

* the live crontab (``crontab -l`` copy; ONE row per active job line, so the totals reconcile to the line count),
* ``config/lane_registry.json`` (the same substring rule as ``scripts/lib/lane_registry.find_undeclared``),
* the 2026-10-14 inventory (``inventory.csv``, 524 jobs) and its WS2 family decisions (52 families),
* a small overrides file (verified per-lane verdicts with their evidence: the retire packet's YES rows),

and writes ``LANE_DISPOSITION_<date>.csv``. Every row gets exactly one disposition:

    RETIRE        dead / duplicate / obsolete; evidence column says why (output age, duplicate-of id)
    CONSOLIDATE   folded on the host into one stage runner first (target pipeline named)
    STAY_HOST     daemons, watchdogs, broker/order/stop/protection/secret, senders, OS/other apps (§23.14, §23.23)
    MIGRATE_N8N   timer -> fabric Run Lane (leaf lane, agent workflow or event subscription; wave named)

Registry ACTIVE lanes with no crontab line (systemd timers/services, n8n, event, none) are appended as
``source=registry`` rows so the lane view is complete; they never change the crontab-line total.

Nothing here writes outside ``--out``. It never calls ``crontab -`` and never reads ``.env`` or a credential file.
Output ages are ``os.stat`` mtimes of the cron line's own ``>> log`` redirect, measured at build time.

    python3 scripts/n8n_lane_disposition.py --crontab <(crontab -l) \
        --inventory docs/implementation/n8n-maturity/data/disposition_20261015/inventory_20261014.csv \
        --families docs/implementation/n8n-maturity/data/disposition_20261015/ws2_family_decisions_20261014.csv \
        --overrides docs/implementation/n8n-maturity/data/disposition_20261015/overrides.json \
        --out docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
NO_CONSUMER_REASON = (
    "Offline report builder for docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv; the operator "
    "packets under docs/ops/packets/lane-*-20261015/ read its CSV, nothing imports this module at runtime."
)

DISPOSITIONS = ("RETIRE", "CONSOLIDATE", "STAY_HOST", "MIGRATE_N8N")
COLUMNS = (
    "row_id",
    "source",
    "line_no",
    "schedule",
    "lane_id",
    "registry_state",
    "registry_stage",
    "inventory_job",
    "inventory_bucket",
    "family_id",
    "family",
    "disposition",
    "target",
    "target_shape",
    "wave",
    "evidence",
    "output_log",
    "output_age_h",
    "signal_kind",
    "signal_age_h",
    "duplicate_of",
    "command",
)

# ── family -> disposition (WS2_family_decisions.csv `category`, read with MIGRATION_TARGET.md §2-§3) ───────────────
STAY_FAMILIES = {"F06", "F07", "F07w", "F08", "F09", "F10"}
RETIRE_FAMILIES = {"F01", "F02", "F03", "F04", "F05"}
#: consolidation family -> (target, wave). Waves: C1 = packets already built (premarket flip, B-families),
#: C2 = manifest exists, flip pending (after-close, hermes), C3 = this program's new manifest (F36 health plane),
#: C4 = same-script multi-slot families, C5 = quote/cache/digest/maintenance.
CONSOLIDATE_TARGETS = {
    "F11": ("premarket-data-pipeline (config/pipelines/premarket.json)", "C1"),
    "F12": ("after-close-pipeline (config/pipelines/after_close.json)", "C2"),
    "F13": ("hermes-learning/hermes-overnight pipelines (config/pipelines/hermes_*.json)", "C2"),
    "F14": ("B-family lanes (run_family_slot.py, packets/b-families-top5)", "C1"),
    "F15": ("quote-service workflow via CC data broker (P01)", "C5"),
    "F16": ("cache-warm workflow (schedule + server-start event)", "C5"),
    "F36": ("health-audit plane (config/pipelines/health_audit.json, 3 stage runners)", "C3"),
    "F37": ("digest + approval workflows (P11)", "C5"),
    "F41": ("host maintenance timers (destructive retention stays host; n8n approves/observes)", "C5"),
}
MIGRATE_SHAPES = {
    "F38": ("agent workflow: persona dispatcher", "agent_workflow", "M5"),
    "F40": ("agent workflow (CIO/Hermes/Aegis judgment via governed bridge)", "agent_workflow", "M5"),
    "F39": ("event subscription (+ daily backstop)", "event_subscription", "M6"),
    "F49": ("already n8n (fold into generic registry workflow)", "leaf_lane", "M0"),
    "F52": ("already n8n / one live fire away", "leaf_lane", "M0"),
}
_LOG_RE = re.compile(r">>\s*(\S+\.log)\b")
_CD_RE = re.compile(r"^\s*cd\s+(\S+)\s*&&")
_TAG_RE = re.compile(r"#\s*TRADEAI_LANE\s+(\S+)")
_BARE_CRON = re.compile(r"^[\d*/,\-]+(\s+[\d*/,\-]+){4}$")


def parse_crontab(text: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """(env assignments, active job lines). Same active-line rule as lane_registry.discover_cron."""
    env: dict[str, str] = {}
    jobs: list[dict[str, Any]] = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        first = s.split()[0]
        if "=" in first and not s[0].isdigit() and not s.startswith("*"):
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip()
            continue
        if s.startswith("@"):
            sched, _, cmd = s.partition(" ")
        else:
            parts = s.split(None, 5)
            sched, cmd = " ".join(parts[:5]), (parts[5] if len(parts) > 5 else "")
        tag = _TAG_RE.search(s)
        jobs.append({"line_no": n, "line": s, "schedule": sched, "command": cmd, "tag": tag.group(1) if tag else ""})
    return env, jobs


def registry_matchers(reg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(substring, row) for every cron-declaring row; bare schedules are not patterns (LP-DEF-19)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        if sched.get("kind") == "systemd":
            continue
        for key in ("match", "expression"):
            v = str(sched.get(key) or "")
            if not v or _BARE_CRON.match(v) or v in ("dispatcher", "tradeai-dispatcher"):
                continue
            if sched.get("kind") not in ("cron", "n8n") and key == "expression":
                continue
            out.append((v, row))
    return out


def match_rows(job: dict[str, Any], matchers: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for pat, row in matchers:
        if pat in job["line"]:
            seen.setdefault(row["lane_id"], row)
    rows = list(seen.values())

    def rank(r: dict[str, Any]) -> tuple:
        s = r.get("scheduler") or {}
        return (
            r["lane_id"] != job["tag"],
            r.get("state") != "ACTIVE",
            str(s.get("expression") or "") != job["schedule"],
            -len(str(s.get("match") or "")),
            r["lane_id"],
        )

    return sorted(rows, key=rank)


def base_job(name: str) -> str:
    return name.split(" [", 1)[0]


def inventory_for(lane: str, schedule: str, inv_by_lane: dict[str, list[dict[str, str]]]) -> Optional[dict[str, str]]:
    cands = inv_by_lane.get(lane) or []
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    for c in cands:
        if c["job_name"].endswith(f"[{schedule}]") or c["current_status"].startswith(f"cron {schedule};"):
            return c
    return cands[0]


def output_age_hours(command: str, env: dict[str, str], now: float) -> tuple[str, str]:
    m = _LOG_RE.search(command)
    if not m:
        return "", ""
    path = m.group(1)
    cd = _CD_RE.match(command)
    base = cd.group(1) if cd else env.get("PROJ", "")

    def expand(p: str) -> str:
        for k, v in sorted(env.items(), key=lambda kv: -len(kv[0])):
            p = p.replace("${%s}" % k, v).replace("$" + k, v)
        return os.path.expanduser(p.replace("$HOME", str(Path.home())))

    p = expand(path)
    if not p.startswith("/"):
        p = os.path.join(expand(base), p)
    try:
        return path, f"{(now - os.stat(p).st_mtime) / 3600.0:.1f}"
    except OSError:
        return path, "missing"


def signal_age_hours(row: Optional[dict[str, Any]], state_root: Path, now: float) -> tuple[str, str]:
    """Age of the registry output_signal file (file_mtime / json_key), resolved like lane_registry.observe_signal:
    relative paths against the persistent state root, ``~`` expanded. Other kinds are reported, not measured."""
    sig = (row or {}).get("output_signal") or {}
    kind = str(sig.get("kind") or "none")
    if kind not in ("file_mtime", "json_key") or not sig.get("path"):
        return kind, ""
    p = Path(str(sig["path"])).expanduser()
    if not p.is_absolute():
        p = state_root / p
    try:
        return kind, f"{(now - os.stat(p).st_mtime) / 3600.0:.1f}"
    except OSError:
        return kind, "missing"


def classify(
    lane: str,
    row: Optional[dict[str, Any]],
    inv: Optional[dict[str, str]],
    family: Optional[dict[str, str]],
    overrides: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """One disposition for one job. Overrides (verified per-lane evidence) win; then the family; then the registry."""
    ov = (overrides.get("lanes") or {}).get(lane)
    if ov:
        return {
            k: str(ov.get(k, "")) for k in ("disposition", "target", "target_shape", "wave", "evidence", "duplicate_of")
        }
    fid = (family or {}).get("family_id", "")
    state = (row or {}).get("state", "")
    sup = str((row or {}).get("superseded_by") or "")
    # A live line under a RETIRED row: its successor stage absorbed the work (premarket C1, B-families).
    if state == "RETIRED" and sup:
        sup_row = registry.get(sup) or {}
        tgt, wave = CONSOLIDATE_TARGETS.get(fid, (sup, "C1"))
        return {
            "disposition": "CONSOLIDATE",
            "target": tgt if fid in CONSOLIDATE_TARGETS else sup,
            "target_shape": "host_stage_runner",
            "wave": wave,
            "evidence": f"registry RETIRED superseded_by {sup} ({sup_row.get('state', '?')}); line still live — "
            "the successor's flip packet comments it",
            "duplicate_of": sup,
        }
    blocked = str((overrides.get("allowlist_blocked") or {}).get(lane) or "")
    if "sender" in blocked.lower() or "sends telegram" in blocked.lower():
        return {
            "disposition": "STAY_HOST",
            "target": "host sender (comms chokepoint)",
            "target_shape": "host",
            "wave": "-",
            "evidence": f"allowlist blocked_reasons: {blocked[:200]}",
            "duplicate_of": "",
        }
    inv_ref = (inv or {}).get("refactor_required", "")
    if inv_ref.startswith("N (stays on cron") and fid not in RETIRE_FAMILIES:
        return {
            "disposition": "STAY_HOST",
            "target": "host cron/systemd",
            "target_shape": "host",
            "wave": "-",
            "evidence": f"inventory 2026-10-14: not eligible for n8n ({(inv or {}).get('risk_level', '')[:120]}); "
            f"WS2 {fid}",
            "duplicate_of": "",
        }
    if fid in STAY_FAMILIES:
        return {
            "disposition": "STAY_HOST",
            "target": family.get("target_shape", "") if family else "",
            "target_shape": "host",
            "wave": "-",
            "evidence": f"WS2 {fid} {family.get('decision', '')}",
            "duplicate_of": "",
        }
    # A successor stage lane (premarket-data-pipeline, the B-family lanes, after-close/hermes stages) owns a family:
    # two or more absorbed rows name it in superseded_by. Checked after the host-only rules above.
    absorbed = sum(1 for r in registry.values() if str(r.get("superseded_by") or "") == lane)
    if absorbed >= 2:
        tgt, wave = CONSOLIDATE_TARGETS.get(fid, (f"{lane} (stage/family owner)", "C1"))
        return {
            "disposition": "CONSOLIDATE",
            "target": tgt,
            "target_shape": "host_stage_runner",
            "wave": wave,
            "evidence": f"registry successor: {absorbed} absorbed rows name it in superseded_by",
            "duplicate_of": "",
        }
    if fid in RETIRE_FAMILIES:
        return {
            "disposition": "RETIRE",
            "target": "-",
            "target_shape": "none",
            "wave": "R2",
            "evidence": f"WS2 {fid}: {(family or {}).get('evidence', '')[:240]} (R-check pending: operator YES/NO)",
            "duplicate_of": "",
        }
    if fid in CONSOLIDATE_TARGETS or (family or {}).get("category") == "CONSOLIDATE":
        tgt, wave = CONSOLIDATE_TARGETS.get(fid, (f"{(family or {}).get('family', fid)} multi-slot workflow", "C4"))
        return {
            "disposition": "CONSOLIDATE",
            "target": tgt,
            "target_shape": "host_stage_runner",
            "wave": wave,
            "evidence": f"WS2 {fid} {(family or {}).get('decision', '')}",
            "duplicate_of": "",
        }
    if fid in MIGRATE_SHAPES:
        tgt, shape, wave = MIGRATE_SHAPES[fid]
        return {
            "disposition": "MIGRATE_N8N",
            "target": tgt,
            "target_shape": shape,
            "wave": wave,
            "evidence": f"WS2 {fid} {(family or {}).get('decision', '')}",
            "duplicate_of": "",
        }
    if fid:
        return {
            "disposition": "MIGRATE_N8N",
            "target": "fabric Run Lane (registry leaf dispatcher)",
            "target_shape": "leaf_lane",
            "wave": migrate_wave(row, inv),
            "evidence": f"WS2 {fid} {(family or {}).get('decision', '')}; inventory {(inv or {}).get('bucket', '')}",
            "duplicate_of": "",
        }
    # No inventory/family (line installed after the 10-14 inventory): fall back on the registry recommendation.
    rec = str((row or {}).get("recommendation") or "")
    if rec == "KEEP_ON_CRON":
        return {
            "disposition": "STAY_HOST",
            "target": "host",
            "target_shape": "host",
            "wave": "-",
            "evidence": "registry KEEP_ON_CRON; not in the 10-14 inventory",
            "duplicate_of": "",
        }
    return {
        "disposition": "MIGRATE_N8N",
        "target": "fabric Run Lane (registry leaf dispatcher)",
        "target_shape": "leaf_lane",
        "wave": migrate_wave(row, inv),
        "evidence": f"not in the 10-14 inventory; registry {rec or 'no recommendation'}",
        "duplicate_of": "",
    }


def migrate_wave(row: Optional[dict[str, Any]], inv: Optional[dict[str, str]]) -> str:
    """M1 = this PR's shadow wave (overrides); M2 = already shadow, needs canary + live fire; M3 = needs only an
    allowlist + dispatch row (clean dry run exists); M4 = needs refactor (dry-run flag / flock / sender reach)."""
    stage = ((row or {}).get("scheduler") or {}).get("stage")
    if stage in ("canary", "cutover"):
        return "M0"
    if stage == "shadow":
        return "M2"
    ref = (inv or {}).get("refactor_required", "")
    if ref.startswith("Y"):
        return "M4"
    return "M3"


def build(
    crontab_text: str,
    reg: dict[str, Any],
    inventory: list[dict[str, str]],
    families: list[dict[str, str]],
    overrides: dict[str, Any],
    *,
    now: Optional[float] = None,
    measure_logs: bool = True,
    state_root: Optional[Path] = None,
) -> list[dict[str, str]]:
    now = now if now is not None else time.time()
    sroot = state_root or Path.home() / "trade-ai-releases" / "persistent-state"
    env, jobs = parse_crontab(crontab_text)
    matchers = registry_matchers(reg)
    registry = {r["lane_id"]: r for r in reg.get("lanes") or []}
    inv_by_lane: dict[str, list[dict[str, str]]] = {}
    for r in inventory:
        inv_by_lane.setdefault(base_job(r["job_name"]), []).append(r)
    fam_of: dict[str, dict[str, str]] = {}
    for f in families:
        for m in f["member_jobs"].split(";"):
            if m.strip():
                fam_of[m.strip()] = f
    out: list[dict[str, str]] = []
    matched_lanes: set[str] = set()
    for job in jobs:
        rows = match_rows(job, matchers)
        row = rows[0] if rows else None
        lane = row["lane_id"] if row else (job["tag"] or f"UNDECLARED:L{job['line_no']}")
        for r in rows:
            matched_lanes.add(r["lane_id"])
        inv = inventory_for(lane, job["schedule"], inv_by_lane)
        fam = fam_of.get(inv["job_name"]) if inv else None
        d = classify(lane, row, inv, fam, overrides, registry)
        log, age = output_age_hours(job["command"], env, now) if measure_logs else ("", "")
        skind, sage = signal_age_hours(row, sroot, now) if measure_logs else ("", "")
        out.append(
            {
                "row_id": f"cron:L{job['line_no']}",
                "source": "crontab",
                "line_no": str(job["line_no"]),
                "schedule": job["schedule"],
                "lane_id": lane,
                "registry_state": (row or {}).get("state", "NONE"),
                "registry_stage": ((row or {}).get("scheduler") or {}).get("stage") or "none",
                "inventory_job": (inv or {}).get("job_name", ""),
                "inventory_bucket": (inv or {}).get("bucket", ""),
                "family_id": (fam or {}).get("family_id", ""),
                "family": (fam or {}).get("family", ""),
                **d,
                "output_log": log,
                "output_age_h": age,
                "signal_kind": skind,
                "signal_age_h": sage,
                "command": job["line"][:400],
            }
        )
    # Registry ACTIVE lanes not scheduled by a crontab line (timers, services, n8n, event, none).
    for lane, row in sorted(registry.items()):
        if row.get("state") != "ACTIVE" or lane in matched_lanes:
            continue
        sched = row.get("scheduler") or {}
        if sched.get("kind") == "cron":
            src = "registry_cron_no_line"
        else:
            src = f"registry_{sched.get('kind') or 'none'}"
        inv = inventory_for(lane, str(sched.get("expression") or ""), inv_by_lane)
        fam = fam_of.get(inv["job_name"]) if inv else None
        d = classify(lane, row, inv, fam, overrides, registry)
        skind, sage = signal_age_hours(row, sroot, now) if measure_logs else ("", "")
        out.append(
            {
                "row_id": f"lane:{lane}",
                "source": src,
                "line_no": "",
                "schedule": str(sched.get("expression") or ""),
                "lane_id": lane,
                "registry_state": "ACTIVE",
                "registry_stage": sched.get("stage") or "none",
                "inventory_job": (inv or {}).get("job_name", ""),
                "inventory_bucket": (inv or {}).get("bucket", ""),
                "family_id": (fam or {}).get("family_id", ""),
                "family": (fam or {}).get("family", ""),
                **d,
                "output_log": "",
                "output_age_h": "",
                "signal_kind": skind,
                "signal_age_h": sage,
                "command": "",
            }
        )
    return out


def totals(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, int]]:
    t: dict[str, dict[str, int]] = {}
    for r in rows:
        key = "crontab" if r["source"] == "crontab" else "registry_only"
        t.setdefault(key, {d: 0 for d in DISPOSITIONS})
        t[key][r["disposition"]] += 1
    return t


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--crontab", required=True, help="a `crontab -l` copy (read-only)")
    ap.add_argument("--registry", default=str(ROOT / "config" / "lane_registry.json"))
    ap.add_argument("--allowlist", default=str(ROOT / "config" / "n8n_run_allowlist.json"))
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--families", required=True)
    ap.add_argument("--overrides", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-log-ages", action="store_true", help="skip os.stat of log redirects (hermetic runs)")
    a = ap.parse_args(argv)
    text = Path(a.crontab).read_text(encoding="utf-8")
    reg = json.loads(Path(a.registry).read_text(encoding="utf-8"))
    inventory = list(csv.DictReader(Path(a.inventory).open(encoding="utf-8")))
    families = list(csv.DictReader(Path(a.families).open(encoding="utf-8")))
    overrides = json.loads(Path(a.overrides).read_text(encoding="utf-8"))
    allow = json.loads(Path(a.allowlist).read_text(encoding="utf-8"))
    overrides.setdefault("allowlist_blocked", allow.get("blocked_reasons") or {})
    rows = build(text, reg, inventory, families, overrides, measure_logs=not a.no_log_ages)
    write_csv(rows, Path(a.out))
    t = totals(rows)
    print(
        json.dumps(
            {
                "crontab_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "active_lines": sum(t.get("crontab", {}).values()),
                "totals": t,
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
