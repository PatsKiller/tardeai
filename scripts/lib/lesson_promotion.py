"""lesson_promotion.py — ONE promotion queue from every lesson source into procedural memory (Wave 3 O-W3-2; 04 §5).

Today lessons live in five disconnected stores (advisory KB candidates + "ratified" rows auto-ratified by
iris, LessonCandidate@v2 PROVISIONAL rows, reflection candidates, checkpoint-bound lessons, trade post-mortems)
and nothing reaches ``MemoryContext.lessons`` — the façade hardcodes ``[]`` / ``NONE_PROMOTED``.

This module is the queue and the reader:

* ``gather(root)`` — pure: every candidate the sources expose, normalised to ``Procedure@v1`` shape with
  status CANDIDATE, deduped on a content key; ``enqueue(root)`` appends the new ones to
  ``data/cio/lesson_promotions.jsonl`` (``LessonPromotion@v1`` rows: QUEUED).
* ``decide(lesson_id, PROMOTED|REFUTED|RETIRED, by=operator:…)`` — the ONLY way a lesson becomes procedural
  memory. Operator-only (§17): the CLI batches the queue into an ApprovalPackage; an APPROVE reply promotes.
* ``promoted(root, symbol=None, scope=None)`` — the procedures a MemoryContext should carry; the façade's
  ``lessons`` loader calls this. Returns [] until something is promoted, so shipping this changes no output.

Authority READ_ONLY_ADVISORY; a lesson can never become a behaviour field (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "LessonPromotion@v1"
PROCEDURE_SCHEMA = "Procedure@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
STATUSES = ("QUEUED", "PROMOTED", "REFUTED", "RETIRED")
KINDS = ("LESSON", "PREFERENCE", "PLAYBOOK", "POLICY")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _cio_dir(root: Path | None, env: dict) -> Path:
    try:
        try:
            import intelligence_client as ic  # type: ignore
        except ImportError:
            from scripts.lib import intelligence_client as ic  # type: ignore
        return ic._cio_dir(root, env)
    except Exception:  # noqa: BLE001
        return Path(root or Path.cwd()) / "data" / "cio"


def queue_path(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("TRADEAI_LESSON_QUEUE_PATH") or (_cio_dir(root, env) / "lesson_promotions.jsonl"))


def _read_jsonl(path: Path, limit: int = 200_000) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    break
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return out


def _lesson_key(statement: str, scope: str) -> str:
    norm = " ".join(str(statement or "").lower().split())[:400]
    return "les_" + hashlib.sha256(f"{scope}|{norm}".encode("utf-8")).hexdigest()[:16]


def _procedure(*, statement: str, source: str, source_id: str, kind: str = "LESSON", applies_to: dict | None = None,
               evidence: dict | None = None, confidence: float | None = None, symbols: list | None = None) -> dict | None:
    st = str(statement or "").strip()
    if len(st) < 12:
        return None
    scope = json.dumps(applies_to or {}, sort_keys=True)
    return {"schema": PROCEDURE_SCHEMA, "procedure_id": _lesson_key(st, scope), "kind": kind if kind in KINDS else "LESSON",
            "applies_to": dict(applies_to or {}), "symbols": sorted({str(s).upper() for s in (symbols or []) if s}),
            "statement": st[:1000], "evidence": {"confirming_outcomes": [], "refuting_outcomes": [], **(evidence or {})},
            "confidence": confidence, "status": "CANDIDATE", "source": source, "source_id": str(source_id), "authority": AUTHORITY}


def gather(root: Path | None = None, env: dict | None = None) -> list[dict]:
    """Pure read of every source. Each row is a Procedure@v1 CANDIDATE; deduped on procedure_id."""
    env = os.environ if env is None else env
    cio = _cio_dir(root, env)
    runtime = cio.parent / "runtime"
    out: dict[str, dict] = {}

    def add(p: dict | None):
        if p and p["procedure_id"] not in out:
            out[p["procedure_id"]] = p

    # 1. LessonCandidate@v2 (outcome-derived, PROVISIONAL)
    for r in _read_jsonl(cio / "lesson_candidates.jsonl"):
        if r.get("schema", "").startswith("LessonCandidate"):
            add(_procedure(statement=r.get("statement") or "", source="lesson_candidates", source_id=r.get("lesson_id") or "",
                           applies_to={"scope": r.get("scope"), "task_class": r.get("task_class")},
                           evidence={"supporting_outcome_ids": list(r.get("supporting_outcome_ids") or [])[:20],
                                     "counterexamples": list(r.get("counterexamples") or [])[:10]},
                           symbols=r.get("symbols") or []))
    # 2. advisory KB: candidates + iris-ratified rows (ratified by a machine ≠ promoted by the operator)
    seen_kb: set[str] = set()
    for fname, src in (("advisory_kb_lessons.jsonl", "advisory_kb_ratified"), ("advisory_kb_lesson_candidates.jsonl", "advisory_kb_candidate")):
        for r in _read_jsonl(runtime / fname):
            lid = str(r.get("lesson_id") or r.get("id") or "")
            if not lid or lid in seen_kb or str(r.get("status") or "").lower() == "retired":
                continue
            seen_kb.add(lid)
            add(_procedure(statement=r.get("statement") or r.get("text") or r.get("title") or "", source=src, source_id=lid,
                           kind="PLAYBOOK" if r.get("source") == "reflection_ips" else "LESSON",
                           applies_to={"scope": "advisory", "source": r.get("source")},
                           evidence={"hit_rate": r.get("hit_rate"), "applications": r.get("applications"), "ratified_by": r.get("ratified_by")},
                           symbols=r.get("symbols") or []))
    # 3. nightly reflection candidates
    for r in _read_jsonl(cio / "cio_reflection_candidates.jsonl"):
        if str(r.get("state") or r.get("status") or "").upper() in ("CANDIDATE", "RATIFIED"):
            add(_procedure(statement=r.get("candidate_lesson") or r.get("statement") or r.get("proposal") or "", source="cio_reflection",
                           source_id=r.get("candidate_id") or r.get("id") or "", applies_to={"scope": "cio", "kind": r.get("kind")},
                           symbols=r.get("symbols") or []))
    # 4. procedural hints in durable memory
    for r in _read_jsonl(cio / "aif_memory.jsonl"):
        if r.get("kind") == "PROCEDURAL_HINT" or r.get("memory_type") == "PROCEDURAL_HINT":
            add(_procedure(statement=r.get("content") or r.get("text") or r.get("statement") or "", source="aif_memory",
                           source_id=r.get("memory_id") or r.get("id") or "", applies_to={"scope": r.get("scope") or "agent"},
                           symbols=r.get("symbols") or []))
    return list(out.values())


def enqueue(root: Path | None = None, env: dict | None = None, *, apply: bool = False) -> dict:
    """Append QUEUED rows for candidates not yet on the queue. Dry run by default."""
    env = os.environ if env is None else env
    q = queue_path(root, env)
    existing = {r.get("procedure_id") for r in _read_jsonl(q)}
    cands = gather(root, env)
    new = [c for c in cands if c["procedure_id"] not in existing]
    by_src: dict[str, int] = {}
    for c in new:
        by_src[c["source"]] = by_src.get(c["source"], 0) + 1
    if apply and new:
        q.parent.mkdir(parents=True, exist_ok=True)
        with q.open("a", encoding="utf-8") as fh:
            for c in new:
                fh.write(json.dumps({"schema": SCHEMA, "event": "QUEUED", "ts": _now_iso(), **c, "status": "QUEUED"}, sort_keys=True, default=str) + "\n")
    return {"candidates": len(cands), "already_queued": len(cands) - len(new), "new": len(new), "by_source": by_src,
            "written": len(new) if apply else 0, "path": str(q)}


def state(root: Path | None = None, env: dict | None = None) -> dict[str, dict]:
    """procedure_id → latest row (QUEUED / PROMOTED / REFUTED / RETIRED)."""
    env = os.environ if env is None else env
    latest: dict[str, dict] = {}
    for r in _read_jsonl(queue_path(root, env)):
        pid = r.get("procedure_id")
        if pid:
            latest[pid] = {**latest.get(pid, {}), **r}
    return latest


def decide(procedure_id: str, decision: str, *, by: str, reason: str = "", root: Path | None = None, env: dict | None = None) -> dict:
    """Operator-only transition. `by` must start with 'operator:' (the CLI enforces the package reply path)."""
    env = os.environ if env is None else env
    d = str(decision).upper()
    if d not in ("PROMOTED", "REFUTED", "RETIRED"):
        raise ValueError(f"decision must be PROMOTED|REFUTED|RETIRED, got {decision}")
    if not str(by).startswith("operator:"):
        raise PermissionError("lesson promotion is operator-only (AGENTS §17; 04 §5)")
    cur = state(root, env).get(procedure_id)
    if not cur:
        raise KeyError(f"{procedure_id} is not on the queue")
    row = {"schema": SCHEMA, "event": d, "ts": _now_iso(), "procedure_id": procedure_id, "status": d, "decided_by": by,
           "reason": str(reason)[:400], "promoted_at": _now_iso() if d == "PROMOTED" else None}
    q = queue_path(root, env)
    with q.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def promoted(root: Path | None = None, env: dict | None = None, *, symbol: str | None = None, scope: str | None = None,
             limit: int = 8) -> list[dict]:
    """The procedures a MemoryContext should carry: PROMOTED rows, symbol-scoped ones only for that symbol."""
    env = os.environ if env is None else env
    sym = str(symbol or "").upper()
    out = []
    for pid, r in state(root, env).items():
        if r.get("status") != "PROMOTED":
            continue
        syms = [str(s).upper() for s in (r.get("symbols") or [])]
        if syms and sym and sym not in syms:
            continue
        if scope and str((r.get("applies_to") or {}).get("scope") or "") not in ("", scope):
            continue
        out.append({"procedure_id": pid, "kind": r.get("kind"), "statement": r.get("statement"), "applies_to": r.get("applies_to"),
                    "symbols": syms, "confidence": r.get("confidence"), "promoted_at": r.get("promoted_at"), "decided_by": r.get("decided_by"),
                    "source": r.get("source"), "authority": AUTHORITY})
    return out[:limit]


def package_items(root: Path | None = None, env: dict | None = None, *, limit: int = 20) -> list[dict]:
    """QUEUED lessons as ApprovalPackage items (one per lesson) for the weekly promotion batch."""
    env = os.environ if env is None else env
    items = []
    for i, (pid, r) in enumerate(sorted(state(root, env).items())):
        if r.get("status") != "QUEUED":
            continue
        items.append({"item_id": f"L-{i + 1}", "category": "OPERATOR", "title": f"PROMOTE {pid} [{r.get('source')}]: {str(r.get('statement'))[:160]}",
                      "why": "04 §5 procedural memory", "rule": "§17 operator ratifies", "rollback": f"decide {pid} RETIRED", "scopes_needed": [],
                      "procedure_id": pid})
        if len(items) >= limit:
            break
    return items
