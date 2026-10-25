"""Priority requests for symbol-thesis acquisition (operator 2026-09-27).

Why: the options lifecycle's CIO said MORE_RESEARCH on DELL three times because DELL
had no house symbol thesis, but nothing asked the acquisition worker for one; it only
ran its own daily, debt-ordered list of 10. A MORE_RESEARCH decision on a symbol with
no thesis now files a request here. The acquisition runner and the curation monitor
serve open requests first. A request closes when acquisition publishes (or finds no
material change) after it, or when it ages out. Append-only; nothing is deleted.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

RELPATH = ("data", "cio", "symbol_thesis_priority_queue.jsonl")
LEDGER_RELPATH = ("data", "cio", "symbol_thesis_acquisition_ledger.jsonl")
DONE = {"PUBLISHED", "SYNTHESIZED_NO_MATERIAL_CHANGE"}
TTL_DAYS = 7


def _root(root: Any) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        pass
    return out


def request(symbol: str, *, reason: str, source: str, root: Any = None,
            now: Optional[datetime] = None, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Append one request. ``extra`` carries optional lineage (request_id, security_guid, identity_status,
    conflict_key); it never overrides the core fields."""
    now = now or datetime.now(timezone.utc)
    row = {"schema": "SymbolThesisPriorityRequest@v1", "symbol": str(symbol).upper(), "reason": reason[:300],
           "source": source, "requested_at": now.isoformat(), "authority": "READ_ONLY_ADVISORY"}
    row = {**{k: v for k, v in (extra or {}).items() if v is not None}, **row}
    path = _root(root).joinpath(*RELPATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def open_requests(root: Any = None, *, now: Optional[datetime] = None, ttl_days: float = TTL_DAYS) -> list[str]:
    """Symbols with an open request, oldest request first."""
    now = now or datetime.now(timezone.utc)
    base = _root(root)
    first: dict[str, str] = {}
    for r in _rows(base.joinpath(*RELPATH)):
        sym, at = str(r.get("symbol") or "").upper(), str(r.get("requested_at") or "")
        if not sym or not at:
            continue
        try:
            if datetime.fromisoformat(at) < now - timedelta(days=ttl_days):
                continue
        except ValueError:
            continue
        first.setdefault(sym, at)
        first[sym] = min(first[sym], at)
    if not first:
        return []
    done_at: dict[str, str] = {}
    for r in _rows(base.joinpath(*LEDGER_RELPATH)):
        sym = str(r.get("symbol") or "").upper()
        if sym in first and r.get("status") in DONE:
            done_at[sym] = max(done_at.get(sym, ""), str(r.get("as_of") or ""))
    return [s for s, at in sorted(first.items(), key=lambda kv: kv[1]) if done_at.get(s, "") < at]


# Who asked, in serving order (operator 2026-10-09): a name the operator flags from the opportunity view first, then
# the CIO's top-ranked opportunities with no thesis (cio_opportunity_curator), then every other source. Oldest first
# within a source. Without this a new flag waited behind ~27 open requests at ~3 LLM syntheses per run.
SOURCE_ORDER = ("operator_opportunity_view", "cio_opportunity_curator")


def open_requests_ranked(root: Any = None, *, now: Optional[datetime] = None, ttl_days: float = TTL_DAYS) -> list[str]:
    """open_requests(), reordered by SOURCE_ORDER (best source any open request for the symbol came from)."""
    syms = open_requests(root, now=now, ttl_days=ttl_days)
    if not syms:
        return []
    best: dict[str, int] = {}
    for r in _rows(_root(root).joinpath(*RELPATH)):
        sym = str(r.get("symbol") or "").upper()
        if sym in syms:
            src = str(r.get("source") or "")
            rank = SOURCE_ORDER.index(src) if src in SOURCE_ORDER else len(SOURCE_ORDER)
            best[sym] = min(best.get(sym, rank), rank)
    pos = {s: i for i, s in enumerate(syms)}
    return sorted(syms, key=lambda s: (best.get(s, len(SOURCE_ORDER)), pos[s]))



# ── Request state for a surface (Watch rows, review-request response) ───────────────────────────────────────────
# Plain words for the acquisition run's recorded outcome (scripts/run_symbol_thesis_acquisition.py ledger rows).
GAP_WORDS = {
    "insufficient_contradictory_rag": "no contradicting evidence on file yet",
    "insufficient_supporting_rag": "not enough supporting evidence on file yet",
    "no_approved_primary_or_news": "no approved primary source or news yet",
}
STATUS_WORDS = {
    "BLOCKED": "Blocked",
    "SYNTHESIS_FAILED": "Write-up failed",
    "LLM_BUDGET_EXHAUSTED": "Waiting for model budget",
    "PUBLISHED": "CIO view published",
    "SYNTHESIZED_NO_MATERIAL_CHANGE": "Reviewed — no material change",
}
_STATE_CACHE: dict[str, Any] = {}


def _signature(path: Path):
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size, st.st_ino
    except OSError:
        return None


def _attempts(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Acquisition outcomes per symbol (slim rows), re-read only when the ledger file changes."""
    sig = (str(path), _signature(path))
    cached = _STATE_CACHE.get("attempts")
    if cached and cached[0] == sig:
        return cached[1]
    out: dict[str, list[dict[str, Any]]] = {}
    for r in _rows(path):
        sym = str(r.get("symbol") or "").upper()
        if not sym or not r.get("status"):
            continue
        out.setdefault(sym, []).append({
            "status": str(r.get("status")), "at": str(r.get("as_of") or ""),
            "block_reason": r.get("block_reason") or (r.get("gate") if r.get("status") == "BLOCKED" else None),
            "remaining_gaps": [str(g) for g in r.get("remaining_gaps") or []],
            "pending_curation_n": r.get("pending_curation_n"), "error": r.get("error")})
    _STATE_CACHE["attempts"] = (sig, out)
    return out


def attempt_reason(attempt: dict[str, Any]) -> str:
    """One plain sentence for an acquisition outcome; the raw code stays alongside it."""
    status = attempt.get("status")
    if status == "BLOCKED":
        gaps = [GAP_WORDS.get(g, g.replace("_", " ")) for g in attempt.get("remaining_gaps") or []]
        text = "waiting for evidence" + (f" — {'; '.join(gaps)}" if gaps else "")
        pending = attempt.get("pending_curation_n")
        if isinstance(pending, int) and pending > 0:
            text += f" ({pending} new item{'s' if pending != 1 else ''} awaiting curation)"
        return text
    if status == "SYNTHESIS_FAILED":
        return "the CIO write-up could not be produced; the next run retries"
    if status == "LLM_BUDGET_EXHAUSTED":
        return "the model budget for this run was used up; the next run retries"
    if status in DONE:
        return "the CIO recorded a view"
    return str(status or "unknown").replace("_", " ").lower()


def review_states(symbols, root: Any = None, *, now: Optional[datetime] = None,
                  ttl_days: float = TTL_DAYS, run_label: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """ReviewRequestState@v1 per symbol from the priority queue and the acquisition ledger (read-only).

    status: none | queued | blocked | failed | waiting_budget | answered | expired. ``label`` is display-ready.
    A request is open from its first unanswered requested_at until TTL after its latest request.
    """
    now = now or datetime.now(timezone.utc)
    base = _root(root)
    wanted = {str(s).upper() for s in symbols if s}
    requests: dict[str, list[dict[str, Any]]] = {}
    for r in _rows(base.joinpath(*RELPATH)):
        sym = str(r.get("symbol") or "").upper()
        if sym in wanted and r.get("requested_at"):
            requests.setdefault(sym, []).append(r)
    attempts = _attempts(base.joinpath(*LEDGER_RELPATH))
    ranked = open_requests_ranked(root, now=now, ttl_days=ttl_days) if requests else []
    out: dict[str, dict[str, Any]] = {}
    for sym in wanted:
        reqs = sorted(requests.get(sym) or [], key=lambda r: str(r.get("requested_at")))
        tries = sorted(attempts.get(sym) or [], key=lambda a: a["at"])
        state: dict[str, Any] = {"schema": "ReviewRequestState@v1", "symbol": sym, "status": "none",
                                 "label": "Not requested", "open": False, "queued_at": None, "requested_by": None,
                                 "expires_at": None, "queue_position": None, "queue_length": len(ranked),
                                 "last_attempt": None, "attempts_since_request": 0, "conflict_key": None,
                                 "request_id": None, "next_run": run_label}
        if not reqs:
            out[sym] = state
            continue
        done_at = max((a["at"] for a in tries if a["status"] in DONE), default="")
        latest = reqs[-1]
        unanswered = [r for r in reqs if str(r["requested_at"]) > done_at]
        first_open = unanswered[0] if unanswered else None
        try:
            expires = datetime.fromisoformat(str(latest["requested_at"])) + timedelta(days=ttl_days)
        except ValueError:
            expires = None
        since = str((first_open or latest)["requested_at"])
        later = [a for a in tries if a["at"] >= since]
        last = (later or tries or [None])[-1]
        state.update(queued_at=since, requested_by=(first_open or latest).get("source"),
                     expires_at=expires.isoformat() if expires else None,
                     attempts_since_request=len(later), conflict_key=latest.get("conflict_key"),
                     request_id=latest.get("request_id"))
        if last:
            state["last_attempt"] = {**last, "reason": attempt_reason(last)}
        if sym in ranked:
            state.update(open=True, queue_position=ranked.index(sym) + 1)
            if not later:
                state.update(status="queued", label="Queued for the CIO")
            elif later[-1]["status"] == "BLOCKED":
                state.update(status="blocked", label=f"Blocked: {attempt_reason(later[-1])}")
            elif later[-1]["status"] == "LLM_BUDGET_EXHAUSTED":
                state.update(status="waiting_budget", label=f"Queued: {attempt_reason(later[-1])}")
            else:
                state.update(status="failed", label=f"Retrying: {attempt_reason(later[-1])}")
        elif first_open is None and done_at:
            state.update(status="answered", label=f"Answered {done_at[:10]}: {STATUS_WORDS.get(last['status'], last['status']) if last else ''}".rstrip(": "))
        else:
            state.update(status="expired", label="Request expired without a CIO view — ask again")
        out[sym] = state
    return out
