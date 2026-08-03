"""portfolio_report_llm.py — Grounded OAuth narratives for weekly/monthly portfolio reports.

Builds held-position + live-price context from holdings/enrichment, generates via llm_lane
(Grok OAuth → ChatGPT OAuth → local fallback), and validates action text to block hallucinated
tickers/prices (e.g. TSLA @ $195 when not held).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

CASH_SYMS = {"CASH", "--", "SNSXX", "SWVXX", "SPRXX", "VMFXX", "FDRXX"}

TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")
PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")

STOPWORDS = {
    "IRA", "RMD", "YTD", "ETF", "USD", "SSDI", "BUY", "SELL", "ADD", "TRIM", "CEO", "CFO",
    "IPO", "API", "ONE", "TWO", "THE", "FOR", "AND", "NOT", "ALL", "ANY", "NEW", "OLD", "TOP",
    "LOW", "HIGH", "NET", "TAX", "FED", "GDP", "CPI", "RSI", "SMA", "OB", "OS", "AI", "MFS",
    "DEC", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
    "VIA", "PER", "VS", "USD", "IRA", "RMD", "YTD", "ETF", "HOLD", "WAIT", "PLAN", "NEXT",
    "WEEK", "MONTH", "YEAR", "DONE", "ROOM", "GOLD", "CASH", "BETA", "GAIN", "LOSS", "STOP",
}

REPORT_SYSTEM = (
    "You are a professional wealth manager writing a portfolio report. "
    "FORMATTING RULES: Do not use markdown formatting. No asterisks for bold (**), "
    "no hashtags for headers (#), no backticks for code (`). Write plain text only. "
    "Use UPPERCASE section labels on their own line when needed. "
    "Use numbered lists as '1. ' for action items. No bullet points with dashes. "
    "HARD RULE: Only reference tickers and prices from the HELD POSITIONS table provided. "
    "Never invent tickers, share counts, or prices not in that table or explicit rebalancing targets."
)

PROCESS_WEEKLY = "portfolio_weekly_report"
PROCESS_MONTHLY = "portfolio_monthly_report"


@dataclass
class GroundingContext:
    held_symbols: Set[str] = field(default_factory=set)
    rebal_targets: Set[str] = field(default_factory=set)
    prices: Dict[str, float] = field(default_factory=dict)
    positions_table: str = ""
    rebal_orders: List[Dict[str, Any]] = field(default_factory=list)
    stops_near: List[Dict[str, Any]] = field(default_factory=list)
    rebal_total: float = 0.0

    @property
    def allowed_symbols(self) -> Set[str]:
        return self.held_symbols | self.rebal_targets


def _is_equity_ticker(sym: str) -> bool:
    return bool(sym and TICKER_RE.fullmatch(sym) and sym not in CASH_SYMS)


def _resolve_price(h: Dict[str, Any], enrichment: Dict[str, Any]) -> Optional[float]:
    for key in ("current_price", "price"):
        v = h.get(key)
        if v is not None:
            try:
                p = float(v)
                if p > 0:
                    return round(p, 2)
            except (TypeError, ValueError):
                pass
    sym = (h.get("symbol") or "").upper()
    e = enrichment.get(sym) if isinstance(enrichment.get(sym), dict) else {}
    for key in ("price", "last", "close"):
        v = e.get(key)
        if v is not None:
            try:
                p = float(v)
                if p > 0:
                    return round(p, 2)
            except (TypeError, ValueError):
                pass
    return None


def _aggregate_holdings(holdings_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Merge multi-account rows into one row per symbol."""
    agg: Dict[str, Dict[str, Any]] = {}
    for h in holdings_data.get("holdings", []) or []:
        if not isinstance(h, dict):
            continue
        sym = (h.get("symbol") or "").upper().strip()
        if not _is_equity_ticker(sym) or h.get("is_cash") or h.get("delisted"):
            continue
        mv = float(h.get("market_value") or 0)
        if mv <= 0:
            continue
        shares = float(h.get("shares") or 0)
        price = _resolve_price(h, {})
        row = agg.setdefault(sym, {"symbol": sym, "shares": 0.0, "market_value": 0.0, "accounts": []})
        row["shares"] += shares
        row["market_value"] += mv
        if price and price > 0:
            row["price"] = price
        acct = h.get("account_display") or h.get("account") or ""
        if acct and acct not in row["accounts"]:
            row["accounts"].append(acct)
    return agg


def _compute_rebalancing(holdings_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from portfolio_rebalancer import compute_rebalancing
        return compute_rebalancing(holdings_data) or {}
    except Exception:
        return {}


def _stops_near_trigger(risk_data: Dict[str, Any], *, threshold_pct: float = 5.0) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    positions = risk_data.get("positions")
    rows: List[Dict[str, Any]] = []
    if isinstance(positions, list):
        rows = [p for p in positions if isinstance(p, dict)]
    elif isinstance(positions, dict):
        rows = [p for p in positions.values() if isinstance(p, dict)]
    for p in rows:
        sym = (p.get("symbol") or "").upper()
        if not _is_equity_ticker(sym):
            continue
        dist = p.get("pct_from_stop")
        if dist is None:
            dist = p.get("dist_pct")
        if dist is None:
            continue
        try:
            dist_f = float(dist)
        except (TypeError, ValueError):
            continue
        if abs(dist_f) < threshold_pct:
            out.append({"symbol": sym, "dist_pct": dist_f, "status": p.get("status", "")})
    out.sort(key=lambda x: abs(x.get("dist_pct") or 0))
    return out


def build_grounding(
    holdings_data: Dict[str, Any],
    enrichment: Optional[Dict[str, Any]] = None,
    risk_data: Optional[Dict[str, Any]] = None,
    rebal_rationale: Optional[List[Dict[str, Any]]] = None,
) -> GroundingContext:
    """Build held-symbol + price table and rebalancing targets for LLM prompts."""
    enrichment = enrichment or {}
    risk_data = risk_data or {}
    rebal_rationale = rebal_rationale or []

    agg = _aggregate_holdings(holdings_data)
    held: Set[str] = set(agg.keys())
    prices: Dict[str, float] = {}
    lines: List[str] = []

    for sym in sorted(agg, key=lambda s: agg[s].get("market_value", 0), reverse=True):
        row = agg[sym]
        price = row.get("price")
        if not price:
            for h in holdings_data.get("holdings", []) or []:
                if (h.get("symbol") or "").upper() == sym:
                    price = _resolve_price(h, enrichment)
                    if price:
                        break
        if price:
            prices[sym] = price
        shares = row.get("shares") or 0
        mv = row.get("market_value") or 0
        accts = ", ".join(row.get("accounts") or [])[:40]
        price_s = f"${price:,.2f}" if price else "n/a"
        lines.append(f"  {sym}: {shares:,.2f} sh @ {price_s} | MV ${mv:,.0f} | {accts}")

    rebal_targets: Set[str] = set()
    rebal_orders: List[Dict[str, Any]] = []
    rebal_ctx = _compute_rebalancing(holdings_data)
    for o in rebal_ctx.get("rebalance_orders") or []:
        if not isinstance(o, dict):
            continue
        rebal_orders.append(o)
        for key in ("current_tickers", "suggested_tickers"):
            for t in o.get(key) or []:
                ts = str(t).upper().strip()
                if _is_equity_ticker(ts):
                    rebal_targets.add(ts)
    for r in rebal_rationale:
        if not isinstance(r, dict):
            continue
        sym = (r.get("symbol") or "").upper()
        if _is_equity_ticker(sym):
            rebal_targets.add(sym)

    table = "HELD POSITIONS (authoritative — only these tickers may be recommended):\n"
    table += "\n".join(lines[:45]) if lines else "  (no active equity positions)"
    if rebal_targets:
        extra = sorted(rebal_targets - held)
        if extra:
            table += f"\nREBALANCING TARGETS (may recommend buys): {', '.join(extra[:12])}"

    stops = _stops_near_trigger(risk_data)
    rebal_total = float(rebal_ctx.get("total_to_rebalance") or risk_data.get("total_to_rebalance") or 0)

    return GroundingContext(
        held_symbols=held,
        rebal_targets=rebal_targets,
        prices=prices,
        positions_table=table,
        rebal_orders=rebal_orders,
        stops_near=stops,
        rebal_total=rebal_total,
    )


def _clean_llm_text(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text or "")
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"^#{1,4}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pick_lane(preferred: str = "deepseek-flash") -> Optional[str]:
    try:
        import llm_lane
    except Exception:
        return None
    for lane in (preferred, "grok", "chatgpt", "local"):
        if llm_lane.available(lane):
            return lane
    return None


def generate_oauth_narrative(
    prompt: str,
    *,
    process_id: str,
    task_summary: str,
    timeout: int = 120,
    lane: Optional[str] = None,
    system: Optional[str] = None,
) -> str:
    """Generate narrative via OAuth llm_lane with local fallback."""
    try:
        import llm_lane
        from lib.llm_consumption import ManualRequired
    except Exception as e:
        print(f"  [report-llm] llm_lane unavailable: {e}")
        return ""

    chosen = lane or pick_lane()
    if not chosen:
        return "[Report LLM unavailable — no OAuth or local lane]"

    sys_prompt = system or REPORT_SYSTEM
    full_prompt = f"{sys_prompt}\n\n{prompt}"
    oauth_lane = chosen if chosen in ("deepseek-flash", "grok", "chatgpt") else None

    def _call(ln: str, *, with_process: bool) -> str:
        kw: Dict[str, Any] = {"lane": ln, "timeout": timeout}
        if with_process and ln in ("deepseek-flash", "grok", "chatgpt"):
            kw["process_id"] = process_id
            kw["task_summary"] = task_summary
        return llm_lane.generate(full_prompt, **kw)

    try:
        return _clean_llm_text(_call(chosen, with_process=bool(oauth_lane)))
    except ManualRequired:
        print(f"  [report-llm] {process_id} manual gate — falling back to local")
    except Exception as e:
        print(f"  [report-llm] OAuth error ({chosen}): {e}")

    if chosen != "local" and llm_lane.available("local"):
        try:
            return _clean_llm_text(_call("local", with_process=False))
        except Exception as e:
            print(f"  [report-llm] local fallback error: {e}")
    return ""


def extract_tickers(text: str) -> List[str]:
    return [t for t in TICKER_RE.findall(text or "") if t not in STOPWORDS and _is_equity_ticker(t)]


def validate_action_text(text: str, grounding: GroundingContext) -> Tuple[bool, List[str]]:
    """Return (ok, issues). Reject unheld tickers and prices >20% off grounded quotes."""
    issues: List[str] = []
    allowed = grounding.allowed_symbols

    for sym in extract_tickers(text):
        if sym not in allowed:
            issues.append(f"unheld_ticker:{sym}")

    for m in re.finditer(
        r"([A-Z]{1,5})\b[^.$\n]{0,50}\$\s*([\d,]+(?:\.\d+)?)", text or ""
    ):
        sym, price_s = m.group(1), m.group(2)
        if sym in STOPWORDS or sym not in allowed:
            continue
        try:
            cited = float(price_s.replace(",", ""))
        except ValueError:
            continue
        grounded = grounding.prices.get(sym)
        if grounded and grounded > 1:
            if abs(cited - grounded) / grounded > 0.20:
                issues.append(f"price_mismatch:{sym}:{cited}:{grounded}")

    for m in PRICE_RE.finditer(text or ""):
        try:
            cited = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if cited < 1.5:
            continue
        # Skip notional amounts ("for $45,934") — only validate explicit share prices.
        prefix = (text or "")[max(0, m.start() - 12): m.start()].lower()
        if re.search(r"\bfor\s*$", prefix) or cited > 5000:
            continue
        window = (text or "")[max(0, m.start() - 60): m.end() + 10]
        if not re.search(r"(@|at)\s*\$", window, re.I):
            continue
        nearby = extract_tickers(window)
        for sym in nearby:
            grounded = grounding.prices.get(sym)
            if grounded and grounded > 1 and abs(cited - grounded) / grounded > 0.20:
                tag = f"price_mismatch:{sym}:{cited}:{grounded}"
                if tag not in issues:
                    issues.append(tag)

    return len(issues) == 0, issues


def fallback_action_text(grounding: GroundingContext, *, monthly: bool = False) -> str:
    """Deterministic action when LLM output fails validation."""
    if grounding.rebal_orders:
        o = grounding.rebal_orders[0]
        syms = o.get("current_tickers") or o.get("suggested_tickers") or []
        sym = (syms[0] if syms else "portfolio").upper()
        action = (o.get("action") or "REBALANCE").upper()
        amt = float(o.get("amount_usd") or 0)
        acct = o.get("account") or ""
        price = grounding.prices.get(sym)
        price_bit = f" @ ${price:,.2f}" if price else ""
        line1 = f"{action} {sym}{price_bit} for ${amt:,.0f} in {acct} (top rebalancing priority)."
        if not monthly:
            return line1
        lines = [
            line1,
            "Review Roth conversion room before year-end (2026: $35K done).",
            "Deploy idle cash only into held dividend growers already in the positions table.",
            f"Monitor stops within 5% of trigger ({len(grounding.stops_near)} positions flagged).",
            "Defer new tickers until rebalancing backlog is addressed.",
        ]
        return "\n".join(f"{i}. {ln}" for i, ln in enumerate(lines, 1))

    if grounding.stops_near:
        s = grounding.stops_near[0]
        sym = s["symbol"]
        dist = s.get("dist_pct", 0)
        price = grounding.prices.get(sym)
        price_bit = f" (last ${price:,.2f})" if price else ""
        msg = f"Review stop on {sym}{price_bit} — {dist:+.1f}% from trigger."
        return f"1. {msg}\n2. Hold other positions steady.\n3. No new tickers this month." if monthly else msg

    hold = "Hold positions steady; no urgent rebalancing or stop actions flagged."
    return f"1. {hold}\n2. Monitor cash deployment.\n3. Review dividend income gap." if monthly else hold


def build_weekly_action_prompt(
    grounding: GroundingContext,
    *,
    last_action: str = "",
    context_lines: str = "",
) -> str:
    last_bit = f"Last week you recommended: {last_action[:150]}\n" if last_action else ""
    return f"""Give ONE specific priority action for next week.

{grounding.positions_table}

{last_bit}
CURRENT STATE:
{context_lines}

RULES:
- Exactly ONE sentence. Start with a verb.
- ONLY name tickers from HELD POSITIONS or REBALANCING TARGETS above.
- Any share price cited must match the table (within 2%).
- Do not recommend tickers not in the table (e.g. no TSLA unless listed)."""


def build_monthly_action_prompt(
    grounding: GroundingContext,
    *,
    last_action: str = "",
    context_lines: str = "",
) -> str:
    last_bit = f"LAST MONTH'S PLAN: {last_action}\n" if last_action else ""
    return f"""Create a specific action plan for next month.

{grounding.positions_table}

{last_bit}
CURRENT STATE:
{context_lines}

Write exactly 5 numbered action items. Each must be:
- ONE sentence, start with a verb
- Name only tickers from HELD POSITIONS or REBALANCING TARGETS
- Prices must match the table (within 2%)
- Prioritized by urgency

Cover: (1) rebalancing, (2) Roth conversion, (3) dividend growth, (4) risk management, (5) opportunistic."""


def sanitize_action_text(
    text: str,
    grounding: GroundingContext,
    *,
    monthly: bool = False,
) -> str:
    """Validate action text; return fallback if hallucination detected."""
    cleaned = _clean_llm_text(text)
    if not cleaned:
        fb = fallback_action_text(grounding, monthly=monthly)
        print("  [report-llm] action empty — using fallback")
        return fb
    ok, issues = validate_action_text(cleaned, grounding)
    if ok:
        return cleaned
    print(f"  [report-llm] action failed validation ({', '.join(issues[:3])}) — using fallback")
    return fallback_action_text(grounding, monthly=monthly)