#!/usr/bin/env python3
"""journal_ai_critique.py — Automated post-trade AI critique (TradeZella-style) for TradeInView.

Builds deterministic metrics from journal tags + replay bar data + execution quality, then layers
Grok coaching narrative. Persisted in journal_trade_reviews.payload.ai_critique.

  python scripts/journal_ai_critique.py --trade-key GOVX:schwab_rollover_ira:2026-05-18 --apply
  python scripts/journal_ai_critique.py --limit 20 --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import journal_trade_in_view as tiv
import ohlc_charts

PROMPT_VERSION = "ai_critique_v2"
_HISTORY_MAX = 10


def _classify_trade(review: dict, trade: dict, hold_min: int | None) -> dict:
    fam = (review.get("setup_family") or trade.get("strategy_id") or "").lower()
    tags = review.get("setup_types") or []
    tag_s = " ".join(str(t) for t in tags).lower()
    if "scalp" in fam or "scalp" in tag_s or (hold_min is not None and hold_min < 30):
        ttype = "scalp"
    elif "swing" in fam or "swing" in tag_s or (trade.get("hold_days") or 0) > 1:
        ttype = "swing"
    elif "option" in tag_s or "spread" in tag_s:
        ttype = "options"
    elif (trade.get("hold_days") or 0) >= 5:
        ttype = "position"
    else:
        ttype = "day_trade"
    return {
        "type": ttype,
        "setup_family": review.get("setup_family"),
        "setup_types": tags,
        "market_regime": review.get("market_regime"),
        "psychology": review.get("emotion_before"),
        "hold_minutes": hold_min,
    }


def _time_in_profit(bars: list, entry_price: float, exit_price: float, entry_t, exit_t) -> dict:
    """Minutes in profit vs underwater during the hold (1-min bars)."""
    if not bars or not entry_price:
        return {"minutes_in_profit": 0, "minutes_underwater": 0, "pct_in_profit": None}
    import datetime as dt
    bt = [dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00")) if isinstance(b.get("t"), str) else None for b in bars]
    # use chart output bars (already ET-keyed) — walk by index between entry/exit marker bars
    ep = float(entry_price)
    in_profit = underwater = 0
    for b in bars:
        c = float(b["close"])
        if c >= ep:
            in_profit += 1
        else:
            underwater += 1
    total = max(1, in_profit + underwater)
    return {
        "minutes_in_profit": in_profit,
        "minutes_underwater": underwater,
        "pct_in_profit": round(100 * in_profit / total, 1),
        "hold_bars": total,
    }


def _indicator_at(chart: dict, marker_time, field: str):
    rows = chart.get(field) or []
    if not rows or marker_time is None:
        return None
    near = min(rows, key=lambda x: abs((x.get("time") or 0) - marker_time))
    return near


def build_context(trade_key: str) -> dict | None:
    parts = trade_key.split(":")
    if len(parts) < 3:
        return None
    sym, acct, cd = parts[0], parts[1], parts[-1]
    trade = tiv._q("""
        SELECT symbol, account, open_date::text, close_date::text, shares, buy_price, sell_price,
               pnl, pnl_pct, hold_days, strategy_id, trade_type
        FROM trade_closed
        WHERE symbol=%s AND account=%s AND close_date=%s::date
        ORDER BY id DESC LIMIT 1
    """, [sym, acct, cd], fetch="one")
    if not trade:
        return None
    review = tiv._q("SELECT * FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one") or {}
    payload = tiv._review_payload(review)
    eq = tiv._q("""
        SELECT * FROM trade_execution_quality
        WHERE UPPER(symbol)=%s AND entry_time::date=%s::date
          AND ABS(entry_price - %s) < 0.08
        ORDER BY exit_time DESC LIMIT 1
    """, [sym, cd, float(trade.get("buy_price") or 0)], fetch="one") or {}

    ent_iso = (eq.get("entry_time") or "").isoformat() if eq.get("entry_time") else None
    ext_iso = (eq.get("exit_time") or "").isoformat() if eq.get("exit_time") else None
    chart = ohlc_charts.trade_chart(sym, trade["open_date"], trade["close_date"],
                                    trade.get("buy_price"), trade.get("sell_price"),
                                    ent_iso, ext_iso, trade_key)

    hold_min = None
    if eq.get("entry_time") and eq.get("exit_time"):
        hold_min = int((eq["exit_time"] - eq["entry_time"]).total_seconds() / 60)

    entry_marker = next((m for m in (chart.get("markers") or []) if m["type"] == "entry"), None)
    exit_marker = next((m for m in (chart.get("markers") or []) if m["type"] == "exit"), None)
    et = entry_marker["time"] if entry_marker else None
    xt = exit_marker["time"] if exit_marker else None

    hold_bars = []
    if et is not None and chart.get("bars"):
        started = False
        for b in chart["bars"]:
            if b["time"] == et:
                started = True
            if started:
                hold_bars.append(b)
            if xt is not None and b["time"] == xt:
                break

    tip = _time_in_profit(hold_bars, float(trade.get("buy_price") or 0),
                          float(trade.get("sell_price") or 0), et, xt)

    vwap_e = _indicator_at(chart, et, "vwap")
    rsi_e = _indicator_at(chart, et, "rsi")
    macd_e = _indicator_at(chart, et, "macd")

    return {
        "trade_key": trade_key,
        "trade": trade,
        "review": review,
        "payload": payload,
        "eq": eq,
        "chart_meta": {
            "bar_count": chart.get("bar_count"),
            "source": chart.get("source"),
            "timeframe": chart.get("timeframe"),
            "integrity": chart.get("integrity"),
        },
        "classification": _classify_trade(review, trade, hold_min),
        "time_in_trade": tip,
        "indicators_at_entry": {
            "vwap": (vwap_e or {}).get("value"),
            "rsi": (rsi_e or {}).get("value"),
            "macd": (macd_e or {}).get("macd") if macd_e else None,
            "macd_signal": (macd_e or {}).get("signal") if macd_e else None,
            "volume": next((v["value"] for v in (chart.get("volume") or []) if v.get("time") == et), None),
        },
        "planned_r": review.get("planned_r"),
        "realized_r": review.get("realized_r") or trade.get("r_multiple"),
        "mistake_tags": review.get("mistake_tags") or [],
        "strength_tags": review.get("strength_tags") or [],
        "replay_integrity": {
            "markers_resolved": bool(et is not None and xt is not None),
            "chart_integrity": chart.get("integrity"),
        },
    }


def _deterministic_sections(ctx: dict) -> dict:
    trade = ctx["trade"]
    eq = ctx["eq"]
    ep = float(trade.get("buy_price") or 0)
    xp = float(trade.get("sell_price") or 0)
    pnl = float(trade.get("pnl") or 0)
    shares = float(trade.get("shares") or 0)
    ind = ctx["indicators_at_entry"]
    tip = ctx["time_in_trade"]

    alt_exit = None
    if eq.get("post_exit_high"):
        alt_exit = {
            "price": eq.get("post_exit_high"),
            "additional_per_share": round(float(eq["post_exit_high"]) - xp, 4) if xp else None,
            "additional_pnl": round((float(eq["post_exit_high"]) - xp) * shares, 2) if xp and shares else None,
            "runner_type": eq.get("runner_type"),
        }

    return {
        "trade_classification": {
            **ctx["classification"],
            "setup_quality": {
                "volume_at_entry": ind.get("volume"),
                "entry_rvol": eq.get("entry_volume_ratio"),
                "above_vwap": eq.get("entry_above_vwap"),
                "vwap_distance_pct": eq.get("entry_vwap_distance_pct"),
                "rsi": ind.get("rsi") or eq.get("entry_rsi"),
                "macd_state": eq.get("entry_macd_state"),
            },
        },
        "execution_quality": {
            "entry_price": ep,
            "exit_price": xp,
            "entry_timing_grade": eq.get("entry_timing_grade"),
            "exit_timing_grade": eq.get("exit_timing_grade"),
            "outcome_grade": eq.get("outcome_grade"),
            "execution_grade": eq.get("execution_grade"),
            "capture_ratio": eq.get("capture_ratio"),
            "mfe": eq.get("mfe_after_entry"),
            "mae": eq.get("mae_after_entry"),
            "minutes_in_profit": tip.get("minutes_in_profit"),
            "minutes_underwater": tip.get("minutes_underwater"),
            "pct_in_profit": tip.get("pct_in_profit"),
            "flags": [k for k in ("no_volume_entry_flag", "premature_exit_flag", "early_entry_flag", "late_entry_flag")
                      if eq.get(k)],
        },
        "risk_sizing": {
            "shares": shares,
            "pnl": pnl,
            "planned_r": ctx.get("planned_r"),
            "realized_r": ctx.get("realized_r"),
            "position_value": round(ep * shares, 2) if ep and shares else None,
        },
        "opportunity_cost": {
            "mfe_after_exit_pct": eq.get("mfe_after_exit_pct"),
            "missed_opportunity_grade": eq.get("missed_opportunity_grade"),
            "post_exit_high": eq.get("post_exit_high"),
            "alternative_exit": alt_exit,
            "what_if_wait_volume": eq.get("entry_volume_confirmed") is False,
            "what_if_hold_to_mfe": {
                "price": round(ep + float(eq.get("mfe_after_entry") or 0), 4) if ep else None,
                "extra_per_share": eq.get("mfe_after_entry"),
            },
        },
    }


PROMPT = """You are a disciplined trading coach writing a post-trade critique for the operator's journal.
Use ONLY the structured facts below — do not invent prices, times, or indicators.

Trade: {symbol} ({trade_type}) | P&L ${pnl} | {shares} shares | hold {hold_min} min
Tags: setup={setup} | regime={regime} | psych={psych} | mistakes={mistakes} | strengths={strengths}
Execution: {outcome}/{execution} | capture {capture}% | MFE {mfe} MAE {mae}
Time in profit: {pct_profit}% ({min_profit} min green / {min_dd} min red)
Entry: RVOL {rvol} | above VWAP {vwap} ({vwap_dist}%) | RSI {rsi} | MACD {macd}
Opportunity: missed {missed}% post-exit | runner {runner}
Planned R {planned_r} → Realized R {realized_r}
Stop discipline: initial {init_stop_atr}×ATR | breakeven {be_secured} | exit-R vs planned-stop-R {r_vs_stop}

Also critique STOP DISCIPLINE per the momentum-scalp policy: (a) was the initial stop optimal vs the MAE
(too tight = stopped on noise; too loose = gave back too much)? (b) was breakeven moved at the right R? (c)
what R was left on the table or saved? (d) recommend stop params for THIS setup+regime. NOTE: protective
trailing is config-OFF — it backtested net-negative for momentum (truncates the fat tail); do NOT recommend
adding a trailing stop.

Return STRICT JSON only:
{{"summary": "2-3 sentence overview",
"strengths": ["...", "..."],
"improvements": ["...", "..."],
"takeaways": ["repeat this...", "fix this..."],
"stop_critique": {{"initial_stop_vs_mae": "...", "breakeven_timing": "...", "r_left_on_table": "...", "recommended_params_setup_regime": "..."}},
"suggested_tags": ["tag1", "tag2"],
"what_if_scenarios": [{{"scenario": "...", "outcome": "..."}}]}}"""


def _deterministic_narrative(ctx: dict, sections: dict) -> dict:
    """Useful critique when LLM is unavailable or returns empty."""
    trade = ctx["trade"]
    eq = ctx["eq"]
    review = ctx["review"]
    cls = sections.get("trade_classification") or {}
    ex = sections.get("execution_quality") or {}
    risk = sections.get("risk_sizing") or {}
    opp = sections.get("opportunity_cost") or {}
    tip = ctx.get("time_in_trade") or {}
    sym = trade.get("symbol", "?")
    pnl = float(trade.get("pnl") or 0)
    ep = ex.get("entry_price")
    xp = ex.get("exit_price")
    outcome = ex.get("outcome_grade") or "?"
    execution = ex.get("execution_grade") or "?"
    capture = ex.get("capture_ratio")
    cap_pct = f"{int((capture or 0) * 100)}%" if capture is not None else "—"
    setup = cls.get("setup_family") or review.get("setup_family") or "untagged"
    regime = cls.get("market_regime") or review.get("market_regime") or "unknown"
    mistakes = ctx.get("mistake_tags") or []
    strengths = ctx.get("strength_tags") or []

    summary = (
        f"{sym} {cls.get('type', 'day_trade')} ({setup}, {regime}): "
        f"${pnl:+.2f} P&L at {ep}→{xp}. Grades {outcome}/{execution}, capture {cap_pct}."
    )
    if tip.get("pct_in_profit") is not None:
        summary += (
            f" Held {tip.get('minutes_in_profit', 0)}m in profit vs "
            f"{tip.get('minutes_underwater', 0)}m underwater ({tip['pct_in_profit']}% green)."
        )

    str_list = []
    if pnl > 0:
        str_list.append(f"Closed green (${pnl:+.2f}) with {cap_pct} of available move captured.")
    if tip.get("pct_in_profit", 0) >= 50:
        str_list.append(f"Trade spent {tip['pct_in_profit']}% of hold time in profit.")
    if eq.get("entry_above_vwap"):
        str_list.append("Entry was above VWAP — aligned with intraday strength.")
    if strengths:
        str_list.append(f"Tagged strengths: {', '.join(strengths[:3])}.")
    if not str_list:
        str_list.append("Review execution flags and journal tags for repeatable lessons.")

    imp_list = []
    for flag, label in (
        ("no_volume_entry_flag", "Entry lacked volume confirmation — wait for RVOL spike."),
        ("premature_exit_flag", "Exit may have been early vs post-exit continuation."),
        ("early_entry_flag", "Entry was early relative to setup confirmation."),
        ("late_entry_flag", "Entry chased — consider limit orders at planned levels."),
    ):
        if eq.get(flag):
            imp_list.append(label)
    if mistakes:
        imp_list.append(f"Mistake tags to address: {', '.join(mistakes[:4])}.")
    if opp.get("mfe_after_exit_pct") and float(opp["mfe_after_exit_pct"] or 0) > 5:
        imp_list.append(
            f"Stock moved +{opp['mfe_after_exit_pct']}% after exit — review scale-out / runner rules."
        )
    if not imp_list:
        imp_list.append("Log planned stop/target and regime next time for sharper post-trade review.")

    takeaways = []
    if eq.get("grok_what_to_do_next_time"):
        takeaways.append(str(eq["grok_what_to_do_next_time"])[:200])
    takeaways.append(f"Repeat: {setup} only when regime is {regime} and RVOL confirms.")
    if risk.get("realized_r") is not None and risk.get("planned_r") is not None:
        takeaways.append(f"Risk: planned {risk['planned_r']}R → realized {risk['realized_r']}R.")
    takeaways.append("Screenshot the entry bar and tag psychology within 24h while memory is fresh.")

    what_ifs = []
    alt = opp.get("alternative_exit") or {}
    if alt.get("additional_pnl") and float(alt["additional_pnl"]) > 0:
        what_ifs.append({
            "scenario": f"Hold to post-exit high ${alt.get('price')}",
            "outcome": f"+${alt['additional_pnl']} additional ({alt.get('runner_type', 'continuation')})",
        })
    mfe = opp.get("what_if_hold_to_mfe") or {}
    if mfe.get("extra_per_share") and ep:
        what_ifs.append({
            "scenario": f"Hold to in-trade MFE ${mfe.get('price')}",
            "outcome": f"+${float(mfe['extra_per_share']):.2f}/sh vs actual exit",
        })

    return {
        "summary": summary,
        "strengths": str_list[:4],
        "improvements": imp_list[:4],
        "takeaways": takeaways[:4],
        "suggested_tags": mistakes[:2] if mistakes else [],
        "what_if_scenarios": what_ifs[:3],
        "deterministic": True,
    }


def _parse_llm(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    req = {"summary", "strengths", "improvements", "takeaways"}
    return d if req.issubset(d.keys()) else None


# ── Methodology hardening (P1-4) ──────────────────────────────────────────────────────

def _stable_hash(obj) -> str:
    import hashlib
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _context_hash(ctx: dict) -> str:
    """Hash of the DETERMINISTIC inputs that drive the critique — independent of any LLM."""
    keep = {
        "trade_key": ctx.get("trade_key"),
        "trade": ctx.get("trade"),
        "eq": {k: v for k, v in (ctx.get("eq") or {}).items() if not hasattr(v, "isoformat")},
        "classification": ctx.get("classification"),
        "time_in_trade": ctx.get("time_in_trade"),
        "indicators_at_entry": ctx.get("indicators_at_entry"),
        "planned_r": ctx.get("planned_r"),
        "realized_r": ctx.get("realized_r"),
    }
    return _stable_hash(keep)


def _response_hash(text: str) -> str | None:
    return _stable_hash({"llm_raw": text}) if text else None


def _integrity_ok(integrity) -> bool:
    """True unless the chart/replay integrity object explicitly reports a failure."""
    if integrity is None:
        return True
    if isinstance(integrity, dict):
        if integrity.get("ok") is False:
            return False
        if str(integrity.get("status", "")).lower() in ("fail", "failed", "error"):
            return False
        if integrity.get("time_integrity") is False:
            return False
    return True


def replay_integrity_status(ctx: dict) -> dict:
    """Replay integrity for the critique: markers resolved AND no time-integrity failure."""
    r = ctx.get("replay_integrity") or {}
    markers = bool(r.get("markers_resolved"))
    integ = _integrity_ok(r.get("chart_integrity"))
    return {"markers_resolved": markers, "time_integrity_ok": integ,
            "ok": markers and integ, "chart_integrity": r.get("chart_integrity")}


def _merge_llm_narrative(deterministic: dict, parsed: dict | None, llm_raw: str,
                         lane: str) -> tuple[dict, bool]:
    """Merge LLM prose over the deterministic narrative WITHOUT erasing deterministic facts.

    The deterministic narrative is always retained (as ``deterministic_base_summary`` and
    in the critique's separate ``deterministic_facts``). Returns ``(narrative,
    deterministic_fallback)`` where ``deterministic_fallback`` is True when the LLM did not
    contribute a usable narrative."""
    base = dict(deterministic or {})
    if parsed and parsed.get("summary"):
        narrative = {**base, **parsed, "llm_enhanced": True, "llm_lane": lane,
                     "deterministic": True, "deterministic_base_summary": base.get("summary")}
        return narrative, False
    if llm_raw:
        return {**base, "summary": base.get("summary") or llm_raw[:600],
                "parse_failed": True, "deterministic": True}, True
    return base, True


_TAG_FP_FIELDS = (
    "setup_family", "market_regime", "setup_types", "mistake_tags",
    "strength_tags", "emotion_before", "planned_r", "realized_r",
)


def _tag_snapshot(review: dict | None) -> dict:
    if not review:
        return {}
    snap: dict = {}
    for k in _TAG_FP_FIELDS:
        v = review.get(k)
        if k in ("setup_types", "mistake_tags", "strength_tags"):
            snap[k] = sorted(v or [])
        else:
            snap[k] = v
    return snap


def tag_fingerprint(review: dict | None) -> str:
    """Hash of tag fields — stale when operator edits strategy/setup/mistakes after generation."""
    if not review:
        return ""
    blob = json.dumps(_tag_snapshot(review), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def stale_tag_diff(review: dict, meta: dict, critique: dict | None = None) -> list[str]:
    """Human-readable fields that changed since critique generation."""
    old = meta.get("tags_at_generation") or {}
    if not old and critique:
        cls = critique.get("trade_classification") or {}
        old = _tag_snapshot({
            "setup_family": cls.get("setup_family"),
            "market_regime": cls.get("market_regime"),
            "setup_types": cls.get("setup_types"),
            "emotion_before": cls.get("psychology"),
        })
    if not old:
        return []
    cur = _tag_snapshot(review)
    changed = []
    for k in _TAG_FP_FIELDS:
        if old.get(k) != cur.get(k):
            changed.append(k.replace("_", " "))
    return changed


def ensure_critique_schema() -> None:
    """Queryable index table — complements payload.ai_critique for search/aggregation."""
    tiv._q("""
        CREATE TABLE IF NOT EXISTS journal_ai_critiques (
            trade_key TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            account TEXT,
            closed_date DATE,
            setup_family TEXT,
            market_regime TEXT,
            trade_type TEXT,
            status TEXT NOT NULL DEFAULT 'ok',
            prompt_version TEXT,
            generated_at TIMESTAMPTZ,
            tag_fingerprint TEXT,
            summary TEXT,
            takeaways JSONB DEFAULT '[]'::jsonb,
            strengths JSONB DEFAULT '[]'::jsonb,
            improvements JSONB DEFAULT '[]'::jsonb,
            search_text TEXT,
            structured JSONB NOT NULL DEFAULT '{}'::jsonb,
            llm_enhanced BOOLEAN DEFAULT FALSE,
            stale BOOLEAN DEFAULT FALSE,
            error_message TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, fetch="none")
    tiv._q("CREATE INDEX IF NOT EXISTS idx_jac_setup ON journal_ai_critiques(setup_family)", fetch="none")
    tiv._q("CREATE INDEX IF NOT EXISTS idx_jac_closed ON journal_ai_critiques(closed_date DESC)", fetch="none")
    tiv._q("CREATE INDEX IF NOT EXISTS idx_jac_status ON journal_ai_critiques(status)", fetch="none")


def _search_text(critique: dict) -> str:
    nar = critique.get("narrative") or {}
    parts = [
        critique.get("symbol", ""),
        nar.get("summary", ""),
        " ".join(nar.get("takeaways") or []),
        " ".join(nar.get("strengths") or []),
        " ".join(nar.get("improvements") or []),
        " ".join(nar.get("suggested_tags") or []),
    ]
    cls = critique.get("trade_classification") or {}
    parts.append(cls.get("setup_family") or "")
    parts.append(cls.get("market_regime") or "")
    return " ".join(p for p in parts if p).lower()[:8000]


def load_stored_critique(trade_key: str) -> dict | None:
    """Read persisted critique from journal_trade_reviews.payload (no generation)."""
    row = tiv._q("SELECT payload FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one")
    if not row:
        return None
    payload = tiv._review_payload(row)
    c = payload.get("ai_critique")
    if not c or not isinstance(c, dict):
        return None
    meta = payload.get("ai_critique_meta") or {}
    c = dict(c)
    c["_meta"] = meta
    c["_history_count"] = len(payload.get("ai_critique_history") or [])
    return c


def _critique_meta(review: dict, critique: dict | None, *, status: str = "ok", error: str = "",
                   stale: bool = False, llm_raw: str = "", context_hash: str = "",
                   response_hash: str | None = None, deterministic_fallback: bool = False,
                   replay_status: dict | None = None) -> dict:
    fp = tag_fingerprint(review)
    nar = (critique or {}).get("narrative") or {}
    return {
        "status": status,
        "prompt_version": PROMPT_VERSION,
        "tag_fingerprint": fp,
        "tags_at_generation": _tag_snapshot(review),
        "generated_at": (critique or {}).get("generated_at"),
        "stale": stale,
        "llm_enhanced": bool(nar.get("llm_enhanced")),
        "deterministic": bool(nar.get("deterministic")),
        "deterministic_fallback": bool(deterministic_fallback),
        "context_hash": context_hash or None,
        "response_hash": response_hash,
        "replay_integrity": replay_status or (critique or {}).get("replay_integrity"),
        "error_message": error[:300] if error else None,
        "llm_raw_preview": (llm_raw or "")[:500] if llm_raw else None,
    }


def _critique_tag_snapshot(critique: dict | None) -> dict:
    """Tags embedded in the stored critique (generation-time context)."""
    if not critique:
        return {}
    cls = critique.get("trade_classification") or {}
    return _tag_snapshot({
        "setup_family": cls.get("setup_family"),
        "market_regime": cls.get("market_regime"),
        "setup_types": cls.get("setup_types"),
        "emotion_before": cls.get("psychology"),
    })


def _stale_from_tags(review: dict, meta: dict, critique: dict | None = None) -> tuple[bool, str]:
    """Stale when current tags differ from generation-time tags."""
    cur_fp = tag_fingerprint(review)
    cur_snap = _tag_snapshot(review)
    crit_snap = _critique_tag_snapshot(critique)
    if crit_snap and cur_snap == crit_snap:
        return False, cur_fp
    stored_fp = meta.get("tag_fingerprint")
    if not stored_fp:
        return False, cur_fp
    return stored_fp != cur_fp, cur_fp


def _persist_meta(trade_key: str, payload: dict, meta: dict, *, stale: bool) -> None:
    """Write ai_critique_meta + mirror stale flag to journal_ai_critiques."""
    meta = dict(meta)
    meta["stale"] = stale
    if stale:
        meta.setdefault("stale_reason", "tags_changed")
        meta.setdefault("stale_at", datetime.now(timezone.utc).isoformat())
    else:
        meta.pop("stale_reason", None)
        meta.pop("stale_at", None)
        meta.pop("current_tag_fingerprint", None)
    payload["ai_critique_meta"] = meta
    tiv._q("UPDATE journal_trade_reviews SET payload=%s::jsonb, updated_at=NOW() WHERE trade_key=%s",
           [json.dumps(_json_clean(payload), default=str), trade_key], fetch="none")
    try:
        ensure_critique_schema()
        tiv._q("UPDATE journal_ai_critiques SET stale=%s, updated_at=NOW() WHERE trade_key=%s",
               [stale, trade_key], fetch="none")
    except Exception:
        pass


def mark_stale_on_tag_change(trade_key: str) -> bool:
    """Flag critique stale when journal tags change; clear stale when tags match again."""
    row = tiv._q("SELECT * FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one")
    if not row:
        return False
    payload = tiv._review_payload(row)
    meta = payload.get("ai_critique_meta") or {}
    if not payload.get("ai_critique"):
        return False
    stale, cur_fp = _stale_from_tags(row, meta, payload.get("ai_critique"))
    prev_stale = bool(meta.get("stale"))
    if not meta.get("tag_fingerprint"):
        meta["tag_fingerprint"] = cur_fp
        _persist_meta(trade_key, payload, meta, stale=False)
        return False
    if stale == prev_stale and (not stale or meta.get("current_tag_fingerprint") == cur_fp):
        return stale
    meta["current_tag_fingerprint"] = cur_fp
    _persist_meta(trade_key, payload, meta, stale=stale)
    return stale


def _upsert_index(trade_key: str, critique: dict, review: dict, meta: dict) -> None:
    ensure_critique_schema()
    parts = trade_key.split(":")
    sym = parts[0] if parts else critique.get("symbol", "")
    acct = parts[1] if len(parts) > 2 else ""
    cd = parts[-1] if len(parts) > 2 else None
    cls = critique.get("trade_classification") or {}
    nar = critique.get("narrative") or {}
    tiv._q("""
        INSERT INTO journal_ai_critiques (
            trade_key, symbol, account, closed_date, setup_family, market_regime, trade_type,
            status, prompt_version, generated_at, tag_fingerprint, summary, takeaways, strengths,
            improvements, search_text, structured, llm_enhanced, stale, error_message, updated_at
        ) VALUES (%s,%s,%s,%s::date,%s,%s,%s,%s,%s,%s::timestamptz,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s,NOW())
        ON CONFLICT (trade_key) DO UPDATE SET
            symbol=EXCLUDED.symbol, account=EXCLUDED.account, closed_date=EXCLUDED.closed_date,
            setup_family=EXCLUDED.setup_family, market_regime=EXCLUDED.market_regime,
            trade_type=EXCLUDED.trade_type, status=EXCLUDED.status, prompt_version=EXCLUDED.prompt_version,
            generated_at=EXCLUDED.generated_at, tag_fingerprint=EXCLUDED.tag_fingerprint,
            summary=EXCLUDED.summary, takeaways=EXCLUDED.takeaways, strengths=EXCLUDED.strengths,
            improvements=EXCLUDED.improvements, search_text=EXCLUDED.search_text,
            structured=EXCLUDED.structured, llm_enhanced=EXCLUDED.llm_enhanced,
            stale=EXCLUDED.stale, error_message=EXCLUDED.error_message, updated_at=NOW()
    """, [
        trade_key, sym, acct, cd,
        cls.get("setup_family") or review.get("setup_family"),
        cls.get("market_regime") or review.get("market_regime"),
        cls.get("type"),
        meta.get("status", "ok"),
        meta.get("prompt_version", PROMPT_VERSION),
        meta.get("generated_at") or critique.get("generated_at"),
        meta.get("tag_fingerprint"),
        nar.get("summary", "")[:2000],
        json.dumps(nar.get("takeaways") or []),
        json.dumps(nar.get("strengths") or []),
        json.dumps(nar.get("improvements") or []),
        _search_text(critique),
        json.dumps(_json_clean(critique), default=str),
        bool(nar.get("llm_enhanced")),
        bool(meta.get("stale")),
        meta.get("error_message"),
    ], fetch="none")


def generate_critique(trade_key: str, *, force: bool = False, lane: str = "grok", use_llm: bool = True) -> dict:
    review_row = tiv._q("SELECT * FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one") or {}
    payload = tiv._review_payload(review_row)
    cur_fp = tag_fingerprint(review_row)
    meta = payload.get("ai_critique_meta") or {}

    if not force:
        stored = load_stored_critique(trade_key)
        if stored:
            nar = stored.get("narrative") or {}
            sm = meta.get("status", "ok")
            if sm == "ok" and (nar.get("summary") or stored.get("trade_classification")):
                stale, cur_fp = _stale_from_tags(review_row, meta, stored)
                if not meta.get("tag_fingerprint"):
                    meta = {**meta, "tag_fingerprint": cur_fp, "stale": False}
                    _persist_meta(trade_key, payload, meta, stale=False)
                elif bool(meta.get("stale")) != stale:
                    meta = {**meta, "current_tag_fingerprint": cur_fp}
                    _persist_meta(trade_key, payload, meta, stale=stale)
                diff = stale_tag_diff(review_row, meta, stored) if stale else []
                clean = {k: v for k, v in stored.items() if not k.startswith("_")}
                return {
                    "ok": True, "cached": True, "persisted": True, "critique": clean,
                    "meta": {**meta, "tag_fingerprint": meta.get("tag_fingerprint") or cur_fp,
                             "current_tag_fingerprint": cur_fp,
                             "history_count": stored.get("_history_count", 0), "stale": stale,
                             "stale_fields": diff},
                    "stale": stale,
                    "stale_fields": diff,
                }
            if sm == "error":
                return {
                    "ok": False, "persisted": True, "error": meta.get("error_message") or "prior generation failed",
                    "meta": meta, "stale": True,
                }

    ctx = build_context(trade_key)
    if not ctx:
        err = "trade not found"
        _persist_error(trade_key, err, review_row)
        return {"ok": False, "error": err, "persisted": True}

    sections = _deterministic_sections(ctx)
    trade = ctx["trade"]
    eq = ctx["eq"]
    review = ctx["review"]
    deterministic_narrative = _deterministic_narrative(ctx, sections)
    narrative = dict(deterministic_narrative)
    llm_raw = ""
    llm_parsed = None

    if use_llm:
        import llm_lane
        prompt = PROMPT.format(
            symbol=trade["symbol"],
            trade_type=ctx["classification"]["type"],
            pnl=trade.get("pnl"),
            shares=trade.get("shares"),
            hold_min=ctx["classification"].get("hold_minutes"),
            setup=review.get("setup_family") or "untagged",
            regime=review.get("market_regime") or "unknown",
            psych=review.get("emotion_before") or "unknown",
            mistakes=", ".join(ctx["mistake_tags"]) or "none",
            strengths=", ".join(ctx["strength_tags"]) or "none",
            outcome=eq.get("outcome_grade", "?"),
            execution=eq.get("execution_grade", "?"),
            capture=int((eq.get("capture_ratio") or 0) * 100),
            mfe=eq.get("mfe_after_entry"),
            mae=eq.get("mae_after_entry"),
            pct_profit=ctx["time_in_trade"].get("pct_in_profit"),
            min_profit=ctx["time_in_trade"].get("minutes_in_profit"),
            min_dd=ctx["time_in_trade"].get("minutes_underwater"),
            rvol=eq.get("entry_volume_ratio"),
            vwap=eq.get("entry_above_vwap"),
            vwap_dist=eq.get("entry_vwap_distance_pct"),
            rsi=eq.get("entry_rsi"),
            macd=eq.get("entry_macd_state"),
            missed=eq.get("mfe_after_exit_pct"),
            runner=eq.get("runner_type"),
            planned_r=ctx.get("planned_r"),
            realized_r=ctx.get("realized_r"),
            init_stop_atr=trade.get("initial_stop_atr") or "—",
            be_secured=("yes" if trade.get("breakeven_trigger_r") is not None else "not tagged"),
            r_vs_stop=trade.get("final_r_vs_planned_stop") if trade.get("final_r_vs_planned_stop") is not None else "—",
        )
        try:
            llm_raw = llm_lane.generate(prompt, lane=lane, timeout=90)
            llm_parsed = _parse_llm(llm_raw)
        except Exception as e:
            narrative = {**narrative, "llm_error": str(e)[:120]}

    # LLM prose may enrich but NEVER overwrite the deterministic facts.
    narrative, deterministic_fallback = _merge_llm_narrative(
        deterministic_narrative, llm_parsed, llm_raw, lane)

    replay = replay_integrity_status(ctx)
    crit_status = "ok" if replay["ok"] else "degraded"
    crit_status_reason = "" if replay["ok"] else (
        "replay_markers_unresolved" if not replay["markers_resolved"] else "time_integrity_failed")

    critique = {
        "version": PROMPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_key": trade_key,
        "symbol": trade["symbol"],
        **sections,
        "narrative": narrative,
        # Deterministic facts kept verbatim — LLM output cannot erase them.
        "deterministic_facts": deterministic_narrative,
        "replay_integrity": replay,
        "status": crit_status,
        "status_reason": crit_status_reason,
        "chart_meta": ctx["chart_meta"],
        "llm_raw": llm_raw[:4000] if llm_raw else None,
    }
    meta = _critique_meta(
        review_row, critique, status=crit_status, llm_raw=llm_raw,
        context_hash=_context_hash(ctx), response_hash=_response_hash(llm_raw),
        deterministic_fallback=deterministic_fallback, replay_status=replay)
    save_critique(trade_key, critique, meta=meta, review=review_row)
    clean = dict(critique)
    return {
        "ok": True, "generated": True, "persisted": True, "critique": clean,
        "meta": meta, "stale": False,
    }


def _json_clean(obj):
    if isinstance(obj, dict):
        return {k: _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "__float__"):
        try:
            return float(obj)
        except Exception:
            pass
    return obj


def save_critique(trade_key: str, critique: dict, *, meta: dict | None = None, review: dict | None = None) -> None:
    existing = tiv._q("SELECT id, payload FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one")
    payload = tiv._review_payload(existing) if existing else {}
    old = payload.get("ai_critique")
    if old and isinstance(old, dict):
        hist = list(payload.get("ai_critique_history") or [])
        hist.insert(0, {**_json_clean(old), "archived_at": datetime.now(timezone.utc).isoformat()})
        payload["ai_critique_history"] = hist[:_HISTORY_MAX]
    payload["ai_critique"] = _json_clean(critique)
    rev = review or tiv._q("SELECT * FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one") or {}
    payload["ai_critique_meta"] = meta or _critique_meta(rev, critique)
    parts = trade_key.split(":")
    sym, acct, cd = parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
    blob = json.dumps(_json_clean(payload), default=str)
    if existing:
        tiv._q("UPDATE journal_trade_reviews SET payload=%s::jsonb, updated_at=NOW() WHERE trade_key=%s",
               [blob, trade_key], fetch="none")
    else:
        tiv._q("""
            INSERT INTO journal_trade_reviews (trade_key, symbol, account, closed_date, payload)
            VALUES (%s,%s,%s,%s::date,%s::jsonb)
            ON CONFLICT (trade_key) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()
        """, [trade_key, sym, acct, cd, blob], fetch="none")
    try:
        _upsert_index(trade_key, critique, rev, payload["ai_critique_meta"])
    except Exception:
        pass


def _persist_error(trade_key: str, error: str, review: dict | None = None) -> None:
    rev = review or tiv._q("SELECT * FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one") or {}
    payload = tiv._review_payload(rev if rev else None)
    meta = _critique_meta(rev, None, status="error", error=error, stale=True)
    payload["ai_critique_meta"] = meta
    parts = trade_key.split(":")
    sym, acct, cd = parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
    blob = json.dumps(_json_clean(payload), default=str)
    if rev and rev.get("id"):
        tiv._q("UPDATE journal_trade_reviews SET payload=%s::jsonb, updated_at=NOW() WHERE trade_key=%s",
               [blob, trade_key], fetch="none")
    else:
        tiv._q("""
            INSERT INTO journal_trade_reviews (trade_key, symbol, account, closed_date, payload)
            VALUES (%s,%s,%s,%s::date,%s::jsonb)
            ON CONFLICT (trade_key) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()
        """, [trade_key, sym, acct, cd, blob], fetch="none")
    try:
        ensure_critique_schema()
        tiv._q("""
            INSERT INTO journal_ai_critiques (trade_key, symbol, account, closed_date, status, error_message, search_text, structured, stale, updated_at)
            VALUES (%s,%s,%s,%s::date,'error',%s,'', '{}'::jsonb, TRUE, NOW())
            ON CONFLICT (trade_key) DO UPDATE SET status='error', error_message=EXCLUDED.error_message, stale=TRUE, updated_at=NOW()
        """, [trade_key, sym, acct, cd, error[:300]], fetch="none")
    except Exception:
        pass


def ai_critique_for_trade(trade_key: str, force: bool = False, apply: bool = True) -> dict:
    """Unified entry: load persisted critique or generate + save."""
    ensure_critique_schema()
    return generate_critique(trade_key, force=force)


def search_critiques(q: str = "", setup_family: str = "", days: int = 365, limit: int = 50) -> dict:
    ensure_critique_schema()
    params: list = [int(days)]
    where = ["status = 'ok'", "closed_date > now() - (%s || ' days')::interval"]
    if setup_family:
        where.append("setup_family ILIKE %s")
        params.append(f"%{setup_family}%")
    if q:
        where.append("search_text ILIKE %s")
        params.append(f"%{q.lower()}%")
    params.append(int(limit))
    rows = tiv._q(f"""
        SELECT trade_key, symbol, closed_date::text, setup_family, market_regime, trade_type,
               summary, takeaways, generated_at::text, stale
        FROM journal_ai_critiques
        WHERE {' AND '.join(where)}
        ORDER BY generated_at DESC NULLS LAST
        LIMIT %s
    """, params)
    return {"ok": True, "count": len(rows), "items": rows}


def aggregate_by_setup(days: int = 365, limit: int = 15) -> dict:
    ensure_critique_schema()
    rows = tiv._q("""
        SELECT setup_family,
               COUNT(*) AS n,
               COUNT(*) FILTER (WHERE stale) AS stale_n,
               jsonb_agg(DISTINCT imp) FILTER (WHERE imp IS NOT NULL) AS improvements
        FROM journal_ai_critiques,
             LATERAL jsonb_array_elements_text(improvements) AS imp
        WHERE status = 'ok' AND setup_family IS NOT NULL AND setup_family != ''
          AND closed_date > now() - (%s || ' days')::interval
        GROUP BY setup_family
        ORDER BY n DESC
        LIMIT %s
    """, [int(days), int(limit)])
    out = []
    for r in rows:
        imps = r.get("improvements") or []
        freq: dict[str, int] = {}
        for t in imps:
            freq[t] = freq.get(t, 0) + 1
        top = sorted(freq.items(), key=lambda x: -x[1])[:5]
        out.append({
            "setup_family": r["setup_family"],
            "trades": r["n"],
            "stale": r.get("stale_n", 0),
            "top_improvements": [{"text": t, "count": c} for t, c in top],
        })
    return {"ok": True, "setups": out}


def coaching_insights(days: int = 30) -> dict:
    """Patterns for daily coaching / morning brief / behavioral module."""
    ensure_critique_schema()
    rows = tiv._q("""
        SELECT trade_key, symbol, setup_family, market_regime, summary, takeaways, improvements, strengths, stale
        FROM journal_ai_critiques
        WHERE status = 'ok' AND closed_date > now() - (%s || ' days')::interval
        ORDER BY generated_at DESC NULLS LAST
        LIMIT 200
    """, [int(days)])
    imp_freq: dict[str, int] = {}
    str_freq: dict[str, int] = {}
    stale_keys = []
    highlights = []
    for r in rows:
        if r.get("stale"):
            stale_keys.append(r["trade_key"])
        for t in (r.get("improvements") or []):
            imp_freq[t] = imp_freq.get(t, 0) + 1
        for t in (r.get("strengths") or []):
            str_freq[t] = str_freq.get(t, 0) + 1
        if len(highlights) < 5 and r.get("summary"):
            highlights.append({
                "trade_key": r["trade_key"], "symbol": r["symbol"],
                "setup_family": r.get("setup_family"), "summary": r["summary"][:200],
                "takeaway": (r.get("takeaways") or [""])[0][:120] if r.get("takeaways") else "",
            })
    top_imp = sorted(imp_freq.items(), key=lambda x: -x[1])[:8]
    top_str = sorted(str_freq.items(), key=lambda x: -x[1])[:6]
    bullets = []
    if top_str:
        bullets.append(f"Strength pattern: {top_str[0][0]} ({top_str[0][1]} trades)")
    if top_imp:
        bullets.append(f"Recurring fix: {top_imp[0][0]} ({top_imp[0][1]} mentions)")
    if stale_keys:
        bullets.append(f"{len(stale_keys)} critiques stale after tag edits — regenerate in Trade Detail")
    return {
        "ok": True,
        "days": days,
        "critique_count": len(rows),
        "stale_count": len(stale_keys),
        "top_improvements": [{"text": t, "count": c} for t, c in top_imp],
        "top_strengths": [{"text": t, "count": c} for t, c in top_str],
        "highlights": highlights,
        "coaching_bullets": bullets,
    }


def reconcile_stale_flags(limit: int = 500) -> dict:
    """Re-derive stale from tag fingerprints (fixes stuck stale after tag revert)."""
    rows = tiv._q("""
        SELECT trade_key, payload FROM journal_trade_reviews
        WHERE payload ? 'ai_critique'
        ORDER BY updated_at DESC NULLS LAST LIMIT %s
    """, [int(limit)])
    fixed = 0
    for row in rows:
        payload = tiv._review_payload(row)
        meta = payload.get("ai_critique_meta") or {}
        stale, cur_fp = _stale_from_tags(row, meta, payload.get("ai_critique"))
        if not meta.get("tag_fingerprint"):
            meta["tag_fingerprint"] = cur_fp
            _persist_meta(row["trade_key"], payload, meta, stale=False)
            fixed += 1
        elif bool(meta.get("stale")) != stale:
            meta["current_tag_fingerprint"] = cur_fp
            _persist_meta(row["trade_key"], payload, meta, stale=stale)
            fixed += 1
    return {"ok": True, "scanned": len(rows), "reconciled": fixed}


def critique_summaries_bulk(account: str | None = None, days: int = 365, limit: int = 500) -> dict:
    """Lightweight critique summaries keyed by trade_key for trade log cards."""
    ensure_critique_schema()
    params: list = [int(days)]
    where = ["status = 'ok'", "closed_date > now() - (%s || ' days')::interval"]
    if account:
        where.append("account = %s")
        params.append(account)
    params.append(int(limit))
    rows = tiv._q(f"""
        SELECT trade_key, symbol, summary, takeaways, stale, generated_at::text
        FROM journal_ai_critiques
        WHERE {' AND '.join(where)}
        ORDER BY generated_at DESC NULLS LAST
        LIMIT %s
    """, params)
    by_key: dict[str, dict] = {}
    for r in rows:
        tk = r["trade_key"]
        takeaway = ""
        tips = r.get("takeaways") or []
        if isinstance(tips, list) and tips:
            takeaway = str(tips[0])
        by_key[tk] = {
            "trade_key": tk,
            "symbol": r.get("symbol"),
            "summary": (r.get("summary") or "")[:160],
            "takeaway": takeaway[:100],
            "stale": bool(r.get("stale")),
            "has_critique": True,
            "generated_at": r.get("generated_at"),
        }
    return {"ok": True, "count": len(by_key), "by_trade_key": by_key}


def batch_generate_critiques(
    *,
    account: str | None = None,
    date_from: str | None = None,
    days: int = 365,
    limit: int = 200,
    force: bool = False,
    use_llm: bool = False,
    skip_existing: bool = True,
) -> dict:
    """Generate persisted critiques for closed trades in range (deterministic by default)."""
    from datetime import date, timedelta

    ensure_critique_schema()
    if date_from:
        df = date_from
    else:
        df = (date.today() - timedelta(days=int(days))).isoformat()
    rows = tiv.fetch_closed_trades(account=account, date_from=df, limit=int(limit))
    out = {
        "ok": True,
        "total": len(rows),
        "generated": 0,
        "cached": 0,
        "skipped": 0,
        "errors": 0,
        "use_llm": use_llm,
        "date_from": df,
    }
    for row in rows:
        tk = row["trade_key"]
        if skip_existing and not force:
            stored = load_stored_critique(tk)
            nar = (stored or {}).get("narrative") or {}
            if stored and (nar.get("summary") or stored.get("trade_classification")):
                out["cached"] += 1
                continue
        try:
            res = generate_critique(tk, force=force, use_llm=use_llm)
            if res.get("ok"):
                if res.get("generated"):
                    out["generated"] += 1
                elif res.get("cached"):
                    out["cached"] += 1
            else:
                out["errors"] += 1
        except Exception:
            out["errors"] += 1
    # Batch result JSON artifact (P1-4) — machine-readable run record.
    try:
        from pathlib import Path as _P
        from datetime import datetime as _dt, timezone as _tz
        out["generated_at"] = _dt.now(_tz.utc).isoformat()
        rt = _P(__file__).resolve().parent.parent / "data" / "runtime"
        rt.mkdir(parents=True, exist_ok=True)
        art = rt / f"ai_critique_batch_{date.today().isoformat()}.json"
        art.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        out["artifact_path"] = str(art)
    except Exception:
        pass
    return out


def backfill_index_from_payloads(limit: int = 500) -> dict:
    """Sync journal_ai_critiques from existing payload.ai_critique rows."""
    ensure_critique_schema()
    recon = reconcile_stale_flags(limit=limit)
    rows = tiv._q("""
        SELECT trade_key, payload, setup_family, market_regime
        FROM journal_trade_reviews
        WHERE payload ? 'ai_critique'
        ORDER BY updated_at DESC NULLS LAST
        LIMIT %s
    """, [int(limit)])
    n = 0
    for row in rows:
        payload = tiv._review_payload(row)
        c = payload.get("ai_critique")
        if not c:
            continue
        meta = payload.get("ai_critique_meta") or _critique_meta(row, c)
        stale, _ = _stale_from_tags(row, meta, c)
        meta["stale"] = stale
        try:
            _upsert_index(row["trade_key"], c, row, meta)
            n += 1
        except Exception:
            pass
    return {"ok": True, "synced": n, "scanned": len(rows), "reconcile": recon}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-key")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--backfill-index", action="store_true", help="Sync journal_ai_critiques from payload rows")
    ap.add_argument("--reconcile-stale", action="store_true", help="Re-derive stale flags from tag fingerprints")
    args = ap.parse_args()

    if args.reconcile_stale:
        print(json.dumps(reconcile_stale_flags(limit=args.limit), indent=2))
        return 0

    if args.backfill_index:
        print(json.dumps(backfill_index_from_payloads(limit=args.limit), indent=2))
        return 0

    keys = [args.trade_key] if args.trade_key else []
    if not keys:
        rows = tiv.fetch_closed_trades(limit=args.limit)
        seen = set()
        for r in rows:
            k = r["trade_key"]
            if k not in seen:
                seen.add(k)
                keys.append(k)

    out = []
    for k in keys:
        res = generate_critique(k, force=args.force, use_llm=not args.no_llm)
        out.append({"trade_key": k, "ok": res.get("ok"), "cached": res.get("cached"),
                    "persisted": res.get("persisted")})
    print(json.dumps({"processed": len(out), "results": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())