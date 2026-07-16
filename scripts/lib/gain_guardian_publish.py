"""Gain Guardian publication surfaces (F4) — RI rows, charts, Telegram digest.

DARK by default: holdings_gain_guardian.py only calls publish_run() when the
operator has flipped config published=true via --promote (after the 10-day
shadow window). Chart rendering and digest text are pure functions so the
--test-render path can exercise them with ZERO writes.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

CHART_DIR = ROOT / "data" / "runtime" / "exit_charts"


def render_chart(symbol: str, bars: list[dict], *, hwm: float | None = None,
                 basis: float | None = None) -> str | None:
    """6-month daily candlestick via mplfinance (zero-cost, no CHART-IMG API):
    SMA50/200, volume, HWM + basis lines. Returns PNG path or None."""
    try:
        import pandas as pd
        import mplfinance as mpf
    except Exception:
        return None
    rows = []
    for b in bars[-126:]:
        ts = b.get("datetime") or b.get("t") or b.get("date")
        try:
            when = pd.to_datetime(ts, unit="ms") if isinstance(ts, (int, float)) else pd.to_datetime(ts)
        except Exception:
            continue
        rows.append({
            "Date": when,
            "Open": float(b.get("open") or 0), "High": float(b.get("high") or 0),
            "Low": float(b.get("low") or 0), "Close": float(b.get("close") or 0),
            "Volume": float(b.get("volume") or 0),
        })
    if len(rows) < 30:
        return None
    df = pd.DataFrame(rows).set_index("Date")
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    out = CHART_DIR / f"{symbol}_{dt.date.today().isoformat()}.png"
    hlines = [x for x in (hwm, basis) if x]
    kw: dict[str, Any] = dict(
        type="candle", volume=True, mav=(50, 200), style="nightclouds",
        title=f"{symbol} — Gain Guardian exit intel {dt.date.today().isoformat()}",
        savefig=dict(fname=str(out), dpi=110, bbox_inches="tight"),
    )
    if hlines:
        kw["hlines"] = dict(hlines=hlines, colors=["#f59e0b", "#64748b"][:len(hlines)],
                            linestyle="--", linewidths=1)
    try:
        mpf.plot(df, **kw)
        return str(out.relative_to(ROOT))
    except Exception:
        return None


def digest_text(fired: list[dict[str, Any]]) -> str:
    """One Telegram digest per run (never per-symbol) — urgent first, 8 lines max."""
    ordered = sorted(fired, key=lambda r: (0 if r.get("severity") == "urgent" else
                                           1 if r.get("severity") == "high" else 2,
                                           -(r.get("parabolic_score") or 0)))
    lines = [f"🛡 Gain Guardian — {len(fired)} exit advisory(ies) [advisory-only, no orders]"]
    for r in ordered[:8]:
        gb = f" gb={r.get('giveback_frac')}" if r.get("giveback_frac") is not None else ""
        lines.append(
            f"  {'‼️ ' if r.get('severity') == 'urgent' else ''}{r['symbol']} "
            f"[{r.get('extension_state')}{('/' + r['giveback_state']) if r.get('giveback_state') else ''}] "
            f"score={r.get('parabolic_score')} gain={r.get('open_gain_pct')}%{gb} → {r.get('advisory')}"
        )
    if len(ordered) > 8:
        lines.append(f"  … +{len(ordered) - 8} more in holding_exit_metrics")
    return "\n".join(lines)


def _stage_prefill(r: dict[str, Any], tax: dict[str, Any] | None) -> dict[str, Any]:
    """F6: prefill for stage_idea() — operator-clicked only, source gain_guardian.
    Carries the exit note so RI v3's stop-note stage gate passes."""
    return {
        "symbol": r["symbol"],
        "side": "trim",
        "role": "trim_candidate",
        "action": "trim",
        "suggested_trim_fraction": r.get("suggested_trim_fraction"),
        "provisional_stop_note": (
            f"Gain Guardian {r.get('extension_state')}"
            + (f"/{r.get('giveback_state')}" if r.get("giveback_state") else "")
            + f" — HWM ${r.get('hwm_price')}, giveback {r.get('giveback_frac')}; "
              "protect remaining shares via Stop Management (Replace mode)."
        ),
        "funding_source": "; ".join((tax or {}).get("lines") or [])[:400] or None,
        "source": "gain_guardian",
        "source_title": f"Exit intelligence: {r['symbol']} {r.get('advisory')}",
    }


def publish_run(*, results: list[dict[str, Any]], cfg: dict, db_execute) -> dict[str, Any]:
    """Publish fired advisories: RI rows + charts + ONE Telegram digest + dedup.
    Only reachable when config published=true (operator --promote)."""
    fired = [r for r in results if r.get("advisory")]
    if not fired:
        return {"published": 0, "note": "no advisories fired"}

    try:
        from lib.gain_guardian_tax import annotate_trim
    except Exception:
        annotate_trim = None

    published, today = 0, dt.date.today().isoformat()
    for r in fired:
        # Dedup: one exit_intelligence row per symbol per day
        dup = db_execute(
            """SELECT 1 FROM hermes_research_intelligence
               WHERE research_type='exit_intelligence' AND upper(symbol)=%s
                 AND created_at::date = CURRENT_DATE LIMIT 1""",
            (r["symbol"],), fetch="one",
        )
        if dup:
            continue
        tax = None
        if annotate_trim and "TRIM" in (r.get("advisory") or "") and r.get("basis_ps"):
            try:
                tax = annotate_trim(symbol=r["symbol"],
                                    trim_fraction=float(r.get("suggested_trim_fraction") or 0.25),
                                    price=float(r.get("price") or 0),
                                    basis_ps=float(r.get("basis_ps") or 0),
                                    db_execute=db_execute)
            except Exception:
                tax = None
        chart_path = None
        try:
            from holdings_gain_guardian import _bars_with_volume
            chart_path = render_chart(r["symbol"], _bars_with_volume(r["symbol"], days=200),
                                      hwm=r.get("hwm_price"), basis=r.get("basis_ps"))
        except Exception:
            pass

        summary = (
            f"{r['symbol']} {r.get('extension_state')}"
            + (f"/{r.get('giveback_state')}" if r.get("giveback_state") else "")
            + f": parabolic {r.get('parabolic_score')}, ext50 {r.get('ext50_atr')} ATR, "
              f"RSI {r.get('rsi14')}, RVOL {r.get('rvol20')}, open gain {r.get('open_gain_pct')}%, "
              f"giveback {r.get('giveback_frac')} vs HWM ${r.get('hwm_price')}. "
              f"Advisory: {r.get('advisory')}"
            + (f" (trim {int(100 * (r.get('suggested_trim_fraction') or 0))}%)"
               if r.get("suggested_trim_fraction") else "")
            + ". " + " ".join((tax or {}).get("lines") or [])[:400]
            + " Advisory only — no order is created; stops via the monitored 2FA flow."
        )[:1500]
        evidence = {
            "metrics_row": {k: r.get(k) for k in (
                "price", "weight_pct", "ext50_atr", "ext200_atr", "rsi14", "rvol20", "up_streak",
                "gain_5d_pct", "gap_ups_5d", "slope_accel", "open_gain_pct", "giveback_frac",
                "parabolic_score", "extension_state", "giveback_state", "advisory", "severity",
                "hwm_price", "basis_ps", "basis_source", "seeded_from", "notes")},
            "tax_annotation": tax,
            "chart_path": chart_path,
            "stage_prefill": _stage_prefill(r, tax),
            "generator": "holdings_gain_guardian",
        }
        db_execute(
            """INSERT INTO hermes_research_intelligence
               (topic, summary, symbol, research_type, source, status, confidence_score,
                evidence_json, created_at, freshness_date)
               VALUES (%s,%s,%s,'exit_intelligence','gain_guardian','staged',%s,%s::jsonb,NOW(),NOW())""",
            (f"Exit intelligence: {r['symbol']} {r.get('advisory')} ({today})",
             summary, r["symbol"], min(0.95, (r.get("parabolic_score") or 0) / 100.0),
             json.dumps(evidence, default=str)),
            fetch="none",
        )
        published += 1

    sent = False
    if published:
        try:
            from telegram_alert import send_telegram
            from telegram_alert_dedupe import (dedupe_key, load_state, record_sent,
                                               save_state, should_suppress)
            state = load_state()
            key = dedupe_key(f"{today}:exit_intel", "gain_guardian")
            if not should_suppress(state, key, 720):  # one digest per half-day max
                sent = send_telegram(digest_text(fired))
                if sent:
                    record_sent(state, key)
                    save_state(state)
        except Exception:
            sent = False
    return {"published": published, "telegram_sent": sent}
