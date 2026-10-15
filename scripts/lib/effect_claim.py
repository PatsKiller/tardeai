#!/usr/bin/env python3
"""Semantic effect key: one live effect per (business process, slot, input version), whoever fires it.

2026-10-14 (n8n fabric Phase 1; AGENTS.md §23.23 migration rule (4), PROPOSED 10.0.0; REFACTOR_PLAN addendum
items 1 and 2). A shared flock stops a cron run and an n8n run of the same lane from OVERLAPPING. It does not stop
them running one after the other: cron fires the 07:30 slot, finishes and drops the lock, then n8n fires the same
07:30 slot and the effect (a digest, a send, a write) happens twice. Both schedulers therefore claim the same key
in one durable table before the effect, and the second claim of a live key is refused.

Two guards, both in one ``BEGIN IMMEDIATE`` on the coordination ledger file:

* **Key claim** (``effect_claims``). ``effect_key(process, slot, input_version)`` is ``fx:<process>:<slot>:<ver>``.
  A key held CLAIMED, DONE or UNKNOWN refuses every further claim (``effect_already_claimed``). FAILED and
  RELEASED keys may be claimed again (a retry of an effect that did not happen). UNKNOWN (a timeout, a lost run)
  is never re-claimed automatically: the effect may have happened, so only ``release`` by an operator re-opens it.
* **Owner-epoch fence** (``effect_owners``). Each process has exactly one owner (``cron``, ``n8n`` or ``none`` =
  admission fenced) and an epoch. A claim from a scheduler that is not the owner is refused
  (``effect_fenced_owner``); a claim that names an epoch other than the current one is refused
  (``effect_fenced_epoch``); and a claim whose run was admitted before the current epoch began is refused
  (``effect_fenced_stale_admission``), so a late worker of the old owner cannot act after a switch. A process with
  no owner row refuses every claim (``effect_no_owner``): fail closed. ``set-owner`` moves ownership with a
  compare-and-swap on the epoch (one recorded act; addendum item 2).

Cron side (the same key a cron line claims)::

    python3 scripts/lib/effect_claim.py run --process morning-brief --slot now --input-version v1 \\
        --scheduler cron -- python3 scripts/morning_brief.py --send

``run`` claims, runs the command, and finishes the claim DONE (exit 0), FAILED (exit != 0) or UNKNOWN (killed
by a signal). A refused claim exits 75 (``EX_TEMPFAIL``, the same "skipped" code as ``flock -n``) and runs nothing.
``--slot now`` is the current America/New_York minute as ``YYYYMMDDTHHMM``, the slot format of a server-minted
``d:`` key (scripts/lib/n8n_due.py KEY_RE), so a cron line and the n8n dispatcher name the same slot.

AUTHORITY: READ_ONLY_ADVISORY. Writes only the two tables above in the coordination ledger. No send, no broker.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]

NO_CONSUMER_REASON = (
    "Cron-side wrapper for the semantic effect key (n8n fabric Phase 1, 2026-10-14). No cron line uses it until a "
    "process is prepared for a fenced single-owner cutover; scripts/n8n_run_executor.py imports the library half."
)

CLAIM_SCHEMA = "EffectClaim@v1"
EFFECT_CONFIG_SCHEMA = "N8nEffectKeys@v1"
EFFECT_CONFIG_REL = Path("config") / "n8n_effect_keys.json"
SCHEDULERS = ("cron", "n8n")
OWNERS = SCHEDULERS + ("none",)
STATE_CLAIMED = "CLAIMED"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"
STATE_UNKNOWN = "UNKNOWN"
STATE_RELEASED = "RELEASED"
#: A key in one of these states refuses a new claim.
HELD_STATES = frozenset({STATE_CLAIMED, STATE_DONE, STATE_UNKNOWN})
#: A key in one of these states may be claimed again.
RECLAIMABLE_STATES = frozenset({STATE_FAILED, STATE_RELEASED})
FINISH_STATES = frozenset({STATE_DONE, STATE_FAILED, STATE_UNKNOWN, STATE_RELEASED})
REFUSALS = frozenset(
    {
        "effect_already_claimed",
        "effect_no_owner",
        "effect_fenced_owner",
        "effect_fenced_epoch",
        "effect_fenced_stale_admission",
        "effect_bad_key",
    }
)
PROCESS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
SLOT_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,39}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
KEY_RE = re.compile(
    r"^fx:([a-z0-9][a-z0-9._-]{1,63}):([0-9A-Za-z][0-9A-Za-z._-]{0,39}):([0-9A-Za-z][0-9A-Za-z._-]{0,63})$"
)
#: ``run`` exits with this when the claim is refused (flock -n's "skipped" code; scripts/n8n_run_executor.py
#: FLOCK_CONFLICT_EXIT), so a cron wrapper reads like a lock skip, not a failure.
REFUSED_EXIT = 75
#: ``lane-spec`` exits with this when the lane has no entry in config/n8n_effect_keys.json.
LANE_NOT_KEYED_EXIT = 3
SLOT_TZ = "America/New_York"


class EffectKeyError(ValueError):
    pass


def effect_key(process: str, slot: str, input_version: str) -> str:
    """``fx:<process>:<slot>:<input_version>``. Each part is validated; nothing free-form gets through."""
    if not isinstance(process, str) or not PROCESS_RE.fullmatch(process):
        raise EffectKeyError("bad_process")
    if not isinstance(slot, str) or not SLOT_RE.fullmatch(slot):
        raise EffectKeyError("bad_slot")
    if not isinstance(input_version, str) or not VERSION_RE.fullmatch(input_version):
        raise EffectKeyError("bad_input_version")
    return f"fx:{process}:{slot}:{input_version}"


def parse_effect_key(key: str) -> tuple[str, str, str] | None:
    m = KEY_RE.fullmatch(key or "")
    return None if m is None else (m.group(1), m.group(2), m.group(3))


def slot_now(now: float | None = None) -> str:
    """The current America/New_York minute as ``YYYYMMDDTHHMM`` (the ``d:`` key slot format)."""
    from zoneinfo import ZoneInfo

    instant = datetime.fromtimestamp(now if now is not None else datetime.now(timezone.utc).timestamp(), timezone.utc)
    return instant.astimezone(ZoneInfo(SLOT_TZ)).strftime("%Y%m%dT%H%M")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _ts(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass(frozen=True)
class ClaimResult:
    ok: bool
    key: str
    reason: str | None
    owner: str | None
    epoch: int | None
    attempt: int
    holder: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CLAIM_SCHEMA,
            "ok": self.ok,
            "effect_key": self.key,
            "reason": self.reason,
            "owner": self.owner,
            "epoch": self.epoch,
            "attempt": self.attempt,
            "holder": dict(self.holder) if self.holder else None,
        }


class EffectClaimStore:
    """``effect_claims`` + ``effect_owners`` on the coordination ledger's connection and lock.

    ``ledger`` is a scripts.lib.n8n_coordination_ledger.CoordinationLedger (its ``_conn`` and RLock are shared, so
    a gateway or executor thread never interleaves with another thread's transaction); cross-process safety is
    sqlite's BEGIN IMMEDIATE + busy timeout, as for the ``runs`` table."""

    def __init__(self, ledger: Any) -> None:
        self._l = ledger
        self.lock = ledger.lock
        if not getattr(ledger, "read_only", False):
            with self.lock:
                self._l._conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS effect_owners (
                        process TEXT PRIMARY KEY,
                        owner TEXT NOT NULL,
                        epoch INTEGER NOT NULL,
                        switched_at TEXT NOT NULL,
                        switched_by TEXT,
                        note TEXT
                    );
                    CREATE TABLE IF NOT EXISTS effect_claims (
                        effect_key TEXT PRIMARY KEY,
                        process TEXT NOT NULL,
                        slot TEXT NOT NULL,
                        input_version TEXT NOT NULL,
                        state TEXT NOT NULL,
                        scheduler TEXT NOT NULL,
                        epoch INTEGER NOT NULL,
                        run_id TEXT,
                        attempt INTEGER NOT NULL DEFAULT 1,
                        claimed_at TEXT NOT NULL,
                        finished_at TEXT,
                        fenced_late INTEGER NOT NULL DEFAULT 0,
                        detail TEXT
                    );
                    CREATE INDEX IF NOT EXISTS effect_claims_run ON effect_claims (run_id);
                    """
                )

    # -- owners --
    def owner(self, process: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._l._conn.execute("SELECT * FROM effect_owners WHERE process = ?", (process,)).fetchone()
        return None if row is None else {k: row[k] for k in row.keys()}

    def set_owner(
        self, process: str, owner: str, *, expect_epoch: int | None, by: str, now: float, note: str | None = None
    ) -> dict[str, Any]:
        """Move ownership: epoch + 1, compare-and-swap on ``expect_epoch`` (None only when no row exists yet).
        Raises EffectKeyError("epoch_conflict") when someone else switched first."""
        if not PROCESS_RE.fullmatch(process or ""):
            raise EffectKeyError("bad_process")
        if owner not in OWNERS:
            raise EffectKeyError("bad_owner")
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute("SELECT epoch FROM effect_owners WHERE process = ?", (process,)).fetchone()
                current = None if cur is None else int(cur["epoch"])
                if current != expect_epoch:
                    raise EffectKeyError("epoch_conflict")
                epoch = 1 if current is None else current + 1
                conn.execute(
                    "INSERT INTO effect_owners (process, owner, epoch, switched_at, switched_by, note)"
                    " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(process) DO UPDATE SET owner=excluded.owner,"
                    " epoch=excluded.epoch, switched_at=excluded.switched_at, switched_by=excluded.switched_by,"
                    " note=excluded.note",
                    (process, owner, epoch, _iso(now), by, note),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        out = self.owner(process)
        assert out is not None
        return out

    # -- claims --
    def get(self, key: str) -> dict[str, Any] | None:
        with self.lock:
            row = self._l._conn.execute("SELECT * FROM effect_claims WHERE effect_key = ?", (key,)).fetchone()
        return None if row is None else {k: row[k] for k in row.keys()}

    def claim(
        self,
        key: str,
        *,
        scheduler: str,
        now: float,
        run_id: str | None = None,
        expect_epoch: int | None = None,
        admitted_at: float | None = None,
    ) -> ClaimResult:
        """Claim ``key`` for ``scheduler``. ``admitted_at`` is when the run was admitted (n8n: the ledger row's
        requested_at); a run admitted before the current epoch's ``switched_at`` is fenced."""
        parts = parse_effect_key(key)
        if parts is None or scheduler not in SCHEDULERS:
            return ClaimResult(False, str(key), "effect_bad_key", None, None, 0)
        process, slot, version = parts
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                own = conn.execute("SELECT * FROM effect_owners WHERE process = ?", (process,)).fetchone()
                if own is None:
                    conn.execute("ROLLBACK")
                    return ClaimResult(False, key, "effect_no_owner", None, None, 0)
                owner, epoch = str(own["owner"]), int(own["epoch"])
                reason = None
                if owner != scheduler:
                    reason = "effect_fenced_owner"
                elif expect_epoch is not None and int(expect_epoch) != epoch:
                    reason = "effect_fenced_epoch"
                else:
                    switched = _ts(own["switched_at"])
                    if admitted_at is not None and switched is not None and admitted_at < switched:
                        reason = "effect_fenced_stale_admission"
                if reason is not None:
                    conn.execute("ROLLBACK")
                    return ClaimResult(False, key, reason, owner, epoch, 0)
                held = conn.execute("SELECT * FROM effect_claims WHERE effect_key = ?", (key,)).fetchone()
                if held is not None and str(held["state"]) in HELD_STATES:
                    conn.execute("ROLLBACK")
                    holder = {k: held[k] for k in ("state", "scheduler", "epoch", "run_id", "attempt", "claimed_at")}
                    return ClaimResult(False, key, "effect_already_claimed", owner, epoch, int(held["attempt"]), holder)
                attempt = 1 if held is None else int(held["attempt"]) + 1
                conn.execute(
                    "INSERT INTO effect_claims (effect_key, process, slot, input_version, state, scheduler, epoch,"
                    " run_id, attempt, claimed_at, finished_at, fenced_late, detail)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL)"
                    " ON CONFLICT(effect_key) DO UPDATE SET state=excluded.state, scheduler=excluded.scheduler,"
                    " epoch=excluded.epoch, run_id=excluded.run_id, attempt=excluded.attempt,"
                    " claimed_at=excluded.claimed_at, finished_at=NULL, fenced_late=0, detail=NULL",
                    (key, process, slot, version, STATE_CLAIMED, scheduler, epoch, run_id, attempt, _iso(now)),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return ClaimResult(True, key, None, owner, epoch, attempt)

    def finish(
        self, key: str, *, state: str, now: float, run_id: str | None = None, detail: str | None = None
    ) -> dict[str, Any] | None:
        """CLAIMED -> ``state``. Only the holder (same run_id when one was claimed) finishes; returns the row, or
        None when the key is not CLAIMED by that run. ``fenced_late`` = the owner epoch moved while it ran."""
        if state not in FINISH_STATES:
            raise EffectKeyError("bad_state")
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM effect_claims WHERE effect_key = ?", (key,)).fetchone()
                if row is None or row["state"] != STATE_CLAIMED or (run_id is not None and row["run_id"] != run_id):
                    conn.execute("ROLLBACK")
                    return None
                own = conn.execute("SELECT epoch FROM effect_owners WHERE process = ?", (row["process"],)).fetchone()
                late = 1 if own is None or int(own["epoch"]) != int(row["epoch"]) else 0
                conn.execute(
                    "UPDATE effect_claims SET state = ?, finished_at = ?, fenced_late = ?, detail = ?"
                    " WHERE effect_key = ?",
                    (state, _iso(now), late, (detail or None) and str(detail)[:200], key),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get(key)

    def release(self, key: str, *, by: str, now: float, note: str) -> dict[str, Any] | None:
        """Operator release of a held key (UNKNOWN after a lost run, or a stuck CLAIMED): -> RELEASED."""
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    "UPDATE effect_claims SET state = ?, finished_at = ?, detail = ? WHERE effect_key = ?"
                    " AND state IN (?, ?)",
                    (STATE_RELEASED, _iso(now), f"released by {by}: {note}"[:200], key, STATE_UNKNOWN, STATE_CLAIMED),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return self.get(key) if cur.rowcount else None


# ── executor side: which lanes carry an effect key (config/n8n_effect_keys.json) ──────────────────────────────


def load_effect_lanes(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Every keyed lane: {lane_id: {"process", "input_version", "cron_claim", "n8n_claim"}}.

    ``cron_claim`` (default False) arms the cron side (scripts/effect_claim_cron.sh, the manifest runner);
    ``n8n_claim`` (default True, so an entry written before 2026-10-15 keeps its meaning) arms the executor side.
    A missing file is an empty map; an unreadable or malformed file raises EffectKeyError("effect_config_unreadable")
    so both sides fail closed."""
    p = path or (ROOT / EFFECT_CONFIG_REL)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise EffectKeyError("effect_config_unreadable") from exc
    if not isinstance(doc, dict) or doc.get("schema") != EFFECT_CONFIG_SCHEMA or not isinstance(doc.get("lanes"), dict):
        raise EffectKeyError("effect_config_unreadable")
    out: dict[str, dict[str, Any]] = {}
    for lane, spec in doc["lanes"].items():
        if not isinstance(spec, dict):
            raise EffectKeyError("effect_config_unreadable")
        process, version = spec.get("process"), spec.get("input_version")
        if not (isinstance(process, str) and PROCESS_RE.fullmatch(process)):
            raise EffectKeyError("effect_config_unreadable")
        if not (isinstance(version, str) and VERSION_RE.fullmatch(version)):
            raise EffectKeyError("effect_config_unreadable")
        cron_claim, n8n_claim = spec.get("cron_claim", False), spec.get("n8n_claim", True)
        if not isinstance(cron_claim, bool) or not isinstance(n8n_claim, bool):
            raise EffectKeyError("effect_config_unreadable")
        out[str(lane)] = {
            "process": process,
            "input_version": version,
            "cron_claim": cron_claim,
            "n8n_claim": n8n_claim,
        }
    return out


def load_effect_config(path: Path | None = None) -> dict[str, dict[str, str]]:
    """The executor's view: {lane_id: {"process": ..., "input_version": ...}} for lanes whose n8n side is armed
    (``n8n_claim`` absent or true). A lane keyed with ``n8n_claim: false`` (2026-10-15, the canary-wave keys) is
    staged only: the executor does not claim for it, so its live runs behave exactly as before. A missing file is an
    empty map; an unreadable or malformed file raises EffectKeyError("effect_config_unreadable") (fail closed)."""
    return {
        lane: {"process": spec["process"], "input_version": spec["input_version"]}
        for lane, spec in load_effect_lanes(path).items()
        if spec["n8n_claim"]
    }


# ── CLI (cron side) ─────────────────────────────────────────────────────────────────────────────────────────────


def _open_store(ledger: str | None) -> EffectClaimStore:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger

    if ledger:
        path = Path(ledger)
    else:
        explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
        root = os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
        path = Path(explicit) if explicit else Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    return EffectClaimStore(CoordinationLedger(path))


def _key_from_args(a: argparse.Namespace) -> str:
    slot = slot_now() if a.slot == "now" else a.slot
    return effect_key(a.process, slot, a.input_version)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="effect_claim.py", description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default=None, help="coordination ledger (default: the gateway's)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def keyed(p: argparse.ArgumentParser) -> None:
        p.add_argument("--process", required=True)
        p.add_argument("--slot", required=True, help="YYYYMMDDTHHMM, or 'now' (America/New_York minute)")
        p.add_argument("--input-version", required=True)

    p_key = sub.add_parser("key", help="print the effect key")
    keyed(p_key)
    p_claim = sub.add_parser("claim", help="claim the key; exit 0 claimed, 75 refused")
    keyed(p_claim)
    p_claim.add_argument("--scheduler", choices=SCHEDULERS, required=True)
    p_claim.add_argument("--run-id", default=None)
    p_claim.add_argument("--expect-epoch", type=int, default=None)
    p_fin = sub.add_parser("finish", help="finish a claimed key")
    keyed(p_fin)
    p_fin.add_argument("--state", choices=sorted(FINISH_STATES), required=True)
    p_fin.add_argument("--run-id", default=None)
    p_run = sub.add_parser("run", help="claim, run the command after --, finish by its exit")
    keyed(p_run)
    p_run.add_argument("--scheduler", choices=SCHEDULERS, required=True)
    p_run.add_argument("--expect-epoch", type=int, default=None)
    p_run.add_argument("command", nargs=argparse.REMAINDER)
    p_own = sub.add_parser("set-owner", help="move ownership (epoch + 1, compare-and-swap)")
    p_own.add_argument("--process", required=True)
    p_own.add_argument("--owner", choices=OWNERS, required=True)
    p_own.add_argument("--expect-epoch", type=int, default=None, help="current epoch; omit only for a new process")
    p_own.add_argument("--by", required=True)
    p_own.add_argument("--note", default=None)
    p_show = sub.add_parser("show", help="print the owner row and, with --key, the claim row")
    p_show.add_argument("--process", required=True)
    p_show.add_argument("--key", default=None)
    p_rel = sub.add_parser("release", help="operator release of an UNKNOWN or stuck CLAIMED key")
    p_rel.add_argument("--key", required=True)
    p_rel.add_argument("--by", required=True)
    p_rel.add_argument("--note", required=True)
    p_spec = sub.add_parser(
        "lane-spec",
        help="print a keyed lane's process, input_version and cron_claim (tab-separated; exit 3 = lane not keyed)",
    )
    p_spec.add_argument("--lane", required=True)
    p_spec.add_argument("--config", default=None, help="config/n8n_effect_keys.json (default: this tree's)")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc).timestamp()
    try:
        if a.cmd == "key":
            print(_key_from_args(a))
            return 0
        if a.cmd == "lane-spec":
            spec = load_effect_lanes(Path(a.config) if a.config else None).get(a.lane)
            if spec is None:
                print(json.dumps({"error": "lane_not_keyed", "lane": a.lane}), file=sys.stderr)
                return LANE_NOT_KEYED_EXIT
            print(f"{spec['process']}\t{spec['input_version']}\t{'1' if spec['cron_claim'] else '0'}")
            return 0
        store = _open_store(a.ledger)
        if a.cmd == "claim":
            res = store.claim(
                _key_from_args(a), scheduler=a.scheduler, now=now, run_id=a.run_id, expect_epoch=a.expect_epoch
            )
            print(json.dumps(res.as_dict(), sort_keys=True))
            return 0 if res.ok else REFUSED_EXIT
        if a.cmd == "finish":
            row = store.finish(_key_from_args(a), state=a.state, now=now, run_id=a.run_id)
            print(json.dumps({"finished": row is not None, "row": row}, sort_keys=True, default=str))
            return 0 if row is not None else 1
        if a.cmd == "run":
            cmd = list(a.command)
            if cmd and cmd[0] == "--":
                cmd = cmd[1:]
            if not cmd:
                print(json.dumps({"error": "no command after --"}), file=sys.stderr)
                return 2
            key = _key_from_args(a)
            run_id = f"cron:{key}:{os.getpid()}"
            res = store.claim(key, scheduler=a.scheduler, now=now, run_id=run_id, expect_epoch=a.expect_epoch)
            print(json.dumps(res.as_dict(), sort_keys=True), file=sys.stderr, flush=True)
            if not res.ok:
                return REFUSED_EXIT
            try:
                rc = subprocess.call(cmd)
            except OSError as exc:
                store.finish(
                    key,
                    state=STATE_FAILED,
                    now=datetime.now(timezone.utc).timestamp(),
                    run_id=run_id,
                    detail=f"spawn:{type(exc).__name__}",
                )
                return 127
            state = STATE_DONE if rc == 0 else (STATE_UNKNOWN if rc < 0 else STATE_FAILED)
            store.finish(
                key, state=state, now=datetime.now(timezone.utc).timestamp(), run_id=run_id, detail=f"exit_{rc}"
            )
            return rc if rc >= 0 else 128 - rc
        if a.cmd == "set-owner":
            row = store.set_owner(a.process, a.owner, expect_epoch=a.expect_epoch, by=a.by, now=now, note=a.note)
            print(json.dumps(row, sort_keys=True))
            return 0
        if a.cmd == "show":
            out = {"owner": store.owner(a.process), "claim": store.get(a.key) if a.key else None}
            print(json.dumps(out, sort_keys=True, default=str))
            return 0
        if a.cmd == "release":
            row = store.release(a.key, by=a.by, now=now, note=a.note)
            print(json.dumps({"released": row is not None, "row": row}, sort_keys=True, default=str))
            return 0 if row is not None else 1
    except EffectKeyError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(json.dumps({"error": f"ledger:{type(exc).__name__}"}), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
