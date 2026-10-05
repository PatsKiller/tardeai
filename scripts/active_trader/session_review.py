#!/usr/bin/env python3
"""Active Trader session review: what the engine did vs what "should have been" (operator 2026-10-05).

The operator's XNDU review on 2026-10-05 is the method this module automates:

    Time (ET) | Price | Engine                         | Should have been
    09:50:13  | 4.33  | heads-up                        | correct, right before the move
    09:51     | 4.35  | breakout; alert held 4 min      | time to buy (best entry #1)
    09:55:11  | 4.43  | time to buy, +2.5% already      | extended, don't chase; buy zone 4.38–4.40
    09:59     | 4.38  | 10:00:22 blocked by COOLDOWN    | back in buy zone (best entry #2)
    10:06     | 4.50  | —                               | top of the move
    10:07:09  | 4.48  | your buy                        | after the top

"Should have been" is deterministic (docs/active_trader/ACTIVE_TRADER_SOUL.md, thresholds in
`active_trader_review:` of config/scalp_signal_engine.yaml):

  breakout entry  first bar that closes above a base of >= base_min_bars bars whose range is
                  <= base_max_range_pct, on volume >= break_vol_mult x the base's mean volume.
                  Ideal price = max(base high, break-bar open); stop = base low (min-stop floor).
  pullback entry  after an exited leg (entry -> leg high) of at least min_leg_pct, the first bar whose low reaches the
                  zone [high - zone_hi_retrace x leg, high - zone_lo_retrace x leg] and closes
                  >= zone low - zone_tolerance; stop = the leg's entry price.
  exit            the first evidence after entry (shared with the simulator, one brain): stop hit,
                  close below the prior bar's low, volume climax with a long upper wick, close below
                  session VWAP, or the time stop.
  top             highest high from the first entry to the end of the review horizon.

Reads only what the Command Center already holds: the alert journal, the operator fills via
momentum_alerts_api (read-only SELECT), the microstructure recorder's snapshots, and minute bars
from the engine's bar accessor (injected; no new provider fetch here). No order path, no broker.

  python scripts/active_trader/session_review.py                       # today, dry run
  python scripts/active_trader/session_review.py --day 2026-10-05 --apply
  python scripts/active_trader/session_review.py --day 2026-10-05 --symbol XNDU
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, fields
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from active_trader import momentum_alerts as ma
    from active_trader import momentum_alerts_api as api
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import momentum_alerts_api as api

ET = ZoneInfo("America/New_York")
CONTRACT = "active-trader-session-review-v1"

# Engine kinds by name. EXTENDED / PULLBACK_ZONE / APPROACHING come from the fast trigger loop
# (alert-sync PR); they are read here by name only.
KIND_TEXT = {
    ("ARMED", "ALERT"): "🟡 Heads-up",
    ("TRIGGERED", "ALERT"): "🟢 Time to buy",
    ("APPROACHING", "ALERT"): "⏱ About to fire",
    ("EXTENDED", "ALERT"): "🟠 Extended — don't chase",
    ("PULLBACK_ZONE", "ALERT"): "🟢 Back in buy zone",
    ("PREMARKET_WATCH", "ALERT"): "🌅 Premarket heads-up",
}
BUY_KINDS = frozenset({"TRIGGERED", "PULLBACK_ZONE"})
WATCH_KINDS = frozenset({"ARMED", "APPROACHING", "PREMARKET_WATCH", "EXTENDED"})


@dataclass(frozen=True)
class ReviewConfig:
    """Defaults are the v1 doctrine. `active_trader_review:` in config/scalp_signal_engine.yaml may
    override any field (operator-ratified). signal_calibration proposes; it never writes."""
    mode: str = "shadow"                 # shadow = persist only; send = also a Telegram summary
    window_et: tuple = ("09:30", "11:55")  # ideal entries are graded inside the engine's window only
    link_max_s: float = 600.0            # an engine row more than this after an ideal entry is not "its" alert
    base_min_bars: int = 3               # a base is at least this many 1-min bars …
    base_max_bars: int = 8
    base_max_range_pct: float = 1.0      # … whose high-low range is within this % of price
    break_vol_mult: float = 1.5          # break bar volume >= this x the base's mean volume
    zone_lo_retrace: float = 0.382       # pullback zone = 38.2%–61.8% retrace of the exited leg
    zone_hi_retrace: float = 0.618
    zone_tolerance: float = 0.01         # $ below the zone the pullback close may sit (one tick)
    pullback_max_bars: int = 15          # zone must be reached within this many bars of the leg high
    min_leg_pct: float = 1.0             # only a leg of at least this % (entry → high) offers a pullback zone
    min_stop_pct: float = 0.5            # stop at least this % below entry (noise floor)
    climax_mult: float = 3.0             # exit: bar volume >= this x prior climax_lookback average …
    climax_lookback: int = 10
    climax_wick_frac: float = 0.5        # … with an upper wick >= this share of the range
    time_stop_bars: int = 20             # exit at the close after this many bars in the trade
    horizon_bars: int = 30               # the move's top is looked for within this many bars
    heads_up_lead_s: float = 300.0       # a heads-up up to this long before an ideal entry is "correct"
    late_s: float = 60.0                 # a buy alert later than this after the ideal bar is "late"
    chase_pct: float = 1.0               # a buy alert this % above the ideal entry is a chase …
    chase_r: float = 1.0                 # … or this many R above it
    missed_window_s: float = 120.0       # a veto within this long after an ideal entry "missed" it
    top_symbols: int = 5                 # Telegram summary cap

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "ReviewConfig":
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in (raw or {}).items() if k in known})
        if cfg.mode not in ("shadow", "send"):
            raise ValueError(f"active_trader_review.mode must be shadow or send, got {cfg.mode!r}")
        return cfg


# ── bars ──────────────────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def bar_epoch(b: Mapping[str, Any]) -> Optional[float]:
    t = b.get("t")
    if t is None:
        return _f(b.get("ts_epoch"))
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


def norm_bars(bars: Iterable[Mapping[str, Any]]) -> list[dict]:
    out = []
    for b in bars:
        e = bar_epoch(b)
        o, h, lo, c = (_f(b.get(k)) for k in ("o", "h", "l", "c"))
        if e is None or None in (o, h, lo, c):
            continue
        out.append({"ts": e, "o": o, "h": h, "l": lo, "c": c, "v": _f(b.get("v")) or 0.0})
    out.sort(key=lambda x: x["ts"])
    return out


def et(ts: Optional[float], secs: bool = True) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, ET).strftime("%H:%M:%S" if secs else "%H:%M")


def vwap_series(bars: Sequence[Mapping[str, Any]]) -> list[Optional[float]]:
    pv = vol = 0.0
    out: list[Optional[float]] = []
    for b in bars:
        typ = (b["h"] + b["l"] + b["c"]) / 3.0
        pv += typ * b["v"]
        vol += b["v"]
        out.append(pv / vol if vol > 0 else None)
    return out


# ── the shared exit rule (one brain: session review and the auto-trader simulator) ─────────────

def exit_evidence(bars: Sequence[Mapping[str, Any]], i: int, *, stop: float, entry_idx: int,
                  vwap: Sequence[Optional[float]], cfg: ReviewConfig) -> Optional[tuple[str, float]]:
    """Exit reason and price at bar i for a long entered at bar entry_idx, or None to hold."""
    b = bars[i]
    if b["l"] <= stop:
        return "stop hit", min(stop, b["o"])
    if i > entry_idx and b["c"] < bars[i - 1]["l"]:
        return "closed below the prior bar's low", b["c"]
    prior = [x["v"] for x in bars[max(0, i - cfg.climax_lookback):i]]
    rng = b["h"] - b["l"]
    if prior and rng > 0:
        avg = sum(prior) / len(prior)
        wick = (b["h"] - max(b["o"], b["c"])) / rng
        if avg > 0 and b["v"] >= cfg.climax_mult * avg and wick >= cfg.climax_wick_frac:
            return "volume climax with a long upper wick", b["c"]
    if vwap[i] is not None and b["c"] < vwap[i] and (i == 0 or bars[i - 1]["c"] >= (vwap[i - 1] or 0)):
        return "lost VWAP", b["c"]
    if i - entry_idx >= cfg.time_stop_bars:
        return "time stop", b["c"]
    return None


def _floor_stop(entry: float, stop: float, cfg: ReviewConfig) -> float:
    return min(stop, entry * (1 - cfg.min_stop_pct / 100.0))


def _find_base_break(bars: Sequence[Mapping[str, Any]], i: int, cfg: ReviewConfig) -> Optional[dict]:
    """Is bar i the break of a base ending at bar i-1?"""
    b = bars[i]
    best = None
    for n in range(cfg.base_min_bars, cfg.base_max_bars + 1):
        if i - n < 0:
            break
        base = bars[i - n:i]
        hi, lo = max(x["h"] for x in base), min(x["l"] for x in base)
        mid = (hi + lo) / 2
        if mid <= 0 or (hi - lo) / mid * 100 > cfg.base_max_range_pct:
            break  # widening the window only widens the range
        best = (hi, lo, sum(x["v"] for x in base) / n, n)
    if not best:
        return None
    hi, lo, avg_v, n = best
    if b["c"] > hi and b["h"] > hi and avg_v > 0 and b["v"] >= cfg.break_vol_mult * avg_v:
        return {"base_high": hi, "base_low": lo, "base_bars": n, "vol_x": round(b["v"] / avg_v, 2)}
    return None


def _in_window(ts: float, cfg: ReviewConfig) -> bool:
    t = datetime.fromtimestamp(ts, ET).strftime("%H:%M")
    return cfg.window_et[0] <= t <= cfg.window_et[1]


def ideal_trades(bars_in: Iterable[Mapping[str, Any]], cfg: ReviewConfig) -> dict:
    """Deterministic 'should have been' trades over the session's minute bars (one position at a
    time). Returns entries (breakout / pullback), exits, legs and the move's top."""
    bars = norm_bars(bars_in)
    vw = vwap_series(bars)
    trades: list[dict] = []
    holding_breaks: list[dict] = []
    pos: Optional[dict] = None
    last_leg: Optional[dict] = None
    i = 0
    while i < len(bars):
        b = bars[i]
        if pos is None and not _in_window(b["ts"], cfg):
            i += 1
            continue
        if pos is None:
            brk = _find_base_break(bars, i, cfg)
            pb = None
            if brk is None and last_leg and i - last_leg["high_idx"] <= cfg.pullback_max_bars:
                z_hi, z_lo = last_leg["zone"][1], last_leg["zone"][0]
                if b["l"] <= z_hi and b["c"] >= z_lo - cfg.zone_tolerance:
                    pb = last_leg
            if brk or pb:
                if brk:
                    price = max(brk["base_high"], b["o"])
                    stop = _floor_stop(price, brk["base_low"], cfg)
                    pos = {"kind": "breakout", "idx": i, "ts": b["ts"], "price": round(price, 4),
                           "stop": round(stop, 4), "why": f"broke a {brk['base_bars']}-bar base "
                           f"({brk['base_low']:g}–{brk['base_high']:g}) on {brk['vol_x']}x volume", **brk}
                else:
                    price = b["c"]
                    stop = _floor_stop(price, pb["entry"], cfg)
                    pos = {"kind": "pullback", "idx": i, "ts": b["ts"], "price": round(price, 4),
                           "stop": round(stop, 4), "zone": pb["zone"],
                           "why": f"pulled back into the buy zone {pb['zone'][0]:.2f}–{pb['zone'][1]:.2f} and held"}
                    last_leg = None
                pos["high"], pos["high_idx"] = b["h"], i
                i += 1
                continue
        else:
            if b["h"] > pos["high"]:
                pos["high"], pos["high_idx"] = b["h"], i
            if _find_base_break(bars, i, cfg) and i > pos["idx"]:
                holding_breaks.append({"ts": b["ts"], "price": b["c"], "while_in": pos["kind"]})
            ex = exit_evidence(bars, i, stop=pos["stop"], entry_idx=pos["idx"], vwap=vw, cfg=cfg)
            if ex:
                reason, px = ex
                leg = pos["high"] - pos["price"]
                trade = {**{k: v for k, v in pos.items() if k not in ("idx", "high_idx")},
                         "exit_ts": b["ts"], "exit_price": round(px, 4), "exit_reason": reason,
                         "leg_high": pos["high"], "leg_high_ts": bars[pos["high_idx"]]["ts"],
                         "pnl_per_share": round(px - pos["price"], 4),
                         "pnl_pct": round((px - pos["price"]) / pos["price"] * 100, 3),
                         "r": round((px - pos["price"]) / (pos["price"] - pos["stop"]), 2)
                         if pos["price"] > pos["stop"] else None}
                trades.append(trade)
                if leg > 0 and leg / pos["price"] * 100 >= cfg.min_leg_pct:
                    zl = pos["high"] - cfg.zone_hi_retrace * leg
                    zh = pos["high"] - cfg.zone_lo_retrace * leg
                    last_leg = {"entry": pos["price"], "high": pos["high"], "high_idx": pos["high_idx"],
                                "zone": (round(zl, 4), round(zh, 4))}
                pos = None
        i += 1
    if pos is not None:  # still open at the end of the bars: mark at the last close
        lb = bars[-1]
        trades.append({**{k: v for k, v in pos.items() if k not in ("idx", "high_idx")},
                       "exit_ts": lb["ts"], "exit_price": lb["c"], "exit_reason": "open at end of data",
                       "leg_high": pos["high"], "leg_high_ts": bars[pos["high_idx"]]["ts"],
                       "pnl_per_share": round(lb["c"] - pos["price"], 4),
                       "pnl_pct": round((lb["c"] - pos["price"]) / pos["price"] * 100, 3), "r": None})
    top = None
    if trades:
        start = next(k for k, x in enumerate(bars) if x["ts"] >= trades[0]["ts"])
        window = bars[start:start + cfg.horizon_bars]
        tb = max(window, key=lambda x: (x["h"], -x["ts"]))
        top = {"ts": tb["ts"], "price": tb["h"], "volume": tb["v"]}
    return {"trades": trades, "top": top, "holding_breaks": holding_breaks, "bars": len(bars)}


# ── grade the engine and the operator against the ideal ──────────────────────

def _price(row: Mapping[str, Any]) -> Optional[float]:
    c = row.get("candidate") or {}
    return _f(c.get("last")) if c.get("last") is not None else _f((row.get("l2") or {}).get("best_ask"))


def _engine_text(row: Mapping[str, Any]) -> str:
    kind, verdict = row.get("kind"), row.get("verdict")
    if verdict == "VETO":
        reasons = ", ".join(row.get("veto_reasons") or []) or "veto"
        label = "time to buy" if kind == "TRIGGERED" else ("heads-up" if kind == "ARMED" else str(kind).lower())
        return f"⛔ {label} blocked ({reasons})"
    return KIND_TEXT.get((kind, verdict), f"{kind} {verdict}")


def grade(symbol: str, ideal: Mapping[str, Any], journal: Sequence[Mapping[str, Any]],
          trips: Sequence[Mapping[str, Any]], cfg: ReviewConfig) -> dict:
    """The operator's table, built deterministically, plus the metrics behind it."""
    trades = list(ideal.get("trades") or [])
    entries = sorted(trades, key=lambda t: t["ts"])
    rows = sorted((r for r in journal if (r.get("candidate") or {}).get("symbol") == symbol),
                  key=lambda r: r.get("ts_epoch") or 0)
    table: list[dict] = []
    metrics = {"latency_s": [], "missed": [], "chases": [], "correct_heads_up": 0}
    claimed: set[int] = set()

    def ideal_before(ts: float) -> Optional[tuple[int, dict]]:
        cand = [(k, t) for k, t in enumerate(entries) if t["ts"] <= ts]
        return cand[-1] if cand else None

    for r in rows:
        ts, px = float(r["ts_epoch"]), _price(r)
        kind, verdict = r.get("kind"), r.get("verdict")
        should, note = "", ""
        nxt = [t for t in entries if t["ts"] >= ts - 60]
        prev = ideal_before(ts)
        if verdict == "ALERT" and kind in WATCH_KINDS and nxt and 0 <= nxt[0]["ts"] - ts + 60 <= cfg.heads_up_lead_s \
                and (px is None or px <= nxt[0]["price"] * (1 + cfg.chase_pct / 100)):
            should = "✅ Correct — right before the move"
            metrics["correct_heads_up"] += 1
        elif verdict == "ALERT" and kind in BUY_KINDS and prev:
            k, t = prev
            lat = ts - t["ts"]
            metrics["latency_s"].append(round(lat))
            r_size = t["price"] - t["stop"]
            ext_pct = (px - t["price"]) / t["price"] * 100 if px else 0.0
            ext_r = (px - t["price"]) / r_size if (px and r_size > 0) else 0.0
            late = lat > cfg.late_s
            chase = ext_pct >= cfg.chase_pct or ext_r >= cfg.chase_r
            if chase:
                metrics["chases"].append({"ts": ts, "price": px, "ideal": t["price"], "ext_pct": round(ext_pct, 2),
                                          "ext_r": round(ext_r, 2)})
                zone = _zone_after(t, entries, trades)
                should = (f"\"Extended, don't chase; buy zone {zone[0]:.2f}–{zone[1]:.2f}\"" if zone
                          else "\"Extended, don't chase\"")
                note = f"{_mmss(lat)} after the {et(t['ts'], False)} entry, {ext_pct:+.1f}% already"
            elif late:
                should = f"🟢 Time to buy at {et(t['ts'], False)}"
                note = f"{_mmss(lat)} late"
            else:
                should = "✅ On time"
        elif verdict == "VETO" and prev and 0 <= ts - prev[1]["ts"] <= cfg.missed_window_s and prev[0] not in claimed:
            k, t = prev
            claimed.add(k)
            label = ("best entry #%d" % (k + 1)) if t["pnl_per_share"] > 0 else ("entry #%d" % (k + 1))
            metrics["missed"].append({"ideal_ts": t["ts"], "engine_ts": ts, "reasons": r.get("veto_reasons") or []})
            should = f"🟢 {'Back in buy zone' if t['kind'] == 'pullback' else 'Time to buy'} ({label}) — missed"
        elif prev and prev[1]["ts"] < ts <= prev[1]["exit_ts"]:
            hb = [h for h in (ideal.get("holding_breaks") or []) if 0 <= ts - h["ts"] <= cfg.missed_window_s]
            should = ("Second breakout already underway (holding entry #%d)" % (prev[0] + 1) if hb
                      else "Mid-run (holding entry #%d)" % (prev[0] + 1))
        elif verdict == "VETO":
            should = "✅ Correct to stay out (no ideal entry here)"
        elif verdict == "ALERT":
            should = "No ideal entry follows (noise)"
        table.append({"ts": ts, "time": et(ts), "price": px, "engine": _engine_text(r) + (f", {note}" if note else ""),
                      "should": should, "source": "engine"})

    for k, t in enumerate(entries):
        seen = [r for r in rows if r.get("verdict") == "ALERT" and t["ts"] - cfg.heads_up_lead_s <= float(r["ts_epoch"])]
        nxt_row = next((r for r in rows if 0 <= float(r["ts_epoch"]) - t["ts"] <= cfg.link_max_s), None)
        what = "Breakout happened" if t["kind"] == "breakout" else "Pullback into the zone"
        if nxt_row is None:
            engine = f"{what}; no engine alert within {_mmss(cfg.link_max_s)}"
        else:
            lag = float(nxt_row["ts_epoch"]) - t["ts"]
            if nxt_row.get("verdict") == "VETO":
                engine = (f"{what}; engine saw it at {et(float(nxt_row['ts_epoch']))} but blocked it "
                          f"({', '.join(nxt_row.get('veto_reasons') or [])})")
            elif lag > cfg.late_s:
                engine = f"{what}, alert held until the next check ({et(float(nxt_row['ts_epoch']))}, {_mmss(lag)} later)"
            else:
                engine = f"{what}; alerted {_mmss(lag)} later"
        label = f"best entry #{k + 1}" if t["pnl_per_share"] > 0 else f"entry #{k + 1}, failed ({t['pnl_pct']:+.2f}%)"
        table.append({"ts": t["ts"], "time": et(t["ts"], False), "price": t["price"], "engine": engine,
                      "should": f"🟢 {'Time to buy' if t['kind'] == 'breakout' else 'Back in buy zone'} "
                                f"({label}) — {t['why']}", "source": "ideal_entry",
                      "seen_before": bool(seen)})
        table.append({"ts": t["exit_ts"], "time": et(t["exit_ts"], False), "price": t["exit_price"],
                      "engine": "—", "should": f"🔴 Exit entry #{k + 1}: {t['exit_reason']} "
                      f"({t['pnl_pct']:+.2f}%)", "source": "ideal_exit"})
    top = ideal.get("top")
    if top:
        table.append({"ts": top["ts"], "time": et(top["ts"], False), "price": top["price"], "engine": "—",
                      "should": "Top of the move", "source": "top"})

    you = []
    for t in trips:
        if t.get("symbol") != symbol or t.get("buy_ts") is None:
            continue
        bts = float(t["buy_ts"])
        al = t.get("alert") or {}
        kname = {"ARMED": "heads-up", "TRIGGERED": "time-to-buy"}.get(str(al.get("kind") or ""), str(al.get("kind") or "").lower())
        ref = f", {_mmss(al.get('lag_s') or 0)} after the {str(al.get('at') or '')[11:16]} {kname}" if al else ""
        after_top = bool(top and bts > top["ts"] + 60)
        best = min(entries, key=lambda e: abs(e["ts"] - bts)) if entries else None
        table.append({"ts": bts, "time": et(bts), "price": t.get("buy_price"), "engine": f"Your buy{ref}",
                      "should": "After the top" if after_top else
                      (f"vs ideal {best['price']:.2f} at {et(best['ts'], False)}" if best else ""), "source": "you"})
        if t.get("sell_at"):
            sts = bts + float(t.get("held_s") or 0)
            table.append({"ts": sts, "time": et(sts), "price": t.get("sell_price"),
                          "engine": f"Your sell, {_money(t.get('pnl'))}", "should": "—", "source": "you"})
        you.append({"buy_ts": bts, "buy": t.get("buy_price"), "sell": t.get("sell_price"), "qty": t.get("qty"),
                    "pnl": t.get("pnl"), "after_top": after_top,
                    "vs_best_entry": round(t["buy_price"] - best["price"], 4) if best else None})
    table.sort(key=lambda x: (x["ts"], {"ideal_entry": 0, "engine": 1, "you": 2, "top": 3, "ideal_exit": 4}[x["source"]]))
    ideal_pnl = round(sum(t["pnl_per_share"] for t in trades), 4)
    lat = sorted(metrics["latency_s"])
    return {
        "symbol": symbol, "table": table, "ideal_trades": trades, "top": top,
        "holding_breaks": ideal.get("holding_breaks"),
        "metrics": {**metrics,
                    "latency_p50_s": lat[len(lat) // 2] if lat else None,
                    "latency_max_s": lat[-1] if lat else None,
                    "ideal_pnl_per_share": ideal_pnl,
                    "ideal_pnl_pct": round(sum(t["pnl_pct"] for t in trades), 3),
                    "you": you,
                    "your_pnl": round(sum((x.get("pnl") or 0) for x in you), 2) if you else None},
    }


def _zone_after(t: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]]):
    later = [x for x in entries if x["ts"] > t["ts"] and x["kind"] == "pullback"]
    return tuple(later[0]["zone"]) if later else None


def _mmss(s: float) -> str:
    s = int(round(abs(s)))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _money(v: Any) -> str:
    f = _f(v)
    return "—" if f is None else f"{'+' if f >= 0 else '−'}${abs(f):,.2f}"


# ── session ───────────────────────────────────────────────────────────────────

def review_symbol(symbol: str, *, bars: Sequence[Mapping[str, Any]], journal: Sequence[Mapping[str, Any]],
                  trips: Sequence[Mapping[str, Any]], cfg: ReviewConfig) -> dict:
    return grade(symbol, ideal_trades(bars, cfg), journal, trips, cfg)


def reviews_dir(base: Optional[Path] = None) -> Path:
    return (base or ma.journal_dir()) / "reviews"


def review_path(day: str, base: Optional[Path] = None) -> Path:
    return reviews_dir(base) / f"{day}.json"


def read_review(day: str, base: Optional[Path] = None) -> Optional[dict]:
    p = review_path(day, base)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        return None


def list_days(base: Optional[Path] = None) -> list[str]:
    d = reviews_dir(base)
    return sorted((p.stem for p in d.glob("*.json")), reverse=True) if d.exists() else []


def summary_message(review: Mapping[str, Any], cfg: ReviewConfig) -> tuple[str, str]:
    """Concise Telegram block: one short section per symbol, top N by activity."""
    syms = sorted(review.get("symbols") or [], key=lambda s: -(len(s.get("ideal_trades") or []) + len(s["metrics"].get("you") or [])))
    lines = []
    for s in syms[: cfg.top_symbols]:
        m = s["metrics"]
        ent = s.get("ideal_trades") or []
        head = f"{s['symbol']}: ideal {m['ideal_pnl_pct']:+.1f}% in {len(ent)} entr{'y' if len(ent) == 1 else 'ies'}"
        if m.get("you"):
            head += f" · you {_money(m.get('your_pnl'))}"
        lines.append(head)
        for t in ent[:3]:
            lines.append(f"  {et(t['ts'], False)} {t['kind']} {t['price']:.2f} → {et(t['exit_ts'], False)} "
                         f"{t['exit_price']:.2f} ({t['pnl_pct']:+.1f}%)")
        bits = []
        if m.get("latency_max_s"):
            bits.append(f"buy alert late {_mmss(m['latency_max_s'])}")
        if m.get("missed"):
            bits.append(f"{len(m['missed'])} entry missed ({', '.join(sorted({x for r in m['missed'] for x in r['reasons']}))})")
        if m.get("chases"):
            bits.append(f"{len(m['chases'])} chase")
        if bits:
            lines.append("  engine: " + " · ".join(bits))
    title = f"{ma.AT_SCALP_ALERT_HEADER}\n📋 Session review · {review.get('day')}"
    body = "\n".join([ma.NOT_AN_ORDER, *lines] if lines else [ma.NOT_AN_ORDER, "No setups or trades to review."])
    base = ma._cc_base()
    if base:
        body += f"\nDetails: {base}/v3/active-trader?tab=Session%20review"
    return title, body


def build_review(day: str, *, journal: Sequence[Mapping[str, Any]], trips: Sequence[Mapping[str, Any]],
                 bars_fn: Callable[[str], list], cfg: ReviewConfig, symbols: Optional[Iterable[str]] = None) -> dict:
    touched = {(r.get("candidate") or {}).get("symbol") for r in journal} | {t.get("symbol") for t in trips}
    touched = sorted(s for s in touched if s and (symbols is None or s in set(symbols)))
    out = []
    for s in touched:
        try:
            bars = bars_fn(s) or []
        except Exception:  # noqa: BLE001 — one symbol's bars never sink the review
            bars = []
        out.append({**review_symbol(s, bars=bars, journal=journal, trips=trips, cfg=cfg), "bars": len(bars)})
    return {"contract": CONTRACT, "day": day, "generated_at": datetime.now(ET).isoformat(timespec="seconds"),
            "config": {f.name: getattr(cfg, f.name) for f in fields(cfg)}, "symbols": out,
            "method": "docs/active_trader/ACTIVE_TRADER_SOUL.md · scripts/active_trader/session_review.py",
            "authority": ma.AUTHORITY}


def learning_records(review: Mapping[str, Any]) -> list[dict]:
    """Graded evidence for trade_learning / signal_calibration (type=review)."""
    recs = []
    for s in review.get("symbols") or []:
        m = s["metrics"]
        recs.append({"id": f"review:{review['day']}:{s['symbol']}", "type": "review", "day": review["day"],
                     "symbol": s["symbol"], "ideal_trades": len(s.get("ideal_trades") or []),
                     "ideal_pnl_pct": m.get("ideal_pnl_pct"), "latency_s": m.get("latency_s"),
                     "missed": [{"reasons": x["reasons"]} for x in m.get("missed") or []],
                     "chases": [{"ext_pct": x["ext_pct"], "ext_r": x["ext_r"]} for x in m.get("chases") or []],
                     "correct_heads_up": m.get("correct_heads_up"), "your_pnl": m.get("your_pnl")})
    return recs


def write_review(review: Mapping[str, Any], base: Optional[Path] = None) -> Path:
    p = review_path(review["day"], base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(review, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)
    return p


def _load_cfg() -> dict:
    import scalp_shadow_logger as L  # the engine's config loader (no provider call)
    return L.load_config()


def run_day(day: str, *, apply: bool, symbols: Optional[list[str]] = None, conn=None,
            bars_fn: Optional[Callable[[str], list]] = None, send_fn: Optional[Callable[..., dict]] = None,
            cfg_raw: Optional[Mapping[str, Any]] = None) -> dict:
    cfg_raw = cfg_raw if cfg_raw is not None else _load_cfg()
    cfg = ReviewConfig.from_mapping(cfg_raw.get("active_trader_review"))
    from active_trader import trade_replay as tr
    journal = tr._journal_day(day)
    compact = [api._compact(r, None) for r in journal]
    syms = {(r.get("candidate") or {}).get("symbol") for r in journal} - {None}
    fills = api.operator_fills(day, syms, conn=conn) if syms else []
    trips = api.attribute_fills(fills, compact)
    if bars_fn is None:
        import scalp_shadow_logger as L
        fetch_days = (_date.today() - _date.fromisoformat(day)).days + 3
        bars_fn = lambda s: L.session_rth_bars(s, cfg_raw, day, fetch_days)  # noqa: E731 — the engine's own accessor
    review = build_review(day, journal=journal, trips=trips, bars_fn=bars_fn, cfg=cfg, symbols=symbols)
    from active_trader import auto_trader_sim as sim
    review["auto_sim"] = sim.simulate_day(review, journal=journal, cfg_raw=cfg_raw, bars_fn=bars_fn)
    result = {"day": day, "symbols": len(review["symbols"]), "apply": apply, "mode": cfg.mode}
    if apply:
        result["path"] = str(write_review(review))
        from active_trader import trade_learning as tl
        result["learning_appended"] = tl.append_new(learning_records(review))
        if sim.mode(cfg_raw) == "auto_sim":
            result["auto_sim_ledger"] = sim.append_ledger(review["auto_sim"])
        if cfg.mode == "send" and review["symbols"]:
            title, body = summary_message(review, cfg)
            result["send"] = (send_fn or ma.telegram_send)(alert_type="at_session_review", title=title, body=body)
    else:
        result["review"] = review
    return result


def render_table(sym_review: Mapping[str, Any]) -> str:
    lines = ["Time (ET) | Price | Engine | Should have been"]
    for r in sym_review["table"]:
        px = "—" if r["price"] is None else f"{r['price']:.2f}"
        lines.append(f"{r['time']} | {px} | {r['engine']} | {r['should']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day", default=datetime.now(ET).date().isoformat())
    ap.add_argument("--symbol", action="append")
    ap.add_argument("--apply", action="store_true", help="persist the review (+ Telegram when mode=send)")
    a = ap.parse_args(argv)
    from db_adapter import get_connection
    conn = get_connection()
    res = run_day(a.day, apply=a.apply, symbols=[s.upper() for s in a.symbol] if a.symbol else None, conn=conn)
    if not a.apply:
        for s in res["review"]["symbols"]:
            print(f"\n== {s['symbol']} ({s['bars']} bars)\n" + render_table(s))
        a = res["review"]["auto_sim"]
        print(json.dumps({"mode": a["mode"], "size_shares": a["size_shares"], "compare": a["compare"],
                          "metrics": {k: v["metrics"] for k, v in a["sources"].items()}}, indent=1, default=str))
    else:
        print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
