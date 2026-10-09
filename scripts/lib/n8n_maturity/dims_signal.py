"""Signal dimensions of the n8n platform maturity scorer: 4 observability, 5 alert delivery, 10 reliability.

Every number is read through ``core.Probe`` (read-only). Thresholds come from
``config/n8n_platform_maturity.json`` ``dimensions.<id>.<key>``; the fallbacks in ``DEFAULTS`` apply when a
key is absent. Evidence pointers carry paths, counts and timestamps only — never message bodies, chat ids
or secrets.

Scoring convention (plan 2026-10-09): meeting the 8.0 gate scores >= 8.0; below the gate is linear
(``rate_score``: ``core.ratio_score`` with top = 1.0, so 100% = 10); sub-criteria are averaged with
``core.mean_score`` (a sub-criterion whose evidence is missing scores 0 and makes the dimension PARTIAL;
all missing makes it UNVERIFIED).
"""
from __future__ import annotations

import datetime as _dt
import re
import sqlite3
from collections import Counter
from typing import Any, Optional

from . import core

DEFAULTS: dict[str, dict[str, Any]] = {
    "observability": {
        "registry": "config/lane_registry.json",            # relative to probe.proj
        "lane_states": ["ACTIVE"],                          # registry states in scope
        "monitor_receipt": "data/runtime/research_lane_health.json",  # relative to probe.root
        "monitor_lane_key": "lane-registry",                # lane row the registry monitor appends
        "monitor_max_age_hours": 1.0,                       # timer fires every 15 min
        "monitor_timer": "tradeai-research-lane-health.timer",
        "monitor_service": "tradeai-research-lane-health.service",
        "monitor_script": "research_lane_health.py",       # crontab fallback match
        "monitor_alert_flag": "--alert",                    # the monitor only pages with this flag
        "unjudged_verdicts": ["UNVERIFIABLE"],              # verdicts that mean staleness was NOT judged
        "gate_coverage": 1.0,
    },
    "alert_delivery": {
        "ledgers": ["data/cio/system_telegram_sends.jsonl"],  # system Telegram send ledgers (root-relative)
        "ok_rate_basis": "rows",                            # "rows" (every attempt) or "identity" (any ok per identity)
        "gate_ok_rate": 0.99,
        "fanin_receipt": "data/runtime/n8n_incident_fanin_last.json",
        "fanin_max_age_hours": 1.0,                         # fan-in runs every 5 min
        "severities": ["P1", "P2"],
        "gate_p1p2_delivered": 1.0,
    },
    "reliability": {
        "ledger": "n8n_coordination_ledger.sqlite",         # under probe.gov()
        "success_states": ["RUN_DONE"],
        "failure_states": ["RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED"],
        "gate_success_rate": 0.99,
        "n8n_db_container": "",                             # "" = discover: postgres image whose name has "n8n"
        "n8n_db_user": "n8n",
        "n8n_db_name": "n8n",
        "n8n_error_statuses": ["error", "crashed"],
        "api_unit": "portfolio-server.service",
        "api_kill_pattern": r"code=killed, status=9",
        "failed_unit_ignore": [r"^ubuntu-report\.", r"^snap\.", r"^xdg-desktop-portal"],
        "count_zero_at": 5,                                 # kills / failed units at which that sub-score reaches 0
    },
}


def _cfg(probe: core.Probe, dim: str, key: str) -> Any:
    v = probe.cfg(dim).get(key)
    return DEFAULTS[dim][key] if v is None else v


def _rule(probe: core.Probe, dim: str, fallback: str) -> str:
    return str(probe.cfg(dim).get("gate_rule") or fallback)


def rate_score(value: Optional[float], gate: float) -> float:
    """A 0–1 rate against its gate: linear 0→gate maps 0→8.0, gate→1.0 maps 8.0→10 (a gate of 1.0: 100% = 10)."""
    if value is not None and gate >= 1.0 and value >= gate:
        return 10.0
    return core.ratio_score(value, gate, top=1.0)


def count_score(n: int, zero_at: float) -> float:
    """0 → 10 (gate met); n ≥ 1 → linear from 8 down to 0 at ``zero_at`` (a count gate of 0 is binary at 8)."""
    if n <= 0:
        return 10.0
    return core.clamp(8.0 * (1.0 - n / max(float(zero_at), 1.0)))


# ── 4 observability ──────────────────────────────────────────────────────────

def _monitor_scheduled(probe: core.Probe) -> tuple[Optional[bool], dict]:
    """(scheduled-and-alerting, detail). Systemd timer first, then an uncommented crontab line."""
    timer = _cfg(probe, "observability", "monitor_timer")
    service = _cfg(probe, "observability", "monitor_service")
    flag = _cfg(probe, "observability", "monitor_alert_flag")
    detail: dict[str, Any] = {}
    rc, out, _ = probe.run(["systemctl", "--user", "show", timer, "-p", "ActiveState"])
    if rc == 0 and "ActiveState=active" in out:
        rc2, out2, _ = probe.run(["systemctl", "--user", "show", service, "-p", "ExecStart"])
        alerting = rc2 == 0 and flag in out2
        detail.update(via=f"systemd:{timer}", alert_flag=alerting)
        return alerting, detail
    detail["timer_active"] = False if rc == 0 else None
    tab = probe.crontab()
    if tab is None:
        return (False if rc == 0 else None), detail
    script = _cfg(probe, "observability", "monitor_script")
    lines = [ln for ln in tab.splitlines() if script in ln and not ln.lstrip().startswith("#")]
    if lines:
        alerting = any(flag in ln for ln in lines)
        detail.update(via="crontab", alert_flag=alerting)
        return alerting, detail
    detail["via"] = "none"
    return False, detail


def observability(probe: core.Probe) -> dict:
    """% of in-scope registry lanes with an output_signal (kind != none) AND a live staleness alert.

    A lane counts when (a) its registry row declares ``output_signal.kind`` other than ``none`` and an
    ``expected_cadence_hours``; (b) the latest registry-monitor report (research_lane_health.json →
    ``lane-registry``) judged it — its verdict is not in ``unjudged_verdicts``; and (c) the monitor itself
    is alive (report ``as_of`` within ``monitor_max_age_hours``) and scheduled with the alert flag. When
    (c) fails no lane has a staleness alert. score = rate_score(coverage, gate_coverage) — 100% = 10.
    """
    dim = "observability"
    rule = _rule(probe, dim, "100% of registry lanes have an output_signal and a staleness alert")
    reg_path = probe.proj / _cfg(probe, dim, "registry")
    reg = probe.json(reg_path)
    if not isinstance(reg, dict) or not isinstance(reg.get("lanes"), list):
        return core.unverified(dim, rule, f"lane registry unreadable: {reg_path}")
    states = set(_cfg(probe, dim, "lane_states"))
    lanes = [r for r in reg["lanes"] if isinstance(r, dict) and str(r.get("state") or "ACTIVE") in states]
    if not lanes:
        return core.unverified(dim, rule, f"no registry lanes in states {sorted(states)}")
    with_signal = {str(r.get("lane_id")) for r in lanes
                   if str((r.get("output_signal") or {}).get("kind") or "none") != "none"
                   and float(r.get("expected_cadence_hours") or 0) > 0}

    ev = [core.evidence(str(reg_path), lanes_in_scope=len(lanes), with_output_signal=len(with_signal))]
    notes: list[str] = []
    status = core.VERIFIED
    mon_path = probe.root / _cfg(probe, dim, "monitor_receipt")
    mon = probe.json(mon_path)
    judged: set[str] = set()
    verdicts: Counter = Counter()
    mon_age: Optional[float] = None
    report = None
    if isinstance(mon, dict):
        lanes_map = mon.get("lanes")
        key = _cfg(probe, dim, "monitor_lane_key")
        if isinstance(lanes_map, dict):
            report = lanes_map.get(key)
        elif isinstance(lanes_map, list):
            report = next((x for x in lanes_map if isinstance(x, dict) and x.get("lane") == key), None)
        as_of = core.parse_ts((report or {}).get("as_of") or mon.get("as_of"))
        mon_age = round((probe.now - as_of).total_seconds() / 3600.0, 2) if as_of else None
    if not isinstance(report, dict):
        status = core.PARTIAL
        notes.append(f"registry staleness monitor report missing ({mon_path}); no lane has a proven staleness alert")
    else:
        unjudged = set(_cfg(probe, dim, "unjudged_verdicts"))
        for row in report.get("lanes") or []:
            if not isinstance(row, dict):
                continue
            v = str(row.get("verdict") or "")
            lid = str(row.get("lane_id") or row.get("lane") or "")
            verdicts[v] += 1
            if v and v not in unjudged:
                judged.add(lid)
        ev.append(core.evidence(str(mon_path), as_of=(report.get("as_of") or mon.get("as_of")), age_hours=mon_age,
                                declared=report.get("declared"), verdict_counts=dict(verdicts),
                                firing=report.get("firing")))

    scheduled, sched_detail = _monitor_scheduled(probe)
    ev.append(core.evidence("systemctl --user show / crontab -l", **sched_detail))
    max_age = float(_cfg(probe, dim, "monitor_max_age_hours"))
    fresh = mon_age is not None and mon_age <= max_age
    monitor_alive = bool(fresh and scheduled)
    if report is not None and not fresh:
        notes.append(f"monitor report stale: age {mon_age} h > {max_age} h")
    if scheduled is None:
        notes.append("monitor schedule unreadable (systemctl and crontab both unavailable)")
    elif not scheduled:
        notes.append("staleness monitor is not scheduled with its alert flag")

    covered = (with_signal & judged) if monitor_alive else set()
    coverage = len(covered) / len(lanes)
    gate = float(_cfg(probe, dim, "gate_coverage"))
    score = rate_score(coverage, gate)
    missing_signal = sorted({str(r.get("lane_id")) for r in lanes} - with_signal)
    metrics = {"lanes_in_scope": len(lanes), "with_output_signal": len(with_signal),
               "judged_by_monitor": len(judged & {str(r.get("lane_id")) for r in lanes}),
               "covered": len(covered), "coverage_pct": round(100 * coverage, 1),
               "monitor_alive": monitor_alive, "monitor_age_hours": mon_age,
               "lanes_without_signal_sample": missing_signal[:10]}
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=coverage >= gate and monitor_alive,
                           metrics=metrics, evidence_list=ev, status=status, notes=notes)


# ── 5 alert delivery ─────────────────────────────────────────────────────────

_DELIVERED_KEYS = ("delivered", "delivered_at", "notified_at", "telegram_message_id")
_DELIVER_OPS = ("deliver", "notify", "send", "telegram")


def _incident_delivered(inc: dict, ok_keys: set[str]) -> bool:
    if any(inc.get(k) for k in _DELIVERED_KEYS):
        return True
    for op in inc.get("ops") or []:
        if isinstance(op, dict) and any(t in str(op.get("op") or "").lower() for t in _DELIVER_OPS) \
                and (op.get("ok") is True or str(op.get("state") or "").upper() in ("DELIVERED", "SENT", "DELIVERY_CONFIRMED")):
            return True
    keys = {str(inc.get(k)) for k in ("idempotency_key", "event_id") if inc.get(k)}
    return any(k in s for k in keys for s in ok_keys)


def alert_delivery(probe: core.Probe) -> dict:
    """System Telegram ok rate over ``window_hours`` and P1/P2 fan-in incidents delivered to a human.

    * ok_rate = ok:true rows / rows with an ``ok`` field in the send ledgers within the window
      (``ok_rate_basis: identity`` = identities with any ok / identities). sub = rate_score(ok_rate, gate_ok_rate).
      No rows in the window → missing (None).
    * p1p2 = open P1/P2 incidents in the latest fan-in receipt (fresh within ``fanin_max_age_hours``) that carry
      delivery proof — a delivered/notified field or op on the incident, or an ok:true send-ledger row naming its
      idempotency_key/event_id. sub = rate_score(delivered/total, gate_p1p2_delivered); no open P1/P2 → 10.
      Missing or stale receipt → missing (None).
    score = mean of the two; gate = ok_rate ≥ gate_ok_rate and all open P1/P2 delivered.
    """
    dim = "alert_delivery"
    rule = _rule(probe, dim, "system Telegram ok >= 99%; P1/P2 fan-in delivered to a human")
    window_h = float(probe.cfg(dim).get("window_hours") or probe.config.get("window_hours") or 24)
    since = probe.since(window_h)
    ev: list[dict] = []
    notes: list[str] = []
    rows_all: list[dict] = []
    read_any = False
    ok_keys: set[str] = set()
    for rel in _cfg(probe, dim, "ledgers"):
        p = probe.root / rel
        rows = probe.rows(p, since=since)
        if rows is None:
            notes.append(f"send ledger absent: {p}")
            continue
        read_any = True
        rows = [r for r in rows if "ok" in r]
        rows_all.extend(rows)
        last_ok = None
        whole = probe.rows(p) or []
        for r in whole:
            if r.get("ok") is True:
                last_ok = r.get("at") or r.get("ts") or last_ok
                for k in ("identity", "incident_key", "idempotency_key", "event_id"):
                    if r.get(k):
                        ok_keys.add(str(r[k]))
        ev.append(core.evidence(str(p), window_hours=window_h, rows=len(rows),
                                ok=sum(1 for r in rows if r.get("ok") is True),
                                reasons=dict(Counter(str(r.get("reason")) for r in rows if r.get("ok") is not True)),
                                kinds=dict(Counter(str(r.get("kind")) for r in rows)), last_ok_at=last_ok))
    ok_rate: Optional[float] = None
    if rows_all:
        if _cfg(probe, dim, "ok_rate_basis") == "identity":
            ids: dict[str, bool] = {}
            for r in rows_all:
                ident = str(r.get("identity") or id(r))
                ids[ident] = ids.get(ident, False) or r.get("ok") is True
            ok_rate = sum(ids.values()) / len(ids)
        else:
            ok_rate = sum(1 for r in rows_all if r.get("ok") is True) / len(rows_all)
    elif read_any:
        notes.append(f"no system Telegram send rows in the last {window_h:g} h")
    gate_ok = float(_cfg(probe, dim, "gate_ok_rate"))
    ok_sub = rate_score(ok_rate, gate_ok) if ok_rate is not None else None

    fan_path = probe.root / _cfg(probe, dim, "fanin_receipt")
    fan = probe.json(fan_path)
    sevs = set(_cfg(probe, dim, "severities"))
    p1p2_sub: Optional[float] = None
    p1p2_total = p1p2_delivered = 0
    fan_age: Optional[float] = None
    by_sev: dict = {}
    if isinstance(fan, dict):
        as_of = core.parse_ts(fan.get("as_of"))
        fan_age = round((probe.now - as_of).total_seconds() / 3600.0, 2) if as_of else None
        incs = [i for i in (fan.get("incidents") or []) if isinstance(i, dict) and str(i.get("severity")) in sevs]
        by_sev = dict(Counter(str(i.get("severity")) for i in incs))
        p1p2_total = len(incs)
        p1p2_delivered = sum(1 for i in incs if _incident_delivered(i, ok_keys))
        ev.append(core.evidence(str(fan_path), as_of=fan.get("as_of"), age_hours=fan_age, open=fan.get("open"),
                                p1p2_open=by_sev, p1p2_delivered=p1p2_delivered))
        max_age = float(_cfg(probe, dim, "fanin_max_age_hours"))
        if fan_age is None or fan_age > max_age:
            notes.append(f"incident fan-in receipt stale (age {fan_age} h > {max_age} h): P1/P2 delivery unproven")
        else:
            gate_p = float(_cfg(probe, dim, "gate_p1p2_delivered"))
            p1p2_sub = 10.0 if p1p2_total == 0 else rate_score(p1p2_delivered / p1p2_total, gate_p)
    else:
        notes.append(f"incident fan-in receipt absent: {fan_path}")

    if ok_sub is None and p1p2_sub is None:
        return core.unverified(dim, rule, "; ".join(notes) or "no delivery evidence",
                               metrics={"window_hours": window_h}, evidence_list=ev)
    score, status, mnotes = core.mean_score([("system_telegram_ok_rate", ok_sub), ("p1p2_delivered", p1p2_sub)])
    gate_p = float(_cfg(probe, dim, "gate_p1p2_delivered"))
    p_rate = (p1p2_delivered / p1p2_total) if p1p2_total else 1.0
    gate_pass = (ok_rate is not None and ok_rate >= gate_ok and p1p2_sub is not None and p_rate >= gate_p)
    metrics = {"window_hours": window_h, "send_rows": len(rows_all),
               "ok_rate_pct": None if ok_rate is None else round(100 * ok_rate, 2),
               "ok_rate_basis": _cfg(probe, dim, "ok_rate_basis"),
               "p1p2_open": p1p2_total, "p1p2_delivered": p1p2_delivered, "fanin_age_hours": fan_age}
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=notes + mnotes)


# ── 10 reliability ───────────────────────────────────────────────────────────

def _ledger_runs(probe: core.Probe, since_iso: str) -> Optional[Counter]:
    path = probe.gov() / _cfg(probe, "reliability", "ledger")
    con = probe.sqlite_ro(path)
    if con is None:
        return None
    try:
        rows = con.execute(
            "SELECT state, COALESCE(exit_code, 0) FROM runs WHERE COALESCE(finished_at, requested_at) >= ?",
            (since_iso,)).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    ok_states = set(_cfg(probe, "reliability", "success_states"))
    bad_states = set(_cfg(probe, "reliability", "failure_states"))
    c: Counter = Counter()
    for state, code in rows:
        if state in ok_states:
            c["success" if int(code or 0) == 0 else "failure"] += 1
        elif state in bad_states:
            c["failure"] += 1
        else:
            c["other"] += 1
        c[f"state:{state}"] += 1
    return c


def _n8n_errors(probe: core.Probe, since_iso: str) -> tuple[Optional[int], dict]:
    dim = "reliability"
    container = _cfg(probe, dim, "n8n_db_container")
    if not container:
        rc, out, _ = probe.run(["docker", "ps", "--format", "{{.Names}} {{.Image}}"])
        if rc != 0:
            return None, {"docker": f"rc={rc}"}
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) >= 2 and "postgres" in parts[1] and "n8n" in parts[0]:
                container = parts[0]
                break
        if not container:
            return None, {"docker": "no n8n postgres container"}
    statuses = ",".join("'" + re.sub(r"[^a-z_]", "", s) + "'" for s in _cfg(probe, dim, "n8n_error_statuses"))
    sql = (f"SELECT count(*) FROM execution_entity WHERE status IN ({statuses}) "
           f"AND \"startedAt\" >= '{since_iso}'::timestamptz")
    rc, out, _ = probe.run(["docker", "exec", container, "psql", "-U", str(_cfg(probe, dim, "n8n_db_user")),
                            "-d", str(_cfg(probe, dim, "n8n_db_name")), "-At", "-c", sql])
    if rc != 0:
        return None, {"container": container, "psql": f"rc={rc}"}
    try:
        return int(out.strip().splitlines()[-1]), {"container": container}
    except (ValueError, IndexError):
        return None, {"container": container, "psql": "unparseable"}


def reliability(probe: core.Probe) -> dict:
    """Run success over ``window_hours``, API SIGKILLs and failed user units.

    * run_success = success / (success + failure) where success = coordination-ledger ``runs`` rows in
      ``success_states`` with exit 0, failure = ``failure_states`` rows (or success state with exit != 0) plus
      n8n ``execution_entity`` rows in ``n8n_error_statuses`` (n8n keeps no success executions, so its errors
      are added as failures; conservative — a ledger RUN_FAILED may also be an n8n error). RUN_SKIPPED_LOCK and
      in-flight rows are excluded. sub = rate_score(rate, gate_success_rate). No ledger → missing.
    * api_kills = journal lines for ``api_unit`` matching ``api_kill_pattern`` in the window; sub = count_score.
    * failed_units = ``systemctl --user list-units --failed`` minus ``failed_unit_ignore``; sub = count_score.
    score = mean of the three; gate = rate ≥ gate_success_rate and 0 kills and 0 failed units.
    """
    dim = "reliability"
    rule = _rule(probe, dim, "run success >= 99% over 24 h; 0 API SIGKILLs; 0 failed units")
    window_h = float(probe.cfg(dim).get("window_hours") or probe.config.get("window_hours") or 24)
    since = probe.since(window_h).astimezone(_dt.timezone.utc)
    since_iso = since.isoformat()
    zero_at = float(_cfg(probe, dim, "count_zero_at"))
    ev: list[dict] = []
    notes: list[str] = []

    runs = _ledger_runs(probe, since_iso)
    n8n_err, n8n_detail = _n8n_errors(probe, since_iso)
    rate: Optional[float] = None
    run_sub: Optional[float] = None
    if runs is None:
        notes.append(f"coordination ledger runs unreadable: {probe.gov() / _cfg(probe, dim, 'ledger')}")
    else:
        succ, fail = runs["success"], runs["failure"] + (n8n_err or 0)
        if succ + fail:
            rate = succ / (succ + fail)
            run_sub = rate_score(rate, float(_cfg(probe, dim, "gate_success_rate")))
        else:
            notes.append(f"no finished runs in the last {window_h:g} h")
        ev.append(core.evidence(str(probe.gov() / _cfg(probe, dim, "ledger")) + " runs", window_hours=window_h,
                                success=succ, failure=runs["failure"],
                                states={k[6:]: v for k, v in runs.items() if k.startswith("state:")}))
    ev.append(core.evidence("docker exec <n8n db> psql execution_entity", n8n_errors=n8n_err, **n8n_detail))
    if n8n_err is None:
        notes.append("n8n execution errors unreadable (not added to failures)")

    unit = _cfg(probe, dim, "api_unit")
    rc, out, _ = probe.run(["journalctl", "--user", "-u", unit, "--since",
                            since.strftime("%Y-%m-%d %H:%M:%S UTC"), "--no-pager", "-o", "short-iso"])
    kills: Optional[int] = None
    kill_sub: Optional[float] = None
    if rc == 0:
        pat = re.compile(_cfg(probe, dim, "api_kill_pattern"))
        hits = [ln for ln in out.splitlines() if pat.search(ln)]
        kills = len(hits)
        kill_sub = count_score(kills, zero_at)
        ev.append(core.evidence(f"journalctl --user -u {unit}", window_hours=window_h, sigkills=kills,
                                kill_times=[ln.split()[0] for ln in hits][:10]))
    else:
        notes.append(f"journal for {unit} unreadable (rc={rc})")

    rc, out, _ = probe.run(["systemctl", "--user", "list-units", "--failed", "--no-legend", "--plain"])
    failed: Optional[list[str]] = None
    unit_sub: Optional[float] = None
    if rc == 0:
        ignore = [re.compile(p) for p in _cfg(probe, dim, "failed_unit_ignore")]
        names = [ln.split()[0] for ln in out.splitlines() if ln.strip() and not ln.startswith("0 ")]
        failed = [n for n in names if not any(p.search(n) for p in ignore)]
        unit_sub = count_score(len(failed), zero_at)
        ev.append(core.evidence("systemctl --user list-units --failed", failed=failed,
                                ignored=len(names) - len(failed)))
    else:
        notes.append(f"systemctl --user list-units --failed unreadable (rc={rc})")

    parts = [("run_success", run_sub), ("api_sigkills", kill_sub), ("failed_units", unit_sub)]
    score, status, mnotes = core.mean_score(parts)
    if status == core.UNVERIFIED:
        return core.unverified(dim, rule, "; ".join(notes) or "no reliability evidence", evidence_list=ev)
    gate_pass = (rate is not None and rate >= float(_cfg(probe, dim, "gate_success_rate"))
                 and kills == 0 and failed is not None and not failed)
    metrics = {"window_hours": window_h, "run_success_pct": None if rate is None else round(100 * rate, 2),
               "runs_success": None if runs is None else runs["success"],
               "runs_failure": None if runs is None else runs["failure"], "n8n_errors": n8n_err,
               "api_sigkills": kills, "failed_units": failed,
               "sub_scores": {n: (None if v is None else round(v, 2)) for n, v in parts}}
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=ev, status=status, notes=notes + mnotes)


COLLECTORS = {"observability": observability, "alert_delivery": alert_delivery, "reliability": reliability}
