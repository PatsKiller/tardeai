"""cognitive_checkpoint.py — CognitiveCheckpoint@v1 / ResumeReceipt@v1 (Wave 3 item O-W3-1; 04 §3–§4).

Working + episodic memory per agent so a restart is thought continuity instead of a re-read of files.
One append-only, hash-chained JSONL per agent under ``<state>/data/cio/agent_checkpoints/<agent_id>.jsonl``.

* ``write(...)`` — called by the façade on every commit (auto: task_ref from the outcome ref, subjects from
  the context) or by an agent with the full cognitive fields (considered / waiting_on / next_action).
* ``restore(agent_id, task_ref=None)`` — the last checkpoint for the agent (or for one task), plus a
  ``ResumeReceipt@v1`` row. Deterministic and replayable. A restored checkpoint carries NO authority: the
  agent re-opens a MemoryContext and re-validates; a contradiction or refuted belief that touches a KEPT
  option is marked RECONSIDER by the caller.

Kill switch ``TRADEAI_COGNITIVE_CHECKPOINT=0`` (no writes, restore returns None). Authority READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "CognitiveCheckpoint@v1"
RESUME_SCHEMA = "ResumeReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
TASK_PREFIXES = ("WAKE:", "RUN:", "JOB:", "CTX:")
WAITING_KINDS = ("RESEARCH", "OPERATOR", "OUTCOME", "LANE")
VERDICTS = ("KEPT", "RULED_OUT")


def enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("TRADEAI_COGNITIVE_CHECKPOINT", "1")).lower() not in ("0", "false", "off")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _lib(name: str):
    try:
        return __import__(name)
    except ImportError:
        pass
    for prefix in ("lib.", "scripts.lib."):
        try:
            return __import__(prefix + name, fromlist=[name])
        except ImportError:
            continue
    raise ImportError(name)


def checkpoints_dir(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_CHECKPOINTS_DIR"):
        return Path(env["TRADEAI_CHECKPOINTS_DIR"])
    return _lib("intelligence_client")._cio_dir(root, env) / "agent_checkpoints"


def _agent_path(agent_id: str, root: Path | None, env: dict) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(agent_id or "unknown"))[:64]
    return checkpoints_dir(root, env) / f"{safe}.jsonl"


def _hash(row: dict) -> str:
    keep = {k: v for k, v in row.items() if k != "hash_self"}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _read(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return out


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def last(agent_id: str, *, task_ref: str | None = None, root: Path | None = None, env: dict | None = None) -> dict | None:
    """The newest checkpoint for the agent (optionally for one task_ref). None when there is none."""
    env = os.environ if env is None else env
    rows = _read(_agent_path(agent_id, root, env))
    if task_ref:
        rows = [r for r in rows if r.get("task_ref") == task_ref]
    return rows[-1] if rows else None


def write(agent_id: str, *, lane_id: str | None, task_ref: str, subjects: Iterable[str] = (), context_id: str | None = None,
          intent: dict | None = None, considered: Iterable[dict] = (), waiting_on: Iterable[dict] = (),
          commitments_open: Iterable[str] = (), next_action: dict | None = None, provisional_view: str | None = None,
          resumed_from: str | None = None, release_sha: str | None = None, boot_id: str | None = None,
          root: Path | None = None, env: dict | None = None) -> dict | None:
    """Append one checkpoint (step = previous step + 1 for the same task; hash-chained per agent). Never raises."""
    env = os.environ if env is None else env
    if not enabled(env):
        return None
    try:
        tref = str(task_ref or "")
        if not tref.startswith(TASK_PREFIXES):
            tref = "CTX:" + tref
        path = _agent_path(agent_id, root, env)
        rows = _read(path)
        prev = rows[-1] if rows else None
        same_task = [r for r in rows if r.get("task_ref") == tref]
        step = (int(same_task[-1].get("step") or 0) + 1) if same_task else 1
        cons = []
        for c in considered or ():
            if isinstance(c, dict) and c.get("option"):
                v = str(c.get("verdict") or "KEPT").upper()
                cons.append({"option": str(c["option"])[:200], "verdict": v if v in VERDICTS else "KEPT",
                             "reason": str(c.get("reason") or "")[:300], "evidence_refs": list(c.get("evidence_refs") or [])[:10]})
        waits = []
        for w in waiting_on or ():
            if isinstance(w, dict) and w.get("ref"):
                k = str(w.get("kind") or "OUTCOME").upper()
                waits.append({"kind": k if k in WAITING_KINDS else "OUTCOME", "ref": str(w["ref"])[:200],
                              "since": w.get("since") or _now_iso(), "deadline": w.get("deadline")})
        row = {
            "schema": SCHEMA, "checkpoint_id": "ckpt_" + hashlib.sha256(f"{agent_id}|{tref}|{step}|{_now_iso()}".encode()).hexdigest()[:16],
            "agent_id": str(agent_id), "lane_id": lane_id, "release_sha": release_sha or env.get("TRADEAI_RELEASE_SHA"),
            "boot_id": boot_id, "task_ref": tref, "subjects": sorted({str(s) for s in subjects if s}),
            "intent": dict(intent or {}), "step": step, "context_id": context_id, "considered": cons, "waiting_on": waits,
            "commitments_open": [str(c) for c in commitments_open or ()][:50],
            "next_action": dict(next_action or {}) or None, "provisional_view": provisional_view,
            "resumed_from": resumed_from, "written_at": _now_iso(),
            "hash_prev": (prev or {}).get("hash_self"), "authority": AUTHORITY, "memory_behavior_influence": 0,
        }
        row["hash_self"] = _hash(row)
        _append(path, row)
        return row
    except Exception:  # noqa: BLE001 — a checkpoint must never take the agent down
        return None


def restore(agent_id: str, *, task_ref: str | None = None, lane_id: str | None = None, now: _dt.datetime | None = None,
            root: Path | None = None, env: dict | None = None, write_receipt: bool = True) -> dict | None:
    """04 §4 steps 1, 3 and 6: load the last checkpoint (by task when given), settle waits past deadline,
    emit a ResumeReceipt@v1. Steps 2 and 4 (reconcile via GIR, RECONSIDER on contradictions) are the
    caller's, done by re-opening a MemoryContext. Returns {checkpoint, waiting_open, waiting_settled,
    commitments_open, next_action, receipt} or None."""
    env = os.environ if env is None else env
    if not enabled(env):
        return None
    try:
        ck = last(agent_id, task_ref=task_ref, root=root, env=env)
        if not ck:
            return None
        now = now or _dt.datetime.now(_dt.timezone.utc)
        open_w, settled = [], []
        for w in ck.get("waiting_on") or []:
            dl = w.get("deadline")
            try:
                past = bool(dl) and _dt.datetime.fromisoformat(str(dl).replace("Z", "+00:00")) < now
            except ValueError:
                past = False
            (settled if past else open_w).append(w)
        receipt = {"schema": RESUME_SCHEMA, "agent_id": str(agent_id), "lane_id": lane_id, "resumed_from": ck.get("checkpoint_id"),
                   "task_ref": ck.get("task_ref"), "step": ck.get("step"), "waiting_open": len(open_w), "waiting_settled": len(settled),
                   "commitments_open": len(ck.get("commitments_open") or []), "next_action": ck.get("next_action"),
                   "resumed_at": now.isoformat(), "authority": AUTHORITY, "memory_behavior_influence": 0}
        if write_receipt:
            _append(checkpoints_dir(root, env) / "resume_receipts.jsonl", receipt)
        return {"checkpoint": ck, "waiting_open": open_w, "waiting_settled": settled,
                "commitments_open": list(ck.get("commitments_open") or []), "next_action": ck.get("next_action"), "receipt": receipt}
    except Exception:  # noqa: BLE001
        return None


def verify_chain(agent_id: str, *, root: Path | None = None, env: dict | None = None) -> tuple[bool, int, str | None]:
    env = os.environ if env is None else env
    rows = _read(_agent_path(agent_id, root, env))
    prev = None
    for i, r in enumerate(rows):
        if r.get("hash_prev") != prev:
            return False, i, "hash_prev mismatch"
        if _hash(r) != r.get("hash_self"):
            return False, i, "hash_self mismatch"
        prev = r.get("hash_self")
    return True, len(rows), None
