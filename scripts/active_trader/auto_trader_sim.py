#!/usr/bin/env python3
"""Active Trader automated mode — SIMULATION ONLY (operator 2026-10-05).

"If this was an automated trade — build up to having both the option for manual and automated — it
would have got in and got out safely according to the volume and what was happening in the Level 2."

This is that automation, as a shadow. It consumes the same decisions the operator sees (the alert
journal) and the same "should have been" entries the session review grades against, and it exits
with the same evidence rule (session_review.exit_evidence) — one brain for manual and automated.

  fill    at the ask when the decision fired, plus slippage from walking the recorded book for the
          configured size; refused when the size is more than max_take_pct of the ask supply near
          the inside (the "the supply wasn't there" check)
  stop    the decision's stop, never tighter than min_stop_pct of price
  exit    stop, close below the prior bar's low, volume climax with an upper wick, VWAP loss, or the
          time stop; sold at the bid less book slippage
  fees    SEC fee on sells + FINRA TAF per share (config)

Two entry sources are simulated side by side:
  engine           the engine's own buy decisions (TRIGGERED / PULLBACK_ZONE alerts) as they fired
  improved_timing  the session review's ideal entries (breakout / pullback) — what the alert-sync
                   fast loop is being built to deliver; labelled as such until that loop is live

`active_trader_mode: manual | auto_sim` in config/scalp_signal_engine.yaml. auto_sim writes the
ledger (the track record automation must earn); manual computes the comparison only. There is no
auto_live: this module has no broker adapter, no order object, no network and no secret. The gates
any live automation would need are in docs/active_trader/ACTIVE_TRADER_SOUL.md §7.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

try:
    from active_trader import momentum_alerts as ma
    from active_trader import session_review as sr
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import session_review as sr

CONTRACT = "active-trader-auto-sim-v1"
MODES = ("manual", "auto_sim")


@dataclass(frozen=True)
class SimConfig:
    """`active_trader_auto_sim:` in config/scalp_signal_engine.yaml overrides any field."""
    size_shares: int = 500              # used when size_notional_usd is 0
    size_notional_usd: float = 0.0      # > 0: shares = floor(this / entry price), so symbols compare fairly
    tick: float = 0.01
    max_take_pct: float = 25.0          # refuse when size > this % of the ask supply near the inside
    near_pct: float = 1.0               # "near the inside" = within this % of the best quote
    book_max_age_s: float = 600.0       # a book snapshot older than this before the entry is "no book"
    min_stop_pct: float = 1.0           # the #1439 minimum-stop rule's price floor
    sec_fee_rate: float = 0.0000278     # SEC fee on sell proceeds
    taf_per_share: float = 0.000166     # FINRA TAF per share sold …
    taf_cap: float = 8.30               # … capped per trade
    commission: float = 0.0

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "SimConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (raw or {}).items() if k in known})


def mode(cfg_raw: Mapping[str, Any]) -> str:
    m = str((cfg_raw or {}).get("active_trader_mode") or "manual")
    if m not in MODES:
        raise ValueError(f"active_trader_mode must be one of {MODES} (there is no live mode), got {m!r}")
    return m


# ── book ──────────────────────────────────────────────────────────────────────

def book_at(ts: float, symbol: str, journal: Sequence[Mapping[str, Any]], cfg: SimConfig,
            snaps: Sequence[Mapping[str, Any]] = ()) -> Optional[dict]:
    """The most recent book at/before ts: a recorder snapshot (real levels) if one exists, else the
    alert journal's L2 summary (aggregate depth over N levels)."""
    best = None
    for s in snaps:
        st = sr._f(s.get("ts_epoch") or s.get("ts"))
        if st is not None and st <= ts and ts - st <= cfg.book_max_age_s and (best is None or st > best["ts"]):
            asks = [(sr._f(a[0]), sr._f(a[1])) for a in (s.get("asks") or [])]
            bids = [(sr._f(b[0]), sr._f(b[1])) for b in (s.get("bids") or [])]
            if asks and bids:
                best = {"ts": st, "source": "recorder", "asks": asks, "bids": bids}
    if best:
        return best
    for r in journal:
        if (r.get("candidate") or {}).get("symbol") != symbol:
            continue
        rt, l2 = sr._f(r.get("ts_epoch")), r.get("l2") or {}
        if rt is None or l2.get("best_ask") is None or not (rt <= ts + 30) or abs(ts - rt) > cfg.book_max_age_s:
            continue
        if best is None or abs(ts - rt) < abs(ts - best["ts"]):
            n = int(l2.get("levels") or 10) or 10
            ba, bb = float(l2["best_ask"]), float(l2.get("best_bid") or l2["best_ask"] - cfg.tick)
            ad, bd = float(l2.get("ask_depth") or 0), float(l2.get("bid_depth") or 0)
            best = {"ts": rt, "source": "journal_l2 (uniform levels)",
                    "asks": [(round(ba + k * cfg.tick, 4), ad / n) for k in range(n)],
                    "bids": [(round(bb - k * cfg.tick, 4), bd / n) for k in range(n)]}
    return best


def walk(levels: Sequence[tuple], qty: float) -> Optional[float]:
    """Average fill price taking qty through the levels; None when the book cannot fill it."""
    left, cost = qty, 0.0
    for px, sz in levels:
        if px is None or not sz:
            continue
        take = min(left, sz)
        cost += take * px
        left -= take
        if left <= 1e-9:
            return cost / qty
    return None


def near_supply(levels: Sequence[tuple], pct: float) -> float:
    if not levels:
        return 0.0
    ref = levels[0][0]
    return sum(sz for px, sz in levels if px is not None and abs(px - ref) <= ref * pct / 100.0)


# ── simulate ──────────────────────────────────────────────────────────────────

def shares_for(price: float, sim: SimConfig) -> int:
    if sim.size_notional_usd and sim.size_notional_usd > 0 and price > 0:
        return max(1, int(sim.size_notional_usd // price))
    return int(sim.size_shares)


def _entries(symbol: str, review_sym: Mapping[str, Any], journal: Sequence[Mapping[str, Any]], source: str) -> list[dict]:
    if source == "improved_timing":
        return [{"ts": t["ts"], "ref": t["price"], "stop": t["stop"], "kind": t["kind"], "why": t["why"]}
                for t in review_sym.get("ideal_trades") or []]
    out = []
    for r in journal:
        c = r.get("candidate") or {}
        if c.get("symbol") != symbol or r.get("verdict") != "ALERT" or r.get("kind") not in sr.BUY_KINDS:
            continue
        ref = (r.get("l2") or {}).get("best_ask") or c.get("last")
        if ref is None:
            continue
        out.append({"ts": float(r["ts_epoch"]), "ref": float(ref), "stop": sr._f(c.get("stop_ref")),
                    "kind": r.get("kind"), "why": "engine decision"})
    return sorted(out, key=lambda e: e["ts"])


def simulate_symbol(symbol: str, *, bars: Sequence[Mapping[str, Any]], review_sym: Mapping[str, Any],
                    journal: Sequence[Mapping[str, Any]], source: str, sim: SimConfig, rcfg: "sr.ReviewConfig",
                    snaps: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    nb = sr.norm_bars(bars)
    if not nb:
        return []
    vw = sr.vwap_series(nb)
    trades, busy_until = [], 0.0
    for e in _entries(symbol, review_sym, journal, source):
        if e["ts"] < busy_until:
            continue
        idx = next((k for k, b in enumerate(nb) if b["ts"] <= e["ts"] < b["ts"] + 60), None)
        if idx is None:
            idx = next((k for k, b in enumerate(nb) if b["ts"] >= e["ts"]), None)
        if idx is None:
            continue
        book = book_at(e["ts"], symbol, journal, sim, snaps)
        size = shares_for(e["ref"], sim)
        rec: dict[str, Any] = {"symbol": symbol, "source": source, "kind": e["kind"], "entry_ts": e["ts"],
                               "ref_price": e["ref"], "size": size,
                               "book": None if not book else {"source": book["source"], "age_s": round(e["ts"] - book["ts"])}}
        if not book:
            trades.append({**rec, "status": "REFUSED", "reason": "no book within book_max_age_s"})
            continue
        supply = near_supply(book["asks"], sim.near_pct)
        if supply <= 0 or size > supply * sim.max_take_pct / 100.0:
            trades.append({**rec, "status": "REFUSED", "near_ask_supply": round(supply),
                           "reason": f"size {size} > {sim.max_take_pct:g}% of {supply:,.0f} sh near the ask"})
            continue
        # shift the recorded ask ladder to the entry reference when the book was taken earlier
        shift = e["ref"] - book["asks"][0][0] if source == "improved_timing" else 0.0
        half_spread = max(0.0, (book["asks"][0][0] - book["bids"][0][0]) / 2) if source == "improved_timing" else 0.0
        fill = walk([(px + shift + half_spread, sz) for px, sz in book["asks"]], size)
        if fill is None:
            trades.append({**rec, "status": "REFUSED", "reason": "book too thin to fill the size"})
            continue
        stop = e["stop"] if e["stop"] is not None else fill * (1 - sim.min_stop_pct / 100.0)
        stop = min(stop, fill * (1 - sim.min_stop_pct / 100.0)) if source == "engine" else stop
        exit_info = None
        for i in range(idx + 1, len(nb)):
            ev = sr.exit_evidence(nb, i, stop=stop, entry_idx=idx, vwap=vw, cfg=rcfg)
            if ev:
                exit_info = (i, *ev)
                break
        if exit_info is None:
            i = len(nb) - 1
            exit_info = (i, "open at end of data", nb[i]["c"])
        i, reason, px = exit_info
        spread = max(sim.tick, book["asks"][0][0] - book["bids"][0][0])
        bid_ladder = [(px - spread / 2 - k * sim.tick, sz) for k, (_, sz) in enumerate(book["bids"])]
        sell = walk(bid_ladder, size) or (px - spread / 2)
        fees = (sell * size * sim.sec_fee_rate + min(sim.taf_cap, sim.taf_per_share * size)
                + 2 * sim.commission)
        pnl = (sell - fill) * size - fees
        risk = (fill - stop) * size
        trades.append({**rec, "status": "FILLED", "fill": round(fill, 4), "slippage_per_share": round(fill - e["ref"], 4),
                       "near_ask_supply": round(supply), "stop": round(stop, 4), "exit_ts": nb[i]["ts"],
                       "exit_reason": reason, "exit_price": round(sell, 4), "fees": round(fees, 2),
                       "pnl": round(pnl, 2), "pnl_pct": round((sell - fill) / fill * 100, 3),
                       "r": round(pnl / risk, 2) if risk > 0 else None})
        busy_until = nb[i]["ts"] + 60
    return trades


def metrics(trades: Iterable[Mapping[str, Any]]) -> dict:
    t = list(trades)
    filled = [x for x in t if x.get("status") == "FILLED"]
    wins = [x for x in filled if x["pnl"] > 0]
    gross_w, gross_l = sum(x["pnl"] for x in wins), -sum(x["pnl"] for x in filled if x["pnl"] <= 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in sorted(filled, key=lambda y: y["entry_ts"]):
        eq += x["pnl"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    rs = [x["r"] for x in filled if x.get("r") is not None]
    return {"attempted": len(t), "filled": len(filled), "refused": len(t) - len(filled),
            "fill_feasibility": round(len(filled) / len(t), 3) if t else None,
            "win_rate": round(len(wins) / len(filled), 3) if filled else None,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else (None if not filled else float("inf")),
            "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
            "net_pnl": round(sum(x["pnl"] for x in filled), 2), "max_drawdown": round(dd, 2)}


def simulate_day(review: Mapping[str, Any], *, journal: Sequence[Mapping[str, Any]], cfg_raw: Mapping[str, Any],
                 bars_fn: Callable[[str], list], snaps_fn: Optional[Callable[[str], list]] = None) -> dict:
    sim = SimConfig.from_mapping((cfg_raw or {}).get("active_trader_auto_sim"))
    rcfg = sr.ReviewConfig.from_mapping((cfg_raw or {}).get("active_trader_review"))
    by_source: dict[str, list] = {"engine": [], "improved_timing": []}
    for s in review.get("symbols") or []:
        try:
            bars = bars_fn(s["symbol"]) or []
        except Exception:  # noqa: BLE001
            bars = []
        snaps = []
        if snaps_fn:
            try:
                snaps = snaps_fn(s["symbol"]) or []
            except Exception:  # noqa: BLE001
                snaps = []
        for src in by_source:
            by_source[src] += simulate_symbol(s["symbol"], bars=bars, review_sym=s, journal=journal, source=src,
                                              sim=sim, rcfg=rcfg, snaps=snaps)
    you = sum((x.get("pnl") or 0) for s in review.get("symbols") or [] for x in s["metrics"].get("you") or [])
    ideal_usd = sum(t["pnl_per_share"] * shares_for(t["price"], sim)
                    for s in review.get("symbols") or [] for t in s.get("ideal_trades") or [])
    return {"contract": CONTRACT, "day": review.get("day"), "mode": mode(cfg_raw), "size_shares": sim.size_shares if not sim.size_notional_usd else None,
            "size_notional_usd": sim.size_notional_usd or None,
            "improved_timing_label": "simulated at the session review's ideal entries (fast trigger loop not yet live)",
            "sources": {k: {"metrics": metrics(v), "trades": v} for k, v in by_source.items()},
            "compare": {"manual_pnl": round(you, 2), "engine_sim_pnl": metrics(by_source["engine"])["net_pnl"],
                        "improved_sim_pnl": metrics(by_source["improved_timing"])["net_pnl"],
                        "should_have_been_pnl": round(ideal_usd, 2)},
            "authority": {**ma.AUTHORITY, "simulation_only": True}}


def ledger_path(base: Optional[Path] = None) -> Path:
    return (base or ma.journal_dir()) / "auto_sim" / "ledger.jsonl"


def append_ledger(result: Mapping[str, Any], base: Optional[Path] = None) -> int:
    """Append each simulated trade once (id = day:symbol:source:entry_ts)."""
    p = ledger_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line)["id"])
            except (ValueError, KeyError):
                continue
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for src, blk in (result.get("sources") or {}).items():
            for t in blk.get("trades") or []:
                tid = f"{result.get('day')}:{t['symbol']}:{src}:{t['entry_ts']}"
                if tid in seen:
                    continue
                fh.write(json.dumps({"id": tid, "contract": CONTRACT, "day": result.get("day"), **t},
                                    default=str, sort_keys=True) + "\n")
                seen.add(tid)
                n += 1
    return n
