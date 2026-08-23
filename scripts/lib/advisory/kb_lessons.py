"""Advisory Desk L4-D — durable lessons (Iris-curated).

Storage: data/runtime/advisory_kb_lessons.jsonl (+ optional Postgres later).
Embeddings: approved pinned nomic model; fallback deterministic hash embed.

Rules (design §5.4):
  - Lessons are advisory context, never rules
  - Max 5 injected per row
  - Auto-retire hit_rate < 40% over ≥20 applications
  - Nightly reflection proposes; Iris ratifies
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
LESSONS_PATH = RUNTIME / "advisory_kb_lessons.jsonl"
CANDIDATES_PATH = RUNTIME / "advisory_kb_lesson_candidates.jsonl"
APPLICATIONS_PATH = RUNTIME / "advisory_kb_lesson_applications.jsonl"
LESSONS_INDEX = RUNTIME / "advisory_kb_lessons_index.json"

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 64  # hash fallback dim
MAX_INJECT = 5
RETIRE_HIT_RATE = 0.40
RETIRE_MIN_APPS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for r in rows:
            f.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    tmp.replace(path)


# ── Embeddings ───────────────────────────────────────────────────────────────

def hash_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic bag-of-tokens embedding (no model required)."""
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9%$.]+", (text or "").lower())
    if not tokens:
        return vec
    for t in tokens:
        h = int(hashlib.sha256(t.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    # L2 normalize
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def ollama_embed(text: str, model: str = EMBED_MODEL) -> list[float] | None:
    try:
        from lib.ollama_embedding_policy import embed
        emb = embed((text or "")[:4000], model=model, timeout_s=30)
        if isinstance(emb, list) and emb:
            n = math.sqrt(sum(float(x) * float(x) for x in emb)) or 1.0
            return [float(x) / n for x in emb]
    except Exception:
        return None
    return None


def embed_text(text: str) -> tuple[list[float], str]:
    emb = ollama_embed(text)
    if emb:
        return emb, EMBED_MODEL
    return hash_embed(text), "hash_embed_v1"


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


# ── CRUD ─────────────────────────────────────────────────────────────────────

def list_lessons(*, status: str | None = "ratified") -> list[dict[str, Any]]:
    rows = _read_jsonl(LESSONS_PATH)
    # last write wins by id
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        lid = r.get("id")
        if lid:
            by_id[lid] = r
    out = list(by_id.values())
    if status:
        out = [r for r in out if r.get("status") == status]
    return out


def propose_lesson(
    *,
    title: str,
    body: str,
    symbols: list[str] | None = None,
    sectors: list[str] | None = None,
    verdict_types: list[str] | None = None,
    source: str = "nightly_reflection",
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    text = f"{title}\n{body}"
    emb, model = embed_text(text)
    lid = hashlib.sha256(text.encode()).hexdigest()[:12]
    entry = {
        "id": lid,
        "ts": _now_iso(),
        "status": "candidate",
        "title": (title or "")[:120],
        "body": (body or "")[:800],
        "symbols": [s.upper() for s in (symbols or []) if s],
        "sectors": sectors or [],
        "verdict_types": [v.upper() for v in (verdict_types or []) if v],
        "source": source,
        "evidence_refs": evidence_refs or [],
        "embedding": emb,
        "embedding_model": model,
        "applications": 0,
        "hits": 0,
        "hit_rate": None,
        "citations": 0,
        "ratified_at": None,
        "retired_at": None,
        "retire_reason": None,
    }
    _append_jsonl(CANDIDATES_PATH, entry)
    return entry


def ratify_lesson(lesson_id: str, *, by: str = "iris") -> dict[str, Any]:
    """Iris ratification: promote candidate → ratified lesson store."""
    cands = _read_jsonl(CANDIDATES_PATH)
    match = None
    for c in reversed(cands):
        if c.get("id") == lesson_id:
            match = c
            break
    # also allow re-ratify from lessons path
    if not match:
        for c in reversed(_read_jsonl(LESSONS_PATH)):
            if c.get("id") == lesson_id:
                match = c
                break
    if not match:
        raise ValueError(f"lesson not found: {lesson_id}")

    lesson = dict(match)
    lesson["status"] = "ratified"
    lesson["ratified_at"] = _now_iso()
    lesson["ratified_by"] = by
    lesson["ts"] = _now_iso()
    _append_jsonl(LESSONS_PATH, lesson)
    _rebuild_index()
    return lesson


def retire_lesson(lesson_id: str, *, reason: str = "manual") -> dict[str, Any]:
    lessons = list_lessons(status=None)
    match = next((l for l in lessons if l.get("id") == lesson_id), None)
    if not match:
        raise ValueError(f"lesson not found: {lesson_id}")
    retired = dict(match)
    retired["status"] = "retired"
    retired["retired_at"] = _now_iso()
    retired["retire_reason"] = reason
    retired["ts"] = _now_iso()
    _append_jsonl(LESSONS_PATH, retired)
    _rebuild_index()
    return retired


def record_application(
    lesson_id: str,
    *,
    symbol: str = "",
    hit: bool | None = None,
    cited_in_rationale: bool = False,
) -> None:
    apps = 0
    hits = 0
    citations = 0
    # update latest snapshot
    lessons = {l["id"]: l for l in list_lessons(status=None)}
    lesson = lessons.get(lesson_id)
    if not lesson:
        return
    apps = int(lesson.get("applications") or 0) + 1
    hits = int(lesson.get("hits") or 0) + (1 if hit else 0)
    citations = int(lesson.get("citations") or 0) + (1 if cited_in_rationale else 0)
    hit_rate = (hits / apps) if apps else None
    updated = dict(lesson)
    updated.update({
        "applications": apps,
        "hits": hits,
        "hit_rate": hit_rate,
        "citations": citations,
        "ts": _now_iso(),
        "status": lesson.get("status") or "ratified",
    })
    _append_jsonl(LESSONS_PATH, updated)
    _append_jsonl(APPLICATIONS_PATH, {
        "ts": _now_iso(),
        "lesson_id": lesson_id,
        "symbol": symbol,
        "hit": hit,
        "cited": cited_in_rationale,
    })
    # auto-retire
    if (
        updated.get("status") == "ratified"
        and apps >= RETIRE_MIN_APPS
        and hit_rate is not None
        and hit_rate < RETIRE_HIT_RATE
    ):
        retire_lesson(lesson_id, reason=f"auto_hit_rate_{hit_rate:.2f}_n{apps}")


def auto_retire_sweep() -> list[dict[str, Any]]:
    retired = []
    for l in list_lessons(status="ratified"):
        apps = int(l.get("applications") or 0)
        hr = l.get("hit_rate")
        if apps >= RETIRE_MIN_APPS and hr is not None and float(hr) < RETIRE_HIT_RATE:
            retired.append(retire_lesson(l["id"], reason=f"auto_hit_rate_{hr:.2f}_n{apps}"))
    return retired


def _rebuild_index() -> None:
    ratified = list_lessons(status="ratified")
    idx = {
        "rebuilt_at": _now_iso(),
        "n": len(ratified),
        "ids": [l["id"] for l in ratified],
    }
    try:
        LESSONS_INDEX.write_text(json.dumps(idx, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Retrieval & injection ────────────────────────────────────────────────────

def retrieve_lessons_for_row(
    *,
    symbol: str = "",
    sector: str = "",
    verdict: str = "",
    query_text: str = "",
    limit: int = MAX_INJECT,
) -> list[dict[str, Any]]:
    """Rank ratified lessons by symbol/sector/verdict + embedding similarity."""
    lessons = list_lessons(status="ratified")
    if not lessons:
        return []
    q = query_text or f"{symbol} {sector} {verdict}"
    q_emb, _ = embed_text(q)
    scored: list[tuple[float, dict[str, Any]]] = []
    sym_u = (symbol or "").upper()
    ver_u = (verdict or "").upper()
    sec_l = (sector or "").lower()
    for l in lessons:
        score = cosine(q_emb, l.get("embedding") or [])
        if sym_u and sym_u in [s.upper() for s in (l.get("symbols") or [])]:
            score += 0.35
        if ver_u and ver_u in [v.upper() for v in (l.get("verdict_types") or [])]:
            score += 0.20
        if sec_l and sec_l in [s.lower() for s in (l.get("sectors") or [])]:
            score += 0.15
        # Prefer lessons with positive track record
        hr = l.get("hit_rate")
        if hr is not None:
            score += 0.1 * float(hr)
        scored.append((score, l))
    scored.sort(key=lambda x: -x[0])
    return [l for _, l in scored[:limit]]


def format_lessons_for_prompt(lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for l in lessons[:MAX_INJECT]:
        hr = l.get("hit_rate")
        out.append({
            "id": l.get("id"),
            "title": l.get("title"),
            "hit_rate": hr if hr is not None else "n/a",
            "applications": l.get("applications") or 0,
        })
    return out


# ── Nightly reflection (deterministic candidates) ────────────────────────────

def nightly_reflection(*, max_candidates: int = 15) -> dict[str, Any]:
    """Propose lesson candidates from history thrash, feedback, outcomes, specialists."""
    from lib.advisory.advisory_memory import (
        ROWS_PATH,
        FEEDBACK_PATH,
        OUTCOMES_PATH,
        count_verdict_changes,
        row_key,
        _read_jsonl as _rj,
    )

    proposed: list[dict[str, Any]] = []
    existing_titles = {l.get("title") for l in list_lessons(status=None)}
    existing_titles |= {c.get("title") for c in _read_jsonl(CANDIDATES_PATH)}

    # 1) Thrash patterns by symbol
    by_key: dict[str, list[dict]] = {}
    for e in _rj(ROWS_PATH):
        rk = e.get("row_key") or row_key(e.get("symbol", ""), e.get("account", ""))
        by_key.setdefault(rk, []).append(e)
    for rk, hist in by_key.items():
        hist = sorted(hist, key=lambda x: x.get("ts") or "")
        flips = count_verdict_changes(hist)
        if flips >= 3:
            sym = rk.split(":")[0]
            title = f"Thrash on {sym}: avoid flip-flop conviction"
            if title not in existing_titles:
                body = (
                    f"{sym} flipped verdict {flips} times recently. "
                    f"Lower conviction when thrash is high; require new evidence before TRIM↔HOLD flips."
                )
                proposed.append(propose_lesson(
                    title=title, body=body, symbols=[sym],
                    verdict_types=["TRIM", "HOLD"],
                    source="reflection_thrash",
                    evidence_refs=[rk],
                ))
                existing_titles.add(title)

    # 2) DISAGREE_THESIS feedback
    for e in _rj(FEEDBACK_PATH):
        if e.get("reason_code") != "DISAGREE_THESIS":
            continue
        sym = (e.get("symbol") or "").upper()
        if not sym:
            continue
        title = f"Operator held through call on {sym}"
        if title in existing_titles:
            continue
        body = (
            f"Operator rated DISAGREE_THESIS on {sym}. "
            f"Surface prior disagreement; do not re-litigate without new facts. Note: {e.get('note') or ''}"
        )
        proposed.append(propose_lesson(
            title=title, body=body, symbols=[sym],
            source="reflection_feedback",
            evidence_refs=[e.get("row_id") or sym],
        ))
        existing_titles.add(title)

    # 3) Outcome failures for TRIM that rallied
    fail_syms: Counter[str] = Counter()
    for e in _rj(OUTCOMES_PATH):
        if e.get("verdict") in ("TRIM", "EXIT") and e.get("correct") is False:
            fail_syms[str(e.get("symbol") or "")] += 1
    for sym, n in fail_syms.most_common(5):
        if not sym or n < 2:
            continue
        title = f"TRIM/EXIT false positive pattern: {sym}"
        if title in existing_titles:
            continue
        body = (
            f"{sym} TRIM/EXIT scored wrong {n} times (price rallied). "
            f"Require momentum counter-argument before high-conviction EXIT."
        )
        proposed.append(propose_lesson(
            title=title, body=body, symbols=[sym],
            verdict_types=["TRIM", "EXIT"],
            source="reflection_outcomes",
        ))
        existing_titles.add(title)

    # 4) Cash concentration (standing IPS lesson)
    title = "Idle cash vs IPS target is structural, not a ticker trade"
    if title not in existing_titles:
        proposed.append(propose_lesson(
            title=title,
            body=(
                "Large cash overweight should lead synthesis by dollars. "
                "Deployment is Steph/operator decision; do not force equity EXIT solely to fund cash."
            ),
            verdict_types=["ADD", "TRIM"],
            sectors=["cash", "allocation"],
            source="reflection_ips",
        ))

    return {
        "ok": True,
        "proposed": len(proposed[:max_candidates]),
        "candidates": proposed[:max_candidates],
        "ratified_n": len(list_lessons(status="ratified")),
        "auto_retired": [r.get("id") for r in auto_retire_sweep()],
    }


def iris_auto_ratify_safe(*, limit: int = 10) -> list[dict[str, Any]]:
    """Conservative auto-ratify for reflection sources that are non-speculative.

    True Iris curation can override; this bootstraps the KB for shadow.
    """
    safe_sources = {"reflection_ips", "reflection_thrash", "reflection_feedback"}
    ratified = []
    seen = set()
    for c in reversed(_read_jsonl(CANDIDATES_PATH)):
        if c.get("id") in seen:
            continue
        seen.add(c.get("id"))
        if c.get("source") not in safe_sources:
            continue
        # skip if already ratified
        if any(l.get("id") == c.get("id") and l.get("status") == "ratified"
               for l in list_lessons(status="ratified")):
            continue
        try:
            ratified.append(ratify_lesson(c["id"], by="iris_auto_safe"))
        except Exception:
            continue
        if len(ratified) >= limit:
            break
    return ratified


def stats() -> dict[str, Any]:
    all_l = list_lessons(status=None)
    by_status: Counter[str] = Counter(l.get("status") or "?" for l in all_l)
    ratified = [l for l in all_l if l.get("status") == "ratified"]
    cited = sum(1 for l in ratified if int(l.get("citations") or 0) >= 1)
    return {
        "by_status": dict(by_status),
        "ratified_n": len(ratified),
        "candidates_n": len(_read_jsonl(CANDIDATES_PATH)),
        "lessons_with_citations": cited,
        "total_citations": sum(int(l.get("citations") or 0) for l in ratified),
        "auto_retire_threshold": {"hit_rate": RETIRE_HIT_RATE, "min_apps": RETIRE_MIN_APPS},
    }
