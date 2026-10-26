"""Registry-driven source coverage: every domain in ``config/data_source_authority.json`` is either read for the
prospectus or explicitly excluded with a reason (``config/prospectus.json`` ``registry_domains``).

Operator 2026-10-26: "What about the FRED information? S-1 and all of the other information. I want to make sure
we're not missing any information." ``tests/test_prospectus_domains_20261026.py`` fails CI when a registry domain is
added without being wired here or excluded with a reason.

Readers are read-only: data-broker projections, house tables and files written by the existing producers
(fred_data_ingest, macro_calendar_refresh, sec_filings_feed, sec_data_ingest (Form 4), sec_fundamentals_ingest,
run_sec_form4_momentum_context, transcript processors, earnings_enrich). None fetches from a market provider. When a
domain is empty or stale and ``request_refresh`` is on (apply runs only), one gap is filed through the governed
data-gap queue (``data_broker.gap_hook.enqueue_gap`` → the data-gap-resolver lane); the prospectus never waits on it.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
import statistics
from typing import Any, Callable, Optional

from . import blocks as bk
from .inputs import Bundle, _f, _iso, _plib

FRED = {"FEDFUNDS": "Fed funds rate %", "DGS10": "10-year Treasury yield %", "T10Y2Y": "10y-2y Treasury spread %",
        "CPIAUCSL": "CPI index", "PCEPILFE": "Core PCE index", "UNRATE": "Unemployment rate %",
        "PAYEMS": "Nonfarm payrolls (thousands)", "BAMLH0A0HYM2": "High-yield OAS spread %",
        "DTWEXBGS": "Trade-weighted dollar index", "DCOILWTICO": "WTI crude $/bbl", "VIXCLS": "VIX"}
SEC_FORMS = ("10-Q", "10-K", "8-K", "S-1", "S-1/A", "424B4", "424B1", "DEF 14A", "13F-HR", "SC 13G", "SC 13D", "4")


@dataclass
class Ctx:
    sources: Any
    bundle: Bundle
    now: datetime
    request_refresh: bool = False
    bars: list = field(default_factory=list)


def registry_domains(root=None) -> list[str]:
    from . import ROOT
    doc = json.loads(((root or ROOT) / "config/data_source_authority.json").read_text(encoding="utf-8"))
    return [d["domain"] for d in doc.get("domains") or [] if isinstance(d, dict) and d.get("domain")]


def _label_of(item: Any) -> str:
    """A plain label for one SEC item/label entry: dict, dict-like string, list or str (never a raw repr)."""
    if isinstance(item, str) and item.strip().startswith(("{", "[")):
        try:
            item = ast.literal_eval(item.strip())
        except (ValueError, SyntaxError):
            return re.sub(r"[{}\[\]'\"]", "", item).strip()
    if isinstance(item, dict):
        code, label = item.get("item"), item.get("label") or item.get("title") or item.get("description")
        if code and label and str(code) != str(label):
            return f"Item {code} {label}" if re.match(r"^\d+\.\d+$", str(code)) else str(label)
        return str(label or code or "").strip()
    if isinstance(item, (list, tuple)):
        return ", ".join(x for x in (_label_of(i) for i in item) if x)
    return str(item or "").strip()


def filing_change_label(event: dict) -> str | None:
    """What a filing changed, in words: 8-K items with their labels ("Item 2.02 Results of operations, Item 9.01"),
    a 10-Q/10-K as its form label ("Quarterly report")."""
    labels = event.get("labels") or []
    labels = labels if isinstance(labels, list) else [labels]
    by_item = {}
    for lab in labels:
        if isinstance(lab, str) and lab.strip().startswith("{"):
            try:
                lab = ast.literal_eval(lab.strip())
            except (ValueError, SyntaxError):
                pass
        if isinstance(lab, dict) and lab.get("item"):
            by_item[str(lab["item"])] = lab
    parts = []
    items = event.get("items") or []
    for it in items if isinstance(items, list) else [items]:
        key = str(it.get("item") if isinstance(it, dict) else it)
        parts.append(_label_of(by_item.pop(key, None) or ({"item": key} if not isinstance(it, dict) else it)))
        if parts[-1] and re.match(r"^\d+\.\d+$", parts[-1]):
            parts[-1] = f"Item {parts[-1]}"
    parts += [_label_of(v) for v in by_item.values()]
    parts += [_label_of(lab) for lab in labels if not (isinstance(lab, dict) and lab.get("item"))
              and not (isinstance(lab, str) and lab.strip().startswith("{") and "item" in lab)]
    text = ", ".join(dict.fromkeys(p for p in parts if p))
    return text[:200] or None


def _db(ctx: Ctx) -> Callable:
    return ctx.sources.db()


def _sql(ctx: Ctx, sql: str, params: tuple) -> list[dict]:
    return [dict(r) for r in (_db(ctx)(sql, params, fetch="all") or [])]


def _jsonl_for(ctx: Ctx, rel: str, sym: str, limit: int = 12) -> list[dict]:
    path = ctx.sources.state_root / rel
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if sym not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("symbol") or row.get("ticker") or "").upper() == sym:
                out.append(row)
    return out[-limit:]


# ── readers: each returns (rows, as_of, block_update) and adds cited facts ─────────────────────────────────────
def r_quote(ctx: Ctx):
    q = _plib("data_broker.market_quote").get_price_batch(_db(ctx), [ctx.bundle.symbol], skip_live=True).get(ctx.bundle.symbol)
    if q:
        ctx.bundle.add("price", "Latest quote", value=q.get("price"), unit="$", source=f"market_quotes ({q.get('source')})",
                       as_of=q.get("as_of"))
        ctx.bundle.add("price", "Latest quote day change %", value=q.get("chg_pct"), unit="%", source="market_quotes",
                       as_of=q.get("as_of"))
    return ([q] if q else []), (q or {}).get("as_of"), {}


def r_technicals(ctx: Ctx):
    doc = json.loads((ctx.sources.state_root / "data/portfolios/state/technical_snapshot.json").read_text(encoding="utf-8"))
    row = (doc.get("symbols") or doc).get(ctx.bundle.symbol) if isinstance(doc, dict) else None
    if isinstance(row, dict):
        for k, v in list(row.items())[:12]:
            if _f(v) is not None:
                ctx.bundle.add("technicals", f"Technical snapshot: {k}", value=v, source="technical_snapshot.json",
                               as_of=doc.get("as_of") or doc.get("generated_at"))
    return ([row] if row else []), (doc or {}).get("as_of") if isinstance(doc, dict) else None, {}


def r_regime(ctx: Ctx):
    out = _plib("data_broker.market_regime").get_market_regime(_db(ctx), history=5)
    regime = out.get("regime") if isinstance(out, dict) else None
    row = {"regime": regime, "line": out.get("regime_line"), "risk_off": out.get("risk_off")} if regime else {}
    if row:
        ctx.bundle.add("macro", "Market regime", text=str(out.get("regime_line") or regime)[:300],
                       source="market_regime_snapshots", as_of=out.get("as_of"))
    return ([row] if row else []), (out or {}).get("as_of"), {}


def r_earnings_calendar(ctx: Ctx):
    out = _plib("data_broker.earnings_calendar").get_earnings([ctx.bundle.symbol])
    row = ((out or {}).get("symbols") or {}).get(ctx.bundle.symbol)
    if row:
        ctx.bundle.add("estimates", "Earnings calendar entry", text=json.dumps(row, default=str)[:300],
                       source="alpha_vantage earnings calendar (house file)", as_of=(out or {}).get("as_of"))
    return ([row] if row else []), (out or {}).get("as_of"), {}


def r_watch_directives(ctx: Ctx):
    rows = _sql(ctx, "SELECT kind, label, rationale, status, created_at FROM watch_directives "
                     "WHERE status = 'active' AND spec::text ~* %s ORDER BY created_at DESC LIMIT 5",
                (rf"\m{ctx.bundle.symbol}\M",))
    for r in rows:
        ctx.bundle.add("watch", f"Operator watch directive ({r.get('kind')})", text=f"{r.get('label') or ''}: {r.get('rationale') or ''}"[:300],
                       source="watch_directives", as_of=r.get("created_at"))
    return rows, None, {}


def r_private_company(ctx: Ctx):
    rows = _sql(ctx, "SELECT private_target_name, proxy_type, ipo_status, expected_ipo_window, why FROM private_company_proxies "
                     "WHERE upper(proxy_ticker) = %s LIMIT 5", (ctx.bundle.symbol,))
    for r in rows:
        ctx.bundle.add("private", f"Private-company exposure: {r.get('private_target_name')}",
                       text=f"{r.get('proxy_type') or ''}; IPO {r.get('ipo_status') or 'n/a'} {r.get('expected_ipo_window') or ''}; {r.get('why') or ''}"[:300],
                       source="private_company_proxies")
    return rows, None, {}


def r_macro(ctx: Ctx):
    rows = _sql(ctx, "SELECT series_id, series_name, value, observation_date FROM fred_economic_series "
                     "WHERE series_id = ANY(%s) AND observation_date >= %s ORDER BY series_id, observation_date",
                (list(FRED), (ctx.now - timedelta(days=400)).date()))
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["series_id"], []).append((str(r["observation_date"])[:10], _f(r["value"])))
    block = {"series": {}, "rate_beta_10y": None, "next_events": []}
    for sid, label in FRED.items():
        pts = [p for p in by.get(sid, []) if p[1] is not None]
        if not pts:
            continue
        last = pts[-1]
        prior = next((p for p in reversed(pts) if p[0] <= (datetime.fromisoformat(last[0]) - timedelta(days=90)).date().isoformat()), None)
        ctx.bundle.add("macro", label, value=last[1], source=f"FRED {sid} (fred_economic_series)", as_of=last[0])
        chg = round(last[1] - prior[1], 3) if prior else None
        ctx.bundle.add("macro", f"{label}, 3-month change", value=chg, source=f"FRED {sid}", as_of=last[0])
        block["series"][sid] = {"label": label, "value": last[1], "as_of": last[0], "chg_3m": chg,
                                "trend": None if chg is None else ("rising" if chg > 0 else "falling" if chg < 0 else "flat")}
    ten = dict(by.get("DGS10", []))
    closes = bk.series_quality(ctx.bars)["series"][-253:]  # bad bars / pre-break history excluded
    pairs = []
    for (d0, c0), (d1, c1) in zip(closes, closes[1:]):
        if d0 in ten and d1 in ten and ten[d0] is not None and ten[d1] is not None:
            pairs.append((ten[d1] - ten[d0], c1 / c0 - 1))
    if len(pairs) >= 60:
        x, y = [p[0] for p in pairs], [p[1] for p in pairs]
        var = statistics.pvariance(x)
        if var:
            beta = sum((a - statistics.fmean(x)) * (b - statistics.fmean(y)) for a, b in zip(x, y)) / len(x) / var
            block["rate_beta_10y"] = round(beta / 100, 4)  # % price move per 1bp
            ctx.bundle.add("macro", "Rate beta: % price move per 1bp change in the 10y yield (1Y)",
                           value=block["rate_beta_10y"] * 100, source="derived: ticker_prices vs FRED DGS10", as_of=closes[-1][0])
    try:
        cal = json.loads((ctx.sources.state_root / "data/runtime/macro_calendar.json").read_text(encoding="utf-8"))
        events = cal.get("events") if isinstance(cal, dict) else cal
        upcoming = [e for e in events or [] if isinstance(e, dict) and str(e.get("date") or e.get("at") or "") >= ctx.now.date().isoformat()
                    and any(k in json.dumps(e).upper() for k in ("CPI", "FOMC", "PCE", "PAYROLL", "JOBS"))][:6]
        for e in upcoming:
            ctx.bundle.add("macro", f"Upcoming macro event: {e.get('name') or e.get('event')}", text=str(e.get("date") or e.get("at"))[:10],
                           source="macro_calendar.json (macro_calendar_refresh)", as_of=cal.get("generated_at") if isinstance(cal, dict) else None)
        block["next_events"] = upcoming
    except (OSError, ValueError, AttributeError):
        block["next_events_gap"] = "macro calendar file unavailable"
    return rows, max((r[-1][0] for r in by.values() if r), default=None), {"macro_sensitivity": block}


def r_fundamentals(ctx: Ctx):
    rows = _sql(ctx, "SELECT source, metric_name, metric_value, period FROM fundamental_data WHERE upper(symbol) = %s "
                     "ORDER BY metric_name LIMIT 60", (ctx.bundle.symbol,))
    for r in rows:
        ctx.bundle.add("fundamental", f"{r.get('metric_name')} ({r.get('period') or 'latest'})", value=r.get("metric_value"),
                       source=f"fundamental_data ({r.get('source')})")
    xbrl = []
    try:
        xbrl = _sql(ctx, "SELECT * FROM sec_xbrl WHERE upper(symbol) = %s ORDER BY 1 DESC LIMIT 12", (ctx.bundle.symbol,))
        for r in xbrl:
            name, val = r.get("concept") or r.get("tag") or r.get("metric"), r.get("value") or r.get("val")
            if name and _f(val) is not None:
                ctx.bundle.add("fundamental", f"SEC XBRL {name} ({r.get('period') or r.get('fy') or ''})", value=val,
                               source="sec_xbrl (sec_fundamentals_ingest)", as_of=r.get("filed") or r.get("filed_at"))
    except Exception:  # noqa: BLE001 - optional companion table
        pass
    return rows + xbrl, None, {}


def r_agent_debate(ctx: Ctx):
    rows = _sql(ctx, "SELECT consensus_recommendation, consensus_score, participants, status, created_at FROM agent_debate_log "
                     "WHERE upper(symbol) = %s ORDER BY created_at DESC LIMIT 3", (ctx.bundle.symbol,))
    for r in rows:
        r["verdict"] = r.get("consensus_recommendation")
        ctx.bundle.add("house", "House agents' debate consensus", text=f"{r.get('consensus_recommendation')} "
                       f"(consensus score {r.get('consensus_score')})", source="agent_debate_log", as_of=r.get("created_at"))
        r["created_at"] = _iso(r.get("created_at"))
    return rows, rows[0].get("created_at") if rows else None, {"debate": rows[:1]}


def r_ai_reports(ctx: Ctx):
    rows = _sql(ctx, "SELECT report_type, title, left(content, 300) AS excerpt, generated_at FROM ai_reports "
                     "WHERE title ~* %s ORDER BY generated_at DESC LIMIT 3", (rf"\m{ctx.bundle.symbol}\M",))
    for r in rows:
        ctx.bundle.add("research", f"House AI report ({r.get('report_type')}): {str(r.get('title') or '')[:80]}",
                       text=r.get("excerpt"), source="ai_reports", as_of=r.get("generated_at"))
    return rows, None, {}


def r_research_index(ctx: Ctx):
    guid = ctx.bundle.context.get("security_guid")
    if not guid:
        return [], None, {}
    rows = _sql(ctx, "SELECT question_class, horizon, answer_store, answered_at, next_due FROM intelligence.research_index "
                     "WHERE subject_guid = %s ORDER BY answered_at DESC NULLS LAST LIMIT 5", (str(guid),))
    for r in rows:
        ctx.bundle.add("research", f"Research index: {r.get('question_class')} ({r.get('horizon')})",
                       text=f"answered {r.get('answered_at')}, next due {r.get('next_due')}, store {r.get('answer_store')}",
                       source="intelligence.research_index", as_of=r.get("answered_at"))
    return rows, None, {}


def r_sec(ctx: Ctx):
    sym = ctx.bundle.symbol
    events = _jsonl_for(ctx, "data/cio/sec_filing_events.jsonl", sym, limit=30)
    filings = []
    for e in sorted(events, key=lambda r: str(r.get("filed_at") or ""), reverse=True):
        form = str(e.get("form") or "").upper()
        if form in {f.upper() for f in SEC_FORMS} and len([f for f in filings if f["form"] == form]) < 2:
            filings.append({"form": form, "filed_at": str(e.get("filed_at") or "")[:10], "url": e.get("sec_url"),
                            "what_changed": filing_change_label(e),
                            "catalyst_type": e.get("catalyst_type")})
            ctx.bundle.add("sec", f"SEC {form} filed", text=f"{str(e.get('filed_at'))[:10]} {filings[-1]['what_changed'] or ''}",
                           source="SEC EDGAR via sec_filings_feed", as_of=e.get("filed_at"), url=e.get("sec_url"))
    form4 = []
    try:
        form4 = _sql(ctx, "SELECT filer_name, filer_relation, transaction_type, total_value, filing_date, sec_url FROM sec_form4 "
                          "WHERE upper(symbol) = %s AND filing_date >= %s ORDER BY filing_date DESC LIMIT 20",
                     (sym, (ctx.now - timedelta(days=90)).date()))
    except Exception:  # noqa: BLE001
        form4 = []
    buys = sum(1 for r in form4 if str(r.get("transaction_type") or "").upper().startswith("P"))
    sells = sum(1 for r in form4 if str(r.get("transaction_type") or "").upper().startswith("S"))
    if form4:
        ctx.bundle.add("sec", "Form 4 insider purchases (90d, count)", value=buys, source="sec_form4 (sec_data_ingest)")
        ctx.bundle.add("sec", "Form 4 insider sales (90d, count)", value=sells, source="sec_form4 (sec_data_ingest)")
        for side, pref in (("purchases", "P"), ("sales", "S")):
            usd = sum(_f(r.get("total_value")) or 0 for r in form4 if str(r.get("transaction_type") or "").upper().startswith(pref))
            ctx.bundle.add("sec", f"Form 4 insider {side} (90d, $)", value=usd, unit="$", source="sec_form4 (sec_data_ingest)")
    try:
        f4ctx = json.loads((ctx.sources.state_root / "data/runtime/sec_form4_momentum_context_latest.json").read_text(encoding="utf-8"))
        rows = f4ctx.get("symbols") or {}
        row = rows.get(sym) if isinstance(rows, dict) else None
        if isinstance(row, dict):
            for k in ("net_value_usd", "buy_value_usd", "sell_value_usd", "net_shares"):
                ctx.bundle.add("sec", f"Form 4 {k.replace('_', ' ')}", value=row.get(k), source="sec_form4_momentum_context",
                               as_of=f4ctx.get("generated_at"))
    except (OSError, ValueError, AttributeError):
        pass
    ipo = [f for f in filings if f["form"] in {"S-1", "S-1/A", "424B4", "424B1"}]
    block = {"filings": filings, "form4_90d": {"buys": buys if form4 else None, "sells": sells if form4 else None,
                                               "rows": form4[:5]},
             "ipo": {"filings": ipo, "lockup_note": "lock-up terms: see the prospectus filing (not parsed by the house)"} if ipo else None,
             "gaps": ([] if filings else ["no SEC filing events for this symbol in sec_filing_events.jsonl"])
             + ["13F holder changes: not in the house"]}
    for b in block["form4_90d"]["rows"]:
        for k, v in list(b.items()):
            b[k] = _iso(v) if hasattr(v, "isoformat") else v
    return events + form4, max((f["filed_at"] for f in filings), default=None), {"sec_filings": block}


def r_counterfactual(ctx: Ctx):
    rows = _jsonl_for(ctx, "data/cio/counterfactual_ledger.jsonl", ctx.bundle.symbol, limit=3)
    for r in rows:
        ctx.bundle.add("lineage", "Counterfactual ledger entry", text=str({k: r.get(k) for k in ("decision", "outcome", "note", "verdict")
                                                                          if r.get(k)})[:300],
                       source="cio/counterfactual_ledger.jsonl", as_of=r.get("at") or r.get("recorded_at"))
    return rows, None, {}


def r_opportunity(ctx: Ctx):
    doc = json.loads((ctx.sources.state_root / "data/cio/cio_opportunity_projection.json").read_text(encoding="utf-8"))
    items = doc.get("items") if isinstance(doc, dict) else None
    row = items.get(ctx.bundle.symbol) if isinstance(items, dict) else next(
        (r for r in items or [] if isinstance(r, dict) and str(r.get("symbol") or "").upper() == ctx.bundle.symbol), None)
    at = (row or {}).get("as_of") or (doc.get("as_of") if isinstance(doc, dict) else None)
    if row:
        # Its "conviction" is an INPUT to the CIO prospect record, not a second conviction: the one canonical value
        # is "CIO conviction (CIO prospect record)" (inputs.assemble). It is never offered to the writer, and
        # rationale sentences quoting it are dropped, so the report cannot print two convictions.
        src = "cio_opportunity_projection.json (input to the CIO prospect record)"
        for k in ("upside_pct", "momentum_score", "rank"):
            ctx.bundle.add("cio", f"Opportunity screen: {k.replace('_', ' ')}", value=row.get(k), source=src, as_of=at)
        for k in ("stance", "technical_condition", "stance_rationale"):
            text = str(row.get(k) or "")
            if k == "stance_rationale":
                text = " ".join(x for x in re.split(r"(?<=[.;!?])\s+", text) if "conviction" not in x.lower())
                text = text if len(re.sub(r"[^A-Za-z0-9]", "", text)) >= 15 else ""  # a stub like "Owned;" says nothing
            if text.strip():
                ctx.bundle.add("cio", f"Opportunity screen: {k.replace('_', ' ')}", text=text[:300], source=src, as_of=at)
    return ([row] if row else []), at, {}


def r_social(ctx: Ctx):
    out = _plib("data_broker.social_feed").get_social_posts(_db(ctx), [ctx.bundle.symbol], lookback_hours=24 * 7)
    row = ((out or {}).get("symbols") or {}).get(ctx.bundle.symbol) or {}
    if row:
        ctx.bundle.add("sentiment", "Social posts, last 7 days (count)", value=row.get("count"), source="social_posts")
        ctx.bundle.add("sentiment", "Social posts flagged bullish (count)", value=row.get("bullish"), source="social_posts")
        ctx.bundle.add("sentiment", "Social posts flagged bearish (count)", value=row.get("bearish"), source="social_posts")
    return ([row] if row.get("count") else []), (out or {}).get("as_of"), {"social": {k: row.get(k) for k in ("count", "bullish", "bearish")}}


def r_yfinance(ctx: Ctx):
    out = _plib("data_broker.yfinance_info").get_info_batch(_db(ctx), [ctx.bundle.symbol])
    row = ((out or {}).get("symbols") or {}).get(ctx.bundle.symbol) or {}
    info = row.get("payload") or row.get("info") or {}
    for k, label in (("enterpriseToEbitda", "EV/EBITDA"), ("revenueGrowth", "Revenue growth (yoy, fraction)"),
                     ("fiveYearAvgDividendYield", "5-year average dividend yield %"), ("heldPercentInstitutions", "Institutional holding (fraction)"),
                     ("shortPercentOfFloat", "Short % of float (fraction)"), ("totalDebt", "Total debt $"), ("ebitda", "EBITDA $")):
        ctx.bundle.add("fundamental", f"{label} (yfinance snapshot)", value=info.get(k), source="yfinance_info_snapshot",
                       as_of=row.get("as_of"))
    return ([info] if info else []), row.get("as_of"), {"yfinance": {k: info.get(k) for k in ("enterpriseToEbitda", "totalDebt", "ebitda", "totalCash")}}


def r_news_sentiment(ctx: Ctx):
    out = _plib("data_broker.news_sentiment").get_sentiment([ctx.bundle.symbol])
    row = ((out or {}).get("symbols") or {}).get(ctx.bundle.symbol) or {}
    if row:
        ctx.bundle.add("sentiment", "News sentiment score (weighted)", value=row.get("weighted_score"), source="news_sentiment (alpha_vantage file)",
                       as_of=row.get("latest_published_at"))
        ctx.bundle.add("sentiment", "News sentiment label", text=row.get("label"), source="news_sentiment", as_of=row.get("latest_published_at"))
    return ([row] if row else []), row.get("latest_published_at"), {"news_sentiment": {k: row.get(k) for k in ("weighted_score", "label", "articles")}}


def r_transcripts(ctx: Ctx):
    rows = _sql(ctx, "SELECT title, channel_name, publish_date, url, left(transcript_text, 350) AS excerpt FROM youtube_transcripts "
                     "WHERE (title ~* %s OR matched_keywords::text ~* %s) AND publish_date >= %s "
                     "ORDER BY publish_date DESC LIMIT 3",
                (rf"\m{ctx.bundle.symbol}\M", rf"\m{ctx.bundle.symbol}\M", (ctx.now - timedelta(days=120)).date()))
    kept, rejected = [], []
    for r in rows:
        why = transcript_rejection(r, ctx.bundle.symbol, ctx.bundle.name, ctx.bundle.context.get("last_earnings_date"))
        if why:
            rejected.append({"title": str(r.get("title") or "")[:120], "reason": why})
            continue
        kept.append(r)
        ctx.bundle.add("earnings_call", f"Transcript: {str(r.get('title') or '')[:80]} ({r.get('channel_name')})",
                       text=str(r.get("excerpt") or "")[:350], source="youtube_transcripts (transcript_processor)",
                       as_of=r.get("publish_date"), url=r.get("url"))
    ctx.bundle.context["transcripts_rejected"] = rejected
    return kept, kept[0].get("publish_date") if kept else None, {}


EARNINGS_CALL_RE = re.compile(r"(?i)\bearnings\s+(?:call|conference)|\bconference\s+call\b|\bQ[1-4]\b[^\n]{0,40}\b(?:call|results|earnings)\b"
                              r"|\b(?:first|second|third|fourth)\s+quarter\b[^\n]{0,40}\b(?:call|results)\b")
#: Words in a company name that say nothing about which issuer it is.
_NAME_STOP = {"inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "company", "ltd", "plc", "holdings", "group",
              "the", "class", "a", "b", "trust", "series", "etf", "fund", "&", "and", "of"}
TRANSCRIPT_MAX_DAYS_FROM_REPORT = 21


def transcript_rejection(row: dict, sym: str, name: str | None, report_date: str | None) -> str | None:
    """None when a transcript row is a real earnings call for this issuer; else why it was rejected.

    Accepted only when the title names the issuer (ticker as a word, or the first distinctive word of its name), reads
    as an earnings call ("earnings call", "conference call", "Q3 … results/call"), and — when the house knows the last
    report date — was published within TRANSCRIPT_MAX_DAYS_FROM_REPORT days of it."""
    title = str(row.get("title") or "")
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z.&'-]+", str(name or "")) if w.lower() not in _NAME_STOP]
    names_issuer = bool(re.search(rf"(?<![A-Za-z0-9$#]){re.escape(sym)}(?![A-Za-z0-9])", title)) or bool(
        words and re.search(rf"(?i)\b{re.escape(words[0])}\b", title))
    if not names_issuer:
        return "title does not name the issuer"
    if not EARNINGS_CALL_RE.search(title):
        return "not an earnings call (title has no earnings-call / quarter marker)"
    if report_date and row.get("publish_date"):
        try:
            pub = datetime.fromisoformat(str(_iso(row["publish_date"]))[:10])
            rep_d = datetime.fromisoformat(str(report_date)[:10])
            if abs((pub - rep_d).days) > TRANSCRIPT_MAX_DAYS_FROM_REPORT:
                return f"published {abs((pub - rep_d).days)} days from the last report date"
        except ValueError:
            pass
    return None


READERS: dict[str, Callable] = {
    "quote_price": r_quote, "technicals": r_technicals, "market_regime": r_regime, "earnings_calendar": r_earnings_calendar,
    "watch_directives": r_watch_directives, "private_company": r_private_company, "macro": r_macro,
    "fundamentals": r_fundamentals, "agent_debate": r_agent_debate, "ai_reports": r_ai_reports,
    "intelligence_research_index": r_research_index, "sec_filing_events": r_sec, "counterfactual_ledger": r_counterfactual,
    "opportunity_assessment": r_opportunity, "social_posts": r_social, "yfinance_info_snapshot": r_yfinance,
    "news_sentiment": r_news_sentiment, "transcripts": r_transcripts,
}


def read_all(ctx: Ctx, mapping: dict[str, dict]) -> dict[str, Any]:
    """Run every mapped reader once; record registry coverage; file one governed gap per empty/stale domain."""
    b = ctx.bundle
    blocks: dict[str, Any] = {}
    seen = {row["source"]: row for row in b.coverage}
    rows_out = []
    for domain, spec in mapping.items():
        if "excluded" in spec:
            rows_out.append({"domain": domain, "status": "not_applicable", "reason": spec["excluded"]})
            continue
        if "covered_by" in spec:
            got = [seen[s] for s in spec["covered_by"] if s in seen]
            status = "used" if any(r["status"] == "used" for r in got) else (
                "stale" if any(r["status"] == "stale" for r in got) else
                "failed" if any(r["status"] == "failed" for r in got) else "empty")
            if domain in {"holdings_accounts", "positions_store"} and b.scope != "holding":
                status = "not_applicable"
            rows_out.append({"domain": domain, "status": status, "as_of": next((r["as_of"] for r in got if r.get("as_of")), None),
                             "reason": "; ".join(f"{r['source']}={r['status']}" for r in got) or "not attempted"})
        else:
            fn = READERS.get(spec.get("reader", domain))
            if fn is None:
                rows_out.append({"domain": domain, "status": "failed", "reason": "no reader wired"})
                continue
            try:
                rows, as_of, upd = fn(ctx)
                blocks.update(upd or {})
                status = "used" if rows else "empty"
                stale_days = spec.get("stale_days")
                if status == "used" and stale_days and as_of:
                    try:
                        at = datetime.fromisoformat(str(as_of).replace("Z", "+00:00")[:25])
                        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
                        if (ctx.now - at).days > int(stale_days):
                            status = "stale"
                    except ValueError:
                        pass
                rows_out.append({"domain": domain, "status": status, "as_of": _iso(as_of), "reason": spec.get("note", "")})
            except Exception as exc:  # noqa: BLE001 - recorded, never fatal
                rows_out.append({"domain": domain, "status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
        row = rows_out[-1]
        if ctx.request_refresh and row["status"] in {"empty", "stale"} and spec.get("refreshable"):
            row["refresh"] = request_gap(domain, b.symbol, row["status"])
    return {"domains": rows_out, "blocks": blocks}


def request_gap(domain: str, sym: str, why: str) -> str:
    """One governed refresh request through the data-gap queue (gap resolver lane); never an ad-hoc fetch."""
    try:
        res = _plib("data_broker.gap_hook").enqueue_gap(domain, sym, f"prospectus: {domain} {why} for {sym}",
                                                        why="stale_hours" if why == "stale" else "missing",
                                                        requester="prospectus_writer")
        return "requested" if isinstance(res, dict) else "not_requested"
    except Exception as exc:  # noqa: BLE001
        return f"not_requested: {type(exc).__name__}"


def options_sentiment_block(b: Bundle, blocks: dict) -> dict:
    iv = next((f for f in b.facts if f["label"] == "Implied volatility %"), None)
    return {"iv_pct": iv.get("value") if iv else None, "iv_rank": None, "put_call": None, "unusual_flow": None,
            "news_sentiment": blocks.get("news_sentiment"), "social": blocks.get("social"),
            "dividend": {"yield_pct": next((f.get("value") for f in b.facts if f["label"] == "Dividend yield %"), None),
                         "annual_per_share": next((f.get("value") for f in b.facts if f["label"] == "Annual dividend per share"), None)},
            "debate": blocks.get("debate"),
            "gaps": ["IV rank and put/call: not in the house", "options flow: provider retired 2026-09-13 (Polygon)"]}


def earnings_call_block(b: Bundle) -> dict:
    rows = [f for f in b.facts if f["kind"] == "earnings_call"]
    rejected = b.context.get("transcripts_rejected") or []
    gap = "no earnings-call transcript for this symbol in the house; the writer may cite web sources"
    if rejected:
        gap += f" ({len(rejected)} video(s) rejected: " + "; ".join(r["reason"] for r in rejected[:3]) + ")"
    return {"transcripts": [{"id": f["id"], "label": f["label"], "as_of": f.get("as_of"), "url": f.get("url")} for f in rows],
            "rejected": rejected[:5], "gaps": [] if rows else [gap]}


def full_assemble(sources: Any, symbol: str, scope: str, *, cfg: dict, holding: dict | None = None,
                  now: datetime | None = None, book: dict | None = None, request_refresh: bool = False) -> Bundle:
    """House inputs + every registry domain + the derived institutional blocks, with registry coverage."""
    from .inputs import assemble
    now = now or datetime.now(timezone.utc)
    b = assemble(sources, symbol, scope, holding=holding, now=now, book=book)
    try:
        bars = sources.bars(b.symbol)
    except Exception:  # noqa: BLE001
        bars = []
    res = read_all(Ctx(sources=sources, bundle=b, now=now, request_refresh=request_refresh, bars=bars or []),
                   cfg.get("registry_domains") or {})
    b.blocks.update({k: v for k, v in res["blocks"].items() if k in {"macro_sensitivity", "sec_filings"}})
    b.blocks["options_sentiment_dividends"] = options_sentiment_block(b, res["blocks"])
    b.blocks["earnings_call"] = earnings_call_block(b)
    if "macro_sensitivity" not in b.blocks:
        b.blocks["macro_sensitivity"] = {"series": {}, "gaps": ["FRED series unavailable"]}
    if "sec_filings" not in b.blocks:
        b.blocks["sec_filings"] = {"filings": [], "gaps": ["SEC filings unavailable"]}
    b.context["registry_coverage"] = res["domains"]
    try:  # house stop policy + broker stop state, read-only (scripts/lib/prospectus/stops.py, PR #2201)
        from .stops import build as stop_plan
    except ImportError:
        b.blocks["stop_plan"] = {"gaps": ["stop plan: scripts/lib/prospectus/stops.py not installed yet"]}
    else:
        b.blocks["stop_plan"] = stop_plan(sources, b, holding=holding, cfg=cfg, now=now)
    return b
