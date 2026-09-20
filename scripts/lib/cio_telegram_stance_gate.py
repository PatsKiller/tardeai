"""CIO stance hard gate for investment-shaped Telegram sends.

Audit 2026-09-18: Comms Editor could annotate Buy-vs-AVOID and still send;
proposal / screener GO / social GO never joined ``cio_decisions``. INTERDICT is
a kill switch, not stance approval.

This module is the minimum hard gate:

* Investment-shaped message stance (Buy / Accumulate / GO / …) for a symbol
  must align with the latest CIO action for that symbol.
* Missing CIO row, unreadable store, or non-aligned action → hold
  (``allow=False`` + ``held_reason``). Never annotate-and-send from here.
* Every hold appends one durable receipt line
  (``cio_telegram_stance_holds.jsonl``) so PARTIAL-telegram-CIO-stance can be
  observed from the served release — not only as a log line.

AUTHORITY: READ_ONLY_ADVISORY. Reads ``cio_decisions`` only. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA = "CioTelegramStanceGate@v1"
HOLD_RECEIPT_SCHEMA = "CioTelegramStanceHold@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# Mirror comms_editor vocabulary so publisher + transport agree.
_CIO_BULL = {
    "BUY", "ADD", "ADD_ON_PULLBACK", "ACCUMULATE", "INITIATE", "REENTER", "RE_ENTER",
    "BUY_READY", "ENTRY_NEAR",
}
_CIO_BEAR = {"AVOID", "SELL", "EXIT", "TRIM", "REDUCE", "HOLD_REDUCE"}
_STANCE_EXCLUDE_SYMBOLS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VIX", "TLT", "IEF", "HYG", "LQD", "USO", "GLD", "SLV",
})

# Investment-shaped tokens in Telegram text (Buy / Strong Buy / Accumulate / Add / Bullish / GO).
_INVESTMENT_BULL = re.compile(
    r"\b(GO|A\+|BUY|STRONG\s+BUY|ADD(?:_ON_PULLBACK)?|ACCUMULATE|BULLISH|BUY_READY|ENTRY_NEAR)\b",
    re.I,
)
_INVESTMENT_BEAR = re.compile(
    r"\b(AVOID|SELL|EXIT|TRIM|REDUCE|DO NOT BUY|BEARISH)\b",
    re.I,
)

HELD_DISAGREEMENT = "cio_stance_conflict"
HELD_MISSING = "cio_decision_missing"


def hold_receipts_path() -> Optional[Path]:
    """Durable hold receipt path.

    * ``CIO_STANCE_HOLD_RECEIPTS`` redirects (tests) or disables (``0``/``off``).
    * Default: ``persistent-state/data/cio/cio_telegram_stance_holds.jsonl``.
    """
    raw = str(os.environ.get("CIO_STANCE_HOLD_RECEIPTS") or "").strip()
    if raw.lower() in {"0", "off", "false", "no", "disable"}:
        return None
    if raw:
        return Path(raw)
    try:
        from scripts.lib.persistent_state_root import production_state_root
    except Exception:  # noqa: BLE001
        try:
            from lib.persistent_state_root import production_state_root  # type: ignore
        except Exception:  # noqa: BLE001
            return None
    return production_state_root() / "data" / "cio" / "cio_telegram_stance_holds.jsonl"


def _should_persist_hold() -> bool:
    """Production records; pytest only when ``CIO_STANCE_HOLD_RECEIPTS`` is set."""
    if str(os.environ.get("CIO_STANCE_HOLD_RECEIPTS_DISABLE") or "").strip() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and not str(
        os.environ.get("CIO_STANCE_HOLD_RECEIPTS") or ""
    ).strip():
        return False
    return hold_receipts_path() is not None


def record_hold(
    verdict: "StanceGateVerdict",
    *,
    source: str = "check_investment_send",
) -> Optional[Path]:
    """Append one hold receipt. No-op when allowed or persistence disabled."""
    if verdict.allow or not _should_persist_hold():
        return None
    path = hold_receipts_path()
    if path is None:
        return None
    row = {
        "schema": HOLD_RECEIPT_SCHEMA,
        "authority": AUTHORITY,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "symbol": verdict.symbol,
        "held_reason": verdict.held_reason,
        "message_stance": verdict.message_stance,
        "cio_action": verdict.cio_action,
        "cio_side": verdict.cio_side,
        "mbi_behavior": 0,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return path
    except OSError:
        return None


@dataclass(frozen=True)
class StanceGateVerdict:
    allow: bool
    held_reason: Optional[str] = None
    symbol: Optional[str] = None
    message_stance: Optional[str] = None
    cio_action: Optional[str] = None
    cio_side: Optional[str] = None
    schema: str = SCHEMA
    authority: str = AUTHORITY

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def cio_side(action: Optional[str]) -> str:
    a = str(action or "").upper().strip()
    if a in _CIO_BULL:
        return "bullish"
    if a in _CIO_BEAR:
        return "bearish"
    return "neutral"


def text_is_investment_shaped(text: str) -> bool:
    """True when the body carries Buy/Accumulate/GO/Bullish (or bearish) stance words."""
    t = text or ""
    return bool(_INVESTMENT_BULL.search(t) or _INVESTMENT_BEAR.search(t))


def infer_message_stance(text: str, symbol: str) -> Optional[str]:
    """Stance asserted near ``symbol`` in the message, else whole-text investment shape."""
    sym = (symbol or "").upper().strip()
    if not sym or sym in _STANCE_EXCLUDE_SYMBOLS:
        return None
    plain = re.sub(r"<[^>]+>", " ", text or "")
    for m in re.finditer(rf"(?<![A-Z]){re.escape(sym)}(?![A-Z])", plain, flags=re.I):
        window = plain[max(0, m.start() - 80): m.end() + 80]
        bull, bear = _INVESTMENT_BULL.search(window), _INVESTMENT_BEAR.search(window)
        if bull and not bear:
            return "bullish"
        if bear and not bull:
            return "bearish"
    # Publishers (GO / proposal cards) often put the stance token before the ticker.
    if _INVESTMENT_BULL.search(plain) and not _INVESTMENT_BEAR.search(plain):
        return "bullish"
    if _INVESTMENT_BEAR.search(plain) and not _INVESTMENT_BULL.search(plain):
        return "bearish"
    return None


def load_cio_view(
    symbol: str,
    db_query: Optional[Callable[..., list[dict]]] = None,
) -> Optional[dict[str, Any]]:
    """Latest ``cio_decisions`` row for ``symbol`` (3-day window). None = missing / unreadable."""
    sym = (symbol or "").upper().strip()
    if not sym or db_query is None:
        return None
    try:
        rows = db_query(
            "SELECT DISTINCT ON (symbol) symbol, action, status, created_at FROM cio_decisions"
            " WHERE symbol = ANY(%s) AND created_at > now() - interval '3 days'"
            " ORDER BY symbol, created_at DESC",
            ([sym],),
        ) or []
    except Exception:  # noqa: BLE001 — fail closed at the call site
        return None
    for r in rows:
        if str(r.get("symbol") or "").upper() == sym:
            return dict(r)
    return None


def check_investment_send(
    *,
    symbol: str,
    message_text: str = "",
    asserted_stance: Optional[str] = None,
    db_query: Optional[Callable[..., list[dict]]] = None,
    cio_view: Optional[dict[str, Any]] = None,
    source: str = "check_investment_send",
) -> StanceGateVerdict:
    """Allow or hold an investment-shaped Telegram send for one symbol.

    ``asserted_stance`` lets GO publishers declare bullish without relying on
    text proximity. When neither asserted nor inferred stance is investment-shaped,
    the gate is a no-op (allow) — non-recommendation traffic must not be blocked.

    Holds are appended to ``cio_telegram_stance_holds.jsonl`` (see ``record_hold``).
    """
    sym = (symbol or "").upper().strip()
    if not sym or sym in _STANCE_EXCLUDE_SYMBOLS:
        return StanceGateVerdict(allow=True, symbol=sym or None)

    said = (asserted_stance or "").strip().lower() or infer_message_stance(message_text, sym)
    if said not in ("bullish", "bearish"):
        return StanceGateVerdict(allow=True, symbol=sym, message_stance=said)

    view = cio_view if cio_view is not None else load_cio_view(sym, db_query)
    if not view:
        verdict = StanceGateVerdict(
            allow=False,
            held_reason=HELD_MISSING,
            symbol=sym,
            message_stance=said,
        )
        record_hold(verdict, source=source)
        return verdict

    action = str(view.get("action") or "").upper()
    side = cio_side(action)
    if said != side:
        verdict = StanceGateVerdict(
            allow=False,
            held_reason=HELD_DISAGREEMENT,
            symbol=sym,
            message_stance=said,
            cio_action=action or None,
            cio_side=side,
        )
        record_hold(verdict, source=source)
        return verdict
    return StanceGateVerdict(
        allow=True,
        symbol=sym,
        message_stance=said,
        cio_action=action or None,
        cio_side=side,
    )


__all__ = [
    "AUTHORITY",
    "HELD_DISAGREEMENT",
    "HELD_MISSING",
    "HOLD_RECEIPT_SCHEMA",
    "SCHEMA",
    "StanceGateVerdict",
    "check_investment_send",
    "cio_side",
    "hold_receipts_path",
    "infer_message_stance",
    "load_cio_view",
    "record_hold",
    "text_is_investment_shaped",
]
