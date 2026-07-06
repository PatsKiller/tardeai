"""Novice tooltips for compact options metric chips — Python mirror for tests."""
from __future__ import annotations

from typing import Any


def _infer_option_type(ctx: dict[str, Any]) -> str:
    if ctx.get("option_type"):
        return str(ctx["option_type"])
    s = str(ctx.get("strategy") or "").lower()
    return "put" if "put" in s else "call"


def _sym(ctx: dict[str, Any]) -> str:
    return str(ctx.get("symbol") or "the stock")


def get_options_metric_tooltip(metric_key: str, context: dict[str, Any] | None = None) -> dict[str, str]:
    ctx = context or {}
    key = "delta_proxy" if metric_key == "delta" and ctx.get("is_delta_proxy") else metric_key

    if key == "dte_bucket":
        days = ctx.get("dte_bucket") or ctx.get("dte")
        bucket = f"{int(days)}d" if days is not None else "this"
        short = (
            f"This option expires in the longer-term bucket, around {int(days)} days."
            if days is not None
            else "This shows which time bucket the scanner grouped this expiration into."
        )
        return {
            "short": short,
            "more": (
                f"The scanner groups expirations into buckets like 60d, 90d, and 180d so you can compare "
                f"short-term vs longer-term versions of the same idea. A {bucket} option gives the trade more "
                "time to work, but it may cost more and still loses value as time passes."
            ),
            "watch": "Watch DTE, theta decay, liquidity, and whether the original thesis is still valid.",
        }

    if key == "strike":
        ot = _infer_option_type(ctx)
        strike = ctx.get("strike")
        spot = ctx.get("spot")
        strike_s = f"${strike:.0f}" if strike is not None and strike >= 50 else (f"${strike:.2f}" if strike is not None else "the strike")
        if ot == "call":
            above = spot is not None and strike is not None and spot > strike
            more = (
                f"For a call option, the strike is the price where the contract gives you the right to buy "
                f"100 shares. Here, a {strike_s} call is deep in-the-money because {_sym(ctx)} is trading above "
                f"{strike_s}. That is why it behaves more like stock than a far-out-of-the-money lottery ticket."
                if above and ctx.get("symbol")
                else "For a call option, the strike is the price where the contract gives you the right to buy "
                "100 shares at expiration. Compare the strike to the current stock price to see how far in- "
                "or out-of-the-money the contract is."
            )
        else:
            more = (
                f"For a put option, the strike is the price where the contract gives you the right to sell "
                "100 shares at expiration. Compare the strike to the current stock price to see how protective "
                "or speculative the contract is."
            )
        return {
            "short": "The strike is the price where the option contract is anchored.",
            "more": more,
            "watch": "Compare the strike to spot price, breakeven, delta, and liquidity.",
        }

    if key == "delta":
        d = f"{float(ctx['delta']):.2f}" if ctx.get("delta") is not None else "0.50"
        return {
            "short": "Delta estimates how stock-like the option is.",
            "more": (
                f"A delta of {d} means the option may move about ${d} for each $1 move in the stock, "
                "before other factors change. Higher delta usually means the option behaves more like owning "
                "shares. Deep in-the-money calls often have higher delta."
            ),
            "watch": "If delta drops, the option may become less stock-like and more speculative.",
        }

    if key == "breakeven":
        be = ctx.get("breakeven")
        move = ctx.get("breakeven_move_pct")
        be_s = f"${float(be):.2f}" if be is not None else "the breakeven price"
        move_txt = ""
        if move is not None:
            move_txt = (
                f" The {'+' if move >= 0 else ''}{float(move):.1f}% means the stock needs to "
                f"{'rise' if move >= 0 else 'fall'} about {abs(float(move)):.1f}% from the current reference "
                "price by expiration."
            )
        ot = _infer_option_type(ctx)
        if ot == "call":
            more = (
                f"For a long call, breakeven is strike plus premium paid. Here, {_sym(ctx)} would need to be "
                f"around {be_s} at expiration for the option to break even.{move_txt}"
            )
        else:
            more = (
                f"For a long put, breakeven is strike minus premium paid. At expiration, {_sym(ctx)} would need "
                f"to be around {be_s} for the option to break even.{move_txt}"
            )
        return {
            "short": "Breakeven is the stock price needed at expiration to break even.",
            "more": more,
            "watch": "Compare breakeven to current price, earnings risk, time left, and your thesis.",
        }

    if key == "share_capital_pct":
        pct = ctx.get("capital_ratio_pct")
        more = (
            f"Buying 100 shares of {_sym(ctx)} would require much more cash. This option controls roughly "
            f"100 shares but uses about {int(round(pct))}% of the cash needed to buy those shares outright. "
            "That is the stock-replacement idea."
            if pct is not None
            else "This ratio compares the option debit to the cash required to buy 100 shares outright — "
            "the stock-replacement framing used on deep in-the-money calls."
        )
        return {
            "short": "This compares option cost to buying 100 shares.",
            "more": more,
            "watch": "Lower capital use does not mean lower risk. The option can still lose 100% of the debit paid.",
        }

    if key == "no_live_path":
        blocks = ctx.get("blocks") or []
        more = (
            f"Blocked from live broker execution — paper testing remains available. Reasons: {'; '.join(blocks)}."
            if blocks
            else "Blocked from live broker execution — paper testing path remains available. "
            "No live order path until the validation gate is met."
        )
        return {"short": "No live broker execution path exists for this row.", "more": more}

    if key == "alpaca_paper_only":
        return {
            "short": "This route uses Alpaca simulated paper orders only.",
            "more": "Alpaca paper sends a simulated limit order — no live broker execution. "
            "Outcomes feed the validation ledger after fill, close, and reconciliation.",
        }

    if key == "live_eligible_false":
        return {
            "short": "This row is not eligible for live broker execution.",
            "more": "Paper-model and unvalidated strategies stay off the live path by design. "
            "You can still review, paper-test, or log manual research.",
        }

    if key == "paper_validation":
        msg = ctx.get("validation_message")
        return {
            "short": "Progress toward the paper-outcomes validation gate.",
            "more": msg or "Paper strategies must accumulate closed outcomes before live consideration.",
        }

    if key in ("pop", "ev", "edge", "rr", "dte", "max_loss", "spread_pct", "oi", "volume"):
        return {
            "short": f"Desk metric: {key.replace('_', ' ')}.",
            "more": "Review on the card and confirm on the chain before paper or manual tickets.",
        }

    return {
        "short": "Desk metric — hover or tap for context.",
        "more": "Open the chain and Explain this trade panel for full context.",
    }


def paper_flag_metric_key(flag_key: str) -> str | None:
    if "earnings_before_expiry" in flag_key:
        return "earnings_before_expiry"
    if flag_key.startswith("delta_proxy"):
        return "delta_proxy"
    if flag_key in ("iv_rich", "iv_rich_pay_up_warning"):
        return "iv_rank"
    return None


def metric_chip_tap(phase: str, coarse_pointer: bool = False) -> str:
    if phase == "closed":
        return "short"
    if phase == "short":
        return "more"
    return "closed"


def metric_chip_hover_enter(phase: str) -> str:
    return "more" if phase == "more" else "short"


def metric_chip_hover_leave(phase: str) -> str:
    return "more" if phase == "more" else "closed"