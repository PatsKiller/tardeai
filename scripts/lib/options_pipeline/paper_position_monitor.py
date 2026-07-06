"""paper_position_monitor.py — mark-to-market, Greeks drift, advisory labels (PR1).

Schwab chain preferred; broker fallback. Advisory only — no order submit.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from lib.options_pipeline import paper_positions as pp
from lib.options_pipeline import paper_position_alerts as ppa

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "options_paper_monitor.yaml"

Executor = Callable[..., Any]

ADVICE_HOLD = "HOLD_PAPER"
ADVICE_WATCH = "WATCH_PAPER"
ADVICE_CLOSE = "CONSIDER_CLOSE_PAPER"
ADVICE_ROLL = "CONSIDER_ROLL_PAPER"
ADVICE_OUTCOME = "OUTCOME_READY"
ADVICE_STALE = "DATA_STALE"
ADVICE_UNTRADABLE = "QUOTE_UNTRADABLE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def load_config(path: Path | None = None) -> dict:
    p = path or CONFIG_PATH
    if not p.exists():
        return {"enabled": True, "max_positions_per_run": 50, "quote_stale_seconds": 900,
                "max_spread_pct": 12.0, "profit_target_pct": 25.0, "max_loss_pct": 35.0,
                "dte_roll_watch": 14, "advice_only": True,
                "alert_telegram_enabled": True, "alert_ui_enabled": True,
                "telegram_dedupe_minutes": 60}
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def fetch_schwab_chain_quote(
    underlying: str,
    *,
    strike: float,
    expiration: str,
    option_type: str,
    side: str = "call",
) -> dict:
    """Schwab-preferred quote for one contract."""
    try:
        import schwab_transport
        chain = schwab_transport.get_option_chain(underlying.upper(), strike_count=16) or {}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "source": "schwab_chain"}
    chain_side = "put" if (option_type or side or "").lower() == "put" else "call"
    exp_key = (expiration or "")[:10]
    best = None
    for exp in chain.get("expirations") or []:
        if exp_key and str(exp.get("exp") or "")[:10] != exp_key:
            continue
        for row in exp.get("strikes") or []:
            if row.get("side") != chain_side:
                continue
            if abs(_f(row.get("strike")) - _f(strike)) > 0.02:
                continue
            bid, ask = _f(row.get("bid")), _f(row.get("ask"))
            mid = (bid + ask) / 2.0 if bid and ask else _f(row.get("last"))
            best = {
                "ok": True,
                "source": "schwab_chain",
                "underlying_price": _f(chain.get("underlying_price")),
                "bid": bid, "ask": ask, "mid": mid,
                "mark": mid,
                "iv": _f(row.get("iv")) / 100.0 if _f(row.get("iv")) > 3 else _f(row.get("iv")),
                "delta": _f(row.get("delta")),
                "gamma": _f(row.get("gamma")),
                "theta": _f(row.get("theta")),
                "vega": _f(row.get("vega")),
                "oi": int(_f(row.get("oi"))),
                "volume": int(_f(row.get("volume"))),
                "dte": int(_f(exp.get("dte"))),
                "fetched_at": _now().isoformat(),
            }
            if bid and ask and mid:
                best["spread_pct"] = round((ask - bid) / mid * 100.0, 2)
            break
        if best:
            break
    if not best:
        return {"ok": False, "error": "contract not found on schwab chain", "source": "schwab_chain"}
    return best


def compute_unrealized_pnl(position: dict, mark: float) -> tuple[float, float]:
    entry = _f(position.get("entry_fill_price"))
    contracts = int(position.get("contracts") or 1)
    mult = 100.0 * contracts
    dc = str(position.get("entry_debit_credit") or "debit")
    if dc == "credit":
        pnl = round((entry - mark) * mult, 2)
        cost_basis = entry * mult
    else:
        pnl = round((mark - entry) * mult, 2)
        cost_basis = entry * mult
    pct = round(pnl / cost_basis * 100.0, 2) if cost_basis else 0.0
    return pnl, pct


def compute_mfe_mae(position_id: int, pnl: float, *, executor: Executor) -> tuple[float, float]:
    rows = executor(
        """SELECT unrealized_pnl FROM options_monitored_position_snapshots
           WHERE position_id = %s ORDER BY snapshot_at DESC LIMIT 50""",
        (position_id,), fetch="all") or []
    prior = [_f(r.get("unrealized_pnl")) for r in rows]
    all_pnls = prior + [pnl]
    return max(all_pnls), min(all_pnls)


def generate_advisory_label(
    position: dict,
    quote: dict,
    pnl_pct: float,
    cfg: dict,
) -> tuple[str, str, list[dict]]:
    """Return (advice_label, advice_reason, risk_flags)."""
    flags: list[dict] = []
    strat = str(position.get("strategy") or "default")
    rules = (cfg.get("strategy_rules") or {}).get(strat) or (cfg.get("strategy_rules") or {}).get("default") or {}
    max_spread = _f(cfg.get("max_spread_pct"), 12.0)
    profit_tgt = _f(rules.get("profit_target_pct") or cfg.get("profit_target_pct"), 25.0)
    max_loss = _f(rules.get("max_loss_pct") or cfg.get("max_loss_pct"), 35.0)
    dte_roll = int(cfg.get("dte_roll_watch") or 14)

    if not quote.get("ok"):
        return ADVICE_STALE, quote.get("error") or "quote unavailable", [
            {"code": "data_stale", "message": quote.get("error") or "no quote"}]

    spread = quote.get("spread_pct")
    bid, ask = _f(quote.get("bid")), _f(quote.get("ask"))
    if not bid or not ask:
        flags.append({"code": "no_bid_ask", "message": "Missing bid/ask on chain"})
        return ADVICE_UNTRADABLE, "No bid/ask — do not size without live chain review", flags
    if spread is not None and spread > max_spread:
        flags.append({"code": "wide_spread", "message": f"Spread {spread:.1f}% > {max_spread:.0f}%"})
        return ADVICE_WATCH, f"Wide spread ({spread:.1f}%)", flags

    dte = quote.get("dte")
    if dte is not None and dte <= dte_roll:
        flags.append({"code": "dte_roll_watch", "message": f"DTE {dte} ≤ roll watch {dte_roll}"})
        if pnl_pct > 5:
            return ADVICE_ROLL, f"DTE {dte} — thesis still positive; consider roll advisory", flags
        return ADVICE_WATCH, f"Short DTE ({dte})", flags

    if strat == "deep_itm_call":
        min_delta = _f(rules.get("min_delta"), 0.70)
        delta = _f(quote.get("delta"))
        if delta and delta < min_delta:
            flags.append({"code": "delta_decay", "message": f"Δ {delta:.2f} < {min_delta}"})
            return ADVICE_WATCH, f"Delta below deep-ITM floor ({delta:.2f})", flags

    entry_iv = _f(position.get("entry_iv"))
    iv_now = _f(quote.get("iv"))
    if entry_iv and iv_now and cfg.get("iv_crush_watch"):
        crush_pct = _f(cfg.get("iv_crush_watch_pct"), 15.0)
        iv_chg = (iv_now - entry_iv) / entry_iv * 100.0 if entry_iv else 0.0
        if iv_chg <= -crush_pct:
            flags.append({"code": "iv_crush", "message": f"IV down {abs(iv_chg):.1f}% vs entry"})
            return ADVICE_WATCH, "IV crush vs entry", flags

    if pnl_pct >= profit_tgt:
        flags.append({"code": "profit_target", "message": f"P/L {pnl_pct:.1f}% ≥ target {profit_tgt:.0f}%"})
        return ADVICE_CLOSE, f"Profit target advisory ({pnl_pct:.1f}%)", flags
    if pnl_pct <= -max_loss:
        flags.append({"code": "max_loss_watch", "message": f"P/L {pnl_pct:.1f}% ≤ -{max_loss:.0f}%"})
        return ADVICE_CLOSE, f"Max-loss watch ({pnl_pct:.1f}%)", flags

    return ADVICE_HOLD, "Within paper monitor thresholds", flags


def write_snapshot(
    position: dict,
    quote: dict,
    *,
    advice_label: str,
    advice_reason: str,
    risk_flags: list[dict],
    executor: Executor,
) -> dict:
    mark = _f(quote.get("mark") or quote.get("mid"))
    pnl, pnl_pct = compute_unrealized_pnl(position, mark)
    mfe, mae = compute_mfe_mae(int(position["id"]), pnl, executor=executor)
    entry_u = _f(position.get("entry_underlying_price"))
    u_now = _f(quote.get("underlying_price"))
    intrinsic = extrinsic = None
    strike = _f(position.get("strike"))
    if strike and u_now:
        if str(position.get("option_type") or "call").lower() == "put":
            intrinsic = max(strike - u_now, 0.0)
        else:
            intrinsic = max(u_now - strike, 0.0)
        extrinsic = max(mark - intrinsic, 0.0) if mark else None
    ex = executor
    ex(
        """INSERT INTO options_monitored_position_snapshots (
            position_id, snapshot_at, underlying_price, option_bid, option_ask, option_mid,
            option_mark, spread_pct, delta, gamma, theta, vega, iv,
            intrinsic_value, extrinsic_value, dte, open_interest, volume,
            market_value, unrealized_pnl, unrealized_pnl_pct,
            max_favorable_excursion, max_adverse_excursion,
            risk_flags_json, advice_label, advice_reason, quote_source, meta_json
        ) VALUES (
            %s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb
        )""",
        (
            position["id"], u_now or None,
            _f(quote.get("bid")) or None, _f(quote.get("ask")) or None,
            _f(quote.get("mid")) or None, mark or None,
            quote.get("spread_pct"), _f(quote.get("delta")) or None,
            _f(quote.get("gamma")) or None, _f(quote.get("theta")) or None,
            _f(quote.get("vega")) or None, _f(quote.get("iv")) or None,
            intrinsic, extrinsic,
            quote.get("dte"), quote.get("oi"), quote.get("volume"),
            round(mark * 100 * int(position.get("contracts") or 1), 2) if mark else None,
            pnl, pnl_pct, mfe, mae,
            json.dumps(risk_flags, default=str),
            advice_label, advice_reason,
            quote.get("source"),
            json.dumps({"underlying_move_pct": round((u_now - entry_u) / entry_u * 100, 2) if entry_u else None},
                       default=str),
        ))
    return {"position_id": position["id"], "mark": mark, "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct, "advice_label": advice_label}


def monitor_position(
    position: dict,
    *,
    cfg: dict,
    executor: Executor,
    dry_run: bool = False,
) -> dict:
    quote = fetch_schwab_chain_quote(
        str(position.get("underlying_symbol") or position.get("symbol") or ""),
        strike=_f(position.get("strike")),
        expiration=str(position.get("expiration") or ""),
        option_type=str(position.get("option_type") or "call"),
        side=str(position.get("side") or "call"),
    )
    mark = _f(quote.get("mark") or quote.get("mid"))
    pnl, pnl_pct = compute_unrealized_pnl(position, mark) if quote.get("ok") else (0.0, 0.0)
    advice, reason, flags = generate_advisory_label(position, quote, pnl_pct, cfg)
    out = {
        "proposal_id": position.get("proposal_id"),
        "position_id": position.get("id"),
        "symbol": position.get("symbol"),
        "broker": position.get("broker"),
        "execution_route": position.get("execution_route"),
        "quote_ok": quote.get("ok", False),
        "mark": mark,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
        "advice_label": advice,
        "advice_reason": reason,
        "risk_flags": flags,
        "dry_run": dry_run,
    }
    if dry_run:
        return out
    snap = write_snapshot(position, quote, advice_label=advice, advice_reason=reason,
                          risk_flags=flags, executor=executor)
    out.update(snap)
    if advice in (ADVICE_STALE, ADVICE_UNTRADABLE, ADVICE_WATCH, ADVICE_CLOSE, ADVICE_ROLL):
        alert_res = ppa.dispatch_alert(
            position, advice.lower(), reason,
            severity="warn" if advice == ADVICE_WATCH else "info",
            cfg=cfg, executor=executor, dry_run=False,
            advice_label=advice,
            unrealized_pnl=pnl, unrealized_pnl_pct=pnl_pct, mark=mark or None)
        out["alert"] = alert_res
    return out


def run_monitor(
    *,
    position_id: int | None = None,
    dry_run: bool = False,
    cfg: dict | None = None,
    executor: Optional[Executor] = None,
) -> dict:
    """Monitor all open positions (or one by id). Optionally reconcile Alpaca first."""
    ex = executor or _default_executor()
    config = cfg or load_config()
    if not config.get("enabled", True):
        return {"ok": True, "skipped": True, "reason": "monitor disabled in config"}
    report: Dict[str, Any] = {"ok": True, "dry_run": dry_run, "monitored": [], "warnings": []}
    if config.get("brokers", {}).get("alpaca", {}).get("reconcile_on_run") and not dry_run:
        try:
            from lib.options_pipeline.alpaca_paper import reconcile_fills
            rec = reconcile_fills(executor=ex, dry_run=False)
            report["reconcile"] = {"transitions": rec.get("transitions", []),
                                   "warnings": rec.get("warnings", [])}
        except Exception as e:
            report["warnings"].append(f"alpaca reconcile skipped: {e}")

    if position_id is not None:
        row = ex("SELECT * FROM options_monitored_positions WHERE id = %s", (position_id,), fetch="one")
        positions = [dict(row)] if row and row.get("status") == pp.STATUS_OPEN else []
    else:
        limit = int(config.get("max_positions_per_run") or 50)
        positions = pp.load_open_positions(executor=ex, limit=limit)

    for pos in positions:
        try:
            report["monitored"].append(monitor_position(pos, cfg=config, executor=ex, dry_run=dry_run))
        except Exception as e:
            report["warnings"].append(f"{pos.get('proposal_id')}: {e}")
    report["count"] = len(report["monitored"])
    return report