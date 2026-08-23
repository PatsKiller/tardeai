"""Operator ticker feedback journal for Investment Intelligence Cards (Phase B).

Append-only JSONL store shared by Telegram buttons and CC. Continuity on the
next alert is loaded via ``latest_feedback(symbol)``.

Authority: READ_ONLY_ADVISORY — never broker/order/stop authority.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "OperatorTickerFeedback@v1"

VALID_INTENTS = frozenset({
    "AGREE",
    "DISAGREE",
    "INTERESTED",
    "DEFER",
    "NEED_DATA",
    "DISMISS",
    "ACK",
    "NO_LONGER_RELEVANT",
})

VALID_STATUSES = frozenset({"ACTIVE", "RETRO_LABELED"})

# Intent → coarse operator stance for continuity summaries.
_STANCE_BY_INTENT: dict[str, str] = {
    "AGREE": "bullish",
    "INTERESTED": "bullish",
    "DISAGREE": "bearish",
    "DISMISS": "bearish",
    "DEFER": "monitoring",
    "ACK": "monitoring",
    "NEED_DATA": "cautious",
    "NO_LONGER_RELEVANT": "monitoring",
}

VALID_STANCES = frozenset({"bullish", "cautious", "bearish", "monitoring"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def feedback_path(*, root: Path | str | None = None) -> Path:
    root_p = Path(root) if root else _project_root()
    return root_p / "data" / "cio" / "operator_ticker_feedback.jsonl"


def normalize_intent(intent: Any) -> str:
    s = str(intent or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "NEEDDATA": "NEED_DATA",
        "NEED_MORE_DATA": "NEED_DATA",
        "MORE_DATA": "NEED_DATA",
        "ACKNOWLEDGE": "ACK",
        "ACKNOWLEDGED": "ACK",
    }
    return aliases.get(s, s)


def stance_from_intent(intent: Any) -> str:
    """Map feedback intent → bullish|cautious|bearish|monitoring."""
    key = normalize_intent(intent)
    return _STANCE_BY_INTENT.get(key, "monitoring")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Validate + enrich an OperatorTickerFeedback@v1 row (fail-closed on intent)."""
    if not isinstance(row, dict):
        raise ValueError("row_must_be_dict")
    sym = str(row.get("symbol") or "").strip().upper()
    if not sym:
        raise ValueError("symbol_required")
    intent = normalize_intent(row.get("intent"))
    if intent not in VALID_INTENTS:
        raise ValueError(f"invalid_intent:{intent or ''}")
    stance = str(row.get("stance") or "").strip().lower() or stance_from_intent(intent)
    if stance not in VALID_STANCES:
        stance = stance_from_intent(intent)
    free_text = row.get("free_text")
    if free_text is None:
        free_text = row.get("note") or row.get("concerns")
    free_text_s = str(free_text).strip()[:500] if free_text is not None else ""
    status = str(row.get("status") or "ACTIVE").strip().upper()
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid_status:{status or ''}")
    decision_id = str(row.get("decision_id") or "").strip()[:128] or None
    thesis_id = str(row.get("thesis_id") or row.get("symbol_thesis_id") or "").strip()[:128] or None
    thesis_version = str(
        row.get("thesis_version") or row.get("symbol_thesis_version") or ""
    ).strip()[:128] or None
    operator_identity_class = str(
        row.get("operator_identity_class") or "UNKNOWN_OPERATOR"
    ).strip().upper()[:64] or "UNKNOWN_OPERATOR"
    source_surface = str(
        row.get("source_surface") or row.get("channel") or "api"
    ).strip().lower()[:64] or "api"
    trust = "LOW" if status == "RETRO_LABELED" else "NORMAL"
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "feedback_id": str(row.get("feedback_id") or f"otf_{uuid.uuid4().hex[:16]}"),
        "ts": str(row.get("ts") or _now()),
        "symbol": sym,
        "intent": intent,
        "stance": stance,
        "free_text": free_text_s or None,
        "reason": free_text_s or None,
        "object_id": (str(row.get("object_id")).strip()[:96] if row.get("object_id") else None),
        "channel": source_surface[:32],
        "source_surface": source_surface,
        "decision_id": decision_id,
        "thesis_id": thesis_id,
        "thesis_version": thesis_version,
        "operator_identity_class": operator_identity_class,
        "timestamp": str(row.get("timestamp") or row.get("ts") or _now()),
        "status": status,
        "trust": trust,
        "linkage_complete": bool(decision_id and thesis_id and thesis_version),
        "eligible_for_operator_rejection_recall": bool(
            status == "ACTIVE" and intent == "DISAGREE"
        ),
        "behavior_authority": False,
        "authority": AUTHORITY,
    }
    out["ts"] = out["timestamp"]
    # Preserve optional extras without inventing financial fields.
    for k in ("operator_actor_id", "source", "card_schema"):
        if row.get(k) is not None and k not in out:
            out[k] = row[k]
    return out


def append_feedback(
    row: dict[str, Any],
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Append one OperatorTickerFeedback@v1 row to the journal. Returns the stored row."""
    stored = _normalize_row(row)
    path = feedback_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stored, sort_keys=True, default=str) + "\n")
    return stored


def latest_feedback(
    symbol: str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Most recent feedback row for ``symbol``, or None."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    latest: dict[str, Any] | None = None
    for row in _read_jsonl(feedback_path(root=root)):
        if str(row.get("symbol") or "").upper() != sym:
            continue
        schema = row.get("schema")
        # Accept matching or missing schema (forward/backward compat).
        if schema not in (None, "", SCHEMA):
            continue
        if not row.get("intent"):
            continue
        latest = row
    return latest


def journal_for_symbol(
    symbol: str,
    *,
    limit: int = 20,
    root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Timeline of feedback for ``symbol`` (newest first, capped)."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return []
    lim = max(0, int(limit))
    matched: list[dict[str, Any]] = []
    for row in _read_jsonl(feedback_path(root=root)):
        if str(row.get("symbol") or "").upper() != sym:
            continue
        if not row.get("intent"):
            continue
        matched.append(row)
    matched.reverse()  # newest first
    return matched[:lim]


def maybe_enqueue_need_data(
    symbol: str,
    *,
    feedback: dict[str, Any] | None = None,
    root: Path | str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Best-effort NEED_DATA follow-up: held-coverage dry acquire and/or Hermes enqueue.

    Fail-soft — never raises into the feedback write path.
    """
    sym = str(symbol or "").strip().upper()
    out: dict[str, Any] = {
        "ok": True,
        "symbol": sym,
        "authority": AUTHORITY,
        "held_coverage": None,
        "hermes": None,
    }
    if not sym:
        out["ok"] = False
        out["error"] = "symbol_required"
        return out

    root_p = Path(root) if root else _project_root()
    feedback = feedback if isinstance(feedback, dict) else {}

    try:
        from scripts.lib.cio_held_thesis_coverage import run_held_coverage_acquire

        out["held_coverage"] = run_held_coverage_acquire(
            root=root_p,
            limit=1,
            max_llm=0,
            apply=bool(apply),
            symbols=[sym],
        )
    except Exception as exc:
        out["held_coverage"] = {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}"[:200],
        }

    try:
        from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue

        store = root_p / "data" / "cio" / "hermes_challenge_queue.jsonl"
        q = HermesChallengeQueue(event_store_path=store)
        evt = q.enqueue(
            challenge_type="research_gap",
            description=(
                f"Operator NEED_DATA on {sym}: "
                f"{str(feedback.get('reason') or 'additional evidence requested')[:240]}"
            ),
            source="operator_ticker_feedback",
            priority="normal",
            metadata={
                "symbol": sym,
                "intent": "NEED_DATA",
                "schema": SCHEMA,
                "feedback_id": feedback.get("feedback_id"),
                "decision_id": feedback.get("decision_id"),
                "thesis_id": feedback.get("thesis_id"),
                "thesis_version": feedback.get("thesis_version"),
                "source_surface": feedback.get("source_surface"),
                "authority": AUTHORITY,
            },
            actor_id="operator",
        )
        out["hermes"] = {
            "ok": True,
            "challenge_id": evt.get("stream_id") or (evt.get("payload") or {}).get("challenge_id"),
            "event_type": evt.get("event_type"),
        }
    except Exception as exc:
        out["hermes"] = {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}"[:200],
        }

    # Overall ok if at least one path succeeded (or both soft-failed — still advisory).
    hc_ok = isinstance(out.get("held_coverage"), dict) and out["held_coverage"].get("ok") is not False
    hm_ok = isinstance(out.get("hermes"), dict) and out["hermes"].get("ok") is True
    out["ok"] = bool(hc_ok or hm_ok)
    return out
