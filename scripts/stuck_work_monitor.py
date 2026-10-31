#!/usr/bin/env python3
"""Stuck-work monitor: find stuck locks, processes, units, damaged state files, stalled queues, open n8n breakers,
stale heartbeats and silent lanes; page once per item per day; run the safe heals; hand code defects to the Claude
Code fixer.

Operator 2026-10-31 (verbatim): "validate all stuck agents and processes fix montior and make auto healings with
claude code". Decisions live in ``scripts/lib/stuck_work.py`` (pure); this file only collects facts and acts.

  python3 scripts/stuck_work_monitor.py                 # dry run (default): print findings and plans, write nothing
  python3 scripts/stuck_work_monitor.py --json          # same, JSON
  python3 scripts/stuck_work_monitor.py --apply         # write the receipt; send / heal / hand off only where
                                                        # config/stuck_work_monitor.json switches them on

Never: ending a process (AGENTS.md §28.1 — process_reaper.py with measured caps), a broker call, a credential read,
a DB write (the session is read-only). Exit 0 = no finding, 3 = findings (scripts/lib/monitor_exit_codes.py).
"""

from __future__ import annotations

import argparse
import glob
from fnmatch import fnmatch
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import stuck_work as SW  # noqa: E402
from lib.monitor_exit_codes import EXIT_FINDING, EXIT_OK  # noqa: E402

ET = ZoneInfo("America/New_York")
CONFIG_PATH = PROJECT_ROOT / "config" / "stuck_work_monitor.json"


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != "StuckWorkMonitor@v1":
        raise ValueError(f"{path}: expected schema StuckWorkMonitor@v1")
    return cfg


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _expand(p: str, project: Path, state: Path) -> str:
    return p.replace("{project}", str(project)).replace("{state}", str(state))


def _run(argv: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- collectors (read-only)
_BOOT = None


def _boot_time() -> float:
    global _BOOT
    if _BOOT is None:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                _BOOT = float(line.split()[1])
                break
    return _BOOT or 0.0


def collect_procs() -> dict[int, dict]:
    """pid -> {args, stat, wchan, uid, started} for every process this user can see (from /proc)."""
    hz = os.sysconf("SC_CLK_TCK")
    me = os.getuid()
    out: dict[int, dict] = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            st = d.stat()
            if st.st_uid != me:
                continue
            raw = (d / "stat").read_text()
            fields = raw[raw.rindex(")") + 2 :].split()
            start = _boot_time() + int(fields[19]) / hz
            out[int(d.name)] = {
                "args": (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip(),
                "stat": fields[0],
                "wchan": (d / "wchan").read_text().strip(),
                "uid": st.st_uid,
                "started": datetime.fromtimestamp(start, tz=timezone.utc),
            }
        except (OSError, ValueError, IndexError):
            continue
    return out


def collect_locks() -> list[dict]:
    rc, out = _run(["lslocks", "--json", "-o", "COMMAND,PID,TYPE,MODE,BLOCKER,PATH"])
    if rc != 0:
        return []
    try:
        return json.loads(out).get("locks") or []
    except ValueError:
        return []


def _ts(text: str) -> datetime | None:
    text = (text or "").strip()
    if not text or text == "n/a":
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt
        except ValueError:
            continue
    try:
        dt = datetime.strptime(" ".join(text.split()[:3]), "%a %Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=ET)
    except ValueError:
        return None


def collect_units() -> list[dict]:
    rc, out = _run(["systemctl", "--user", "list-units", "--all", "--no-legend", "--plain", "--type=service"])
    if rc != 0:
        return []
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] in ("activating", "failed"):
            names.append(parts[0])
    units = []
    for name in names:
        rc, show = _run(
            [
                "systemctl",
                "--user",
                "show",
                name,
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "Result",
                "-p",
                "StateChangeTimestamp",
                "-p",
                "TimeoutStartUSec",
            ]
        )
        props = dict(line.split("=", 1) for line in show.splitlines() if "=" in line)
        tail = ""
        if props.get("ActiveState") == "failed":
            _, tail = _run(["journalctl", "--user", "-u", name, "-n", "15", "--no-pager", "-o", "cat"])
        units.append(
            {
                "unit": name,
                "active": props.get("ActiveState"),
                "sub": props.get("SubState"),
                "result": props.get("Result"),
                "since": _ts(props.get("StateChangeTimestamp", "")),
                "timeout_start": props.get("TimeoutStartUSec"),
                "journal_tail": tail,
            }
        )
    return units


def _tail_bytes(path: Path, n: int) -> bytes:
    with path.open("rb") as fh:
        size = fh.seek(0, 2)
        fh.seek(max(0, size - n))
        return fh.read()


def collect_files(cfg: dict, project: Path, state: Path, locks: list[dict]) -> list[dict]:
    held = {str(row.get("path") or "") for row in locks}
    f = cfg["files"]
    out = []
    for raw in f.get("jsonl") or []:
        p = Path(_expand(raw, project, state))
        if not p.is_file():
            continue
        real = p.resolve()
        st = real.stat()
        out.append(
            {
                "path": str(real),
                "kind": "jsonl",
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                "tail": SW.tail_state(_tail_bytes(real, int(f["tail_bytes"]))) if st.st_size else {"ok": True},
                "locked": str(real) in held or f"{real}.lock" in held,
            }
        )
    for row in f.get("state") or []:
        p = Path(_expand(row["path"], project, state))
        if not p.is_file():
            continue
        st = p.stat()
        backup = None
        if st.st_size == 0 and row.get("backups"):
            for cand in sorted(glob.glob(_expand(row["backups"], project, state)), key=os.path.getmtime, reverse=True):
                try:
                    if os.path.getsize(cand) > 0:
                        json.loads(Path(cand).read_text(encoding="utf-8"))
                        backup = cand
                        break
                except (OSError, ValueError):
                    continue
        out.append(
            {
                "path": str(p),
                "kind": "state",
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                "backup": backup,
            }
        )
    return out


def _aware(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def collect_db(cfg: dict) -> tuple[list[dict], list[dict], str | None]:
    """(queue rows, heartbeat rows, error). Read-only session; every SQL in config must be a SELECT."""
    try:
        from lib.cio_market_context_state import connect_trade_ai_readonly

        conn = connect_trade_ai_readonly()
    except Exception as exc:  # noqa: BLE001 — reported as unknown, never as zero
        err = f"{type(exc).__name__}: {exc}"
        return [{"name": q["name"], "error": err} for q in cfg.get("queues") or []], [], err
    queues, beats = [], []
    with conn.cursor() as cur:
        for q in cfg.get("queues") or []:
            row = {"name": q["name"]}
            try:
                for key, sql in (
                    ("pending", q["pending_sql"]),
                    ("last_done", q["last_done_sql"]),
                    ("stuck_processing", q.get("stuck_sql")),
                ):
                    if not sql:
                        continue
                    if not sql.lstrip().upper().startswith("SELECT"):
                        raise ValueError(f"{q['name']}.{key}: only SELECT is allowed")
                    cur.execute(sql)
                    row[key] = _aware(cur.fetchone()[0])
            except Exception as exc:  # noqa: BLE001
                row = {"name": q["name"], "error": f"{type(exc).__name__}: {exc}"}
            queues.append(row)
        hb = cfg.get("heartbeats") or {}
        if hb.get("sql"):
            try:
                cur.execute(hb["sql"])
                cols = [d[0] for d in cur.description]
                beats = [
                    {**dict(zip(cols, r)), "last_seen": _aware(dict(zip(cols, r)).get("last_seen"))}
                    for r in cur.fetchall()
                ]
            except Exception as exc:  # noqa: BLE001
                beats = [{"agent_id": "heartbeat-query", "last_seen": None, "status": f"unknown: {exc}"}]
    conn.close()
    return queues, beats, None


def _parse_iso(s):
    if not s:
        return None
    try:
        return _aware(datetime.fromisoformat(str(s).replace("Z", "+00:00")))
    except ValueError:
        return None


def collect_breakers(cfg: dict, state: Path) -> list[dict]:
    path = state / cfg["breakers"]["ledger_rel"]
    if not path.is_file():
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        rows = con.execute("SELECT lane_id, opened_at, consecutive, released_at FROM breakers").fetchall()
    finally:
        con.close()
    return [{"lane_id": r[0], "opened_at": _parse_iso(r[1]), "consecutive": r[2], "released_at": r[3]} for r in rows]


def collect_lanes(cfg: dict, project: Path) -> list[dict]:
    reg = json.loads((project / cfg["lanes"]["registry_rel"]).read_text(encoding="utf-8"))
    out = []
    for lane in reg.get("lanes") or []:
        sig = lane.get("output_signal") or {}
        if (
            lane.get("state") != "ACTIVE"
            or not isinstance(sig, dict)
            or sig.get("kind") not in ("file_mtime", "json_key")
        ):
            continue
        p = project / sig["path"]
        at = None
        try:
            if sig["kind"] == "file_mtime":
                at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            else:
                at = _parse_iso((json.loads(p.read_text(encoding="utf-8")) or {}).get(sig["key"]))
        except (OSError, ValueError, AttributeError):
            at = None
        out.append(
            {
                "lane_id": lane["lane_id"],
                "cadence_hours": lane.get("expected_cadence_hours"),
                "signal_at": at,
                "signal": sig,
                "state_since": _parse_iso(lane.get("state_since")),
            }
        )
    return out


def collect_unit_releases(cfg: dict) -> tuple[list[dict], str, datetime | None]:
    """(active units with their resolved cwd, CURRENT's target, CURRENT's promote time = the symlink's own mtime)."""
    c = cfg["stale_release"]
    cur_link = Path(os.path.expanduser(c["current_link"]))
    try:
        current = str(cur_link.resolve())
        promoted = datetime.fromtimestamp(cur_link.lstat().st_mtime, tz=timezone.utc)
    except OSError:
        return [], "", None
    rc, out = _run(["systemctl", "--user", "list-units", "--state=active", "--no-legend", "--plain", "--type=service"])
    units = []
    for line in out.splitlines() if rc == 0 else []:
        name = line.split()[0] if line.split() else ""
        if not name:
            continue
        _, pid = _run(["systemctl", "--user", "show", name, "-p", "MainPID", "--value"])
        pid = pid.strip()
        if not pid.isdigit() or pid == "0":
            continue
        try:
            cwd = os.path.realpath(f"/proc/{pid}/cwd")
        except OSError:
            continue
        units.append({"unit": name, "pid": int(pid), "cwd": cwd})
    return units, current, promoted


# ---------------------------------------------------------------- evaluate
def evaluate(cfg: dict, *, now: datetime, project: Path, state: Path) -> dict:
    procs = collect_procs()
    locks = collect_locks()
    findings = SW.lock_findings(locks, procs, cfg, now)
    seen_pids = {f["evidence"]["pid"] for f in findings}
    findings += SW.process_findings(procs, cfg, now, seen_pids)
    findings += SW.unit_findings(collect_units(), cfg, now)
    findings += SW.file_findings(collect_files(cfg, project, state, locks), cfg, now)
    queues, beats, db_err = collect_db(cfg)
    findings += SW.queue_findings(queues, cfg, now)
    findings += SW.heartbeat_findings(beats, cfg, now)
    findings += SW.breaker_findings(collect_breakers(cfg, state), cfg, now)
    findings += SW.lane_findings(collect_lanes(cfg, project), cfg, now)
    units, current, promoted = collect_unit_releases(cfg)
    findings += SW.stale_release_findings(units, current, promoted, cfg, now)
    return {
        "schema": "StuckWorkReceipt@v1",
        "at": SW._iso(now),
        "db_error": db_err,
        "findings": findings,
        "counts": {c: sum(1 for f in findings if f["class"] == c) for c in SW.CLASSES},
    }


# ---------------------------------------------------------------- side effects (only with --apply)
def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def restart_unit(unit: str) -> dict:
    """Restart one allowlisted unit and read its cwd back (activeness cannot detect a stale release)."""
    cfg = load_config()
    if unit not in set(cfg["stale_release"].get("restart_allowlist") or []) or any(
        fnmatch(unit, g) for g in cfg["stale_release"].get("never_restart_globs") or []
    ):
        return {"action": "restart", "unit": unit, "result": "refused", "why": "not allowlisted or never-restart"}
    rc, _ = _run(["systemctl", "--user", "restart", unit], timeout=60)
    time.sleep(3)
    _, pid = _run(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"])
    cwd = os.path.realpath(f"/proc/{pid.strip()}/cwd") if pid.strip().isdigit() and pid.strip() != "0" else ""
    current = str(Path(os.path.expanduser(cfg["stale_release"]["current_link"])).resolve())
    ok = rc == 0 and cwd == current
    return {
        "action": "restart",
        "unit": unit,
        "result": "restarted" if ok else "error",
        "cwd": cwd,
        "current": current,
        "rc": rc,
    }


def do_heal(plan: dict, state: Path, project: Path) -> dict:
    """Archive first, then act. Re-checks the condition on the live bytes so a heal never acts on a stale plan."""
    if plan["action"] == "restart":
        return restart_unit(plan["unit"])
    src = Path(plan["path"])
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    arch = Path(_expand(plan["archive_dir"], project, state)) / stamp / src.name
    arch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, arch)
    if plan["action"] == "repair_tail":
        data = src.read_bytes()
        fixed = SW.repaired_bytes(data)
        if fixed is None:
            return {**plan, "result": "skipped", "why": "condition no longer holds or not safe", "archive": str(arch)}
        _atomic_write(src, fixed)
        return {**plan, "result": "repaired", "dropped_bytes": len(data) - len(fixed), "archive": str(arch)}
    if plan["action"] == "restore_backup":
        if src.stat().st_size != 0:
            return {**plan, "result": "skipped", "why": "target no longer empty", "archive": str(arch)}
        _atomic_write(src, Path(plan["from"]).read_bytes())
        return {**plan, "result": "restored", "archive": str(arch)}
    return {**plan, "result": "skipped", "why": "unknown action"}


def send(message: str, priority: str, cfg: dict) -> tuple[bool, str | None]:
    try:
        from telegram_alert import send_telegram

        ok = send_telegram(
            message, priority=priority, dedupe_minutes=0, producer=cfg["producer"], message_class=cfg["message_class"]
        )
        return bool(ok), None if ok else "send_telegram returned falsy"
    except Exception as exc:  # noqa: BLE001 — surfaced in the receipt and the exit code, never swallowed
        return False, f"{type(exc).__name__}: {exc}"


def apply(receipt: dict, cfg: dict, *, now: datetime, project: Path, state: Path) -> dict:
    day = now.astimezone(ET).date().isoformat()
    st_path = state / cfg["state_rel"]
    try:
        st = json.loads(st_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    sent = st.get("sent") or {}
    healed = st.get("healed") or {}
    handed = st.get("handed_off") or {}
    actions: dict = {"alerts": None, "heals": [], "fixer": [], "errors": []}

    due = SW.due_alerts(receipt["findings"], sent, day)
    if due and cfg.get("alerts_enabled"):
        prio = "P1" if any(f["severity"] == "P1" for f in due) else "P2"
        ok, err = send(SW.render(due, now.astimezone(ET).strftime("%a %m-%d %H:%M ET")), prio, cfg)
        actions["alerts"] = {"sent": ok, "priority": prio, "items": len(due), "error": err}
        if ok:
            for f in due:
                sent[f["dedupe_key"]] = day
        else:
            actions["errors"].append(err)
    elif due:
        actions["alerts"] = {"sent": False, "why": "alerts_enabled is false", "items": len(due)}

    if cfg.get("heals_enabled"):
        for f in receipt["findings"]:
            plan = SW.heal_plan(f, cfg)
            if not plan or healed.get(f["dedupe_key"]) == f.get("since"):
                continue
            if len(actions["heals"]) >= int(cfg["heals"]["max_per_tick"]):
                break
            try:
                res = do_heal(plan, state, project)
            except OSError as exc:
                res = {**plan, "result": "error", "why": f"{type(exc).__name__}: {exc}"}
                actions["errors"].append(res["why"])
            healed[f["dedupe_key"]] = f.get("since")
            actions["heals"].append(res)

    if cfg.get("fixer_intake_enabled"):
        store = state / cfg["fixer_defects_rel"]
        for f in receipt["findings"]:
            rec = SW.fixer_defect(f, now, receipt=str(state / cfg["receipt_rel"]))
            if not rec or rec["code_defect"]["defect_id"] in handed:
                continue
            store.parent.mkdir(parents=True, exist_ok=True)
            with store.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            handed[rec["code_defect"]["defect_id"]] = SW._iso(now)
            actions["fixer"].append(rec["code_defect"]["defect_id"])

    _atomic_write(st_path, json.dumps({"sent": sent, "healed": healed, "handed_off": handed}, indent=1).encode())
    full = {**receipt, "actions": actions}
    _atomic_write(state / cfg["receipt_rel"], json.dumps(full, indent=1, default=str).encode())
    with (state / cfg["history_rel"]).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": receipt["at"], "counts": receipt["counts"], "actions": actions}, default=str) + "\n")
    return full


def plans(receipt: dict, cfg: dict, now: datetime, state: Path) -> dict:
    return {
        "heals": [p for p in (SW.heal_plan(f, cfg) for f in receipt["findings"]) if p],
        "fixer": [
            r["code_defect"]
            for r in (SW.fixer_defect(f, now, receipt=str(state / cfg["receipt_rel"])) for f in receipt["findings"])
            if r
        ],
        "alert_preview": SW.render(
            SW.due_alerts(receipt["findings"], {}, ""), now.astimezone(ET).strftime("%a %m-%d %H:%M ET")
        )
        if receipt["findings"]
        else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write receipt/state; send/heal/hand off per config")
    ap.add_argument("--dry-run", action="store_true", help="default: print only, write nothing")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--project-root", default=None, help="read the lane registry and {project} paths from here")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    now = datetime.now(timezone.utc)
    project, state = Path(a.project_root).resolve() if a.project_root else PROJECT_ROOT, state_root()
    receipt = evaluate(cfg, now=now, project=project, state=state)
    if a.apply and not a.dry_run:
        out = apply(receipt, cfg, now=now, project=project, state=state)
        rc = EXIT_FINDING if out["findings"] else EXIT_OK
        if out["actions"]["errors"]:
            rc = 1
    else:
        out = {
            **receipt,
            "mode": "DRY RUN — nothing written, sent, healed or handed off",
            "would": plans(receipt, cfg, now, state),
            "switches": {k: bool(cfg.get(k)) for k in ("alerts_enabled", "heals_enabled", "fixer_intake_enabled")},
        }
        rc = EXIT_FINDING if receipt["findings"] else EXIT_OK
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(
            f"[stuck-work] {out['at']} findings={len(out['findings'])} db_error={out['db_error']} "
            f"{out.get('mode', 'APPLY')}"
        )
        for f in out["findings"]:
            age = f"{f['age_min'] / 60:.1f}h" if f.get("age_min") is not None else "?"
            print(f"  {f['severity']} {f['class']:<22} {age:>7} heal={f['heal']:<14} lane={f.get('lane')} {f['item']}")
        if "would" in out:
            for p in out["would"]["heals"]:
                print(f"  would heal: {p['action']} {p['path']}")
            for d in out["would"]["fixer"]:
                print(f"  would hand to the Claude Code fixer: {d['defect_id']} ({d['failure_kind']})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
