#!/usr/bin/env python3
"""LIVE MATURITY n/N counter (QA E14, LiveAcceptance@v2) — read-only on production.

A production fix is verified by N consecutive passing production cycles since it went live, not by
elapsed time. Rules (operator 11-11 15:15 ET):
  * a cycle counts once (state keeps every counted cycle id);
  * a dry_run receipt is never a production cycle (neither passes nor fails);
  * any failing cycle resets n to 0;
  * a verdict already given is never downgraded: after n reached N the line stays
    "PRODUCTION VERIFIED · LIVE MATURITY n/N";
  * what cannot be proven is UNKNOWN, never guessed.

Probe kinds: n8n_receipts (d:<lane>:live:*.json), last_receipt (data/runtime/<lane>_last.json, cron
lanes), service (hourly sample of systemd unit + /proc cwd + restart events; never a loopback request),
unknown. The only file written is the counter's own state file, and only with --write-state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import zoneinfo
from pathlib import Path

ET = zoneinfo.ZoneInfo("America/New_York")
DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "live_acceptance_v2.json"
SP = Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state" / "data")
VERIFIED = "PRODUCTION VERIFIED"


def load_registry(path) -> dict:
    reg = json.loads(Path(path).read_text())
    if reg.get("schema") != "LiveAcceptance@v2":
        raise ValueError(f"{path}: schema {reg.get('schema')!r} is not LiveAcceptance@v2")
    return reg


def parse_et(s):
    if not s:
        return None
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ET)


def _parse_iso(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


class Sources:
    """Where production evidence is read from. Tests inject temp dirs and a fake service reader."""

    def __init__(self, receipts_dir=SP / "runtime" / "n8n_runs", runtime_dir=SP / "runtime", service_reader=None):
        self.receipts_dir = Path(receipts_dir)
        self.runtime_dir = Path(runtime_dir)
        self.service_reader = service_reader or systemd_reader


def systemd_reader(unit):
    """{'active','active_enter','cwd'} from systemctl --user + /proc/<pid>/cwd; None when unreadable."""
    try:
        out = subprocess.run(["systemctl", "--user", "show", unit, "-p", "ActiveState,ActiveEnterTimestamp,MainPID"],
                             capture_output=True, text=True, timeout=20).stdout
        kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        pid = int(kv.get("MainPID") or 0)
        cwd = os.readlink(f"/proc/{pid}/cwd") if pid else ""
        if not kv.get("ActiveState"):
            return None
        return {"active": kv["ActiveState"], "active_enter": kv.get("ActiveEnterTimestamp", ""), "cwd": cwd}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# ---- cycle extraction: each returns [(cycle_id, started_dt, passed, note)] sorted by start -------------------

def _n8n_cycles(src, lane, since):
    prefix = f"d:{lane}:live:"
    out = []
    with os.scandir(src.receipts_dir) as it:
        names = [e.name for e in it if e.name.startswith(prefix) and e.name.endswith(".json")]
    for name in names:
        try:
            r = json.loads((src.receipts_dir / name).read_text())
        except (OSError, ValueError):
            continue
        started = _parse_iso(r.get("started_at"))
        if started is None or started < since:
            continue
        if r.get("mode") != "live" or r.get("requested_mode", "live") != "live":
            continue                                      # dry_run never counts
        if (r.get("stage_clamp") or {}).get("effective_mode", "live") != "live":
            continue                                      # clamped to dry_run by the stage gate
        if r.get("lock_skipped") or not r.get("finished_at"):
            continue                                      # another instance held the lock / still running
        ok = r.get("state") == "RUN_DONE" and r.get("exit_code") == 0 and not r.get("timed_out")
        note = f"{r.get('state')} exit={r.get('exit_code')}"
        out.append((r.get("run_id") or name[:-5], started, ok, note))
    return sorted(out, key=lambda c: c[1])


def _last_receipt_cycles(src, lane, since):
    p = src.runtime_dir / f"{lane}_last.json"
    try:
        r = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    started = _parse_iso(r.get("started_at"))
    if started is None or started < since or r.get("mode") != "live" or not r.get("finished_at"):
        return []
    ok = r.get("status") == "ok" and r.get("exit") == 0
    return [(f"{lane}@{r['started_at']}", started, ok, f"{r.get('status')} exit={r.get('exit')}")]


# ---- evaluation -----------------------------------------------------------------------------------------

def _apply(st, cid, at, ok, note):
    st["history"].append({"id": cid, "at": at.astimezone(ET).strftime("%Y-%m-%d %H:%M"), "pass": ok, "note": note})
    st["n"] = st["n"] + 1 if ok else 0
    if not ok:
        st["restart_confirmed"] = False
    st["last_cycle"] = cid


def _verdict(item, st, restart_needed):
    n, N = st["n"], item["N"]
    done = n >= N and (st.get("restart_confirmed") or not restart_needed)
    if done:
        st["ever_verified"] = True
    ever = st.get("ever_verified") or item.get("prior_verdict") == VERIFIED
    tail = " (restart not yet seen)" if restart_needed and not st.get("restart_confirmed") else ""
    if done and not (ever and n < N):
        return VERIFIED
    if ever:
        return f"{VERIFIED} · LIVE MATURITY {n}/{N}"
    return f"LIVE {n}/{N}{tail}"


def evaluate_item(item, state, src, now):
    st = {"n": 0, "last_cycle": None, "history": [], "restart_confirmed": False, "ever_verified": False}
    st.update(json.loads(json.dumps(state or {})))
    res = {"id": item["id"], "lq": item.get("lq"), "N": item["N"], "cycle_kind": item["cycle_kind"]}
    probe = item["probe"]
    if item.get("status") == "pending_fix" or not item.get("live_since"):
        res["verdict"] = "PENDING FIX · not live, nothing counted"
        return st, res
    if probe["kind"] == "unknown":
        res["verdict"] = f"UNKNOWN ({probe.get('reason', 'not proven')})"
        return st, res
    since = parse_et(item["live_since"])
    seen = {h["id"] for h in st["history"]}
    restart_needed = probe["kind"] == "service"
    if probe["kind"] == "service":
        s = src.service_reader(probe["unit"])
        if s is None:
            res["verdict"] = f"UNKNOWN (cannot read {probe['unit']})"
            return st, res
        cid = f"svc:{probe['unit']}:{now.astimezone(ET).strftime('%Y%m%dT%H')}"
        if now >= since and cid not in seen:
            healthy = s["active"] == "active" and probe.get("release_match", item.get("fix_commit") or "") in s["cwd"]
            if st.get("baseline_active_enter") is None:
                st["baseline_active_enter"] = s["active_enter"]
            restarted = healthy and s["active_enter"] != st["baseline_active_enter"]
            _apply(st, cid, now, healthy, f"active={s['active']} cwd={os.path.basename(s['cwd'])}")
            if restarted:
                st["baseline_active_enter"] = s["active_enter"]
                st["restart_confirmed"] = True
                st["history"][-1]["note"] += " restart-event"
    else:
        fn = _n8n_cycles if probe["kind"] == "n8n_receipts" else _last_receipt_cycles
        for cid, at, ok, note in fn(src, probe["lane"], since):
            if cid not in seen:
                _apply(st, cid, at, ok, note)
    res["n"] = st["n"]
    res["verdict"] = _verdict(item, st, restart_needed)
    res["last_cycle"] = st["last_cycle"]
    return st, res


def evaluate(registry, state, src, now):
    new, results = {}, []
    for item in registry["items"]:
        st, res = evaluate_item(item, state.get(item["id"]), src, now)
        new[item["id"]] = st
        results.append(res)
    return new, results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--state", required=True, help="counter state JSON (its own file; read, and written with --write-state)")
    ap.add_argument("--write-state", action="store_true", help="persist counted cycles; default is a read-only run")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    reg = load_registry(a.registry)
    sp = Path(a.state)
    state = json.loads(sp.read_text()) if sp.exists() else {}
    now = dt.datetime.now(ET)
    new, results = evaluate(reg, state, Sources(), now)
    if a.write_state:
        sp.parent.mkdir(parents=True, exist_ok=True)
        tmp = sp.with_suffix(".tmp")
        tmp.write_text(json.dumps(new, indent=1, sort_keys=True))
        os.replace(tmp, sp)
    if a.json:
        print(json.dumps(results, indent=1))
    else:
        print(f"LIVE MATURITY @ {now.strftime('%Y-%m-%d %H:%M ET')}  ({'state written' if a.write_state else 'read-only'})")
        for r in results:
            print(f"  {r['id']:<34} {r['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
