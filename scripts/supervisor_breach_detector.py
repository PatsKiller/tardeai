#!/usr/bin/env python3
"""supervisor_breach_detector.py — Breach@v1 detection over heartbeats, SLA rows and output signals (06 §5).

Wave 1 tranche 2 body: DETECT and RECORD. It walks every ACTIVE lane in config/lane_registry.json,
reads its SLA row (data/runtime/supervisor_sla_seed.json, or intelligence.sla when present), its
heartbeat (file fallback via supervisor_heartbeat.read_all, or intelligence.heartbeat), and its
registered output signal (lane_registry.observe_signal), and raises:

  UNGOVERNED         no SLA row
  SILENT             last beat older than max_silence_s (only when the lane has ever beaten)
  NO_OUTPUT          output signal older than 3 × cadence (or unreadable) for an ACTIVE lane
  MEMORY_UNREACHABLE last beat says memory_context_ok = false on a fail-closed lane

It writes an append-only data/runtime/supervisor_breaches.jsonl (one row per NEW breach id; a breach
id is stable per lane × kind × day, so a repeat is a re-observation, not a new row) and
data/runtime/supervisor_breach_detector_latest.json (the lane's own output signal). Ladder actions
L1–L5 are NOT executed here: L1 restarts need the sudoers allowlist review (11 S-6) and land in
Wave 2; escalation to the health agent (L3) is available with --enqueue-escalations and is off by default.

Dry-run by default (prints, writes nothing); --write records.
Approval: pkg-20260927-cogx-w1-d9e1 item 2. Authority: READ_ONLY_ADVISORY. Never touches a broker.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
NO_CONSUMER_REASON = (
    "Breach@v1 rows are read by report_platform_conformance (monitoring standard) and by the Command "
    "Center supervisor panel (Wave 2); lane supervisor-breach-detector is declared NEVER_SCHEDULED "
    "until the pkg-20260927-cogx-w1-d9e1 service grant installs its timer"
)
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

SCHEMA = "Breach@v1"
KINDS = ("SILENT", "HUNG", "BACKLOG", "FAILING", "NO_OUTPUT", "MEMORY_UNREACHABLE", "SLO_MISS", "UNGOVERNED")


def _parse(ts):
    if not ts:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def breach_id(lane_id: str, kind: str, day: str) -> str:
    return "br_" + hashlib.sha256(f"{lane_id}|{kind}|{day}".encode()).hexdigest()[:16]


def _parse_any(ts):
    return _parse(ts)


def _expected_since(lane: dict, now: _dt.datetime, max_run_s: float = 900.0) -> tuple[_dt.datetime | None, str]:
    """When should this lane have produced by? Returns (deadline, basis).

    cron lanes: the most recent scheduled fire ≤ now (5-field expression), so a weekday-only or
    market-hours lane is not judged over a weekend (2026-09-27 triage: 6 false breaches). Other
    lanes: 3 × cadence (min 15 min), extended by any declared inactive days ending today.
    """
    sched = lane.get("scheduler") or {}
    expr = str(sched.get("expression") or "")
    cad_h = lane.get("expected_cadence_hours")
    if sched.get("kind") == "cron" and expr:
        try:
            import cron_last_fire as cron_schedule  # type: ignore
            # the most recent fire that has had max_run to finish: a run still in progress is not a miss
            local_ref = (now - _dt.timedelta(seconds=max_run_s)).astimezone()
            lf = cron_schedule.last_fire(expr, local_ref.replace(tzinfo=None))
            local_now = local_ref
            if lf is not None:
                lf = lf.replace(tzinfo=local_now.tzinfo).astimezone(_dt.timezone.utc)
                return lf, f"cron:{expr}"
        except Exception:  # noqa: BLE001 — fall back to the cadence rule
            pass
    if not cad_h:
        return None, "no_cadence"
    limit_s = max(3 * float(cad_h) * 3600, 900)
    days = lane.get("active_days")
    if isinstance(days, (list, tuple)) and days:
        # extend the window by the inactive days that end today (Mon=0 .. Sun=6)
        d = now.astimezone().date(); extra = 0
        while d.weekday() not in days and extra < 7:
            extra += 1; d -= _dt.timedelta(days=1)
        limit_s += extra * 86400
    return now - _dt.timedelta(seconds=limit_s), f"cadence:{cad_h}h×3"


def detect(*, lanes: list[dict], sla_by_lane: dict[str, dict], heartbeats: dict[str, dict],
           observe, now: _dt.datetime) -> list[dict]:
    """Pure: returns Breach@v1 rows. ``observe(sig)`` returns {last_output_at, readable}."""
    day = now.strftime("%Y-%m-%d")
    out: list[dict] = []

    def add(lane, kind, evidence, level=1):
        out.append({"schema": SCHEMA, "breach_id": breach_id(lane["lane_id"], kind, day), "lane_id": lane["lane_id"],
                    "silo_id": None, "kind": kind, "detected_at": now.isoformat(), "evidence": evidence,
                    "level": level, "state": "OPEN", "recovery": [], "authority": "READ_ONLY_ADVISORY"})

    for lane in lanes:
        if lane.get("state") != "ACTIVE":
            continue
        lid = lane.get("lane_id")
        fd = _parse(lane.get("first_due"))
        if fd and now < fd:
            continue  # declared not-yet-due (e.g. a monthly report installed mid-month)
        sla = sla_by_lane.get(lid)
        if not sla:
            add(lane, "UNGOVERNED", {"note": "no SLA row", "cmd": "python3 scripts/seed_supervisor_sla.py --json-out data/runtime/supervisor_sla_seed.json"})
            continue
        hb = heartbeats.get(lid)
        if hb and sla.get("max_silence_s"):
            lb = _parse(hb.get("last_beat"))
            if lb and (now - lb).total_seconds() > float(sla["max_silence_s"]):
                add(lane, "SILENT", {"last_beat": hb.get("last_beat"), "max_silence_s": sla["max_silence_s"], "boot_id": hb.get("boot_id")})
            if hb.get("memory_context_ok") is False and sla.get("memory_context_required") == "fail-closed":
                add(lane, "MEMORY_UNREACHABLE", {"degraded_reasons": hb.get("degraded_reasons"), "last_beat": hb.get("last_beat")}, level=2)
        sig = lane.get("output_signal") or {}
        if sig.get("kind") in (None, "none"):
            continue
        max_run = float(sla.get("max_run_s") or 900)
        deadline, basis = _expected_since(lane, now, max_run)
        if deadline is None:
            continue
        obs = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (observe(sig) or {}).items()}
        lo = _parse(obs.get("last_output_at"))
        if obs.get("readable") is False:
            add(lane, "NO_OUTPUT", {"signal": sig, "observed": obs, "basis": basis, "note": "signal unreadable (UNVERIFIABLE, reported as NO_OUTPUT)"})
        elif lo is None:
            add(lane, "NO_OUTPUT", {"signal": sig, "observed": obs, "basis": basis, "note": "never produced"})
        elif lo < deadline:
            add(lane, "NO_OUTPUT", {"signal": sig, "last_output_at": obs.get("last_output_at"), "expected_by": deadline.isoformat(), "basis": basis})
    return out


def _read_only_db_query():
    """A `db_query(sql) -> rows` for db_max signals, read-only, fail-soft (None when no DSN).
    2026-09-27 triage: without it every db_max lane read as NO_OUTPUT ("no db_query supplied")."""
    try:
        import db_adapter  # type: ignore
        conn = db_adapter._get_conn()
    except Exception:  # noqa: BLE001
        return None

    def q(sql: str):
        try:
            with conn.cursor() as cur:
                cur.execute("BEGIN READ ONLY")
                cur.execute(sql)
                rows = cur.fetchall()
            conn.rollback()
            return rows
        except Exception:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None
    return q


L4_AFTER_S = 3 * 3600      # a breach still OPEN this long after detection pages the operator (06 §5 L4)
L5_RECURRENCES = 3         # the same lane × kind three times in 7 days → orchestration-change proposal (06 §5 L5)


def _ladder_l4_l5(rows: list[dict], sla_by_lane: dict, now, runtime_dir: Path, *, live: bool) -> dict:
    """L4: one page per breach_id (edge-triggered through alert_transition) when a breach stays OPEN past
    L4_AFTER_S and the lane's ladder_max allows it. L5: a Recovery/orchestration proposal row when a
    lane × kind recurs L5_RECURRENCES times in 7 days. Shadow = receipts only; live = page + proposal."""
    led = runtime_dir / "supervisor_breaches.jsonl"
    history: list[dict] = []
    try:
        with led.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        history = []
    week_ago = (now - _dt.timedelta(days=7)).isoformat()
    recur: dict[tuple, int] = {}
    first_seen: dict[str, str] = {}
    for h in history:
        if str(h.get("detected_at") or "") >= week_ago:
            recur[(h.get("lane_id"), h.get("kind"))] = recur.get((h.get("lane_id"), h.get("kind")), 0) + 1
        first_seen.setdefault(h.get("breach_id"), h.get("detected_at"))
    out = {"l4_candidates": 0, "l4_paged": 0, "l5_candidates": 0, "l5_proposed": 0, "mode": "live" if live else "shadow"}
    receipts = runtime_dir / "supervisor_ladder_receipts.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)
    try:
        import alert_transition as at  # type: ignore
    except Exception:  # noqa: BLE001
        at = None
    for r in rows:
        lane = r.get("lane_id"); kind = r.get("kind")
        ladder_max = int((sla_by_lane.get(lane) or {}).get("ladder_max") or 3)
        since = first_seen.get(r.get("breach_id")) or r.get("detected_at")
        try:
            age_s = (now - _dt.datetime.fromisoformat(str(since).replace("Z", "+00:00"))).total_seconds()
        except (ValueError, TypeError):
            age_s = 0
        rec = {"schema": "SupervisorLadderReceipt@v1", "ts": now.isoformat(), "breach_id": r.get("breach_id"), "lane_id": lane, "kind": kind,
               "age_s": int(age_s), "ladder_max": ladder_max, "recurrences_7d": recur.get((lane, kind), 0), "mode": out["mode"]}
        if ladder_max >= 4 and age_s >= L4_AFTER_S:
            out["l4_candidates"] += 1
            rec["level"] = 4
            fire = True
            if live and at is not None:  # shadow never touches the transition state (an evaluate persists the observation)
                try:
                    tr = at.evaluate(f"supervisor:{r.get('breach_id')}", "BREACH", path=runtime_dir / "supervisor_ladder_transitions.json", extra={"kind": kind})
                    fire = bool(getattr(tr, "notify", True))       # edge-triggered: one page per breach, re-alert after MIN_REALERT_MINUTES
                    rec["transition"] = getattr(tr, "action", None)
                    tr.commit()
                except Exception:  # noqa: BLE001
                    fire = True
            rec["would_page"] = fire
            if live and fire:
                try:
                    from telegram_alert import send_telegram  # type: ignore
                    send_telegram(f"STOP HEALTH — supervisor L4: lane {lane} {kind} OPEN for {int(age_s // 3600)}h (breach {r.get('breach_id')}); L1–L3 did not recover it",
                                  bypass_router=True)
                    rec["paged"] = True; out["l4_paged"] += 1
                except Exception as exc:  # noqa: BLE001
                    rec["paged"] = False; rec["error"] = type(exc).__name__
        if recur.get((lane, kind), 0) >= L5_RECURRENCES and ladder_max >= 5:
            out["l5_candidates"] += 1
            rec["level"] = max(rec.get("level", 0), 5)
            proposal = {"schema": "OrchestrationProposal@v1", "ts": now.isoformat(), "lane_id": lane, "kind": kind,
                        "recurrences_7d": recur.get((lane, kind), 0), "proposal": "declare an alternate lane or change the schedule / owner (06 §5 L5)",
                        "requires": "ApprovalPackage item (operator-only, AGENTS §17)", "state": "PROPOSED" if live else "SHADOW"}
            rec["proposal"] = proposal
            if live:
                with (runtime_dir.parent / "governance" / "orchestration_proposals.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(proposal, sort_keys=True) + "\n")
                out["l5_proposed"] += 1
        if rec.get("level"):
            with receipts.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(PROJ), help="code root (lane registry, silos)")
    ap.add_argument("--state-root", help="persistent-state root for output signals (default: production)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--enqueue-escalations", action="store_true", help="L3: append to the health agent's escalation queue (off by default)")
    ap.add_argument("--ladder", action="store_true", help="L4/L5 live: page the operator / write the orchestration proposal (default: shadow receipts only)")
    a = ap.parse_args()
    root = Path(a.root)
    env = os.environ
    now = _dt.datetime.now(_dt.timezone.utc)
    import lane_registry  # type: ignore
    import supervisor_heartbeat as hbmod  # type: ignore
    reg = lane_registry.load_registry(root / "config" / "lane_registry.json")
    from approval_package import governance_dir  # type: ignore
    runtime_dir = governance_dir(root, env).parent / "runtime"   # state root's data/runtime (a persistent symlink in releases)
    seed_p = runtime_dir / "supervisor_sla_seed.json"
    sla_by_lane = {r["lane_id"]: r for r in (json.loads(seed_p.read_text()).get("rows", []) if seed_p.exists() else [])}
    heartbeats = {h.get("lane_id"): h for h in hbmod.read_all(root=root, env=env)}
    state_root = Path(a.state_root) if a.state_root else None
    db_query = _read_only_db_query()
    observe = (lambda sig: lane_registry.observe_signal(sig, root=state_root, db_query=db_query)) if state_root else (lambda sig: lane_registry.observe_signal(sig, db_query=db_query))
    rows = detect(lanes=reg.get("lanes", []), sla_by_lane=sla_by_lane, heartbeats=heartbeats, observe=observe, now=now)
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    summary = {"schema": "BreachDetectorRun@v1", "as_of": now.isoformat(), "active_lanes": sum(1 for l in reg.get("lanes", []) if l.get("state") == "ACTIVE"),
               "sla_rows": len(sla_by_lane), "heartbeats": len(heartbeats), "breaches": len(rows), "by_kind": by_kind,
               "ladder": "detect+record only (L1–L5 not executed in Wave 1)", "authority": "READ_ONLY_ADVISORY"}
    print(json.dumps(summary, indent=1))
    for r in rows[:15]:
        print(f"  {r['kind']:<18} {r['lane_id']}")
    if len(rows) > 15:
        print(f"  … {len(rows) - 15} more")
    if a.write:
        led = runtime_dir / "supervisor_breaches.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        if led.exists():
            for line in led.read_text().splitlines():
                try:
                    seen.add(json.loads(line).get("breach_id"))
                except (json.JSONDecodeError, AttributeError):
                    pass
        new = [r for r in rows if r["breach_id"] not in seen]
        with led.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
        latest = runtime_dir / "supervisor_breach_detector_latest.json"
        tmp = latest.with_suffix(".json.tmp"); tmp.write_text(json.dumps({**summary, "new_rows": len(new)}, indent=1, default=str) + "\n"); os.replace(tmp, latest)
        # item 10 (pkg-20260928-wave-2-enforcement-35c4): upsert the beat into intelligence.heartbeat when reachable
        _conn = None
        try:
            import db_adapter  # type: ignore
            _conn = db_adapter._get_conn()
            with _conn.cursor() as _c:
                _c.execute("SET app.tenant_id = 'tradeai:tenant:primary'")
        except Exception:  # noqa: BLE001
            _conn = None
        hb_row = hbmod.beat("supervisor-breach-detector", conn=_conn, success=True, output_signal=True, work_done=len(rows), root=root, env=env)
        print(f"heartbeat: file + pg={hb_row.get('pg')}")
        print(f"wrote {len(new)} new breach rows; latest → {latest}")
        if a.enqueue_escalations and new:
            try:
                import health_agent  # type: ignore
                # Wave 4 O-W4-5 finding: this call passed one argument to enqueue_escalations(policy, findings_flat)
                # and rows without `severity`, so the TypeError was swallowed as "L3 unavailable" and nothing was
                # ever enqueued. Now the policy is loaded and each breach carries a severity + component.
                pol = {}
                try:
                    pol = health_agent.load_policy() if hasattr(health_agent, "load_policy") else {}
                except Exception:  # noqa: BLE001
                    pol = {}
                findings = [{"source": "supervisor-breach-detector", "breach_id": r["breach_id"], "lane_id": r["lane_id"], "kind": r["kind"],
                             "component": f"lane:{r['lane_id']}", "type": f"breach_{str(r['kind']).lower()}", "severity": "high" if r.get("level", 1) >= 2 else "medium",
                             "message": f"{r['kind']} on lane {r['lane_id']}", "evidence": r.get("evidence")} for r in new]
                health_agent.enqueue_escalations(pol, findings)
                print(f"L3: {len(findings)} escalation(s) enqueued")
            except Exception as exc:  # noqa: BLE001
                print(f"L3 enqueue unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        # Wave 4 O-W4-5: ladder L4 (operator page) and L5 (orchestration-change proposal). SHADOW unless --ladder:
        # what WOULD be paged / proposed is recorded on data/runtime/supervisor_ladder_receipts.jsonl.
        try:
            ladder_rows = _ladder_l4_l5(rows, sla_by_lane, now, runtime_dir, live=bool(getattr(a, "ladder", False)))
            print(f"ladder L4/L5: {ladder_rows}")
        except Exception as exc:  # noqa: BLE001
            print(f"ladder skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
    else:
        print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
