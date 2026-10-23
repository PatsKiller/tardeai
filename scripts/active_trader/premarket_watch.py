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
  python3 scripts/active_trader/premarket_watch.py --apply --loop        # 1-minute supervisor until window end

1-MINUTE CADENCE + THREADED LIFECYCLE (operator 2026-10-23: "I agree for every minute, because on manually, I do a
1 minute candle check"; "this should just be critiqued at least the top 20"). `cadence_mode` in
`active_trader_premarket:`:
  legacy  today's 5-minute pass exactly: PREMARKET_WATCH heads-up, 30-min per-symbol throttle, nothing new.
  shadow  (default) the legacy pass still runs on its 5-minute grid and is still the only sender; beside it, on every
          closed 1-minute candle, the FOCUS list (lib/scalp_focus: top N of the hot-list pool, hysteresis) is
          re-ranked and each focus name's lifecycle state (WATCH -> APPROACHING -> ARMED -> TRIGGERED -> STAND DOWN,
          EXTENDED, PULLBACK_ZONE, TRIGGER_CANCELLED) is logged to the unified threaded-alert ledger (#1971) as
          SHADOW_LOGGED, plus momentum_alerts_premarket_1m.jsonl. Nothing new is sent.
  live    the threaded lifecycle replaces the throttled heads-up: each state change is sent at once as a reply in
          the symbol's thread (same state never re-sent, hard cap max_msgs_per_symbol_hour); the legacy pass is
          journaled but not sent; a failed threaded send falls back to the legacy transport.
`--loop` ticks settle_s seconds after every minute boundary on the CLOSED candle and exits at window end; an
in-process lock (premarket_watch.run.lock) plus the cron line's flock mean two runs never overlap.
scripts/premarket_cadence_compare.py --day D lists, per symbol, when the old and the new path alerted.
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
try:
    from scripts.lib import momentum_setup_evidence as mse
except ModuleNotFoundError:  # pragma: no cover
    from lib import momentum_setup_evidence as mse  # type: ignore

ET = ZoneInfo("America/New_York")
PREMARKET_WATCH = "PREMARKET_WATCH"
THROTTLE_FILE = "momentum_alerts_premarket_throttle.json"
HEARTBEAT_FILE = "momentum_alerts_premarket_heartbeat.json"
EVIDENCE_GATES = ("downgrade", "hold", "off")
VALIDATED, UNVALIDATED = "VALIDATED", "UNVALIDATED"
CADENCE_MODES = ("legacy", "shadow", "live")
CADENCE_JOURNAL = "momentum_alerts_premarket_1m.jsonl"
LIFECYCLE_FILE = "momentum_alerts_premarket_lifecycle.json"
RUN_LOCK_FILE = "premarket_watch.run.lock"
ORIGIN_1M = "active_trader_premarket"


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
    # Momentum-evidence gate (operator 2026-10-14, GLND: "why does this even fire without validated
    # momentum?"). An ALERT ships as a normal heads-up only when the shared same-symbol evidence
    # (scripts/lib/momentum_setup_evidence.same_symbol_evidence) is CURRENT, unconflicted and proves at
    # least evidence_min_passed of its five source facts. Otherwise: downgrade = send an explicit
    # UNVALIDATED heads-up with no CIO chrome; hold = journal only, never sent; off = the pre-10-14 path.
    evidence_gate: str = "downgrade"
    evidence_min_passed: int = 5
    # 1-minute cadence + threaded lifecycle (operator 2026-10-23). Thresholds are v1 priors, operator-ratified.
    cadence_mode: str = "shadow"            # legacy | shadow | live
    settle_s: float = 6.0                   # tick this long after each minute boundary (recorder polls every 5 s)
    legacy_grid_min: int = 5                # the legacy pass runs on minutes divisible by this in --loop
    approach_pct: float = 3.0               # close within this % of the PM high -> APPROACHING
    arm_pct: float = 0.75                   # within this % and volume accelerating -> ARMED
    arm_vol_mult: float = 1.2               # closed-bar volume vs session median 1-min volume
    trigger_vol_mult: float = 1.5           # break of the prior PM high on CLOSE needs this volume multiple
    extended_pct: float = 5.0               # close this % above the break level -> EXTENDED (don't chase)
    pullback_pct: float = 2.0               # back within this % of the break level, above VWAP -> PULLBACK_ZONE
    stand_down_vwap_bars: int = 2           # consecutive closes below PM VWAP -> STAND DOWN
    max_msgs_per_symbol_hour: int = 6       # hard cap per thread per trailing hour
    reopen_after_min: float = 10.0          # after a STAND DOWN, no new pre-trigger state for this long
    direct_book_max: int = 8                # focus names whose book/tape may be read directly when the recorder has none

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "PremarketConfig":
        if not raw:
            return cls()
        known = set(cls.__dataclass_fields__)
        kw = {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items() if k in known}
        cfg = cls(**kw)
        if cfg.mode not in ("shadow", "send"):
            raise ValueError(f"active_trader_premarket.mode must be shadow or send, got {cfg.mode!r}")
        if cfg.cadence_mode not in CADENCE_MODES:
            raise ValueError(f"active_trader_premarket.cadence_mode must be one of {CADENCE_MODES}, "
                             f"got {cfg.cadence_mode!r}")
        if cfg.evidence_gate not in EVIDENCE_GATES:
            raise ValueError(f"active_trader_premarket.evidence_gate must be one of {EVIDENCE_GATES}, "
                             f"got {cfg.evidence_gate!r}")
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


def momentum_gate(sym: str, snapshot: Any, *, cfg: PremarketConfig, now: float) -> dict:
    """Is there validated same-symbol momentum evidence for this heads-up? Pure over the snapshot.

    Reads the shared candidate snapshot through the evidence library (never re-derives it). VALIDATED
    only when the library returns CURRENT evidence with passed_count >= cfg.evidence_min_passed;
    every other state (UNKNOWN, CONFLICT, AMBIGUOUS, SNAPSHOT_UNAVAILABLE, too few facts) is UNVALIDATED.
    """
    found = mse.same_symbol_evidence(sym, snapshot, now=datetime.fromtimestamp(now, ET))
    passed = found.get("passed_count")
    ok = found["status"] == "CURRENT" and isinstance(passed, int) and passed >= int(cfg.evidence_min_passed)
    return {
        "gate": cfg.evidence_gate, "result": VALIDATED if ok else UNVALIDATED, "status": found["status"],
        "conflicts": found.get("conflicts") or [], "passed_count": passed,
        "required_count": found.get("required_count"), "min_passed": int(cfg.evidence_min_passed),
        "source": found.get("source"), "observations": found.get("observations") or {},
        "evidence": found.get("evidence"),
    }


def _gate_reason(gate: Mapping[str, Any]) -> str:
    status = gate.get("status") or "UNKNOWN"
    if status == "CONFLICT":
        return f"CONFLICTED ({', '.join(gate.get('conflicts') or [])})"
    if status == "CURRENT":
        return f"{gate.get('passed_count')}/{gate.get('required_count')} source facts (needs {gate.get('min_passed')})"
    return status


def build_message(sym: str, feat: Mapping[str, Any], l2: Mapping[str, Any], tape: Mapping[str, Any],
                  near: Mapping[str, Any], gate: Optional[Mapping[str, Any]] = None, *,
                  day: Optional[str] = None) -> tuple[str, str]:
    """(title, body). First line is the fixed AT header the comms editor recognises.

    gate None or VALIDATED: the normal heads-up (the transport adds the evidence footer). UNVALIDATED:
    the title says so, the second body line is the library's UNVALIDATED line with the reason, and the
    evidence line is written here, so the CIO conviction/stance line and a second footer are not added."""
    f2 = ma._fmt
    unvalidated = bool(gate) and gate.get("result") == UNVALIDATED
    title = (f"{ma.AT_SCALP_ALERT_HEADER}\n🔵 PREMARKET · {sym} · gapping {feat.get('gap_pct', 0):+.1f}% — "
             + ("UNVALIDATED heads-up, levels only" if unvalidated else "levels for the open"))
    lines = [ma.NOT_AN_ORDER]
    if unvalidated:
        lines.append(f"{mse.UNVALIDATED_MARK} same-symbol momentum evidence {_gate_reason(gate)}. "
                     "Not a validated setup; no CIO view attached.")
    lines += [
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
    # 2026-10-16: an explicit catalyst line (Hermes scalp research via the data broker, or "none found (why)");
    # include_catalyst=False below and the transport appendix both defer to it.
    lines.append(ma.catalyst_line(sym, None, day or datetime.now(ET).date().isoformat()))
    lines.append("Heads-up only: wait for the open; the regular engine confirms after 09:30.")
    base = ma._cc_base()
    if base:
        lines.append(f"Active Trader: {base}/v3/active-trader?tab=Alerts")
    if unvalidated:
        lines.append(mse.format_notification_evidence(gate.get("evidence"), include_catalyst=False))
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
                "pre_volume": _f(r.get("pre_volume")),
                "last_price": _f(r.get("last_price")),
            }
        return out

    def bars_start(self, symbol: str) -> list[dict]:
        """Today's 1-min bars normalized to bar START ({s,o,h,l,c,v}; the forming bar included -- callers keep
        only CLOSED bars). Same quote-context subscription the recorder uses (MoomooSource.bars_1m)."""
        return self.src.bars_1m(symbol)

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
                         AND s.float_mm IS NOT NULL ORDER BY s.scanned_at DESC LIMIT 1) AS float_mm,
                      (SELECT s.rvol FROM scalp_scan_results s WHERE s.symbol = r.symbol
                         AND s.rvol IS NOT NULL ORDER BY s.scanned_at DESC LIMIT 1) AS rvol
               FROM recent r ORDER BY r.score DESC NULLS LAST, r.symbol LIMIT %s""",
            [int(cfg.lookback_hours), list(cfg.excluded_routes), int(cfg.max_symbols) * 3])
        rows = cur.fetchall()
    return [{"symbol": str(r[0]).upper(), "score": r[1], "float_mm": _f(r[2]),
             "rvol": _f(r[3]) if len(r) > 3 else None} for r in rows]


def resolve_pool(conn, cfg: PremarketConfig) -> list[dict]:
    """The FOCUS pool: the hot list's scalp names (same rules as resolve_universe) without the legacy
    max_symbols x 3 cut -- the focus list ranks the whole pool and keeps the top N. SELECT only."""
    big = PremarketConfig.from_mapping({**{k: getattr(cfg, k) for k in cfg.__dataclass_fields__},
                                        "max_symbols": 200})
    return resolve_universe(conn, big)


# ── pass ──────────────────────────────────────────────────────────────────────

def _send_scoped(send_fn: Callable, sym: str, *, title: str, body: str) -> dict:
    """Send with the comms editor's primary symbols bound to this heads-up's one ticker, so footer links,
    ids and the transport's evidence lookup are about `sym` only — never a word in the chrome that happens
    to resolve to another issuer (2026-10-14: RMAX links on a GLND alert). Binding is best-effort."""
    token = reset = None
    try:
        try:
            from scripts.lib.comms_editor import reset_primary_symbols, set_primary_symbols
        except ImportError:  # pragma: no cover
            from lib.comms_editor import reset_primary_symbols, set_primary_symbols  # type: ignore
        token, reset = set_primary_symbols([sym]), reset_primary_symbols
    except Exception:  # noqa: BLE001 — scoping is chrome hygiene; the alert still goes
        token = None
    try:
        return send_fn(alert_type="at_scalp_premarket", title=title, body=body)
    finally:
        if token is not None and reset is not None:
            reset(token)


def evaluate(universe: Sequence[Mapping[str, Any]], *, data, cfg: PremarketConfig, now: float, day: str,
             as_of_hm: str, live_book: bool, persist: bool, send_fn: Optional[Callable] = None,
             throttle_path: Optional[Path] = None, evidence_loader: Optional[Callable] = None) -> list[dict]:
    """One premarket pass. Floats from the scan, else the moomoo snapshot; unknown fails closed.
    live_book=False (replay) skips book/tape: they cannot be replayed and are not guessed.
    evidence_loader: () -> shared candidate snapshot, read at most once per pass (first ALERT). None
    means no evidence was read: the gate sees SNAPSHOT_UNAVAILABLE and fails closed to UNVALIDATED."""
    # spread is judged against the premarket limit in decide(), not the RTH one
    acfg = ma.AlertConfig(book_levels=cfg.book_levels, max_book_age_s=cfg.max_book_age_s, max_spread_bps=1e9)
    syms = [u["symbol"] for u in universe][: int(cfg.max_symbols) * 3]
    snap = data.snapshot(syms) if syms else {}
    tpath = throttle_path or (ma.journal_dir() / THROTTLE_FILE)
    thr = ma.Throttle(ma.load_throttle_state(tpath), cfg)  # type: ignore[arg-type]
    rows: list[dict] = []
    checked = 0
    snapshot_box: dict[str, Any] = {}

    def evidence_snapshot() -> Any:
        if "v" not in snapshot_box:
            try:
                snapshot_box["v"] = evidence_loader() if evidence_loader is not None else None
            except Exception:  # noqa: BLE001 — unreadable evidence is UNKNOWN evidence, never a pass
                snapshot_box["v"] = None
        return snapshot_box["v"]
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
        gate: Optional[dict] = None
        if d["verdict"] == ma.ALERT and cfg.evidence_gate != "off":
            gate = momentum_gate(sym, evidence_snapshot(), cfg=cfg, now=now)
            if gate["result"] == UNVALIDATED and cfg.evidence_gate == "hold":
                d = {"verdict": ma.VETO, "veto_reasons": [f"MOMENTUM_EVIDENCE_{gate['status']}"]}
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
        if gate is not None:
            row["momentum_evidence"] = {k: v for k, v in gate.items() if k != "evidence"}
        if d["verdict"] == ma.ALERT:
            title, body = build_message(sym, feat, l2, tape, near, gate, day=day)
            row["message"] = {"title": title, "body": body}
            if send_fn is not None and cfg.mode == "send":
                try:
                    res = _send_scoped(send_fn, sym, title=title, body=body)
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


# ── 1-minute cadence: closed-candle features, lifecycle, focus, threading (operator 2026-10-23) ───────────────

PRE_TRIGGER = ("WATCH", "APPROACHING", "ARMED")
POST_TRIGGER = ("TRIGGERED", "EXTENDED", "PULLBACK_ZONE", "TRIGGER_CANCELLED")
ACTIVE_STATES = PRE_TRIGGER + POST_TRIGGER
HARD_FAIL = frozenset({"PRICE_OUT_OF_BAND", "GAP_SMALL", "FLOAT_TOO_LARGE", "FLOAT_UNKNOWN", "NO_PREMARKET_BARS"})


def minute_boundary(now: float) -> float:
    """The most recent minute boundary at or before `now` (epoch seconds): the close of the last 1-min candle."""
    return float(int(now // 60) * 60)


def next_tick(now: float, settle_s: float) -> float:
    """When the next tick fires: settle_s after the next minute boundary (or this one, if still ahead)."""
    b = minute_boundary(now)
    t = b + float(settle_s)
    return t if t > now else b + 60.0 + float(settle_s)


def closed_bars(rows: Sequence[Mapping[str, Any]], *, boundary: float, day: str) -> list[dict]:
    """Start-normalized bars ({s|t, o, h, l, c, v}) of `day`, premarket only, CLOSED at `boundary` (start + 60 <=
    boundary). The forming bar is never used: the operator's manual method is the completed 1-minute candle."""
    start_of_day = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=ET).timestamp()
    rth = datetime.fromisoformat(f"{day}T09:30:00").replace(tzinfo=ET).timestamp()
    out = []
    for r in rows or []:
        t = _f(r.get("s") if r.get("s") is not None else r.get("t"))
        if t is None or t < start_of_day or t >= rth or t + 60.0 > boundary:
            continue
        out.append({"t": t, "o": _f(r.get("o")), "h": _f(r.get("h")), "l": _f(r.get("l")), "c": _f(r.get("c")),
                    "v": _f(r.get("v")) or 0.0})
    out.sort(key=lambda b: b["t"])
    return out


def candle_features(bars: Sequence[Mapping[str, Any]], *, prev_close: Optional[float], float_mm: Optional[float],
                    boundary: float, vwap_hold_bars: int) -> dict:
    """Features of the last CLOSED 1-minute candle and the premarket session up to it. Pure.

    prior_high is the PM high BEFORE the last candle (the break level that candle is judged against)."""
    out: dict[str, Any] = {"bars": len(bars), "boundary_epoch": boundary}
    if not bars:
        out["status"] = "NO_PREMARKET_BARS"
        return out
    last = bars[-1]
    vol = sum(b["v"] or 0.0 for b in bars)
    pv = sum(((b["h"] or 0) + (b["l"] or 0) + (b["c"] or 0)) / 3.0 * (b["v"] or 0.0) for b in bars)
    vwap = (pv / vol) if vol > 0 else None
    highs = [b["h"] for b in bars if b["h"] is not None]
    prior = [b["h"] for b in bars[:-1] if b["h"] is not None]
    pm_high = max(highs) if highs else None
    hi_bar = max((b for b in bars if b["h"] is not None), key=lambda b: (b["h"], b["t"]), default=None)
    vols = sorted(b["v"] for b in bars[:-1] if (b["v"] or 0) > 0)
    med = vols[len(vols) // 2] if vols else None
    close = last["c"]
    tail = [b["c"] for b in bars[-max(1, vwap_hold_bars):]]
    below = 0
    for b in reversed(bars):
        if vwap is not None and b["c"] is not None and b["c"] < vwap:
            below += 1
        else:
            break
    out.update(
        status="OK", last=close, candle_at=datetime.fromtimestamp(last["t"], ET).strftime("%H:%M"),
        candle_open=last["o"], candle_high=last["h"], candle_low=last["l"], candle_volume=last["v"],
        candle_green=bool(close is not None and last["o"] is not None and close > last["o"]),
        candle_age_s=round(boundary - (last["t"] + 60.0), 1),
        pm_volume=vol, pm_vwap=None if vwap is None else round(vwap, 4), pm_high=pm_high,
        pm_high_at=datetime.fromtimestamp(hi_bar["t"], ET).strftime("%H:%M") if hi_bar else None,
        prior_high=max(prior) if prior else None, prev_close=prev_close, float_mm=float_mm,
        gap_pct=None if not (prev_close and close) else round((close - prev_close) / prev_close * 100, 2),
        rotation_pct=None if not float_mm else round(vol / (float_mm * 1e6) * 100, 2),
        above_vwap=bool(vwap is not None and all(c is not None and c >= vwap for c in tail)),
        below_vwap_bars=below,
        vol_accel=None if not med else round((last["v"] or 0.0) / med, 2),
        dist_to_high_pct=None if not (close and pm_high) else round((pm_high - close) / close * 100, 2),
        minutes_since_high=None if not hi_bar else round((last["t"] - hi_bar["t"]) / 60.0, 1),
    )
    return out


def classify(feat: Mapping[str, Any], gates: Mapping[str, Any], memory: Optional[Mapping[str, Any]], *,
             cfg: PremarketConfig, l2: Optional[Mapping[str, Any]] = None) -> tuple[Optional[str], str, dict]:
    """(state, why, new memory) for one focus name on one closed candle. Pure.

    memory: {"state", "break_level", "since"} from the previous candle. Pre-trigger states only escalate
    (WATCH < APPROACHING < ARMED) until a STAND DOWN, so a name hovering near a threshold does not chatter."""
    mem = dict(memory or {})
    prev = mem.get("state")
    reasons = list(gates.get("veto_reasons") or [])
    if feat.get("status") != "OK":
        return (("STAND_DOWN", "no premarket bars", {**mem, "state": "STAND_DOWN"}) if prev in ACTIVE_STATES
                else (None, "no premarket bars", mem))
    close, prior_high = feat.get("last"), feat.get("prior_high")
    hard = [r for r in reasons if r in HARD_FAIL]
    vwap_lost = int(feat.get("below_vwap_bars") or 0) >= int(cfg.stand_down_vwap_bars)
    if prev in ACTIVE_STATES and (hard or vwap_lost):
        why = (f"{int(feat.get('below_vwap_bars') or 0)} closes below PM VWAP {_fmt_n(feat.get('pm_vwap'))}"
               if vwap_lost else ", ".join(hard))
        if prev == "WATCH":
            # a plain heads-up that fades is dropped quietly: a STAND DOWN message is for a name that was getting
            # close (replay 2026-10-23: WATCH <-> STAND DOWN chatter on names oscillating around PM VWAP)
            return None, f"watch dropped: {why}", {"emitted_state": mem.get("emitted_state")}
        return "STAND_DOWN", why, {"state": "STAND_DOWN", "since": feat.get("candle_at"),
                                   "stood_down_at": feat.get("boundary_epoch"),
                                   "emitted_state": mem.get("emitted_state")}
    accel = feat.get("vol_accel")
    breakout = bool(prior_high and close and close > prior_high and feat.get("candle_green")
                    and accel is not None and accel >= cfg.trigger_vol_mult)
    if prev in POST_TRIGGER:
        bl = _f(mem.get("break_level")) or prior_high
        if bl and close is not None:
            if close >= bl * (1 + cfg.extended_pct / 100.0) and prev != "EXTENDED":
                return "EXTENDED", f"close {_fmt_n(close)} is {((close / bl) - 1) * 100:.1f}% above the break " \
                                   f"{_fmt_n(bl)}: don't chase", {**mem, "state": "EXTENDED"}
            if prev == "TRIGGERED" and close < bl:
                return "TRIGGER_CANCELLED", f"closed back below the break {_fmt_n(bl)}", \
                    {**mem, "state": "TRIGGER_CANCELLED"}
            if prev == "EXTENDED" and abs(close / bl - 1) * 100 <= cfg.pullback_pct and feat.get("above_vwap"):
                return "PULLBACK_ZONE", f"back to {_fmt_n(close)} near the break {_fmt_n(bl)}, above VWAP", \
                    {**mem, "state": "PULLBACK_ZONE"}
            if prev == "TRIGGER_CANCELLED" and breakout:
                return "TRIGGERED", f"re-broke {_fmt_n(prior_high)} on close, volume {accel:.1f}x", \
                    {"state": "TRIGGERED", "break_level": prior_high, "since": feat.get("candle_at")}
        return prev, "unchanged", mem
    ok = gates.get("verdict") == ma.ALERT
    if prev == "STAND_DOWN" and mem.get("stood_down_at") is not None and feat.get("boundary_epoch") is not None \
            and float(feat["boundary_epoch"]) - float(mem["stood_down_at"]) < cfg.reopen_after_min * 60.0:
        return "STAND_DOWN", "cooling off after stand-down", mem
    if not ok:
        if prev in PRE_TRIGGER and not hard:
            return prev, "soft veto: " + ", ".join(reasons), mem       # e.g. a wide spread for a minute
        return None, ", ".join(reasons) or "gates not met", ({} if prev == "STAND_DOWN" else mem)
    if breakout:
        return "TRIGGERED", f"closed {_fmt_n(close)} above the PM high {_fmt_n(prior_high)}, volume {accel:.1f}x", \
            {"state": "TRIGGERED", "break_level": prior_high, "since": feat.get("candle_at")}
    dist = feat.get("dist_to_high_pct")
    ask_heavy = bool(l2 and l2.get("depth_ratio") is not None and l2.get("best_ask") is not None
                     and l2["depth_ratio"] < cfg.min_depth_ratio)
    if dist is not None and dist <= cfg.arm_pct and accel is not None and accel >= cfg.arm_vol_mult and not ask_heavy:
        new, why = "ARMED", f"{dist:.2f}% under the PM high {_fmt_n(feat.get('pm_high'))}, volume {accel:.1f}x"
    elif dist is not None and dist <= cfg.approach_pct:
        new, why = "APPROACHING", f"{dist:.2f}% under the PM high {_fmt_n(feat.get('pm_high'))}"
    else:
        new, why = "WATCH", f"gapping {feat.get('gap_pct') or 0:+.1f}%, holding PM VWAP {_fmt_n(feat.get('pm_vwap'))}"
    if prev in PRE_TRIGGER and PRE_TRIGGER.index(prev) > PRE_TRIGGER.index(new):
        return prev, f"holding {prev} (now {new})", mem
    return new, why, {"state": new, "since": feat.get("candle_at") if new != prev else mem.get("since")}


def _fmt_n(v: Any) -> str:
    x = _f(v)
    return "—" if x is None else f"{x:,.2f}"


def live_facts(feat: Mapping[str, Any], l2: Mapping[str, Any], tape: Mapping[str, Any], *, rvol: Optional[float],
               cfg: PremarketConfig, book_src: Optional[str], book_age: Optional[float]) -> list[dict]:
    """Facts measured on the closed candle / book / tape for the shared evidence block (MomentumEvidenceBlock@v1)."""
    facts: list[dict] = []
    gap = feat.get("gap_pct")
    facts.append({"id": "gap", "label": "Gap", "driver": True,
                  "status": "UNKNOWN" if gap is None else "PASSED" if abs(gap) >= cfg.min_gap_pct else "FAILED",
                  "detail": None if gap is None else f"{gap:+.1f}%"})
    facts.append({"id": "rvol", "label": "RVOL", "driver": True,
                  "status": "UNKNOWN" if rvol is None else "PASSED" if rvol >= 5 else "FAILED",
                  "detail": "unknown (scan)" if rvol is None else f"{rvol:.1f}x (scan)"})
    acc = feat.get("vol_accel")
    facts.append({"id": "volume_1m", "label": "1-min volume", "driver": True,
                  "status": "UNKNOWN" if acc is None else "PASSED" if acc >= cfg.arm_vol_mult else "FAILED",
                  "detail": None if acc is None else f"{acc:.1f}x session median"})
    facts.append({"id": "vwap", "label": "Above PM VWAP", "driver": False,
                  "status": "PASSED" if feat.get("above_vwap") else "FAILED",
                  "detail": _fmt_n(feat.get("pm_vwap"))})
    if l2.get("best_ask") is not None:
        r = l2.get("depth_ratio")
        facts.append({"id": "book", "label": "Book bid/ask", "driver": True,
                      "status": "PASSED" if r is not None and r >= cfg.min_depth_ratio else "FAILED",
                      "detail": f"{_u(r, 2, 'x')} ({book_src}, {_u(book_age, 0, 's')} old)"})
    else:
        facts.append({"id": "book", "label": "Book", "driver": False, "status": "UNKNOWN",
                      "detail": f"none ({book_src or 'not recorded'})"})
    br = tape.get("buy_ratio") if tape else None
    facts.append({"id": "tape", "label": "Tape buys", "driver": True,
                  "status": "UNKNOWN" if br is None else "PASSED" if br >= cfg.min_buy_ratio else "FAILED",
                  "detail": "none" if br is None else f"{br * 100:.0f}% of {tape.get('prints', 0)} prints"})
    return facts


def _u(v: Any, nd: int, unit: str) -> str:
    x = _f(v)
    return "—" if x is None else f"{x:.{nd}f}{unit}"


def load_lifecycle(path: Path, day: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc.get(day) or {} if isinstance(doc, dict) else {}


def save_lifecycle(path: Path, day: str, memory: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({day: dict(memory)}, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


class RecorderReader:
    """Book / tape / bars from the microstructure recorder's store (data broker, read-only), each with its age."""

    def __init__(self, micro=None):
        if micro is None:
            try:
                from lib.data_broker import microstructure as micro  # type: ignore
            except ModuleNotFoundError:  # pragma: no cover
                from scripts.lib.data_broker import microstructure as micro  # type: ignore
        self.m = micro

    def bars(self, day: str, sym: str, *, boundary: float, now: float, max_age_s: float) -> Optional[list[dict]]:
        """Closed bars only when the store was published AFTER the boundary (so the last candle is final)."""
        env = self.m.bars(day, sym, now=now, max_age_s=max_age_s)
        if env.get("status") != "ok" or float(env.get("as_of") or 0) < boundary:
            return None
        return list(env.get("closed") or [])

    def book(self, day: str, sym: str, *, now: float, max_age_s: float) -> Optional[dict]:
        return self.m.book(day, sym, now=now, max_age_s=max_age_s)

    def tape(self, day: str, sym: str, *, now: float) -> list[dict]:
        return self.m.tape(day, sym, now=now)


def _cadence(cfg: PremarketConfig, unified_mode: str) -> dict:
    """What each path does this tick. The legacy path is the sender unless cadence is live (and send is allowed)."""
    new_on = cfg.cadence_mode in ("shadow", "live")
    live = cfg.cadence_mode == "live" and cfg.mode == "send" and unified_mode != "off"
    return {"cadence_mode": cfg.cadence_mode, "new_path": new_on, "emit": new_on and unified_mode != "off",
            "emit_mode": "live" if live else "shadow", "legacy_sends": not live}


def evaluate_1m(pool: Sequence[Mapping[str, Any]], *, data, cfg: PremarketConfig, fcfg=None, boundary: float,
                now: float, day: str, persist: bool, recorder: Optional[RecorderReader] = None,
                evidence_loader: Optional[Callable] = None, unified_mode: Optional[str] = None,
                ledger=None, send=None, fallback_send: Optional[Callable] = None,
                lifecycle_path: Optional[Path] = None, focus_path: Optional[Path] = None,
                focus_events_path: Optional[Path] = None, journal_path: Optional[Path] = None,
                catalyst_lookup: Optional[Callable] = None) -> dict:
    """One closed candle for the FOCUS list: re-rank the pool, update membership, classify, thread. ALERTS ONLY.

    Returns {"focus": state, "events": focus events, "rows": per-member rows}. persist=False writes nothing (the
    unified ledger is then a MemoryLedger)."""
    try:
        from lib import scalp_focus as sf  # type: ignore
        from lib import unified_momentum_alert as um  # type: ignore
        from lib import l2_book_signals as l2sig  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.lib import scalp_focus as sf  # type: ignore
        from scripts.lib import unified_momentum_alert as um  # type: ignore
        from scripts.lib import l2_book_signals as l2sig  # type: ignore
    fcfg = fcfg or sf.load_config()
    unified_mode = unified_mode or um.resolve_mode()
    plan = _cadence(cfg, unified_mode)
    rec = recorder or RecorderReader()
    jdir = ma.journal_dir()
    lpath = lifecycle_path or (jdir / LIFECYCLE_FILE)
    memory = load_lifecycle(lpath, day)
    prev_focus = sf.load_state(focus_path, day=day)
    if ledger is None:
        ledger = um.Ledger(um.ledger_path()) if persist else um.MemoryLedger()
    acfg = ma.AlertConfig(book_levels=cfg.book_levels, max_book_age_s=cfg.max_book_age_s, max_spread_bps=1e9)
    tcfg = ma.AlertConfig(tape_prints=cfg.tape_prints, max_tape_age_s=cfg.max_quote_age_s, min_tape_prints=1)
    snapshot_box: dict[str, Any] = {}

    def evidence_snapshot() -> Any:
        if "v" not in snapshot_box:
            try:
                snapshot_box["v"] = evidence_loader() if evidence_loader is not None else None
            except Exception:  # noqa: BLE001 — unreadable evidence is UNKNOWN evidence, never a pass
                snapshot_box["v"] = None
        return snapshot_box["v"]

    # 1) pool pre-rank from one batched snapshot (no subscription): change, PM volume vs float, scan RVOL
    syms = [str(u["symbol"]).upper() for u in pool if u.get("symbol")]
    by_sym = {str(u["symbol"]).upper(): u for u in pool if u.get("symbol")}
    try:
        snap = data.snapshot(syms) if syms else {}
    except Exception:  # noqa: BLE001
        snap = {}
    invalid: dict[str, str] = {}
    pre: dict[str, dict] = {}
    members = set(((prev_focus or {}).get("members") or {}).keys())
    for sym in syms:
        u, sn = by_sym[sym], snap.get(sym) or {}
        float_mm = u.get("float_mm") if u.get("float_mm") is not None else sn.get("float_mm")
        if float_mm is not None and float_mm > cfg.float_mm_max:
            invalid[sym] = f"float {float_mm:.1f}M > {cfg.float_mm_max:g}M"
            continue
        px = sn.get("pre_price") or sn.get("last_price")
        pc = sn.get("prev_close")
        # a member keeps a 3 % band tolerance so a name trading at the $1.00 / $25 edge does not flap in and out
        tol = 0.03 if sym in members else 0.0
        if px is not None and not (cfg.price_min * (1 - tol) <= px <= cfg.price_max * (1 + tol)):
            invalid[sym] = f"price {px:.2f} out of band"
            continue
        pre[sym] = {"rvol": u.get("rvol"), "float_mm": float_mm, "prev_close": pc,
                    "change_pct": None if not (px and pc) else round((px - pc) / pc * 100, 2),
                    "rotation_pct": None if not (float_mm and sn.get("pre_volume")) else
                    round(sn["pre_volume"] / (float_mm * 1e6) * 100, 2)}
    pre_ranked = sf.rank(pre, fcfg)
    contenders = [r["symbol"] for r in pre_ranked[: fcfg.exit_rank]]
    contenders += [s for s in sorted(members) if s in pre and s not in contenders]

    # 2) closed-candle features for the contenders (recorder store first, own quote-context bars second)
    feats: dict[str, dict] = {}
    ctx: dict[str, dict] = {}
    for sym in contenders:
        p = pre[sym]
        bars_src = "recorder"
        try:
            rows = rec.bars(day, sym, boundary=boundary, now=now, max_age_s=max(60.0, cfg.max_book_age_s))
        except Exception:  # noqa: BLE001
            rows = None
        if rows is None:
            bars_src = "moomoo_quote"
            try:
                rows = data.bars_start(sym)
            except Exception as exc:  # noqa: BLE001
                rows, bars_src = [], f"error:{type(exc).__name__}"
        feat = candle_features(closed_bars(rows, boundary=boundary, day=day), prev_close=p["prev_close"],
                               float_mm=p["float_mm"], boundary=boundary, vwap_hold_bars=cfg.vwap_hold_bars)
        feat["bars_source"] = bars_src
        book_src, book, book_age = "recorder", None, None
        try:
            book = rec.book(day, sym, now=now, max_age_s=cfg.max_book_age_s)
        except Exception:  # noqa: BLE001
            book = None
        try:
            ticks = rec.tape(day, sym, now=now)
        except Exception:  # noqa: BLE001
            ticks = []
        ctx[sym] = {"feat": feat, "book": book, "book_src": book_src if book else None, "ticks": ticks}
        gate_ev = mse.same_symbol_evidence(sym, evidence_snapshot(), now=datetime.fromtimestamp(now, ET))
        l2 = ma.l2_evidence(book, now=now, cfg=acfg, source="recorder") if book else {}
        tape = ma.tape_evidence(ticks, now=now, cfg=tcfg, source="recorder") if ticks else {}
        ctx[sym].update(l2=l2, tape=tape, evidence=gate_ev)
        feats[sym] = {"rvol": p["rvol"],
                      "change_pct": feat.get("gap_pct") if feat.get("status") == "OK" else p["change_pct"],
                      "rotation_pct": feat.get("rotation_pct") if feat.get("status") == "OK" else p["rotation_pct"],
                      "depth_ratio": l2.get("depth_ratio"), "buy_ratio": tape.get("buy_ratio"),
                      "evidence_passed": gate_ev.get("passed_count") if gate_ev.get("status") == "CURRENT" else None,
                      "minutes_since_high": feat.get("minutes_since_high"), "above_vwap": feat.get("above_vwap")}
    ranked = sf.rank(feats, fcfg)
    tail = [r for r in pre_ranked if r["symbol"] not in feats]
    for i, r in enumerate(tail, len(ranked) + 1):
        ranked.append({**r, "rank": i})

    # 3) lifecycle for current members + contenders that may enter (state feeds the protection rule)
    # states for members (ARMED / TRIGGERED are protected) and for any name still cooling off after a STAND DOWN
    # (it may not re-enter until reopen_after_min has passed: no leave/enter flapping on a faded name)
    states = {}
    for s_, m_ in memory.items():
        st_ = (m_ or {}).get("state")
        if st_ == "STAND_DOWN" and boundary - float((m_ or {}).get("stood_down_at") or 0) >= cfg.reopen_after_min * 60:
            st_ = None
        if s_ in members or st_ == "STAND_DOWN":
            states[s_] = st_
    focus, fevents = sf.update(prev_focus, ranked, now=boundary, cfg=fcfg, states=states, invalidated=invalid)
    rank_of = {r["symbol"]: r["rank"] for r in ranked}
    direct_left = int(cfg.direct_book_max)
    rows_out: list[dict] = []
    for m in sf.members_by_rank(focus):
        sym = m["symbol"]
        c = ctx.get(sym)
        if c is None:
            continue
        feat, l2, tape = c["feat"], c["l2"], c["tape"]
        mem = memory.get(sym) or {}
        if not l2 and direct_left > 0 and mem.get("state") in ("APPROACHING", "ARMED") + POST_TRIGGER:
            direct_left -= 1                     # closest to action: read the book directly when unrecorded
            try:
                book = data.book(sym, now)
                l2 = ma.l2_evidence(book, now=now, cfg=acfg, source="moomoo_direct")
                c["book_src"] = "moomoo_direct"
                tape = ma.tape_evidence(data.tape(sym), now=now, cfg=tcfg, source="moomoo_direct")
            except Exception:  # noqa: BLE001
                l2 = l2 or {"source": "moomoo_direct", "ok": False, "reasons": ["BOOK_MISSING"]}
        gates = decide(feat, l2, tape, cfg=cfg, quote_age_s=feat.get("candle_age_s"))
        state, why, new_mem = classify(feat, gates, mem, cfg=cfg, l2=l2)
        gate = None
        if state is not None and cfg.evidence_gate != "off":
            gate = momentum_gate(sym, evidence_snapshot(), cfg=cfg, now=now)
        block = mse.evidence_block((c.get("evidence") or {}).get("evidence"),
                                   extra_facts=live_facts(feat, l2, tape, rvol=pre[sym]["rvol"], cfg=cfg,
                                                          book_src=c.get("book_src"),
                                                          book_age=(l2 or {}).get("age_s")))
        row = {"schema": "PremarketCadence@v1", "day": day, "tick_epoch": now, "boundary_epoch": boundary,
               "candle_at": feat.get("candle_at"), "symbol": sym, "rank": rank_of.get(sym),
               "cadence": plan, "prev_state": mem.get("state"), "state": state, "why": why,
               "gates": gates, "features": {k: feat.get(k) for k in (
                   "last", "pm_high", "prior_high", "pm_vwap", "gap_pct", "vol_accel", "dist_to_high_pct",
                   "below_vwap_bars", "candle_age_s", "bars_source")},
               "book": {"source": c.get("book_src"), "age_s": (l2 or {}).get("age_s")},
               "evidence_block": {k: block[k] for k in ("driven_by", "ready", "missing")},
               "evidence_gate": None if gate is None else gate.get("result"), "action": None}
        changed = state is not None and state != mem.get("emitted_state")
        hold = gate is not None and gate.get("result") == UNVALIDATED and cfg.evidence_gate == "hold"
        if changed and plan["emit"] and not hold:
            ev = um.UnifiedAlertEvent(
                symbol=sym, state=state, ts_epoch=boundary, origin=ORIGIN_1M,
                origin_ref=f"pm1m:{day}:{sym}:{int(boundary)}:{state}",
                float_m=pre[sym]["float_mm"], volume=feat.get("pm_volume"), rvol=pre[sym]["rvol"],
                price=feat.get("last"),
                sources={"scan": True, "social": None,
                         "l2": None if l2.get("best_ask") is None else
                         (l2.get("depth_ratio") or 0) >= cfg.min_depth_ratio},
                source_detail={"scan": f"focus rank {rank_of.get(sym)}"},
                l2=l2sig.from_at_l2(l2) if l2 else None,
                levels={"trigger": new_mem.get("break_level") or feat.get("pm_high"), "stop": feat.get("pm_vwap")},
                detail=f"{feat.get('candle_at')} 1-min close {_fmt_n(feat.get('last'))}: {why}"
                       + (" · UNVALIDATED" if gate and gate.get("result") == UNVALIDATED else ""),
                evidence_block=block)
            try:
                um.enrich_catalyst(ev, catalyst_lookup)
            except Exception:  # noqa: BLE001 — a missing catalyst renders "—"; the state change still goes
                pass
            res = um.emit(ev, mode=plan["emit_mode"], ledger=ledger, send=send,
                          legacy_alert="active_trader.premarket_watch (5-min throttled heads-up)",
                          # corrections of an alert already sent are never capped (momentum_alerts._INFO_KINDS)
                          max_per_hour=None if state in ma._INFO_KINDS else int(cfg.max_msgs_per_symbol_hour),
                          priority="P1")
            row["action"] = res.get("action")
            row["thread_key"] = res.get("thread_key")
            if res.get("action") in um.EMITTED_ACTIONS or res.get("action") == "DEDUPED_SAME_STATE":
                new_mem["emitted_state"] = state
            else:
                new_mem["emitted_state"] = mem.get("emitted_state")
            if res.get("action") == "SEND_FAILED" and fallback_send is not None:
                text = res.get("text") or um.render(ev)
                head, _, body = text.partition("\n")
                try:
                    fb = _send_scoped(fallback_send, sym, title=f"{ma.AT_SCALP_ALERT_HEADER}\n{head}", body=body)
                except Exception as exc:  # noqa: BLE001
                    # ALARM-DELIVERY-DECLARED: both the threaded send and the legacy fallback failed; recorded on the
                    # 1-min journal row (durable) and in the unified ledger as SEND_FAILED, retried next state change.
                    fb = {"sent": False, "error": type(exc).__name__}
                row["fallback_send"] = fb
        else:
            new_mem.setdefault("emitted_state", mem.get("emitted_state"))
            if hold and changed:
                row["action"] = "HELD_UNVALIDATED"
        memory[sym] = new_mem
        m["state"] = state or m.get("state")
        if persist and (row["action"] or state != mem.get("state")):
            ma.append_journal(row, journal_path or (jdir / CADENCE_JOURNAL))
        rows_out.append(row)
    if persist:
        sf.save(focus, fevents, day=day, path=focus_path, events_file=focus_events_path)
        save_lifecycle(lpath, day, memory)
        ma.append_journal({"schema": "PremarketCadenceTick@v1", "day": day, "tick_epoch": now,
                           "boundary_epoch": boundary, "cadence": plan, "pool": len(syms),
                           "contenders": len(contenders), "focus": [m["symbol"] for m in sf.members_by_rank(focus)],
                           "focus_events": [{k: e.get(k) for k in ("event", "symbol", "reason")} for e in fevents],
                           "state_changes": sum(1 for r in rows_out if r.get("action"))},
                          journal_path or (jdir / CADENCE_JOURNAL))
    return {"focus": focus, "events": fevents, "rows": rows_out, "plan": plan}


class RunLock:
    """Non-blocking exclusive lock for the whole process: a second premarket run (manual or cron) never overlaps."""

    def __init__(self, path: Path):
        self.path, self.fh = Path(path), None

    def acquire(self) -> bool:
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = self.path.open("a")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True

    def release(self) -> None:
        if self.fh is not None:
            import fcntl
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None


def run_loop(tick: Callable[[float, float, bool], Any], *, cfg: PremarketConfig, now_fn=time.time,
             sleep_fn=time.sleep, max_ticks: Optional[int] = None, stop_fn: Optional[Callable[[], bool]] = None,
             out=print) -> dict:
    """Tick settle_s after every minute boundary, on the closed candle, until the window ends. Single-threaded,
    so ticks never overlap; a tick that overruns skips the minutes it missed (counted, never queued)."""
    stats = {"ticks": 0, "skipped_minutes": 0, "stopped": None, "boundaries": []}
    last_boundary: Optional[float] = None
    while True:
        if stop_fn is not None and stop_fn():
            stats["stopped"] = "kill_file"
            break
        if max_ticks is not None and stats["ticks"] >= max_ticks:
            stats["stopped"] = "max_ticks"
            break
        now = now_fn()
        at = next_tick(now, cfg.settle_s)
        if at > now:
            sleep_fn(at - now)
        now = now_fn()
        boundary = minute_boundary(now - float(cfg.settle_s))
        if not in_window(datetime.fromtimestamp(boundary, ET), cfg) and not in_window(
                datetime.fromtimestamp(boundary - 60.0, ET), cfg):
            stats["stopped"] = "window_closed"
            break
        if last_boundary is not None and boundary - last_boundary > 60.0:
            stats["skipped_minutes"] += int((boundary - last_boundary) // 60) - 1
        if last_boundary is not None and boundary <= last_boundary:
            continue
        minute = datetime.fromtimestamp(boundary, ET).minute
        legacy_due = minute % max(1, int(cfg.legacy_grid_min)) == 0
        try:
            tick(boundary, now, legacy_due)
        except Exception as exc:  # noqa: BLE001 — one bad minute never stops the loop
            out(f"[premarket-loop] tick failed: {type(exc).__name__}: {str(exc)[:160]}")
        stats["ticks"] += 1
        stats["boundaries"].append(boundary)
        last_boundary = boundary
    return stats


def _print_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    for r in rows:
        f = r["premarket"]
        print(f"{r['candidate']['symbol']:6} {r['verdict']:5} gap={f.get('gap_pct')}% pmvol={f.get('pm_volume')} "
              f"rot={f.get('rotation_pct')}% pmH={f.get('pm_high')}@{f.get('pm_high_at')} vwap={f.get('pm_vwap')} "
              f"last={f.get('last')} above_vwap={f.get('above_vwap')} {','.join(r['veto_reasons'])}"
              + (f" evidence={r['momentum_evidence']['result']}:{r['momentum_evidence']['status']}"
                 if r.get("momentum_evidence") else ""))
        if r.get("message"):
            print("  " + (r["message"]["title"] + "\n" + r["message"]["body"]).replace("\n", "\n  "))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Active Trader premarket watch (heads-up only)")
    ap.add_argument("--apply", action="store_true", help="journal (and send when mode=send)")
    ap.add_argument("--as-of", help="replay today's bars up to HH:MM ET (dry run only; no book/tape)")
    ap.add_argument("--symbols", help="comma list instead of the scan universe")
    ap.add_argument("--loop", action="store_true",
                    help="1-minute supervisor: tick on every closed candle until the window ends (cron-launched)")
    ap.add_argument("--max-ticks", type=int, default=None, help="--loop: stop after N ticks (testing)")
    a = ap.parse_args(argv)
    if a.apply and a.as_of:
        ap.error("--as-of is a replay; it never journals or sends")
    if a.loop and a.as_of:
        ap.error("--loop runs on live candles; --as-of is a replay")
    if (ma.journal_dir() / "PREMARKET_DISABLED").exists():
        print("HALT: PREMARKET_DISABLED present"); return 0
    cfg = load_config()
    now = time.time()
    now_et = datetime.fromtimestamp(now, ET)
    day = now_et.date().isoformat()
    as_of = a.as_of or now_et.strftime("%H:%M")
    if not a.as_of and not in_window(now_et, cfg):
        print(f"outside premarket window {cfg.window_start}-{cfg.window_end} ET; nothing to do"); return 0
    lock = RunLock(ma.journal_dir() / RUN_LOCK_FILE)
    if a.apply and not lock.acquire():
        print(json.dumps({"status": "SKIPPED_ALREADY_RUNNING", "lock": str(lock.path)})); return 0
    try:
        return _run(a, cfg, now=now, day=day, as_of=as_of)
    finally:
        lock.release()


def _universe(a, cfg: PremarketConfig) -> tuple[list[dict], list[dict]]:
    if a.symbols:
        u = [{"symbol": s.strip().upper(), "float_mm": None} for s in a.symbols.split(",") if s.strip()]
        return u, u
    from db_adapter import get_connection  # type: ignore
    conn = get_connection()
    try:
        universe = resolve_universe(conn, cfg)
        pool = resolve_pool(conn, cfg) if cfg.cadence_mode != "legacy" else universe
    finally:
        conn.close()
    return universe, pool


def _run(a, cfg: PremarketConfig, *, now: float, day: str, as_of: str) -> int:
    data = PremarketMoomoo(levels=cfg.book_levels, prints=cfg.tape_prints)
    universe_box: dict[str, Any] = {}

    start_cfg = cfg

    def tick(boundary: float, tick_now: float, legacy_due: bool) -> dict:
        # re-read each minute in --loop, so a cadence_mode flip or rollback applies at the next candle
        cfg = (load_config() if a.loop else start_cfg)
        tday = datetime.fromtimestamp(boundary, ET).date().isoformat()
        if not universe_box or tick_now - universe_box.get("at", 0) >= 120:   # the hot list refreshes every 2 min
            universe_box["u"], universe_box["pool"] = _universe(a, cfg)
            universe_box["at"] = tick_now
        universe, pool = universe_box["u"], universe_box["pool"]
        try:
            from lib import unified_momentum_alert as um  # type: ignore
        except ModuleNotFoundError:  # pragma: no cover
            from scripts.lib import unified_momentum_alert as um  # type: ignore
        plan = _cadence(cfg, um.resolve_mode())
        summary: dict[str, Any] = {"as_of": datetime.fromtimestamp(boundary, ET).strftime("%H:%M"),
                                   "mode": cfg.mode, "cadence": plan, "applied": a.apply,
                                   "universe": len(universe), "pool": len(pool)}
        if legacy_due or a.as_of:
            send_ok = a.apply and cfg.mode == "send" and plan["legacy_sends"]
            rows = evaluate(universe, data=data, cfg=cfg, now=tick_now, day=tday, as_of_hm=as_of if a.as_of else
                            datetime.fromtimestamp(tick_now, ET).strftime("%H:%M"),
                            live_book=not a.as_of, persist=a.apply,
                            send_fn=ma.telegram_send if send_ok else None, evidence_loader=mse.load_cached_snapshot)
            _print_rows(rows)
            summary.update(evaluated=len(rows), alerts=sum(r["verdict"] == ma.ALERT for r in rows),
                           sent=sum(bool(r.get("sent")) for r in rows),
                           unvalidated=sum((r.get("momentum_evidence") or {}).get("result") == UNVALIDATED
                                           for r in rows))
        if plan["new_path"] and not a.as_of:
            res = evaluate_1m(pool, data=data, cfg=cfg, boundary=boundary, now=tick_now, day=tday, persist=a.apply,
                              evidence_loader=mse.load_cached_snapshot,
                              fallback_send=ma.telegram_send if a.apply and cfg.mode == "send" else None)
            for r in res["rows"]:
                if r.get("action") or r.get("state") != r.get("prev_state"):
                    print(f"[1m] {r['symbol']:6} rank={r.get('rank')} {r.get('prev_state')} -> {r.get('state')} "
                          f"({r.get('why')}) action={r.get('action')}")
            for e in res["events"]:
                print(f"[focus] {e['event']} {e['symbol']}: {e['reason']}")
            summary["focus"] = [m["symbol"] for m in sorted(res["focus"]["members"].values(),
                                                             key=lambda m: m.get("rank") or 10 ** 6)]
            summary["state_changes"] = sum(1 for r in res["rows"] if r.get("action"))
        print(json.dumps(summary, default=str))
        if a.apply:
            try:
                p = ma.journal_dir() / HEARTBEAT_FILE
                p.write_text(json.dumps({"ts_epoch": tick_now, **summary}, default=str), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        return summary

    try:
        if a.loop:
            stats = run_loop(tick, cfg=cfg, max_ticks=a.max_ticks,
                             stop_fn=lambda: (ma.journal_dir() / "PREMARKET_DISABLED").exists())
            print(json.dumps({"loop": {k: v for k, v in stats.items() if k != "boundaries"}}))
        else:
            # one pass (the 5-minute cron line until the 1-minute packet is installed): the legacy pass as before,
            # plus one closed-candle tick of the new path when cadence is shadow/live
            tick(minute_boundary(now), now, True)
    finally:
        data.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
