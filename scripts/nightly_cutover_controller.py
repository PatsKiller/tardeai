#!/usr/bin/env python3
"""nightly_cutover_controller.py — lane `nightly-cutover-controller`: the bounded nightly n8n cutover (2026-10-16).

Operator approval, in writing, 2026-10-16: "building, testing and operating a bounded nightly automatic cutover process
for the already approved migration scope, including the necessary controlled crontab edits". AGENTS.md §23.25.
Owner: Agent A (Chief Architect), operator-approved. Enforced state machine, not a scheduled comment-cron:
the per-lane states and checks are in scripts/lib/nightly_cutover.py (ONE evaluator for plan, dry-run and apply).

    nightly_cutover_controller.py plan     [--json]     evaluate and print (no receipt)
    nightly_cutover_controller.py --dry-run             evaluate, write the run receipt, change nothing
    nightly_cutover_controller.py --apply               ARMED ONLY: re-evaluate from scratch (never an earlier plan),
                                                        optional forced canaries, then per ready lane: narrow crontab
                                                        edit (scripts/nightly_cutover_cron_edit.py), registry
                                                        reconciliation, rollback receipt; one summary line
    nightly_cutover_controller.py rollback --receipt F  ARMED ONLY: uncomment that lane's lines, restore its rows

ARMING: apply and rollback refuse unless an active guard grant of tier `cron` (read-only check of
~/.cursor/approvals/grants.json, the guard's own ledger) has a reason naming `nightly-cutover-controller`. Nothing here
creates, extends or consumes a grant. Without one the controller is DISARMED: it evaluates and writes its receipt only.

Shared control failure (ledger, CURRENT, crontab, lock, hash, registry, inventory) -> the whole cohort STOPS, exit 2.
Exit 0 = the run completed (lanes may be held); 1 = refused (disarmed / usage); 2 = cohort stop.

AUTHORITY: crontab comment-only edits of planned lines (via the edit capability), registry-root row writes, coordination
ledger run REQUESTs for approved forced canaries (gateway host_run_request), one P3 summary through send_telegram.
MBI_BEHAVIOR = 0: no broker, order, stop, secret or live flag.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import nightly_cutover as NC  # noqa: E402

NO_CONSUMER_REASON = (
    "NightlyCutoverRun@v1 receipts are the controller's durable proof (operator, Agent A, the lane's output_signal); "
    "per-lane NightlyCutoverRollback@v1 receipts are read by this script's rollback subcommand."
)
RUN_SCHEMA = "NightlyCutoverRun@v1"
ROLLBACK_SCHEMA = "NightlyCutoverRollback@v1"
CONFIG_REL = Path("config/nightly_cutover_controller.json")
CURRENT_LINK = Path.home() / "trade-ai-releases/portfolio-server/CURRENT"
STATE_ROOT = Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases/persistent-state")
LEDGER = STATE_ROOT / "data/governance/n8n_coordination_ledger.sqlite"
RELAY_LIVE = Path.home() / ".config/tradeai/n8n-live-lanes.env"
GRANTS = Path(os.environ.get("TRADEAI_GUARD_GRANTS_PATH", str(Path.home() / ".cursor/approvals/grants.json")))
EDIT_SCRIPT = ROOT / "scripts/nightly_cutover_cron_edit.py"
REQUESTED_BY = "host:nightly-cutover-controller"
CALLER_ID = "nightly-cutover-controller"


# ── arming (read-only grant check) ─────────────────────────────────────────────────────────────────────────────────

def armed(config: Mapping[str, Any], *, grants_path: Path = GRANTS, now: Optional[float] = None) -> tuple[bool, str]:
    """(armed, why). Active grant of config.grant_tier whose reason names config.grant_token. Read-only."""
    from scripts.lib.release_grant_binding import load_grants

    now = time.time() if now is None else now
    tier, token = str(config.get("grant_tier") or "cron"), str(config.get("grant_token") or NC.LANE_ID).lower()
    seen = []
    for g in load_grants(grants_path):
        if str(g.get("tier") or "") != tier:
            continue
        try:
            exp, uses = float(g.get("expires") or g.get("expires_at") or 0), int(g.get("uses") or 0)
        except (TypeError, ValueError):
            seen.append("unparseable")
            continue
        reason = str(g.get("reason") or "")
        if exp <= now:
            seen.append("expired")
        elif uses <= 0:
            seen.append("no_uses_left")
        elif token not in reason.lower():
            seen.append("reason_does_not_name_" + token)
        else:
            return True, f"grant {str(g.get('grant_id') or '?')[:8]} tier {tier} names {token}"
    return False, f"DISARMED: no active {tier} grant naming {token} ({','.join(seen) or 'no grant of that tier'})"


# ── world ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def live_workflows() -> list[dict]:
    from scripts.lib import n8n_live_inventory as inv

    return inv.read_workflow_bodies()


def read_crontab_text(path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    p = subprocess.run([os.environ.get("CRONTAB_CMD", "crontab"), "-l"], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise NC.CohortStop(f"crontab_unreadable:{p.stderr.strip()[:120]}")
    return p.stdout


def build_world(a: argparse.Namespace, config: Mapping[str, Any], *, now: Optional[datetime] = None,
                workflow_reader: Optional[Callable[[], list[dict]]] = None) -> tuple[NC.World, Path]:
    served, sha = NC.resolve_current(Path(a.current))
    reg_root = Path(os.path.expanduser(a.registry_root or str(config.get("registry_root"))))
    world = NC.gather_world(served_root=Path(a.served_root) if a.served_root else served, current_sha=sha,
                            registry_root=reg_root, crontab=read_crontab_text(a.crontab), ledger=Path(a.ledger),
                            relay_live_path=Path(a.relay_live), config=config,
                            now=now or datetime.now(timezone.utc),
                            workflow_reader=workflow_reader or live_workflows, state_root=Path(a.state_root),
                            policy_path=Path(a.cutover_policy) if a.cutover_policy else None)
    return world, reg_root


# ── receipts ───────────────────────────────────────────────────────────────────────────────────────────────────────

def receipt_dir(a: argparse.Namespace, config: Mapping[str, Any]) -> Path:
    if a.receipt_dir:
        return Path(a.receipt_dir)
    return Path(a.state_root) / str(config.get("receipt_dir") or "data/runtime/nightly_cutover")


def write_json_atomic(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
    os.replace(tmp, path)


def write_run_receipt(rdir: Path, rc: dict[str, Any]) -> Path:
    p = rdir / f"run-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{rc['mode']}.json"
    write_json_atomic(p, rc)
    write_json_atomic(rdir / "nightly_cutover_last.json", {**rc, "receipt_path": str(p),
                                                           "ok_at": rc.get("finished_at")})
    return p


# ── apply steps ────────────────────────────────────────────────────────────────────────────────────────────────────

def call_edit(req: dict[str, Any], *, lock: str, backup_dir: Path, runner=subprocess.run) -> tuple[int, dict]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(req, fh)
        path = fh.name
    try:
        p = runner([sys.executable, str(EDIT_SCRIPT), "--request", path, "--lock", lock,
                    "--backup-dir", str(backup_dir)], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(path)
    try:
        out = json.loads((p.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        out = {"problems": [f"edit capability gave no JSON (rc {p.returncode}): {(p.stderr or '')[:200]}"]}
    return p.returncode, out


def forced_canaries(world: NC.World, plan: dict[str, Any], config: Mapping[str, Any], *,
                    request_run: Callable[[str, str, str], dict], wait_run: Callable[[str, float], Optional[dict]]
                    ) -> list[dict[str, Any]]:
    """Approved forced canaries for lanes held ONLY for a missing qualifying run: one dry run then one live run through
    the gateway's coordination/run path (host_run_request; the executor applies the stage clamp). Not for F09 (natural
    proof only) and not for a lane whose effect key is armed for n8n (its live run needs the dispatcher's slot key)."""
    fc = config.get("forced_canary") or {}
    if not fc.get("enabled"):
        return []
    natural = set(fc.get("natural_only_families") or ["F09"])
    out = []
    for v in plan["lanes"]:
        if len(out) >= int(fc.get("max_per_night") or 0):
            break
        if not str(v.get("held") or "").startswith(("no_live_n8n_run", "no_qualifying_live_run")):
            continue
        lane = v["lane_id"]
        entry = world.allowlist.get(lane) or {}
        if v.get("family_id") in natural or (world.effect_lanes.get(lane) or {}).get("n8n_claim") \
                or entry.get("dry_run_arg") is None or entry.get("live_arg") is None:
            continue
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        rec: dict[str, Any] = {"lane_id": lane, "dry_run": None, "live": None}
        for mode in ("dry_run", "live"):
            rid = f"nc:{lane}:{mode}:{stamp}"
            env = request_run(lane, mode, rid)
            if env.get("state") == "REFUSED":
                rec[mode] = {"run_id": rid, "refused": env.get("reason")}
                break
            done = wait_run(rid, float(fc.get("poll_seconds") or 600))
            rec[mode] = {"run_id": rid, "state": (done or {}).get("state"), "exit": (done or {}).get("exit_code")}
            if not done or done.get("state") != "RUN_DONE" or done.get("exit_code") != 0:
                break
        out.append(rec)
    return out


def _host_request_run(allowlist: Mapping[str, Any], ledger: Path) -> Callable[[str, str, str], dict]:
    def req(lane: str, mode: str, rid: str) -> dict:
        from scripts.lib import n8n_coordination_gateway as G
        from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

        store = LedgerRunStore(CoordinationLedger(ledger))
        return G.host_run_request(lane_id=lane, mode=mode, run_id=rid, requested_by=REQUESTED_BY,
                                  caller_id=CALLER_ID, run_store=store, run_allowlist=frozenset(allowlist),
                                  now=time.time())
    return req


def _ledger_wait(ledger: Path) -> Callable[[str, float], Optional[dict]]:
    import sqlite3

    def wait(rid: str, budget: float) -> Optional[dict]:
        end = time.time() + budget
        while time.time() < end:
            c = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
            try:
                r = c.execute("SELECT state, exit_code FROM runs WHERE run_id=?", (rid,)).fetchone()
            finally:
                c.close()
            if r and r[0] not in NC.IN_FLIGHT_STATES:
                return {"state": r[0], "exit_code": r[1]}
            time.sleep(15)
        return None
    return wait


def apply_lane(v: dict[str, Any], world: NC.World, *, expect_sha: str, reg_root: Path, rdir: Path,
               config: Mapping[str, Any], a: argparse.Namespace, edit=call_edit) -> tuple[str, dict[str, Any]]:
    """Retire one lane. Returns (new crontab sha, step record). Raises CohortStop on any shared failure, after
    rolling back what this lane changed."""
    lane = v["lane_id"]
    _, sha_now = NC.resolve_current(Path(a.current))
    if sha_now != world.current_sha:
        raise NC.CohortStop(f"current_changed:{world.current_sha[:9]}->{sha_now[:9]}")
    req = {"op": "retire", "lane_id": lane, "date": world.now.strftime("%Y-%m-%d"), "expect_sha": expect_sha,
           "edits": [{"index": e["index"], "before": e["before"], "after": e["after"]} for e in v["edits"]]}
    lock, bdir = str(config.get("lock_path") or "/tmp/n8n_cutover.lock"), Path(a.backup_dir)
    rc, out = edit(req, lock=lock, backup_dir=bdir)
    step = {"lane_id": lane, "edit": out}
    if rc != 0 or not out.get("applied") or not out.get("read_back_ok") or not out.get("ownership_ok") \
            or not out.get("backup"):
        if out.get("applied"):
            _undo_cron(req, out, lock, bdir, edit)
        raise NC.CohortStop(f"crontab_edit_failed:{lane}:{'; '.join(out.get('problems') or ['rc %d' % rc])[:160]}")
    v["state"] = "applied"
    wave = f"nightly-{world.now.strftime('%Y%m%d')}"
    try:
        reg = NC.reconcile_registry(reg_root, lane, wave, world.registry[lane])
    except NC.CohortStop:
        _undo_cron(req, out, lock, bdir, edit)
        raise
    rb = {"schema": ROLLBACK_SCHEMA, "lane_id": lane, "at": out.get("at"), "current_sha": world.current_sha,
          "crontab_backup": out.get("backup"), "crontab_sha_after": out.get("sha_after"),
          "edits": [{"index": e["index"], "before": e["before"], "after": e["after"]} for e in v["edits"]],
          "registry_root": str(reg_root), **reg,
          "rollback_command": f"python3 scripts/nightly_cutover_controller.py rollback --receipt <this file>"}
    try:
        p = rdir / "rollback" / f"{lane}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
        write_json_atomic(p, rb)
    except OSError as exc:
        NC.restore_registry(reg_root, lane, reg)
        _undo_cron(req, out, lock, bdir, edit)
        raise NC.CohortStop(f"rollback_receipt_write_failed:{lane}:{exc}") from exc
    v["state"] = "reconciled"
    v["status"] = "reconciled"
    step["rollback_receipt"] = str(p)
    return str(out.get("sha_after")), step


def _undo_cron(req: dict, out: dict, lock: str, bdir: Path, edit) -> None:
    undo = {"op": "rollback", "lane_id": req["lane_id"], "expect_sha": out.get("sha_after"),
            "edits": req["edits"]}
    if out.get("sha_after"):
        edit(undo, lock=lock, backup_dir=bdir)


def summary_line(rc: Mapping[str, Any]) -> str:
    applied = [s["lane_id"] for s in rc.get("applied") or []]
    held = [v for v in rc.get("plan", {}).get("lanes") or [] if v.get("held")]
    stop = rc.get("cohort_stop") or "none"
    return (f"nightly-cutover {rc.get('mode')} {rc.get('date')}: cut over {len(applied)}"
            f"{' (' + ', '.join(applied[:6]) + ')' if applied else ''}; held {len(held)}; stop {stop}; "
            f"receipt {Path(str(rc.get('receipt_path') or '')).name}")


def notify(line: str, config: Mapping[str, Any]) -> bool:
    """At most ONE line per run, through the host chokepoint as a notification intent (P3 = digest)."""
    from telegram_alert import send_telegram  # type: ignore  # the one chokepoint module (scripts/ on sys.path)

    s = config.get("summary") or {}
    return bool(send_telegram(line, message_class="report", priority=str(s.get("priority") or "P3"),
                              producer=str(s.get("producer") or NC.LANE_ID)))


# ── main ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(a: argparse.Namespace, *, workflow_reader=None, edit=call_edit, request_run=None, wait_run=None,
        notifier=None, now: Optional[datetime] = None) -> tuple[int, dict[str, Any]]:
    mode = "apply" if a.apply else ("rollback" if a.cmd == "rollback" else ("dry_run" if a.dry_run else "plan"))
    rc: dict[str, Any] = {"schema": RUN_SCHEMA, "mode": mode, "started_at": datetime.now(timezone.utc).isoformat(),
                          "lane_id": NC.LANE_ID, "armed": None, "cohort_stop": None, "applied": [],
                          "forced_canaries": [], "plan": {}}
    try:
        config = NC.load_config(Path(a.config))
    except NC.CohortStop as exc:
        rc["cohort_stop"] = exc.reason
        return 2, rc
    ok, why = armed(config, grants_path=Path(a.grants))
    rc["armed"], rc["arming"] = ok, why
    if mode in ("apply", "rollback") and not ok:
        rc["refused"] = why
        return 1, rc
    if mode == "rollback":
        return do_rollback(a, config, rc, edit=edit)
    try:
        world, reg_root = build_world(a, config, now=now, workflow_reader=workflow_reader)
        plan = NC.evaluate(world)
        rc["date"] = plan["date"]
        if mode == "apply" and request_run is not None:
            rc["forced_canaries"] = forced_canaries(world, plan, config, request_run=request_run,
                                                    wait_run=wait_run or (lambda r, b: None))
            if rc["forced_canaries"]:
                world, reg_root = build_world(a, config, now=now, workflow_reader=workflow_reader)
                plan = NC.evaluate(world)
        rc["plan"] = plan
        if mode == "apply":
            expect = world.crontab_sha
            for v in plan["lanes"]:
                if v.get("status") != "ready":
                    continue
                expect, step = apply_lane(v, world, expect_sha=expect, reg_root=reg_root,
                                          rdir=receipt_dir(a, config), config=config, a=a, edit=edit)
                rc["applied"].append(step)
    except NC.CohortStop as exc:
        rc["cohort_stop"] = exc.reason
    rc["finished_at"] = datetime.now(timezone.utc).isoformat()
    if mode != "plan":
        try:
            rc["receipt_path"] = str(write_run_receipt(receipt_dir(a, config), rc))
        except OSError as exc:
            rc["receipt_error"] = str(exc)
        if mode == "apply" and not a.no_notify:
            try:
                rc["summary_accepted"] = (notifier or notify)(summary_line(rc), config)
            except Exception as exc:  # noqa: BLE001 - a notification failure never undoes the run
                rc["summary_error"] = f"{type(exc).__name__}: {exc}"
    return (2 if rc["cohort_stop"] else 0), rc


def do_rollback(a: argparse.Namespace, config: Mapping[str, Any], rc: dict[str, Any], *, edit) -> tuple[int, dict]:
    rec = json.loads(Path(a.receipt).read_text(encoding="utf-8"))
    if rec.get("schema") != ROLLBACK_SCHEMA:
        rc["refused"] = "not a NightlyCutoverRollback@v1 receipt"
        return 1, rc
    text = read_crontab_text(a.crontab)
    req = {"op": "rollback", "lane_id": rec["lane_id"], "expect_sha": NC.sha256_text(text), "edits": rec["edits"]}
    code, out = edit(req, lock=str(config.get("lock_path") or "/tmp/n8n_cutover.lock"), backup_dir=Path(a.backup_dir))
    rc["rollback"] = {"lane_id": rec["lane_id"], "edit": out}
    if code != 0:
        rc["cohort_stop"] = "rollback_edit_failed"
        return 2, rc
    rc["rollback"]["registry_problems"] = NC.restore_registry(Path(rec["registry_root"]), rec["lane_id"], rec)
    return 0, rc


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("cmd", nargs="?", default="run", choices=("run", "plan", "rollback"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--receipt", help="rollback: the NightlyCutoverRollback@v1 file")
    ap.add_argument("--config", default=str(ROOT / CONFIG_REL))
    ap.add_argument("--current", default=str(CURRENT_LINK))
    ap.add_argument("--served-root", help="evaluate this tree's config instead of CURRENT's (tests)")
    ap.add_argument("--registry-root", help="override config.registry_root")
    ap.add_argument("--cutover-policy", help="PROJECTION ONLY (refused with --apply): read this lane_cutover_policy.json "
                                             "instead of the served one")
    ap.add_argument("--crontab", help="read this file instead of `crontab -l` (plan/dry-run only)")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--relay-live", default=str(RELAY_LIVE))
    ap.add_argument("--state-root", default=str(STATE_ROOT))
    ap.add_argument("--receipt-dir")
    ap.add_argument("--grants", default=str(GRANTS))
    ap.add_argument("--backup-dir", default=str(Path.home() / ".local/state/tradeai/backups"))
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--no-forced-canary", action="store_true")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    a = parser().parse_args(argv)
    if a.cmd == "plan":
        a.dry_run = False
    if a.apply and (a.cutover_policy or a.served_root):
        print("REFUSED: --apply evaluates the served release only (no --cutover-policy / --served-root)", file=sys.stderr)
        return 1
    if a.apply and a.crontab:
        print("REFUSED: --apply reads the live crontab (no --crontab copy)", file=sys.stderr)
        return 1
    if a.cmd == "rollback" and not a.receipt:
        print("REFUSED: rollback needs --receipt", file=sys.stderr)
        return 1
    if a.cmd == "rollback":
        a.apply = False
    req = None
    if a.apply and not a.no_forced_canary:
        try:
            al = json.loads((NC.resolve_current(Path(a.current))[0] / "config/n8n_run_allowlist.json").read_text())
            req = _host_request_run({e["lane_id"]: e for e in al.get("lanes") or [] if isinstance(e, dict)},
                                    Path(a.ledger))
        except (OSError, ValueError, NC.CohortStop):
            req = None
    code, rc = run(a, request_run=req, wait_run=_ledger_wait(Path(a.ledger)) if req else None)
    if a.json or a.cmd == "rollback":
        print(json.dumps(rc, indent=2, default=str))
    else:
        print(f"{rc['mode']}: armed={rc.get('armed')} ({rc.get('arming')}); stop={rc.get('cohort_stop') or 'none'}")
        for v in (rc.get("plan") or {}).get("lanes") or []:
            print(f"  {(v.get('status') or '-')[:110]:<110} {v['lane_id']}")
        print(json.dumps((rc.get("plan") or {}).get("counts") or {}), rc.get("receipt_path") or "")
        if rc.get("refused"):
            print("REFUSED:", rc["refused"])
    return code


if __name__ == "__main__":
    sys.exit(main())
