"""Momentum-scalp advisory alert: a fully-gated setup becomes an operator alert, not a paper order.

Operator decision 2026-10-03: momentum scalps feed the Active Trader as immediate alerts for a
manual decision; paper auto-trading stops. The generator calls this instead of inserting a
paper_trade_proposals row when the strategy's proposal_contract.delivery is "advisory_alert", so
nothing downstream (validation fast path, ATM) has a proposal to route.

One alert per symbol and setup per session window (ledger). Telegram goes through the
telegram_alert.send_telegram chokepoint (comms editor applies). Every alert is recorded to a JSONL
receipt the Active Trader surface can read.

AUTHORITY: READ_ONLY_ADVISORY. An alert is a notification; nothing here sizes, orders or stops.
MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data" / "runtime" / "scalp_advisory_alerts_sent.json"
RECEIPTS = ROOT / "data" / "scalp" / "scalp_advisory_alerts.jsonl"
SCHEMA = "ScalpAdvisoryAlert@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MESSAGE_CLASS = "operator_alert"


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def alert_key(signal: dict, session: str) -> str:
    setup = signal.get("setup_description") or signal.get("strategy_id") or "momentum_scalp"
    return f"{session}:{str(signal.get('symbol') or '').upper()}:{setup}"


def build_alert(signal: dict, *, gates: dict, window_end_et: str, session: str,
                now: Optional[datetime] = None) -> dict:
    """The alert payload: only values the signal and gates already carry."""
    now = now or datetime.now(timezone.utc)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": 0,
        "session": session,
        "key": alert_key(signal, session),
        "symbol": str(signal.get("symbol") or "").upper(),
        "strategy_id": signal.get("strategy_id") or "momentum_scalp",
        "setup": signal.get("setup_description"),
        "grade": signal.get("signal_grade"),
        "score": _num(signal.get("signal_score")),
        "price": _num(signal.get("price")),
        "rvol": _num(signal.get("rvol")),
        "float_m": _num(signal.get("float_m")),
        "gap_pct": _num(signal.get("gap_pct")),
        "catalyst": signal.get("catalyst"),
        "catalyst_verified": bool(signal.get("catalyst_verified")),
        "entry_high": _num(signal.get("entry_high")),
        "stop": _num(signal.get("stop_loss")),
        "target_1": _num(signal.get("target_1")),
        "target_2": _num(signal.get("target_2")),
        "gates": dict(gates or {}),
        "expires_et": window_end_et,
        "discovery_trace_id": signal.get("discovery_trace_id"),
        "alerted_at": now.isoformat(),
    }


def format_alert(item: dict) -> str:
    def f(v, fmt):
        return "n/a" if v is None else format(v, fmt)

    passed = ", ".join(k for k, v in (item.get("gates") or {}).items() if v) or "none recorded"
    cat = item.get("catalyst") or "none"
    cat_note = "verified" if item.get("catalyst_verified") else "unverified"
    return (
        f"⚡ SCALP SETUP {item['symbol']} — grade {item.get('grade') or 'n/a'}, score {f(item.get('score'), '.0f')}\n"
        f"Price ${f(item.get('price'), '.2f')} · RVOL {f(item.get('rvol'), '.1f')}x · "
        f"float {f(item.get('float_m'), '.1f')}M · gap {f(item.get('gap_pct'), '.1f')}%\n"
        f"Catalyst ({cat_note}): {str(cat)[:160]}\n"
        f"Plan: entry ≤ ${f(item.get('entry_high'), '.2f')} · stop ${f(item.get('stop'), '.2f')} · "
        f"target ${f(item.get('target_1'), '.2f')}\n"
        f"Gates passed: {passed}\n"
        f"Valid until {item.get('expires_et')} ET. Your decision on Active Trader — nothing is placed.\n"
        f"READ_ONLY_ADVISORY · MBI 0"
    )


def _load_ledger(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _append_receipt(path: Path, row: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass


def _default_send(text: str) -> bool:
    try:
        import telegram_alert as _ta  # type: ignore
    except ImportError:
        from scripts import telegram_alert as _ta  # type: ignore
    return bool(_ta.send_telegram(text, bypass_router=True, message_class=MESSAGE_CLASS))


def send_advisory_alert(signal: dict, *, gates: dict, window_end_et: str, session: str,
                        send: Optional[Callable[[str], bool]] = None,
                        ledger_path: Optional[Path] = None, receipts_path: Optional[Path] = None,
                        now: Optional[datetime] = None) -> dict:
    """Alert once per symbol+setup per session. Returns a receipt; never raises."""
    ledger_path = ledger_path or LEDGER
    receipts_path = receipts_path or RECEIPTS
    item = build_alert(signal, gates=gates, window_end_et=window_end_et, session=session, now=now)
    ledger = _load_ledger(ledger_path)
    if item["key"] in ledger:
        return {**item, "sent": False, "status": "DUPLICATE_SUPPRESSED"}
    try:
        ok = bool((send or _default_send)(format_alert(item)))
    except Exception as exc:  # noqa: BLE001 - an alert failure must not break generation
        ok = False
        item["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    receipt = {**item, "sent": ok, "status": "SENT" if ok else "SEND_FAILED"}
    if ok:
        ledger[item["key"]] = item["alerted_at"]
        try:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            pass
    _append_receipt(receipts_path, receipt)
    return receipt
