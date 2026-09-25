"""CIO stance hard gate for investment-shaped Telegram sends.

Audit 2026-09-18: Comms Editor could annotate Buy-vs-AVOID and still send;
proposal / screener GO / social GO never joined ``cio_decisions``. INTERDICT is
a kill switch, not stance approval.

This module is the minimum hard gate:

* A bullish send against CIO ``AVOID`` or ``SELL`` is a hard hold
  (``allow=False``, ``held_reason=cio_stance_conflict``).
* ``HOLD`` and epistemic gaps (``RESEARCH_MORE``, ``HUMAN_REVIEW``,
  ``ADD_REVIEW``, ``NEUTRAL``, ``UNSTATED``) rewrite ``GO``/``BUY``/``ACCUMULATE``
  to ``WATCH`` and allow the send, with a stance footer. Missing CIO row stays
  fail-closed (``cio_decision_missing``).
* Every other non-bullish CIO action (``TRIM``, ``EXIT``, ``REDUCE``, ``WAIT``,
  ``NO_GO``, unknown) still holds a bullish send. Those are neither the named
  interdict pair nor a listed soft gap, so they keep the pre-M5 fail-closed hold.
* Every hold appends a durable receipt line
  (``cio_telegram_stance_holds.jsonl``), at most once per identical hold per
  ``CIO_STANCE_HOLD_DEDUPE_SECONDS`` window (publishers re-run every few
  minutes; the hold is enforced every run, only the repeat ledger row is
  skipped), so ``LIVE-cio-stance-governance``
  (24/7 multi-workflow) can be observed from the served release — not only as a
  log line. Formerly ``PARTIAL-telegram-CIO-stance`` (weekday equity-only bar).

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
SUMMARY_SCHEMA = "CioTelegramStanceHoldSummary@v2"
AUTHORITY = "READ_ONLY_ADVISORY"
GAP_ID = "LIVE-cio-stance-governance"
GAP_ID_FORMER = "PARTIAL-telegram-CIO-stance"

#: Live producers that call ``check_investment_send``. Their holds prove
#: LIVE-cio-stance-governance OBSERVED_LIVE when stamped
#: ``source=check_investment_send`` (ledger proof). Canary/probe sources stay
#: distinct. Set is workflow-agnostic (GO / scalp / proposal); day-of-week is
#: not a filter — 24/7 continuous governance.
ORGANIC_HOLD_CALLERS = frozenset(
    {
        "screener_go_alerts",
        "send_telegram_proposal_alert",
        "social_scalp_scanner",
    }
)

# Mirror comms_editor vocabulary so publisher + transport agree.
_CIO_BULL = {
    "BUY", "ADD", "ADD_ON_PULLBACK", "ACCUMULATE", "INITIATE", "REENTER", "RE_ENTER",
    "BUY_READY", "ENTRY_NEAR",
}
_CIO_BEAR = {"AVOID", "SELL", "EXIT", "TRIM", "REDUCE", "HOLD_REDUCE"}
# Broad market *context* tickers only (not investment advisories). Commodity /
# sector ETFs (GLD, SLV, USO, …) are gated — asset-agnostic 24/7 definition.
_STANCE_EXCLUDE_SYMBOLS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VIX",
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

# Active policy interdicts. A bullish proposal against these is a hard block.
HARD_BLOCK_STANCES = frozenset({"AVOID", "SELL"})
# HOLD plus epistemic gaps: GO/BUY/ACCUMULATE rewrite to WATCH and still send.
SOFT_REWRITE_STANCES = frozenset({
    "HOLD", "RESEARCH_MORE", "HUMAN_REVIEW", "ADD_REVIEW", "NEUTRAL", "UNSTATED",
})
_BULLISH_PROPOSALS = frozenset({"GO", "BUY", "ACCUMULATE"})


def hold_receipts_path() -> Optional[Path]:
    """Durable hold receipt path.

    * ``CIO_STANCE_HOLD_RECEIPTS`` redirects (tests) or disables (``0``/``off``).
    * Default: prefer ``~/.local/state/tradeai/`` (readable without release-write),
      then persistent-state when present.
    """
    raw = str(os.environ.get("CIO_STANCE_HOLD_RECEIPTS") or "").strip()
    if raw.lower() in {"0", "off", "false", "no", "disable"}:
        return None
    if raw:
        return Path(raw)
    # Prefer local primary so measurement works without release-write.
    # Dual-write in record_hold still mirrors to persistent-state when present.
    return Path.home() / ".local/state/tradeai/cio_telegram_stance_holds.jsonl"


#: Default repeat-suppression window for identical hold receipts. Override with
#: ``CIO_STANCE_HOLD_DEDUPE_SECONDS`` (``0`` disables dedupe).
DEFAULT_HOLD_DEDUPE_SECONDS = 3600


def hold_dedupe_seconds() -> int:
    raw = str(os.environ.get("CIO_STANCE_HOLD_DEDUPE_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_HOLD_DEDUPE_SECONDS
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_HOLD_DEDUPE_SECONDS


def _hold_dedupe_key(verdict: "StanceGateVerdict", gate_source: str, caller: Optional[str]) -> str:
    """Same hold = same producer, symbol, proposal, CIO decision and reason."""
    return "|".join(
        str(x or "")
        for x in (
            gate_source,
            caller,
            verdict.symbol,
            verdict.effective_action or verdict.message_stance,
            verdict.cio_action,
            verdict.cio_as_of,
            verdict.held_reason,
        )
    )


def _dedupe_state_path(primary: Path) -> Path:
    return primary.with_name(primary.stem + ".dedupe.json")


def _claim_hold_slot(primary: Path, key: str, now: datetime) -> tuple[bool, int]:
    """Return ``(write_row, repeats_skipped_since_last_row)``.

    Best-effort: unreadable state writes the row (never loses a first hold).
    """
    window = hold_dedupe_seconds()
    if window <= 0:
        return True, 0
    state_path = _dedupe_state_path(primary)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    now_ts = now.timestamp()
    entry = state.get(key) if isinstance(state.get(key), dict) else None
    if entry and now_ts - float(entry.get("last_row_ts") or 0) < window:
        entry["repeats"] = int(entry.get("repeats") or 0) + 1
        write, repeats = False, 0
    else:
        repeats = int(entry.get("repeats") or 0) if entry else 0
        state[key] = {"last_row_ts": now_ts, "repeats": 0}
        write = True
    # Prune keys idle past the window so the state file stays small.
    state = {
        k: v for k, v in state.items()
        if isinstance(v, dict) and now_ts - float(v.get("last_row_ts") or 0) < window
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(state_path.suffix + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        tmp.replace(state_path)
    except OSError:
        pass
    return write, repeats


def _hold_write_targets(primary: Path) -> list[Path]:
    """Primary plus persistent-state mirror when env does not pin a single path."""
    raw = str(os.environ.get("CIO_STANCE_HOLD_RECEIPTS") or "").strip()
    if raw and raw.lower() not in {"0", "off", "false", "no", "disable"}:
        return [primary]
    targets = [primary]
    try:
        from scripts.lib.persistent_state_root import good_persistent_root

        persist = good_persistent_root() / "data" / "cio" / "cio_telegram_stance_holds.jsonl"
        if persist.parent.is_dir() and persist.resolve() != primary.resolve():
            targets.append(persist)
    except Exception:  # noqa: BLE001
        pass
    return targets


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


def _normalize_hold_source(source: str) -> tuple[str, Optional[str]]:
    """Return ``(source, caller)`` for the hold receipt.

    Organic producers keep ``source=check_investment_send`` (ledger proof) and
    record their name in ``caller``. Canary/probe/test sources stay as ``source``
    so they cannot be mistaken for organic.
    """
    s = str(source or "check_investment_send").strip() or "check_investment_send"
    if s in ORGANIC_HOLD_CALLERS:
        return "check_investment_send", s
    return s, None


def record_hold(
    verdict: "StanceGateVerdict",
    *,
    source: str = "check_investment_send",
    extra: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    """Append one hold receipt. No-op when allowed or persistence disabled."""
    if verdict.allow or not _should_persist_hold():
        return None
    path = hold_receipts_path()
    if path is None:
        return None
    gate_source, caller = _normalize_hold_source(source)
    now = datetime.now(timezone.utc)
    write, repeats = _claim_hold_slot(path, _hold_dedupe_key(verdict, gate_source, caller), now)
    if not write:
        return None
    row: dict[str, Any] = {
        "schema": HOLD_RECEIPT_SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": gate_source,
        "symbol": verdict.symbol,
        "held_reason": verdict.held_reason,
        "message_stance": verdict.message_stance,
        "cio_action": verdict.cio_action,
        "cio_side": verdict.cio_side,
        "mbi_behavior": 0,
    }
    if caller:
        row["caller"] = caller
    if verdict.cio_as_of:
        row["cio_as_of"] = verdict.cio_as_of
    if repeats:
        row["repeats_since_last_row"] = repeats
    if extra:
        row.update({k: v for k, v in extra.items() if k not in row})
    wrote: Optional[Path] = None
    line = json.dumps(row, sort_keys=True) + "\n"
    for target in _hold_write_targets(path):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
            if wrote is None:
                wrote = target
        except OSError:
            continue
    return wrote


def request_missing_stance_review(symbol: str, *, source: str) -> dict[str, Any]:
    """Queue a CIO review for a bullish send held for a missing stance. Never raises."""
    try:
        from scripts.lib.cio_stance_review_request import request_cio_review
    except Exception:  # noqa: BLE001
        try:
            from lib.cio_stance_review_request import request_cio_review  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {"review_requested": False, "review_status": f"import_error:{type(exc).__name__}"}
    gate_source, caller = _normalize_hold_source(source)
    return request_cio_review(symbol, source=gate_source, caller=caller)


@dataclass(frozen=True)
class StanceGateVerdict:
    allow: bool
    held_reason: Optional[str] = None
    symbol: Optional[str] = None
    message_stance: Optional[str] = None
    cio_action: Optional[str] = None
    cio_side: Optional[str] = None
    effective_action: Optional[str] = None
    annotation_text: str = ""
    cio_as_of: Optional[str] = None
    schema: str = SCHEMA
    authority: str = AUTHORITY

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_cio_stance_gate(
    proposal_symbol: str,
    proposal_action: str,
    cio_stance: Optional[str],
) -> tuple[bool, str, str, str]:
    """Bullish proposal versus one CIO stance.

    Returns ``(allow_send, effective_action, held_reason, annotation_text)``.

    ``AVOID`` and ``SELL`` hard-block a bullish proposal. ``HOLD`` and the
    epistemic gaps rewrite ``GO``/``BUY``/``ACCUMULATE`` to ``WATCH`` and allow
    the send. A matching bullish CIO action passes unchanged. ``proposal_symbol``
    is part of the call contract for receipts; the decision itself is stance-only.
    """
    del proposal_symbol  # stance comparison does not depend on the ticker
    norm_proposal = (proposal_action or "").upper().strip()
    norm_cio = (cio_stance or "").upper().strip() if cio_stance else "UNSTATED"

    if norm_cio in HARD_BLOCK_STANCES and norm_proposal in _BULLISH_PROPOSALS:
        return (
            False,
            norm_proposal,
            HELD_DISAGREEMENT,
            f"🚫 [BLOCKED] Proposal '{norm_proposal}' conflicts with active CIO Interdict: {norm_cio}",
        )

    if norm_cio in SOFT_REWRITE_STANCES:
        # None and blank already normalized to UNSTATED.
        effective = "WATCH" if norm_proposal in _BULLISH_PROPOSALS else norm_proposal
        if effective == "WATCH" and norm_proposal in _BULLISH_PROPOSALS:
            annotation = f"[CIO Stance: {norm_cio} — Action rewritten to WATCH]"
        else:
            annotation = f"[CIO Stance: {norm_cio} — Action: {effective}]"
        return (True, effective, "", annotation)

    return (True, norm_proposal, "", "")


def _proposal_verb(message_text: str, said: str) -> str:
    """Map a bullish or bearish message onto the verb the stance table uses."""
    plain = message_text or ""
    if re.search(r"\bACCUMULATE\b", plain, re.I):
        return "ACCUMULATE"
    if re.search(r"\bBUY\b", plain, re.I):
        return "BUY"
    if re.search(r"\bGO\b", plain, re.I):
        return "GO"
    if said == "bullish":
        return "GO"
    if said == "bearish":
        return "SELL"
    return (said or "").upper()


#: Labelled verdict lines in single-symbol publisher cards ("Decision: GO").
_LABELLED_BULL_LINE = re.compile(
    r"^(\s*(?:Decision|Action|Signal|Verdict|Rating|Recommendation)\s*:\s*)"
    r"(STRONG\s+BUY|ACCUMULATE|BUY|GO|A\+)\b",
    re.I | re.M,
)


def _demote_bullish(text: str, symbol: str) -> str:
    """Demote bullish verbs for one symbol to WATCH.

    Reuses the transport editor's C2 vocabulary so publisher and transport
    agree, then covers the two single-symbol card shapes it does not:
    an ``A+`` tier headline and a labelled ``Decision: GO`` line.
    """
    try:
        from lib.comms_editor import rewrite_bullish_to_watch  # noqa: PLC0415
    except ImportError:
        from scripts.lib.comms_editor import rewrite_bullish_to_watch  # type: ignore  # noqa: PLC0415
    out, _ = rewrite_bullish_to_watch(text, [symbol])
    sym = re.escape(symbol.upper())
    out = re.sub(rf"(?<![\w+])A\+(\s+\*?{sym}\b)", r"WATCH\1", out)
    return _LABELLED_BULL_LINE.sub(r"\1WATCH", out)


def apply_stance_rewrite(text: str, symbol: str, verdict: "StanceGateVerdict") -> str:
    """Demote a bullish verb to WATCH when required and append the stance footer.

    The footer only claims a rewrite that actually happened in the text.
    """
    note = (verdict.annotation_text or "").strip()
    if not note:
        return text or ""
    out = text or ""
    if verdict.effective_action == "WATCH" and symbol:
        demoted = _demote_bullish(out, symbol)
        if demoted == out:
            note = f"[CIO Stance: {verdict.cio_action or 'UNSTATED'}]"
        out = demoted
    if note not in out:
        out = out.rstrip() + "\n" + note
    return out

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
    request_review: bool = True,
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
        # OPERATOR DECISION 2026-09-23: a GO/BUY with no CIO stance stays held
        # AND forces a CIO review, so the next send has a stance to check.
        review: Optional[dict[str, Any]] = None
        if said == "bullish" and request_review:
            review = request_missing_stance_review(sym, source=source)
        elif said == "bullish":
            # Observe-only callers (Maria gate in observe mode) must not spend.
            review = {"review_requested": False, "review_status": "skipped_observe_only"}
        record_hold(verdict, source=source, extra=review)
        return verdict

    action = str(view.get("action") or "").upper()
    side = cio_side(action)
    as_of = view.get("created_at") or view.get("as_of")
    base = {
        "symbol": sym,
        "message_stance": said,
        "cio_action": action or None,
        "cio_side": side,
        "cio_as_of": str(as_of) if as_of else None,
    }
    if said == "bullish":
        proposal = _proposal_verb(message_text, said)
        allow_send, effective, reason, annotation = evaluate_cio_stance_gate(
            sym, proposal, action or "UNSTATED",
        )
        if allow_send and effective == "WATCH":
            return StanceGateVerdict(
                allow=True, effective_action=effective, annotation_text=annotation, **base,
            )
        if allow_send and side == "bullish":
            return StanceGateVerdict(allow=True, effective_action=effective, **base)
        # Hard interdict (AVOID/SELL), or a non-bullish CIO action that is not a
        # listed soft gap (TRIM, EXIT, WAIT, NO_GO, unknown): keep the hold.
        verdict = StanceGateVerdict(
            allow=False,
            held_reason=reason or HELD_DISAGREEMENT,
            effective_action=effective,
            annotation_text=annotation,
            **base,
        )
        record_hold(verdict, source=source)
        return verdict
    if said != side:
        verdict = StanceGateVerdict(allow=False, held_reason=HELD_DISAGREEMENT, **base)
        record_hold(verdict, source=source)
        return verdict
    return StanceGateVerdict(allow=True, **base)

def is_organic_hold_row(row: dict[str, Any]) -> bool:
    """True when a hold receipt proves a live producer (ledger close condition).

    Requires ``source=check_investment_send`` and ``caller`` in
    ``ORGANIC_HOLD_CALLERS``. Canary/probe sources never qualify.
    """
    if not isinstance(row, dict):
        return False
    if str(row.get("source") or "") != "check_investment_send":
        return False
    return str(row.get("caller") or "") in ORGANIC_HOLD_CALLERS


def load_hold_receipt_rows(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Load hold receipt JSONL rows from ``path`` or the default primary."""
    target = path if path is not None else hold_receipts_path()
    if target is None or not target.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out


def summarize_stance_holds(path: Optional[Path] = None) -> dict[str, Any]:
    """Count organic vs non-organic holds for LIVE-cio-stance-governance."""
    rows = load_hold_receipt_rows(path)
    organic = [r for r in rows if is_organic_hold_row(r)]
    other = [r for r in rows if not is_organic_hold_row(r)]
    latest = organic[-1] if organic else None
    return {
        "schema": SUMMARY_SCHEMA,
        "gap_id": GAP_ID,
        "gap_id_former": GAP_ID_FORMER,
        "authority": AUTHORITY,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "path": str(path or hold_receipts_path() or ""),
        "scope": "24/7 continuous; asset-agnostic; multi-workflow",
        "total": len(rows),
        "organic": len(organic),
        "non_organic": len(other),
        "observed": len(organic) > 0,
        "latest_organic": (
            {
                "as_of": latest.get("as_of"),
                "symbol": latest.get("symbol"),
                "caller": latest.get("caller"),
                "held_reason": latest.get("held_reason"),
            }
            if latest
            else None
        ),
        "mbi_behavior": 0,
    }


def write_organic_observe_receipt(summary: dict[str, Any]) -> list[str]:
    """Persist the latest observe summary for lane/timer evidence (not a hold).

    Never under pytest: test_report_organic_stance_hold_cli_exit_codes runs the
    CLI on a tmp fixture, and its summary overwrote the PRODUCTION receipt
    (path=/tmp/pytest-of-…/organic.jsonl, organic=1) -- the LIVE observe
    evidence was test data (M5 audit 2026-09-23). PYTEST_CURRENT_TEST is
    inherited by that subprocess, so the guard holds there too.
    """
    import json
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    payload = dict(summary)
    payload["schema"] = "CioTelegramStanceObserveReceipt@v1"
    body = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    written: list[str] = []
    targets = [Path.home() / ".local/state/tradeai/organic_stance_hold_observe.json"]
    try:
        from scripts.lib.persistent_state_root import good_persistent_root

        persist = (
            good_persistent_root()
            / "data"
            / "runtime"
            / "organic_stance_hold_observe.json"
        )
        if persist.parent.is_dir():
            targets.append(persist)
    except Exception:  # noqa: BLE001
        pass
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            written.append(str(target))
        except OSError:
            continue
    return written


__all__ = [
    "AUTHORITY",
    "GAP_ID",
    "GAP_ID_FORMER",
    "HELD_DISAGREEMENT",
    "HELD_MISSING",
    "HOLD_RECEIPT_SCHEMA",
    "ORGANIC_HOLD_CALLERS",
    "SCHEMA",
    "SUMMARY_SCHEMA",
    "StanceGateVerdict",
    "HARD_BLOCK_STANCES",
    "SOFT_REWRITE_STANCES",
    "apply_stance_rewrite",
    "check_investment_send",
    "cio_side",
    "evaluate_cio_stance_gate",
    "hold_receipts_path",
    "infer_message_stance",
    "is_organic_hold_row",
    "load_cio_view",
    "load_hold_receipt_rows",
    "record_hold",
    "summarize_stance_holds",
    "write_organic_observe_receipt",
    "text_is_investment_shaped",
]
