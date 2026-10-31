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
import contextlib
import fcntl
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
    """pid -> {args, stat, ppid, wchan, uid, started, cpu_s, cwd, deleted_open} for this user's processes (/proc)."""
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
            try:
                cwd = os.readlink(d / "cwd")
            except OSError:
                cwd = ""
            deleted = []
            try:
                for fd in (d / "fd").iterdir():
                    try:
                        target = os.readlink(fd)
                        if target.endswith(" (deleted)") and target.startswith("/"):
                            deleted.append({"path": target, "size": os.stat(fd).st_size})
                    except OSError:
                        continue
            except OSError:
                pass
            out[int(d.name)] = {
                "args": (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip(),
                "stat": fields[0],
                "ppid": int(fields[1]),
                "wchan": (d / "wchan").read_text().strip(),
                "uid": st.st_uid,
                "started": datetime.fromtimestamp(start, tz=timezone.utc),
                "cpu_s": (int(fields[11]) + int(fields[12])) / hz,
                "cwd": cwd,
                "deleted_open": deleted,
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
    """Every user service: state, exit status, type, start timeout and the last run's wall/CPU time (one
    ``systemctl show`` call for all units)."""
    rc, out = _run(["systemctl", "--user", "list-units", "--all", "--no-legend", "--plain", "--type=service"])
    if rc != 0:
        return []
    names = [ln.split()[0] for ln in out.splitlines() if ln.split()]
    if not names:
        return []
    props = [
        "Id",
        "ActiveState",
        "SubState",
        "Result",
        "StateChangeTimestamp",
        "TimeoutStartUSec",
        "Type",
        "ExecMainStatus",
        "ExecMainStartTimestampMonotonic",
        "ExecMainExitTimestampMonotonic",
        "CPUUsageNSec",
    ]
    argv = ["systemctl", "--user", "show", *names]
    for p in props:
        argv += ["-p", p]
    _, show = _run(argv, timeout=60)
    units = []
    for block in show.split("\n\n"):
        kv = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if not kv.get("Id"):
            continue
        try:
            t0, t1 = (
                int(kv.get("ExecMainStartTimestampMonotonic") or 0),
                int(kv.get("ExecMainExitTimestampMonotonic") or 0),
            )
            wall = (t1 - t0) / 1e6 if t0 and t1 > t0 else None
        except ValueError:
            wall = None
        try:
            cpu = int(kv["CPUUsageNSec"]) / 1e9 if kv.get("CPUUsageNSec", "").isdigit() else None
        except ValueError:
            cpu = None
        tail = ""
        if kv.get("ActiveState") == "failed":
            _, tail = _run(["journalctl", "--user", "-u", kv["Id"], "-n", "15", "--no-pager", "-o", "cat"])
        units.append(
            {
                "unit": kv["Id"],
                "active": kv.get("ActiveState"),
                "sub": kv.get("SubState"),
                "result": kv.get("Result"),
                "since": _ts(kv.get("StateChangeTimestamp", "")),
                "timeout_start": kv.get("TimeoutStartUSec"),
                "type": kv.get("Type"),
                "exit_status": kv.get("ExecMainStatus"),
                "last_wall_s": wall,
                "last_cpu_s": cpu,
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
                "tail": SW.tail_state(
                    _tail_bytes(real, int(f["tail_bytes"])), whole_file=st.st_size <= int(f["tail_bytes"])
                )
                if st.st_size
                else {"ok": True},
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
                "backup_mtime": datetime.fromtimestamp(os.path.getmtime(backup), tz=timezone.utc) if backup else None,
                "locked": str(p) in held or f"{p}.lock" in held,
            }
        )
    return out


def _aware(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def collect_db(cfg: dict) -> tuple[list[dict], list[dict], str | None, bool | None]:
    """(queue rows, heartbeat rows, error, postgres in recovery). Read-only session; every SQL is a SELECT."""
    try:
        from lib.cio_market_context_state import connect_trade_ai_readonly

        conn = connect_trade_ai_readonly()
    except Exception as exc:  # noqa: BLE001 — reported as unknown, never as zero
        err = f"{type(exc).__name__}: {exc}"
        return [{"name": q["name"], "error": err} for q in cfg.get("queues") or []], [], err, None
    queues, beats, recovery = [], [], None
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT pg_is_in_recovery()")
            recovery = bool(cur.fetchone()[0])
        except Exception:  # noqa: BLE001 — unknown, reported as None
            recovery = None
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
    return queues, beats, None, recovery


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
    return [
        {
            "lane_id": r[0],
            "opened_at": _parse_iso(r[1]),
            "raw_opened_at": r[1],
            "consecutive": r[2],
            "released_at": r[3],
        }
        for r in rows
    ]


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
        raw_path = str(sig["path"])
        p = Path(os.path.expanduser(raw_path)) if raw_path.startswith("~") else project / raw_path
        at, missing = None, None
        if not p.exists():
            missing = "signal file does not exist"
        else:
            try:
                if sig["kind"] == "file_mtime":
                    at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                else:
                    doc = json.loads(p.read_text(encoding="utf-8")) or {}
                    if sig["key"] not in doc:
                        missing = f"key {sig['key']!r} absent"
                    at = _parse_iso(doc.get(sig["key"]))
            except (OSError, ValueError, AttributeError) as exc:
                missing = f"unreadable: {type(exc).__name__}"
        out.append(
            {
                "lane_id": lane["lane_id"],
                "cadence_hours": lane.get("expected_cadence_hours"),
                "signal_at": at,
                "signal": sig,
                "state_since": _parse_iso(lane.get("state_since")),
                "signal_missing": missing,
                "stage": (lane.get("scheduler") or {}).get("stage"),
            }
        )
    return out


def collect_zero_byte(cfg: dict, project: Path, state: Path, already: set[str]) -> list[dict]:
    """Class 7 beyond the critical list: every zero-byte JSON under the scan roots (one P3 summary)."""
    z = cfg["files"].get("zero_byte_scan") or {}
    hits = []
    for root in z.get("roots") or []:
        base = Path(_expand(root, project, state))
        for p in base.rglob("*.json") if base.is_dir() else []:
            try:
                if (
                    p.is_file()
                    and p.stat().st_size == 0
                    and str(p) not in already
                    and not any(fnmatch(p.name, g) for g in z.get("ignore_globs") or [])
                ):
                    hits.append(str(p))
            except OSError:
                continue
    return sorted(hits)


def collect_ledger_extras(cfg: dict, state: Path, open_breakers: dict) -> tuple[dict, list, list]:
    """(probes since open per open breaker, poison items, exit-0 output_unverifiable counts) — ledger opened ro."""
    path = state / cfg["breakers"]["ledger_rel"]
    if not path.is_file():
        return {}, [], []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        probes = {}
        for lane, opened in open_breakers.items():
            probes[lane] = con.execute(
                "SELECT count(*) FROM runs WHERE lane_id = ? AND requested_at > ?", (lane, opened)
            ).fetchone()[0]
        poison = [
            {"lane_id": r[0], "slot_key": r[1], "attempts": r[2], "last_reason": r[3]}
            for r in con.execute(
                "SELECT lane_id, slot_key, max(attempts), max(last_reason) FROM dead_letters "
                "WHERE released_at IS NULL GROUP BY lane_id, slot_key HAVING max(attempts) >= ?",
                (int(cfg["breakers"]["poison_min"]),),
            ).fetchall()
        ]
        since = datetime.now(timezone.utc).timestamp() - 86400 * float(cfg["breakers"]["unverifiable_days"])
        unver = [
            {"lane_id": r[0], "count": r[1]}
            for r in con.execute(
                "SELECT lane_id, count(*) FROM run_outcomes WHERE reason = 'output_unverifiable' AND exit_code = 0 "
                "AND recorded_at >= ? GROUP BY lane_id",
                (datetime.fromtimestamp(since, tz=timezone.utc).isoformat(),),
            ).fetchall()
        ]
    finally:
        con.close()
    return probes, poison, unver


def collect_windows(cfg: dict, project: Path, now: datetime) -> tuple[list[dict], bool]:
    """Market windows (class 13): today's due time per lane and its signal time; trading day from the NYSE calendar."""
    try:
        from lib.cio_market_session import is_trading_day

        trading = bool(is_trading_day(now))
    except Exception:  # noqa: BLE001 — unknown calendar: weekday rule, stated in the receipt
        trading = now.astimezone(ET).weekday() < 5
    today = now.astimezone(ET).date()
    rows = []
    for w in cfg.get("market_windows") or []:
        hh, mm = (int(x) for x in w["due_et"].split(":"))
        due = datetime(today.year, today.month, today.day, hh, mm, tzinfo=ET).astimezone(timezone.utc)
        p = project / w["signal_path"]
        try:
            at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            at = None
        rows.append(
            {
                "lane": w["lane"],
                "due": due,
                "grace_min": w["grace_min"],
                "signal_at": at,
                "severity": w.get("severity", "P1"),
            }
        )
    return rows, trading


def collect_claims(cfg: dict, state: Path) -> list[dict]:
    out = []
    for f in glob.glob(str(state / cfg["claims"]["dir_rel"] / "*.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("schema") == "AgentClaim@v1":
            out.append(
                {
                    "claim_id": d.get("claim_id"),
                    "status": d.get("status"),
                    "branch": d.get("branch"),
                    "heartbeat_at": _parse_iso(d.get("heartbeat_at") or d.get("started_at")),
                }
            )
    return out


def collect_heal_counts(cfg: dict, state: Path, project: Path, now: datetime) -> dict[str, int]:
    """Heals attempted in the last 24 h per item: this monitor's history plus other healers' ledgers."""
    counts: dict[str, int] = {}
    cut = now.timestamp() - 86400
    hist = state / cfg["history_rel"]
    for path, key_of in [(hist, None)] + [
        (Path(_expand(x["path"], project, state)), x) for x in cfg["heals"].get("foreign_ledgers") or []
    ]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
        except OSError:
            continue
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            at = _parse_iso(d.get("at") or d.get("ts"))
            if at is None or at.timestamp() < cut:
                continue
            if key_of is None:
                for h in (d.get("actions") or {}).get("heals") or []:
                    counts[str(h.get("path"))] = counts.get(str(h.get("path")), 0) + 1
            elif key_of["match"] in json.dumps(d):
                k = str(d.get(key_of["key_field"]) or key_of["match"])
                counts[k] = counts.get(k, 0) + 1
    return counts


def collect_resources(cfg: dict) -> dict:
    res: dict = {"disk_pct": {}}
    for m in cfg["resources"]["mounts"]:
        try:
            u = shutil.disk_usage(m)
            res["disk_pct"][m] = round(100.0 * u.used / u.total, 1)
        except OSError:
            continue
    try:
        mem = dict(ln.split(":", 1) for ln in Path("/proc/meminfo").read_text().splitlines())
        tot, free = int(mem["SwapTotal"].split()[0]), int(mem["SwapFree"].split()[0])
        res["swap_pct"] = round(100.0 * (tot - free) / tot, 1) if tot else None
    except (OSError, KeyError, ValueError):
        res["swap_pct"] = None
    return res


def collect_pid_locks(cfg: dict, project: Path, state: Path, locks: list[dict]) -> list[dict]:
    """pid-file locks on the configured globs: JSON {"pid": N} or a bare integer."""
    held = {str(r.get("path") or "") for r in locks}
    out = []
    for g in cfg["stale_locks"]["globs"]:
        for f in glob.glob(_expand(g, project, state)):
            try:
                txt = Path(f).read_text(encoding="utf-8").strip()
                pid = (json.loads(txt) or {}).get("pid") if txt.startswith("{") else int(txt.split()[0])
                pid = int(pid)
            except (OSError, ValueError, TypeError, AttributeError, IndexError):
                continue
            out.append(
                {
                    "path": f,
                    "pid": pid,
                    "pid_alive": Path(f"/proc/{pid}").exists(),
                    "held": f in held,
                    "mtime": datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc),
                }
            )
    return out


def collect_ledger_done(cfg: dict, state: Path, lanes: list[str]) -> dict[str, datetime | None]:
    """Newest RUN_DONE per lane from the coordination ledger (read-only) — liveness for shadow/canary lanes."""
    path = state / cfg["breakers"]["ledger_rel"]
    if not path.is_file() or not lanes:
        return {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        marks = ",".join("?" * len(lanes))
        rows = con.execute(
            f"SELECT lane_id, max(finished_at) FROM runs WHERE state = 'RUN_DONE' AND lane_id IN ({marks})"
            " GROUP BY lane_id",
            lanes,
        ).fetchall()
    finally:
        con.close()
    return {r[0]: _parse_iso(r[1]) for r in rows}


def collect_quarantined(cfg: dict, state: Path) -> list[dict]:
    """Items held by scripts/lib/poison_quarantine.py: one store per lane, ``<poison_quarantine_dir_rel>/<lane>.json``
    (#2380). A store that does not parse is itself reported (as a quarantine of item ``<store unreadable>``), never
    read as empty."""
    out = []
    for f in sorted((state / cfg["poison_quarantine_dir_rel"]).glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            held = (doc or {}).get("quarantined") or {}
        except (OSError, ValueError) as exc:
            out.append(
                {
                    "lane": f.stem,
                    "item": "<store unreadable>",
                    "at": None,
                    "consecutive_failures": None,
                    "reason": f"{type(exc).__name__}: {exc}"[:200],
                }
            )
            continue
        for item, rec in held.items():
            rec = rec or {}
            out.append(
                {
                    "lane": f.stem,
                    "item": item,
                    "at": _parse_iso(rec.get("at")),
                    "consecutive_failures": rec.get("consecutive_failures"),
                    "reason": rec.get("reason"),
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
    d_pids = [pid for pid, p in procs.items() if str(p.get("stat") or "").startswith("D")]
    if d_pids:  # false-positive guard: D state must still hold on a second sample
        time.sleep(float(cfg["processes"].get("d_resample_s", 2)))
        for pid in d_pids:
            try:
                raw = Path(f"/proc/{pid}/stat").read_text()
                procs[pid]["d_confirmed"] = raw[raw.rindex(")") + 2 :].split()[0].startswith("D")
            except (OSError, ValueError):
                procs[pid]["d_confirmed"] = False
    locks = collect_locks()
    findings = SW.lock_findings(locks, procs, cfg, now)
    seen_pids = {f["evidence"]["pid"] for f in findings}
    findings += SW.process_findings(procs, cfg, now, seen_pids)
    findings += SW.proc_extra_findings({k: v for k, v in procs.items() if k not in seen_pids}, cfg, now)
    units = collect_units()
    findings += SW.unit_findings(units, cfg, now)
    findings += SW.unit_lint_findings(units, cfg, now)
    files = collect_files(cfg, project, state, locks)
    findings += SW.file_findings(files, cfg, now)
    zb = collect_zero_byte(cfg, project, state, {f["path"] for f in files})
    if zb:
        findings.append(
            SW.finding(
                "zero_byte_state",
                f"{len(zb)} other zero-byte JSON files",
                key="other_zero_byte_json",
                since=None,
                now=now,
                severity="P3",
                heal="page",
                evidence={"files": zb[:60], "count": len(zb)},
            )
        )
    lanes = collect_lanes(cfg, project)
    stages = set(cfg["lanes"].get("ledger_liveness_stages") or [])
    done = collect_ledger_done(cfg, state, [r["lane_id"] for r in lanes if r.get("stage") in stages])
    for r in lanes:
        r["ledger_done_at"] = done.get(r["lane_id"])
    lane_at = {r["lane_id"]: r.get("signal_at") for r in lanes}
    queues, beats, db_err, pg_recovery = collect_db(cfg)
    for q, qc in zip(queues, cfg.get("queues") or []):
        at = lane_at.get(qc.get("consumer_lane") or "")
        q["consumer_fresh"] = bool(at and (now - at).total_seconds() < 3600 * float(qc.get("stale_hours", 24)))
    findings += SW.queue_findings(queues, cfg, now)
    findings += SW.heartbeat_findings(beats, cfg, now)
    breakers = collect_breakers(cfg, state)
    open_b = {r["lane_id"]: r["raw_opened_at"] for r in breakers if r.get("released_at") is None}
    probes, poison, unver = collect_ledger_extras(cfg, state, open_b)
    findings += SW.breaker_findings(breakers, cfg, now, probes)
    findings += SW.ledger_findings(poison, unver, cfg, now)
    findings += SW.lane_findings(lanes, cfg, now)
    findings += SW.quarantine_findings(collect_quarantined(cfg, state), now)
    windows, trading = collect_windows(cfg, project, now)
    findings += SW.missed_window_findings(windows, now, trading)
    findings += SW.claim_findings(collect_claims(cfg, state), cfg, now)
    heal_counts = collect_heal_counts(cfg, state, project, now)
    findings += SW.heal_loop_findings(heal_counts, cfg, now)
    res = collect_resources(cfg)
    res["pg_in_recovery"] = pg_recovery
    findings += SW.precursor_findings(res, cfg, now)
    findings += SW.stale_lock_findings(collect_pid_locks(cfg, project, state, locks), now)
    units_rel, current, promoted = collect_unit_releases(cfg)
    findings += SW.stale_release_findings(units_rel, current, promoted, cfg, now)
    return {
        "schema": "StuckWorkReceipt@v1",
        "at": SW._iso(now),
        "db_error": db_err,
        "trading_day": trading,
        "heal_counts_24h": heal_counts,
        "resources": res,
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


def do_heal(plan: dict, state: Path, project: Path, cfg: dict, *, allow_unratified: bool = False) -> dict:
    """Act on one heal plan. Every condition is re-checked at act time on the live file, under the store's real
    flock (``<file>.lock`` when present, and the file itself), held across archive-and-act; the original is archived
    before any change. Review 2026-10-31: never os.replace a store a writer may be appending to; truncate in place
    to the last good newline instead, only after the file has been quiet for ``quiet_min``."""
    src = Path(plan["path"])
    if plan["action"] not in SW.RATIFIED_HEALS and not allow_unratified:  # tests exercise the guards directly
        return {**plan, "result": "refused", "why": "not in RATIFIED_HEALS"}
    if SW.never_act(src.name, cfg):  # the file's own name; every state path contains "releases"
        return {**plan, "result": "refused", "why": "NEVER_ACT pattern in the target name"}
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    arch = Path(_expand(plan["archive_dir"], project, state)) / stamp / src.name
    h = cfg["heals"]
    with contextlib.ExitStack() as stack:
        for lk in [p for p in (Path(f"{src}.lock"), src) if p.exists()]:
            fh = stack.enter_context(lk.open("rb+" if lk == src else "a+b"))
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return {**plan, "result": "skipped", "why": f"lock held: {lk.name}"}
            stack.callback(fcntl.flock, fh.fileno(), fcntl.LOCK_UN)
        if not src.exists():
            return {**plan, "result": "skipped", "why": "file gone"}
        st = src.stat()
        quiet_min = (time.time() - st.st_mtime) / 60.0
        if plan["action"] == "reconcile_lock":
            if Path(f"/proc/{int(plan['pid'])}").exists():
                return {**plan, "result": "skipped", "why": "pid alive now"}
            arch.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, arch)  # archived, not deleted (AGENTS.md §0 rule 6), under the held flock
            return {**plan, "result": "reconciled", "archive": str(arch)}
        if plan.get("mtime") and datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        ) != str(plan["mtime"]):
            return {**plan, "result": "skipped", "why": "file changed since the finding"}
        if quiet_min < float(h["quiet_min"]):
            return {**plan, "result": "skipped", "why": f"written {quiet_min:.1f} min ago"}
        if plan["action"] == "repair_tail":
            data = src.read_bytes()
            off = SW.truncate_offset(data)
            if off is None:
                return {**plan, "result": "skipped", "why": "condition no longer holds or not safe"}
            arch.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, arch)
            fd = os.open(src, os.O_WRONLY)
            try:
                os.ftruncate(fd, off)
                os.fsync(fd)
            finally:
                os.close(fd)
            return {**plan, "result": "repaired", "dropped_bytes": len(data) - off, "archive": str(arch)}
        if plan["action"] == "restore_backup":
            if st.st_size != 0:
                return {**plan, "result": "skipped", "why": "target no longer empty"}
            b = Path(plan["from"])
            b_age_h = (time.time() - b.stat().st_mtime) / 3600.0
            if b_age_h > float(h["backup_max_age_h"]):
                return {**plan, "result": "skipped", "why": f"backup {b_age_h:.0f} h old"}
            raw = b.read_bytes()
            try:
                json.loads(raw)
            except ValueError:
                return {**plan, "result": "skipped", "why": "backup is not valid JSON now"}
            arch.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, arch)
            _atomic_write(src, raw)
            return {**plan, "result": "restored", "archive": str(arch), "backup_age_h": round(b_age_h, 1)}
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
            loops = int((receipt.get("heal_counts_24h") or {}).get(str(plan.get("path")), 0))
            if loops >= int(cfg["heals"]["loop_min"]):
                actions["heals"].append({**plan, "result": "suppressed", "why": f"heal loop: {loops} tries in 24 h"})
                continue
            if plan["action"] not in SW.RATIFIED_HEALS:
                actions["heals"].append(
                    {
                        **plan,
                        "result": "not_ratified",
                        "why": "not in RATIFIED_HEALS: needs a ratified §28.14 amendment",
                    }
                )
                continue
            if len(actions["heals"]) >= int(cfg["heals"]["max_per_tick"]):
                break
            try:
                res = do_heal(plan, state, project, cfg)
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
