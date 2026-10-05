#!/usr/bin/env python3
"""Active Trader PREMARKET watch: heads-up alerts 06:00–09:29 ET for the momentum-scalp names.

Operator 2026-10-05: "why can't [it] pick up premarket". The RTH engine (scalp_shadow_logger +
momentum_alert_pass) only runs 09:30–11:55 because its RVOL profile and IEX bars are regular-hours
only, so a name that gaps and runs before the open (XNDU 10-05: premarket 04:01–09:29, 329 bars)
was invisible until 09:30. This pass looks at the same scalp names before the open and sends a
heads-up with the levels that matter at the bell:

  PM high  = the break level for the open
  PM VWAP  = the stop reference (holding above it = buyers in control)

Data (verified 2026-10-05, moomoo OpenD QUOTE context only — never a trade context, never unlock):
- 1-min extended-hours K-lines via SubType.K_1M subscribed with extended_time=True + get_cur_kline
  (subscription quota, 100 concurrent). request_history_kline is NOT used: it spends the 100
  symbols / 30 days history quota.
- prev close / float via get_market_snapshot; order book + tape via the existing MoomooSource.

kind = PREMARKET_WATCH, heads-up only: it never says "time to buy". Same journal, throttle style,
Telegram path and AT header as momentum_alerts. mode shadow (default) journals only; send also
delivers to Telegram — the operator decides, in the `active_trader_premarket:` config section.
ALERTS ONLY — no order path.

  python3 scripts/active_trader/premarket_watch.py                       # dry run, now
  python3 scripts/active_trader/premarket_watch.py --as-of 09:00         # replay today's bars to 09:00
  python3 scripts/active_trader/premarket_watch.py --apply               # journal (+ Telegram if send)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from active_trader import momentum_alerts as ma
except ModuleNotFoundError:
    from scripts.active_trader import momentum_alerts as ma

ET = ZoneInfo("America/New_York")
PREMARKET_WATCH = "PREMARKET_WATCH"
THROTTLE_FILE = "momentum_alerts_premarket_throttle.json"
HEARTBEAT_FILE = "momentum_alerts_premarket_heartbeat.json"


@dataclass(frozen=True)
class PremarketConfig:
    """Defaults are the proposal. `active_trader_premarket:` in config/scalp_signal_engine.yaml may
    override any field (operator-ratified changes only)."""
    mode: str = "shadow"                    # shadow = journal only; send = journal + Telegram
    window_start: str = "06:00"             # ET (operator 2026-10-05: from 6am)
    window_end: str = "09:29"               # ET, inclusive; the RTH engine takes over at 09:30
    max_symbols: int = 15                   # also bounds K_1M + book subscriptions
    lookback_hours: int = 20                # scan rows newer than this feed the universe
    float_mm_max: float = 30.0              # same scalp rule as the RTH universe
    price_min: float = 1.0
    price_max: float = 25.0
    min_gap_pct: float = 5.0                # last vs previous close
    min_pm_volume: float = 100_000.0        # shares traded since 04:00
    min_rotation_pct: float = 1.0           # PM volume as % of float
    vwap_hold_bars: int = 5                 # last N 1-min closes at/above PM VWAP
    max_spread_bps: float = 150.0           # premarket spreads are wider than RTH (80)
    min_depth_ratio: float = 1.0            # bid/ask depth over book_levels
    min_buy_ratio: float = 0.5              # tape buys / (buys + sells) when tape is available
    book_levels: int = 10
    tape_prints: int = 50
    supply_near_pct: float = 1.0            # ask shares within this % of the PM high
    max_book_age_s: float = 30.0
    max_quote_age_s: float = 120.0          # premarket prints are sparse
    cooldown_s: float = 1800.0              # 1 per symbol per 30 min
    max_alerts_per_hour: int = 12
    excluded_routes: tuple = field(default=("reject", "large_float_social_scout", "portfolio"))

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "PremarketConfig":
        if not raw:
            return cls()
        known = set(cls.__dataclass_fields__)
        kw = {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items() if k in known}
        cfg = cls(**kw)
        if cfg.mode not in ("shadow", "send"):
            raise ValueError(f"active_trader_premarket.mode must be shadow or send, got {cfg.mode!r}")
        return cfg


def load_config(path: Optional[Path] = None) -> PremarketConfig:
    try:
        import yaml
        raw = yaml.safe_load((path or ROOT / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8")) or {}
        return PremarketConfig.from_mapping(raw.get("active_trader_premarket"))
    except Exception:  # noqa: BLE001 — unreadable config → code defaults (shadow)
        return PremarketConfig()


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def in_window(now_et: datetime, cfg: PremarketConfig) -> bool:
    if now_et.weekday() >= 5:
        return False
    t = (now_et.hour, now_et.minute)
    return _hm(cfg.window_start) <= t <= _hm(cfg.window_end)


# ── features (pure) ───────────────────────────────────────────────────────────

def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def premarket_features(bars: Sequence[Mapping[str, Any]], *, prev_close: Optional[float],
                       float_mm: Optional[float], day: str, as_of_hm: str, vwap_hold_bars: int) -> dict:
    """Bars: [{time_key 'YYYY-MM-DD HH:MM:SS' (ET), open, high, low, close, volume}]. Only today's
    bars before 09:30 and at/before `as_of_hm` are used, so a replay never sees the future."""
    cut = f"{day} {as_of_hm}:59"
    pm = [b for b in bars if str(b.get("time_key", "")).startswith(day)
          and str(b["time_key"]) < f"{day} 09:30:00" and str(b["time_key"]) <= cut]
    out: dict[str, Any] = {"bars": len(pm)}
    if not pm:
        out["status"] = "NO_PREMARKET_BARS"
        return out
    vol = sum(_f(b.get("volume")) or 0.0 for b in pm)
    pv = sum(((_f(b.get("high")) or 0) + (_f(b.get("low")) or 0) + (_f(b.get("close")) or 0)) / 3.0
             * (_f(b.get("volume")) or 0.0) for b in pm)
    hi_bar = max(pm, key=lambda b: _f(b.get("high")) or -1.0)
    last = _f(pm[-1].get("close"))
    vwap = (pv / vol) if vol > 0 else None
    tail = [_f(b.get("close")) for b in pm[-max(1, vwap_hold_bars):]]
    out.update(
        status="OK", last=last, pm_volume=vol, pm_vwap=None if vwap is None else round(vwap, 4),
        pm_high=_f(hi_bar.get("high")), pm_high_at=str(hi_bar.get("time_key"))[11:16],
        pm_low=min(_f(b.get("low")) or 1e18 for b in pm), last_bar_at=str(pm[-1]["time_key"])[11:16],
        prev_close=prev_close, float_mm=float_mm,
        gap_pct=None if not (prev_close and last) else round((last - prev_close) / prev_close * 100, 2),
        rotation_pct=None if not float_mm else round(vol / (float_mm * 1e6) * 100, 2),
        above_vwap=bool(vwap is not None and all(c is not None and c >= vwap for c in tail)),
        dist_to_high_pct=None if not (last and _f(hi_bar.get("high"))) else
        round((_f(hi_bar.get("high")) - last) / last * 100, 2),
    )
    return out


def supply_near_level(asks: Sequence[tuple], level: Optional[float], *, near_pct: float) -> dict:
    """Ask shares stacked within near_pct% of a level (the PM high) and the biggest one there."""
    if not asks or level is None:
        return {}
    lo, hi = level * (1 - near_pct / 100.0), level * (1 + near_pct / 100.0)
    near = [(p, s) for p, s in asks if p is not None and s is not None and lo <= p <= hi]
    if not near:
        return {"level": level, "ask_shares_near_level": 0}
    wp, ws = max(near, key=lambda x: x[1])
    return {"level": level, "ask_shares_near_level": sum(s for _, s in near), "wall_price": wp, "wall_size": ws}


def decide(feat: Mapping[str, Any], l2: Mapping[str, Any], tape: Mapping[str, Any], *,
           cfg: PremarketConfig, quote_age_s: Optional[float]) -> dict:
    """ALERT (heads-up) or VETO with every reason. Pure."""
    reasons: list[str] = []
    if feat.get("status") != "OK":
        return {"verdict": ma.VETO, "veto_reasons": [feat.get("status") or "NO_PREMARKET_BARS"]}
    last = feat.get("last")
    if feat.get("float_mm") is None:
        reasons.append("FLOAT_UNKNOWN")
    elif feat["float_mm"] > cfg.float_mm_max:
        reasons.append("FLOAT_TOO_LARGE")
    if last is None or not (cfg.price_min <= last <= cfg.price_max):
        reasons.append("PRICE_OUT_OF_BAND")
    if feat.get("gap_pct") is None or feat["gap_pct"] < cfg.min_gap_pct:
        reasons.append("GAP_SMALL")
    if (feat.get("pm_volume") or 0) < cfg.min_pm_volume:
        reasons.append("PM_VOLUME_THIN")
    if feat.get("rotation_pct") is not None and feat["rotation_pct"] < cfg.min_rotation_pct:
        reasons.append("PM_ROTATION_LOW")
    if not feat.get("above_vwap"):
        reasons.append("BELOW_PM_VWAP")
    if quote_age_s is not None and quote_age_s > cfg.max_quote_age_s:
        reasons.append("QUOTE_STALE")
    if l2:
        reasons += [r for r in (l2.get("reasons") or []) if r != "SPREAD_WIDE"]
        sp = l2.get("spread_bps")
        if sp is not None and sp > cfg.max_spread_bps:
            reasons.append("SPREAD_WIDE")
        ratio = l2.get("depth_ratio")
        if l2.get("best_ask") is not None and (ratio is None or ratio < cfg.min_depth_ratio):
            reasons.append("L2_ASK_HEAVY")
    if tape and tape.get("buy_ratio") is not None and tape["buy_ratio"] < cfg.min_buy_ratio:
        reasons.append("TAPE_SELLERS")
    return {"verdict": ma.VETO if reasons else ma.ALERT, "veto_reasons": reasons}


def build_message(sym: str, feat: Mapping[str, Any], l2: Mapping[str, Any], tape: Mapping[str, Any],
                  near: Mapping[str, Any]) -> tuple[str, str]:
    """(title, body). First line is the fixed AT header the comms editor recognises."""
    f2 = ma._fmt
    title = (f"{ma.AT_SCALP_ALERT_HEADER}\n🔵 PREMARKET · {sym} · gapping {feat.get('gap_pct', 0):+.1f}% — "
             f"levels for the open")
    lines = [
        ma.NOT_AN_ORDER,
        f"last {f2(feat.get('last'))} · prev close {f2(feat.get('prev_close'))} · as of {feat.get('last_bar_at')} ET",
        f"PM high {f2(feat.get('pm_high'))} ({feat.get('pm_high_at')}) = break level · "
        f"PM VWAP {f2(feat.get('pm_vwap'))} = stop reference",
        f"PM volume {ma._u(feat.get('pm_volume', 0) / 1e3 if feat.get('pm_volume') else None, 0, 'k')} · "
        f"{ma._u(feat.get('rotation_pct'), 1, '%')} of float {ma._u(feat.get('float_mm'), 1, 'M')}",
    ]
    if l2.get("best_ask") is not None:
        lines.append(f"L2 {l2.get('source')} {l2.get('levels', 0)} lv: bid/ask {ma._u(l2.get('depth_ratio'), 2, 'x')} · "
                     f"spread {ma._u(l2.get('spread_bps'), 0, ' bps')}")
    if near.get("ask_shares_near_level") is not None:
        wall = (f" · wall {int(near['wall_size']):,} @ {f2(near.get('wall_price'))}" if near.get("wall_size") else "")
        lines.append(f"supply near PM high: {int(near['ask_shares_near_level']):,} sh{wall}")
    if tape.get("buy_ratio") is not None:
        lines.append(f"tape {tape.get('source')}: {ma._pct(tape.get('buy_ratio'))} buys of {tape.get('prints', 0)} prints")
    lines.append("Heads-up only: wait for the open; the regular engine confirms after 09:30.")
    base = ma._cc_base()
    if base:
        lines.append(f"Active Trader: {base}/v3/active-trader?tab=Alerts")
    return title, "\n".join(lines)


# ── data (moomoo quote context only) ──────────────────────────────────────────

class PremarketMoomoo:
    """Extended-hours bars + snapshot on top of the existing MoomooSource quote context."""

    def __init__(self, src=None, *, levels: int = 10, prints: int = 50):
        if src is None:
            from active_trader.momentum_alert_sources import MoomooSource
            src = MoomooSource(levels=levels, prints=prints)
        self.src = src
        self._kl: set[str] = set()

    def _ctx(self):
        return self.src._transport()._context()

    def bars(self, symbol: str) -> list[dict]:
        from futu import KLType, SubType
        code = f"US.{symbol.upper()}"
        if code not in self._kl:
            ret, msg = self._ctx().subscribe([code], [SubType.K_1M], subscribe_push=False, extended_time=True)
            if ret != 0:
                raise RuntimeError(f"K_1M subscribe refused for {symbol}: {str(msg)[:120]}")
            self._kl.add(code)
        ret, df = self._ctx().get_cur_kline(code, num=1000, ktype=KLType.K_1M)
        if ret != 0:
            raise RuntimeError(f"get_cur_kline failed for {symbol}: {str(df)[:120]}")
        return df[["time_key", "open", "high", "low", "close", "volume"]].to_dict("records")

    def snapshot(self, symbols: Sequence[str]) -> dict[str, dict]:
        ret, df = self._ctx().get_market_snapshot([f"US.{s.upper()}" for s in symbols])
        if ret != 0:
            return {}
        out = {}
        for r in df.to_dict("records"):
            # moomoo has no float field; outstanding_shares is circulating shares — a fallback only,
            # labelled as such (SDEV 10-05: scan float 1.8M vs moomoo outstanding 23.7M)
            fs = _f(r.get("outstanding_shares"))
            out[str(r["code"]).split(".", 1)[1]] = {
                "prev_close": _f(r.get("prev_close_price")),
                "float_mm": (fs / 1e6) if fs else None,
                "update_time": r.get("update_time"),
                "pre_price": _f(r.get("pre_price")),
            }
        return out

    def book(self, symbol: str, now: float):
        return self.src.book(symbol, now=now)

    def tape(self, symbol: str):
        return self.src.tape(symbol)

    def close(self) -> None:
        if self._kl:
            try:
                from futu import SubType
                self._ctx().unsubscribe(list(self._kl), [SubType.K_1M])
            except Exception:  # noqa: BLE001 — OpenD drops subscriptions with the connection anyway
                pass
        self.src.close()


def resolve_universe(conn, cfg: PremarketConfig) -> list[dict]:
    """Today's scalp names (finviz momentum scan + social scanner both write scalp_scan_results):
    not disqualified, route not excluded; latest known float (any age) carried along. SELECT only."""
    with conn.cursor() as cur:
        cur.execute(
            """WITH recent AS (
                 SELECT symbol, max(score) AS score
                 FROM scalp_scan_results
                 WHERE scanned_at > now() - make_interval(hours => %s) AND symbol IS NOT NULL
                   AND coalesce(disqualified, false) = false
                   AND (route IS NULL OR NOT (route = ANY(%s)))
                 GROUP BY symbol)
               SELECT r.symbol, r.score,
                      (SELECT s.float_mm FROM scalp_scan_results s WHERE s.symbol = r.symbol
                         AND s.float_mm IS NOT NULL ORDER BY s.scanned_at DESC LIMIT 1) AS float_mm
               FROM recent r ORDER BY r.score DESC NULLS LAST, r.symbol LIMIT %s""",
            [int(cfg.lookback_hours), list(cfg.excluded_routes), int(cfg.max_symbols) * 3])
        rows = cur.fetchall()
    return [{"symbol": str(r[0]).upper(), "score": r[1], "float_mm": _f(r[2])} for r in rows]


# ── pass ──────────────────────────────────────────────────────────────────────

def evaluate(universe: Sequence[Mapping[str, Any]], *, data, cfg: PremarketConfig, now: float, day: str,
             as_of_hm: str, live_book: bool, persist: bool, send_fn: Optional[Callable] = None,
             throttle_path: Optional[Path] = None) -> list[dict]:
    """One premarket pass. Floats from the scan, else the moomoo snapshot; unknown fails closed.
    live_book=False (replay) skips book/tape: they cannot be replayed and are not guessed."""
    # spread is judged against the premarket limit in decide(), not the RTH one
    acfg = ma.AlertConfig(book_levels=cfg.book_levels, max_book_age_s=cfg.max_book_age_s, max_spread_bps=1e9)
    syms = [u["symbol"] for u in universe][: int(cfg.max_symbols) * 3]
    snap = data.snapshot(syms) if syms else {}
    tpath = throttle_path or (ma.journal_dir() / THROTTLE_FILE)
    thr = ma.Throttle(ma.load_throttle_state(tpath), cfg)  # type: ignore[arg-type]
    rows: list[dict] = []
    checked = 0
    for u in universe:
        if checked >= cfg.max_symbols:
            break
        sym = u["symbol"]
        sn = snap.get(sym) or {}
        float_mm, float_src = ((u.get("float_mm"), "scan") if u.get("float_mm") is not None
                               else (sn.get("float_mm"), "moomoo_outstanding") if sn.get("float_mm") is not None
                               else (None, None))
        if float_mm is not None and float_mm > cfg.float_mm_max:
            continue                              # cheap pre-filter: no subscription spent
        checked += 1
        try:
            bars = data.bars(sym)
        except Exception as exc:  # noqa: BLE001
            bars = []
            err = type(exc).__name__
        else:
            err = None
        feat = premarket_features(bars, prev_close=sn.get("prev_close"), float_mm=float_mm, day=day,
                                  as_of_hm=as_of_hm, vwap_hold_bars=cfg.vwap_hold_bars)
        l2: dict = {}
        tape: dict = {}
        near: dict = {}
        if live_book and feat.get("status") == "OK":
            try:
                book = data.book(sym, now)
                l2 = ma.l2_evidence(book, now=now, cfg=acfg, source="moomoo")
                asks = [(_f(a[0]), _f(a[1])) for a in (book or {}).get("asks") or []][: cfg.book_levels]
                near = supply_near_level(asks, feat.get("pm_high"), near_pct=cfg.supply_near_pct)
            except Exception:  # noqa: BLE001
                l2 = {"source": "moomoo", "ok": False, "reasons": ["BOOK_MISSING"]}
            try:
                tape = ma.tape_evidence(data.tape(sym), now=now, cfg=ma.AlertConfig(tape_prints=cfg.tape_prints,
                                        max_tape_age_s=cfg.max_quote_age_s, min_tape_prints=1), source="moomoo")
            except Exception:  # noqa: BLE001
                tape = {}
        bar_age = None
        if feat.get("last_bar_at") and live_book:
            h, m = _hm(feat["last_bar_at"])
            bar_age = now - datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=ET, hour=h, minute=m).timestamp() - 60
        d = decide(feat, l2, tape, cfg=cfg, quote_age_s=bar_age)
        if err:
            d["veto_reasons"] = [f"BARS_{err}"] + d["veto_reasons"]
            d["verdict"] = ma.VETO
        if d["verdict"] == ma.ALERT:
            block = thr.check(sym, PREMARKET_WATCH, now)
            if block:
                d = {"verdict": ma.VETO, "veto_reasons": [block]}
        row = {
            "contract": ma.CONTRACT, "authority": ma.AUTHORITY, "run_id": f"{day}:pm:{int(now)}",
            "ts_epoch": now, "kind": PREMARKET_WATCH, "mode": cfg.mode, "verdict": d["verdict"],
            "veto_reasons": d["veto_reasons"], "replay_as_of": None if live_book else as_of_hm,
            # entry_ref = the break level, stop_ref = PM VWAP: the levels this heads-up is about
            "candidate": {"symbol": sym, "last": feat.get("last"), "entry_ref": feat.get("pm_high"),
                          "stop_ref": feat.get("pm_vwap"), "float_mm": float_mm, "session_date": day,
                          "float_source": float_src, "lane": "PREMARKET", "fsm_state": "PREMARKET"},
            "r_dollars": None, "premarket": feat, "l2": l2, "tape": tape, "supply_near_pm_high": near,
            "sent": False,
        }
        if d["verdict"] == ma.ALERT:
            title, body = build_message(sym, feat, l2, tape, near)
            row["message"] = {"title": title, "body": body}
            if send_fn is not None and cfg.mode == "send":
                try:
                    res = send_fn(alert_type="at_scalp_premarket", title=title, body=body)
                except Exception as exc:  # noqa: BLE001
                    res = {"sent": False, "error": type(exc).__name__}
                row["send_result"], row["sent"] = res, bool(res.get("sent"))
            if persist:
                thr.record(sym, PREMARKET_WATCH, now)
        if persist:
            ma.append_journal(row)
        rows.append(row)
    if persist:
        ma.save_throttle_state(thr.state(), tpath)
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Active Trader premarket watch (heads-up only)")
    ap.add_argument("--apply", action="store_true", help="journal (and send when mode=send)")
    ap.add_argument("--as-of", help="replay today's bars up to HH:MM ET (dry run only; no book/tape)")
    ap.add_argument("--symbols", help="comma list instead of the scan universe")
    a = ap.parse_args(argv)
    if a.apply and a.as_of:
        ap.error("--as-of is a replay; it never journals or sends")
    if (ma.journal_dir() / "PREMARKET_DISABLED").exists():
        print("HALT: PREMARKET_DISABLED present"); return 0
    cfg = load_config()
    now = time.time()
    now_et = datetime.fromtimestamp(now, ET)
    day = now_et.date().isoformat()
    as_of = a.as_of or now_et.strftime("%H:%M")
    if not a.as_of and not in_window(now_et, cfg):
        print(f"outside premarket window {cfg.window_start}-{cfg.window_end} ET; nothing to do"); return 0
    if a.symbols:
        universe = [{"symbol": s.strip().upper(), "float_mm": None} for s in a.symbols.split(",") if s.strip()]
    else:
        from db_adapter import get_connection  # type: ignore
        conn = get_connection()
        try:
            universe = resolve_universe(conn, cfg)
        finally:
            conn.close()
    data = PremarketMoomoo(levels=cfg.book_levels, prints=cfg.tape_prints)
    try:
        rows = evaluate(universe, data=data, cfg=cfg, now=now, day=day, as_of_hm=as_of,
                        live_book=not a.as_of, persist=a.apply,
                        send_fn=ma.telegram_send if (a.apply and cfg.mode == "send") else None)
    finally:
        data.close()
    for r in rows:
        f = r["premarket"]
        print(f"{r['candidate']['symbol']:6} {r['verdict']:5} gap={f.get('gap_pct')}% pmvol={f.get('pm_volume')} "
              f"rot={f.get('rotation_pct')}% pmH={f.get('pm_high')}@{f.get('pm_high_at')} vwap={f.get('pm_vwap')} "
              f"last={f.get('last')} above_vwap={f.get('above_vwap')} {','.join(r['veto_reasons'])}")
        if r.get("message"):
            print("  " + (r["message"]["title"] + "\n" + r["message"]["body"]).replace("\n", "\n  "))
    summary = {"as_of": as_of, "mode": cfg.mode, "applied": a.apply, "universe": len(universe),
               "evaluated": len(rows), "alerts": sum(r["verdict"] == ma.ALERT for r in rows),
               "sent": sum(bool(r.get("sent")) for r in rows)}
    print(json.dumps(summary))
    if a.apply:
        try:
            p = ma.journal_dir() / HEARTBEAT_FILE
            p.write_text(json.dumps({"ts_epoch": now, **summary}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
