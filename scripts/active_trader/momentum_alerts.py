"""Active Trader Phase 1: ARMED / TRIGGERED momentum-scalp alerts (operator-approved 2026-10-04).

ALERTS ONLY. This module has no order path, no broker session, no 2FA, no trade context. It
decides whether a scored ignition candidate deserves the operator's attention and writes that
decision (alert or veto) to an append-only journal. Sending is a separate, gated step.

Two alerts:
  ARMED      heads-up: the IGN ladder reached an armed lane (IGN_75 / IGN_ACCEL) or the entry
             trigger state machine is ARMED, and the Level 2 book is not against it.
  TRIGGERED  time to buy: the trigger state machine fired within the freshness window AND moomoo
             Level 2 supports it (bid depth >= ask depth x ratio, spread within limit) AND the tape
             confirms (buy-side prints dominate).

Deterministic only: no LLM anywhere in this path. Fail closed: a stale or missing quote, book or
tape is a VETO with the reason journaled, never an alert. Level 2 primary source is moomoo
(OpenD, 60-level depth proven 2026-10-04); Schwab NASDAQ_BOOK is recorded alongside for
comparison and never decides.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

CONTRACT = "active-trader-momentum-alert-v1"
ARMED = "ARMED"
TRIGGERED = "TRIGGERED"
ALERT = "ALERT"
VETO = "VETO"

AUTHORITY = {
    "read_only": True,
    "order": False,
    "broker_write": False,
    "two_factor": False,
    "financial_action": False,
}


@dataclass(frozen=True)
class AlertConfig:
    """Defaults are the Phase 1 proposal. A `active_trader_alerts:` section in
    config/scalp_signal_engine.yaml may override any field (operator-ratified changes only)."""
    mode: str = "shadow"                    # shadow = journal only; send = journal + Telegram
    armed_lanes: tuple = ("IGN_75", "IGN_ACCEL")
    max_quote_age_s: float = 30.0
    max_book_age_s: float = 15.0
    max_tape_age_s: float = 60.0
    max_fire_age_s: float = 360.0           # the logger runs every 5 min; older fires are history
    book_levels: int = 10
    min_depth_ratio_armed: float = 1.0      # bid depth / ask depth over book_levels
    min_depth_ratio_triggered: float = 1.2
    max_spread_bps: float = 80.0
    tape_prints: int = 50
    min_tape_prints: int = 15
    min_buy_ratio: float = 0.55             # buy volume / (buy + sell) volume over the window
    cooldown_s: float = 900.0               # per symbol per alert kind
    max_alerts_per_hour: int = 12
    # Outcome scoring (audit 2026-10-05): measured from the price you could have paid at the alert
    # (best ask, else last), stop-first counts as a miss, plus best and rule-based exits.
    score_touch_min: int = 15               # first touch of stop vs +1R is looked for in this window
    score_horizon_min: int = 30             # best exit / rule exit are looked for in this window
    supply_near_pct: float = 1.0            # ask shares within this % above the inside ask

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "AlertConfig":
        if not raw:
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        kw = {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items() if k in known}
        cfg = cls(**kw)
        if cfg.mode not in ("shadow", "send"):
            raise ValueError(f"active_trader_alerts.mode must be shadow or send, got {cfg.mode!r}")
        return cfg


# ── evidence ──────────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def l2_evidence(book: Optional[Mapping[str, Any]], *, now: float, cfg: AlertConfig,
                source: str) -> dict:
    """Summarise an order book {bids:[(price,size)..], asks:[..], ts_epoch} into deterministic
    evidence. Missing or stale → ok False with a reason; never guessed."""
    ev: dict[str, Any] = {"source": source, "ok": False, "reasons": []}
    if not book:
        ev["reasons"].append("BOOK_MISSING")
        return ev
    ts = _num(book.get("ts_epoch"))
    age = (now - ts) if ts is not None else None
    ev["age_s"] = None if age is None else round(age, 1)
    ev["ts_source"] = book.get("ts_source")
    bids = [(p, s) for p, s in ((_num(b[0]), _num(b[1])) for b in (book.get("bids") or []))
            if p is not None and s is not None][: cfg.book_levels]
    asks = [(p, s) for p, s in ((_num(a[0]), _num(a[1])) for a in (book.get("asks") or []))
            if p is not None and s is not None][: cfg.book_levels]
    ev["levels"] = min(len(bids), len(asks))
    if age is None or age > cfg.max_book_age_s:
        ev["reasons"].append("BOOK_STALE")
    if not bids or not asks:
        ev["reasons"].append("BOOK_EMPTY")
        return ev
    bid_depth = sum(s for _, s in bids)
    ask_depth = sum(s for _, s in asks)
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2.0
    spread_bps = ((best_ask - best_bid) / mid * 1e4) if mid > 0 else None
    ratio = (bid_depth / ask_depth) if ask_depth > 0 else None
    ev.update(bid_depth=bid_depth, ask_depth=ask_depth, best_bid=best_bid, best_ask=best_ask,
              depth_ratio=None if ratio is None else round(ratio, 3),
              spread_bps=None if spread_bps is None else round(spread_bps, 1))
    ev["supply"] = supply_evidence(bids, asks, near_pct=cfg.supply_near_pct)
    if spread_bps is None or spread_bps > cfg.max_spread_bps:
        ev["reasons"].append("SPREAD_WIDE")
    if best_ask <= best_bid:
        ev["reasons"].append("BOOK_CROSSED")
    ev["ok"] = not ev["reasons"]
    return ev


def supply_evidence(bids: Sequence[tuple], asks: Sequence[tuple], *, near_pct: float) -> dict:
    """Observation only (operator 2026-10-05: "the supply wasn't there" on the XNDU fill). Shares
    offered at the inside ask, within `near_pct`% above it, and the largest ask level (a wall)."""
    if not bids or not asks:
        return {}
    best_ask = asks[0][0]
    near = [(p, s) for p, s in asks if p <= best_ask * (1 + near_pct / 100.0)]
    wall_p, wall_s = max(asks, key=lambda x: x[1])
    sizes = sorted(s for _, s in asks)
    med = sizes[len(sizes) // 2] if sizes else None
    return {"ask_size_inside": asks[0][1], "bid_size_inside": bids[0][1],
            "ask_shares_near": sum(s for _, s in near), "ask_levels_near": len(near),
            "near_pct": near_pct, "ask_wall_price": wall_p, "ask_wall_size": wall_s,
            "ask_wall_x_median": round(wall_s / med, 1) if med else None}


def tape_evidence(ticks: Optional[Sequence[Mapping[str, Any]]], *, now: float,
                  cfg: AlertConfig, source: str) -> dict:
    """Ticks are [{ts_epoch, price, volume, direction: BUY|SELL|NEUTRAL}] oldest→newest."""
    ev: dict[str, Any] = {"source": source, "ok": False, "reasons": []}
    rows = list(ticks or [])[-cfg.tape_prints:]
    if not rows:
        ev["reasons"].append("TAPE_MISSING")
        return ev
    last_ts = _num(rows[-1].get("ts_epoch"))
    age = (now - last_ts) if last_ts is not None else None
    ev["age_s"] = None if age is None else round(age, 1)
    buy = sum(_num(r.get("volume")) or 0.0 for r in rows if str(r.get("direction")).upper() == "BUY")
    sell = sum(_num(r.get("volume")) or 0.0 for r in rows if str(r.get("direction")).upper() == "SELL")
    ev.update(prints=len(rows), buy_volume=buy, sell_volume=sell,
              buy_ratio=round(buy / (buy + sell), 3) if (buy + sell) > 0 else None,
              last_price=_num(rows[-1].get("price")))
    if age is None or age > cfg.max_tape_age_s:
        ev["reasons"].append("TAPE_STALE")
    if len(rows) < cfg.min_tape_prints:
        ev["reasons"].append("TAPE_THIN")
    ev["ok"] = not ev["reasons"]
    return ev


# ── decision ──────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """One symbol from one logger pass. Built from the ignition row and trigger engine."""
    symbol: str
    lane: str
    ign: float
    fsm_state: str = "IDLE"
    setup_id: Optional[str] = None
    setup_label: Optional[str] = None
    last: Optional[float] = None
    entry_ref: Optional[float] = None
    stop_ref: Optional[float] = None
    rvol: Optional[float] = None
    float_mm: Optional[float] = None
    quote_ts_epoch: Optional[float] = None
    fire_ts_epoch: Optional[float] = None     # set when the trigger state machine fired
    session_date: Optional[str] = None

    @property
    def r_dollars(self) -> Optional[float]:
        if self.entry_ref is None or self.stop_ref is None:
            return None
        r = self.entry_ref - self.stop_ref
        return r if r > 0 else None


def alert_kind(c: Candidate, *, now: float, cfg: AlertConfig) -> Optional[str]:
    """Which alert this candidate is a candidate FOR (before evidence). None = not interesting."""
    if c.fire_ts_epoch is not None and (now - c.fire_ts_epoch) <= cfg.max_fire_age_s:
        return TRIGGERED
    if c.lane in cfg.armed_lanes or str(c.fsm_state).upper() == "ARMED":
        return ARMED
    return None


def decide(c: Candidate, kind: str, l2: dict, tape: dict, *, now: float, cfg: AlertConfig) -> dict:
    """ALERT or VETO with every reason. Pure function of its inputs."""
    reasons: list[str] = []
    q_age = (now - c.quote_ts_epoch) if c.quote_ts_epoch is not None else None
    if q_age is None or q_age > cfg.max_quote_age_s:
        reasons.append("QUOTE_STALE")
    reasons += [r for r in l2.get("reasons", [])]
    ratio = l2.get("depth_ratio")
    need = cfg.min_depth_ratio_triggered if kind == TRIGGERED else cfg.min_depth_ratio_armed
    if l2.get("ok") and (ratio is None or ratio < need):
        reasons.append("L2_ASK_HEAVY")
    if kind == TRIGGERED:
        reasons += [r for r in tape.get("reasons", [])]
        br = tape.get("buy_ratio")
        if tape.get("ok") and (br is None or br < cfg.min_buy_ratio):
            reasons.append("TAPE_SELLERS")
        if c.entry_ref is None or c.stop_ref is None or c.r_dollars is None:
            reasons.append("NO_STOP_REF")
    # Audit 2026-10-05: XNDU 10:25 and CHPT 10:30 went out as heads-ups with price already through
    # the stop. A setup whose stop is already broken is not a setup.
    if c.last is not None and c.stop_ref is not None and c.last <= c.stop_ref:
        reasons.append("PRICE_AT_OR_BELOW_STOP")
    return {"verdict": VETO if reasons else ALERT, "veto_reasons": reasons,
            "quote_age_s": None if q_age is None else round(q_age, 1)}


# ── throttle (cooldown per symbol+kind, global hourly cap) ───────────────────

class Throttle:
    def __init__(self, state: Optional[Mapping[str, Any]], cfg: AlertConfig):
        self.cfg = cfg
        self.last: dict[str, float] = dict((state or {}).get("last") or {})
        self.sent: list[float] = list((state or {}).get("sent") or [])

    def check(self, symbol: str, kind: str, now: float) -> Optional[str]:
        key = f"{symbol}:{kind}"
        if key in self.last and now - self.last[key] < self.cfg.cooldown_s:
            return "COOLDOWN"
        if len([t for t in self.sent if now - t < 3600]) >= self.cfg.max_alerts_per_hour:
            return "RATE_LIMIT"
        return None

    def record(self, symbol: str, kind: str, now: float) -> None:
        self.last[f"{symbol}:{kind}"] = now
        self.sent = [t for t in self.sent if now - t < 3600] + [now]

    def state(self) -> dict:
        return {"last": self.last, "sent": self.sent}


# ── message ───────────────────────────────────────────────────────────────────

def _fmt(v: Any, nd: int = 2) -> str:
    f = _num(v)
    return "n/a" if f is None else f"{f:.{nd}f}"


AT_SCALP_ALERT_HEADER = "ACTIVE TRADER · SCALP ALERT"   # comms_editor recognises this line
NOT_AN_ORDER = "ADVISORY ONLY — NOT AN ORDER. Your decision, your broker."


def build_message(c: Candidate, kind: str, l2: dict, tape: dict, decision: dict) -> tuple[str, str]:
    """(title, body). The FIRST line of title+body is always the fixed header: the comms editor
    uses it (with the not-an-order line) to apply the operator's 2026-10-04 exemption from the
    missing-CIO hold. Do not reword it."""
    if kind == TRIGGERED:
        headline = f"🟢 TRIGGERED · {c.symbol} · entry conditions met — time to buy?"
    else:
        headline = f"🟡 ARMED · {c.symbol} · setting up — watch it"
    title = f"{AT_SCALP_ALERT_HEADER}\n{headline}"
    lines = [
        NOT_AN_ORDER,
        f"last {_fmt(c.last)} · entry {_fmt(c.entry_ref)} · stop {_fmt(c.stop_ref)} · R {_fmt(c.r_dollars)}",
        f"float {_u(c.float_mm, 1, 'M')} · RVOL {_u(c.rvol, 1, 'x')} · setup {c.setup_label or c.setup_id or 'n/a'}",
        (f"L2 {l2.get('source')} {l2.get('levels', 0)} lv: bid/ask {_u(l2.get('depth_ratio'), 2, 'x')} · "
         f"spread {_u(l2.get('spread_bps'), 0, ' bps')}"),
    ]
    if kind == TRIGGERED:
        lines.append(f"tape {tape.get('source')}: {_pct(tape.get('buy_ratio'))} buys of {tape.get('prints', 0)} prints")
    lines.append(f"data age: quote {_u(decision.get('quote_age_s'), 0, 's')} · book {_u(l2.get('age_s'), 0, 's')}"
                 + (f" · tape {_u(tape.get('age_s'), 0, 's')}" if kind == TRIGGERED else ""))
    base = _cc_base()
    if base:
        lines.append(f"Active Trader: {base}/v3/active-trader?tab=Alerts")
    return title, "\n".join(lines)


def _cc_base() -> str:
    """Command Center base URL (tailnet https) for the deep link; empty when unknown."""
    try:
        try:
            from lib.comms_editor import cc_base  # type: ignore
        except ModuleNotFoundError:
            from scripts.lib.comms_editor import cc_base  # type: ignore
        return (cc_base() or "").rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


def _u(v: Any, nd: int, unit: str) -> str:
    """Value with its unit, or a bare "n/a" — never "n/aM" / "n/ax" (2026-10-04 test alert)."""
    f = _num(v)
    return "n/a" if f is None else f"{f:.{nd}f}{unit}"


def _pct(v: Any) -> str:
    f = _num(v)
    return "n/a" if f is None else f"{f * 100:.0f}%"


def telegram_send(*, alert_type: str, title: str, body: str, **_: Any) -> dict:
    """Deliver one alert now: telegram_alert.send_telegram with the router bypassed (an alert that
    arrives in a digest is useless). Cooldown and hourly cap are enforced by Throttle above."""
    try:
        from telegram_alert import send_telegram  # type: ignore
    except ModuleNotFoundError:
        from scripts.telegram_alert import send_telegram  # type: ignore
    ok = send_telegram(f"{title}\n{body}", bypass_router=True, message_class="active_trader_scalp_alert")
    return {"sent": bool(ok), "alert_type": alert_type, "channel": "telegram"}


# ── journal ───────────────────────────────────────────────────────────────────

def journal_dir() -> Path:
    """Where the logger WRITES and the API READS. Pinned to persistent state first: a per-process
    TRADEAI_ROOT (honoured by production_state_root) would otherwise split writer and reader the
    way the motion journal split on 2026-10-04. ACTIVE_TRADER_ALERTS_DIR overrides (tests)."""
    env = os.environ.get("ACTIVE_TRADER_ALERTS_DIR", "").strip()
    if env:
        return Path(env)
    persistent = Path.home() / "trade-ai-releases" / "persistent-state"
    if (persistent / "PERSISTENT_STATE_ROOT.json").is_file():
        return persistent / "data" / "active_trader"
    try:
        from scripts.lib.canonical_store_registry import production_state_root
    except Exception:  # noqa: BLE001
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
        except Exception:  # noqa: BLE001
            production_state_root = None  # type: ignore
    root = Path(production_state_root()) if production_state_root else persistent
    return root / "data" / "active_trader"


def append_journal(row: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    p = path or (journal_dir() / "momentum_alerts.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str, sort_keys=True) + "\n")
    return p


def load_throttle_state(path: Optional[Path] = None) -> dict:
    p = path or (journal_dir() / "momentum_alerts_throttle.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_throttle_state(state: Mapping[str, Any], path: Optional[Path] = None) -> None:
    p = path or (journal_dir() / "momentum_alerts_throttle.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(p)


# ── one pass ──────────────────────────────────────────────────────────────────

def evaluate_pass(candidates: Iterable[Candidate], *, cfg: AlertConfig, now: Optional[float] = None,
                  fetch_primary_book=None, fetch_primary_tape=None, fetch_compare_book=None,
                  send_fn=None, journal_path: Optional[Path] = None,
                  throttle_path: Optional[Path] = None, run_id: str = "",
                  persist: bool = True) -> list[dict]:
    """Evaluate every interesting candidate once. Fetchers are injected (moomoo primary, Schwab
    comparison) so replay and tests use recorded data. Returns the journal rows written."""
    now = time.time() if now is None else now
    throttle = Throttle(load_throttle_state(throttle_path) if persist else {}, cfg)
    rows: list[dict] = []
    for c in candidates:
        kind = alert_kind(c, now=now, cfg=cfg)
        if kind is None:
            continue
        book = _safe(fetch_primary_book, c.symbol)
        ticks = _safe(fetch_primary_tape, c.symbol) if kind == TRIGGERED else None
        l2 = l2_evidence(book, now=now, cfg=cfg, source="moomoo")
        tape = tape_evidence(ticks, now=now, cfg=cfg, source="moomoo") if kind == TRIGGERED else {}
        compare = l2_evidence(_safe(fetch_compare_book, c.symbol), now=now, cfg=cfg, source="schwab") \
            if fetch_compare_book else None
        d = decide(c, kind, l2, tape, now=now, cfg=cfg)
        if d["verdict"] == ALERT:
            blocked = throttle.check(c.symbol, kind, now)
            if blocked:
                d = {**d, "verdict": VETO, "veto_reasons": [blocked]}
        row = {"contract": CONTRACT, "authority": AUTHORITY, "run_id": run_id, "ts_epoch": now,
               "kind": kind, "mode": cfg.mode, "candidate": asdict(c), "r_dollars": c.r_dollars,
               "l2": l2, "tape": tape, "l2_compare": compare, **d, "sent": False}
        if d["verdict"] == ALERT:
            throttle.record(c.symbol, kind, now)
            title, body = build_message(c, kind, l2, tape, d)
            row["message"] = {"title": title, "body": body}
            if cfg.mode == "send" and send_fn is not None and persist:
                try:
                    res = send_fn(alert_type=f"at_scalp_{kind.lower()}", title=title, body=body,
                                  tier="ALERT", symbol=c.symbol, source="active_trader_p1",
                                  dedupe_scope="none")
                    row["sent"] = bool((res or {}).get("sent"))
                    row["send_result"] = res
                except Exception as e:  # noqa: BLE001
                    row["send_error"] = f"{type(e).__name__}: {e}"
        if persist:
            append_journal(row, journal_path)
        rows.append(row)
    if persist:
        save_throttle_state(throttle.state(), throttle_path)
    return rows


def _safe(fn, symbol: str):
    if fn is None:
        return None
    try:
        return fn(symbol)
    except Exception:  # noqa: BLE001
        return None
