"""CIO Investment Intelligence Product — the four canonical books.

READ_ONLY_ADVISORY. Turns existing desks (re-entry, watchlist/queue, research,
Financial Senses, lessons, memory, regime) into:

  1. Market Temperament
  2. Re-Entry Book
  3. Opportunity Book
  4. Portfolio Action Book

and a CIORunWorker-compatible synthesis_fn that emits real recommendations.

Desk READY / IN_ZONE / NEAR is never auto-promoted to RE_ENTER.
A candidate-specific governed RE_ENTER is created only by adjudication:

  * explicit queue verdict RE_ENTER, or
  * IN_ZONE/READY + explicit ADD + valid FS + no restricting lesson
    when advisory influence is ACTIVE_ADVISORY/CANARY.

MEMORY_BEHAVIOR_INFLUENCE stays 0. Memory/lessons/FS never grant broker authority.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.lib.maturity_control.store import resolve_root
from scripts.lib.cio_production_eligibility import (
    classify_advisory_record,
    select_current_production_product,
    stamp_advisory_origin,
    unavailable_current_product,
)

SCHEMA = "CIOInvestmentProduct@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

READY_STATES = frozenset({"READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW", "IN_ZONE", "READY"})
AVOID_SIGNALS = frozenset({"ABOVE_ZONE"})
RESTRICT_LESSON = frozenset({"RESTRICTED", "RETIRED"})

# Category/aggregate labels that leaked into the former-holdings symbol column.
# They are not tickers and must never render as re-entry candidates.
NON_TICKER_SYMBOLS = frozenset({
    "HEALTH",
    "DAY_SWING",
    "POSITION",
    "LONG_TERM_COMPOUNDER",
    "CATEGORY",
    "SECTOR",
    "STYLE",
    "AGGREGATE",
    "UNKNOWN_CATEGORY",
})

_OPP_STATUS_PREF = {
    "REENTER": 0,
    "RE_ENTER": 0,
    "NEAR": 1,
    "WAIT": 2,
    "AVOID": 3,
    "not_former": 4,
}

# Pipeline 2B/2C surface caps. Provenance: T=template, D=deterministic, A=agent/memory.
EARNINGS_CAP = 10
NEW_NAME_CAP = 8
CASE_SUMMARY_CAP = 10
CASE_CONTENT_MAX = 400
CASH_ATTENTION_BAND_PCT = 20.0
NEW_NAME_SOURCE_PREFIXES = ("defense", "advisory")
PORTFOLIO_IMPLICATION_CONSTANT = (
    "Preserve quality growth exposure, keep cash for dislocations, "
    "and do not force lower-quality replacements. Re-entries need "
    "candidate-specific governed verdicts — desk zone marks are not authorization."
)
CASE_SUMMARY_BANNER = "A-context · NON_AUTHORITATIVE · does not change action"
EARNINGS_REL = Path("data") / "portfolios" / "state" / "earnings_dates.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(now: Optional[datetime] = None) -> str:
    return (now or _now()).replace(microsecond=0).isoformat()


def _fmt_num(v: Any, digits: int = 2) -> str:
    """Round floats for operator-facing strings; strip trailing zeros.

    1.3469600000000002 → '1.35'; 85.0 → '85'; None/bad → '?'
    """
    if v is None or v == "":
        return "?"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not (n == n):  # NaN
        return "?"
    s = f"{n:.{digits}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _round_pct(value: Any, nd: int = 2) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), nd)
    except (TypeError, ValueError):
        return value


def _env(name: str, default: str = "", env: Optional[dict[str, str]] = None) -> str:
    return str((env or os.environ).get(name) or default).strip()


def _influence_active(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    from scripts.lib.advisory_influence.gates import current_gates, present_enhanced
    from scripts.lib.agent_memory_shadow import memory_mode
    gates = current_gates(env)
    mem = memory_mode(env)
    return {
        "gates": gates,
        "lesson_enhanced": present_enhanced(gates["lesson_mode"]),
        "fs_enhanced": present_enhanced(gates["financial_senses_mode"]),
        "memory_enhanced": mem in {"CANARY", "ACTIVE_ADVISORY"},
        "memory_mode": mem,
        "memory_behavior_influence": _env("MEMORY_BEHAVIOR_INFLUENCE", "0", env) or "0",
        "financial_action": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _read_jsonl(path: Path, n: int = 200) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-n:]:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def paths(root: Path | str | None = None) -> dict[str, Path]:
    base = resolve_root(root) / "data" / "cio"
    return {
        "brief": base / "cio_investment_brief.json",
        "briefs": base / "cio_investment_briefs.jsonl",
        "verdicts": base / "cio_governed_verdicts.json",
        "verdicts_log": base / "cio_governed_verdicts.jsonl",
    }


# ── Collectors (fail-soft) ──────────────────────────────────────────────────


def collect_queue(root: Path | str | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.cio_opportunity_queue import build_queue_from_executor
        from scripts.db_adapter import _execute  # type: ignore
        return build_queue_from_executor(_execute)
    except Exception:
        pass
    try:
        import scripts.api_v2 as v2
        from scripts.lib.cio_opportunity_queue import build_queue_from_executor
        return build_queue_from_executor(v2._db_query)
    except Exception:
        return {"items": [], "top": [], "count": 0, "by_source": {}, "material": False}


def collect_previously_traded() -> list[dict[str, Any]]:
    sql = (
        "SELECT symbol, last_exit_price, current_price, reentry_zone_low, reentry_zone_high, "
        "reentry_signal, pct_above_exit, best_pnl_pct, is_currently_held "
        "FROM previously_traded_watchlist WHERE is_currently_held=false "
        "ORDER BY CASE reentry_signal WHEN 'IN_ZONE' THEN 0 WHEN 'WATCH' THEN 1 "
        "WHEN 'BELOW_ZONE' THEN 2 ELSE 3 END, best_pnl_pct DESC NULLS LAST, symbol ASC LIMIT 250"
    )
    try:
        import scripts.api_v2 as v2
        rows = v2._db_query(sql, fetch="all") or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def collect_holdings(root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    for rel in (
        "data/portfolios/state/holdings.json",
        "data/state/holdings.json",
    ):
        doc = _read_json(base / rel)
        if doc:
            return doc
    return {}


def collect_lessons(root: Path | str | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.maturity_control.lessons import collect_lessons
        return collect_lessons(root=root)
    except Exception:
        return {"lessons": [], "counts": {}}


def collect_fs(root: Path | str | None = None) -> list[dict[str, Any]]:
    rows = _read_jsonl(resolve_root(root) / "data/cio/agent_tool_traces.jsonl", 80)
    return [r for r in rows if r.get("fs_provider") or r.get("fs_capability")]


def collect_memory(root: Path | str | None = None) -> dict[str, Any]:
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        p = get_durable_provider(root)
        return {"health": p.health(), "counts": p.counts(), "sample": list(p._store.values())[:8]}
    except Exception:
        return {"health": {"status": "NOT_CONFIGURED"}, "counts": {}, "sample": []}


def collect_regime() -> dict[str, Any]:
    try:
        import scripts.api_v2 as v2
        row = v2._db_query(
            "SELECT regime_label, created_at FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1",
            fetch="one",
        )
        if row:
            return {"label": row.get("regime_label") or row.get("label"), "as_of": row.get("created_at")}
    except Exception:
        pass
    return {"label": "UNKNOWN", "as_of": None}


def _is_cash_holding(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("is_cash") or row.get("asset_type") == "cash":
        return True
    return str(row.get("symbol") or "").upper() == "CASH"


def _looks_like_ticker(sym: str) -> bool:
    s = str(sym or "").upper().strip()
    if not s or s in NON_TICKER_SYMBOLS or s == "CASH":
        return False
    # Drop CUSIP-like identifiers (digits) and overlong labels.
    if any(ch.isdigit() for ch in s):
        return False
    core = s.replace(".", "").replace("-", "")
    return core.isalpha() and 1 <= len(core) <= 6


def held_equity_symbols(holdings: dict[str, Any] | None) -> list[str]:
    """Tradable equity tickers currently held. Skips cash and CUSIPs."""
    held_map = holdings or {}
    out: list[str] = []
    rows = held_map.get("holdings")
    if isinstance(rows, list):
        for h in rows:
            if not isinstance(h, dict) or _is_cash_holding(h):
                continue
            sym = str(h.get("symbol") or "").upper()
            if _looks_like_ticker(sym):
                out.append(sym)
    elif isinstance(held_map.get("symbols"), list):
        for s in held_map["symbols"]:
            sym = str(s).upper()
            if _looks_like_ticker(sym):
                out.append(sym)
    # unique, stable
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ── Wave 2 slice 12 / 12a: instrument_id and DUST_RESIDUAL ──────────────────
# Threshold, rationale and the rejected weight-based alternative live in
# scripts/lib/holdings_universe.DUST_POLICY. This module applies that policy to
# an injected holdings dict so callers/tests need no filesystem.

def _row_market_value(row: dict[str, Any]) -> float | None:
    if not isinstance(row, dict):
        return None
    v = row.get("market_value")
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def market_value_by_symbol(holdings: dict[str, Any] | None) -> dict[str, float | None]:
    """Aggregate held market value per ticker. ``None`` = unknown, never dust."""
    rows = (holdings or {}).get("holdings")
    if not isinstance(rows, list):
        return {}
    known: dict[str, float] = {}
    unknown: set[str] = set()
    for h in rows:
        if not isinstance(h, dict) or _is_cash_holding(h):
            continue
        sym = str(h.get("symbol") or "").upper()
        if not _looks_like_ticker(sym):
            continue
        known.setdefault(sym, 0.0)
        mv = _row_market_value(h)
        if mv is None:
            unknown.add(sym)
        else:
            known[sym] += mv
    return {sym: (None if sym in unknown else round(total, 2)) for sym, total in known.items()}


def dust_symbols(holdings: dict[str, Any] | None) -> list[str]:
    """Held tickers below the documented dust floor. SCHG is the fixture."""
    from scripts.lib.holdings_universe import is_dust_market_value

    return sorted(s for s, mv in market_value_by_symbol(holdings).items() if is_dust_market_value(mv))


def held_equity_symbols_nondust(holdings: dict[str, Any] | None) -> list[str]:
    """held_equity_symbols minus DUST_RESIDUAL. The post-12a coverage universe."""
    dust = set(dust_symbols(holdings))
    return [s for s in held_equity_symbols(holdings) if s not in dust]


def collect_held_instrument_ids(holdings: dict[str, Any] | None) -> dict[str, Any]:
    """Held rows whose ``symbol`` is an instrument id (CUSIP), not a ticker.

    These rows must never be rendered as tickers. Reported separately so a
    surface that wants tickers gets tickers and a surface that wants the whole
    book can still show the unresolved ids honestly.
    """
    from scripts.lib.holdings_universe import classify_instrument_id

    rows = (holdings or {}).get("holdings")
    items: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for h in rows:
            if not isinstance(h, dict) or _is_cash_holding(h):
                continue
            raw = str(h.get("symbol") or "").upper().strip()
            if not raw or _looks_like_ticker(raw):
                continue
            items.append({
                "instrument_id": raw,
                "id_type": classify_instrument_id(raw),
                "is_ticker": False,
                "ticker": None,
                "account": h.get("account") or h.get("account_id"),
                "market_value": _row_market_value(h),
                "name": h.get("name"),
                "class": "D",
            })
    items.sort(key=lambda x: (str(x["instrument_id"]), str(x.get("account") or "")))
    return {
        "schema": "HeldInstrumentIds@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "instrument_id_n": len(items),
        "items": items,
        "class": "D",
        "note": (
            "CUSIP-only held rows are instrument_id, not ticker. No surface may "
            "render these in a ticker field and no thesis is minted for them."
        ),
    }


# Surface A former-sold probe (Wave 2 slice 04). Dust residual ≠ HELD.
SURFACE_A_STATUS_PROBE = ("SCHG", "AXTI", "FATN", "FANG")

# Wave 2 slice 28: how many PROVISIONAL lessons the product surfaces.
PROVISIONAL_LESSON_CAP = 8
_MATERIAL_HELD_MIN_SHARES = 1.0


def _holding_row_for_symbol(
    holdings: dict[str, Any] | None,
    symbol: str,
) -> dict[str, Any] | None:
    sym = str(symbol or "").upper()
    rows = (holdings or {}).get("holdings")
    if not isinstance(rows, list):
        return None
    for h in rows:
        if isinstance(h, dict) and str(h.get("symbol") or "").upper() == sym:
            return h
    return None


def _is_material_held_row(row: dict[str, Any] | None) -> bool:
    """True only for a real held sleeve. Fractional dust is not HELD for Surface A."""
    if not isinstance(row, dict) or _is_cash_holding(row):
        return False
    try:
        shares = float(row.get("shares") or row.get("broker_actual_shares") or 0)
    except (TypeError, ValueError):
        shares = 0.0
    return shares >= _MATERIAL_HELD_MIN_SHARES


def collect_surface_a_status(
    *,
    symbols: list[str] | tuple[str, ...] | None = None,
    holdings: dict[str, Any] | None = None,
    previously_traded: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify Surface A names HELD | EXITED | UNAVAILABLE. No invented prices.

    HELD = material held (≥1 share). EXITED = former table or dust residual.
    UNAVAILABLE = neither. Dust residual is EXITED, not HELD (operator: SCHG former).
    """
    holdings = holdings if holdings is not None else collect_holdings()
    prev = previously_traded if previously_traded is not None else collect_previously_traded()
    prev_syms = {
        str(r.get("symbol") or "").upper()
        for r in (prev or [])
        if isinstance(r, dict) and r.get("symbol")
    }
    probe = [str(s).upper() for s in (symbols or SURFACE_A_STATUS_PROBE) if str(s).strip()]
    items: list[dict[str, Any]] = []
    for sym in probe:
        row = _holding_row_for_symbol(holdings, sym)
        try:
            residual = float((row or {}).get("shares") or (row or {}).get("broker_actual_shares") or 0)
        except (TypeError, ValueError):
            residual = 0.0
        material = _is_material_held_row(row)
        dust = bool(row) and not material and residual > 0
        if material:
            status, reason = "HELD", "material_held"
        elif sym in prev_syms:
            status, reason = "EXITED", "previously_traded"
        elif dust:
            status, reason = "EXITED", "residual_dust_not_material_held"
        else:
            status, reason = "UNAVAILABLE", "not_in_holdings_or_former_table"
        item: dict[str, Any] = {
            "symbol": sym,
            "status": status,
            "status_reason": reason,
            "class": "D",
        }
        # Honesty only: residual share count when dust EXITED. Never invent prices.
        if dust:
            item["residual_shares"] = residual
        items.append(item)
    counts = {
        "HELD": sum(1 for i in items if i["status"] == "HELD"),
        "EXITED": sum(1 for i in items if i["status"] == "EXITED"),
        "UNAVAILABLE": sum(1 for i in items if i["status"] == "UNAVAILABLE"),
    }
    return {
        "schema": "SurfaceAStatus@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "surface": "A",
        "surface_name": "former holdings vs exit",
        "probe": probe,
        "counts": counts,
        "items": items,
        "class": "D",
        "note": "Dust residual (<1 share) is EXITED, not HELD. No invented prices.",
    }


def collect_holdings_thesis_coverage(
    *,
    holdings: dict[str, Any] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Every currently held equity → CURRENT or UNAVAILABLE. Never fake a thesis.

    Wave 2 slice 12a: DUST_RESIDUAL names are reported but excluded from
    ``held_n`` / ``current_n`` / ``unavailable_n``. A residual share left over
    from a sale is not a hold and must not manufacture a coverage hole. Lots
    are untouched — this is a label. ``held_n_including_dust`` keeps the old
    number visible so the change is auditable rather than silent.
    """
    from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
    from scripts.lib.holdings_universe import DUST_POLICY, DUST_STATUS, HELD_STATUS

    mv_by_symbol = market_value_by_symbol(holdings)
    dust = set(dust_symbols(holdings))
    dust_items: list[dict[str, Any]] = [
        {
            "symbol": sym,
            "holding_status": DUST_STATUS,
            "market_value": mv_by_symbol.get(sym),
            "threshold_usd": DUST_POLICY["threshold_usd"],
            "thesis_status": "NOT_REQUIRED",
            "thesis_status_reason": "dust_residual_not_a_hold",
            "class": "D",
        }
        for sym in sorted(dust)
    ]

    items: list[dict[str, Any]] = []
    for sym in held_equity_symbols_nondust(holdings):
        try:
            th = thesis_fields_for_symbol(sym, root=root)
        except Exception as exc:
            th = {
                "has_current_symbol_thesis": False,
                "thesis_state": "INSUFFICIENT_DATA",
                "thesis_unavailable_reason": type(exc).__name__,
            }
        has_th = bool(
            th.get("has_current_symbol_thesis")
            and (th.get("thesis_summary") or th.get("why_owned_or_watched"))
        )
        if has_th:
            items.append({
                "symbol": sym,
                "thesis_status": "CURRENT",
                "thesis_status_reason": None,
                "thesis_state": th.get("thesis_state"),
                "why_owned_or_watched": th.get("why_owned_or_watched"),
                "class": "D",
            })
        else:
            items.append({
                "symbol": sym,
                "thesis_status": "UNAVAILABLE",
                "thesis_status_reason": (
                    th.get("thesis_unavailable_reason")
                    or th.get("thesis_reason")
                    or th.get("thesis_state")
                    or "no living symbol thesis"
                ),
                "thesis_state": th.get("thesis_state") or "INSUFFICIENT_DATA",
                "why_owned_or_watched": None,
                "class": "D",
            })
    for row in items:
        row["holding_status"] = HELD_STATUS
        row["market_value"] = mv_by_symbol.get(row["symbol"])
    current_n = sum(1 for i in items if i["thesis_status"] == "CURRENT")
    instrument_ids = collect_held_instrument_ids(holdings)
    return {
        "held_n": len(items),
        "current_n": current_n,
        "unavailable_n": len(items) - current_n,
        "items": items,
        # Wave 2C item 118 — cost-basis provenance on the card. The basis and the
        # positions are dated separately from the reprice, so a reader can see
        # which of the three a number came from instead of assuming "now".
        "cost_basis_as_of": (holdings or {}).get("reconciled_at"),
        "positions_as_of": (holdings or {}).get("as_of"),
        "priced_as_of": (holdings or {}).get("last_repriced"),
        "cost_basis_sources": sorted({
            str(r.get("cost_basis_source"))
            for r in ((holdings or {}).get("holdings") or [])
            if isinstance(r, dict) and r.get("cost_basis_source")
        }),
        # Wave 2 slice 12a — dust is excluded from the counts above, not hidden.
        "held_n_including_dust": len(items) + len(dust_items),
        "dust_n": len(dust_items),
        "dust_tickers": sorted(dust),
        "dust_items": dust_items,
        "dust_policy": DUST_POLICY,
        # Wave 2 slice 12 — CUSIP-only rows are instrument ids, not tickers.
        "instrument_id_n": instrument_ids["instrument_id_n"],
        "instrument_ids": instrument_ids["items"],
        "class": "D",
        "no_fake_thesis": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
    }


def _is_new_name_source(source: Any) -> bool:
    s = str(source or "").strip().lower()
    return any(s == p or s.startswith(p) for p in NEW_NAME_SOURCE_PREFIXES)


def _parse_earnings_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text:
        return None
    for fmt, sl in (("%Y-%m-%d", 10), ("%Y/%m/%d", 10), ("%m/%d/%Y", 10)):
        try:
            return datetime.strptime(text[:sl], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def extract_cash_metrics(holdings: dict[str, Any] | None) -> dict[str, Any]:
    """Deterministic cash_pct / total_cash from holdings / portfolio_totals.

    Does not call a broker. Band is the engine attention threshold unless a
    numeric cash_target_range_pct is already on the holdings document.
    """
    doc = holdings if isinstance(holdings, dict) else {}
    totals = doc.get("portfolio_totals") if isinstance(doc.get("portfolio_totals"), dict) else {}
    total_cash = doc.get("cash")
    if total_cash is None:
        total_cash = doc.get("cash_value")
    if total_cash is None:
        total_cash = doc.get("total_cash")
    if total_cash is None:
        total_cash = totals.get("total_cash")
    total_value = doc.get("total_value")
    if total_value is None:
        total_value = totals.get("total_value")
    cash_pct = doc.get("cash_pct")
    if cash_pct is None:
        cash_pct = totals.get("cash_pct")
    if total_cash is None:
        rows = doc.get("holdings") if isinstance(doc.get("holdings"), list) else []
        cash_sum = 0.0
        found = False
        for h in rows:
            if isinstance(h, dict) and _is_cash_holding(h):
                found = True
                try:
                    cash_sum += float(h.get("market_value") or 0)
                except (TypeError, ValueError):
                    pass
        if found:
            total_cash = cash_sum
    try:
        total_cash_f = float(total_cash) if total_cash is not None else None
    except (TypeError, ValueError):
        total_cash_f = None
    try:
        total_value_f = float(total_value) if total_value is not None else None
    except (TypeError, ValueError):
        total_value_f = None
    try:
        cash_pct_f = float(cash_pct) if cash_pct is not None else None
    except (TypeError, ValueError):
        cash_pct_f = None
    if cash_pct_f is None and total_cash_f is not None and total_value_f not in (None, 0.0):
        cash_pct_f = (total_cash_f / total_value_f) * 100.0
    band_hi = CASH_ATTENTION_BAND_PCT
    band_lo = None
    band_source = "attention_threshold_pct"
    raw_band = doc.get("cash_target_range_pct") or totals.get("cash_target_range_pct")
    if isinstance(raw_band, (list, tuple)) and len(raw_band) >= 2:
        try:
            band_lo = float(raw_band[0])
            band_hi = float(raw_band[1])
            band_source = "holdings.cash_target_range_pct"
        except (TypeError, ValueError):
            pass
    elif isinstance(raw_band, (int, float)):
        band_hi = float(raw_band)
        band_source = "holdings.cash_target_range_pct"
    available = cash_pct_f is not None or total_cash_f is not None
    return {
        "total_cash": round(total_cash_f, 2) if total_cash_f is not None else None,
        "total_value": round(total_value_f, 2) if total_value_f is not None else None,
        "cash_pct": round(cash_pct_f, 2) if cash_pct_f is not None else None,
        "band": {"lo": band_lo, "hi": band_hi, "source": band_source},
        "quality": "OK" if available else "DATA_UNAVAILABLE",
        "class": "D",
    }


def cash_hold_row(metrics: dict[str, Any]) -> dict[str, Any]:
    """HOLD_CASH_FOR row from live numbers. Never the portfolio_implication constant."""
    cash_pct = metrics.get("cash_pct")
    total_cash = metrics.get("total_cash")
    band = metrics.get("band") or {}
    band_hi = band.get("hi")
    band_lo = band.get("lo")
    if cash_pct is None and total_cash is None:
        why = (
            "DATA_UNAVAILABLE — cash_pct and total_cash missing from "
            "holdings / cash_buying_power / portfolio"
        )
        quality = "DATA_UNAVAILABLE"
    elif cash_pct is not None and band_hi is not None and float(cash_pct) > float(band_hi):
        why = (
            f"cash_pct {_fmt_num(cash_pct)} total_cash {_fmt_num(total_cash)} "
            f"is above band {_fmt_num(band_hi)}; staged deploy vs hold reserve"
        )
        quality = "OK"
    elif cash_pct is not None and band_lo is not None and float(cash_pct) < float(band_lo):
        why = (
            f"cash_pct {_fmt_num(cash_pct)} total_cash {_fmt_num(total_cash)} "
            f"is below band {_fmt_num(band_lo)}; hold reserve"
        )
        quality = "OK"
    else:
        why = (
            f"cash_pct {_fmt_num(cash_pct)} total_cash {_fmt_num(total_cash)} "
            f"band {_fmt_num(band_lo)}–{_fmt_num(band_hi)} ({band.get('source')})"
        )
        quality = str(metrics.get("quality") or "OK")
    return {
        "symbol": "CASH",
        "action": "HOLD_CASH_FOR",
        "why": why,
        "cash_pct": cash_pct,
        "total_cash": total_cash,
        "band": band,
        "quality": quality,
        "class": "D",
    }


def collect_earnings_events(
    *,
    root: Path | str | None = None,
    holdings: dict[str, Any] | None = None,
    watch_symbols: list[str] | None = None,
    now: Optional[datetime] = None,
    cap: int = EARNINGS_CAP,
) -> dict[str, Any]:
    """Next dated earnings for held names first, then watch. Class D.

    Empty items only when the source file is missing/unreadable (or has no
    parseable dated events) — then quality=DATA_UNAVAILABLE, not a fake quiet night.
    """
    as_of = _iso(now)
    base = resolve_root(root)
    path = base / EARNINGS_REL
    source = str(path)
    if not path.is_file():
        return {
            "items": [],
            "count": 0,
            "quality": "DATA_UNAVAILABLE",
            "reason": "earnings_dates.json missing",
            "as_of": as_of,
            "source": source,
            "class": "D",
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "items": [],
            "count": 0,
            "quality": "DATA_UNAVAILABLE",
            "reason": f"earnings_dates.json unreadable:{type(exc).__name__}",
            "as_of": as_of,
            "source": source,
            "class": "D",
        }
    if not isinstance(raw, dict) or not raw:
        return {
            "items": [],
            "count": 0,
            "quality": "DATA_UNAVAILABLE",
            "reason": "earnings_dates.json empty or not an object",
            "as_of": as_of,
            "source": source,
            "class": "D",
        }
    today = (now or _now()).date()
    held = set(held_equity_symbols(holdings))
    watch = {str(s).upper() for s in (watch_symbols or []) if _looks_like_ticker(str(s))}
    dated: list[dict[str, Any]] = []
    for key, rec in raw.items():
        sym = str(key or "").upper()
        if not _looks_like_ticker(sym):
            continue
        blob = rec if isinstance(rec, dict) else {"earnings_date": rec}
        dt = _parse_earnings_date(blob.get("earnings_date") or blob.get("date"))
        if dt is None:
            continue
        dated.append({
            "symbol": sym,
            "earnings_date": dt.isoformat(),
            "_date": dt,
            "fetched_at": blob.get("fetched_at"),
            "source": "earnings_dates.json",
            "class": "D",
            "as_of": as_of,
        })

    def _sk(row: dict[str, Any]) -> tuple:
        d = row["_date"]
        delta = (d - today).days
        return (0 if delta >= 0 else 1, abs(delta), row["symbol"])

    held_dated = sorted((r for r in dated if r["symbol"] in held), key=_sk)
    watch_dated = sorted(
        (r for r in dated if r["symbol"] not in held and (not watch or r["symbol"] in watch)),
        key=_sk,
    )
    def _finalize(row: dict[str, Any], *, scope: str) -> dict[str, Any]:
        out = dict(row)
        dt = out.pop("_date", None)
        out["scope"] = scope
        # days_to_event from source date only — never invent a date.
        if dt is not None:
            out["days_to_event"] = (dt - today).days
        out.setdefault("source_as_of", out.get("fetched_at") or out.get("as_of"))
        # Slice 07: 1-line commentary only if a transcript row exists; else UNAVAILABLE.
        # No scrape, no LLM, no 4150 dump. Cap handled by collector.
        out["commentary"] = "UNAVAILABLE"
        out["commentary_reason"] = "no_earnings_transcript_row"
        out["commentary_class"] = "D"
        return out

    items: list[dict[str, Any]] = []
    for row in held_dated:
        items.append(_finalize(row, scope="held"))
        if len(items) >= cap:
            break
    if len(items) < cap:
        seen = {r["symbol"] for r in items}
        for row in watch_dated:
            if row["symbol"] in seen:
                continue
            items.append(_finalize(row, scope="watch"))
            seen.add(row["symbol"])
            if len(items) >= cap:
                break
    if not items and dated:
        # Source present with dates — never pretend it is a quiet night.
        for row in sorted(dated, key=_sk)[:cap]:
            items.append(_finalize(
                row, scope="held" if row["symbol"] in held else "watch",
            ))
    quality = "OK" if items else "DATA_UNAVAILABLE"
    reason = None if items else "no dated events in earnings_dates.json"
    return {
        "items": items,
        "count": len(items),
        "quality": quality,
        "reason": reason,
        "as_of": as_of,
        "source": source,
        "class": "D",
    }


def collect_case_summaries(
    *,
    root: Path | str | None = None,
    cap: int = CASE_SUMMARY_CAP,
) -> dict[str, Any]:
    """ACTIVE CASE_SUMMARY memories only. A-context, never action."""
    from scripts.lib.agent_memory_governance import MEMORY_TYPE_CASE_SUMMARY, STATUS_ACTIVE

    out: dict[str, Any] = {
        "banner": CASE_SUMMARY_BANNER,
        "authority_class": "NON_AUTHORITATIVE_CONTEXT",
        "class": "A",
        "source": "durable CASE_SUMMARY ACTIVE",
        "count": 0,
        "items": [],
        "financial_action": False,
        "changes_action": False,
    }
    try:
        from scripts.lib.agent_durable_memory import get_durable_provider
        provider = get_durable_provider(root)
    except Exception as exc:
        out["quality"] = "DATA_UNAVAILABLE"
        out["reason"] = f"memory_provider:{type(exc).__name__}"
        return out
    rows: list[dict[str, Any]] = []
    for rec in (getattr(provider, "_store", {}) or {}).values():
        if not isinstance(rec, dict):
            continue
        if rec.get("memory_type") != MEMORY_TYPE_CASE_SUMMARY:
            continue
        st = str(rec.get("status") or "")
        if st not in {STATUS_ACTIVE, "ADMITTED"}:
            continue
        rows.append(rec)
    rows.sort(
        key=lambda r: str(r.get("created_at") or r.get("admitted_at") or ""),
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    for rec in rows[:cap]:
        refs = [str(x) for x in (rec.get("source_refs") or rec.get("source_event_ids") or []) if x]
        plan_ids = [str(x) for x in (rec.get("plan_ids") or []) if x]
        plan_id = plan_ids[0] if plan_ids else (refs[0] if refs else None)
        result_id = None
        for ref in reversed(refs):
            if ref and ref != plan_id and not str(ref).startswith("res_"):
                result_id = ref
                break
        if not result_id and len(refs) >= 3:
            result_id = refs[-1]
        content = str(rec.get("content") or "")[:CASE_CONTENT_MAX]
        items.append({
            "memory_id": rec.get("memory_id"),
            "subject": rec.get("subject"),
            "symbols": list(rec.get("symbols") or []),
            "plan_id": plan_id,
            "hermes_result_id": result_id,
            "content": content,
            "created_at": rec.get("created_at") or rec.get("admitted_at"),
            "class": "A",
            "authority_class": "NON_AUTHORITATIVE_CONTEXT",
        })
    out["items"] = items
    out["count"] = len(items)
    return out


def collect_watch_block_summary(
    payload: dict[str, Any] | list | None = None,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Honest BLOCK histogram for watch items. Does not map BLOCK→READY or fire S7.

    G-ID-01: stamps ``subject_guid`` on top / ready_near_named rows when the
    identity registry resolves. Miss leaves guid unset and increments the miss
    counter — never ticker-as-GUID.
    """
    empty = {
        "count": 0,
        "by_reason": {},
        "top": [],
        "ready_count": 0,
        "ready_symbols": [],
        "near_symbols": [],
        "ready_near_named": [],
        "class": "D",
        "fires_s7": False,
        "note": "BLOCK is honest; not mapped to READY; does not fire S7",
    }
    try:
        from scripts.lib.data_broker.watch_intelligence import (
            list_watch_intelligence,
            project_watch_intelligence_for_cio,
        )
        if payload is None:
            payload = list_watch_intelligence({})
        proj = project_watch_intelligence_for_cio(payload)
    except Exception as exc:
        empty["quality"] = "DATA_UNAVAILABLE"
        empty["reason"] = type(exc).__name__
        return empty
    items = [r for r in (proj.get("items") or []) if isinstance(r, dict)]
    blocked = [r for r in items if str(r.get("status") or "") == "BLOCK"]
    by_reason: dict[str, int] = {}
    top: list[dict[str, Any]] = []
    for r in blocked:
        reason = str(r.get("map_reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if len(top) < 8:
            top.append({
                "symbol": r.get("symbol"),
                "reason": reason,
                "trade_ai_state": r.get("trade_ai_state"),
                "class": "D",
            })
    ready_symbols: list[str] = []
    near_symbols: list[str] = []
    ready_near_named: list[dict[str, Any]] = []
    for r in items:
        st = str(r.get("status") or "").upper()
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        if st in {"READY", "GO"}:
            if sym not in ready_symbols:
                ready_symbols.append(sym)
            ready_near_named.append({"symbol": sym, "status": st, "class": "D"})
        elif st == "NEAR":
            if sym not in near_symbols:
                near_symbols.append(sym)
            ready_near_named.append({"symbol": sym, "status": st, "class": "D"})
    # G-ID-01 carriage: stamp watch rows when registry resolves.
    try:
        from scripts.lib.cio_subject_guid import empty_carriage_metrics, stamp_subject_guid
        carriage = empty_carriage_metrics()
        top = [stamp_subject_guid(r, root=root, metrics=carriage) for r in top]
        ready_near_named = [
            stamp_subject_guid(r, root=root, metrics=carriage) for r in ready_near_named[:12]
        ]
    except Exception:
        carriage = {"subject_guid_hit": 0, "subject_guid_miss": 0}
        ready_near_named = ready_near_named[:12]
    return {
        "count": len(blocked),
        "by_reason": by_reason,
        "top": top,
        "ready_count": len(ready_symbols) + len(near_symbols),
        "ready_symbols": ready_symbols,
        "near_symbols": near_symbols,
        "ready_near_named": ready_near_named,
        "identity_carriage": carriage,
        "class": "D",
        "fires_s7": False,
        "note": "BLOCK is honest; not mapped to READY; does not fire S7",
    }


def _new_if_action(row: dict[str, Any]) -> str:
    """Decision language stays IF / WATCH / AVOID. Never invent a buy."""
    v = str(row.get("verdict") or "").upper()
    if v in {"EXIT", "TRIM"}:
        return "AVOID"
    if v == "ADD":
        return "ADD_IF"
    return "WATCH"


# ── Adjudication ────────────────────────────────────────────────────────────


def _queue_by_symbol(queue: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for it in (queue.get("items") or queue.get("top") or []):
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or "").upper()
        if not sym:
            continue
        out.setdefault(sym, []).append(it)
    return out


def _lesson_restricts(lessons: dict[str, Any], symbol: str) -> bool:
    for les in lessons.get("lessons") or []:
        if les.get("lifecycle") in RESTRICT_LESSON:
            syms = [str(s).upper() for s in (les.get("symbols") or [])]
            if symbol in syms:
                return True
    return False


def _fs_ok(fs_rows: list[dict[str, Any]]) -> bool:
    from scripts.lib.advisory_influence.gates import fs_receipt_eligible
    recent = fs_rows[-8:]
    if not recent:
        return False
    return any(fs_receipt_eligible(r) for r in recent)


def adjudicate_reentry(
    row: dict[str, Any],
    *,
    qitems: list[dict[str, Any]],
    lessons: dict[str, Any],
    fs_ok: bool,
    infl: dict[str, Any],
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    signal = str(row.get("reentry_signal") or row.get("state") or "").upper()
    verdicts = [str(i.get("verdict") or "").upper() for i in qitems]
    sources = {str(i.get("source") or "") for i in qitems}
    vs_exit_raw = row.get("pct_above_exit")
    try:
        vs_exit = float(vs_exit_raw) if vs_exit_raw is not None else None
    except (TypeError, ValueError):
        vs_exit = None
    zone_lo = row.get("reentry_zone_low")
    zone_hi = row.get("reentry_zone_high")
    zone = f"{_fmt_num(zone_lo) if zone_lo is not None else '?'}–{_fmt_num(zone_hi) if zone_hi is not None else '?'}"
    restrict = _lesson_restricts(lessons, symbol)

    # Symbol thesis (fail-soft) — never invent why_owned / why_exited
    thesis: dict[str, Any] = {}
    try:
        from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
        thesis = thesis_fields_for_symbol(symbol, root=row.get("_product_root"))
    except Exception:
        thesis = {"thesis_state": "INSUFFICIENT_DATA", "has_current_symbol_thesis": False}

    why_exited = thesis.get("why_exited")
    if why_exited in (None, "", "DATA_UNAVAILABLE"):
        why_sold = (
            f"DATA_UNAVAILABLE — no living exit thesis; mechanical last exit "
            f"{row.get('last_exit_price') or 'n/a'}."
        )
    else:
        why_sold = why_exited
    why_owned = thesis.get("why_owned_or_watched") or "DATA_UNAVAILABLE"
    what_changed = thesis.get("what_changed_since_exit") or "DATA_UNAVAILABLE"
    market_fit = (
        thesis.get("thesis_summary")
        or (f"thesis_state={thesis.get('thesis_state')}; role={thesis.get('portfolio_role')}")
    )
    prior_lessons = "restricting" if restrict else (
        "see_symbol_thesis" if thesis.get("has_current_symbol_thesis") else "none_documented"
    )

    status = "WAIT"
    governed = None
    change = "A candidate-specific governed RE_ENTER verdict plus non-stale confirmation."
    if "EXIT" in verdicts or "TRIM" in verdicts:
        status = "AVOID"
        change = "Restricting desk verdict is lifted."
    elif "RE_ENTER" in verdicts:
        status = "REENTER"
        governed = "RE_ENTER"
        change = "Governed RE_ENTER verdict is revoked or freshness blocks it."
    elif signal in AVOID_SIGNALS or (isinstance(vs_exit, (int, float)) and vs_exit > 25):
        status = "AVOID"
        change = "Price returns to the re-entry zone without chasing the extension."
    elif signal in READY_STATES or any(str(i.get("state") or "").upper() in READY_STATES for i in qitems):
        if restrict:
            status = "WAIT"
            change = "Restricting lesson is retired and zone confirmation remains."
        elif infl.get("lesson_enhanced") and "ADD" in verdicts and fs_ok:
            status = "REENTER"
            governed = "RE_ENTER"
            change = "ADD confluence, FS, or zone confirmation fails."
        elif len(sources) >= 2 or "ADD" in verdicts:
            status = "NEAR"
            change = "Second independent source + valid FS, or an explicit RE_ENTER verdict."
        else:
            status = "NEAR" if signal in {"IN_ZONE", "READY TO REVIEW", "READY", "NEAR ENTRY", "NEAR"} else "WAIT"
            change = "Independent research/queue confluence plus valid Financial Senses."

    # Thesis gaps cannot invent RE_ENTER; they can block weak promotion to actionable.
    thesis_state = str(thesis.get("thesis_state") or "")
    if governed == "RE_ENTER" and thesis_state in {"RESEARCH_REQUIRED", "STALE", "CONFLICTED"}:
        # Keep governed RE_ENTER if explicit queue verdict, but surface that thesis is incomplete
        change = (
            f"{change} Symbol thesis is {thesis_state} — operator should review thesis gaps "
            f"before treating this as high-conviction."
        )
    elif status in {"NEAR", "REENTER"} and thesis_state in {"RESEARCH_REQUIRED", "INSUFFICIENT_DATA"} and not governed:
        # Do not silently look "ready" without thesis; keep NEAR/WAIT and flag research
        if status == "REENTER":
            status = "NEAR"
        change = (
            f"Thesis {thesis_state}: specific research gaps must close before high-conviction RE_ENTER. "
            f"{change}"
        )

    try:
        from scripts.lib.research_prompt_context import latest_delta
        from scripts.lib.thesis_decision_gate import apply_thesis_decision_gate
        delta = latest_delta(symbol, root=row.get("_product_root"))
        thesis_gate = apply_thesis_decision_gate(
            current_action=status,
            governed_verdict=governed,
            thesis_state=thesis_state,
            thesis_stance=thesis.get("thesis_stance"),
            delta=delta,
        )
        status = thesis_gate["effective_action"]
        governed = thesis_gate["effective_governed_verdict"]
        if thesis_gate["restricted"]:
            change = f"{'/'.join(thesis_gate['reason_codes'])}. {change}"
    except Exception as gate_exc:
        thesis_gate = {
            "schema": "ThesisDecisionGate@v1",
            "restricted": False,
            "reason_codes": [f"GATE_UNAVAILABLE:{type(gate_exc).__name__}"],
            "authority": AUTHORITY,
            "financial_action": False,
        }

    what_changes = thesis.get("what_would_change") or []
    if isinstance(what_changes, list) and what_changes:
        change_thesis = "; ".join(str(x) for x in what_changes[:3])
    else:
        change_thesis = change

    rec = {
        "symbol": symbol,
        "status": status,
        "governed_verdict": governed,
        "why_sold": why_sold,
        "why_previously_owned": why_owned,
        "what_happened_since": (
            what_changed if what_changed not in (None, "DATA_UNAVAILABLE")
            else (
                f"Signal {signal or 'n/a'}; {_fmt_num(vs_exit)}% vs exit"
                if vs_exit is not None
                else f"Signal {signal or 'n/a'}."
            )
        ),
        "what_changed_since_exit": what_changed,
        "current_price": row.get("current_price"),
        "last_exit_price": row.get("last_exit_price"),
        "pct_above_exit": round(vs_exit, 2) if vs_exit is not None else None,
        "setup": f"Zone {zone}; desk {signal or 'n/a'}",
        "financial_senses": "valid_recent" if fs_ok else "none_or_stale",
        "research_change": f"queue_sources={sorted(sources)} verdicts={verdicts}",
        "market_fit": market_fit if thesis.get("has_current_symbol_thesis") else (
            f"DATA_UNAVAILABLE (desk temperament separate); thesis_state={thesis_state or 'INSUFFICIENT_DATA'}"
        ),
        "prior_lessons": prior_lessons,
        "entry_trigger": "Price in zone + governed RE_ENTER + non-stale confirmation",
        "invalidation": (
            "; ".join(str(x) for x in (thesis.get("invalidation_conditions") or [])[:3])
            if thesis.get("invalidation_conditions")
            else "Extension >25% above exit, restricting lesson, or stale FS used as truth"
        ),
        "suggested_advisory_size": "policy default; cash/risk first",
        "what_would_change": change_thesis,
        "thesis": thesis,
        "symbol_thesis_id": thesis.get("symbol_thesis_id"),
        "symbol_thesis_version": thesis.get("symbol_thesis_version"),
        "thesis_state": thesis_state or "INSUFFICIENT_DATA",
        "portfolio_role": thesis.get("portfolio_role") or "UNKNOWN",
        "portfolio_role_source": thesis.get("portfolio_role_source"),
        "research_gap_count": thesis.get("research_gap_count") or 0,
        "research_gaps": thesis.get("research_gaps") or [],
        "counter_thesis_state": thesis.get("counter_thesis_state"),
        "thesis_decision_gate": thesis_gate,
        "authority": AUTHORITY,
        "financial_action": False,
    }
    return rec


def apply_governed_verdicts(queue: dict[str, Any], verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    q = dict(queue or {})
    items = [dict(it) for it in (q.get("items") or q.get("top") or [])]
    by_v = {str(v.get("symbol") or "").upper(): v for v in verdicts if v.get("governed_verdict")}
    seen: set[str] = set()
    for it in items:
        sym = str(it.get("symbol") or "").upper()
        if sym in by_v:
            it["verdict"] = by_v[sym]["governed_verdict"]
            it["governed"] = True
            it["adjudication_status"] = by_v[sym].get("status")
            seen.add(sym)
    for sym, v in by_v.items():
        if sym in seen:
            continue
        items.append({
            "opportunity_key": f"cio-gov-{sym}",
            "source": "cio",
            "symbol": sym,
            "directive_label": f"CIO adjudicated {v['governed_verdict']}",
            "verdict": v["governed_verdict"],
            "state": None,
            "governed": True,
        })
    q["items"] = items
    q["top"] = items[:12]
    q["count"] = len(items)
    return q


# ── Books ───────────────────────────────────────────────────────────────────


def build_temperament(
    *,
    regime: dict[str, Any],
    holdings: dict[str, Any],
    fs_rows: list[dict[str, Any]],
    lessons: dict[str, Any],
    infl: dict[str, Any],
) -> dict[str, Any]:
    label = str(regime.get("label") or "UNKNOWN").replace("_", " ")
    cash_metrics = extract_cash_metrics(holdings)
    cash_f = cash_metrics.get("total_cash")
    if cash_f is None:
        cash_f = cash_metrics.get("cash_pct")
    fs_n = len(fs_rows)
    ratified = (lessons.get("counts") or {}).get("RATIFIED_CONTEXT") or 0
    if label.upper() in {"UNKNOWN", ""}:
        title = "CAUTIOUS / SELECTIVE — REGIME UNCONFIRMED"
    else:
        title = f"{label.upper()} — SELECTIVE RISK"
    return {
        "title": title,
        "regime": label,
        "regime_as_of": regime.get("as_of"),
        "cash": cash_f,
        "cash_pct": cash_metrics.get("cash_pct"),
        "cash_band": cash_metrics.get("band"),
        "cash_quality": cash_metrics.get("quality"),
        "cash_class": "D",
        "financial_senses_receipts": fs_n,
        "ratified_lessons": ratified,
        "influence": {
            "lesson_mode": infl["gates"]["lesson_mode"],
            "fs_mode": infl["gates"]["financial_senses_mode"],
            "memory_mode": infl["memory_mode"],
            "memory_behavior_influence": infl["memory_behavior_influence"],
        },
        "narrative": (
            f"Temperament {title}. Regime source as-of {regime.get('as_of') or 'n/a'}. "
            f"FS receipts in store: {fs_n}. Ratified lessons available: {ratified}."
        ),
        "portfolio_implication": PORTFOLIO_IMPLICATION_CONSTANT,
        "portfolio_implication_class": "T",
        "authority": AUTHORITY,
    }


def _infer_signal_from_queue_item(it: dict[str, Any]) -> str:
    state = str(it.get("state") or "").upper()
    if state in READY_STATES:
        return state
    label = str(it.get("directive_label") or it.get("label") or "").upper()
    if "IN ZONE" in label or "IN_ZONE" in label:
        return "IN_ZONE"
    if "NEAR" in label:
        return "NEAR ENTRY"
    if "READY" in label:
        return "READY TO REVIEW"
    if "OVERSOLD" in label:
        return "OVERSOLD REVIEW"
    if "ABOVE" in label:
        return "ABOVE_ZONE"
    if it.get("verdict") == "RE_ENTER":
        return "IN_ZONE"
    return "WATCH"


def _merge_prev_and_queue(prev: list[dict[str, Any]], queue: dict[str, Any]) -> list[dict[str, Any]]:
    """Former-holdings table plus re-entry desk/queue names (CSCO/ANET etc.)."""
    by: dict[str, dict[str, Any]] = {}
    for row in prev or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        if sym:
            by[sym] = dict(row)
            by[sym]["symbol"] = sym
    for it in (queue.get("items") or queue.get("top") or []):
        if not isinstance(it, dict):
            continue
        src = str(it.get("source") or "")
        label = str(it.get("directive_label") or "")
        if src != "reentry" and "re-entry" not in label.lower() and it.get("verdict") != "RE_ENTER":
            continue
        sym = str(it.get("symbol") or "").upper()
        if not sym:
            continue
        if sym not in by:
            by[sym] = {
                "symbol": sym,
                "reentry_signal": _infer_signal_from_queue_item(it),
                "source": "opportunity_queue",
                "directive_label": label,
            }
        else:
            by[sym].setdefault("reentry_signal", _infer_signal_from_queue_item(it))
    return list(by.values())


def build_reentry_book(
    prev: list[dict[str, Any]],
    queue: dict[str, Any],
    lessons: dict[str, Any],
    fs_rows: list[dict[str, Any]],
    infl: dict[str, Any],
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    by_q = _queue_by_symbol(queue)
    fs_ok = _fs_ok(fs_rows)
    rows = []
    # G-ID-01 carriage: stamp subject_guid when registry resolves; miss → unset + counter.
    try:
        from scripts.lib.cio_subject_guid import empty_carriage_metrics, stamp_subject_guid
        carriage = empty_carriage_metrics()
        _stamp = stamp_subject_guid
    except Exception:
        carriage = {"subject_guid_hit": 0, "subject_guid_miss": 0}
        _stamp = None
    for row in _merge_prev_and_queue(prev, queue):
        row = dict(row)
        sym = str(row.get("symbol") or "").upper()
        # Drop category/fund labels that are not tradable tickers.
        if sym in NON_TICKER_SYMBOLS:
            continue
        if root is not None:
            row["_product_root"] = str(root)
        rec = adjudicate_reentry(
            row, qitems=by_q.get(str(row.get("symbol") or "").upper(), []),
            lessons=lessons, fs_ok=fs_ok, infl=infl,
        )
        if _stamp is not None:
            try:
                rec = _stamp(rec, root=root, metrics=carriage)
            except Exception:
                rec.setdefault("subject_guid", None)
        rows.append(rec)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    thesis_incomplete = sum(
        1 for r in rows
        if str(r.get("thesis_state") or "") in {"RESEARCH_REQUIRED", "STALE", "CONFLICTED", "INSUFFICIENT_DATA"}
    )
    from scripts.lib.cio_reentry_surface_labels import SURFACE_A, banner as _scope_banner, stamp as _stamp_scope
    return _stamp_scope({
        "count": len(rows),
        "counts": counts,
        "thesis_incomplete_count": thesis_incomplete,
        "names": rows,
        "identity_carriage": carriage,
        "note": (
            f"{_scope_banner(SURFACE_A)}. "
            "IN_ZONE / READY / NEAR is not RE_ENTER. Governed verdicts are candidate-specific. "
            "Symbol thesis gaps are surfaced; mechanical why_sold placeholders replaced with "
            "DATA_UNAVAILABLE when no living exit thesis exists."
        ),
        "authority": AUTHORITY,
    }, SURFACE_A)


def _opportunity_row_pref(row: dict[str, Any]) -> tuple:
    """Lower tuple = better: prefer stronger status, then earlier queue order."""
    status = str(row.get("status") or "").upper()
    return (
        _OPP_STATUS_PREF.get(status, 9),
        int(row.get("_orig_i") or 9999),
        str(row.get("symbol") or ""),
    )


def build_opportunity_book(
    queue: dict[str, Any],
    reentry: dict[str, Any],
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    from scripts.lib.symbol_thesis_attach import opportunity_actionability, thesis_fields_for_symbol
    re_by = {r["symbol"]: r for r in reentry.get("names") or []}
    candidates: list[dict[str, Any]] = []
    for i, it in enumerate(queue.get("items") or queue.get("top") or []):
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or "").upper()
        if not sym or sym in NON_TICKER_SYMBOLS:
            continue
        vs_re = (re_by.get(sym) or {}).get("status") or "not_former"
        thesis = (re_by.get(sym) or {}).get("thesis") or thesis_fields_for_symbol(sym, root=root)
        row = {
            "_orig_i": i,
            "symbol": sym,
            "source": it.get("source"),
            "verdict": it.get("verdict"),
            "state": it.get("state"),
            "label": it.get("directive_label"),
            "vs_former_holdings": vs_re,
            "vs_re": vs_re,
            "status": vs_re if vs_re != "not_former" else it.get("state"),
            "thesis": thesis,
            "thesis_state": thesis.get("thesis_state"),
            "portfolio_role": thesis.get("portfolio_role"),
            "research_gap_count": thesis.get("research_gap_count") or 0,
            "research_gaps": thesis.get("research_gaps") or [],
            "symbol_thesis_version": thesis.get("symbol_thesis_version"),
            "why_outranks_cash_or_reentry": (
                f"Desk {it.get('source')} {it.get('verdict') or it.get('state') or 'watch'}; "
                f"former-holding status {vs_re or 'n/a'}; "
                f"thesis_state={thesis.get('thesis_state')}; gaps={thesis.get('research_gap_count') or 0}."
            ),
        }
        # Carry rounded zone/pct from re-entry adjudication when present (P2.9 helper).
        re_row = re_by.get(sym) or {}
        if re_row.get("setup"):
            row["setup"] = re_row.get("setup")
        if re_row.get("pct_above_exit") is not None:
            row["pct_above_exit"] = _round_pct(re_row.get("pct_above_exit"))
        elif it.get("pct_above_exit") is not None:
            row["pct_above_exit"] = _round_pct(it.get("pct_above_exit"))
        if it.get("reentry_zone_low") is not None or it.get("reentry_zone_high") is not None:
            row["zone"] = (
                f"{_fmt_num(it.get('reentry_zone_low'))}–{_fmt_num(it.get('reentry_zone_high'))}"
            )
        row["actionability"] = opportunity_actionability(row)
        if row["actionability"] == "RESEARCH_REQUIRED" and row.get("verdict") == "ADD":
            row["verdict_note"] = "ADD suppressed to RESEARCH_REQUIRED until thesis gaps close"
        candidates.append(row)

    # Dedupe by symbol — keep best rank/status (fixes AUUD-style duplicates).
    best_by_sym: dict[str, dict[str, Any]] = {}
    for row in candidates:
        sym = row["symbol"]
        prev = best_by_sym.get(sym)
        if prev is None or _opportunity_row_pref(row) < _opportunity_row_pref(prev):
            best_by_sym[sym] = row

    ranked = sorted(best_by_sym.values(), key=_opportunity_row_pref)[:20]
    # Bounded not_former defense/advisory slice — do not let ranking drop new names.
    not_former_items: list[dict[str, Any]] = []
    for row in sorted(best_by_sym.values(), key=lambda r: int(r.get("_orig_i") or 9999)):
        if str(row.get("vs_re") or row.get("vs_former_holdings") or "") != "not_former":
            continue
        if not _is_new_name_source(row.get("source")):
            continue
        item = {k: v for k, v in row.items() if k != "_orig_i"}
        not_former_items.append(item)
        if len(not_former_items) >= NEW_NAME_CAP:
            break
    seen_top = {r["symbol"] for r in ranked}
    for item in not_former_items:
        if item["symbol"] not in seen_top:
            ranked.append(dict(item))
            seen_top.add(item["symbol"])
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
        row.pop("_orig_i", None)
        row.setdefault("vs_re", row.get("vs_former_holdings"))
        row.setdefault("class", "D")
    # G-ID-01 carriage: stamp opportunity / not_former rows when registry resolves.
    try:
        from scripts.lib.cio_subject_guid import empty_carriage_metrics, stamp_subject_guid
        carriage = empty_carriage_metrics()
        ranked = [stamp_subject_guid(r, root=root, metrics=carriage) for r in ranked]
        not_former_items = [
            stamp_subject_guid(r, root=root, metrics=carriage) for r in not_former_items
        ]
    except Exception:
        carriage = {"subject_guid_hit": 0, "subject_guid_miss": 0}
    nf_reason = None
    if not not_former_items:
        nf_reason = "no not_former defense/advisory names in queue after held+reentry classification"
    return {
        "count": len(ranked),
        "top": ranked,
        "not_former": not_former_items,
        "not_former_count": len(not_former_items),
        "not_former_reason": nf_reason,
        "not_former_class": "D",
        "deduped_from": len(candidates),
        "identity_carriage": carriage,
        "note": (
            "New capital uses ranked against cash and former holdings. "
            "Unresolved material thesis gaps → RESEARCH_REQUIRED, not weak ADD/REENTER. "
            "Duplicate symbols collapsed to best status before ranking. "
            "not_former defense/advisory names are a bounded labeled slice, not a buy."
        ),
        "authority": AUTHORITY,
    }


def build_action_book(
    reentry: dict[str, Any],
    opportunities: dict[str, Any],
    temperament: dict[str, Any],
    *,
    holdings: Optional[dict[str, Any]] = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol
    do_now, watch, re_if, new_if, cash_for, avoid, research = [], [], [], [], [], [], []
    reentry_syms = {
        str(r.get("symbol") or "").upper()
        for r in (reentry.get("names") or [])
        if isinstance(r, dict) and r.get("symbol")
    }
    for r in reentry.get("names") or []:
        base = {
            "symbol": r["symbol"],
            "thesis_state": r.get("thesis_state"),
            "portfolio_role": r.get("portfolio_role"),
            "research_gaps": r.get("research_gaps") or [],
        }
        if r["status"] == "REENTER":
            do_now.append({**base, "action": "RE_ENTER", "why": r["what_would_change"]})
        elif r["status"] == "NEAR":
            watch.append({**base, "action": "WATCH", "why": r["setup"]})
            re_if.append({**base, "action": "RE_ENTER_IF", "why": r["what_would_change"]})
        elif r["status"] == "AVOID":
            avoid.append({**base, "action": "AVOID", "why": r["what_happened_since"]})
        else:
            re_if.append({**base, "action": "RE_ENTER_IF", "why": r["what_would_change"]})
        if (r.get("research_gap_count") or 0) > 0:
            research.append({
                **base,
                "action": "THESIS_RESEARCH",
                "why": "; ".join(str(x) for x in (r.get("research_gaps") or [])[:2]) or "thesis gaps",
            })
    for o in opportunities.get("top") or []:
        if o.get("actionability") == "RESEARCH_REQUIRED":
            research.append({
                "symbol": o["symbol"],
                "action": "THESIS_RESEARCH",
                "why": o.get("why_outranks_cash_or_reentry"),
                "thesis_state": o.get("thesis_state"),
                "portfolio_role": o.get("portfolio_role"),
                "research_gaps": o.get("research_gaps") or [],
            })
            continue
        if not o.get("verdict") and o.get("actionability") != "RESEARCH_REQUIRED":
            research.append({"symbol": o["symbol"], "action": "RESEARCH", "why": o.get("label")})

    # Current holdings — living thesis state for Portfolio Action Book
    held_thesis = []
    held_map = holdings or {}
    held_syms: list[str] = held_equity_symbols(held_map)
    if not held_syms:
        if isinstance(held_map.get("holdings"), list):
            for h in held_map["holdings"]:
                if isinstance(h, dict) and h.get("symbol") and not _is_cash_holding(h):
                    held_syms.append(str(h["symbol"]).upper())
        elif isinstance(held_map.get("symbols"), list):
            held_syms = [str(s).upper() for s in held_map["symbols"]]
    # also pull from reentry rows marked held via thesis memberships
    for r in reentry.get("names") or []:
        memb = (r.get("thesis") or {}).get("memberships") or []
        if "HELD" in memb and r["symbol"] not in held_syms:
            held_syms.append(r["symbol"])
    # G-ID-01 carriage for holdings thesis rows (product surface, not broker lots).
    try:
        from scripts.lib.cio_subject_guid import empty_carriage_metrics, stamp_subject_guid
        holdings_carriage = empty_carriage_metrics()
        _stamp_held = stamp_subject_guid
    except Exception:
        holdings_carriage = {"subject_guid_hit": 0, "subject_guid_miss": 0}
        _stamp_held = None
    for sym in sorted(set(held_syms)):
        th = thesis_fields_for_symbol(sym, root=root)
        held_row = {
            "symbol": sym,
            "action": "HOLD_REVIEW",
            "thesis_state": th.get("thesis_state"),
            "portfolio_role": th.get("portfolio_role"),
            "portfolio_role_source": th.get("portfolio_role_source"),
            "why_still_held": th.get("why_owned_or_watched") or "DATA_UNAVAILABLE",
            "counter_thesis": th.get("counter_evidence") or [],
            "research_gaps": th.get("research_gaps") or [],
            "what_would_change": th.get("what_would_change") or [],
            "symbol_thesis_version": th.get("symbol_thesis_version"),
        }
        if _stamp_held is not None:
            try:
                held_row = _stamp_held(held_row, root=root, metrics=holdings_carriage)
            except Exception:
                held_row.setdefault("subject_guid", None)
        held_thesis.append(held_row)
        if th.get("thesis_state") in {"STALE", "RESEARCH_REQUIRED", "CONFLICTED"}:
            research.append({
                "symbol": sym,
                "action": "THESIS_RESEARCH",
                "why": f"HELD thesis {th.get('thesis_state')}",
                "thesis_state": th.get("thesis_state"),
                "research_gaps": th.get("research_gaps") or [],
            })

    cash_for.append(cash_hold_row(extract_cash_metrics(held_map)))
    # NEW_POSITION_IF: bounded not_former defense/advisory slice. Not a buy.
    blocked = set(held_syms) | reentry_syms | {x["symbol"] for x in do_now}
    seen_new: set[str] = set()
    nf_pool = list(opportunities.get("not_former") or []) + list(opportunities.get("top") or [])
    for o in nf_pool:
        if not isinstance(o, dict):
            continue
        sym = str(o.get("symbol") or "").upper()
        vs = str(o.get("vs_re") or o.get("vs_former_holdings") or "")
        if vs != "not_former" or not _is_new_name_source(o.get("source")):
            continue
        if not sym or sym in blocked or sym in seen_new:
            continue
        seen_new.add(sym)
        th = o.get("thesis") if isinstance(o.get("thesis"), dict) else {}
        if not th.get("has_current_symbol_thesis"):
            try:
                th = thesis_fields_for_symbol(sym, root=root)
            except Exception as exc:
                th = {
                    "has_current_symbol_thesis": False,
                    "thesis_state": "INSUFFICIENT_DATA",
                    "thesis_unavailable_reason": type(exc).__name__,
                }
        has_th = bool(th.get("has_current_symbol_thesis") and (th.get("thesis_summary") or th.get("why_owned_or_watched")))
        new_if.append({
            "symbol": sym,
            "action": _new_if_action(o),
            "why": o.get("why_outranks_cash_or_reentry") or o.get("label") or "queue candidate",
            "source": o.get("source"),
            "vs_re": "not_former",
            "vs_former_holdings": "not_former",
            "verdict": o.get("verdict"),
            "thesis_state": th.get("thesis_state") or o.get("thesis_state"),
            "thesis_status": (th.get("thesis_state") if has_th else "UNAVAILABLE"),
            "thesis_status_reason": None if has_th else (
                th.get("thesis_unavailable_reason") or th.get("thesis_reason")
                or th.get("thesis_state") or "no living symbol thesis"
            ),
            "why_owned_or_watched": th.get("why_owned_or_watched") if has_th else None,
            "has_current_symbol_thesis": bool(th.get("has_current_symbol_thesis")),
            "actionability": o.get("actionability"),
            "class": "D",
        })
        try:
            from scripts.lib.cio_subject_guid import stamp_row
            new_if[-1] = stamp_row(new_if[-1], root=root)
        except Exception:
            new_if[-1].setdefault("subject_guid", None)
            new_if[-1].setdefault("identity_status", "UNRESOLVED")
        if len(new_if) >= NEW_NAME_CAP:
            break
    new_if_reason = None
    if not new_if:
        new_if_reason = (
            "no not_former defense/advisory names in queue after held+reentry dedup"
        )
    # de-dupe research by symbol
    seen_r = set()
    research_dedup = []
    for r in research:
        if r["symbol"] in seen_r:
            continue
        seen_r.add(r["symbol"])
        research_dedup.append(r)
    return {
        "DO_NOW": do_now,
        "WATCH_CLOSELY": watch,
        "RE_ENTER_IF": re_if,
        "NEW_POSITION_IF": new_if[:NEW_NAME_CAP],
        "NEW_POSITION_IF_REASON": new_if_reason,
        "HOLD_CASH_FOR": cash_for,
        "AVOID": avoid,
        "CURRENT_HOLDINGS_THESIS": held_thesis[:40],
        "CURRENT_HOLDINGS_IDENTITY_CARRIAGE": holdings_carriage,
        "RESEARCH_NEXT": research_dedup[:12],
        "authority": AUTHORITY,
        "financial_action": False,
    }


def build_product(
    *,
    root: Path | str | None = None,
    env: Optional[dict[str, str]] = None,
    now: Optional[datetime] = None,
    queue: Optional[dict[str, Any]] = None,
    previously_traded: Optional[list[dict[str, Any]]] = None,
    holdings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    infl = _influence_active(env)
    queue = queue if queue is not None else collect_queue(root)
    prev = previously_traded if previously_traded is not None else collect_previously_traded()
    holdings = holdings if holdings is not None else collect_holdings(root)
    lessons = collect_lessons(root)
    fs_rows = collect_fs(root)
    mem = collect_memory(root)
    regime = collect_regime()
    root_path = Path(root) if root is not None else resolve_root()
    try:
        from scripts.lib.symbol_thesis_attach import clear_cache, universe_metrics
        clear_cache()
        thesis_metrics = universe_metrics(root=root_path)
    except Exception:
        thesis_metrics = {"error": "thesis_metrics_unavailable"}
    try:
        from scripts.lib.symbol_thesis_review import daily_thesis_changes
        thesis_changes_today = daily_thesis_changes(root=root_path)
    except Exception:
        thesis_changes_today = {"error": "daily_thesis_changes_unavailable"}

    temperament = build_temperament(regime=regime, holdings=holdings, fs_rows=fs_rows, lessons=lessons, infl=infl)
    reentry = build_reentry_book(prev, queue, lessons, fs_rows, infl, root=root_path)
    opportunities = build_opportunity_book(queue, reentry, root=root_path)
    actions = build_action_book(reentry, opportunities, temperament, holdings=holdings, root=root_path)
    watch_syms = [
        str(it.get("symbol") or "").upper()
        for it in (queue.get("items") or queue.get("top") or [])
        if isinstance(it, dict) and it.get("symbol")
    ]
    earnings = collect_earnings_events(
        root=root_path, holdings=holdings, watch_symbols=watch_syms, now=now,
    )
    case_summaries = collect_case_summaries(root=root_path)
    watch_block_summary = collect_watch_block_summary(root=root_path)
    verdicts = [r for r in reentry.get("names") or [] if r.get("governed_verdict")]
    merged = apply_governed_verdicts(queue, verdicts)
    recs = _recommendations(actions, temperament, holdings=holdings)
    product = {
        "schema": SCHEMA,
        "as_of": _iso(now),
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": infl["memory_behavior_influence"],
        "temperament": temperament,
        "reentry_book": reentry,
        "opportunity_book": opportunities,
        "action_book": actions,
        "earnings": earnings["items"],
        "earnings_quality": {
            "quality": earnings.get("quality"),
            "reason": earnings.get("reason"),
            "as_of": earnings.get("as_of"),
            "source": earnings.get("source"),
            "class": "D",
        },
        "case_summaries": case_summaries,
        "research_cases": case_summaries,
        "watch_block_summary": watch_block_summary,
        "holdings_thesis_coverage": collect_holdings_thesis_coverage(
            holdings=holdings, root=root_path,
        ),
        "surface_a_status": collect_surface_a_status(
            holdings=holdings, previously_traded=prev,
        ),
        "thesis_universe": thesis_metrics,
        "thesis_changes_today": thesis_changes_today,
        "governed_verdicts": verdicts,
        "merged_queue": merged,
        "memory": {"provider": (mem.get("health") or {}).get("provider"), "counts": mem.get("counts")},
        "recommendations": recs,
        "summary": _summary(temperament, reentry, actions, prev),
        "summary_class": "T",
        "nothing_requires_action_class": "D",
        "decision_id": "cio_books_" + _iso(now).replace(":", "").replace("-", "")[:15],
        "final_position": "HOLD",
        "requires_operator_review": True,
        "confidence": 0.55 if verdicts or (queue.get("count") or 0) else 0.35,
    }
    # Wave 2 slice 19: Hermes failure histogram, last 7d, classified. Read-only,
    # mtime-cached, fail-soft — a ledger problem must not blank the product.
    try:
        from scripts.lib.cio_research_fail_policy import load_fail_histogram
        product["research_fail_histogram"] = load_fail_histogram(root=root_path)
    except Exception as exc:
        product["research_fail_histogram"] = {
            "schema": "CIOResearchFailHistogram@v1",
            "authority": AUTHORITY,
            "source_available": False,
            "reason": type(exc).__name__,
            "by_class": {},
            "class": "D",
        }
    # Wave 2 slice 32: how much of the research->checkpoint chain is joinable.
    # Reports a reason, not a fake percentage, when the two ends do not join.
    try:
        from scripts.lib.cio_plan_outcome_checkpoints import checkpoint_lineage_health
        product["checkpoint_lineage"] = checkpoint_lineage_health(
            root=root_path, holdings=holdings,
        )
    except Exception as exc:
        product["checkpoint_lineage"] = {
            "schema": "CheckpointLineageHealth@v1", "authority": AUTHORITY,
            "rate_state": "UNCOMPUTABLE", "rate_reason": type(exc).__name__,
            "checkpoints_total": 0, "class": "D",
        }
    # Wave 2 slices 39/40: holdings freshness + the two-writer cash check.
    # Detect only — never merges or reconciles the disagreeing totals.
    try:
        from scripts.lib.holdings_universe import holdings_data_quality
        product["holdings_data_quality"] = holdings_data_quality(root=root_path)
    except Exception as exc:
        product["holdings_data_quality"] = {
            "schema": "HoldingsDataQuality@v1", "authority": AUTHORITY,
            "state": "DATA_UNAVAILABLE", "reason": type(exc).__name__,
            "labels": ["DATA_UNAVAILABLE"], "class": "D",
        }
    # Wave 2 slice 25: VALID / PARTIAL / FAIL-family counts, with the attach
    # rule stated on the payload so it cannot be tightened silently (slice 26).
    try:
        from scripts.lib.cio_research_fail_policy import load_verdict_counts
        product["research_quality_counts"] = load_verdict_counts(root=root_path)
    except Exception as exc:
        product["research_quality_counts"] = {
            "schema": "CIOResearchVerdictCounts@v1", "authority": AUTHORITY,
            "source_available": False, "reason": type(exc).__name__,
            "by_verdict": {}, "attach_rule": "VALID|PARTIAL", "class": "D",
        }
    # Wave 2 slice 28: top PROVISIONAL lessons. Support-only, capped, and every
    # row must carry cannot_become_policy — a lesson is context, never policy.
    try:
        from scripts.lib.outcome_to_lesson import candidates_from_case_summaries
        cands = candidates_from_case_summaries(mem.get("sample") or [])
        if not cands:
            from scripts.lib.agent_durable_memory import get_durable_provider
            provider = get_durable_provider(root_path)
            cands = candidates_from_case_summaries(list(provider._store.values()))
        product["provisional_lessons"] = {
            "schema": "CIOProvisionalLessons@v1",
            "authority": AUTHORITY,
            "memory_behavior_influence": 0,
            "financial_action": False,
            "total_n": len(cands),
            "review_ready_n": sum(
                1 for c in cands if c.get("promotion_stage") == "REVIEW_READY"
            ),
            "policy_n": 0,
            "cap": PROVISIONAL_LESSON_CAP,
            "items": [
                {
                    "scope": c.get("scope"),
                    "statement": c.get("statement"),
                    "status": c.get("status"),
                    "promotion_stage": c.get("promotion_stage"),
                    "cannot_become_policy": c.get("cannot_become_policy"),
                    "policy_effect": c.get("policy_effect"),
                    "role": c.get("role"),
                    "plan_id": c.get("plan_id"),
                    "class": "D",
                }
                for c in cands[:PROVISIONAL_LESSON_CAP]
            ],
            "class": "D",
            "note": (
                "PROVISIONAL / REVIEW_READY only. cannot_become_policy is true on "
                "every row; the promotion ceiling is REVIEW_READY and no path "
                "here reaches policy."
            ),
        }
    except Exception as exc:
        product["provisional_lessons"] = {
            "schema": "CIOProvisionalLessons@v1", "authority": AUTHORITY,
            "available": False, "reason": type(exc).__name__,
            "items": [], "total_n": 0, "policy_n": 0, "class": "D",
        }
    # Wave 2 slice 13: measure identity coverage on the surfaces just built.
    # Lookup only — never mints, and fail-soft so a registry problem cannot
    # blank the product.
    try:
        from scripts.lib.cio_identity_coverage import measure_identity_coverage
        product["identity_coverage"] = measure_identity_coverage(
            product=product, root=root_path,
        )
    except Exception as exc:
        product["identity_coverage"] = {
            "schema": "CIOIdentityCoverage@v1",
            "authority": AUTHORITY,
            "available": False,
            "reason": type(exc).__name__,
            "minted": 0,
            "class": "D",
        }
    stamp_advisory_origin(product, producer="cio_investment_product.build_product")
    return product


def overlay_step2_surfaces(
    product: dict[str, Any],
    *,
    root: Path | str | None = None,
    now: Optional[datetime] = None,
    holdings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Refresh 2B/2C surfaces onto a persisted brief. No persist. No DO_NOW mutation.

    Cheap file/memory overlay so Command Center sees earnings, cash, and
    CASE_SUMMARY without waiting for the next worker persist. Does not recompute
    reentry adjudication.
    """
    if not isinstance(product, dict):
        return product
    p = dict(product)
    root_path = Path(root) if root is not None else resolve_root()
    holdings = holdings if holdings is not None else collect_holdings(root_path)
    watch_syms: list[str] = []
    for o in ((p.get("opportunity_book") or {}).get("top") or []):
        if isinstance(o, dict) and o.get("symbol"):
            watch_syms.append(str(o["symbol"]).upper())
    earnings = collect_earnings_events(
        root=root_path, holdings=holdings, watch_symbols=watch_syms, now=now,
    )
    p["earnings"] = earnings["items"]
    p["earnings_quality"] = {
        "quality": earnings.get("quality"),
        "reason": earnings.get("reason"),
        "as_of": earnings.get("as_of"),
        "source": earnings.get("source"),
        "class": "D",
    }
    cases = collect_case_summaries(root=root_path)
    p["case_summaries"] = cases
    p["research_cases"] = cases
    p["holdings_thesis_coverage"] = collect_holdings_thesis_coverage(
        holdings=holdings, root=root_path,
    )
    p["surface_a_status"] = collect_surface_a_status(holdings=holdings)
    temp = dict(p.get("temperament") or {})
    metrics = extract_cash_metrics(holdings)
    if metrics.get("total_cash") is not None or metrics.get("cash_pct") is not None:
        temp["cash"] = metrics.get("total_cash") if metrics.get("total_cash") is not None else metrics.get("cash_pct")
        temp["cash_pct"] = metrics.get("cash_pct")
        temp["cash_band"] = metrics.get("band")
        temp["cash_quality"] = metrics.get("quality")
        temp["cash_class"] = "D"
    p["temperament"] = temp
    ab = dict(p.get("action_book") or {})
    ab["HOLD_CASH_FOR"] = [cash_hold_row(metrics)]
    p["action_book"] = ab
    return p


def _recommendations(
    actions: dict[str, Any],
    temperament: dict[str, Any],
    holdings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    recs = [{
        "action": "NO_ACTION",
        "action_type": "ADVISORY",
        "title": f"Market temperament — {temperament.get('title')}",
        "description": temperament.get("portfolio_implication"),
        "domain": "CIO",
        "priority": "NORMAL",
        "recommended_action": "HOLD_POSTURE",
        "rationale": temperament.get("narrative"),
        "evidence_refs": ["temperament"],
    }]
    for bucket, key in (
        ("DO_NOW", "do_now"),
        ("WATCH_CLOSELY", "watch"),
        ("RE_ENTER_IF", "reenter_if"),
        ("AVOID", "avoid"),
    ):
        for row in (actions.get(bucket) or [])[:8]:
            recs.append({
                "action": "NO_ACTION",
                "action_type": "ADVISORY",
                "title": f"{row.get('action')} {row.get('symbol')}",
                "description": row.get("why"),
                "domain": "CIO",
                "priority": "HIGH" if bucket == "DO_NOW" else "NORMAL",
                "recommended_action": row.get("action"),
                "rationale": row.get("why"),
                "evidence_refs": [f"book:{key}:{row.get('symbol')}"],
                "symbol": row.get("symbol"),
            })
    from scripts.lib.cio_advisory_admissibility import gate_recommendation_rows
    return gate_recommendation_rows(recs, holdings=holdings)


def _nearest_reentries(reentry: dict[str, Any], limit: int = 3) -> list[str]:
    """The candidates closest to their trigger, named, with the distance.

    `pct_above_exit` is signed against the last exit: -9.1 means 9.1% below the
    price it was sold at. Rank by absolute distance so the ones nearest to
    acting come first, regardless of side.
    """
    rows = []
    for r in (reentry.get("names") or []):
        if r.get("status") != "NEAR":
            continue
        pct = r.get("pct_above_exit")
        sym = r.get("symbol")
        if sym is None or not isinstance(pct, (int, float)):
            continue
        rows.append((abs(pct), sym, pct))
    rows.sort()
    return [f"{sym} {pct:+.1f}% vs exit" for _, sym, pct in rows[:limit]]


def _do_now_lines(actions: dict[str, Any], limit: int = 4) -> list[str]:
    out = []
    for row in (actions.get("DO_NOW") or [])[:limit]:
        sym, act = row.get("symbol"), row.get("action")
        why = (row.get("why") or "").strip().rstrip(".")
        out.append(f"{act} {sym} — {why}" if why else f"{act} {sym}")
    return out


def _changed_since(reentry: dict[str, Any], prev: dict[str, Any] | None) -> str | None:
    """What moved since the previous brief, or None if this is the first."""
    if not isinstance(prev, dict):
        return None
    pb = prev.get("reentry_book") or {}
    if not pb:
        return None
    now_c, was_c = (reentry.get("counts") or {}), (pb.get("counts") or {})
    moves = [f"{k} {was_c.get(k, 0)}→{now_c.get(k, 0)}"
             for k in ("REENTER", "NEAR", "WAIT", "AVOID")
             if now_c.get(k, 0) != was_c.get(k, 0)]
    now_near = {r.get("symbol") for r in (reentry.get("names") or [])
                if r.get("status") == "NEAR"}
    was_near = {r.get("symbol") for r in (pb.get("names") or [])
                if r.get("status") == "NEAR"}
    entered = sorted(x for x in (now_near - was_near) if x)
    if entered:
        moves.append("newly NEAR: " + ", ".join(entered[:4]))
    if not moves:
        return "No change since the last brief."
    return "Changed: " + "; ".join(moves) + "."


def _summary(
    temperament: dict[str, Any],
    reentry: dict[str, Any],
    actions: dict[str, Any],
    prev: dict[str, Any] | None = None,
) -> str:
    """The operator-facing line. Symbols, distances, and what moved.

    The previous version stated four counts and then this sentence verbatim:
    "No material financial Telegram unless a candidate-specific governed act-now
    exists." That is the delivery policy talking to itself -- it tells the
    operator nothing about their portfolio, and it shipped to their phone. A
    brief naming no security is not a brief.
    """
    counts = reentry.get("counts") or {}
    parts: list[str] = [f"{temperament.get('title')}."]

    do_now = _do_now_lines(actions)
    if do_now:
        parts.append("DO NOW: " + " · ".join(do_now) + ".")
    else:
        from scripts.lib.cio_p90_voice import stamp_nothing_requires_action
        parts.append(stamp_nothing_requires_action())

    near = _nearest_reentries(reentry)
    if near:
        parts.append("Closest re-entries: " + ", ".join(near) + ".")
    if counts.get("REENTER"):
        syms = [r.get("symbol") for r in (reentry.get("names") or [])
                if r.get("status") == "REENTER"][:4]
        parts.append("Triggered: " + ", ".join(s for s in syms if s) + ".")

    parts.append(
        f"Tracking {reentry.get('count') or 0} former names "
        f"({counts.get('NEAR', 0)} near, {counts.get('WAIT', 0)} waiting, "
        f"{counts.get('AVOID', 0)} avoid); "
        f"{len(actions.get('WATCH_CLOSELY') or [])} on close watch."
    )

    changed = _changed_since(reentry, prev)
    if changed:
        parts.append(changed)

    parts.append("Advisory only — no orders placed.")
    return " ".join(parts)

def persist_product(product: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    from scripts.lib.autonomy_watchdog.io import append_jsonl, atomic_write_json
    p = paths(root)
    pid = str(product.get("product_id") or product.get("decision_id") or "")
    if not pid.startswith("prod_"):
        # classify_advisory_record treats prod_* CIOInvestmentProduct as
        # LEGACY_PROVEN. cio_books_* without origin stamps as LEGACY_UNPROVEN
        # and blanks Command Center current product.
        suffix = pid or ("cio_books_" + _iso().replace(":", "").replace("-", "")[:15])
        product["product_id"] = "prod_" + suffix
    stamp_advisory_origin(product, producer="cio_investment_product.persist_product")
    slim = {k: product[k] for k in product if k != "merged_queue"}
    atomic_write_json(p["brief"], slim)
    append_jsonl(p["briefs"], {
        "as_of": product.get("as_of"),
        "product_id": product.get("product_id"),
        "previous_product_id": product.get("previous_product_id"),
        "trigger": product.get("trigger"),
        "summary": product.get("summary"),
        "verdict_count": len(product.get("governed_verdicts") or []),
        "reentry_count": (product.get("reentry_book") or {}).get("count"),
        "what_changed_material": ((product.get("what_changed") or {}).get("material")
                                 if isinstance(product.get("what_changed"), dict) else None),
    })
    atomic_write_json(p["verdicts"], {
        "as_of": product.get("as_of"),
        "verdicts": product.get("governed_verdicts") or [],
        "authority": AUTHORITY,
    })
    append_jsonl(p["verdicts_log"], {
        "as_of": product.get("as_of"),
        "verdicts": [
            {"symbol": v.get("symbol"), "verdict": v.get("governed_verdict"), "status": v.get("status")}
            for v in (product.get("governed_verdicts") or [])
        ],
    })
    return product


def load_brief(root: Path | str | None = None) -> dict[str, Any]:
    return _read_json(paths(root)["brief"])


def load_current_production_product(root: Path | str | None = None) -> dict[str, Any]:
    """Canonical current CIO product: eligible PROD only. Fail closed."""
    brief = load_brief(root)
    chosen = select_current_production_product([brief] if brief else [])
    if chosen:
        return chosen
    if brief:
        return unavailable_current_product(
            reason=classify_advisory_record(brief)["reason"],
            last=brief,
        )
    return unavailable_current_product(reason="no_current_product")


def load_verdicts(root: Path | str | None = None) -> list[dict[str, Any]]:
    return list((_read_json(paths(root)["verdicts"]).get("verdicts") or []))


def merge_queue_with_stored_verdicts(queue: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    return apply_governed_verdicts(queue, load_verdicts(root))


def build_investment_product_synthesis_fn(
    *,
    root: Path | str | None = None,
    env: Optional[dict[str, str]] = None,
) -> Callable[..., dict[str, Any]]:
    def fn(run: dict[str, Any], snapshot: dict[str, Any], specialist_result: dict[str, Any], hermes_result: dict[str, Any]) -> dict[str, Any]:
        product = persist_product(build_product(root=root, env=env))
        product["run_id"] = (run or {}).get("run_id")
        product["snapshot_ref"] = (snapshot or {}).get("snapshot_id")
        product["specialist_count"] = len((specialist_result or {}).get("artifacts") or [])
        product["hermes_present"] = bool(hermes_result)
        product["opportunity_queue"] = {
            "top": ((run or {}).get("context") or {}).get("top") or (product.get("opportunity_book") or {}).get("top"),
            "opportunity_count": ((run or {}).get("context") or {}).get("opportunity_count"),
        }
        return product
    return fn
