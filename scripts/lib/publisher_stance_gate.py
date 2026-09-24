"""Publisher-level CIO stance gate for the scheduled recommendation senders.

M5 audit 2026-09-23 (Module 4, 4d): only three publishers called the stance
gate (screener_go_alerts, send_telegram_proposal_alert, social_scalp_scanner).
Every other sender with GO/BUY vocabulary relied on the transport comms editor,
which fails open and only matches a stance within 60 characters of a ticker.

This module is the one place those senders call. It never re-implements the
stance table: every decision comes from ``cio_telegram_stance_gate``'s public
API (``check_investment_send`` / ``apply_stance_rewrite``).

Shapes:

* ``gate_card`` -- one symbol, one message (entry alert, proposal card).
  Held -> do not send. Soft stance -> bullish verb demoted to WATCH + footer.
* ``gate_bullish_symbols`` -- a digest's list of bullish symbols. Held symbols
  are dropped and counted, soft stances move to WATCH, the rest pass. One held
  symbol never silences the digest.
* ``stamp_symbols`` -- CIO stance footer only, no hold. For text that is not a
  house recommendation (CIO-authored entry pages, agent-conflict reviews), where
  gating would be circular or would suppress a review prompt.

Only BULLISH text is gated here. Bearish / protective text (stop proximity,
downgrades, sells) is never held by this module.

If the CIO decision store cannot be read at all, bullish symbols are held with
``cio_gate_unavailable`` (fail closed) and nothing is written to the hold
ledger as ``cio_decision_missing`` -- an outage is not a missing CIO review.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:  # scripts/ on sys.path (cron)
    from lib import cio_telegram_stance_gate as SG
except ImportError:  # pragma: no cover - repo-root imports (tests)
    from scripts.lib import cio_telegram_stance_gate as SG  # type: ignore

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HELD_UNAVAILABLE = "cio_gate_unavailable"
SCHEMA = "PublisherStanceGate@v1"

DbQuery = Callable[..., list[dict]]

_DB_ENV_KEYS = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_PORT")


def _load_db_env_from_dotenv() -> None:
    """Cron senders do not all export DB_*; fill only missing DB_* keys from the repo .env."""
    if os.environ.get("DB_PASSWORD"):
        return
    env = PROJECT_ROOT / ".env"
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k in _DB_ENV_KEYS:
                os.environ.setdefault(k, v.strip().strip("\"'"))
    except OSError:
        return


def default_db_query() -> Optional[DbQuery]:
    """The comms editor's read-only query (2 s timeout), with DB_* filled from .env."""
    _load_db_env_from_dotenv()
    try:
        from lib.comms_editor import default_db_query as q  # noqa: PLC0415
    except ImportError:
        try:
            from scripts.lib.comms_editor import default_db_query as q  # type: ignore  # noqa: PLC0415
        except ImportError:
            return None
    return q


def _store_reachable(db_query: Optional[DbQuery]) -> bool:
    if db_query is None:
        return False
    try:
        db_query("SELECT 1 AS ok", None)
        return True
    except Exception as exc:  # noqa: BLE001 -- any failure means the gate cannot decide
        log.warning("publisher_stance_gate: CIO decision store unreachable (%s)", type(exc).__name__)
        return False


@dataclass
class SymbolOutcome:
    symbol: str
    outcome: str  # allowed | watch | held
    held_reason: Optional[str] = None
    cio_action: Optional[str] = None
    annotation: str = ""


@dataclass
class BullishGate:
    allowed: list[str] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    outcomes: dict[str, SymbolOutcome] = field(default_factory=dict)

    def held_line(self) -> str:
        """One count line for the digest, or '' when nothing was held."""
        if not self.held:
            return ""
        parts = []
        for s in self.held:
            o = self.outcomes[s]
            why = {
                SG.HELD_MISSING: "no CIO stance",
                HELD_UNAVAILABLE: "CIO store unreachable",
            }.get(o.held_reason or "", f"CIO {o.cio_action or '?'}")
            parts.append(f"{s} ({why})")
        return f"⏸ Held for CIO review ({len(self.held)}): " + ", ".join(parts)

    def stance_notes(self) -> list[str]:
        return [f"[CIO Stance: {s} {self.outcomes[s].cio_action or 'UNSTATED'} — shown as WATCH]"
                for s in self.watch]

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "allowed": list(self.allowed),
            "watch": list(self.watch),
            "held": {s: self.outcomes[s].held_reason for s in self.held},
        }


def gate_bullish_symbols(
    symbols: Iterable[str],
    *,
    source: str,
    db_query: Optional[DbQuery] = None,
    proposal_verb: str = "GO",
) -> BullishGate:
    """Gate a list of symbols a digest presents as bullish (GO / BUY / re-enter)."""
    q = db_query if db_query is not None else default_db_query()
    reachable = _store_reachable(q)
    out = BullishGate()
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        if not reachable:
            out.held.append(sym)
            out.outcomes[sym] = SymbolOutcome(sym, "held", HELD_UNAVAILABLE)
            continue
        v = SG.check_investment_send(
            symbol=sym, message_text=f"{proposal_verb} {sym}", asserted_stance="bullish",
            db_query=q, source=source,
        )
        if not v.allow:
            out.held.append(sym)
            out.outcomes[sym] = SymbolOutcome(sym, "held", v.held_reason, v.cio_action, v.annotation_text)
        elif v.effective_action == "WATCH":
            out.watch.append(sym)
            out.outcomes[sym] = SymbolOutcome(sym, "watch", None, v.cio_action, v.annotation_text)
        else:
            out.allowed.append(sym)
            out.outcomes[sym] = SymbolOutcome(sym, "allowed", None, v.cio_action, v.annotation_text)
    if out.held or out.watch:
        log.info("publisher_stance_gate[%s]: %s", source, out.receipt())
    return out


@dataclass
class CardGate:
    send: bool
    text: str
    held_reason: Optional[str] = None
    verdict: Optional[dict[str, Any]] = None


def gate_card(
    text: str,
    symbol: str,
    *,
    source: str,
    db_query: Optional[DbQuery] = None,
) -> CardGate:
    """One-symbol bullish card. Held -> send=False. Soft stance -> WATCH + footer."""
    sym = str(symbol or "").upper().strip()
    q = db_query if db_query is not None else default_db_query()
    if not _store_reachable(q):
        log.info("publisher_stance_gate[%s]: %s held (%s)", source, sym, HELD_UNAVAILABLE)
        return CardGate(False, text, HELD_UNAVAILABLE)
    v = SG.check_investment_send(
        symbol=sym, message_text=text, asserted_stance="bullish", db_query=q, source=source,
    )
    if not v.allow:
        log.info("publisher_stance_gate[%s]: %s held (%s, CIO %s)", source, sym, v.held_reason, v.cio_action)
        return CardGate(False, text, v.held_reason, v.as_dict())
    out = SG.apply_stance_rewrite(text, sym, v) if (v.annotation_text or "").strip() else text
    if v.effective_action == "WATCH" and out.startswith(text.rstrip()) and "WATCH" not in text:
        # Nothing in the card body was demotable (e.g. "🟢 READY"): say it up front.
        out = f"👀 WATCH — CIO stance {v.cio_action or 'UNSTATED'}\n" + out
    return CardGate(True, out, None, v.as_dict())


def stamp_symbols(
    text: str,
    symbols: Iterable[str],
    *,
    db_query: Optional[DbQuery] = None,
    note: str = "",
    exclude_decision_prefix: Optional[str] = None,
    only_conflicts: bool = False,
) -> str:
    """Append a CIO stance footer per symbol. Never holds.

    ``exclude_decision_prefix`` skips ``cio_decisions`` rows whose id starts with
    the prefix -- the entry-state runner writes its own ``cio-entry-*`` row
    before paging, so reading the latest row would just echo the page back.
    ``only_conflicts`` stamps only AVOID/SELL (for long digests).
    """
    q = db_query if db_query is not None else default_db_query()
    if q is None:
        return text
    lines = []
    for raw in symbols:
        sym = str(raw or "").upper().strip()
        if not sym:
            continue
        try:
            sql = ("SELECT DISTINCT ON (symbol) symbol, action, created_at FROM cio_decisions"
                   " WHERE symbol = ANY(%s) AND created_at > now() - interval '3 days'")
            params: tuple = ([sym],)
            if exclude_decision_prefix:
                sql += " AND decision_id NOT LIKE %s"
                params = ([sym], exclude_decision_prefix + "%")
            rows = q(sql + " ORDER BY symbol, created_at DESC", params) or []
        except Exception:  # noqa: BLE001 -- a footer must never cost the message
            continue
        action = str((rows[0] if rows else {}).get("action") or "").upper() or "NONE ON FILE"
        flag = " ⚠️ conflicts" if action in SG.HARD_BLOCK_STANCES else ""
        if only_conflicts and not flag:
            continue
        lines.append(f"[CIO Stance: {sym} {action}{flag}{(' — ' + note) if note else ''}]")
    if not lines:
        return text
    return text.rstrip() + "\n" + "\n".join(lines)


__all__ = [
    "HELD_UNAVAILABLE", "SCHEMA", "BullishGate", "CardGate", "SymbolOutcome",
    "default_db_query", "gate_bullish_symbols", "gate_card", "stamp_symbols",
]
