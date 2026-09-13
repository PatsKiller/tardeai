"""Option Chain — Data Broker read model over options_iv_history (store-only).

Registry domain ``options_iv`` (class live_external, writer
scripts/lib/strategy_research/iv_history.py, cadence unscheduled, stale after 4h,
no_coverage ``call_out_at_read_time``). The registry's own note: "No option_chain
projection exists yet — Phase 4 adds it." This is it.

DECLARED LIVE-EXTERNAL NOTE
    The chain itself lives at Schwab. This projection makes NO call to Schwab (or
    any provider). It reads what iv_history stored and states the age. A 4-hour
    window on an unscheduled writer means the envelope will usually say ``stale``;
    that is the honest answer, and the desk shows the age rather than a chain that
    looks live. Fetching a fresh chain is a governed command, not a read.

Zero provider calls. Read-only.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope, newest

DOMAIN = "options_iv"

LIVE_EXTERNAL_NOTE = (
    "options_iv is live_external at Schwab; this projection reads options_iv_history only "
    "and never calls the provider. Freshness is the envelope's age, not a live quote."
)

LATEST_SQL = """SELECT symbol, iv_pct, atm_strike, underlying, source, captured_at, snapshot_date, meta_json
                FROM options_iv_history WHERE upper(symbol)=%s
                ORDER BY captured_at DESC LIMIT %s"""


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def get_option_chain(db_query, symbol: str, *, history: int = 30, now=None, registry=None) -> dict[str, Any]:
    """{ok, symbol, latest: {iv_pct, atm_strike, underlying, source, captured_at}|None,
        history: [...], live_external: {...}, <envelope>}."""
    sym = str(symbol or "").upper().strip()
    rows: list[dict[str, Any]] = []
    error = None
    if sym:
        try:
            rows = db_query(LATEST_SQL, (sym, max(1, min(int(history), 500))), fetch="all") or []
        except Exception as e:  # noqa: BLE001
            error = str(e)[:200]
    hist = []
    for r in rows:
        cap = r.get("captured_at")
        sd = r.get("snapshot_date")
        hist.append({
            "iv_pct": _f(r.get("iv_pct")),
            "atm_strike": _f(r.get("atm_strike")),
            "underlying": _f(r.get("underlying")),
            "source": r.get("source"),
            "captured_at": cap.isoformat() if hasattr(cap, "isoformat") else cap,
            "snapshot_date": sd.isoformat() if hasattr(sd, "isoformat") else sd,
        })
    latest = hist[0] if hist else None
    env = envelope(DOMAIN, newest([r.get("captured_at") for r in rows]), now=now, registry=registry,
                   source={"table": "options_iv_history"})
    out = {
        "ok": error is None,
        "symbol": sym,
        "latest": latest,
        "history": hist,
        "n": len(hist),
        "live_external": {"provider": "schwab", "called": False, "note": LIVE_EXTERNAL_NOTE},
        "provider_calls": 0,
    }
    if error:
        out["error"] = error
    out.update(env)
    return out
