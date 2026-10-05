"""EXIT_WATCH: exit signals for your open Active Trader scalps (operator-approved 2026-10-05).

While the microstructure recorder runs, once per `eval_s` it finds your open round trips today that
were tagged to an alert (your broker fills, SELECT only on trade_transactions), and evaluates the
exit signals over the recorded book and tape: tape flipped to sellers, volume climax with a long
upper wick, an ask wall appearing just above price, a 1-minute close below the prior bar's low,
VWAP lost. When at least `min_signals` are on it records an EXIT_WATCH decision in
<journal dir>/exit_watch.jsonl and, only when `active_trader_exit_watch.mode == "send"`, sends it to
Telegram with the Active Trader header. Default mode is shadow (journal only).

ADVISORY ONLY. It never sells, never places, modifies or cancels anything; you decide.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

try:
    from active_trader import momentum_alerts as ma
    from active_trader import microstructure_signals as msig
    from active_trader import microstructure_recorder as rec
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import microstructure_signals as msig
    from scripts.active_trader import microstructure_recorder as rec

ET = ZoneInfo("America/New_York")
CONTRACT = "active-trader-exit-watch-v1"
KIND = "EXIT_WATCH"


@dataclass(frozen=True)
class ExitWatchConfig:
    mode: str = "shadow"          # shadow = journal only; send = journal + Telegram
    eval_s: float = 60.0
    lookback_s: float = 900.0
    min_signals: int = 1
    cooldown_s: float = 300.0

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "ExitWatchConfig":
        known = {f.name for f in fields(cls)}
        c = cls(**{k: v for k, v in (raw or {}).items() if k in known})
        if c.mode not in ("shadow", "send"):
            raise ValueError(f"active_trader_exit_watch.mode must be shadow or send, got {c.mode!r}")
        return c


SIGNAL_TEXT = {"tape_flip": "tape flipped to sellers", "volume_climax": "volume climax, long upper wick",
               "ask_wall": "ask wall appeared above price", "close_below_prior_low": "1-min close below prior low",
               "vwap_loss": "lost VWAP"}


def exit_path(base: Optional[Path] = None) -> Path:
    return (base or ma.journal_dir()) / "exit_watch.jsonl"


def read_rows(day: Optional[str] = None, base: Optional[Path] = None) -> list[dict]:
    p = exit_path(base)
    if not p.exists():
        return []
    out = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        if day is None or r.get("session_date") == day:
            out.append(r)
    return out


def build_message(pos: Mapping[str, Any], fired: list[str], last: Optional[float]) -> tuple[str, str]:
    title = f"{ma.AT_SCALP_ALERT_HEADER}\n🟠 EXIT WATCH · {pos['symbol']} · exit signals on your position"
    pnl = ((last - pos["buy_price"]) * pos["qty"]) if last is not None else None
    lines = [ma.NOT_AN_ORDER,
             f"you hold {pos['qty']:g} sh from {pos['buy_price']:.2f} · last {last if last is not None else 'n/a'}"
             + (f" · open P&L {pnl:+.2f}" if pnl is not None else ""),
             "signals: " + ", ".join(SIGNAL_TEXT.get(s, s) for s in fired)]
    return title, "\n".join(lines)


def evaluate(pos: Mapping[str, Any], snaps: list[dict], *, now: float, scfg: msig.SignalConfig,
             ecfg: ExitWatchConfig) -> dict:
    snaps = [s for s in snaps if now - ecfg.lookback_s <= (s.get("t") or 0) <= now]
    bars = [b for b in msig.bars_from_ticks(msig.ticks(snaps)) if b["t"] + 60 <= now]
    sig = msig.exit_signals(snaps, bars, now=now, cfg=scfg)
    fired = msig.fired(sig)
    last = next((s.get("l") for s in reversed(snaps) if s.get("l") is not None), None)
    return {"signals": sig, "fired": fired, "last": last,
            "verdict": "ALERT" if len(fired) >= ecfg.min_signals else "QUIET"}


def open_tagged_positions(trips: list[Mapping[str, Any]]) -> list[dict]:
    return [{"symbol": t["symbol"], "qty": t["qty"], "buy_price": t["buy_price"], "buy_ts": t.get("buy_ts"),
             "alert": t.get("alert")}
            for t in trips if t.get("sell_at") is None and t.get("source") == "active_trader"]


class ExitWatcher:
    def __init__(self, *, ecfg: ExitWatchConfig, scfg: msig.SignalConfig, positions_fn: Callable[[], list[dict]],
                 snaps_fn: Callable[[str], list[dict]], send_fn=None, base: Optional[Path] = None):
        self.ecfg, self.scfg = ecfg, scfg
        self.positions_fn, self.snaps_fn, self.send_fn, self.base = positions_fn, snaps_fn, send_fn, base
        self.last_eval = -1e18
        self.last_sent: dict[str, float] = {}

    def __call__(self, now: float, _symbols=None) -> list[dict]:
        if now - self.last_eval < self.ecfg.eval_s:
            return []
        self.last_eval = now
        rows = []
        for pos in self.positions_fn():
            ev = evaluate(pos, self.snaps_fn(pos["symbol"]), now=now, scfg=self.scfg, ecfg=self.ecfg)
            if ev["verdict"] != "ALERT":
                continue
            key = f"{pos['symbol']}:{pos.get('buy_ts')}"
            cooling = now - self.last_sent.get(key, -1e18) < self.ecfg.cooldown_s
            row = {"contract": CONTRACT, "authority": ma.AUTHORITY, "kind": KIND, "ts_epoch": now,
                   "session_date": datetime.fromtimestamp(now, ET).date().isoformat(), "mode": self.ecfg.mode,
                   "position": pos, "fired": ev["fired"], "signals": ev["signals"], "last": ev["last"],
                   "verdict": "VETO" if cooling else "ALERT", "veto_reasons": ["COOLDOWN"] if cooling else [],
                   "sent": False}
            if not cooling:
                self.last_sent[key] = now
                title, body = build_message(pos, ev["fired"], ev["last"])
                row["message"] = {"title": title, "body": body}
                if self.ecfg.mode == "send" and self.send_fn is not None:
                    try:
                        res = self.send_fn(alert_type="at_scalp_exit_watch", title=title, body=body, tier="ALERT",
                                           symbol=pos["symbol"], source="active_trader_exit_watch", dedupe_scope="none")
                        row["sent"] = bool((res or {}).get("sent"))
                        row["send_result"] = res
                    except Exception as e:  # noqa: BLE001
                        row["send_error"] = f"{type(e).__name__}: {e}"
            p = exit_path(self.base)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str, sort_keys=True) + "\n")
            rows.append(row)
        return rows


def ticker(cfg: Mapping[str, Any], *, conn_fn: Callable[[], Any], alert_cfg) -> ExitWatcher:
    """Build the recorder's on_tick hook from config. Positions come from your fills today."""
    try:
        from active_trader import momentum_alerts_api as api
    except ModuleNotFoundError:  # pragma: no cover
        from scripts.active_trader import momentum_alerts_api as api
    ecfg = ExitWatchConfig.from_mapping(cfg.get("active_trader_exit_watch"))
    scfg = msig.SignalConfig.from_mapping(cfg.get("microstructure_signals"))

    def positions() -> list[dict]:
        conn = conn_fn()
        if conn is None:
            return []
        day = datetime.now(ET).date().isoformat()
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT symbol FROM trade_transactions WHERE trade_date=%s AND action IN ('Buy','Sell')""", (day,))
            syms = {r[0] for r in cur.fetchall() if r[0] and r[0].isalpha()}
        conn.rollback()
        if not syms:
            return []
        fills = api.operator_fills(day, syms, conn=conn)
        snap = api.alerts_snapshot(limit=500, session_date=day)
        return open_tagged_positions(api.attribute_fills(fills, snap.get("decisions") or []))

    day_now = lambda: datetime.now(ET).date().isoformat()  # noqa: E731
    return ExitWatcher(ecfg=ecfg, scfg=scfg, positions_fn=positions,
                       snaps_fn=lambda s: rec.load_snapshots(day_now(), s, start=time.time() - ecfg.lookback_s),
                       send_fn=ma.telegram_send if ecfg.mode == "send" else None)
