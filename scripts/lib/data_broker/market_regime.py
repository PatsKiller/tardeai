"""Market Regime — Data Broker read model over market_regime_snapshots.

Registry domain ``market_regime`` (writer scripts/market_regime_classifier.py,
06:35 · 16:05 Mon-Fri, stale after 26h, no_coverage
``carry_last_regime_with_date_never_neutral``). This is the ONLY read path for the
table from a hub handler; before Phase 4 scripts/api_v2.py selected from it in five
places, each with its own idea of "latest" and none carrying an age.

The registry names ``risk_snapshot`` as the market_regime projection today;
``risk_snapshot`` composes book risk from JSON state and does not read this
table, so this module is the table read and risk_snapshot may compose it.
The registry patch (docs/implementation/sot/phase4_registry_patch.json) moves the
domain's projection pointer here.

Zero provider calls. Read-only.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope, newest

DOMAIN = "market_regime"

LATEST_SQL = """SELECT snapshot_id, regime_label, regime_score, confidence, stale_data,
                       volatility_state, trend_state, breadth_state, liquidity_state,
                       leadership_state, risk_appetite_state, macro_state,
                       data_freshness_state, market_session, summary, generated_at, created_at
                FROM market_regime_snapshots
                ORDER BY created_at DESC LIMIT %s"""


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        elif v is not None and type(v).__name__ == "Decimal":
            v = float(v)
        out[k] = v
    return out


def get_market_regime(db_query, *, history: int = 10, now=None, registry=None) -> dict[str, Any]:
    """Latest regime snapshot + short history, wrapped in the read envelope.

    Returns {ok, regime: {...}|None, history: [...], regime_line, risk_off, <envelope>}.
    ``regime`` is the newest row. ``regime_line`` is the one-line label the desks
    render ("risk_off down 72%"). ``risk_off`` is the deterministic boolean the
    Defense desk keys on. Never returns "neutral" for a missing row — the registry's
    no_coverage rule is carry-last-with-date; with no row at all the answer is None
    and the envelope says no_coverage.
    """
    rows: list[dict[str, Any]] = []
    error = None
    try:
        rows = [_clean(r) for r in (db_query(LATEST_SQL, (max(1, int(history)),)) or [])]
    except Exception as e:  # noqa: BLE001 — fail soft, the envelope reports no_coverage
        error = str(e)[:200]
    latest = rows[0] if rows else None
    as_of = latest.get("generated_at") or latest.get("created_at") if latest else None
    env = envelope(DOMAIN, as_of, now=now, registry=registry)
    line = regime_line(latest)
    out: dict[str, Any] = {
        "ok": error is None,
        "regime": latest,
        "history": rows,
        "regime_line": line,
        "risk_off": any(w in (line or "").lower() for w in ("off", "bear", "defensive")),
        "provider_calls": 0,
    }
    if error:
        out["error"] = error
    out.update(env)
    return out


def regime_line(row: dict[str, Any] | None) -> str | None:
    """'risk_off down 72%' — the label string desks already render; None when no row."""
    if not row:
        return None
    label = str(row.get("regime_label") or "unknown").replace("_", " ")
    trend = str(row.get("trend_state") or "").strip()
    conf = row.get("confidence")
    line = label + (f" {trend}" if trend else "")
    if conf is not None:
        try:
            line += f" {int(float(conf) * 100)}%"
        except (TypeError, ValueError):
            pass
    return line


def history_as_of(rows: list[dict[str, Any]]) -> str | None:
    return newest([r.get("generated_at") or r.get("created_at") for r in rows])
