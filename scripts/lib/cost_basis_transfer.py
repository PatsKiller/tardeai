"""Auto-detect cross-account position transfers and carry forward cost basis history.

When the same ticker disappears from one account (e.g. fidelity_rollover_ira) and appears in another
(e.g. schwab_rollover_ira) during a holdings sync, this module pairs the move, records a transfer
event, and — when confidence is high — writes an explicit basis override so Schwab reconstruction
never fabricates basis.

Never infers basis silently without a known source position or fidelity PDF anchor.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OVERRIDES_PATH = PROJECT_ROOT / "data" / "portfolios" / "input" / "cost_basis_overrides.json"
FIDELITY_BASIS_PATH = PROJECT_ROOT / "data" / "portfolios" / "input" / "fidelity_cost_basis.json"
EVENTS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "cost_basis_transfer_events.json"

SKIP_SYMBOLS = frozenset({
    "CASH", "USD", "SPAXX", "FDRXX", "FZFXX", "FZDXX", "SPRXX", "FGTXX", "FMPXX", "FNSXX",
    "SWVXX", "SNVXX", "SNAXX", "SWGXX", "VMFXX", "VMRXX", "VUSXX",
})
KNOWN_BASIS_SOURCES = frozenset({
    "snaptrade", "fidelity_positions_pdf", "operator_provided", "operator_provided_carry_forward",
    "reconstructed_from_amounts", "transactions_sum", "csv_lot", "broker_api", "auto_transfer_history",
})


def _norm_account(acct: str) -> str:
    return (acct or "").strip().lower()


def _norm_symbol(sym: str) -> str:
    return (sym or "").strip().upper()


def _is_equity_row(row: dict[str, Any]) -> bool:
    sym = _norm_symbol(row.get("symbol") or "")
    if not sym or sym in SKIP_SYMBOLS:
        return False
    if row.get("is_cash"):
        return False
    return True


def index_positions(holdings_doc: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Map (account, symbol) → position row for equity holdings."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for h in (holdings_doc or {}).get("holdings") or []:
        if not _is_equity_row(h):
            continue
        key = (_norm_account(h.get("account") or ""), _norm_symbol(h.get("symbol") or ""))
        out[key] = h
    return out


def _shares(row: dict[str, Any] | None) -> float:
    if not row:
        return 0.0
    try:
        return float(row.get("shares") or 0)
    except (TypeError, ValueError):
        return 0.0


def _per_share_basis(row: dict[str, Any] | None, fidelity_ps: dict[str, float]) -> tuple[float | None, str]:
    """Return (per_share_basis, basis_source_label) from a departing position."""
    if not row:
        return None, ""
    shares = _shares(row)
    cb = row.get("cost_basis")
    try:
        cb_f = float(cb) if cb is not None else None
    except (TypeError, ValueError):
        cb_f = None
    if cb_f and shares > 0.001:
        src = str(row.get("cost_basis_source") or "holdings_cost_basis")
        return round(cb_f / shares, 6), src
    avg = row.get("avg_cost")
    try:
        avg_f = float(avg) if avg is not None else None
    except (TypeError, ValueError):
        avg_f = None
    if avg_f and avg_f > 0:
        return round(avg_f, 6), str(row.get("cost_basis_source") or "holdings_avg_cost")
    sym = _norm_symbol(row.get("symbol") or "")
    if sym in fidelity_ps:
        return round(float(fidelity_ps[sym]), 6), "fidelity_positions_pdf"
    return None, ""


def _share_match_ratio(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return 1.0 - abs(a - b) / max(a, b)


def _event_id(symbol: str, from_acct: str, to_acct: str, shares: float, on: str) -> str:
    sh = int(shares) if abs(shares - round(shares)) < 0.01 else round(shares, 4)
    return f"xfer-{on}-{symbol}-{from_acct}-to-{to_acct}-{sh}"


def detect_transfers(
    prior_doc: dict[str, Any] | None,
    current_doc: dict[str, Any],
    *,
    share_tol: float = 0.02,
    min_shares: float = 1.0,
    fidelity_ps: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Pair cross-account share movements for the same ticker between two holdings snapshots."""
    fidelity_ps = fidelity_ps if fidelity_ps is not None else _load_fidelity_per_share()
    prior = index_positions(prior_doc)
    current = index_positions(current_doc)
    keys = set(prior) | set(current)
    by_symbol: dict[str, list[dict[str, Any]]] = {}

    for acct, sym in keys:
        p_sh = _shares(prior.get((acct, sym)))
        c_sh = _shares(current.get((acct, sym)))
        delta = round(c_sh - p_sh, 6)
        if abs(delta) < share_tol:
            continue
        by_symbol.setdefault(sym, []).append({
            "account": acct,
            "prior_shares": p_sh,
            "current_shares": c_sh,
            "delta": delta,
            "prior_row": prior.get((acct, sym)),
            "current_row": current.get((acct, sym)),
        })

    events: list[dict[str, Any]] = []
    today = date.today().isoformat()

    for sym, moves in by_symbol.items():
        departures = [m for m in moves if m["delta"] < -min_shares]
        arrivals = [m for m in moves if m["delta"] > min_shares]
        if not departures or not arrivals:
            continue

        for dep in departures:
            dep_qty = abs(dep["delta"])
            best_arr = None
            best_ratio = 0.0
            for arr in arrivals:
                if dep["account"] == arr["account"]:
                    continue
                ratio = _share_match_ratio(dep_qty, arr["delta"])
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_arr = arr
            if not best_arr or best_ratio < 0.85:
                continue

            from_acct = dep["account"]
            to_acct = best_arr["account"]
            xfer_shares = round(min(dep_qty, best_arr["delta"]), 6)
            ps, basis_src = _per_share_basis(dep.get("prior_row"), fidelity_ps)

            if best_ratio >= 0.995 and ps is not None:
                confidence = "high"
                status = "auto_tagged"
            elif ps is not None:
                confidence = "medium"
                status = "needs_confirmation"
            else:
                confidence = "low"
                status = "needs_confirmation"

            events.append({
                "id": _event_id(sym, from_acct, to_acct, xfer_shares, today),
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "symbol": sym,
                "from_account": from_acct,
                "to_account": to_acct,
                "shares": xfer_shares,
                "per_share_basis": ps,
                "total_basis": round(ps * xfer_shares, 2) if ps else None,
                "basis_source": basis_src or None,
                "share_match_pct": round(best_ratio * 100, 2),
                "confidence": confidence,
                "status": status,
            })
    return events


def _load_fidelity_per_share() -> dict[str, float]:
    if not FIDELITY_BASIS_PATH.exists():
        return {}
    try:
        raw = json.loads(FIDELITY_BASIS_PATH.read_text())
        return {k: float(v) for k, v in raw.items() if not str(k).startswith("_")}
    except Exception:
        return {}


def _load_overrides_doc() -> dict[str, Any]:
    if not OVERRIDES_PATH.exists():
        return {"_description": "Explicit transfer-basis overrides.", "overrides": [],
                "candidate_mappings_needing_confirmation": [], "auto_transfer_events": []}
    return json.loads(OVERRIDES_PATH.read_text())


def _override_key(acct: str, sym: str) -> tuple[str, str]:
    a = _norm_account(acct)
    a = re.sub(r"_ira$", "", a)  # schwab_roth_ira ↔ schwab_roth normalization
    return a, _norm_symbol(sym)


def _has_override(overrides_doc: dict[str, Any], acct: str, sym: str) -> bool:
    for o in overrides_doc.get("overrides") or []:
        if _override_key(o.get("account", ""), o.get("symbol", "")) == _override_key(acct, sym):
            return True
    return False


def apply_transfer_events(
    events: list[dict[str, Any]],
    *,
    apply: bool = True,
    sync_source: str = "holdings_sync",
) -> dict[str, Any]:
    """Persist transfer events; auto-apply high-confidence basis overrides for Schwab destinations."""
    if not events:
        return {"events": 0, "applied_overrides": 0, "candidates": 0, "summary": "no transfers detected"}

    overrides_doc = _load_overrides_doc()
    applied = 0
    candidates = 0
    stamped = []

    for ev in events:
        ev = dict(ev)
        ev["sync_source"] = sync_source
        stamped.append(ev)
        sym = ev["symbol"]
        to_acct = ev["to_account"]
        ps = ev.get("per_share_basis")

        if ev.get("confidence") == "high" and ps and not _has_override(overrides_doc, to_acct, sym):
            if to_acct.startswith("schwab"):
                overrides_doc.setdefault("overrides", []).append({
                    "account": to_acct,
                    "symbol": sym,
                    "event_date": date.today().isoformat(),
                    "event_type": "Security Transfer",
                    "shares": ev.get("shares"),
                    "per_share_basis": round(float(ps), 4),
                    "source": "auto_transfer_history",
                    "from_account": ev.get("from_account"),
                    "transfer_event_id": ev.get("id"),
                    "note": f"Auto-tagged {ev.get('from_account')} → {to_acct} "
                            f"({ev.get('share_match_pct')}% share match, basis from {ev.get('basis_source')}).",
                })
                ev["status"] = "auto_applied"
                applied += 1
        elif ev.get("status") == "needs_confirmation" and ps:
            key = _override_key(to_acct, sym)
            existing = {_override_key(c.get("account", ""), c.get("symbol", ""))
                        for c in overrides_doc.get("candidate_mappings_needing_confirmation") or []}
            if key not in existing:
                overrides_doc.setdefault("candidate_mappings_needing_confirmation", []).append({
                    "account": to_acct,
                    "symbol": sym,
                    "event_date": date.today().isoformat(),
                    "event_type": "Security Transfer",
                    "shares": ev.get("shares"),
                    "candidate_per_share_basis": round(float(ps), 4),
                    "candidate_source": f"auto_transfer:{ev.get('from_account')}:{ev.get('basis_source')}",
                    "candidate_total_basis": ev.get("total_basis"),
                    "status": "needs_confirmation_before_apply",
                    "transfer_event_id": ev.get("id"),
                })
                candidates += 1

    events_doc = _load_events_doc()
    known_ids = {e.get("id") for e in events_doc.get("transfer_events") or []}
    for ev in stamped:
        if ev.get("id") not in known_ids:
            events_doc.setdefault("transfer_events", []).append(ev)

    if apply:
        _write_json_atomic(EVENTS_PATH, events_doc)
        if applied or candidates:
            _write_json_atomic(OVERRIDES_PATH, overrides_doc)

    summary = f"{len(stamped)} transfer(s): {applied} auto-applied, {candidates} need confirmation"
    return {
        "events": len(stamped),
        "applied_overrides": applied,
        "candidates": candidates,
        "transfer_events": stamped,
        "summary": summary,
    }


def tag_holdings_with_transfers(
    holdings_doc: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Annotate destination holdings rows with transfer history tags and basis when auto-applied."""
    if not events:
        return holdings_doc
    by_dest = {(_norm_account(e["to_account"]), _norm_symbol(e["symbol"])): e for e in events}
    for h in holdings_doc.get("holdings") or []:
        if not _is_equity_row(h):
            continue
        key = (_norm_account(h.get("account") or ""), _norm_symbol(h.get("symbol") or ""))
        ev = by_dest.get(key)
        if not ev:
            continue
        h["transfer_history_tag"] = {
            "event_id": ev.get("id"),
            "from_account": ev.get("from_account"),
            "to_account": ev.get("to_account"),
            "shares": ev.get("shares"),
            "per_share_basis": ev.get("per_share_basis"),
            "basis_source": ev.get("basis_source"),
            "confidence": ev.get("confidence"),
            "status": ev.get("status"),
            "detected_at": ev.get("detected_at"),
        }
        if ev.get("status") == "auto_applied" and ev.get("per_share_basis"):
            sh = _shares(h)
            if sh > 0:
                cb = round(sh * float(ev["per_share_basis"]), 2)
                h["cost_basis"] = cb
                h["cost_basis_source"] = "auto_transfer_history"
                h["basis_partial"] = False
                mv = h.get("market_value")
                if mv is not None:
                    h["gain_loss"] = round(float(mv) - cb, 2)
                    h["gain_loss_pct"] = round((float(mv) - cb) / cb * 100, 4) if cb > 0 else None
    return holdings_doc


def _load_events_doc() -> dict[str, Any]:
    if not EVENTS_PATH.exists():
        return {"_description": "Cross-account transfer detections with cost-basis carry-forward.",
                "transfer_events": []}
    try:
        return json.loads(EVENTS_PATH.read_text())
    except Exception:
        return {"_description": "Cross-account transfer detections with cost-basis carry-forward.",
                "transfer_events": []}


def _write_json_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(path)


def process_holdings_change(
    prior_doc: dict[str, Any] | None,
    current_doc: dict[str, Any],
    *,
    sync_source: str = "holdings_sync",
    apply: bool = True,
) -> dict[str, Any]:
    """Full pipeline: detect → basis overrides → transfer normalize (DB + provenance).

    Prefer position_transfer_normalize.process_and_normalize when available so
    Fidelity→Schwab / Trad→Roth movements get source tracking, transfer_history,
    performance_adjusted flags, audit log, and stop-impact flags. Falls back to
    basis-only tagging if the normalize module is unavailable.
    """
    # Prefer full transfer-aware normalization (2026-07-23)
    try:
        from lib.position_transfer_normalize import process_and_normalize
        full = process_and_normalize(
            prior_doc, current_doc, sync_source=sync_source, apply=apply
        )
        if full.get("events"):
            full["holdings_tagged"] = True
        return full
    except Exception:
        pass

    events = detect_transfers(prior_doc, current_doc)
    result = apply_transfer_events(events, apply=apply, sync_source=sync_source)
    if apply and events:
        tagged = tag_holdings_with_transfers(current_doc, result.get("transfer_events") or events)
        # Best-effort provenance stamps even without normalize module
        try:
            from lib.position_transfer_normalize import (
                classify_transfer_type, transfer_display_note, annotate_holding_row,
            )
            for ev in result.get("transfer_events") or events:
                ev = dict(ev)
                ev["transfer_type"] = classify_transfer_type(
                    ev.get("from_account") or "", ev.get("to_account") or ""
                )
                ev["display_note"] = transfer_display_note(ev["transfer_type"])
                for h in tagged.get("holdings") or []:
                    if ((h.get("account") or "").lower() == (ev.get("to_account") or "").lower()
                            and (h.get("symbol") or "").upper() == (ev.get("symbol") or "").upper()):
                        annotate_holding_row(h, ev)
        except Exception:
            pass
        result["holdings_tagged"] = True
        return {**result, "holdings_doc": tagged}
    return result