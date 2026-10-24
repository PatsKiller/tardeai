"""Force a CIO review when a bullish send is held for a missing CIO stance.

OPERATOR DECISION 2026-09-23: "GO/BUY message with no CIO stance on file should
be held yes force cio review". The stance gate already holds the send
(``cio_decision_missing``). Before this module the hold was the end of it: the
same ~15-20 names were re-held every two minutes (757 / 635 / 776 holds on
09-21 / 09-22 / 09-23) and nothing ever asked the CIO about them.

What "review" means here, measured 2026-09-23 -- no invented mechanism:

* ``cio_decisions`` (the table ``load_cio_view`` reads) has two live writers.
  ``cio_decision_engine`` covers only symbols with an active
  ``ticker_strategy_classifications`` row plus ``strategy_rule_evaluations``;
  26 of the 30 names held for a missing stance in the last three days have
  neither. ``cio_entry_state_runner`` writes only BUY_READY / ENTRY_NEAR for
  names already in an actionable entry state. Neither takes a per-symbol
  request.
* CIO wakes (``cio_wake_dispatcher.enqueue_instrument_record_wakes``) run only on
  the 53 existing InstrumentRecords and never invent a subject.
* The desk's own research pull -- a ``CIOPlanStore`` plan plus
  ``hermes_research_loop.emit_research_for_plan`` -- takes any named symbol, is
  drained by ``tradeai-hermes-cio-worker`` (``LLM_DEFER_OFFPEAK=1``) and lands
  in the ``res_`` projection that the desk, the Hermes subject join and the CIO
  read. That is the path used here.

So this module queues the CIO research pull that a stance needs. It does NOT by
itself write a ``cio_decisions`` row; the name stays held until a stance exists.
Every request is recorded in ``cio_stance_review_requests.jsonl``.

Classification follow-up (OPERATOR 2026-09-23 "add the classification queue
follow-up"): the same ledger row carries ``classification_requested``. The
engine only covers symbols with an ACTIVE ``ticker_strategy_classifications``
row plus a ``strategy_rule_evaluations`` row, and the rule-evaluation producer
has been unscheduled since 2026-09-06. ``scripts/drain_cio_stance_classification.py``
reads these ledger rows, classifies the symbol deterministically (no LLM) and
writes its rule evaluation, so the next ``cio_decision_engine`` run writes a
real stance. Disable with ``CIO_STANCE_CLASSIFY_DISABLE=1``.

Never raises into the send path. Deduped per symbol per
``CIO_STANCE_REVIEW_DEDUPE_SECONDS``. Pytest writes nothing unless
``CIO_STANCE_REVIEW_REQUESTS`` points at a test path.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "CIOStanceReviewRequest@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: One review request per symbol per window (a stance takes the research queue
#: longer than the 2-minute publisher cadence). ``0`` disables dedupe.
DEFAULT_DEDUPE_SECONDS = 86400
#: A failed enqueue retries after this long instead of on every 2-minute run.
DEFAULT_RETRY_SECONDS = 3600
#: The operator asked to FORCE the review, so it outranks routine plan research.
DEFAULT_PRIORITY = "high"

#: Hold sources that are real sends. Canary / probe / test sources never queue
#: paid research.
REVIEW_SOURCES = frozenset(
    {
        "check_investment_send",
        "screener_go_alerts",
        "send_telegram_proposal_alert",
        "social_scalp_scanner",
        "maria_outbound_gate",
    }
)

_OFF = {"0", "off", "false", "no", "disable"}


def requests_path() -> Optional[Path]:
    raw = str(os.environ.get("CIO_STANCE_REVIEW_REQUESTS") or "").strip()
    if raw.lower() in _OFF:
        return None
    if raw:
        return Path(raw)
    return Path.home() / ".local/state/tradeai/cio_stance_review_requests.jsonl"


def dedupe_seconds() -> int:
    raw = str(os.environ.get("CIO_STANCE_REVIEW_DEDUPE_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_DEDUPE_SECONDS
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_DEDUPE_SECONDS


def retry_seconds() -> int:
    raw = str(os.environ.get("CIO_STANCE_REVIEW_RETRY_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_RETRY_SECONDS
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_RETRY_SECONDS


def review_priority() -> str:
    raw = str(os.environ.get("CIO_STANCE_REVIEW_PRIORITY") or "").strip().lower()
    return raw if raw in {"critical", "high", "normal", "low"} else DEFAULT_PRIORITY


def _enabled() -> bool:
    if str(os.environ.get("CIO_STANCE_REVIEW_DISABLE") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and not str(os.environ.get("CIO_STANCE_REVIEW_REQUESTS") or "").strip():
        return False
    return requests_path() is not None


def classification_enabled() -> bool:
    return str(os.environ.get("CIO_STANCE_CLASSIFY_DISABLE") or "").strip().lower() not in {"1", "true", "yes", "on"}


def review_questions(symbol: str) -> list[dict[str, str]]:
    return [
        {
            "intent": "cio_stance",
            "text": (
                f"{symbol} reached a GO/BUY publisher with no CIO stance on file. "
                "What should the CIO's stance be (BUY / WATCH / AVOID), and why?"
            ),
        },
        {"intent": "thesis_check", "text": f"What is the investment thesis for {symbol}, and what would break it?"},
        {"intent": "risk", "text": f"What are the main risks for {symbol} now (valuation, balance sheet, catalysts)?"},
    ]


def _emit_via_desk_research(symbol: str, source: str) -> dict[str, Any]:
    """Queue the CIO research pull the desk uses for a named symbol."""
    from datetime import timedelta

    try:
        from scripts.lib.cio_plans import CIOPlanStore
        from scripts.lib.hermes_research_loop import emit_research_for_plan
    except ImportError:  # publishers run with only scripts/ on sys.path
        from lib.cio_plans import CIOPlanStore  # type: ignore
        from lib.hermes_research_loop import emit_research_for_plan  # type: ignore

    revisit = (datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat()
    plan = CIOPlanStore().create_plan(
        situation_type="S7_WATCH_PROMOTION",
        symbols=[symbol],
        title=f"CIO stance review: {symbol}",
        summary=f"Bullish send held for a missing CIO stance ({source}). Operator rule 2026-09-23: force CIO review.",
        options=[
            {"id": "stance", "label": "Form a CIO stance", "pros": "Unblocks the send", "cons": "Research spend"},
            {"id": "hold", "label": "Keep holding", "pros": "No spend", "cons": "Name stays unreviewed"},
        ],
        recommendation="Research the name and record a CIO stance. READ_ONLY.",
        risks=["Send stays held until a CIO stance exists"],
        revisit_at=revisit,
        owner_agent="alex",
        actor_id="cio_stance_review_request",
    )
    if not isinstance(plan, dict) or not plan.get("plan_id"):
        return {"ok": False, "error": "no_plan_id"}
    plan = {**plan, "hermes_requested": True}
    emit = emit_research_for_plan(
        plan,
        reason="cio_stance_missing_review",
        priority=review_priority(),
        questions=review_questions(symbol),
        actor_id="cio_stance_review_request",
    )
    out = dict(emit) if isinstance(emit, dict) else {"ok": True, "raw": str(emit)[:200]}
    out["plan_id"] = plan["plan_id"]
    return out


def _state_path(ledger: Path) -> Path:
    return ledger.with_name(ledger.stem + ".dedupe.json")


def _load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _identity(symbol: str) -> dict[str, Any]:
    try:
        try:
            from scripts.lib.cio_hermes_research import _subject_identity
        except ImportError:
            from lib.cio_hermes_research import _subject_identity  # type: ignore

        ident = _subject_identity(symbol)
        return ident if isinstance(ident, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def request_cio_review(
    symbol: str,
    *,
    source: str,
    caller: Optional[str] = None,
    now: Optional[datetime] = None,
    emitter: Optional[Callable[[str, str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Queue a CIO stance review for ``symbol``. Returns fields for the hold row.

    ``{"review_requested": bool, "review_status": str, ...}``. Never raises.
    """
    sym = str(symbol or "").upper().strip()
    src = caller or source
    try:
        if not sym:
            return {"review_requested": False, "review_status": "no_symbol"}
        if src not in REVIEW_SOURCES:
            return {"review_requested": False, "review_status": "source_not_eligible"}
        if not _enabled():
            return {"review_requested": False, "review_status": "disabled"}
        ledger = requests_path()
        if ledger is None:
            return {"review_requested": False, "review_status": "disabled"}
        when = now or datetime.now(timezone.utc)
        state_path = _state_path(ledger)
        state = _load_state(state_path)
        window = dedupe_seconds()
        prior = state.get(sym) if isinstance(state.get(sym), dict) else None
        age = when.timestamp() - float((prior or {}).get("ts") or 0)
        if prior and prior.get("failed") and age < retry_seconds():
            return {"review_requested": False, "review_status": "retry_backoff"}
        if prior and not prior.get("failed") and window and age < window:
            return {
                "review_requested": True,
                "review_status": "deduped",
                "review_request_id": prior.get("research_id"),
                "review_requested_at": prior.get("as_of"),
                "classification_requested": bool(prior.get("classification_requested")),
            }
        emit = (emitter or _emit_via_desk_research)(sym, src)
        ok = bool(emit.get("ok", False))
        research_id = emit.get("research_id")
        status = str(emit.get("reason") or emit.get("status") or ("created" if ok else emit.get("error") or "failed"))
        as_of = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        row = {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "as_of": as_of,
            "symbol": sym,
            "source": src,
            "ok": ok,
            "status": status[:80],
            "research_id": research_id,
            "plan_id": emit.get("plan_id"),
            "priority": review_priority(),
            "mbi_behavior": 0,
            # Deterministic, no spend: requested even when the research emit failed.
            "classification_requested": classification_enabled(),
            **_identity(sym),
        }
        try:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        except OSError:
            pass
        entry: dict[str, Any] = {
            "ts": when.timestamp(),
            "as_of": as_of,
            "research_id": research_id,
            "classification_requested": row["classification_requested"],
        }
        if not ok:
            entry["failed"] = True
        state[sym] = entry
        keep = max(window, retry_seconds())
        if keep:
            state = {
                k: v
                for k, v in state.items()
                if isinstance(v, dict) and when.timestamp() - float(v.get("ts") or 0) < keep
            }
        _save_state(state_path, state)
        return {
            "review_requested": ok,
            "review_status": status[:80],
            "review_request_id": research_id,
            "review_requested_at": as_of,
            "classification_requested": row["classification_requested"],
        }
    except Exception as exc:  # noqa: BLE001 -- the send path must never see this
        return {"review_requested": False, "review_status": f"error:{type(exc).__name__}"}


__all__ = [
    "DEFAULT_DEDUPE_SECONDS",
    "DEFAULT_PRIORITY",
    "DEFAULT_RETRY_SECONDS",
    "REVIEW_SOURCES",
    "SCHEMA",
    "classification_enabled",
    "dedupe_seconds",
    "request_cio_review",
    "requests_path",
    "review_priority",
    "retry_seconds",
    "review_questions",
]
