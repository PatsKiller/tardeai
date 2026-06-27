#!/usr/bin/env python3
"""journal_ai_critique.py — Automated post-trade AI critique (TradeZella-style) for TradeInView.

Builds deterministic metrics from journal tags + replay bar data + execution quality, then layers
Grok coaching narrative. Persisted in journal_trade_reviews.payload.ai_critique.

  python scripts/journal_ai_critique.py --trade-key GOVX:schwab_rollover_ira:2026-05-18 --apply
  python scripts/journal_ai_critique.py --limit 20 --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import journal_trade_in_view as tiv
import ohlc_charts

PROMPT_VERSION = "ai_critique_v1"


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

Return STRICT JSON only:
{{"summary": "2-3 sentence overview",
"strengths": ["...", "..."],
"improvements": ["...", "..."],
"takeaways": ["repeat this...", "fix this..."],
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


def generate_critique(trade_key: str, *, force: bool = False, lane: str = "grok", use_llm: bool = True) -> dict:
    existing = tiv._q("SELECT payload FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one")
    payload = tiv._review_payload(existing)
    if not force and payload.get("ai_critique", {}).get("version") == PROMPT_VERSION:
        cached = payload["ai_critique"]
        nar = (cached.get("narrative") or {})
        if nar.get("summary"):
            return {"ok": True, "cached": True, "critique": cached}
        # Backfill empty narrative from stored sections (older --no-llm runs).
        ctx = build_context(trade_key)
        if ctx:
            sections = {k: cached.get(k) for k in (
                "trade_classification", "execution_quality", "risk_sizing", "opportunity_cost")}
            cached = {**cached, "narrative": _deterministic_narrative(ctx, sections)}
            save_critique(trade_key, cached)
            return {"ok": True, "cached": True, "critique": cached, "backfilled": True}

    ctx = build_context(trade_key)
    if not ctx:
        return {"ok": False, "error": "trade not found"}

    sections = _deterministic_sections(ctx)
    trade = ctx["trade"]
    eq = ctx["eq"]
    review = ctx["review"]
    narrative = _deterministic_narrative(ctx, sections)

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
        )
        try:
            text = llm_lane.generate(prompt, lane=lane, timeout=90)
            parsed = _parse_llm(text)
            if parsed and parsed.get("summary"):
                narrative = {**parsed, "llm_enhanced": True}
            elif text:
                narrative = {**narrative, "summary": (text or "")[:600], "parse_failed": True}
        except Exception as e:
            narrative = {**narrative, "llm_error": str(e)[:120]}

    critique = {
        "version": PROMPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_key": trade_key,
        "symbol": trade["symbol"],
        **sections,
        "narrative": narrative,
        "chart_meta": ctx["chart_meta"],
    }
    return {"ok": True, "critique": critique}


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


def save_critique(trade_key: str, critique: dict) -> None:
    existing = tiv._q("SELECT id, payload FROM journal_trade_reviews WHERE trade_key=%s", [trade_key], fetch="one")
    payload = tiv._review_payload(existing) if existing else {}
    payload["ai_critique"] = _json_clean(critique)
    parts = trade_key.split(":")
    sym, acct, cd = parts[0], parts[1] if len(parts) > 2 else "", parts[-1]
    if existing:
        tiv._q("UPDATE journal_trade_reviews SET payload=%s::jsonb, updated_at=NOW() WHERE trade_key=%s",
               [json.dumps(_json_clean(payload), default=str), trade_key], fetch="none")
    else:
        tiv._q("""
            INSERT INTO journal_trade_reviews (trade_key, symbol, account, closed_date, payload)
            VALUES (%s,%s,%s,%s::date,%s::jsonb)
            ON CONFLICT (trade_key) DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()
        """, [trade_key, sym, acct, cd, json.dumps(_json_clean(payload), default=str)], fetch="none")


def ai_critique_for_trade(trade_key: str, force: bool = False, apply: bool = True) -> dict:
    res = generate_critique(trade_key, force=force)
    if res.get("ok") and apply and res.get("critique") and not res.get("cached"):
        save_critique(trade_key, res["critique"])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-key")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

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
        if args.apply and res.get("critique"):
            save_critique(k, res["critique"])
        out.append({"trade_key": k, "ok": res.get("ok"), "cached": res.get("cached")})
    print(json.dumps({"processed": len(out), "results": out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())