"""Everything the house holds about a named stock, each line tagged with where it came from.

Operator, 2026-09-14 08:40, after the AXTI reply carried only the re-entry card:

    "What about analyst reviews? What about ... the industry? What about other data
    enhancement ... the information that I'm asking about is not thorough and
    complete, and all the data is there. Also, once again, I don't see the pill
    icons of whether this is internal to trade AI, has any external information
    been looked up, or if it was a LLM like DeepSeek."

The data was there. For AXTI at that moment the house held: the company and its
industry (symbol_profiles), last quarter's EPS beat and the next earnings date,
Yahoo analyst targets (four analysts, mean $96.50 -- dated, and stale), the
record-quarter catalysts (catalyst_events) and news, the sector's momentum and
the Semiconductor Equipment & Materials industry group (both runtime files),
house research, the symbol thesis, and whether it is held. The desk read none
of them for that question.

THE PILLS. Every line starts with one:

    🟢 Trade-AI data                 read from a Trade-AI store (the store and its as-of are named)
    🔵 Looked up outside Trade-AI    fetched from outside Trade-AI for THIS reply
    🟣 AI model (DeepSeek)           written or classified by a model
    Spelled out in words on every line and in the key (operator 2026-09-14).

A line never mixes origins. Data that Trade-AI ingested earlier from Yahoo or
Finviz is 🟢 -- it was read from the house store, not looked up now -- and the
line says which provider it came from ("via Yahoo").

AUTHORITY: READ_ONLY_ADVISORY. Read-only queries through an injected
``db_query``; no model call; no provider call; MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# One definition of the pills and the key, shared with every reply's Origin line.
try:
    from scripts.lib.reply_provenance import LEGEND, PILL_HOUSE, PILL_MODEL, PILL_OUTSIDE
except ImportError:  # pragma: no cover -- hub import path
    from lib.reply_provenance import LEGEND, PILL_HOUSE, PILL_MODEL, PILL_OUTSIDE  # type: ignore

#: yfinance sector names (symbol_profiles) -> the sector names sector_momentum_latest.json uses.
SECTOR_ALIASES = {
    "financial services": "financials",
    "consumer cyclical": "consumer discretionary",
    "consumer defensive": "consumer staples",
    "basic materials": "materials",
    "communication services": "communications",
    "health care": "healthcare",
}

#: Beyond this many days a stored analyst target is history, not a view.
ANALYST_STALE_DAYS = 7

#: The dossier rides under an answer inside one Telegram message (4096 chars).
MAX_CHARS = 2600

DbQuery = Callable[..., list[dict[str, Any]]]


# ── reads ────────────────────────────────────────────────────────────────────


def _rows(db_query: DbQuery, sql: str, params: tuple) -> list[dict[str, Any]]:
    try:
        return list(db_query(sql, params) or [])
    except Exception:  # noqa: BLE001 -- an unreadable store is a gap, never a crash
        return []


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _sector_row(doc: Optional[dict[str, Any]], sector: Optional[str]) -> Optional[dict[str, Any]]:
    if not doc or not sector:
        return None
    want = SECTOR_ALIASES.get(sector.strip().lower(), sector.strip().lower())
    for row in doc.get("rows") or []:
        if isinstance(row, dict) and str(row.get("sector") or "").strip().lower() == want:
            return row
    return None


def _industry_row(doc: Optional[dict[str, Any]], industry: Optional[str]) -> Optional[dict[str, Any]]:
    if not doc or not industry:
        return None
    for row in doc.get("industries") or []:
        if isinstance(row, dict) and str(row.get("industry") or "").strip().lower() == industry.strip().lower():
            return row
    return None


def gather(symbols: list[str], *, db_query: DbQuery, runtime_dir: Path,
           analyst_fn: Optional[Callable[[list[str]], list[dict[str, Any]]]] = None,
           research_fn: Optional[Callable[[list[str]], list[dict[str, Any]]]] = None,
           thesis_fn: Optional[Callable[[str], dict[str, Any]]] = None,
           held: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, dict[str, Any]]:
    """One dict per symbol: every section the house holds, each with its store and as-of."""
    syms = [str(s).upper().strip() for s in symbols or [] if str(s).strip()][:3]
    sector_doc = _read_json(Path(runtime_dir) / "sector_momentum_latest.json")
    industry_doc = _read_json(Path(runtime_dir) / "industry_momentum_latest.json")
    analysts = {}
    if analyst_fn:
        try:
            analysts = {str(a.get("symbol") or "").upper(): a for a in analyst_fn(syms) or []}
        except Exception:  # noqa: BLE001
            analysts = {}
    research: list[dict[str, Any]] = []
    if research_fn:
        try:
            research = list(research_fn(syms) or [])
        except Exception:  # noqa: BLE001
            research = []
    out: dict[str, dict[str, Any]] = {}
    for sym in syms:
        d: dict[str, Any] = {"symbol": sym}
        prof = _rows(db_query, (
            "SELECT description_1s, sector, industry, source, updated_at, next_earnings_date,"
            "       last_earnings_date, last_eps_estimate, last_eps_actual, last_eps_surprise_pct,"
            "       earnings_updated_at"
            "  FROM symbol_profiles WHERE upper(symbol) = %s LIMIT 1"), (sym,))
        d["profile"] = prof[0] if prof else None
        d["catalysts"] = _rows(db_query, (
            "SELECT catalyst_type, severity, headline, source, COALESCE(published_at, created_at) AS at"
            "  FROM catalyst_events WHERE upper(symbol) = %s AND catalyst_type <> 'other'"
            "   AND COALESCE(published_at, created_at) > now() - interval '60 days'"
            " ORDER BY COALESCE(published_at, created_at) DESC LIMIT 3"), (sym,))
        d["news"] = _rows(db_query, (
            "SELECT title, source, published_at FROM news_articles"
            " WHERE upper(symbol) = %s AND published_at > now() - interval '30 days'"
            "   AND COALESCE(is_duplicate, false) = false"
            " ORDER BY published_at DESC LIMIT 4"), (sym,))
        d["agents"] = _rows(db_query, (
            "SELECT DISTINCT ON (agent) agent, recommendation, confidence, created_at"
            "  FROM watchlist_agent_results WHERE upper(symbol) = %s"
            "   AND created_at > now() - interval '60 days'"
            " ORDER BY agent, created_at DESC"), (sym,))
        syn = _rows(db_query, (
            "SELECT recommendation, confidence, decision_safety, updated_at FROM watchlist_final_synthesis"
            " WHERE upper(symbol) = %s ORDER BY updated_at DESC NULLS LAST LIMIT 1"), (sym,))
        d["synthesis"] = syn[0] if syn else None
        iv = _rows(db_query, (
            "SELECT iv_pct, snapshot_date FROM options_iv_history WHERE upper(symbol) = %s"
            " ORDER BY snapshot_date DESC LIMIT 1"), (sym,))
        d["iv"] = iv[0] if iv else None
        div = _rows(db_query, (
            "SELECT dividend_yield_pct, annual_dividend_per_share, ex_div_date, updated_at"
            "  FROM ticker_dividend_data WHERE upper(symbol) = %s LIMIT 1"), (sym,))
        d["dividends"] = div[0] if div and div[0].get("dividend_yield_pct") else None
        prof_row = d["profile"] or {}
        d["sector"] = _sector_row(sector_doc, prof_row.get("sector"))
        d["sector_as_of"] = (sector_doc or {}).get("generated_at")
        d["industry"] = _industry_row(industry_doc, prof_row.get("industry"))
        d["industry_as_of"] = (industry_doc or {}).get("captured_at")
        d["analyst"] = analysts.get(sym)
        d["research"] = [r for r in research if str(r.get("symbol") or "").upper() == sym][:3]
        if thesis_fn:
            try:
                th = thesis_fn(sym) or {}
                d["thesis"] = th if (th.get("thesis_state") and th.get("thesis_state") != "INSUFFICIENT_DATA") else None
            except Exception:  # noqa: BLE001
                d["thesis"] = None
        if held is not None:
            d["held"] = held.get(sym)
        out[sym] = d
    return out


# ── formatting ───────────────────────────────────────────────────────────────


def _day(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        dt = v if isinstance(v, (date, datetime)) else datetime.fromisoformat(str(v).replace("Z", "+00:00")[:25])
    except ValueError:
        return str(v)[:10]
    return dt.strftime("%b %d")


def _age_days(v: Any) -> Optional[int]:
    try:
        d = v if isinstance(v, date) and not isinstance(v, datetime) else (
            v.date() if isinstance(v, datetime) else datetime.fromisoformat(str(v)[:10]).date())
        return (datetime.now(timezone.utc).date() - d).days
    except (ValueError, TypeError, AttributeError):
        return None


def _usd(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(v: Any, *, signed: bool = True) -> str:
    try:
        return f"{float(v):+.1f}%" if signed else f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _clean(text: Any, n: int) -> str:
    s = re.sub(r"[*_`\[\]]", " ", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def format_symbol(d: dict[str, Any], *, price: Optional[float] = None,
                  skip: frozenset[str] | set[str] = frozenset()) -> tuple[str, list[str]]:
    """(text, missing sections) for one symbol. Every line starts with a pill."""
    sym = d["symbol"]
    H = PILL_HOUSE + " ·"
    lines = [f"*{sym} — full picture*"]
    missing: list[str] = []

    prof = d.get("profile") or {}
    if prof.get("sector") or prof.get("description_1s"):
        via = f" via {prof['source']}" if prof.get("source") else ""
        bits = [b for b in (prof.get("sector"), prof.get("industry")) if b]
        line = f"{H} Company (symbol_profiles{via}, {_day(prof.get('updated_at'))}): " + " / ".join(bits)
        if prof.get("description_1s"):
            line += " — " + _clean(prof["description_1s"], 140)
        lines.append(line)
    else:
        missing.append("company profile")

    if prof.get("last_eps_actual") is not None or prof.get("next_earnings_date"):
        parts = []
        if prof.get("last_eps_actual") is not None:
            p = f"last {_day(prof.get('last_earnings_date'))} EPS {_usd(prof['last_eps_actual'])}"
            if prof.get("last_eps_estimate") is not None:
                p += f" vs est {_usd(prof['last_eps_estimate'])}"
            if prof.get("last_eps_surprise_pct") is not None:
                p += f" ({_pct(prof['last_eps_surprise_pct'])} surprise)"
            parts.append(p)
        if prof.get("next_earnings_date"):
            parts.append(f"next report {_day(prof['next_earnings_date'])}")
        lines.append(f"{H} Earnings (symbol_profiles, {_day(prof.get('earnings_updated_at'))}): " + " · ".join(parts))
    else:
        missing.append("earnings")

    a = None if "analyst" in skip else d.get("analyst")
    if "analyst" in skip:
        pass
    elif a:
        age = a.get("age_days") if a.get("age_days") is not None else _age_days(a.get("as_of"))
        stale = a.get("stale") if a.get("stale") is not None else (age is not None and age > ANALYST_STALE_DAYS)
        rating = str(a.get("rating") or "no rating").replace("_", " ").title()
        line = f"{H} Analysts (Yahoo targets, as of {_day(a.get('as_of'))}"
        line += f", {age} days old — stale" if stale and age is not None else ""
        line += f"): {rating}"
        if a.get("analysts"):
            line += f" · {a['analysts']} analysts"
        if a.get("target_mean") is not None:
            line += f" · mean target {_usd(a['target_mean'])}"
            if a.get("target_low") is not None and a.get("target_high") is not None:
                line += f" (low {_usd(a['target_low'])}, high {_usd(a['target_high'])})"
            if price:
                try:
                    line += f" · {_pct((float(a['target_mean']) - price) / price * 100)} vs {_usd(price)}"
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        lines.append(line)
    else:
        missing.append("analyst ratings")

    cats = d.get("catalysts") or []
    if cats:
        items = [f"{_day(c.get('at'))} {str(c.get('catalyst_type') or '').replace('_', ' ')}"
                 f"{' (' + str(c['severity']) + ')' if c.get('severity') else ''} — {_clean(c.get('headline'), 90)}"
                 for c in cats[:2]]
        lines.append(f"{H} Catalysts (catalyst_events, 60 days): " + " · ".join(items))
    else:
        missing.append("catalysts (60 days)")

    heads = {_clean(c.get("headline"), 60).lower() for c in cats}
    news = [n for n in d.get("news") or [] if _clean(n.get("title"), 60).lower() not in heads][:2]
    if news:
        lines.append(f"{H} News (news_articles, 30 days): " + " · ".join(
            f"{_day(n.get('published_at'))} {_clean(n.get('title'), 90)} ({_clean(n.get('source'), 30)})" for n in news))
    elif not cats:
        missing.append("news (30 days)")

    sec = d.get("sector")
    if sec:
        line = (f"{H} Sector (sector momentum, {_day(d.get('sector_as_of'))}): {sec.get('sector')} ({sec.get('etf')}) "
                f"{sec.get('state')}")
        rs = [f"{k[2:]}d {float(sec[k]):+.2f}" for k in ("rs5", "rs20", "rs60") if sec.get(k) is not None]
        if rs:
            line += " · RS vs SPY " + " / ".join(rs)
        if sec.get("breadth_pct") is not None:
            line += f" · breadth {sec['breadth_pct']}%"
        lines.append(line)
    else:
        missing.append("sector momentum")

    ind = d.get("industry")
    if ind:
        perf = [f"{lbl} {_pct(ind.get(k))}" for lbl, k in (("week", "perf_week"), ("month", "perf_month"),
                                                            ("quarter", "perf_quarter"), ("YTD", "perf_ytd"))
                if ind.get(k) is not None]
        line = (f"{H} Industry (Finviz groups, {_day(d.get('industry_as_of'))}): {ind.get('industry')} "
                f"{ind.get('state') or ''} · " + " · ".join(perf))
        if ind.get("rel1m") is not None:
            line += f" · vs S&P month {float(ind['rel1m']):+.1f} pts"
        lines.append(line)
    else:
        missing.append("industry group")

    research = [] if "research" in skip else (d.get("research") or [])
    if "research" in skip:
        pass
    elif research:
        lines.append(f"{H} Research (hermes_research_intelligence): " + " · ".join(
            f"{_day(r.get('as_of'))} {str(r.get('research_type') or 'research').replace('_', ' ')}: "
            f"{_clean(r.get('summary') or r.get('topic'), 110)}" for r in research[:2]))
    else:
        missing.append("house research")

    th = d.get("thesis")
    if th:
        line = f"{H} Thesis (symbol thesis store): {th.get('thesis_state')} · role {th.get('portfolio_role')}"
        if th.get("thesis_summary"):
            line += f" — {_clean(th['thesis_summary'], 110)}"
        lines.append(line)
    else:
        missing.append("thesis")

    if "held" in d:
        h = d.get("held")
        if h:
            lines.append(f"{H} Position (holdings.json): held · {h.get('shares')} shares"
                         + (f" · {_usd(h.get('market_value'))}" if h.get("market_value") is not None else ""))
        else:
            lines.append(f"{H} Position (holdings.json): not held")

    agents = d.get("agents") or []
    syn = d.get("synthesis")
    if agents or syn:
        bits = [f"{r.get('agent')} {str(r.get('recommendation') or 'n/a')} ({_day(r.get('created_at'))})" for r in agents[:3]]
        if syn:
            bits.append(f"CIO synthesis {syn.get('recommendation')} ({_day(syn.get('updated_at'))})")
        lines.append(f"{H} Specialist reviews (watchlist agents): " + " · ".join(bits))
    else:
        missing.append("specialist agent reviews")

    if d.get("iv"):
        lines.append(f"{H} Options volatility (options_iv_history, {_day(d['iv'].get('snapshot_date'))}): "
                     f"IV {_pct(d['iv'].get('iv_pct'), signed=False)}")
    else:
        missing.append("options IV")
    if d.get("dividends"):
        dv = d["dividends"]
        lines.append(f"{H} Dividend (ticker_dividend_data): yield {_pct(dv.get('dividend_yield_pct'), signed=False)}"
                     + (f" · ex-div {_day(dv.get('ex_div_date'))}" if dv.get("ex_div_date") else ""))

    take = _meaning(d, price)
    if take:
        lines.append(f"{H} What the stored facts say together: {take}")
    return "\n".join(lines), missing


def _meaning(d: dict[str, Any], price: Optional[float]) -> str:
    """A factual read across the lines above. No recommendation, no new number."""
    bits: list[str] = []
    prof = d.get("profile") or {}
    if prof.get("last_eps_surprise_pct") is not None:
        try:
            s = float(prof["last_eps_surprise_pct"])
            bits.append("last quarter beat estimates" if s > 0 else "last quarter missed estimates")
        except (TypeError, ValueError):
            pass
    ind = d.get("industry") or {}
    if ind.get("state"):
        bits.append(f"its industry group is {str(ind['state']).lower()}")
    a = d.get("analyst") or {}
    if a.get("target_mean") is not None and price:
        try:
            above = float(a["target_mean"]) > price
            age = a.get("age_days") if a.get("age_days") is not None else _age_days(a.get("as_of"))
            s = f"the analyst mean target sits {'above' if above else 'below'} the price"
            if a.get("stale") or (age is not None and age > ANALYST_STALE_DAYS):
                s += " but that view is dated"
            bits.append(s)
        except (TypeError, ValueError):
            pass
    th = d.get("thesis") or {}
    if th.get("thesis_state"):
        bits.append(f"the house thesis is {str(th['thesis_state']).lower()}")
    if not d.get("agents") and not d.get("synthesis"):
        bits.append("no specialist agent has reviewed it in the last two months")
    if not bits:
        return ""
    text = "; ".join(bits)
    return text[0].upper() + text[1:] + "."


def format_dossier(symbols: list[str], dossier: dict[str, dict[str, Any]],
                   *, prices: Optional[dict[str, float]] = None,
                   skip: frozenset[str] | set[str] = frozenset()) -> str:
    """The pill-tagged block for every symbol, plus what is not on file and that nothing went outside."""
    blocks: list[str] = []
    for sym in [str(s).upper() for s in symbols][:3]:
        d = dossier.get(sym)
        if not d:
            continue
        text, missing = format_symbol(d, price=(prices or {}).get(sym), skip=skip)
        if missing:
            text += f"\nNot on file for {sym}: " + ", ".join(missing) + "."
        blocks.append(text)
    if not blocks:
        return ""
    out = "\n\n".join(blocks)
    out += (f"\n{PILL_OUTSIDE}: nothing for these lines — "
            f"say 'research {str(symbols[0]).upper()}' to queue a fresh pull.")
    if len(out) > MAX_CHARS:
        out = out[: MAX_CHARS - 1].rstrip() + "…"
    return out


__all__ = ["LEGEND", "PILL_HOUSE", "PILL_MODEL", "PILL_OUTSIDE", "format_dossier", "format_symbol", "gather"]
