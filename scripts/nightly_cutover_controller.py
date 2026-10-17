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
                                                        (inside the handover fence; every target re-read and
                                                        verified; exit 2 + per-target report on any failure)

ARMING: apply and rollback refuse unless an active guard grant of tier `cron` (read-only check of
~/.cursor/approvals/grants.json, the guard's own ledger) has a reason naming `nightly-cutover-controller`. Nothing here
creates, extends or consumes a grant. Without one the controller is DISARMED: it evaluates and writes its receipt only.

Shared control failure (ledger, CURRENT, crontab, lock, hash, registry, inventory) -> the whole cohort STOPS, exit 2.
Exit 0 = the run completed (lanes may be held); 1 = refused (disarmed / usage / another invocation running);
2 = cohort stop.

2026-10-16 (architect review) transaction guarantees, all under ONE controller lock (<receipt_dir>/controller.lock,
non-blocking: a concurrent invocation is refused `controller_busy` and changes nothing):

* durable nightly quota: max_lanes_per_night is counted across every invocation of the ET night in
  <receipt_dir>/quota/night-<date>.json (scripts/lib/nightly_cutover_txn.py); a lane is reserved before it is touched.
* fresh checks at mutation time: immediately before EACH lane's edit, with the handover-manifest lock held (so no
  `effect_claim.py set-owner` can land in between), the controller re-reads the grant (still active, not revoked),
  re-gathers the world (ledger owner, in-flight runs, ambiguous claims, workflow graph hashes, CURRENT sha, allowlist
  and contract versions, crontab hash) and re-evaluates the lane. A lane-level change holds that lane; a shared change
  (grant revoked, release / allowlist / contracts / approved-workflow graph changed, crontab changed) stops the cohort.
* write-ahead transaction: <receipt_dir>/txn/<txn_id>.json is written BEFORE the first mutation (crontab, registry,
  health contract), each step is marked as it completes, and every armed start recovers any incomplete transaction
  (complete when every mutation landed, else roll back) before any new work, then stops for the night.

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

from scripts.lib import effect_claim as EC  # noqa: E402
from scripts.lib import nightly_cutover as NC  # noqa: E402
from scripts.lib import nightly_cutover_txn as TX  # noqa: E402

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
TXN_STEP_POINTS = ("txn_written", "crontab_done", "registry_done", "contracts_done", "rollback_receipt_done")
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
                            policy_path=Path(a.cutover_policy) if a.cutover_policy else None,
                            manifest_path=manifest_path(a))
    try:
        world.quota_used = TX.quota_used(TX.quota_read(receipt_dir(a, config), TX.night_key(world.now)))
    except ValueError as exc:
        raise NC.CohortStop(str(exc)) from exc
    return world, reg_root


def manifest_path(a: argparse.Namespace) -> Path:
    return Path(a.handover_manifest) if getattr(a, "handover_manifest", None) else \
        EC.handover_manifest_path(Path(a.ledger))


# ── receipts ───────────────────────────────────────────────────────────────────────────────────────────────────────

def receipt_dir(a: argparse.Namespace, config: Mapping[str, Any]) -> Path:
    if a.receipt_dir:
        return Path(a.receipt_dir)
    return Path(a.state_root) / str(config.get("receipt_dir") or "data/runtime/nightly_cutover")


def write_json_atomic(path: Path, doc: Any, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=sort_keys, default=str)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
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


def _noop_checkpoint(point: str) -> None:
    return None


def cron_state(text: str, edits: list[Mapping[str, Any]]) -> str:
    """applied / not_applied / conflict for these planned edits in this crontab text."""
    lines = text.split("\n")
    st = set()
    for e in edits:
        i = int(e["index"])
        cur = lines[i] if 0 <= i < len(lines) else None
        st.add("applied" if cur == e["after"] else "not_applied" if cur == e["before"] else "conflict")
    return "conflict" if "conflict" in st or len(st) != 1 else st.pop()


def read_cron_lines(edits: list[Mapping[str, Any]]) -> tuple[str, str]:
    """(crontab text, state) where state is applied / not_applied / conflict for these planned edits."""
    text = read_crontab_text(None)
    return text, cron_state(text, edits)


def _backup_file(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = Path(src).read_bytes()
    fd = os.open(dst, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return str(dst)


def apply_lane(v: dict[str, Any], world: NC.World, *, expect_sha: str, reg_root: Path, rdir: Path,
               config: Mapping[str, Any], a: argparse.Namespace, edit=call_edit,
               checkpoint=_noop_checkpoint) -> tuple[Optional[str], dict[str, Any]]:
    """Retire one lane inside a write-ahead transaction. Returns (new crontab sha, step record); the sha is None when
    the lane was held at reservation (nightly quota spent). Raises CohortStop on any shared failure, after rolling
    back whatever this lane changed. The caller holds the controller lock and the handover lock."""
    lane = v["lane_id"]
    _, sha_now = NC.resolve_current(Path(a.current))
    if sha_now != world.current_sha:
        raise NC.CohortStop(f"current_changed:{world.current_sha[:9]}->{sha_now[:9]}")
    night = TX.night_key(world.now)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    txn_id = f"{night}-{lane}-{stamp}-{os.getpid()}"
    wave = f"nightly-{world.now.strftime('%Y%m%d')}"
    js = NC.plan_reconcile(reg_root, lane, wave, world.registry[lane])
    edits = [{"index": e["index"], "before": e["before"], "after": e["after"]} for e in v["edits"]]
    lock, bdir = str(config.get("lock_path") or "/tmp/n8n_cutover.lock"), Path(a.backup_dir)
    cap = int(config.get("max_lanes_per_night") or 0)
    try:
        ok, used = TX.quota_reserve(rdir, night, lane=lane, txn_id=txn_id, cap=cap, now=world.now)
    except (ValueError, OSError) as exc:
        raise NC.CohortStop(f"quota_ledger_failure:{exc}") from exc
    if not ok:
        NC._hold(v, f"nightly_cap_reached: max_lanes_per_night={cap}, already used tonight={used} (durable quota)")
        return None, {"lane_id": lane, "held": v["held"]}
    tdir = TX.txn_dir(rdir)
    try:
        backups = {"crontab": None, "registry": _backup_file(Path(js["registry"]["path"]),
                                                            tdir / f"{txn_id}.lane_registry.json.bak"),
                   "contracts": None if js["contracts"] is None else
                   _backup_file(Path(js["contracts"]["path"]), tdir / f"{txn_id}.n8n_health_contracts.json.bak")}
        cb = tdir / f"{txn_id}.crontab.bak"
        fd = os.open(cb, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(world.crontab)
            fh.flush()
            os.fsync(fh.fileno())
        backups["crontab"] = str(cb)
        rec = TX.new_txn(txn_id=txn_id, lane=lane, night=night, now=world.now, current_sha=world.current_sha,
                         wave=wave, crontab={"lock": lock, "backup_dir": str(bdir), "edits": edits,
                                             "sha_before": expect_sha},
                         json_steps=js, backups=backups, invocation=f"pid:{os.getpid()}")
        TX.txn_write(rdir, rec)                                          # WRITE-AHEAD: before any mutation
    except OSError as exc:
        TX.quota_mark(rdir, night, txn_id, "released")
        raise NC.CohortStop(f"txn_record_write_failed:{lane}:{exc}") from exc
    checkpoint("txn_written")
    step: dict[str, Any] = {"lane_id": lane, "txn_id": txn_id, "txn": str(TX.txn_path(rdir, txn_id))}
    try:
        # 1. crontab
        TX.txn_mark(rdir, rec, "crontab", "intent")
        req = {"op": "retire", "lane_id": lane, "date": world.now.strftime("%Y-%m-%d"), "expect_sha": expect_sha,
               "edits": edits}
        rc, out = edit(req, lock=lock, backup_dir=bdir)
        step["edit"] = out
        if rc != 0 or not out.get("applied") or not out.get("read_back_ok") or not out.get("ownership_ok") \
                or not out.get("backup"):
            raise NC.CohortStop(f"crontab_edit_failed:{lane}:"
                                f"{'; '.join(out.get('problems') or ['rc %d' % rc])[:160]}")
        TX.txn_mark(rdir, rec, "crontab", "done", crontab_sha_after=out.get("sha_after"),
                    crontab_edit_backup=out.get("backup"))
        v["state"] = "applied"
        checkpoint("crontab_done")
        # 2. registry row, 3. health contract
        for name in ("registry", "contracts"):
            if rec.get(name) is None:
                TX.txn_mark(rdir, rec, name, "not_applicable")
                continue
            TX.txn_mark(rdir, rec, name, "intent")
            NC.json_step(rec[name])
            TX.txn_mark(rdir, rec, name, "done")
            checkpoint(f"{name}_done")
        # 4. rollback receipt
        p = write_rollback_receipt(rdir, rec, out)
        TX.txn_mark(rdir, rec, "rollback_receipt", "done", rollback_receipt_path=str(p))
        checkpoint("rollback_receipt_done")
    except NC.CohortStop as exc:
        res = rollback_txn(rdir, rec, edit=edit)
        step["rolled_back"] = res
        raise NC.CohortStop(f"{exc.reason} (txn {txn_id} {res.get('outcome')})") from exc
    except OSError as exc:
        res = rollback_txn(rdir, rec, edit=edit)
        raise NC.CohortStop(f"txn_step_failed:{lane}:{exc} (txn {txn_id} {res.get('outcome')})") from exc
    TX.txn_mark(rdir, rec, status="committed", outcome="committed")
    TX.quota_mark(rdir, night, txn_id, "applied")
    v["state"] = "reconciled"
    v["status"] = "reconciled"
    step["rollback_receipt"] = rec["rollback_receipt_path"]
    return str(out.get("sha_after")), step


def write_rollback_receipt(rdir: Path, rec: Mapping[str, Any], out: Mapping[str, Any]) -> Path:
    reg, con = rec["registry"], rec.get("contracts") or {}
    rb = {"schema": ROLLBACK_SCHEMA, "lane_id": rec["lane_id"], "at": out.get("at"), "txn_id": rec["txn_id"],
          "current_sha": rec["current_sha"], "crontab_backup": out.get("backup") or rec.get("crontab_edit_backup"),
          "crontab_sha_after": out.get("sha_after") or rec.get("crontab_sha_after"),
          "edits": rec["crontab"]["edits"], "registry_root": str(Path(reg["path"]).parents[1]),
          "registry_path": reg["path"], "contracts_path": con.get("path"),
          "row_before": reg["before"], "row_after": reg["after"],
          "contract_before": con.get("before"), "contract_after": con.get("after"),
          "registry_sha_before": reg.get("sha_before"), "contracts_sha_before": con.get("sha_before"),
          "rollback_command": "python3 scripts/nightly_cutover_controller.py rollback --receipt <this file>"}
    p = rdir / "rollback" / f"{rec['lane_id']}-{rec['txn_id']}.json"
    # key order preserved: a restored before-image must serialise byte-identically to what was there
    write_json_atomic(p, rb, sort_keys=False)
    return p


def inspect_txn(rec: Mapping[str, Any]) -> dict[str, str]:
    """The ACTUAL state of each mutation target: applied / not_applied / conflict (n/a when there is none)."""
    try:
        _, cron = read_cron_lines(rec["crontab"]["edits"])
    except (NC.CohortStop, OSError, subprocess.SubprocessError):
        cron = "conflict"
    out = {"crontab": cron}
    for name in ("registry", "contracts"):
        out[name] = "n/a" if rec.get(name) is None else NC.json_step_state(rec[name])
    return out


def rollback_txn(rdir: Path, rec: dict[str, Any], *, edit=call_edit) -> dict[str, Any]:
    """Undo every applied mutation of the transaction in reverse order (contracts, registry, crontab). Inspection
    based and idempotent. A conflicting target is never touched: the transaction is marked conflict, both values are
    reported, and the caller stops the cohort."""
    seen = inspect_txn(rec)
    if "conflict" in seen.values():
        TX.txn_mark(rdir, rec, status="conflict", outcome="conflict", conflict=seen)
        return {"outcome": "conflict", "inspected": seen}
    TX.txn_mark(rdir, rec, status="rolling_back", inspected=seen)
    for name in ("contracts", "registry"):
        if seen[name] == "applied":
            NC.json_step(rec[name], undo=True)
            TX.txn_mark(rdir, rec, name, "undone")
    if seen["crontab"] == "applied":
        text, _ = read_cron_lines(rec["crontab"]["edits"])
        undo = {"op": "rollback", "lane_id": rec["lane_id"], "expect_sha": NC.sha256_text(text),
                "edits": rec["crontab"]["edits"]}
        code, out = edit(undo, lock=rec["crontab"]["lock"], backup_dir=Path(rec["crontab"]["backup_dir"]))
        if code != 0:
            TX.txn_mark(rdir, rec, status="conflict", outcome="crontab_undo_failed",
                        conflict={"crontab_undo": out.get("problems")})
            return {"outcome": "crontab_undo_failed", "problems": out.get("problems")}
        TX.txn_mark(rdir, rec, "crontab", "undone")
    TX.txn_mark(rdir, rec, status="rolled_back", outcome="rolled_back")
    TX.quota_mark(rdir, rec["night"], rec["txn_id"], "released")
    return {"outcome": "rolled_back", "inspected": seen}


def recover(rdir: Path, *, edit=call_edit) -> list[dict[str, Any]]:
    """Recover every incomplete transaction, deterministically: all mutations applied -> complete (rollback receipt,
    commit); otherwise roll back. Also releases quota reservations whose record never got written. Idempotent."""
    out = []
    for night, e in list(TX.quota_orphans(rdir)):
        TX.quota_mark(rdir, night, str(e.get("txn_id")), "released")
        out.append({"txn_id": e.get("txn_id"), "lane_id": e.get("lane_id"), "outcome": "orphan_reservation_released"})
    for rec in TX.open_txns(rdir):
        seen = inspect_txn(rec)
        applied = [k for k, st in seen.items() if st == "applied"]
        needed = [k for k, st in seen.items() if st != "n/a"]
        if "conflict" not in seen.values() and applied == needed:
            TX.txn_mark(rdir, rec, status="completing", inspected=seen)
            for name in MUTATION_ORDER:
                if rec["steps"].get(name) not in ("done", "not_applicable"):
                    TX.txn_mark(rdir, rec, name, "done" if seen[name] == "applied" else "not_applicable")
            if not rec.get("rollback_receipt_path"):
                p = write_rollback_receipt(rdir, rec, {})
                TX.txn_mark(rdir, rec, "rollback_receipt", "done", rollback_receipt_path=str(p))
            TX.txn_mark(rdir, rec, status="committed", outcome="committed_by_recovery")
            TX.quota_mark(rdir, rec["night"], rec["txn_id"], "applied")
            out.append({"txn_id": rec["txn_id"], "lane_id": rec["lane_id"], "outcome": "committed_by_recovery",
                        "inspected": seen})
        else:
            res = rollback_txn(rdir, rec, edit=edit)
            out.append({"txn_id": rec["txn_id"], "lane_id": rec["lane_id"], **res})
    return out


MUTATION_ORDER = TX.MUTATION_STEPS


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
        notifier=None, now: Optional[datetime] = None, checkpoint=_noop_checkpoint) -> tuple[int, dict[str, Any]]:
    mode = "apply" if a.apply else ("rollback" if a.cmd == "rollback" else ("dry_run" if a.dry_run else "plan"))
    rc: dict[str, Any] = {"schema": RUN_SCHEMA, "mode": mode, "started_at": datetime.now(timezone.utc).isoformat(),
                          "lane_id": NC.LANE_ID, "armed": None, "cohort_stop": None, "applied": [],
                          "forced_canaries": [], "plan": {}, "recovered": [], "incomplete_txns": []}
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
    rdir = receipt_dir(a, config)
    if mode in ("apply", "rollback"):
        try:
            lock = TX.ControllerLock(rdir).__enter__()
        except TX.ControllerBusy as exc:
            rc["refused"] = f"controller_busy: another invocation holds {exc}"
            return 1, rc
        try:
            if mode == "rollback":
                return do_rollback(a, config, rc, edit=edit, rdir=rdir)
            return _run_locked(a, config, rc, rdir, workflow_reader=workflow_reader, edit=edit,
                               request_run=request_run, wait_run=wait_run, notifier=notifier, now=now,
                               checkpoint=checkpoint)
        finally:
            lock.__exit__()
    return _run_locked(a, config, rc, rdir, workflow_reader=workflow_reader, edit=edit, request_run=None,
                       wait_run=None, notifier=notifier, now=now, checkpoint=checkpoint)


def _run_locked(a, config, rc, rdir, *, workflow_reader, edit, request_run, wait_run, notifier, now,
                checkpoint) -> tuple[int, dict[str, Any]]:
    mode = rc["mode"]
    try:
        # 0. incomplete transactions: recovered (armed apply) or reported (plan / dry-run) BEFORE any new work.
        try:
            pending = TX.open_txns(rdir)
            orphans = list(TX.quota_orphans(rdir))
        except ValueError as exc:
            raise NC.CohortStop(str(exc)) from exc
        rc["incomplete_txns"] = [{"txn_id": t["txn_id"], "lane_id": t["lane_id"], "status": t["status"]}
                                 for t in pending]
        if pending or orphans:
            if mode == "apply":
                # finding 2 (architect review of 26fd0518): a recovery ROLLBACK is an ownership-relevant mutation
                # (it re-enables a cron line); it runs inside the same handover fence as admission and set-owner.
                try:
                    fence = EC.handover_lock(manifest_path(a)).__enter__()
                except (EC.HandoverLockTimeout, OSError) as exc:
                    raise NC.CohortStop(f"handover_lock_timeout:{exc}") from exc
                try:
                    rc["recovered"] = recover(rdir, edit=edit)
                finally:
                    fence.__exit__()
                bad = [r for r in rc["recovered"] if r.get("outcome") not in
                       ("rolled_back", "committed_by_recovery", "orphan_reservation_released")]
                raise NC.CohortStop(("recovery_conflict:" if bad else "recovered_incomplete_txn:")
                                    + ",".join(f"{r.get('txn_id')}={r.get('outcome')}" for r in rc["recovered"])
                                    + " (no new work this invocation)")
            if pending:
                raise NC.CohortStop("incomplete_txn_pending_recovery:" + ",".join(t["txn_id"] for t in pending)
                                    + " (the next armed apply recovers it first)")
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
            apply_cohort(a, config, rc, world, plan, reg_root, rdir, workflow_reader=workflow_reader, edit=edit,
                         now=now, checkpoint=checkpoint)
    except NC.CohortStop as exc:
        rc["cohort_stop"] = exc.reason
    rc["finished_at"] = datetime.now(timezone.utc).isoformat()
    if mode != "plan":
        try:
            rc["receipt_path"] = str(write_run_receipt(rdir, rc))
        except OSError as exc:
            rc["receipt_error"] = str(exc)
        if mode == "apply" and not a.no_notify:
            try:
                rc["summary_accepted"] = (notifier or notify)(summary_line(rc), config)
            except Exception as exc:  # noqa: BLE001 - a notification failure never undoes the run
                rc["summary_error"] = f"{type(exc).__name__}: {exc}"
    return (2 if rc["cohort_stop"] else 0), rc


def apply_cohort(a, config, rc, world: NC.World, plan: dict[str, Any], reg_root: Path, rdir: Path, *,
                 workflow_reader, edit, now, checkpoint) -> None:
    """Per ready lane: the FENCED HANDOVER (handover-manifest lock held, so no owner switch can land), fresh checks
    at mutation time, then the write-ahead transaction. Raises CohortStop on a shared change."""
    expect = world.crontab_sha
    baseline = NC.shared_fingerprint(world)
    mpath = manifest_path(a)
    for v in plan["lanes"]:
        if v.get("status") != "ready":
            continue
        lane = v["lane_id"]
        try:
            fence = EC.handover_lock(mpath).__enter__()
        except EC.HandoverLockTimeout as exc:
            raise NC.CohortStop(f"handover_lock_timeout:{exc}") from exc
        try:
            ok, why = armed(config, grants_path=Path(a.grants))
            if not ok:
                raise NC.CohortStop(f"authorization_revoked_mid_run: {why}")
            fresh, reg_root = build_world(a, config, now=now, workflow_reader=workflow_reader)
            fp = NC.shared_fingerprint(fresh)
            if fp != baseline:
                changed = sorted(k for k in fp if fp[k] != baseline[k])
                raise NC.CohortStop(f"shared_state_changed_mid_run:{','.join(changed)}")
            if fresh.crontab_sha != expect:
                raise NC.CohortStop("crontab_changed_mid_run: the crontab differs from the one this run left")
            fv = NC.evaluate_lane(fresh, lane, plan["date"])
            if fv.get("status") != "ready":
                NC._hold(v, f"changed_at_mutation:{fv.get('held')}")
                continue
            if fv.get("owner_at_eval") != v.get("owner_at_eval"):
                NC._hold(v, f"owner_changed_mid_run: {v.get('owner_at_eval')} -> {fv.get('owner_at_eval')}")
                continue
            if fv.get("workflow_at_eval") != v.get("workflow_at_eval"):
                NC._hold(v, "lane_workflow_graph_changed_mid_run")
                continue
            if fv["edits"] != v["edits"]:
                NC._hold(v, "planned_edits_changed_mid_run")
                continue
            v["edits"] = fv["edits"]
            new_sha, step = apply_lane(v, fresh, expect_sha=expect, reg_root=reg_root, rdir=rdir, config=config,
                                       a=a, edit=edit, checkpoint=checkpoint)
            if new_sha is None:
                continue
            expect = new_sha
            rc["applied"].append(step)
        finally:
            fence.__exit__()


def rollback_steps(rec: Mapping[str, Any]) -> dict[str, Optional[dict[str, Any]]]:
    """The receipt's registry / contract targets as transaction steps (the json_step shape the write-ahead txn uses),
    so the explicit rollback restores and verifies with the SAME primitives as rollback_txn / recover."""
    lane = rec["lane_id"]
    root = Path(str(rec.get("registry_root") or "."))
    reg = {"path": str(rec.get("registry_path") or root / "config/lane_registry.json"), "coll": "lanes",
           "key": "lane_id", "id": lane, "before": rec.get("row_before"), "after": rec.get("row_after")}
    con = None
    if rec.get("contract_before") is not None:
        con = {"path": str(rec.get("contracts_path") or root / "config/n8n_health_contracts.json"),
               "coll": "contracts", "key": "id", "id": lane, "before": rec.get("contract_before"),
               "after": rec.get("contract_after")}
    return {"registry": reg, "contracts": con}


def do_rollback(a: argparse.Namespace, config: Mapping[str, Any], rc: dict[str, Any], *, edit,
                rdir: Optional[Path] = None) -> tuple[int, dict]:
    """The explicit ``rollback --receipt`` (architect review of 26fd0518, finding 4: it used to exit 0 even when the
    registry restore failed). Now, inside the handover fence (finding 2) and with the transaction primitives:

    1. inspect every target (crontab lines, registry row, health contract): applied / not_applied / conflict. A
       conflict anywhere -> nothing is touched, exit 2 (never auto-reconciled, AGENTS.md §0 rule 5);
    2. undo in rollback_txn's order (contracts, registry, crontab), each through NC.json_step(undo=True) / the edit
       capability;
    3. VERIFY each target by re-reading it: it must now equal its before-image (``not_applied``);
    4. exit 0 only when every target verified; otherwise exit 2 with ``rollback.targets`` = the per-target report
       {before, action, after, ok, problem}. The report is also written as a run receipt."""
    rec = json.loads(Path(a.receipt).read_text(encoding="utf-8"))
    if rec.get("schema") != ROLLBACK_SCHEMA:
        rc["refused"] = "not a NightlyCutoverRollback@v1 receipt"
        return 1, rc
    try:
        fence = EC.handover_lock(manifest_path(a)).__enter__()
    except (EC.HandoverLockTimeout, OSError) as exc:
        rc["cohort_stop"] = f"handover_lock_timeout:{exc}"
        return 2, rc
    try:
        code, rc = _rollback_fenced(a, config, rc, rec, edit=edit)
    finally:
        fence.__exit__()
    rc["finished_at"] = datetime.now(timezone.utc).isoformat()
    if rdir is not None:
        try:      # the run receipt only: nightly_cutover_last.json (the lane's freshness signal) is not touched
            p = rdir / f"run-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-rollback.json"
            write_json_atomic(p, rc)
            rc["receipt_path"] = str(p)
        except OSError as exc:
            rc["receipt_error"] = str(exc)
    return code, rc


def _rollback_fenced(a: argparse.Namespace, config: Mapping[str, Any], rc: dict[str, Any], rec: Mapping[str, Any],
                     *, edit) -> tuple[int, dict]:
    steps = rollback_steps(rec)
    edits = list(rec.get("edits") or [])
    targets: dict[str, dict[str, Any]] = {}
    rc["rollback"] = {"lane_id": rec["lane_id"], "targets": targets, "edit": None, "registry_problems": []}
    try:
        text = read_crontab_text(a.crontab)
        cron_before = cron_state(text, edits) if edits else "n/a"
    except (NC.CohortStop, OSError, subprocess.SubprocessError) as exc:
        text, cron_before = None, "conflict"
        targets["crontab"] = {"problem": f"crontab_unreadable:{exc}"[:200]}
    targets.setdefault("crontab", {})["before"] = cron_before
    for name in ("registry", "contracts"):
        targets[name] = {"before": "n/a" if steps[name] is None else NC.json_step_state(steps[name])}
    conflicts = [k for k, t in targets.items() if t["before"] == "conflict"]
    if conflicts:
        for t in targets.values():
            t.update(action="untouched", after=t["before"], ok=t["before"] in ("not_applied", "n/a"))
        rc["rollback"]["registry_problems"] = [f"{k}: conflict (neither the before nor the after image)"
                                               for k in conflicts]
        rc["cohort_stop"] = "rollback_conflict:" + ",".join(conflicts)
        return 2, rc
    # 2. undo, rollback_txn order: contracts, registry, crontab
    for name in ("contracts", "registry"):
        t, step = targets[name], steps[name]
        if step is None:
            t.update(action="not_applicable", after="n/a", ok=True)
            continue
        if t["before"] == "applied":
            try:
                t["action"] = NC.json_step(step, undo=True)
            except NC.CohortStop as exc:
                t["action"], t["problem"] = "failed", exc.reason
        else:
            t["action"] = "already_restored"
        t["after"] = NC.json_step_state(step)          # 3. verify by re-reading the target
        t["ok"] = t["after"] == "not_applied"
        if not t["ok"]:
            t.setdefault("problem", f"after_restore_state:{t['after']}")
    t = targets["crontab"]
    json_failed = [k for k in ("contracts", "registry") if not targets[k].get("ok")]
    if json_failed and cron_before == "applied":
        # The registry still routes the lane to n8n: re-enabling its cron line now would schedule it twice.
        t.update(action="skipped_prior_failure", problem=f"not restored: {','.join(json_failed)} failed first")
    elif cron_before == "applied":
        req = {"op": "rollback", "lane_id": rec["lane_id"], "expect_sha": NC.sha256_text(text), "edits": edits}
        code, out = edit(req, lock=str(config.get("lock_path") or "/tmp/n8n_cutover.lock"),
                         backup_dir=Path(a.backup_dir))
        rc["rollback"]["edit"] = out
        t["action"] = "written" if code == 0 else f"failed:rc={code}"
        if code != 0:
            t["problem"] = "; ".join(out.get("problems") or [f"edit rc {code}"])[:200]
    else:
        t["action"] = "already_restored" if cron_before == "not_applied" else "not_applicable"
    if edits:
        try:
            t["after"] = cron_state(read_crontab_text(a.crontab), edits)
        except (NC.CohortStop, OSError, subprocess.SubprocessError) as exc:
            t["after"], t["problem"] = "unreadable", f"crontab_unreadable:{exc}"[:200]
    else:
        t["after"] = "n/a"
    t["ok"] = t["after"] in ("not_applied", "n/a")
    if not t["ok"]:
        t.setdefault("problem", f"after_restore_state:{t['after']}")
    failed = [k for k, x in targets.items() if not x.get("ok")]
    rc["rollback"]["registry_problems"] = [f"{k}: {targets[k].get('problem')}" for k in failed
                                           if k in ("registry", "contracts")]
    if failed:
        rc["cohort_stop"] = "rollback_incomplete:" + ",".join(f"{k}={targets[k].get('after')}" for k in failed)
        return 2, rc
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
    ap.add_argument("--handover-manifest", help="the durable handover manifest (default: beside the ledger)")
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
