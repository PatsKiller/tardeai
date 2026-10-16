#!/usr/bin/env python3
"""Semantic effect key: one live effect per (business process, slot, input version), whoever fires it.

2026-10-14 (n8n fabric Phase 1; AGENTS.md §23.23 migration rule (4), PROPOSED 10.0.0; REFACTOR_PLAN addendum
items 1 and 2). A shared flock stops a cron run and an n8n run of the same lane from OVERLAPPING. It does not stop
them running one after the other: cron fires the 07:30 slot, finishes and drops the lock, then n8n fires the same
07:30 slot and the effect (a digest, a send, a write) happens twice. Both schedulers therefore claim the same key
in one durable table before the effect, and the second claim of a live key is refused.

Two guards, both in one ``BEGIN IMMEDIATE`` on the coordination ledger file:

* **Key claim** (``effect_claims``). ``effect_key(process, slot, input_version)`` is ``fx:<process>:<slot>:<ver>``.
  A key held CLAIMED, DONE or UNKNOWN refuses every further claim (``effect_already_claimed``). RELEASED keys may
  be claimed again. A FAILED key may be claimed again ONLY when the failure is PROVEN pre-effect (``pre_effect = 1``:
  the spawn failed, or a fence-calling lane exited before passing ``assert_fence``); any other FAILED key is held
  exactly like UNKNOWN (2026-10-15 third-party audit DD05: "FAILED claims can be reclaimed without proving that no
  external effect occurred" - a target write followed by a non-zero exit used to reopen the key). UNKNOWN (a
  timeout, a lost run, an unproven failure) is never re-claimed automatically: the effect may have happened, so only
  ``release`` by an operator re-opens it.
* **Late-write fence** (2026-10-15, audit DD06). The owner-epoch fence below acts at ADMISSION; it cannot stop a
  worker that is already running. Every claim therefore hands the lane a fencing token
  ``TRADEAI_EFFECT_FENCE=<key>:<epoch>:<attempt>`` (the executor and ``run`` both set it), and a lane calls
  ``assert_fence()`` immediately before its target write: it refuses (``EffectFenceError``) when the claim was
  released, re-claimed (attempt moved), re-owned (epoch moved) or finished. ONLY a lane that calls it is late-write
  safe; ``late_write_fenced: true`` in config/n8n_effect_keys.json declares that it does (a test checks the
  declaration against the lane's source). Today NO keyed lane calls it (N8N_CONTRACTS_DESIGN.md section 7 lists
  them). A finish that arrives after the owner epoch moved is a LATE COMPLETION: the key becomes UNKNOWN with
  ``fenced_late = 1`` and detail ``late_completion:<state>`` (an actionable incident for the operator), never a
  silent DONE.
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
#: A key in one of these states may be claimed again (FAILED only with ``pre_effect = 1``: see ``_is_held``).
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
#: assert_fence refusals (EffectFenceError.reason).
FENCE_REFUSALS = frozenset(
    {
        "fence_missing",
        "fence_malformed",
        "fence_store_unavailable",
        "fence_claim_missing",
        "fence_claim_not_held",
        "fence_attempt_moved",
        "fence_epoch_moved",
        "fence_no_owner",
    }
)
FENCE_ENV = "TRADEAI_EFFECT_FENCE"
#: The coordination ledger the fence is checked against (the executor sets it next to the token).
FENCE_LEDGER_ENV = "TRADEAI_EFFECT_FENCE_LEDGER"
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


class EffectFenceError(RuntimeError):
    """``assert_fence`` refused: the lane must NOT perform its target write."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def fence_token(key: str, epoch: int, attempt: int) -> str:
    return f"{key}:{int(epoch)}:{int(attempt)}"


def parse_fence_token(token: Any) -> tuple[str, int, int] | None:
    try:
        key, epoch, attempt = str(token).rsplit(":", 2)
        parsed = (key, int(epoch), int(attempt))
    except (ValueError, TypeError):
        return None
    return parsed if parse_effect_key(parsed[0]) else None


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


def _is_held(row: Any) -> bool:
    """A claim row refuses a new claim: CLAIMED / DONE / UNKNOWN, or FAILED without proof it preceded the effect."""
    state = str(row["state"])
    if state in HELD_STATES:
        return True
    if state == STATE_FAILED:
        try:
            return not bool(row["pre_effect"])
        except (IndexError, KeyError):
            return True
    return False


def assert_fence(token: str | None = None, *, ledger: str | Path | None = None, now: float | None = None) -> dict:
    """The lane-side late-write fence (DD06). Call it immediately before the target write::

        from scripts.lib.effect_claim import assert_fence
        assert_fence()          # raises EffectFenceError -> do not write

    ``token`` defaults to $TRADEAI_EFFECT_FENCE; ``ledger`` to $TRADEAI_EFFECT_FENCE_LEDGER, else the gateway's
    default ledger. No token = ``fence_missing`` (a lane that declares ``late_write_fenced`` must never write
    unfenced). The store being unreadable = ``fence_store_unavailable`` (fail closed)."""
    tok = token if token is not None else os.environ.get(FENCE_ENV)
    if not tok:
        raise EffectFenceError("fence_missing")
    try:
        store = _open_store(str(ledger) if ledger else (os.environ.get(FENCE_LEDGER_ENV) or None))
        return store.assert_fence(tok, now=now if now is not None else datetime.now(timezone.utc).timestamp())
    except (sqlite3.Error, OSError) as exc:
        raise EffectFenceError("fence_store_unavailable") from exc


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
                # 2026-10-15 (audit DD05/DD06): additive columns. pre_effect = the FAILED finish is proven to precede
                # any target effect (only then is FAILED reclaimable); fence_passed_at = the lane passed assert_fence.
                cols = {r[1] for r in self._l._conn.execute("PRAGMA table_info(effect_claims)").fetchall()}
                for name, decl in (("pre_effect", "INTEGER NOT NULL DEFAULT 0"), ("fence_passed_at", "TEXT")):
                    if name not in cols:
                        self._l._conn.execute(f"ALTER TABLE effect_claims ADD COLUMN {name} {decl}")

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
                if held is not None and _is_held(held):
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
                    " claimed_at=excluded.claimed_at, finished_at=NULL, fenced_late=0, detail=NULL, pre_effect=0,"
                    " fence_passed_at=NULL",
                    (key, process, slot, version, STATE_CLAIMED, scheduler, epoch, run_id, attempt, _iso(now)),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return ClaimResult(True, key, None, owner, epoch, attempt)

    def finish(
        self,
        key: str,
        *,
        state: str,
        now: float,
        run_id: str | None = None,
        detail: str | None = None,
        pre_effect: bool = False,
    ) -> dict[str, Any] | None:
        """CLAIMED -> ``state``. Only the holder (same run_id when one was claimed) finishes; returns the row, or
        None when the key is not CLAIMED by that run.

        ``pre_effect`` (FAILED only) records that the failure is PROVEN to precede any target effect; only such a
        FAILED key is reclaimable (DD05). A finish after the owner epoch moved (``fenced_late``) is a LATE COMPLETION:
        DONE / FAILED become UNKNOWN (held for operator reconciliation) with detail ``late_completion:<state>``
        (DD06); the returned row carries ``late_completion: True``."""
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
                final, note = state, (str(detail)[:200] if detail else None)
                if late and state in (STATE_DONE, STATE_FAILED):
                    final = STATE_UNKNOWN
                    note = (f"late_completion:{state}" + (f" {detail}" if detail else ""))[:200]
                proven = 1 if (final == STATE_FAILED and pre_effect) else 0
                conn.execute(
                    "UPDATE effect_claims SET state = ?, finished_at = ?, fenced_late = ?, detail = ?, pre_effect = ?"
                    " WHERE effect_key = ?",
                    (final, _iso(now), late, note, proven, key),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        out = self.get(key)
        if out is not None:
            out["late_completion"] = bool(late and state in (STATE_DONE, STATE_FAILED))
        return out

    def fence_passed(self, key: str) -> bool:
        row = self.get(key)
        return bool(row and row.get("fence_passed_at"))

    def assert_fence(self, token: str, *, now: float) -> dict[str, Any]:
        """Refuse (EffectFenceError) unless the claim named by ``token`` is still CLAIMED at that attempt and the
        process owner epoch is unchanged; on success records ``fence_passed_at`` (first pass) and returns the row.
        A lane calls this IMMEDIATELY before its target write (late-write fence, DD06)."""
        parsed = parse_fence_token(token)
        if parsed is None:
            raise EffectFenceError("fence_malformed")
        key, epoch, attempt = parsed
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM effect_claims WHERE effect_key = ?", (key,)).fetchone()
                reason = None
                if row is None:
                    reason = "fence_claim_missing"
                elif row["state"] != STATE_CLAIMED:
                    reason = "fence_claim_not_held"
                elif int(row["attempt"]) != attempt:
                    reason = "fence_attempt_moved"
                elif int(row["epoch"]) != epoch:
                    reason = "fence_epoch_moved"
                else:
                    own = conn.execute(
                        "SELECT epoch FROM effect_owners WHERE process = ?", (row["process"],)
                    ).fetchone()
                    if own is None:
                        reason = "fence_no_owner"
                    elif int(own["epoch"]) != epoch:
                        reason = "fence_epoch_moved"
                if reason is None:
                    conn.execute(
                        "UPDATE effect_claims SET fence_passed_at = COALESCE(fence_passed_at, ?) WHERE effect_key = ?",
                        (_iso(now), key),
                    )
                    conn.execute("COMMIT")
                else:
                    conn.execute("ROLLBACK")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        if reason is not None:
            raise EffectFenceError(reason)
        out = self.get(key)
        assert out is not None
        return out

    def release(self, key: str, *, by: str, now: float, note: str) -> dict[str, Any] | None:
        """Operator release of a held key (UNKNOWN after a lost run, a FAILED not proven pre-effect, or a stuck CLAIMED): -> RELEASED."""
        with self.lock:
            conn = self._l._conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    "UPDATE effect_claims SET state = ?, finished_at = ?, detail = ? WHERE effect_key = ?"
                    " AND state IN (?, ?, ?)",
                    (STATE_RELEASED, _iso(now), f"released by {by}: {note}"[:200], key, STATE_UNKNOWN, STATE_CLAIMED, STATE_FAILED),
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
        if not isinstance(spec.get("late_write_fenced", False), bool):
            raise EffectKeyError("effect_config_unreadable")
        out[str(lane)] = {
            "process": process,
            "input_version": version,
            "cron_claim": cron_claim,
            "n8n_claim": n8n_claim,
        }
    return out


def load_fenced_lanes(path: Path | None = None) -> frozenset[str]:
    """Lanes whose config entry declares ``late_write_fenced: true``: their command calls ``assert_fence()`` before
    the target write (2026-10-15, audit DD06), so a non-zero exit BEFORE the fence passed is proven pre-effect.
    tests/test_n8n_audit_findings_20261015.py checks each declaration against the lane's source. Empty today."""
    p = path or (ROOT / EFFECT_CONFIG_REL)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return frozenset()
    except (OSError, json.JSONDecodeError) as exc:
        raise EffectKeyError("effect_config_unreadable") from exc
    lanes = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(lanes, dict):
        raise EffectKeyError("effect_config_unreadable")
    return frozenset(str(k) for k, v in lanes.items() if isinstance(v, dict) and v.get("late_write_fenced") is True)


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

    return EffectClaimStore(CoordinationLedger(_ledger_path(ledger)))


def _ledger_path(ledger: str | None) -> Path:
    if ledger:
        return Path(ledger)
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    root = os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(explicit) if explicit else Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def owner_read_only(process: str, ledger: str | None = None) -> str:
    """The process's owner ("cron", "n8n") or "none", from a mode=ro open that never creates or migrates the ledger.
    Raises sqlite3.Error when the ledger is unreachable (missing file, locked past the busy timeout, corrupt)."""
    path = _ledger_path(ledger)
    if not path.exists():
        raise sqlite3.OperationalError("ledger_missing")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='effect_owners'").fetchone()
        if has is None:
            return "none"
        row = conn.execute("SELECT owner FROM effect_owners WHERE process = ?", (process,)).fetchone()
        return "none" if row is None else str(row[0])
    finally:
        conn.close()


# ── durable handover manifest (2026-10-16, architect review: fail CLOSED for handed-over lanes) ──────────────────
#
# The cron wrapper (scripts/effect_claim_cron.sh) used to FAIL OPEN whenever the ledger could not be read: the cron
# copy ran unclaimed. The shared flock stops an overlap but not a second run after the first finished, so for a lane
# already HANDED OVER to n8n an unreadable ledger re-opened the double effect. The wrapper must therefore know, without
# the ledger, whether a process was handed over. That is this manifest:
#
# * path: $TRADEAI_N8N_HANDOVER_MANIFEST, else ``n8n_handover_manifest.json`` beside the coordination ledger
#   (default <state>/data/governance/n8n_handover_manifest.json). A plain JSON file, not sqlite: a locked, corrupt or
#   missing ledger does not make it unreadable.
# * schema ``N8nHandoverManifest@v1``: {"schema", "updated_at", "processes": {process: {"owner", "epoch",
#   "switched_at", "by"}}}. ``owner`` is the LAST owner ``set-owner`` recorded.
# * writer: ONLY ``effect_claim.py set-owner`` (and the one-time bootstrap ``handover-seed``), under an exclusive
#   flock on ``<manifest>.lock``, by write-to-temp + fsync + rename + directory fsync (atomic: a reader sees the old or
#   the new file, never a torn one). The wrapper and every reporter open it read-only.
# * ordering (so a crash leaves the two stores disagreeing only in the SAFE direction): a switch TO n8n writes the
#   manifest first, then the ledger (a refused compare-and-swap restores the prior manifest entry under the same lock);
#   a switch AWAY from n8n writes the ledger first, then the manifest. Either crash leaves "manifest n8n / ledger not",
#   which the wrapper treats as ownership unknown: fail closed + P1.
# * the controller (scripts/nightly_cutover_controller.py) holds the same lock across each lane's re-check and
#   mutation (the fenced handover), so no owner switch can land between its check and its edit.
#
# Never auto-reconciled (AGENTS.md §0 rule 5): a disagreement is reported with both values and the run is skipped.

HANDOVER_SCHEMA = "N8nHandoverManifest@v1"
HANDOVER_ENV = "TRADEAI_N8N_HANDOVER_MANIFEST"
HANDOVER_NAME = "n8n_handover_manifest.json"
HANDOVER_LOCK_TIMEOUT_S = 30.0
#: ``ownership`` decisions (the wrapper reads the first tab-separated field).
DECIDE_RUN = "run"
DECIDE_SKIP_N8N = "skip_owner_n8n"
DECIDE_SKIP_UNKNOWN = "skip_ownership_unknown"


class HandoverLockTimeout(RuntimeError):
    pass


def handover_manifest_path(ledger: str | Path | None = None) -> Path:
    explicit = os.environ.get(HANDOVER_ENV)
    if explicit:
        return Path(explicit)
    return _ledger_path(str(ledger) if ledger else None).parent / HANDOVER_NAME


def read_handover_manifest(path: Path) -> dict[str, Any] | None:
    """The manifest document, or None when the file does not exist (no process was ever handed over through
    set-owner on this host). Unreadable / malformed -> EffectKeyError("handover_manifest_unreadable")."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise EffectKeyError("handover_manifest_unreadable") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EffectKeyError("handover_manifest_unreadable") from exc
    if not isinstance(doc, dict) or doc.get("schema") != HANDOVER_SCHEMA or not isinstance(doc.get("processes"), dict):
        raise EffectKeyError("handover_manifest_unreadable")
    for proc, ent in doc["processes"].items():
        if not isinstance(ent, dict) or ent.get("owner") not in OWNERS or not PROCESS_RE.fullmatch(str(proc)):
            raise EffectKeyError("handover_manifest_unreadable")
    return doc


class handover_lock:  # noqa: N801 - used as a context manager
    """Exclusive flock on ``<manifest>.lock`` (blocking up to ``timeout`` seconds, then HandoverLockTimeout)."""

    def __init__(self, manifest: Path, timeout: float = HANDOVER_LOCK_TIMEOUT_S) -> None:
        self.path = Path(str(manifest) + ".lock")
        self.timeout = timeout
        self.fd: int | None = None

    def __enter__(self) -> "handover_lock":
        import fcntl
        import time as _time

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        end = _time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if _time.monotonic() >= end:
                    os.close(self.fd)
                    self.fd = None
                    raise HandoverLockTimeout(str(self.path))
                _time.sleep(0.05)

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)  # closing the descriptor drops the flock
            self.fd = None


def _write_manifest_atomic(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _manifest_put(path: Path, process: str, entry: Mapping[str, Any] | None, now: float) -> None:
    """Set (or, with entry None, remove) one process entry. Caller holds handover_lock."""
    doc = read_handover_manifest(path) or {"schema": HANDOVER_SCHEMA, "processes": {}}
    procs = dict(doc["processes"])
    if entry is None:
        procs.pop(process, None)
    else:
        procs[process] = dict(entry)
    _write_manifest_atomic(path, {"schema": HANDOVER_SCHEMA, "updated_at": _iso(now), "processes": procs})


def set_owner_with_manifest(
    store: "EffectClaimStore", manifest: Path, process: str, owner: str, *, expect_epoch: int | None, by: str,
    now: float, note: str | None = None,
) -> dict[str, Any]:
    """``set-owner`` with the manifest kept in the safe order (see the block comment above). Under handover_lock."""
    if not PROCESS_RE.fullmatch(process or ""):
        raise EffectKeyError("bad_process")
    if owner not in OWNERS:
        raise EffectKeyError("bad_owner")
    with handover_lock(manifest):
        prior_doc = read_handover_manifest(manifest)
        prior = (prior_doc or {}).get("processes", {}).get(process)
        planned_epoch = 1 if expect_epoch is None else int(expect_epoch) + 1
        entry = {"owner": owner, "epoch": planned_epoch, "switched_at": _iso(now), "by": by}
        if owner == "n8n":
            _manifest_put(manifest, process, entry, now)          # 1. intent: handed over (safe direction)
            try:
                row = store.set_owner(process, owner, expect_epoch=expect_epoch, by=by, now=now, note=note)
            except Exception:
                _manifest_put(manifest, process, prior, now)      # the switch did not happen: restore our own entry
                raise
            if int(row["epoch"]) != planned_epoch:
                _manifest_put(manifest, process, dict(entry, epoch=int(row["epoch"])), now)
            return row
        row = store.set_owner(process, owner, expect_epoch=expect_epoch, by=by, now=now, note=note)
        _manifest_put(manifest, process, dict(entry, epoch=int(row["epoch"])), now)   # 2. after the ledger
        return row


def ownership_decision(process: str, *, ledger: str | None = None, manifest: Path | None = None) -> dict[str, Any]:
    """Whether a cron copy of ``process`` may run, from the ledger (read-only) AND the handover manifest.

    decision ``run`` / ``skip_owner_n8n`` / ``skip_ownership_unknown``; ``p1`` True when the operator must be told
    (ownership could not be established for a handed-over process, or the two stores disagree). Never writes."""
    mpath = manifest or handover_manifest_path(ledger)
    try:
        ledger_owner = owner_read_only(process, ledger)
    except (sqlite3.Error, OSError):
        ledger_owner = "unreachable"
    try:
        doc = read_handover_manifest(mpath)
        if doc is None:
            manifest_owner = "file_absent"
        else:
            ent = doc["processes"].get(process)
            manifest_owner = "not_listed" if ent is None else str(ent["owner"])
    except EffectKeyError:
        manifest_owner = "unreadable"
    out = {"process": process, "ledger_owner": ledger_owner, "manifest_owner": manifest_owner,
           "manifest": str(mpath), "decision": DECIDE_RUN, "reason": "", "p1": False}

    def skip_unknown(reason: str) -> dict[str, Any]:
        out.update(decision=DECIDE_SKIP_UNKNOWN, reason=reason, p1=True)
        return out

    if manifest_owner == "unreadable":
        return skip_unknown("handover_manifest_unreadable")
    if ledger_owner == "unreachable":
        if manifest_owner in ("n8n", "none"):
            return skip_unknown(f"ledger_unreachable_handed_over:manifest={manifest_owner}")
        out["reason"] = f"ledger_unreachable_never_handed_over:manifest={manifest_owner}"
        return out                                                # fail OPEN: this process was never handed over
    if manifest_owner in ("n8n", "cron", "none") and manifest_owner != ledger_owner:
        return skip_unknown(f"manifest_ledger_disagree:manifest={manifest_owner},ledger={ledger_owner}")
    if ledger_owner == "n8n" and manifest_owner in ("file_absent", "not_listed"):
        return skip_unknown(f"manifest_ledger_disagree:manifest={manifest_owner},ledger=n8n")
    if ledger_owner == "n8n":
        out.update(decision=DECIDE_SKIP_N8N, reason="owner_n8n")
        return out
    out["reason"] = f"owner_{ledger_owner}"
    return out


def handover_seed(ledger: str | None, manifest: Path, *, apply: bool, by: str, now: float) -> dict[str, Any]:
    """One-time bootstrap: create the manifest from the ledger's owner rows. Refuses when the manifest already exists
    (never a reconcile of two divergent stores). Dry run unless ``apply``."""
    path = _ledger_path(ledger)
    if not path.exists():
        raise sqlite3.OperationalError("ledger_missing")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='effect_owners'").fetchone()
        rows = [] if has is None else conn.execute(
            "SELECT process, owner, epoch, switched_at FROM effect_owners ORDER BY process").fetchall()
    finally:
        conn.close()
    procs = {str(p): {"owner": str(o), "epoch": int(e), "switched_at": str(s), "by": f"handover-seed:{by}"}
             for p, o, e, s in rows}
    out = {"manifest": str(manifest), "apply": apply, "processes": procs, "written": False}
    with handover_lock(manifest):
        if Path(manifest).exists():
            out["refused"] = "manifest_exists: seed is a one-time bootstrap; compare with `ownership` instead"
            return out
        if apply:
            _write_manifest_atomic(Path(manifest), {"schema": HANDOVER_SCHEMA, "updated_at": _iso(now),
                                                    "processes": procs})
            out["written"] = True
    return out


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
    p_run.add_argument(
        "--fenced",
        action="store_true",
        help="the command calls assert_fence() before its target write: a non-zero exit before the fence passed is "
        "proven pre-effect (FAILED, reclaimable); without it every non-zero exit is held (DD05)",
    )
    p_run.add_argument(
        "--decision-out",
        default=None,
        help="write the claim decision JSON to this file BEFORE the command runs (2026-10-16, cron effect-claim "
        "wrap): no file = the claim was never decided (ledger unreachable), so the caller knows the command did "
        "not run; a refusal names its reason (effect_fenced_owner = another scheduler owns the process)",
    )
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
    p_owner = sub.add_parser(
        "owner",
        help="print the process's owner (cron, n8n or none) from a READ-ONLY ledger open; exit 2 = ledger unreachable",
    )
    p_owner.add_argument("--process", required=True)
    p_own.add_argument("--manifest", default=None, help="handover manifest (default: beside the ledger)")
    p_dec = sub.add_parser(
        "ownership",
        help="may the cron copy run? prints decision<TAB>ledger_owner<TAB>manifest_owner<TAB>p1<TAB>reason from a "
        "read-only ledger open AND the handover manifest (never writes); exit 0 whenever a decision was made",
    )
    p_dec.add_argument("--process", required=True)
    p_dec.add_argument("--manifest", default=None)
    p_dec.add_argument("--json", action="store_true")
    p_seed = sub.add_parser("handover-seed", help="one-time: create the handover manifest from the ledger owner rows")
    p_seed.add_argument("--manifest", default=None)
    p_seed.add_argument("--by", required=True)
    p_seed.add_argument("--apply", action="store_true", help="write it (default: dry run)")
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
        if a.cmd == "owner":
            print(owner_read_only(a.process, a.ledger))
            return 0
        if a.cmd == "ownership":
            d = ownership_decision(a.process, ledger=a.ledger, manifest=Path(a.manifest) if a.manifest else None)
            if a.json:
                print(json.dumps(d, sort_keys=True))
            else:
                print("\t".join([d["decision"], d["ledger_owner"], d["manifest_owner"], "1" if d["p1"] else "0",
                                 d["reason"]]))
            return 0
        if a.cmd == "handover-seed":
            mpath = Path(a.manifest) if a.manifest else handover_manifest_path(a.ledger)
            out = handover_seed(a.ledger, mpath, apply=a.apply, by=a.by, now=now)
            print(json.dumps(out, sort_keys=True))
            return 1 if out.get("refused") else 0
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
            if a.decision_out:
                try:
                    Path(a.decision_out).write_text(json.dumps(res.as_dict(), sort_keys=True) + "\n")
                except OSError as exc:
                    if res.ok:  # nothing spawned yet: proven no effect, so the key stays reclaimable
                        store.finish(key, state=STATE_FAILED, now=datetime.now(timezone.utc).timestamp(),
                                     run_id=run_id, detail=f"decision_out:{type(exc).__name__}", pre_effect=True)
                    print(json.dumps({"error": f"decision_out:{type(exc).__name__}"}), file=sys.stderr)
                    return 2
            if not res.ok:
                return REFUSED_EXIT
            child_env = dict(os.environ)
            child_env[FENCE_ENV] = fence_token(key, int(res.epoch or 0), res.attempt)
            try:
                rc = subprocess.call(cmd, env=child_env)
            except OSError as exc:
                store.finish(
                    key,
                    state=STATE_FAILED,
                    now=datetime.now(timezone.utc).timestamp(),
                    run_id=run_id,
                    detail=f"spawn:{type(exc).__name__}",
                    pre_effect=True,  # nothing was spawned: proven no effect
                )
                return 127
            state = STATE_DONE if rc == 0 else (STATE_UNKNOWN if rc < 0 else STATE_FAILED)
            proven = state == STATE_FAILED and bool(a.fenced) and not store.fence_passed(key)
            store.finish(
                key,
                state=state,
                now=datetime.now(timezone.utc).timestamp(),
                run_id=run_id,
                detail=f"exit_{rc}",
                pre_effect=proven,
            )
            return rc if rc >= 0 else 128 - rc
        if a.cmd == "set-owner":
            mpath = Path(a.manifest) if a.manifest else handover_manifest_path(a.ledger)
            try:
                row = set_owner_with_manifest(store, mpath, a.process, a.owner, expect_epoch=a.expect_epoch,
                                              by=a.by, now=now, note=a.note)
            except HandoverLockTimeout as exc:
                print(json.dumps({"error": f"handover_lock_timeout:{exc}"}), file=sys.stderr)
                return 2
            except OSError as exc:  # the manifest write failed: the stores may disagree (safe direction) - say so
                print(json.dumps({"error": f"handover_manifest_write:{type(exc).__name__}",
                                  "manifest": str(mpath)}), file=sys.stderr)
                return 2
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
