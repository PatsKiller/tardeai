"""Re-entry watch for names the operator was stopped out of or sold (precision PR round 2).

Operator 2026-10-31: "SpaceX is down to 134. So my 137 stop was actually good, but I would have liked to get out sooner
... we also need the system to let me know when is the right time to hop back in."

Every symbol exited in the last ``lookback_days`` (trade ledger ``trade_closed`` + holdings ``closed_today``, read-only)
gets a CIO RE_ENTER_IF stance, held or not, with deterministic per-symbol conditions from
``config/market_risk_policy.yaml`` ``reentry_watch:``:

1. ``trend_repaired`` — close back above its 20-session average AND above the breakdown level (the close before the
   exit day). Analysis shown as a condition, never as an order or a price to buy at.
2. ``group_recovered`` — the symbol's sector/theme group out of STRESS/WEAK for ``group_sessions`` sessions.
3. ``earnings_clear`` — no earnings inside the next ``earnings_ahead_sessions``; after a print, ``settle_sessions``
   sessions must pass. While earnings are pending the card says so and re-entry is NOT evaluated.
4. ``market_tier_ok`` — market tier at or below YELLOW.
5. ``hedging_normal`` — the options-flow category not at STRESS.

All met -> RE_ENTER (P2 card). Every card shows k of 5 met, the as_of, and a historical base rate from the symbol's
own history (how often a re-entry on the same trend-repair condition beat waiting ``horizon_sessions``, with n).
Taxable account + loss sale within 30 days -> wash-sale note; IRA -> none. MBI_BEHAVIOR = 0: no size, no price to
pay, no order; behaviour-field and sizing-text guards on every card.
"""

from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Any

from scripts.lib.market_risk import contract as c


def _sma(v: list[float], n: int) -> float | None:
    return mean(v[-n:]) if len(v) >= n else None


def base_rate(closes: list[float], cfg: dict[str, Any]) -> dict[str, Any]:
    """Past setups on the symbol's own history: a breakdown (close falls drawdown_pct below its 20-session high and
    under its 20-session average), then the first close that repairs the trend (above the 20-session average and above
    the pre-breakdown close). 'Beat waiting' = the close ``horizon`` sessions later is higher than at the repair."""
    dd = float(cfg.get("breakdown_drawdown_pct", -8.0))
    h = int(cfg.get("horizon_sessions", 20))
    wins = n = 0
    i = 21
    while i < len(closes) - h:
        hi = max(closes[i - 20 : i])
        sma = mean(closes[i - 20 : i])
        if (closes[i] / hi - 1) * 100 <= dd and closes[i] < sma:
            pre = closes[i - 1]
            j = i + 1
            while j < len(closes) - h:
                sj = mean(closes[j - 20 : j])
                if closes[j] >= sj and closes[j] >= pre:
                    n += 1
                    wins += closes[j + h] > closes[j]
                    break
                j += 1
            i = j + 1
            continue
        i += 1
    return {"n": n, "beat_waiting": wins, "rate": round(wins / n, 2) if n else None, "horizon_sessions": h}


def card(
    *,
    symbol: str,
    exit_date: str,
    breakdown_close: float | None,
    closes: list[float],
    last_date: str | None,
    group_label: str | None,
    group_history: list[str],
    earnings_next: str | None,
    earnings_last: str | None,
    sessions_since_earnings: int | None,
    sessions_to_earnings: int | None,
    market_tier: str,
    options_flow_state: str,
    account_types: list[str],
    loss: bool,
    days_since_exit: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    cfg = (policy or {}).get("reentry_watch") or {}
    last = closes[-1] if closes else None
    sma20 = _sma(closes, 20)
    conds = []
    conds.append(
        {
            "key": "trend_repaired",
            "met": bool(last and sma20 and breakdown_close and last >= sma20 and last >= breakdown_close),
            "text": f"close back above its 20-day average and above the pre-exit close ({exit_date})",
        }
    )
    gs = int(cfg.get("group_sessions", 2))
    conds.append(
        {
            "key": "group_recovered",
            "met": len(group_history) >= gs and all(s not in ("STRESS", "WEAK") for s in group_history[-gs:]),
            "text": f"{group_label or 'its group'} out of stress for {gs} sessions",
        }
    )
    ahead = int(cfg.get("earnings_ahead_sessions", 5))
    settle = int(cfg.get("settle_sessions", 3))
    pending = sessions_to_earnings is not None and 0 <= sessions_to_earnings <= ahead
    settling = sessions_since_earnings is not None and sessions_since_earnings < settle
    conds.append(
        {
            "key": "earnings_clear",
            "met": not pending and not settling,
            "text": f"no earnings in the next {ahead} sessions; {settle} sessions after a print",
        }
    )
    conds.append(
        {
            "key": "market_tier_ok",
            "met": str(market_tier).upper() in ("NONE", "GREEN", "BLUE", "YELLOW"),
            "text": "market risk at or below YELLOW",
        }
    )
    conds.append(
        {
            "key": "hedging_normal",
            "met": str(options_flow_state).upper() not in ("STRESS",),
            "text": "index options hedging back to normal",
        }
    )
    met = sum(1 for x in conds if x["met"])
    if pending:
        status, headline = (
            "PENDING_EARNINGS",
            (f"earnings {earnings_next} pending: re-entry not evaluated until the post-earnings reaction settles"),
        )
    elif met == len(conds):
        status, headline = "RE_ENTER", "re-entry conditions met"
    else:
        status, headline = "RE_ENTER_IF", f"{met} of {len(conds)} conditions met"
    taxable = any(str(t).lower() == "taxable" for t in account_types)
    wash = None
    if taxable and loss and days_since_exit <= int(cfg.get("wash_sale_days", 30)):
        wash = (
            f"Taxable account, loss sale {days_since_exit} days ago: a re-buy within 30 days of the loss sale is a "
            "wash sale (the loss is deferred into the new lot)."
        )
    rec = {
        "symbol": symbol,
        "stance": "RE_ENTER" if status == "RE_ENTER" else "RE_ENTER_IF",
        "status": status,
        "headline": headline,
        "conditions": conds,
        "met": met,
        "of": len(conds),
        "exit_date": exit_date,
        "as_of": last_date,
        "base_rate": base_rate(closes, cfg) if closes else {"n": 0, "rate": None},
        "wash_sale_note": wash,
    }
    c.assert_no_behavior_fields(rec)
    _guard(render(rec))
    return rec


def render(rec: dict[str, Any]) -> str:
    br = rec.get("base_rate") or {}
    lines = [
        f"{'🟢' if rec['status'] == 'RE_ENTER' else '⏳'} RE-ENTRY WATCH · {rec['symbol']} · {rec['headline']}",
        *[f"{'✓' if x['met'] else '·'} {x['text']}" for x in rec["conditions"]],
    ]
    if br.get("n"):
        lines.append(
            f"Base rate: in {br['n']} past setups on its own history, re-entering on trend repair beat waiting "
            f"{br['horizon_sessions']} sessions {br['beat_waiting']} times ({round(100 * br['rate'])}%)."
        )
    if rec.get("wash_sale_note"):
        lines.append(rec["wash_sale_note"])
    lines.append(
        f"as of {rec.get('as_of')} · CIO stance {rec['stance']} (advisory; no order, size or price is implied)"
    )
    return "\n".join(lines)


def _guard(text: str) -> None:
    from scripts.lib import buy_ready_cio_review as br

    if br._SIZING_TEXT.search(text):  # noqa: SLF001 — the shared sizing-text guard
        raise ValueError("sizing text in re-entry card")


def sessions_between(a: str, b: str, trading_days: list[str]) -> int | None:
    """Trading sessions from a to b (b > a positive) over a sorted list of session dates."""
    if a not in trading_days or b not in trading_days:
        try:
            da, db = date.fromisoformat(a), date.fromisoformat(b)
            return int((db - da).days * 5 / 7)
        except ValueError:
            return None
    return trading_days.index(b) - trading_days.index(a)
